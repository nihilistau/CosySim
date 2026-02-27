"""Tests for the phone assistant cascade routing system."""
from __future__ import annotations

import time
from unittest.mock import MagicMock, patch

import pytest


# ── Fixtures ───────────────────────────────────────────────────────────


@pytest.fixture(autouse=True)
def _reset_singleton():
    """Reset the PhoneAssistant singleton between tests."""
    from engine.assistant.phone_assistant import reset_phone_assistant
    reset_phone_assistant()
    yield
    reset_phone_assistant()


@pytest.fixture
def mock_config():
    """Mock config with sensible phone assistant defaults."""
    cfg = MagicMock()
    cfg.get = MagicMock(side_effect=lambda key, default=None: {
        "phone.assistant.max_history": 50,
        "phone.assistant.tts_enabled": True,
    }.get(key, default))
    return cfg


@pytest.fixture
def pa(mock_config):
    """Create a PhoneAssistant with mocked config."""
    with patch("engine.assistant.phone_assistant.get_config", return_value=mock_config):
        from engine.assistant.phone_assistant import PhoneAssistant
        return PhoneAssistant()


# ── Singleton Tests ────────────────────────────────────────────────────


def test_singleton_creates_instance(mock_config):
    """get_phone_assistant() creates and returns a singleton."""
    with patch("engine.assistant.phone_assistant.get_config", return_value=mock_config):
        from engine.assistant.phone_assistant import get_phone_assistant
        a = get_phone_assistant()
        b = get_phone_assistant()
        assert a is b


def test_reset_clears_singleton(mock_config):
    """reset_phone_assistant() clears the singleton."""
    with patch("engine.assistant.phone_assistant.get_config", return_value=mock_config):
        from engine.assistant.phone_assistant import get_phone_assistant, reset_phone_assistant
        a = get_phone_assistant()
        reset_phone_assistant()
        b = get_phone_assistant()
        assert a is not b


# ── Mode Control Tests ─────────────────────────────────────────────────


def test_default_mode_is_auto(pa):
    """Default routing mode should be auto."""
    assert pa.get_mode() == "auto"


def test_set_mode_passthrough(pa):
    """Setting mode to passthrough should work."""
    result = pa.set_mode("passthrough")
    assert result == "passthrough"
    assert pa.get_mode() == "passthrough"


def test_set_mode_offline(pa):
    """Setting mode to offline should work."""
    result = pa.set_mode("offline")
    assert result == "offline"
    assert pa.get_mode() == "offline"


def test_set_mode_invalid_keeps_current(pa):
    """Setting an invalid mode should keep the current mode."""
    pa.set_mode("passthrough")
    result = pa.set_mode("invalid_mode")
    assert result == "passthrough"


# ── Cascade Routing Tests ─────────────────────────────────────────────


def test_cascade_assistant_hit(pa):
    """When system assistant responds, it's the source."""
    with patch.object(pa, "_try_system_assistant", return_value={"reply": "Hello from Aria"}):
        result = pa.chat("hello")
    assert result["reply"] == "Hello from Aria"
    assert result["source"] == "assistant"


def test_cascade_nexus_hit(pa):
    """When assistant fails and Nexus answers, Nexus is the source."""
    with patch.object(pa, "_try_system_assistant", return_value=None), \
         patch.object(pa, "_try_nexus", return_value="From Nexus"):
        result = pa.chat("what is MCP?")
    assert result["reply"] == "From Nexus"
    assert result["source"] == "nexus"


def test_cascade_anythingllm_hit(pa):
    """When assistant and Nexus fail, AnythingLLM responds."""
    with patch.object(pa, "_try_system_assistant", return_value=None), \
         patch.object(pa, "_try_nexus", return_value=None), \
         patch.object(pa, "_try_anythingllm", return_value="From ALLM"):
        result = pa.chat("offline question")
    assert result["reply"] == "From ALLM"
    assert result["source"] == "anythingllm"


def test_cascade_fallback(pa):
    """When all tiers fail, fallback message is returned."""
    with patch.object(pa, "_try_system_assistant", return_value=None), \
         patch.object(pa, "_try_nexus", return_value=None), \
         patch.object(pa, "_try_anythingllm", return_value=None):
        result = pa.chat("nothing works")
    assert result["source"] == "fallback"
    assert "offline" in result["reply"].lower()


def test_passthrough_skips_anythingllm(pa):
    """Passthrough mode should not try AnythingLLM."""
    with patch.object(pa, "_try_system_assistant", return_value=None), \
         patch.object(pa, "_try_nexus", return_value=None), \
         patch.object(pa, "_try_anythingllm") as mock_allm:
        result = pa.chat("test", mode="passthrough")
    mock_allm.assert_not_called()
    assert result["source"] == "fallback"


def test_offline_skips_assistant_and_nexus(pa):
    """Offline mode should skip assistant and Nexus, only try AnythingLLM."""
    with patch.object(pa, "_try_system_assistant") as mock_asst, \
         patch.object(pa, "_try_nexus") as mock_nexus, \
         patch.object(pa, "_try_anythingllm", return_value="Offline reply"):
        result = pa.chat("test", mode="offline")
    mock_asst.assert_not_called()
    mock_nexus.assert_not_called()
    assert result["source"] == "anythingllm"


def test_mode_override_per_request(pa):
    """Per-request mode override should not change default mode."""
    pa.set_mode("passthrough")
    with patch.object(pa, "_try_system_assistant", return_value=None), \
         patch.object(pa, "_try_nexus", return_value=None), \
         patch.object(pa, "_try_anythingllm", return_value="offline"):
        result = pa.chat("test", mode="offline")
    assert result["source"] == "anythingllm"
    assert pa.get_mode() == "passthrough"


# ── Tier Implementation Tests ──────────────────────────────────────────


def test_try_system_assistant_dict_response(pa):
    """_try_system_assistant handles dict responses."""
    mock_assistant = MagicMock()
    mock_assistant.chat.return_value = {"reply": "hello"}
    with patch("engine.assistant.system_assistant.get_assistant", return_value=mock_assistant):
        result = pa._try_system_assistant("test")
    assert result == {"reply": "hello"}


def test_try_system_assistant_string_response(pa):
    """_try_system_assistant wraps string responses."""
    mock_assistant = MagicMock()
    mock_assistant.chat.return_value = "hello string"
    with patch("engine.assistant.system_assistant.get_assistant", return_value=mock_assistant):
        result = pa._try_system_assistant("test")
    assert result == {"reply": "hello string"}


def test_try_system_assistant_exception_returns_none(pa):
    """_try_system_assistant returns None on exception."""
    with patch("engine.assistant.system_assistant.get_assistant", side_effect=RuntimeError("offline")):
        result = pa._try_system_assistant("test")
    assert result is None


def test_try_nexus_high_confidence(pa):
    """_try_nexus returns answer when confidence > 0.3."""
    mock_client = MagicMock()
    mock_client.ask.return_value = {"answer": "Nexus answer", "confidence": 0.8}
    with patch("engine.nexus.client.get_nexus_client", return_value=mock_client):
        result = pa._try_nexus("test")
    assert result == "Nexus answer"


def test_try_nexus_low_confidence(pa):
    """_try_nexus returns None when confidence is too low."""
    mock_client = MagicMock()
    mock_client.ask.return_value = {"answer": "Low conf", "confidence": 0.1}
    with patch("engine.nexus.client.get_nexus_client", return_value=mock_client):
        result = pa._try_nexus("test")
    assert result is None


def test_try_nexus_exception_returns_none(pa):
    """_try_nexus returns None on exception."""
    with patch("engine.nexus.client.get_nexus_client", side_effect=RuntimeError("offline")):
        result = pa._try_nexus("test")
    assert result is None


def test_try_anythingllm_success(pa):
    """_try_anythingllm extracts textResponse from result."""
    mock_client = MagicMock()
    mock_client.chat.return_value = {"textResponse": "ALLM says hi"}
    with patch("engine.integrations.anythingllm.get_anythingllm_client", return_value=mock_client):
        result = pa._try_anythingllm("test")
    assert result == "ALLM says hi"


def test_try_anythingllm_exception_returns_none(pa):
    """_try_anythingllm returns None on exception."""
    with patch("engine.integrations.anythingllm.get_anythingllm_client", side_effect=RuntimeError("nope")):
        result = pa._try_anythingllm("test")
    assert result is None


# ── TTS Tests ──────────────────────────────────────────────────────────


def test_voice_enabled_triggers_tts(pa):
    """When voice=True, TTS synthesis should be attempted."""
    with patch.object(pa, "_try_system_assistant", return_value={"reply": "voice me"}), \
         patch.object(pa, "_synthesize_voice", return_value="/audio/reply.wav") as mock_tts:
        result = pa.chat("hello", voice=True)
    mock_tts.assert_called_once_with("voice me")
    assert result["voice_url"] == "/audio/reply.wav"


def test_voice_disabled_skips_tts(pa):
    """When voice=False, TTS synthesis should not be attempted."""
    with patch.object(pa, "_try_system_assistant", return_value={"reply": "no voice"}), \
         patch.object(pa, "_synthesize_voice") as mock_tts:
        result = pa.chat("hello", voice=False)
    mock_tts.assert_not_called()
    assert result["voice_url"] is None


def test_synthesize_voice_calls_tts_manager(pa):
    """_synthesize_voice delegates to TTS manager."""
    mock_manager = MagicMock()
    mock_manager.synthesize.return_value = "/tmp/audio.wav"
    with patch("engine.tts.tts_manager.get_tts_manager", return_value=mock_manager):
        result = pa._synthesize_voice("test text")
    assert result == "/tmp/audio.wav"
    mock_manager.synthesize.assert_called_once_with("test text")


def test_synthesize_voice_exception_returns_none(pa):
    """_synthesize_voice returns None on failure."""
    with patch("engine.tts.tts_manager.get_tts_manager", side_effect=RuntimeError("no tts")):
        result = pa._synthesize_voice("test")
    assert result is None


# ── History Tests ──────────────────────────────────────────────────────


def test_chat_stores_history(pa):
    """Each chat stores user + assistant messages in history."""
    with patch.object(pa, "_try_system_assistant", return_value={"reply": "hi"}):
        pa.chat("hello")
    history = pa.get_history()
    assert len(history) == 2
    assert history[0]["role"] == "user"
    assert history[0]["text"] == "hello"
    assert history[1]["role"] == "assistant"
    assert history[1]["text"] == "hi"
    assert history[1]["source"] == "assistant"


def test_history_limit(pa):
    """History should be capped at max_history * 2 entries."""
    with patch.object(pa, "_try_system_assistant", return_value={"reply": "ok"}):
        for i in range(60):
            pa.chat(f"msg {i}")
    assert len(pa._history) <= 100


def test_get_history_with_limit(pa):
    """get_history(limit=N) returns last N*2 entries."""
    with patch.object(pa, "_try_system_assistant", return_value={"reply": "ok"}):
        for i in range(10):
            pa.chat(f"msg {i}")
    result = pa.get_history(limit=3)
    assert len(result) == 6  # 3 pairs


def test_clear_history(pa):
    """clear_history clears all entries and returns count."""
    with patch.object(pa, "_try_system_assistant", return_value={"reply": "ok"}):
        pa.chat("hello")
    count = pa.clear_history()
    assert count == 2
    assert len(pa.get_history()) == 0


# ── Stats Tests ────────────────────────────────────────────────────────


def test_stats_track_queries(pa):
    """Stats should count total queries."""
    with patch.object(pa, "_try_system_assistant", return_value={"reply": "ok"}):
        pa.chat("one")
        pa.chat("two")
    stats = pa.stats()
    assert stats["queries"] == 2
    assert stats["hits"]["assistant"] == 2


def test_stats_hit_rates(pa):
    """Hit rates should be calculated correctly."""
    with patch.object(pa, "_try_system_assistant", return_value={"reply": "ok"}):
        pa.chat("one")
    with patch.object(pa, "_try_system_assistant", return_value=None), \
         patch.object(pa, "_try_nexus", return_value="nexus hit"), \
         patch.object(pa, "_try_anythingllm", return_value=None):
        pa.chat("two")
    stats = pa.stats()
    assert stats["queries"] == 2
    assert stats["hit_rates"]["assistant"] == 0.5
    assert stats["hit_rates"]["nexus"] == 0.5


def test_empty_stats_no_division_error(pa):
    """Stats with zero queries should not cause division by zero."""
    stats = pa.stats()
    assert stats["queries"] == 0
    assert stats["hit_rates"]["assistant"] == 0


# ── Status Tests ───────────────────────────────────────────────────────


def test_status_connectivity(pa):
    """Status should check connectivity for all tiers."""
    with patch("engine.assistant.system_assistant.get_assistant"), \
         patch("engine.nexus.client.get_nexus_client"):
        status = pa.status()
    assert status["mode"] == "auto"
    assert status["connected"]["assistant"] is True
    assert status["connected"]["nexus"] is True
    assert "stats" in status


def test_status_offline_services(pa):
    """Status should report False for unavailable services."""
    with patch("engine.assistant.system_assistant.get_assistant", side_effect=RuntimeError), \
         patch("engine.nexus.client.get_nexus_client", side_effect=RuntimeError), \
         patch("engine.integrations.anythingllm.get_anythingllm_client", side_effect=RuntimeError):
        status = pa.status()
    assert status["connected"]["assistant"] is False
    assert status["connected"]["nexus"] is False
    assert status["connected"]["anythingllm"] is False


# ── Response Structure Tests ───────────────────────────────────────────


def test_response_has_required_fields(pa):
    """Response dict should have reply, source, voice_url, timestamp."""
    with patch.object(pa, "_try_system_assistant", return_value={"reply": "test"}):
        result = pa.chat("hello")
    assert "reply" in result
    assert "source" in result
    assert "voice_url" in result
    assert "timestamp" in result
    assert isinstance(result["timestamp"], float)
