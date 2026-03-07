"""Tests for reusable Nexus knowledge capture helpers."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from engine.nexus.knowledge_capture import (
    capture_entry_and_qa,
    capture_external_discovery,
)


class TestCaptureEntryAndQA:
    """Tests for storing entries and Q&A pairs together."""

    @patch("engine.nexus.client.get_nexus_client")
    def test_capture_entry_and_qa_stores_both(self, mock_get_client):
        """Entry capture stores both the knowledge entry and Q&A pair."""
        mock_client = MagicMock()
        mock_client.add_entry.return_value = "entry-123"
        mock_client.add_qa.return_value = "qa-456"
        mock_get_client.return_value = mock_client

        result = capture_entry_and_qa(
            "Useful note",
            "Important content",
            question="What is the useful note?",
            answer="Important content",
            category="architecture",
            tags=["nexus", "capture"],
        )

        mock_client.add_entry.assert_called_once_with(
            title="Useful note",
            content="Important content",
            content_type="note",
            category="architecture",
            tags=["nexus", "capture"],
        )
        mock_client.add_qa.assert_called_once_with(
            question="What is the useful note?",
            answer="Important content",
            category="architecture",
            tags=["nexus", "capture"],
        )
        assert result.entry_id == "entry-123"
        assert result.qa_id == "qa-456"
        assert result.to_dict()["stored"] is True


class TestCaptureExternalDiscovery:
    """Tests for the external discovery backfill helper."""

    @patch("engine.nexus.client.get_nexus_client")
    def test_capture_external_discovery_adds_backfill_tags(self, mock_get_client):
        """External discovery capture stores reusable backfill tags."""
        mock_client = MagicMock()
        mock_client.add_entry.return_value = "entry-abc"
        mock_client.add_qa.return_value = "qa-def"
        mock_get_client.return_value = mock_client

        result = capture_external_discovery(
            question="How is auth refreshed?",
            answer="Use the CDP refresh path.",
            source="docs/auth.md",
            details="Validated against live runtime behavior.",
            tags=["auth"],
        )

        _, entry_kwargs = mock_client.add_entry.call_args
        _, qa_kwargs = mock_client.add_qa.call_args
        assert "nexus-backfill" in entry_kwargs["tags"]
        assert "external-discovery" in entry_kwargs["tags"]
        assert "auth" in entry_kwargs["tags"]
        assert qa_kwargs["question"] == "How is auth refreshed?"
        assert result.title.startswith("Discovery:")
