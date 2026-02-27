"""Tests for engine.nexus.copilot_self_config — Copilot config sync to Nexus."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from engine.nexus.copilot_self_config import (
    CopilotSelfConfig,
    NEXUS_CATEGORIES,
    get_copilot_config,
)


# ── Fixtures ────────────────────────────────────────────────────────────


@pytest.fixture
def config(tmp_path):
    """CopilotSelfConfig with a temp project root."""
    # Create mock directory structure
    instructions = tmp_path / ".github" / "instructions"
    instructions.mkdir(parents=True)
    (instructions / "python.instructions.md").write_text("# Python rules\nUse type hints.", encoding="utf-8")
    (instructions / "testing.instructions.md").write_text("# Testing rules\nUse pytest.", encoding="utf-8")

    agents = tmp_path / ".github" / "agents"
    agents.mkdir(parents=True)
    (agents / "scene-builder.agent.md").write_text("# Scene Builder\nBuild scenes.", encoding="utf-8")
    (agents / "test-writer.agent.md").write_text("# Test Writer\nWrite tests.", encoding="utf-8")
    (agents / "doc-writer.agent.md").write_text("# Doc Writer\nWrite docs.", encoding="utf-8")

    hooks = tmp_path / ".github" / "hooks"
    scripts = hooks / "scripts"
    scripts.mkdir(parents=True)
    (hooks / "cosysim-hooks.json").write_text('{"hooks": []}', encoding="utf-8")
    (scripts / "check-tool-safety.ps1").write_text("# Safety check", encoding="utf-8")

    return CopilotSelfConfig(project_root=tmp_path)


# ── Instruction Files ──────────────────────────────────────────────────


class TestInstructions:
    """Test instruction file operations."""

    def test_list_instructions(self, config):
        """Lists all .md files in instructions dir."""
        instructions = config.list_instructions()
        assert len(instructions) == 2
        names = [i["name"] for i in instructions]
        assert "python.instructions" in names
        assert "testing.instructions" in names

    def test_list_instructions_empty_dir(self, tmp_path):
        """Empty dir returns empty list."""
        cfg = CopilotSelfConfig(project_root=tmp_path)
        assert cfg.list_instructions() == []

    def test_read_instruction(self, config):
        """Read an instruction file by stem name."""
        content = config.read_instruction("python.instructions")
        assert content is not None
        assert "type hints" in content

    def test_read_nonexistent(self, config):
        """Reading nonexistent instruction returns None."""
        assert config.read_instruction("nonexistent") is None

    @patch("engine.nexus.client.get_nexus_client")
    def test_sync_instructions_to_nexus(self, mock_client, config):
        """Syncs instruction files to Nexus."""
        client = MagicMock()
        client.search.return_value = []
        mock_client.return_value = client

        result = config.sync_instructions_to_nexus()
        assert result["stored"] == 2
        assert result["skipped"] == 0
        assert client.add_entry.call_count == 2

    @patch("engine.nexus.client.get_nexus_client")
    def test_sync_instructions_skips_existing(self, mock_client, config):
        """Already-stored instructions are skipped."""
        client = MagicMock()
        client.search.return_value = [{"title": "existing"}]
        mock_client.return_value = client

        result = config.sync_instructions_to_nexus()
        assert result["stored"] == 0
        assert result["skipped"] == 2

    def test_sync_instructions_no_nexus(self, config):
        """Sync handles missing Nexus gracefully."""
        result = config.sync_instructions_to_nexus()
        assert "stored" in result or "error" in result


# ── Agent Definitions ──────────────────────────────────────────────────


class TestAgents:
    """Test agent definition operations."""

    def test_list_agents(self, config):
        """Lists all agent .md files."""
        agents = config.list_agents()
        assert len(agents) == 3
        names = [a["name"] for a in agents]
        assert "scene-builder" in names
        assert "test-writer" in names

    def test_read_agent(self, config):
        """Read an agent definition by name."""
        content = config.read_agent("scene-builder")
        assert content is not None
        assert "Scene Builder" in content

    def test_read_nonexistent_agent(self, config):
        """Reading nonexistent agent returns None."""
        assert config.read_agent("nonexistent") is None

    @patch("engine.nexus.client.get_nexus_client")
    def test_sync_agents_to_nexus(self, mock_client, config):
        """Syncs agent definitions to Nexus."""
        client = MagicMock()
        client.search.return_value = []
        mock_client.return_value = client

        result = config.sync_agents_to_nexus()
        assert result["stored"] == 3
        assert client.add_entry.call_count == 3


# ── Hook Scripts ───────────────────────────────────────────────────────


class TestHooks:
    """Test hook script operations."""

    def test_list_hooks(self, config):
        """Lists all hook scripts and JSON."""
        hooks = config.list_hooks()
        assert len(hooks) == 2
        names = [h["name"] for h in hooks]
        assert "cosysim-hooks" in names
        assert "check-tool-safety" in names

    @patch("engine.nexus.client.get_nexus_client")
    def test_sync_hooks_to_nexus(self, mock_client, config):
        """Syncs hook scripts to Nexus."""
        client = MagicMock()
        client.search.return_value = []
        mock_client.return_value = client

        result = config.sync_hooks_to_nexus()
        assert result["stored"] == 2


# ── Full Sync ──────────────────────────────────────────────────────────


class TestFullSync:
    """Test sync_all_to_nexus."""

    @patch("engine.nexus.client.get_nexus_client")
    def test_sync_all(self, mock_client, config):
        """Full sync stores everything."""
        client = MagicMock()
        client.search.return_value = []
        mock_client.return_value = client

        result = config.sync_all_to_nexus()
        assert "instructions" in result
        assert "agents" in result
        assert "hooks" in result
        assert "summary" in result
        assert result["summary"]["total_stored"] == 7  # 2 + 3 + 2

    @patch("engine.nexus.client.get_nexus_client")
    def test_sync_all_idempotent(self, mock_client, config):
        """Running sync twice doesn't duplicate."""
        client = MagicMock()
        # First call: nothing exists
        client.search.side_effect = lambda *a, **kw: []
        mock_client.return_value = client
        config.sync_all_to_nexus()

        # Second call: everything exists
        client.search.side_effect = lambda *a, **kw: [{"title": "existing"}]
        result = config.sync_all_to_nexus()
        assert result["summary"]["total_stored"] == 0


# ── Preferences ────────────────────────────────────────────────────────


class TestPreferences:
    """Test preference storage and retrieval."""

    def test_store_and_get_cached(self, config):
        """Stored preference is returned from cache."""
        config.store_preference("model", "qwen-7b")
        assert config.get_preference("model") == "qwen-7b"

    def test_get_default(self, config):
        """Missing preference returns default when Nexus has no answer."""
        with patch("engine.nexus.client.get_nexus_client") as mock_client:
            client = MagicMock()
            client.ask.return_value = None
            mock_client.return_value = client
            assert config.get_preference("nonexistent", "default") == "default"

    def test_store_complex_value(self, config):
        """Complex values (dict/list) can be stored."""
        config.store_preference("settings", {"temp": 0.7, "top_p": 0.9})
        result = config.get_preference("settings")
        assert result["temp"] == 0.7


# ── Status ─────────────────────────────────────────────────────────────


class TestStatus:
    """Test status reporting."""

    def test_status_structure(self, config):
        """Status has expected keys."""
        status = config.status()
        assert "instructions" in status
        assert "agents" in status
        assert "hooks" in status
        assert "cached_preferences" in status
        assert "project_root" in status

    def test_status_counts(self, config):
        """Status counts match actual files."""
        status = config.status()
        assert status["instructions"] == 2
        assert status["agents"] == 3
        assert status["hooks"] == 2


# ── Nexus Categories ──────────────────────────────────────────────────


class TestCategories:
    """Test Nexus category constants."""

    def test_categories_defined(self):
        """All expected categories exist."""
        assert "instructions" in NEXUS_CATEGORIES
        assert "agents" in NEXUS_CATEGORIES
        assert "hooks" in NEXUS_CATEGORIES
        assert "preferences" in NEXUS_CATEGORIES
        assert "rules" in NEXUS_CATEGORIES


# ── Singleton ──────────────────────────────────────────────────────────


class TestSingleton:
    """Test singleton pattern."""

    def test_singleton(self):
        """get_copilot_config returns same instance."""
        import engine.nexus.copilot_self_config as mod
        mod._instance = None
        c1 = get_copilot_config()
        c2 = get_copilot_config()
        assert c1 is c2
        mod._instance = None
