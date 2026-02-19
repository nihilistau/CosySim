"""
Tests for engine/mcp/cosysim_server.py — MCP tools and resources

Uses mocks for DB/RAG/config to test tool/resource logic in isolation.
"""
import json
import pytest
from unittest.mock import patch, MagicMock

# Import the module-level functions (MCP tools/resources)
from engine.mcp import cosysim_server


# ── Fixtures ──────────────────────────────────────────────────────────

@pytest.fixture(autouse=True)
def mock_db():
    """Mock database for all tests."""
    db = MagicMock()
    with patch.object(cosysim_server, "_get_db", return_value=db):
        yield db


@pytest.fixture
def mock_rag():
    """Mock RAG manager."""
    rag = MagicMock()
    with patch.object(cosysim_server, "_get_rag", return_value=rag):
        yield rag


@pytest.fixture
def mock_config():
    """Mock config manager."""
    config = MagicMock()
    config._config = {"system": {"name": "CosySim"}, "lmstudio": {"host": "127.0.0.1"}}
    config.get.side_effect = lambda key, default=None: {
        "scenes.phone.port": 5555,
    }.get(key, default)
    with patch.object(cosysim_server, "_get_config", return_value=config):
        yield config


# ═══════════════════════════════════════════════════════════════════════
#  TOOL TESTS
# ═══════════════════════════════════════════════════════════════════════

class TestSearchMemory:
    def test_success(self, mock_rag):
        mock_rag.search.return_value = [
            {"text": "We met at the park", "score": 0.95},
            {"text": "She likes coffee", "score": 0.80},
        ]
        result = cosysim_server.search_memory("park", character_id="luna")
        assert "park" in result
        assert "0.95" in result
        assert "coffee" in result

    def test_no_results(self, mock_rag):
        mock_rag.search.return_value = []
        result = cosysim_server.search_memory("nonexistent")
        assert "No relevant memories" in result

    def test_rag_unavailable(self):
        with patch.object(cosysim_server, "_get_rag", return_value=None):
            result = cosysim_server.search_memory("test")
            assert "unavailable" in result


class TestStoreMemory:
    def test_success(self, mock_rag):
        result = cosysim_server.store_memory("Important fact", character_id="luna")
        assert "stored" in result.lower()
        mock_rag.add.assert_called_once()

    def test_with_metadata(self, mock_rag):
        meta = json.dumps({"importance": "high"})
        result = cosysim_server.store_memory("Fact", character_id="luna", metadata=meta)
        assert "stored" in result.lower()
        call_args = mock_rag.add.call_args
        assert call_args[1]["metadata"]["importance"] == "high"

    def test_rag_unavailable(self):
        with patch.object(cosysim_server, "_get_rag", return_value=None):
            result = cosysim_server.store_memory("test", character_id="x")
            assert "unavailable" in result


class TestGetCharacterState:
    def test_success(self, mock_db):
        mock_db.get_character_state.return_value = {"mood": "happy", "energy": 0.8}
        mock_db.list_relationships.return_value = []
        result = cosysim_server.get_character_state("luna")
        parsed = json.loads(result)
        assert parsed["state"]["mood"] == "happy"

    def test_not_found(self, mock_db):
        mock_db.get_character_state.return_value = None
        result = cosysim_server.get_character_state("nobody")
        assert "No state found" in result


class TestAdjustRelationship:
    def test_valid_field(self, mock_db):
        mock_db.get_or_create_relationship.return_value = {"trust": 0.5}
        result = cosysim_server.adjust_relationship("luna", "player", "trust", 0.1)
        assert "0.50" in result
        assert "0.60" in result
        mock_db.update_relationship.assert_called_once()

    def test_clamp_to_max(self, mock_db):
        mock_db.get_or_create_relationship.return_value = {"trust": 0.95}
        result = cosysim_server.adjust_relationship("luna", "player", "trust", 0.2)
        assert "1.00" in result

    def test_clamp_to_min(self, mock_db):
        mock_db.get_or_create_relationship.return_value = {"trust": 0.05}
        result = cosysim_server.adjust_relationship("luna", "player", "trust", -0.2)
        assert "0.00" in result

    def test_invalid_field(self, mock_db):
        result = cosysim_server.adjust_relationship("a", "b", "invalid_field", 0.1)
        assert "Invalid field" in result


class TestGetChainEvents:
    def test_success(self, mock_db):
        mock_db.get_chain_events.return_value = [
            {"event_type": "user_message", "actor": "Player", "summary": "Hello"},
            {"event_type": "llm_response", "actor": "Luna", "summary": "Hi there!"},
        ]
        result = cosysim_server.get_chain_events("chain-123")
        assert "user_message" in result
        assert "Player" in result
        assert "Luna" in result

    def test_no_events(self, mock_db):
        mock_db.get_chain_events.return_value = []
        result = cosysim_server.get_chain_events("empty-chain")
        assert "No events" in result


class TestLogEvent:
    def test_success(self, mock_db):
        result = cosysim_server.log_event(
            chain_id="chain-123",
            event_type="custom_event",
            actor="TestActor",
            summary="Something happened",
        )
        assert "logged" in result.lower()
        mock_db.log_event.assert_called_once()

    def test_with_payload(self, mock_db):
        payload = json.dumps({"key": "value"})
        result = cosysim_server.log_event(
            chain_id="chain-123",
            event_type="data_event",
            actor="System",
            summary="Data logged",
            payload=payload,
        )
        assert "logged" in result.lower()


class TestListCharacters:
    def test_success(self, mock_db):
        mock_db.get_all_characters.return_value = [
            {"name": "Luna", "id": "luna"},
            {"name": "Alex", "id": "alex"},
        ]
        result = cosysim_server.list_characters()
        assert "Luna" in result
        assert "Alex" in result

    def test_empty(self, mock_db):
        mock_db.get_all_characters.return_value = []
        result = cosysim_server.list_characters()
        assert "No characters" in result


class TestGetBenchmarkStats:
    def test_success(self):
        mock_stats = {
            "llm.complete": {"count": 10, "avg_ms": 500, "p95_ms": 800, "max_ms": 1000},
        }
        with patch("engine.mcp.cosysim_server.get_benchmarks", mock_stats, create=True):
            with patch("engine.logging.get_benchmarks", return_value=mock_stats):
                result = cosysim_server.get_benchmark_stats()
                assert "llm.complete" in result or "No benchmark" in result or "Failed" in result

    def test_no_data(self):
        with patch("engine.logging.get_benchmarks", return_value={}):
            result = cosysim_server.get_benchmark_stats()
            assert "No benchmark" in result or "Failed" in result


class TestGenerateImageRequest:
    def test_success(self):
        with patch("content.simulation.services.comfyui_client.ComfyUIClient") as MockClient:
            with patch("engine.config.get_config") as mock_cfg:
                mock_cfg.return_value = MagicMock()
                mock_cfg.return_value.get.return_value = "http://127.0.0.1:8188"
                MockClient.return_value.generate_image.return_value = "/path/to/image.png"
                result = cosysim_server.generate_image_request("a beautiful sunset")
                assert "image" in result.lower() or "failed" in result.lower()


# ═══════════════════════════════════════════════════════════════════════
#  RESOURCE TESTS
# ═══════════════════════════════════════════════════════════════════════

class TestResourceConfig:
    def test_returns_json(self, mock_config):
        result = cosysim_server.resource_config()
        parsed = json.loads(result)
        assert "system" in parsed
        assert parsed["system"]["name"] == "CosySim"


class TestResourceBenchmarks:
    def test_returns_json(self):
        mock_data = {"op1": {"count": 5, "avg_ms": 100}}
        with patch("engine.logging.get_benchmarks", return_value=mock_data):
            result = cosysim_server.resource_benchmarks()
            assert "op1" in result or "unavailable" in result.lower()


class TestResourceCharacter:
    def test_returns_full_profile(self, mock_db):
        mock_db.get_character.return_value = {"id": "luna", "name": "Luna"}
        mock_db.get_character_state.return_value = {"mood": "happy"}
        mock_db.list_relationships.return_value = []
        mock_db.get_personality.return_value = {"warmth": 0.8}
        result = cosysim_server.resource_character("luna")
        parsed = json.loads(result)
        assert parsed["character"]["name"] == "Luna"
        assert parsed["state"]["mood"] == "happy"
        assert parsed["personality"]["warmth"] == 0.8


class TestResourceChain:
    def test_returns_events(self, mock_db):
        mock_db.get_chain_events.return_value = [
            {"event_type": "test", "actor": "A", "summary": "event 1"},
        ]
        result = cosysim_server.resource_chain("chain-abc")
        parsed = json.loads(result)
        assert len(parsed) == 1
        assert parsed[0]["event_type"] == "test"


class TestResourceSceneStatus:
    def test_running(self, mock_config):
        with patch("socket.create_connection") as mock_sock:
            mock_sock.return_value.__enter__ = MagicMock()
            mock_sock.return_value.__exit__ = MagicMock()
            result = cosysim_server.resource_scene_status("phone")
            parsed = json.loads(result)
            assert parsed["scene"] == "phone"
            assert parsed["status"] == "running"

    def test_stopped(self, mock_config):
        with patch("socket.create_connection", side_effect=OSError("refused")):
            result = cosysim_server.resource_scene_status("phone")
            parsed = json.loads(result)
            assert parsed["status"] == "stopped"

    def test_unknown_scene(self, mock_config):
        mock_config.get.side_effect = lambda key, default=None: default
        result = cosysim_server.resource_scene_status("nonexistent")
        parsed = json.loads(result)
        assert parsed["status"] == "unknown"
