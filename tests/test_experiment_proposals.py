"""Tests for engine.nexus.experiment_proposals — auto-propose experiments."""

from __future__ import annotations

import json
from dataclasses import asdict
from unittest.mock import MagicMock, patch

import pytest

from engine.nexus.experiment_proposals import (
    ExperimentProposal,
    ExperimentProposer,
    EXPERIMENT_TEMPLATES,
    get_experiment_proposer,
)


# ── Fixtures ────────────────────────────────────────────────────────────


@pytest.fixture
def proposer():
    """Fresh ExperimentProposer instance."""
    return ExperimentProposer()


# ── Data Model Tests ────────────────────────────────────────────────────


class TestExperimentProposal:
    """Test ExperimentProposal dataclass."""

    def test_create_proposal(self):
        """Basic proposal creation."""
        p = ExperimentProposal(
            proposal_id="test-1",
            trigger_metric="llm.cache.hit_rate",
            trigger_value=0.2,
            hypothesis="Caching will help",
            experiment_name="cache-test",
            variants=[{"id": "a"}, {"id": "b"}],
            success_metric="llm.cache.hit_rate",
            success_threshold=0.5,
            priority="high",
        )
        assert p.proposal_id == "test-1"
        assert p.experiment_id is None
        assert p.auto_run is False

    def test_proposal_asdict(self):
        """asdict serialization."""
        p = ExperimentProposal(
            proposal_id="test-2",
            trigger_metric="speed",
            trigger_value=100,
            hypothesis="Faster",
            experiment_name="speed-test",
            variants=[],
            success_metric="speed",
            success_threshold=50,
            priority="medium",
        )
        d = asdict(p)
        assert d["proposal_id"] == "test-2"
        assert "experiment_id" in d


# ── Templates ──────────────────────────────────────────────────────────


class TestTemplates:
    """Test experiment template definitions."""

    def test_templates_exist(self):
        """At least 3 templates defined."""
        assert len(EXPERIMENT_TEMPLATES) >= 3

    def test_all_templates_have_required_fields(self):
        """Every template has required fields."""
        required = {
            "trigger_metric", "condition", "threshold",
            "hypothesis", "experiment_name", "variants",
            "success_metric", "success_threshold",
        }
        for name, template in EXPERIMENT_TEMPLATES.items():
            for field in required:
                assert field in template, f"{name} missing {field}"

    def test_all_templates_have_variants(self):
        """Every template has at least 2 variants."""
        for name, template in EXPERIMENT_TEMPLATES.items():
            assert len(template["variants"]) >= 2, f"{name} needs more variants"

    def test_cache_template(self):
        """Cache hit rate template specifics."""
        t = EXPERIMENT_TEMPLATES["cache_hit_rate_low"]
        assert t["trigger_metric"] == "llm.cache.hit_rate"
        assert t["condition"] == "below"
        assert t["threshold"] == 0.4

    def test_inference_template(self):
        """Inference latency template specifics."""
        t = EXPERIMENT_TEMPLATES["inference_slow"]
        assert t["trigger_metric"] == "llm.latency.avg_ms"
        assert t["condition"] == "above"


# ── Scan and Propose ───────────────────────────────────────────────────


class TestScanAndPropose:
    """Test the metric scanning and proposal generation."""

    def test_no_metrics_no_proposals(self, proposer):
        """No metric data means no proposals."""
        with patch.object(proposer, "_get_current_metrics", return_value={}):
            proposals = proposer.scan_and_propose()
        assert proposals == []

    def test_below_threshold_triggers(self, proposer):
        """Metric below threshold triggers proposal."""
        with patch.object(proposer, "_get_current_metrics", return_value={
            "llm.cache.hit_rate": 0.2,
        }):
            proposals = proposer.scan_and_propose()
        matching = [p for p in proposals if p.experiment_name == "cache-hit-optimization"]
        assert len(matching) == 1
        assert matching[0].trigger_value == 0.2
        assert matching[0].priority == "high"

    def test_above_threshold_triggers(self, proposer):
        """Metric above threshold triggers proposal."""
        with patch.object(proposer, "_get_current_metrics", return_value={
            "llm.latency.avg_ms": 8000,
        }):
            proposals = proposer.scan_and_propose()
        matching = [p for p in proposals if p.experiment_name == "inference-latency-reduction"]
        assert len(matching) == 1

    def test_within_threshold_no_trigger(self, proposer):
        """Metric within threshold does not trigger."""
        with patch.object(proposer, "_get_current_metrics", return_value={
            "llm.cache.hit_rate": 0.6,
            "llm.latency.avg_ms": 2000,
        }):
            proposals = proposer.scan_and_propose()
        assert proposals == []

    def test_multiple_triggers(self, proposer):
        """Multiple metrics can trigger multiple proposals."""
        with patch.object(proposer, "_get_current_metrics", return_value={
            "llm.cache.hit_rate": 0.1,
            "llm.latency.avg_ms": 10000,
            "tasks.agent_error_rate": 0.5,
        }):
            proposals = proposer.scan_and_propose()
        assert len(proposals) >= 3

    def test_proposals_stored_in_history(self, proposer):
        """Proposals are tracked in internal history."""
        with patch.object(proposer, "_get_current_metrics", return_value={
            "llm.cache.hit_rate": 0.1,
        }):
            proposer.scan_and_propose()
        assert len(proposer._proposals) >= 1


# ── Create Experiment ──────────────────────────────────────────────────


class TestCreateExperiment:
    """Test creating experiments from proposals."""

    @patch("engine.nexus.experiment_framework.get_experiment_runner")
    @patch("engine.nexus.experiment_proposals.ExperimentProposer._store_proposal")
    def test_create_from_proposal(self, mock_store, mock_runner, proposer):
        """Creating experiment from proposal calls ExperimentRunner."""
        runner = MagicMock()
        runner.create.return_value = {"id": "exp-123"}
        mock_runner.return_value = runner

        proposal = ExperimentProposal(
            proposal_id="p-1",
            trigger_metric="llm.cache.hit_rate",
            trigger_value=0.2,
            hypothesis="Caching will help",
            experiment_name="cache-test",
            variants=[{"id": "a"}, {"id": "b"}],
            success_metric="llm.cache.hit_rate",
            success_threshold=0.5,
            priority="high",
        )

        result = proposer.create_experiment(proposal)
        assert result is not None
        assert result["id"] == "exp-123"
        assert proposal.experiment_id == "exp-123"
        runner.create.assert_called_once()
        mock_store.assert_called_once()

    @patch("engine.nexus.experiment_framework.get_experiment_runner")
    def test_create_handles_failure(self, mock_runner, proposer):
        """Failure to create experiment returns None."""
        runner = MagicMock()
        runner.create.side_effect = RuntimeError("Experiment creation failed")
        mock_runner.return_value = runner

        proposal = ExperimentProposal(
            proposal_id="p-2",
            trigger_metric="test",
            trigger_value=0,
            hypothesis="Test",
            experiment_name="test",
            variants=[],
            success_metric="test",
            success_threshold=0,
            priority="low",
        )
        result = proposer.create_experiment(proposal)
        assert result is None


# ── Get Proposals ──────────────────────────────────────────────────────


class TestGetProposals:
    """Test proposal retrieval and filtering."""

    def test_empty_history(self, proposer):
        """No proposals returns empty list."""
        assert proposer.get_proposals() == []

    def test_filter_pending(self, proposer):
        """Filter for pending (no experiment_id) proposals."""
        proposer._proposals = [
            ExperimentProposal(
                proposal_id="p-1", trigger_metric="x", trigger_value=0,
                hypothesis="h", experiment_name="e", variants=[],
                success_metric="x", success_threshold=0, priority="low",
            ),
            ExperimentProposal(
                proposal_id="p-2", trigger_metric="x", trigger_value=0,
                hypothesis="h", experiment_name="e", variants=[],
                success_metric="x", success_threshold=0, priority="low",
                experiment_id="exp-1",
            ),
        ]
        pending = proposer.get_proposals(status="pending")
        assert len(pending) == 1
        assert pending[0]["proposal_id"] == "p-1"

    def test_filter_active(self, proposer):
        """Filter for active (has experiment_id) proposals."""
        proposer._proposals = [
            ExperimentProposal(
                proposal_id="p-1", trigger_metric="x", trigger_value=0,
                hypothesis="h", experiment_name="e", variants=[],
                success_metric="x", success_threshold=0, priority="low",
            ),
            ExperimentProposal(
                proposal_id="p-2", trigger_metric="x", trigger_value=0,
                hypothesis="h", experiment_name="e", variants=[],
                success_metric="x", success_threshold=0, priority="low",
                experiment_id="exp-1",
            ),
        ]
        active = proposer.get_proposals(status="active")
        assert len(active) == 1
        assert active[0]["proposal_id"] == "p-2"

    def test_no_filter_returns_all(self, proposer):
        """No filter returns all proposals."""
        proposer._proposals = [
            ExperimentProposal(
                proposal_id=f"p-{i}", trigger_metric="x", trigger_value=0,
                hypothesis="h", experiment_name="e", variants=[],
                success_metric="x", success_threshold=0, priority="low",
            )
            for i in range(5)
        ]
        assert len(proposer.get_proposals()) == 5


# ── List Templates ─────────────────────────────────────────────────────


class TestListTemplates:
    """Test template listing."""

    def test_list_templates(self, proposer):
        """List returns template summaries."""
        templates = proposer.list_templates()
        assert len(templates) >= 3
        for t in templates:
            assert "name" in t
            assert "trigger_metric" in t
            assert "condition" in t
            assert "variant_count" in t

    def test_custom_template(self, proposer):
        """Custom templates appear in listing."""
        proposer.add_template("custom_test", {
            "trigger_metric": "custom.metric",
            "condition": "above",
            "threshold": 100,
            "hypothesis": "Custom hypothesis",
            "experiment_name": "custom-experiment",
            "variants": [{"id": "a"}, {"id": "b"}],
            "success_metric": "custom.metric",
            "success_threshold": 50,
            "priority": "low",
        })
        names = [t["name"] for t in proposer.list_templates()]
        assert "custom_test" in names


# ── Nexus Storage ──────────────────────────────────────────────────────


class TestNexusStorage:
    """Test proposal storage in Nexus."""

    @patch("engine.nexus.client.get_nexus_client")
    def test_store_proposal(self, mock_client, proposer):
        """Proposal is stored in Nexus."""
        client = MagicMock()
        mock_client.return_value = client

        proposal = ExperimentProposal(
            proposal_id="p-1",
            trigger_metric="llm.cache.hit_rate",
            trigger_value=0.2,
            hypothesis="Test hypothesis",
            experiment_name="test-exp",
            variants=[{"id": "a"}],
            success_metric="llm.cache.hit_rate",
            success_threshold=0.5,
            priority="high",
            experiment_id="exp-1",
        )
        proposer._store_proposal(proposal)
        client.add_entry.assert_called_once()

    def test_store_failure_handled(self, proposer):
        """Storage failure doesn't raise."""
        proposal = ExperimentProposal(
            proposal_id="p-1",
            trigger_metric="x",
            trigger_value=0,
            hypothesis="h",
            experiment_name="e",
            variants=[],
            success_metric="x",
            success_threshold=0,
            priority="low",
        )
        # Should not raise even without Nexus
        proposer._store_proposal(proposal)


# ── Singleton ──────────────────────────────────────────────────────────


class TestSingleton:
    """Test singleton pattern."""

    def test_singleton(self):
        """get_experiment_proposer returns same instance."""
        import engine.nexus.experiment_proposals as mod
        mod._instance = None
        p1 = get_experiment_proposer()
        p2 = get_experiment_proposer()
        assert p1 is p2
        mod._instance = None
