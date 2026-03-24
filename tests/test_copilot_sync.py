"""Tests for bidirectional Copilot config sync.

v1.50.2 [2026-03-24] — Tests for pull_from_nexus, bidirectional_sync, and structured preferences.
"""
from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from engine.nexus.copilot_self_config import CopilotSelfConfig, NEXUS_CATEGORIES


# ── Fixtures ──────────────────────────────────────────────────────────────

@pytest.fixture
def config_dir(tmp_path):
    """Create a temporary project root with config dirs."""
    instructions = tmp_path / ".github" / "instructions"
    instructions.mkdir(parents=True)
    agents = tmp_path / ".github" / "agents"
    agents.mkdir(parents=True)
    hooks = tmp_path / ".github" / "hooks"
    hooks.mkdir(parents=True)
    return tmp_path


@pytest.fixture
def config(config_dir):
    """Create a CopilotSelfConfig with temp project root."""
    return CopilotSelfConfig(project_root=config_dir)


@pytest.fixture
def mock_client():
    """Create a mock NexusClient."""
    client = MagicMock()
    client.search.return_value = []
    client.add_entry.return_value = "entry-123"
    return client


# ── Pull instructions ─────────────────────────────────────────────────────

class TestPullInstructions:

    def test_pull_new_file(self, config, config_dir, mock_client):
        """Nexus has instruction not on disk → written to disk."""
        mock_client.search.return_value = [
            {
                "title": "[Copilot Instruction] testing",
                "content": "# Testing Guidelines\nAlways run tests.",
                "category": NEXUS_CATEGORIES["instructions"],
                "updated_at": "2026-03-25T00:00:00Z",
            }
        ]
        with patch("engine.nexus.client.get_nexus_client", return_value=mock_client):
            result = config.pull_instructions_from_nexus()

        assert result["pulled"] == 1
        target = config_dir / ".github" / "instructions" / "testing.instructions.md"
        assert target.exists()
        assert "Testing Guidelines" in target.read_text()

    def test_pull_unchanged_skipped(self, config, config_dir, mock_client):
        """Identical content → skipped, no write."""
        content = "# Same content"
        target = config_dir / ".github" / "instructions" / "unchanged.instructions.md"
        target.write_text(content)

        mock_client.search.return_value = [
            {
                "title": "[Copilot Instruction] unchanged",
                "content": content,
                "category": NEXUS_CATEGORIES["instructions"],
                "updated_at": "2026-03-20T00:00:00Z",
            }
        ]
        with patch("engine.nexus.client.get_nexus_client", return_value=mock_client):
            result = config.pull_instructions_from_nexus()

        assert result["skipped"] == 1
        assert result["pulled"] == 0

    def test_pull_nexus_offline(self, config, mock_client):
        """Nexus offline → graceful failure."""
        mock_client.search.side_effect = ConnectionError("offline")
        with patch("engine.nexus.client.get_nexus_client", return_value=mock_client):
            result = config.pull_instructions_from_nexus()

        assert result["pulled"] == 0
        assert "error" in result


# ── Bidirectional sync ────────────────────────────────────────────────────

class TestBidirectionalSync:

    def test_push_then_pull_order(self, config, mock_client):
        """bidirectional_sync must push first, then pull."""
        call_order = []

        def track_push():
            call_order.append("push")
            return {"summary": {"total_stored": 0, "total_updated": 0, "total_skipped": 0}}

        def track_pull():
            call_order.append("pull")
            return {"summary": {"total_pulled": 0, "total_conflicts": 0}}

        config.sync_all_to_nexus = track_push
        config.pull_all_from_nexus = track_pull

        result = config.bidirectional_sync()

        assert call_order == ["push", "pull"]
        assert "push" in result
        assert "pull" in result


# ── Structured preference storage ─────────────────────────────────────────

class TestPreferences:

    def test_store_preference_uses_entry(self, config, mock_client):
        """store_preference should use add_entry, not add_qa."""
        with patch("engine.nexus.client.get_nexus_client", return_value=mock_client):
            config.store_preference("default_model", "qwen3-7b")

        mock_client.add_entry.assert_called_once()
        call_kwargs = mock_client.add_entry.call_args
        assert "[Copilot Preference] default_model" in str(call_kwargs)
        mock_client.add_qa.assert_not_called()

    def test_get_preference_from_cache(self, config):
        """Cached preferences should be returned without Nexus call."""
        config._cache["theme"] = "dark"
        assert config.get_preference("theme") == "dark"

    def test_get_preference_from_nexus(self, config, mock_client):
        """Preferences should be found via structured entry search."""
        mock_client.search.return_value = [
            {
                "title": "[Copilot Preference] theme",
                "content": '"dark"',
                "category": NEXUS_CATEGORIES["preferences"],
            }
        ]
        with patch("engine.nexus.client.get_nexus_client", return_value=mock_client):
            value = config.get_preference("theme")

        assert value == "dark"
        assert config._cache["theme"] == "dark"  # Cached for next time

    def test_get_preference_default(self, config, mock_client):
        """Missing preference should return default."""
        mock_client.search.return_value = []
        with patch("engine.nexus.client.get_nexus_client", return_value=mock_client):
            value = config.get_preference("nonexistent", default="fallback")

        assert value == "fallback"
