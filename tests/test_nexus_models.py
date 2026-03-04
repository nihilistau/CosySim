"""Tests for engine.nexus.models — Pydantic domain models."""
import json
from datetime import datetime

import pytest

from engine.nexus.models import (
    AgentMemory,
    BenchmarkResult,
    NexusEntry,
    NexusResponse,
    NexusRule,
    NewsArticle,
    NLMAnswer,
    NLMNotebook,
    RouterDecision,
    SessionLog,
    TrainingRun,
)


# ──── NexusEntry backward compat ─────────────────────────────────────────


def test_nexus_entry_dot_get():
    entry = NexusEntry(id="1", title="My note", content="body", created_by="copilot")
    assert entry.get("title") == "My note"
    assert entry.get("content") == "body"
    assert entry.get("missing_key", "default") == "default"
    assert entry.get("missing_key") is None


def test_nexus_entry_getitem():
    entry = NexusEntry(id="1", title="My note", content="body", created_by="copilot")
    assert entry["title"] == "My note"
    assert entry["content"] == "body"


def test_nexus_entry_defaults():
    entry = NexusEntry(id="x", title="T", content="C", created_by="test")
    assert entry.content_type == "note"
    assert entry.category == ""
    assert entry.tags == []
    assert isinstance(entry.created_at, datetime)
    assert entry.updated_at is None


def test_nexus_entry_pydantic_serialisation():
    entry = NexusEntry(id="abc", title="Hello", content="World", created_by="agent")
    data = json.loads(entry.model_dump_json())
    assert data["id"] == "abc"
    assert data["title"] == "Hello"


# ──── NexusRule backward compat ──────────────────────────────────────────


def test_nexus_rule_dot_get():
    rule = NexusRule(rule_id="r1", scope="scene:bedroom", rule_type="access")
    assert rule.get("scope") == "scene:bedroom"
    assert rule.get("nonexistent", "fallback") == "fallback"
    assert rule["rule_type"] == "access"


def test_nexus_rule_defaults():
    rule = NexusRule(rule_id="r1", scope="global", rule_type="governance")
    assert rule.active is True
    assert rule.condition == {}
    assert rule.action == {}


# ──── AgentMemory ─────────────────────────────────────────────────────────


def test_agent_memory_importance_bounds():
    with pytest.raises(Exception):
        AgentMemory(agent_id="a1", content="test", importance=1.5)
    with pytest.raises(Exception):
        AgentMemory(agent_id="a1", content="test", importance=-0.1)


def test_agent_memory_defaults():
    mem = AgentMemory(agent_id="aria", content="player entered room")
    assert mem.memory_type == "observation"
    assert mem.importance == 0.5
    assert mem.tags == []


# ──── v0.83b addition models ─────────────────────────────────────────────


def test_benchmark_result_dot_get():
    br = BenchmarkResult(model="qwen3-0.6b", method="router", score=0.87)
    assert br.get("model") == "qwen3-0.6b"
    assert br["score"] == 0.87


def test_training_run_defaults():
    tr = TrainingRun(run_id="run-1", model_type="router", dataset_path="/data/train.jsonl")
    assert tr.status == "pending"
    assert tr.epochs == 3
    assert tr.lora_r == 16
    assert tr.loss is None


def test_news_article_optional_published():
    article = NewsArticle(url="https://example.com", title="AI news", category="ai")
    assert article.published_at is None
    assert article.tags == []
    assert article.get("category") == "ai"


def test_router_decision_dot_get():
    rd = RouterDecision(request_hash="abc123", chosen_model="copilot-sonnet", confidence=0.95)
    assert rd["chosen_model"] == "copilot-sonnet"
    assert rd.get("confidence") == 0.95


# ──── NexusResponse envelope ─────────────────────────────────────────────


def test_nexus_response_ok():
    resp = NexusResponse(ok=True, data={"count": 5})
    assert resp.ok is True
    assert resp.error is None


def test_nexus_response_error():
    resp = NexusResponse(ok=False, error="not found")
    assert resp.ok is False
    assert resp.error == "not found"
