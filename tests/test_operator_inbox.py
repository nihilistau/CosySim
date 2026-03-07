"""Tests for engine.nexus.operator_inbox."""
from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock, patch

from engine.nexus.operator_inbox import OperatorInbox


def _mock_config() -> MagicMock:
    """Return a config stub with operator inbox defaults."""
    config = MagicMock()
    config.get.side_effect = lambda key, default=None: {
        "nexus.operator_inbox.plan_digest_limit": 5,
    }.get(key, default)
    return config


def test_submit_item_stores_nexus_entry_and_state(tmp_path: Path):
    """Submitting an operator item mirrors it into Nexus and local state."""
    nexus_client = MagicMock()
    nexus_client.add_entry.return_value = "entry-1"
    state_path = tmp_path / "operator_inbox.json"
    inbox = OperatorInbox(config=_mock_config(), state_path=state_path)

    with patch("engine.nexus.client.get_nexus_client", return_value=nexus_client):
        item = inbox.submit_item(
            title="Add mobile control panel",
            content="Expose current work, git, queue, and notifications.",
            item_type="feature",
            priority="high",
            source="test",
            author="operator",
            tags=["Mobile UI", "Control Panel"],
            metadata={"dispatch_mode": "queue", "scene_id": "intel_hub"},
        )

    assert item.nexus_entry_id == "entry-1"
    assert item.priority == "high"
    assert state_path.exists()
    persisted = json.loads(state_path.read_text(encoding="utf-8"))
    assert persisted["items"][0]["title"] == "Add mobile control panel"
    assert "mobile-ui" in persisted["items"][0]["tags"]


def test_process_items_creates_scheduler_task_and_digest(tmp_path: Path):
    """Processing pending items promotes them into the task queue and digest."""
    nexus_client = MagicMock()
    nexus_client.add_entry.side_effect = ["entry-1", "digest-1"]
    nexus_client.update_entry.return_value = True
    scheduler = MagicMock()
    scheduler.create_task.return_value = MagicMock(
        id="task-1",
        title="Operator: Add mobile control panel",
    )
    inbox = OperatorInbox(config=_mock_config(), state_path=tmp_path / "operator_inbox.json")

    with (
        patch("engine.nexus.client.get_nexus_client", return_value=nexus_client),
        patch("engine.nexus.task_scheduler.get_task_scheduler", return_value=scheduler),
    ):
        item = inbox.submit_item(
            title="Add mobile control panel",
            content="Queue this request for implementation.",
            item_type="feature",
            priority="critical",
            source="test",
            author="operator",
        )
        result = inbox.process_items(limit=1)

    updated = inbox.get_item(item.item_id)
    assert result["ok"] is True
    assert result["created_tasks"] == 1
    assert result["digest_entry_id"] == "digest-1"
    scheduler.create_task.assert_called_once()
    assert updated is not None
    assert updated.status == "queued"
    assert updated.task_id == "task-1"
    assert updated.digest_entry_id == "digest-1"


def test_pending_for_onboarding_returns_compact_summary(tmp_path: Path):
    """Pending onboarding payload includes summary counts and compact items."""
    nexus_client = MagicMock()
    nexus_client.add_entry.return_value = "entry-1"
    inbox = OperatorInbox(config=_mock_config(), state_path=tmp_path / "operator_inbox.json")

    with patch("engine.nexus.client.get_nexus_client", return_value=nexus_client):
        inbox.submit_item(
            title="Remember vague user notes",
            content="Store off-turn suggestions in Nexus and surface them later.",
            item_type="direction",
            priority="normal",
            source="test",
            author="operator",
        )

    onboarding = inbox.pending_for_onboarding(limit=5)
    assert onboarding["summary"]["pending"] == 1
    assert onboarding["items"][0]["title"] == "Remember vague user notes"
    assert onboarding["items"][0]["item_type"] == "direction"
