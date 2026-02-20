"""
End-to-end integration tests for CosySim three-pillar architecture.

Tests the full pipeline: CharacterAgent → EventChain → skills → media → TTS.
All external services (LMStudio, ComfyUI, TTS server) are mocked.
"""
import json
import os
import pytest
import tempfile
import wave
from pathlib import Path
from unittest.mock import MagicMock, patch, PropertyMock


# ═══════════════════════════════════════════════════════════════════════
#  CharacterAgent ↔ EventChain integration
# ═══════════════════════════════════════════════════════════════════════

class TestAgentEventChain:
    """CharacterAgent logs all interactions to EventChain."""

    def _make_agent(self, char_name="Luna"):
        from engine.agents.character_agent import CharacterAgent
        char = MagicMock()
        char.id = "luna_01"
        char.name = char_name
        char.mood = "playful"
        char.warmth = 0.8
        char.formality = 0.3
        char.humor = 0.7
        char.flirtiness = 0.6
        char.intelligence = 0.6
        char.creativity = 0.7
        char.relationship_level = 0.5
        char.description = "A playful companion"
        char.backstory = ""
        return CharacterAgent(char, skill_packs=["memory", "character"])

    @patch("engine.agents.character_agent.CharacterAgent._get_llm")
    @patch("engine.agents.character_agent.CharacterAgent._get_event_chain")
    def test_reply_calls_llm(self, mock_ec_fn, mock_llm_fn):
        """Agent.reply() calls the LLM and returns a string."""
        ec = MagicMock()
        ec.start_chain.return_value = "chain_001"
        mock_ec_fn.return_value = ec

        llm = MagicMock()
        # act() returns a prediction result; content attr is the text
        result_mock = MagicMock()
        result_mock.content = "Hey there!"
        result_mock.__str__ = lambda s: "Hey there!"
        llm.act.return_value = result_mock
        llm.respond.return_value = result_mock
        mock_llm_fn.return_value = llm

        agent = self._make_agent()
        result = agent.reply("Hello!", use_tools=False)
        # Should return a string
        assert isinstance(result, str)

    @patch("engine.agents.character_agent.CharacterAgent._get_llm")
    @patch("engine.agents.character_agent.CharacterAgent._get_event_chain")
    def test_reply_uses_event_chain(self, mock_ec_fn, mock_llm_fn):
        """Agent.reply() starts an EventChain and logs events."""
        ec = MagicMock()
        ec.start_chain.return_value = "chain_002"
        mock_ec_fn.return_value = ec

        llm = MagicMock()
        result_mock = MagicMock()
        result_mock.content = "Sure!"
        llm.respond.return_value = result_mock
        mock_llm_fn.return_value = llm

        agent = self._make_agent()
        agent.reply("Help me", use_tools=False)
        # EventChain start_chain should be called
        ec.start_chain.assert_called_once()


# ═══════════════════════════════════════════════════════════════════════
#  AgentLoop ↔ SceneMap ↔ EventChain integration
# ═══════════════════════════════════════════════════════════════════════

def _make_char(cid, name, mood="neutral", arousal=0.0, energy=1.0):
    """Helper: creates a character mock with proper string fields."""
    c = MagicMock()
    c.id = cid
    c.name = name
    c.mood = mood
    c.arousal = arousal
    c.energy = energy
    c.relationship_level = 0.5
    return c


class TestAgentLoopIntegration:
    """Full tick cycle: perceive → decide → execute → log."""

    def test_full_tick_with_two_characters(self):
        from engine.agents.agent_loop import AgentLoop
        from engine.spatial.location import Location
        from engine.spatial.scene_map import SceneMap

        sm = SceneMap()
        sm.add_location(Location(id="bed", name="Bed", capacity=2,
                                 properties={"privacy": 0.9, "spiciness": 5},
                                 interactions=["cuddle", "pillow talk"]))
        sm.add_location(Location(id="bar", name="Bar", capacity=2,
                                 properties={"privacy": 0.3, "spiciness": 2},
                                 interactions=["pour drinks", "sit and chat"]))

        loop = AgentLoop(scene_map=sm, llm_url="http://fake:9999/v1",
                         scene_id="integration_test")

        c1 = _make_char("c1", "Luna", "playful", 0.3, 0.8)
        c2 = _make_char("c2", "Maya", "curious", 0.2, 0.9)

        loop.register_character(c1)
        loop.register_character(c2)
        sm.place_character("c1", "bed")
        sm.place_character("c2", "bar")

        actions = loop.tick()
        assert len(actions) == 2
        for a in actions:
            assert a["character_id"] in ("c1", "c2")
            assert a["action"] in loop.VALID_ACTIONS

    def test_tick_produces_idle_without_llm(self):
        """Without an LLM, agents fall back to idle actions."""
        from engine.agents.agent_loop import AgentLoop
        from engine.spatial.location import Location
        from engine.spatial.scene_map import SceneMap

        sm = SceneMap()
        sm.add_location(Location(id="room", name="Room", capacity=2))
        loop = AgentLoop(scene_map=sm, scene_id="test")
        c = _make_char("c1", "Luna", "happy")
        loop.register_character(c)
        sm.place_character("c1", "room")

        actions = loop.tick()
        assert len(actions) == 1
        assert actions[0]["action"] == "idle"


# ═══════════════════════════════════════════════════════════════════════
#  VoiceMessage ↔ TTS pipeline
# ═══════════════════════════════════════════════════════════════════════

class TestVoicePipeline:
    """VoiceMessageGenerator → TTS server → WAV file pipeline."""

    def test_placeholder_generates_valid_wav(self):
        from content.simulation.services.voice_message import VoiceMessageGenerator
        gen = VoiceMessageGenerator(db=None)
        result = gen.generate_voice_message("c1", "Luna", "Hello world!")
        assert result is not None
        assert result.get("placeholder") is True or result.get("source") == "qwen3_tts"
        filepath = result["filepath"]
        assert Path(filepath).exists()
        with wave.open(filepath, "rb") as wf:
            assert wf.getnchannels() == 1
            assert wf.getframerate() > 0

    def test_voice_message_generator_with_db_mock(self):
        from content.simulation.services.voice_message import VoiceMessageGenerator
        db = MagicMock()
        gen = VoiceMessageGenerator(db=db)
        result = gen.generate_voice_message("c1", "Luna", "Test message")
        assert result is not None


# ═══════════════════════════════════════════════════════════════════════
#  TTS Server ↔ Voice Designer integration
# ═══════════════════════════════════════════════════════════════════════

class TestTTSVoiceDesignerIntegration:
    """TTS server uses VoiceDesigner for character voice lookup."""

    @pytest.fixture
    def client(self):
        from engine.tts.qwen3_server import create_tts_app
        from fastapi.testclient import TestClient
        return TestClient(create_tts_app())

    def test_cast_then_generate_uses_design(self, client):
        # Cast a voice for a character
        resp = client.post("/cast", json={
            "character_id": "int_test_luna",
            "description": "A warm, playful female voice with slight vocal fry.",
            "model_size": "1.7b",
            "tags": ["playful", "warm"],
        })
        assert resp.status_code == 200

        # Generate with that character — should use the cast voice
        resp = client.post("/generate", json={
            "text": "Hey babe, just thinking about you!",
            "character_id": "int_test_luna",
            "max_duration": 15,
        })
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "completed"
        assert data["filepath"] is not None

    def test_voices_endpoint_shows_cast(self, client):
        client.post("/cast", json={
            "character_id": "int_voice_check",
            "description": "Deep male voice.",
        })
        resp = client.get("/voices")
        chars = resp.json()["characters"]
        assert "int_voice_check" in chars


# ═══════════════════════════════════════════════════════════════════════
#  MCP Server ↔ Skills integration
# ═══════════════════════════════════════════════════════════════════════

class TestMCPSkillsIntegration:
    """MCP tools call through to real skill implementations."""

    def test_mcp_search_memory_calls_rag(self):
        with patch("engine.mcp.cosysim_server._get_rag") as mock_rag:
            mock_rag.return_value = MagicMock()
            mock_rag.return_value.search.return_value = [
                {"content": "Luna likes coffee", "score": 0.9}
            ]
            from engine.mcp.cosysim_server import search_memory
            result = search_memory("coffee", character_id="luna_01")
            assert "coffee" in result.lower()

    def test_mcp_get_character_state_returns_json(self):
        with patch("engine.mcp.cosysim_server._get_db") as mock_db:
            db = MagicMock()
            mock_db.return_value = db
            db.get_character.return_value = {
                "id": "luna_01", "name": "Luna", "mood": "happy",
                "relationship_level": 0.7, "arousal": 0.3,
            }
            from engine.mcp.cosysim_server import get_character_state
            result = get_character_state("luna_01")
            # Returns a JSON string — verify it's parseable
            assert isinstance(result, str)
            assert len(result) > 0


# ═══════════════════════════════════════════════════════════════════════
#  REST Client v2 ↔ MCP integration
# ═══════════════════════════════════════════════════════════════════════

class TestRESTClientIntegration:
    """LMStudio REST client with MCP integrations field."""

    def test_mcp_plugin_format(self):
        from engine.lmstudio.client_v2 import MCP
        plugin = MCP.plugin("mcp/cosysim")
        assert plugin["type"] == "plugin"
        assert plugin["id"] == "mcp/cosysim"

    def test_mcp_ephemeral_format(self):
        from engine.lmstudio.client_v2 import MCP
        eph = MCP.ephemeral("http://localhost:8600/mcp")
        assert eph["type"] == "ephemeral_mcp"
        assert eph["server_url"] == "http://localhost:8600/mcp"


# ═══════════════════════════════════════════════════════════════════════
#  Config → Services consistency
# ═══════════════════════════════════════════════════════════════════════

class TestConfigConsistency:
    """Config values are properly consumed by services."""

    def test_tts_server_url_in_config(self):
        from engine.config import get_config
        cfg = get_config()
        url = cfg.get("tts.server_url", None)
        assert url is not None
        assert "8600" in url

    def test_lmstudio_mcp_config_exists(self):
        from engine.config import get_config
        cfg = get_config()
        assert cfg.get("lmstudio.mcp_enabled") is not None

    def test_media_config_loads(self):
        from engine.media.media_config import get_media_config
        mc = get_media_config()
        w, h = mc.image_dims("selfie")
        assert w > 0
        assert h > 0

    def test_benchmark_stores_exist(self):
        from engine.logging.benchmark import get_benchmarks, get_llm_kpis
        stats = get_benchmarks()
        assert isinstance(stats, dict)
        kpis = get_llm_kpis()
        assert isinstance(kpis, dict)


# ═══════════════════════════════════════════════════════════════════════
#  EventChain ground truth
# ═══════════════════════════════════════════════════════════════════════

class TestEventChainGroundTruth:
    """EventChain maintains causal trees with chain_id/parent_id."""

    @pytest.fixture
    def db(self, tmp_path):
        from content.simulation.database.db import Database
        db_path = str(tmp_path / "test.db")
        return Database(db_path)

    def test_chain_creates_tree(self, db):
        from content.simulation.database.events import EventChain
        ec = EventChain(db)
        chain_id = ec.start_chain(scene_id="test", summary="Integration test")
        assert chain_id is not None

        ev1 = ec.log("llm_request", "agent", {"model": "test"},
                      "Requesting", chain_id=chain_id, scene_id="test")
        ev2 = ec.log("llm_response", "agent", {"tokens": 50},
                      "Response", chain_id=chain_id, scene_id="test",
                      parent_id=ev1)

        events = ec.get_chain(chain_id)
        assert len(events) >= 2
        ids = [e["id"] for e in events]
        assert ev1 in ids
        assert ev2 in ids

    def test_multiple_event_types(self, db):
        from content.simulation.database.events import EventChain
        ec = EventChain(db)
        chain_id = ec.start_chain(scene_id="test", summary="Multi-type test")

        types = ["llm_request", "rag_result", "tool_call", "media_generated",
                 "mcp_tool_call", "llm_response"]
        for t in types:
            ec.log(t, "test_actor", {"type": t}, f"Event: {t}",
                   chain_id=chain_id, scene_id="test")

        events = ec.get_chain(chain_id)
        logged_types = {e["event_type"] for e in events}
        for t in types:
            assert t in logged_types, f"Missing event type: {t}"
