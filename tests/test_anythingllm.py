"""Tests for AnythingLLM integration module."""
from __future__ import annotations

import json
from unittest.mock import MagicMock, patch, PropertyMock

import pytest


# ══════════════════════════════════════════════════════════════════════
#  Client initialization
# ══════════════════════════════════════════════════════════════════════


class TestAnythingLLMClientInit:
    """Test client initialization with config."""

    def test_init_with_no_instances(self):
        """Client initializes cleanly with no instances configured."""
        mock_cfg = MagicMock()
        mock_cfg.get.side_effect = lambda key, default=None: {
            "anythingllm.instances": {},
            "anythingllm.default_instance": "",
            "anythingllm.timeout_seconds": 30,
        }.get(key, default)

        with patch("engine.integrations.anythingllm.get_config", return_value=mock_cfg):
            from engine.integrations.anythingllm import AnythingLLMClient, reset_anythingllm_client
            reset_anythingllm_client()
            client = AnythingLLMClient()
            assert client._instances == {}
            assert client.status()["instances"] == {}

    def test_init_with_instances(self):
        """Client picks up instances from config."""
        mock_cfg = MagicMock()
        mock_cfg.get.side_effect = lambda key, default=None: {
            "anythingllm.instances": {
                "laptop": {"url": "http://localhost:3001", "api_key": "key1"},
                "phone": {"url": "http://phone:3001", "api_key": "key2"},
            },
            "anythingllm.default_instance": "laptop",
            "anythingllm.timeout_seconds": 30,
        }.get(key, default)

        with patch("engine.integrations.anythingllm.get_config", return_value=mock_cfg):
            from engine.integrations.anythingllm import AnythingLLMClient, reset_anythingllm_client
            reset_anythingllm_client()
            client = AnythingLLMClient()
            assert len(client._instances) == 2
            assert "laptop" in client._instances
            assert "phone" in client._instances
            assert client._default_instance == "laptop"

    def test_init_with_explicit_instances(self):
        """Client accepts explicit instances dict."""
        mock_cfg = MagicMock()
        mock_cfg.get.return_value = None

        with patch("engine.integrations.anythingllm.get_config", return_value=mock_cfg):
            from engine.integrations.anythingllm import AnythingLLMClient, reset_anythingllm_client
            reset_anythingllm_client()
            client = AnythingLLMClient(instances={
                "test": {"url": "http://test:3001", "api_key": "abc"},
            })
            assert len(client._instances) == 1
            assert client._default_instance == "test"


# ══════════════════════════════════════════════════════════════════════
#  Connection
# ══════════════════════════════════════════════════════════════════════


class TestConnection:
    """Test connect/disconnect logic."""

    def test_connect_success(self):
        """Successful connect marks instance as connected."""
        mock_cfg = MagicMock()
        mock_cfg.get.return_value = None

        with patch("engine.integrations.anythingllm.get_config", return_value=mock_cfg):
            from engine.integrations.anythingllm import AnythingLLMClient, reset_anythingllm_client
            reset_anythingllm_client()
            client = AnythingLLMClient(instances={
                "test": {"url": "http://test:3001", "api_key": "abc"},
            })

            with patch.object(client, "_get", return_value={"authenticated": True}):
                result = client.connect(instance="test")
                assert result["ok"] is True
                assert client.is_connected("test") is True

    def test_connect_failure(self):
        """Failed connect marks instance as disconnected."""
        mock_cfg = MagicMock()
        mock_cfg.get.return_value = None

        with patch("engine.integrations.anythingllm.get_config", return_value=mock_cfg):
            from engine.integrations.anythingllm import AnythingLLMClient, reset_anythingllm_client
            reset_anythingllm_client()
            client = AnythingLLMClient(instances={
                "test": {"url": "http://test:3001", "api_key": "abc"},
            })

            with patch.object(client, "_get", side_effect=ConnectionError("refused")):
                result = client.connect(instance="test")
                assert result["ok"] is False
                assert client.is_connected("test") is False

    def test_connect_all(self):
        """Connect all iterates all instances."""
        mock_cfg = MagicMock()
        mock_cfg.get.return_value = None

        with patch("engine.integrations.anythingllm.get_config", return_value=mock_cfg):
            from engine.integrations.anythingllm import AnythingLLMClient, reset_anythingllm_client
            reset_anythingllm_client()
            client = AnythingLLMClient(instances={
                "a": {"url": "http://a:3001", "api_key": ""},
                "b": {"url": "http://b:3001", "api_key": ""},
            })

            with patch.object(client, "_get", return_value={}):
                results = client.connect_all()
                assert "a" in results
                assert "b" in results


# ══════════════════════════════════════════════════════════════════════
#  Workspaces
# ══════════════════════════════════════════════════════════════════════


class TestWorkspaces:
    """Test workspace operations."""

    @pytest.fixture()
    def client(self):
        mock_cfg = MagicMock()
        mock_cfg.get.return_value = None
        with patch("engine.integrations.anythingllm.get_config", return_value=mock_cfg):
            from engine.integrations.anythingllm import AnythingLLMClient, reset_anythingllm_client
            reset_anythingllm_client()
            return AnythingLLMClient(instances={
                "test": {"url": "http://test:3001", "api_key": "abc"},
            })

    def test_list_workspaces(self, client):
        """List workspaces returns workspace list."""
        with patch.object(client, "_get", return_value={"workspaces": [{"name": "ws1"}]}):
            result = client.list_workspaces(instance="test")
            assert len(result) == 1
            assert result[0]["name"] == "ws1"

    def test_create_workspace(self, client):
        """Create workspace sends POST."""
        with patch.object(client, "_post", return_value={"workspace": {"slug": "new-ws"}}) as m:
            result = client.create_workspace("new-ws", instance="test")
            m.assert_called_once()
            assert result["workspace"]["slug"] == "new-ws"

    def test_list_workspaces_empty(self, client):
        """Empty workspace list returns empty array."""
        with patch.object(client, "_get", return_value={"workspaces": []}):
            result = client.list_workspaces(instance="test")
            assert result == []


# ══════════════════════════════════════════════════════════════════════
#  Chat
# ══════════════════════════════════════════════════════════════════════


class TestChat:
    """Test chat operations."""

    @pytest.fixture()
    def client(self):
        mock_cfg = MagicMock()
        mock_cfg.get.return_value = None
        with patch("engine.integrations.anythingllm.get_config", return_value=mock_cfg):
            from engine.integrations.anythingllm import AnythingLLMClient, reset_anythingllm_client
            reset_anythingllm_client()
            return AnythingLLMClient(instances={
                "test": {"url": "http://test:3001", "api_key": "abc"},
            })

    def test_chat_increments_stats(self, client):
        """Chat call increments chat counter."""
        with patch.object(client, "_post", return_value={"textResponse": "Hi"}):
            client.chat("my-ws", "Hello", instance="test")
            assert client._stats["chats"] == 1

    def test_chat_returns_response(self, client):
        """Chat returns the response dict."""
        with patch.object(client, "_post", return_value={"textResponse": "Hello!"}):
            result = client.chat("my-ws", "Hi", instance="test")
            assert result["textResponse"] == "Hello!"

    def test_chat_history(self, client):
        """Chat history returns message list."""
        with patch.object(client, "_get", return_value={"history": [{"role": "user", "content": "Hi"}]}):
            result = client.get_chat_history("my-ws", instance="test")
            assert len(result) == 1


# ══════════════════════════════════════════════════════════════════════
#  Nexus sync
# ══════════════════════════════════════════════════════════════════════


class TestNexusSync:
    """Test knowledge sync between AnythingLLM and Nexus."""

    @pytest.fixture()
    def client(self):
        mock_cfg = MagicMock()
        mock_cfg.get.return_value = None
        with patch("engine.integrations.anythingllm.get_config", return_value=mock_cfg):
            from engine.integrations.anythingllm import AnythingLLMClient, reset_anythingllm_client
            reset_anythingllm_client()
            return AnythingLLMClient(instances={
                "test": {"url": "http://test:3001", "api_key": "abc"},
            })

    def test_sync_to_nexus(self, client):
        """Sync exports Q&A pairs to Nexus."""
        history = [
            {"role": "user", "content": "What is X?"},
            {"role": "assistant", "content": "X is Y."},
        ]
        mock_nexus = MagicMock()
        with patch.object(client, "get_chat_history", return_value=history):
            with patch("engine.nexus.client.get_nexus_client", return_value=mock_nexus):
                result = client.sync_to_nexus("my-ws", instance="test")
                assert result["synced"] == 1
                mock_nexus.add_qa.assert_called_once()

    def test_sync_from_nexus(self, client):
        """Sync pushes Nexus entries to workspace."""
        mock_nexus = MagicMock()
        mock_nexus.search.return_value = [
            {"title": "Entry 1", "content": "Content 1"},
            {"title": "Entry 2", "content": "Content 2"},
        ]
        with patch("engine.nexus.client.get_nexus_client", return_value=mock_nexus):
            with patch.object(client, "upload_document", return_value={"ok": True}):
                result = client.sync_from_nexus("my-ws", instance="test")
                assert result["uploaded"] == 2


# ══════════════════════════════════════════════════════════════════════
#  Status & instances
# ══════════════════════════════════════════════════════════════════════


class TestStatusAndInstances:
    """Test status and instance listing."""

    def test_status_includes_stats(self):
        """Status includes request stats."""
        mock_cfg = MagicMock()
        mock_cfg.get.return_value = None
        with patch("engine.integrations.anythingllm.get_config", return_value=mock_cfg):
            from engine.integrations.anythingllm import AnythingLLMClient, reset_anythingllm_client
            reset_anythingllm_client()
            client = AnythingLLMClient(instances={
                "test": {"url": "http://test:3001", "api_key": "abc"},
            })
            status = client.status()
            assert "stats" in status
            assert "instances" in status
            assert status["stats"]["requests"] == 0

    def test_list_instances(self):
        """List instances returns all configured instances."""
        mock_cfg = MagicMock()
        mock_cfg.get.return_value = None
        with patch("engine.integrations.anythingllm.get_config", return_value=mock_cfg):
            from engine.integrations.anythingllm import AnythingLLMClient, reset_anythingllm_client
            reset_anythingllm_client()
            client = AnythingLLMClient(instances={
                "laptop": {"url": "http://localhost:3001", "api_key": ""},
                "phone": {"url": "http://phone:3001", "api_key": ""},
            })
            instances = client.list_instances()
            assert len(instances) == 2
            names = {i["name"] for i in instances}
            assert names == {"laptop", "phone"}


# ══════════════════════════════════════════════════════════════════════
#  Skills registration
# ══════════════════════════════════════════════════════════════════════


class TestSkillsRegistration:
    """Test that AnythingLLM skills are importable and registered."""

    def test_skills_importable(self):
        """All AnythingLLM skills can be imported."""
        from engine.skills.builtin.anythingllm_skills import (
            allm_connect, allm_status, allm_list_instances,
            allm_list_workspaces, allm_create_workspace,
            allm_chat, allm_chat_history,
            allm_sync_to_nexus, allm_sync_from_nexus,
            allm_upload_document,
        )
        assert callable(allm_connect)
        assert callable(allm_chat)
        assert callable(allm_sync_to_nexus)

    def test_skill_pack_name(self):
        """All skills are registered in the skill registry."""
        from engine.skills.registry import SKILL_REGISTRY
        allm_skills = SKILL_REGISTRY.get_pack_tools("anythingllm")
        assert len(allm_skills) >= 10


# ══════════════════════════════════════════════════════════════════════
#  MCP tools registration
# ══════════════════════════════════════════════════════════════════════


class TestMCPToolsRegistration:
    """Test that AnythingLLM MCP tools are registered in devtools_server."""

    def test_allm_mcp_tools_exist(self):
        """AnythingLLM MCP tools are defined in devtools_server.py."""
        from pathlib import Path
        content = Path("engine/mcp/devtools_server.py").read_text(encoding="utf-8")
        assert "def allm_connect" in content
        assert "def allm_status" in content
        assert "def allm_list_workspaces" in content
        assert "def allm_chat" in content
        assert "def allm_sync_to_nexus" in content
        assert "def allm_sync_from_nexus" in content
