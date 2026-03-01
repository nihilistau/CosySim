"""Tests for engine.nexus.local_agent_bridge."""
from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from engine.nexus.local_agent_bridge import (
    LocalAgentBridge,
    _build_context_summary,
    _build_execution_steps,
    get_local_agent_bridge,
)


# ── Fixtures ──────────────────────────────────────────────────────────────

@pytest.fixture
def bridge():
    """Fresh LocalAgentBridge instance with mocked internals."""
    b = LocalAgentBridge()
    b._scheduler = _make_mock_scheduler()
    b._nexus = _make_mock_nexus()
    return b


def _make_mock_scheduler():
    sched = MagicMock()
    task1 = MagicMock()
    task1.to_dict.return_value = {
        "id": "abc1234",
        "title": "Add lounge skill",
        "description": "Create ambient_music skill",
        "complexity": "low",
        "priority": 2,
        "status": "pending",
        "allowed_operations": ["read", "edit", "test"],
        "target_files": ["content/scenes/lounge/lounge_skills.py"],
        "tags": ["skills", "lounge"],
        "created_at": 1000.0,
    }
    task2 = MagicMock()
    task2.to_dict.return_value = {
        "id": "def5678",
        "title": "Fix auth bug",
        "description": "Auth endpoint returns 500",
        "complexity": "medium",
        "priority": 1,
        "status": "pending",
        "allowed_operations": ["read", "edit", "test"],
        "target_files": ["engine/auth.py"],
        "tags": ["bug", "auth"],
        "created_at": 900.0,
    }
    task3 = MagicMock()
    task3.to_dict.return_value = {
        "id": "ghi9012",
        "title": "Architecture review",
        "description": "Review MCP state design",
        "complexity": "high",
        "priority": 0,
        "status": "pending",
        "allowed_operations": ["read"],
        "target_files": [],
        "tags": ["architecture"],
        "created_at": 800.0,
    }
    sched.get_pending_tasks.return_value = [task1, task2, task3]
    sched.claim_task_by_id.side_effect = lambda tid, aid: task1 if tid == "abc1234" else None
    sched.get_task.side_effect = lambda tid: task1 if tid == "abc1234" else None
    sched.complete_task.side_effect = lambda tid, result, files_changed=None: task1 if tid == "abc1234" else None
    sched.fail_task.side_effect = lambda tid, reason, retry=False: task1 if tid == "abc1234" else None
    return sched


def _make_mock_nexus():
    nexus = MagicMock()
    nexus.search.return_value = [
        {"title": "Lounge scene docs", "content": "The lounge scene uses Flask.", "content_type": "document"},
        {"title": "Skill decorator guide", "content": "@skill decorator wraps functions.", "content_type": "note"},
    ]
    nexus.get_rules.return_value = [{"rule_text": "Use absolute imports."}, {"rule_text": "Add type hints."}]
    nexus.add_entry.return_value = {"id": "nexus-entry-123"}
    nexus.add_qa.return_value = {"id": "qa-456"}
    return nexus


# ── get_ready_tasks ───────────────────────────────────────────────────────

def test_get_ready_tasks_worker_returns_low_and_medium(bridge):
    tasks = bridge.get_ready_tasks(model_size="worker", limit=10)
    complexities = {t["complexity"] for t in tasks}
    assert "high" not in complexities
    assert "low" in complexities or "medium" in complexities


def test_get_ready_tasks_expert_includes_high(bridge):
    tasks = bridge.get_ready_tasks(model_size="expert", limit=10)
    complexities = {t["complexity"] for t in tasks}
    assert "high" in complexities


def test_get_ready_tasks_mini_only_low(bridge):
    tasks = bridge.get_ready_tasks(model_size="mini", limit=10)
    for t in tasks:
        assert t["complexity"] == "low"


def test_get_ready_tasks_respects_limit(bridge):
    tasks = bridge.get_ready_tasks(model_size="expert", limit=1)
    assert len(tasks) <= 1


def test_get_ready_tasks_sorted_by_priority(bridge):
    tasks = bridge.get_ready_tasks(model_size="expert", limit=10)
    priorities = [t["priority"] for t in tasks]
    assert priorities == sorted(priorities)


def test_get_ready_tasks_tag_filter(bridge):
    tasks = bridge.get_ready_tasks(model_size="expert", tags=["architecture"])
    titles = [t["title"] for t in tasks]
    assert any("Architecture" in t for t in titles)


def test_get_ready_tasks_tag_filter_excludes_unmatched(bridge):
    tasks = bridge.get_ready_tasks(model_size="expert", tags=["nonexistent_tag_xyz"])
    assert tasks == []


def test_get_ready_tasks_router_only_low(bridge):
    tasks = bridge.get_ready_tasks(model_size="router", limit=10)
    for t in tasks:
        assert t["complexity"] == "low"


# ── claim_task ────────────────────────────────────────────────────────────

def test_claim_task_success(bridge):
    result = bridge.claim_task("abc1234", "worker-agent-1")
    assert result["id"] == "abc1234"
    bridge._scheduler.claim_task_by_id.assert_called_once_with("abc1234", "worker-agent-1")


def test_claim_task_not_found(bridge):
    result = bridge.claim_task("not-exist", "agent-1")
    assert "error" in result


def test_claim_task_scheduler_exception(bridge):
    bridge._scheduler.claim_task_by_id.side_effect = RuntimeError("DB error")
    result = bridge.claim_task("abc1234", "agent-1")
    assert "error" in result


# ── get_task_context ──────────────────────────────────────────────────────

def test_get_task_context_returns_task(bridge):
    ctx = bridge.get_task_context("abc1234")
    assert "task" in ctx
    assert ctx["task"]["id"] == "abc1234"


def test_get_task_context_includes_nexus_knowledge(bridge):
    ctx = bridge.get_task_context("abc1234")
    assert "nexus_knowledge" in ctx
    assert len(ctx["nexus_knowledge"]) > 0


def test_get_task_context_includes_coding_rules(bridge):
    ctx = bridge.get_task_context("abc1234")
    assert "coding_rules" in ctx


def test_get_task_context_includes_execution_steps(bridge):
    ctx = bridge.get_task_context("abc1234")
    assert "execution_steps" in ctx
    assert isinstance(ctx["execution_steps"], list)
    assert len(ctx["execution_steps"]) > 0


def test_get_task_context_includes_summary(bridge):
    ctx = bridge.get_task_context("abc1234")
    assert "context_summary" in ctx
    assert "abc1234" in ctx["context_summary"] or "lounge" in ctx["context_summary"].lower()


def test_get_task_context_not_found(bridge):
    ctx = bridge.get_task_context("not-exist")
    assert "error" in ctx


def test_get_task_context_searches_nexus_with_task_info(bridge):
    bridge.get_task_context("abc1234")
    assert bridge._nexus.search.call_count >= 1


def test_get_task_context_knowledge_truncated(bridge):
    # Knowledge entries should have content capped at 500 chars
    ctx = bridge.get_task_context("abc1234")
    for k in ctx["nexus_knowledge"]:
        assert len(k["content"]) <= 500


def test_get_task_context_scheduler_error(bridge):
    bridge._scheduler.get_task.side_effect = RuntimeError("fail")
    ctx = bridge.get_task_context("abc1234")
    assert "error" in ctx


# ── complete_task ─────────────────────────────────────────────────────────

def test_complete_task_returns_completed(bridge):
    result = bridge.complete_task("abc1234", "Done — 3 skills added.")
    assert result["status"] == "completed"


def test_complete_task_stores_in_nexus(bridge):
    bridge.complete_task("abc1234", "Done.", store_to_nexus=True)
    bridge._nexus.add_entry.assert_called_once()
    call_kwargs = bridge._nexus.add_entry.call_args
    args = call_kwargs[1] if call_kwargs[1] else {}
    if not args:
        args = {k: v for k, v in zip(["title", "content", "content_type", "category"],
                                      call_kwargs[0])}


def test_complete_task_skips_nexus_if_disabled(bridge):
    bridge.complete_task("abc1234", "Done.", store_to_nexus=False)
    bridge._nexus.add_entry.assert_not_called()


def test_complete_task_includes_files_changed(bridge):
    bridge.complete_task("abc1234", "Done.", files_changed=["engine/auth.py"])
    args = bridge._nexus.add_entry.call_args
    content_arg = args[0][1] if args[0] else args[1].get("content", "")
    assert "engine/auth.py" in content_arg


def test_complete_task_not_found(bridge):
    result = bridge.complete_task("not-exist", "Done.")
    assert "error" in result


# ── fail_task ─────────────────────────────────────────────────────────────

def test_fail_task_returns_failed(bridge):
    result = bridge.fail_task("abc1234", "Model context overflow.")
    assert result["status"] == "failed"


def test_fail_task_retry_returns_pending(bridge):
    result = bridge.fail_task("abc1234", "Temp error.", retry=True)
    assert result["status"] == "pending"


def test_fail_task_includes_reason(bridge):
    result = bridge.fail_task("abc1234", "Stack overflow.")
    assert result["reason"] == "Stack overflow."


def test_fail_task_not_found(bridge):
    result = bridge.fail_task("not-exist", "reason")
    assert "error" in result


# ── get_agent_manifest ────────────────────────────────────────────────────

def test_get_agent_manifest_worker(bridge):
    manifest = bridge.get_agent_manifest("worker")
    assert "WORKER" in manifest
    assert "Nexus" in manifest
    assert "low" in manifest or "medium" in manifest


def test_get_agent_manifest_expert(bridge):
    manifest = bridge.get_agent_manifest("expert")
    assert "EXPERT" in manifest
    assert "high" in manifest


def test_get_agent_manifest_contains_workflow(bridge):
    manifest = bridge.get_agent_manifest("mini")
    assert "get_ready_tasks" in manifest
    assert "claim_task" in manifest
    assert "complete_task" in manifest


def test_get_agent_manifest_contains_nexus_instructions(bridge):
    manifest = bridge.get_agent_manifest("worker")
    assert "Nexus" in manifest


# ── helpers ───────────────────────────────────────────────────────────────

def test_build_execution_steps_includes_test_step():
    task = {"allowed_operations": ["read", "edit", "test"], "target_files": []}
    steps = _build_execution_steps(task)
    combined = " ".join(steps)
    assert "pytest" in combined or "test" in combined.lower()


def test_build_execution_steps_no_edit_skips_implement():
    task = {"allowed_operations": ["read"], "target_files": []}
    steps = _build_execution_steps(task)
    combined = " ".join(steps)
    assert "Implement" not in combined


def test_build_context_summary_includes_title():
    task = {"title": "Add lounge skill", "description": "", "target_files": []}
    knowledge = [{"title": "Lounge docs", "content": ""}]
    summary = _build_context_summary(task, knowledge)
    assert "Add lounge skill" in summary


def test_build_context_summary_includes_knowledge():
    task = {"title": "Task", "description": "", "target_files": []}
    knowledge = [{"title": "Auth guide", "content": ""}]
    summary = _build_context_summary(task, knowledge)
    assert "Auth guide" in summary


# ── singleton ─────────────────────────────────────────────────────────────

def test_get_local_agent_bridge_singleton():
    b1 = get_local_agent_bridge()
    b2 = get_local_agent_bridge()
    assert b1 is b2
