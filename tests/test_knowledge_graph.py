"""Tests for engine.nexus.knowledge_graph — topic graph and gap detection."""

from __future__ import annotations

import json
from dataclasses import asdict
from unittest.mock import MagicMock, patch

import pytest

from engine.nexus.knowledge_graph import (
    KnowledgeGraph,
    TopicNode,
    KnowledgeGap,
    GraphSnapshot,
    get_knowledge_graph,
)


# ── Fixtures ────────────────────────────────────────────────────────────


@pytest.fixture
def graph():
    """Fresh KnowledgeGraph instance."""
    return KnowledgeGraph()


@pytest.fixture
def sample_entries():
    """Sample Nexus entries for graph building."""
    return [
        {
            "id": "1",
            "title": "MCP Framework Architecture",
            "content": (
                "The MCP framework provides state management for scenes. "
                "MCP nodes form a tree. State is persisted via the framework. "
                "The framework supports skills and interceptors."
            ),
            "category": "architecture",
            "tags": ["mcp", "framework", "architecture"],
        },
        {
            "id": "2",
            "title": "MCP Skills System",
            "content": (
                "Skills are registered via the @skill decorator. "
                "The skill registry manages all skills. Skills can have "
                "cooldowns, costs, and prerequisites. MCP tools expose skills."
            ),
            "category": "architecture",
            "tags": ["mcp", "skills", "decorator"],
        },
        {
            "id": "3",
            "title": "Interceptor Pipeline",
            "content": (
                "Interceptors modify LLM requests and responses. "
                "The pipeline runs pre_call and post_call hooks. "
                "Interceptors inject system prompts and extract tags."
            ),
            "category": "architecture",
            "tags": ["interceptor", "pipeline", "llm"],
        },
        {
            "id": "4",
            "title": "LMStudio Integration",
            "content": (
                "LMStudio provides inference via the v1 API. "
                "Models are loaded and managed dynamically. "
                "The orchestrator routes between model profiles."
            ),
            "category": "infrastructure",
            "tags": ["lmstudio", "inference", "models"],
        },
        {
            "id": "5",
            "title": "Nexus Knowledge System",
            "content": (
                "Nexus stores knowledge, Q&A pairs, and rules. "
                "The query router checks cache before calling LLM. "
                "Knowledge entries have quality scores."
            ),
            "category": "infrastructure",
            "tags": ["nexus", "knowledge", "cache"],
        },
        {
            "id": "6",
            "title": "MCP State Persistence",
            "content": (
                "MCP framework state is persisted to disk. "
                "State includes scene nodes, character data, and timers. "
                "The framework auto-saves on shutdown."
            ),
            "category": "architecture",
            "tags": ["mcp", "state", "persistence"],
        },
    ]


# ── Data Model Tests ────────────────────────────────────────────────────


class TestTopicNode:
    """Test TopicNode dataclass."""

    def test_create_node(self):
        """Basic node creation."""
        node = TopicNode(name="mcp", entry_count=5)
        assert node.name == "mcp"
        assert node.entry_count == 5
        assert node.entry_ids == []
        assert node.related_topics == {}

    def test_node_with_relations(self):
        """Node with related topics."""
        node = TopicNode(
            name="skills",
            entry_count=3,
            related_topics={"mcp": 2, "decorator": 1},
        )
        assert node.related_topics["mcp"] == 2


class TestKnowledgeGap:
    """Test KnowledgeGap dataclass."""

    def test_create_gap(self):
        """Basic gap creation."""
        gap = KnowledgeGap(
            topic="testing",
            entry_count=1,
            related_strong_topics=["mcp", "skills"],
            suggested_research="Research testing in the context of mcp, skills.",
            priority="high",
        )
        assert gap.topic == "testing"
        assert gap.priority == "high"

    def test_gap_asdict(self):
        """asdict serialization."""
        gap = KnowledgeGap(
            topic="auth",
            entry_count=0,
            related_strong_topics=["api"],
            suggested_research="Research auth.",
            priority="medium",
        )
        d = asdict(gap)
        assert d["topic"] == "auth"


class TestGraphSnapshot:
    """Test GraphSnapshot dataclass."""

    def test_create_snapshot(self):
        """Basic snapshot creation."""
        snap = GraphSnapshot(
            topic_count=10,
            edge_count=15,
            gap_count=3,
            top_topics=[],
            gaps=[],
            clusters=[],
            created_at="2024-01-01",
        )
        assert snap.topic_count == 10


# ── Topic Extraction ───────────────────────────────────────────────────


class TestTopicExtraction:
    """Test keyword extraction from entries."""

    def test_extracts_from_tags(self, graph):
        """Tags become topics."""
        topics = graph._extract_topics("", "", ["python", "testing", "api"])
        assert "python" in topics
        assert "testing" in topics
        assert "api" in topics

    def test_extracts_from_title(self, graph):
        """Title words become topics."""
        topics = graph._extract_topics("MCP Framework Architecture", "", [])
        assert "framework" in topics
        assert "architecture" in topics

    def test_filters_stop_words(self, graph):
        """Stop words are filtered out."""
        topics = graph._extract_topics("The Quick Brown Fox", "", [])
        assert "the" not in topics
        assert "quick" in topics

    def test_filters_short_words(self, graph):
        """Words shorter than 3 chars are filtered."""
        topics = graph._extract_topics("AI ML DL Testing", "", [])
        assert "testing" in topics
        # "ai", "ml", "dl" are 2 chars — should be filtered
        assert "ai" not in topics

    def test_extracts_frequent_content_words(self, graph):
        """Content words appearing 2+ times become topics."""
        content = "The framework manages state. Framework also handles events. Framework is core."
        topics = graph._extract_topics("", content, [])
        assert "framework" in topics

    def test_deduplicates(self, graph):
        """Same word from multiple sources appears once."""
        topics = graph._extract_topics("framework", "framework framework", ["framework"])
        assert topics.count("framework") == 1


# ── Graph Building ─────────────────────────────────────────────────────


class TestGraphBuilding:
    """Test graph construction from entries."""

    def test_build_from_entries(self, graph, sample_entries):
        """Building from sample entries creates topics."""
        snap = graph.build(sample_entries)
        assert snap.topic_count > 0
        assert snap.created_at != ""

    def test_build_creates_edges(self, graph, sample_entries):
        """Co-occurring topics have edges."""
        snap = graph.build(sample_entries)
        assert snap.edge_count > 0

    def test_mcp_is_common_topic(self, graph, sample_entries):
        """MCP should be a top topic (appears in 3+ entries)."""
        graph.build(sample_entries)
        topic = graph.get_topic("mcp")
        assert topic is not None
        assert topic["entry_count"] >= 3

    def test_prune_removes_infrequent(self, graph):
        """Topics with < 2 entries are pruned."""
        entries = [
            {"id": "1", "title": "Unique Topic Only Here", "content": "x", "tags": ["raretopic"]},
        ]
        snap = graph.build(entries)
        assert graph.get_topic("raretopic") is None

    def test_empty_entries(self, graph):
        """Building with empty list gives empty graph."""
        snap = graph.build([])
        assert snap.topic_count == 0
        assert snap.edge_count == 0

    def test_rebuild_clears_previous(self, graph, sample_entries):
        """Rebuilding clears the previous graph."""
        graph.build(sample_entries)
        count1 = len(graph._topics)
        graph.build([])
        assert len(graph._topics) == 0


# ── Gap Detection ──────────────────────────────────────────────────────


class TestGapDetection:
    """Test knowledge gap detection."""

    def test_detects_gaps(self, graph):
        """Topics with 1 entry neighbor to strong topics are gaps."""
        graph._topics = {
            "mcp": TopicNode(name="mcp", entry_count=10, related_topics={"testing": 1}),
            "testing": TopicNode(name="testing", entry_count=1, related_topics={"mcp": 1}),
        }
        gaps = graph.detect_gaps(threshold=2)
        assert len(gaps) >= 1
        assert gaps[0].topic == "testing"

    def test_no_gaps_when_all_strong(self, graph):
        """No gaps when all topics have sufficient entries."""
        graph._topics = {
            "mcp": TopicNode(name="mcp", entry_count=10),
            "nexus": TopicNode(name="nexus", entry_count=8),
        }
        gaps = graph.detect_gaps(threshold=2)
        assert len(gaps) == 0

    def test_gap_priority(self, graph):
        """Single-entry topics get high priority."""
        graph._topics = {
            "mcp": TopicNode(name="mcp", entry_count=10, related_topics={"orphan": 1}),
            "orphan": TopicNode(name="orphan", entry_count=1, related_topics={"mcp": 1}),
        }
        gaps = graph.detect_gaps()
        assert gaps[0].priority == "high"

    def test_isolated_weak_topics_not_gaps(self, graph):
        """Weak topics without strong neighbors are not gaps."""
        graph._topics = {
            "weak1": TopicNode(name="weak1", entry_count=1, related_topics={"weak2": 1}),
            "weak2": TopicNode(name="weak2", entry_count=1, related_topics={"weak1": 1}),
        }
        gaps = graph.detect_gaps()
        assert len(gaps) == 0


# ── Clustering ─────────────────────────────────────────────────────────


class TestClustering:
    """Test topic clustering."""

    def test_clusters_connected_topics(self, graph):
        """Co-occurring topics form clusters."""
        graph._topics = {
            "mcp": TopicNode(name="mcp", entry_count=5, related_topics={"skills": 3, "state": 2}),
            "skills": TopicNode(name="skills", entry_count=4, related_topics={"mcp": 3}),
            "state": TopicNode(name="state", entry_count=3, related_topics={"mcp": 2}),
            "nexus": TopicNode(name="nexus", entry_count=5, related_topics={"cache": 3}),
            "cache": TopicNode(name="cache", entry_count=3, related_topics={"nexus": 3}),
        }
        clusters = graph.cluster_topics(min_overlap=2)
        assert len(clusters) >= 2

    def test_no_clusters_with_high_threshold(self, graph):
        """High overlap threshold prevents clustering."""
        graph._topics = {
            "a": TopicNode(name="a", entry_count=5, related_topics={"b": 1}),
            "b": TopicNode(name="b", entry_count=3, related_topics={"a": 1}),
        }
        clusters = graph.cluster_topics(min_overlap=5)
        assert len(clusters) == 0

    def test_cluster_total_entries(self, graph):
        """Clusters track total entry count."""
        graph._topics = {
            "x": TopicNode(name="x", entry_count=10, related_topics={"y": 5}),
            "y": TopicNode(name="y", entry_count=8, related_topics={"x": 5}),
        }
        clusters = graph.cluster_topics(min_overlap=2)
        if clusters:
            assert clusters[0]["total_entries"] == 18


# ── Search and Lookup ──────────────────────────────────────────────────


class TestSearchAndLookup:
    """Test topic search and individual lookup."""

    def test_get_existing_topic(self, graph):
        """Lookup returns details for existing topic."""
        graph._topics["mcp"] = TopicNode(
            name="mcp", entry_count=5,
            entry_ids=["1", "2"],
            related_topics={"skills": 3},
            categories=["architecture"],
        )
        result = graph.get_topic("mcp")
        assert result is not None
        assert result["entry_count"] == 5
        assert "skills" in result["related_topics"]

    def test_get_nonexistent_topic(self, graph):
        """Lookup returns None for missing topic."""
        assert graph.get_topic("nonexistent") is None

    def test_search_topics(self, graph):
        """Search matches topic name substrings."""
        graph._topics = {
            "mcp_framework": TopicNode(name="mcp_framework", entry_count=5),
            "mcp_skills": TopicNode(name="mcp_skills", entry_count=3),
            "nexus": TopicNode(name="nexus", entry_count=4),
        }
        results = graph.search_topics("mcp")
        assert len(results) == 2
        assert results[0]["name"] == "mcp_framework"  # Sorted by count

    def test_search_no_matches(self, graph):
        """Search with no matches returns empty."""
        graph._topics = {"mcp": TopicNode(name="mcp", entry_count=1)}
        assert graph.search_topics("zzz") == []


# ── Task Creation ──────────────────────────────────────────────────────


class TestTaskCreation:
    """Test research task generation from gaps."""

    @patch("engine.nexus.task_scheduler.get_task_scheduler")
    def test_creates_tasks_for_gaps(self, mock_scheduler, graph):
        """Tasks are created for detected gaps."""
        scheduler = MagicMock()
        mock_scheduler.return_value = scheduler

        graph._topics = {
            "mcp": TopicNode(name="mcp", entry_count=10, related_topics={"testing": 1}),
            "testing": TopicNode(name="testing", entry_count=1, related_topics={"mcp": 1}),
        }
        tasks = graph.create_research_tasks()
        assert len(tasks) >= 1
        scheduler.add_task.assert_called()

    def test_no_gaps_no_tasks(self, graph):
        """No gaps means no tasks."""
        graph._topics = {
            "mcp": TopicNode(name="mcp", entry_count=10),
        }
        tasks = graph.create_research_tasks()
        assert tasks == []

    @patch("engine.nexus.task_scheduler.get_task_scheduler")
    def test_max_five_tasks(self, mock_scheduler, graph):
        """At most 5 research tasks created."""
        scheduler = MagicMock()
        mock_scheduler.return_value = scheduler

        graph._topics = {
            "strong": TopicNode(
                name="strong", entry_count=20,
                related_topics={f"weak{i}": 1 for i in range(10)}
            ),
        }
        for i in range(10):
            graph._topics[f"weak{i}"] = TopicNode(
                name=f"weak{i}", entry_count=1,
                related_topics={"strong": 1},
            )

        tasks = graph.create_research_tasks()
        assert scheduler.add_task.call_count <= 5


# ── Nexus Integration ─────────────────────────────────────────────────


class TestNexusIntegration:
    """Test Nexus storage."""

    @patch("engine.nexus.client.get_nexus_client")
    def test_store_snapshot(self, mock_client, graph, sample_entries):
        """Snapshot is stored in Nexus."""
        client = MagicMock()
        mock_client.return_value = client

        graph.build(sample_entries)
        graph.store_snapshot()
        client.add_entry.assert_called_once()

    def test_store_handles_failure(self, graph):
        """Storage failure doesn't raise."""
        graph.build([])
        graph.store_snapshot()  # Should not raise


# ── Snapshot ───────────────────────────────────────────────────────────


class TestSnapshot:
    """Test graph snapshot generation."""

    def test_snapshot_structure(self, graph, sample_entries):
        """Snapshot has expected fields."""
        snap = graph.build(sample_entries)
        assert isinstance(snap.topic_count, int)
        assert isinstance(snap.edge_count, int)
        assert isinstance(snap.gap_count, int)
        assert isinstance(snap.top_topics, list)
        assert isinstance(snap.gaps, list)
        assert isinstance(snap.clusters, list)

    def test_snapshot_empty_graph(self, graph):
        """Empty graph produces valid snapshot."""
        snap = graph.snapshot()
        assert snap.topic_count == 0


# ── Singleton ──────────────────────────────────────────────────────────


class TestSingleton:
    """Test singleton pattern."""

    def test_singleton(self):
        """get_knowledge_graph returns same instance."""
        import engine.nexus.knowledge_graph as mod
        mod._instance = None
        g1 = get_knowledge_graph()
        g2 = get_knowledge_graph()
        assert g1 is g2
        mod._instance = None
