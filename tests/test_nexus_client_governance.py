"""Focused governance tests for engine.nexus.client."""
from __future__ import annotations

from unittest.mock import MagicMock, patch

from engine.nexus.client import NexusClient


def _allowing_manager() -> MagicMock:
    manager = MagicMock()
    manager.check_permissions.return_value = True
    return manager


class TestEntryGovernance:
    def test_add_entry_normalizes_namespace_tags(self) -> None:
        client = NexusClient("http://test")
        manager = _allowing_manager()

        with patch(
            "engine.nexus.governance_rules.get_governance_manager",
            return_value=manager,
        ), patch.object(
            client,
            "_post",
            return_value={"ok": True, "data": {"id": "entry-1"}},
        ) as mock_post:
            entry_id = client.add_entry(
                "Session Note",
                "Useful session content",
                content_type="document",
                category="sessions",
                tags=["manual"],
                created_by="session_sync",
                agent_id="copilot",
            )

        assert entry_id == "entry-1"
        payload = mock_post.call_args.args[1]
        assert "copilot" in payload["tags"]
        assert "manual" in payload["tags"]

    def test_add_entry_denied_for_low_permission_actor(self) -> None:
        client = NexusClient("http://test")
        manager = MagicMock()
        manager.check_permissions.return_value = False

        with patch(
            "engine.nexus.governance_rules.get_governance_manager",
            return_value=manager,
        ), patch.object(client, "_post") as mock_post:
            entry_id = client.add_entry(
                "Title",
                "Content",
                agent_id="qwen3-0.6b",
            )

        assert entry_id is None
        mock_post.assert_not_called()


class TestQaGovernance:
    def test_add_qa_normalizes_namespace_tags(self) -> None:
        client = NexusClient("http://test")
        manager = _allowing_manager()

        with patch(
            "engine.nexus.governance_rules.get_governance_manager",
            return_value=manager,
        ), patch.object(
            client,
            "_post",
            return_value={"ok": True, "data": {"id": "qa-1"}},
        ) as mock_post:
            qa_id = client.add_qa(
                "What happened?",
                "A governed answer.",
                category="sessions",
                tags=["decision"],
                agent_id="copilot",
            )

        assert qa_id == "qa-1"
        payload = mock_post.call_args.args[1]
        assert "copilot" in payload["tags"]
        assert "decision" in payload["tags"]


class TestDeleteGovernance:
    def test_delete_entry_blocks_low_permission_actor(self) -> None:
        client = NexusClient("http://test")
        manager = MagicMock()
        manager.check_permissions.return_value = False

        with patch(
            "engine.nexus.governance_rules.get_governance_manager",
            return_value=manager,
        ), patch.object(
            client,
            "get_entry",
            return_value={"created_by": "copilot"},
        ), patch.object(client, "_delete") as mock_delete:
            ok = client.delete_entry("entry-1", agent_id="qwen3-0.6b")

        assert ok is False
        mock_delete.assert_not_called()


class TestBatchGovernance:
    def test_batch_add_skips_denied_entries_and_posts_allowed_ones(self) -> None:
        client = NexusClient("http://test")
        manager = MagicMock()
        manager.check_permissions.side_effect = [True, False]

        with patch(
            "engine.nexus.governance_rules.get_governance_manager",
            return_value=manager,
        ), patch.object(
            client,
            "_post",
            return_value={"ok": True, "data": {"ids": ["entry-1"]}},
        ) as mock_post:
            ids = client.batch_add(
                [
                    {
                        "title": "Allowed",
                        "content": "First payload",
                        "content_type": "note",
                        "category": "architecture",
                        "tags": [],
                        "created_by": "copilot",
                        "agent_id": "copilot",
                    },
                    {
                        "title": "Denied",
                        "content": "Second payload",
                        "content_type": "note",
                        "category": "architecture",
                        "tags": [],
                        "created_by": "tiny-model",
                        "agent_id": "qwen3-0.6b",
                    },
                ]
            )

        assert ids == ["entry-1"]
        payload = mock_post.call_args.args[1]
        assert len(payload["entries"]) == 1
        assert payload["entries"][0]["title"] == "Allowed"
