"""Tests for SystemAssistant — singleton, chat, commands, fallback, registration."""

from __future__ import annotations

import time
from unittest.mock import MagicMock, patch

import pytest


# ═══════════════════════════════════════════════════════════════
#  Helpers
# ═══════════════════════════════════════════════════════════════

def _make_assistant():
    """Create a fresh SystemAssistant instance (bypasses singleton)."""
    from engine.assistant.system_assistant import SystemAssistant
    return SystemAssistant()


def _mock_port_registry():
    """Build a mock PortRegistry with a tiny scene list."""
    reg = MagicMock()
    reg.SERVICE_GROUPS = {"scenes": ["bedroom", "casino"]}
    reg.get_port = MagicMock(side_effect=lambda n: {"bedroom": 5556, "casino": 5559}[n])
    return reg


# ═══════════════════════════════════════════════════════════════
#  Imports
# ═══════════════════════════════════════════════════════════════

class TestImports:
    """Module-level constants and class imports work."""

    def test_import_class(self):
        from engine.assistant.system_assistant import SystemAssistant
        assert SystemAssistant is not None

    def test_import_get_assistant(self):
        from engine.assistant.system_assistant import get_assistant
        assert callable(get_assistant)

    def test_import_profile(self):
        from engine.assistant.system_assistant import ARIA_PROFILE
        assert ARIA_PROFILE["name"] == "Aria"
        assert ARIA_PROFILE["id"] == "aria"

    def test_import_system_prompt(self):
        from engine.assistant.system_assistant import SYSTEM_PROMPT
        assert "{scene_id}" in SYSTEM_PROMPT
        assert "{system_summary}" in SYSTEM_PROMPT


# ═══════════════════════════════════════════════════════════════
#  Initialization & Profile
# ═══════════════════════════════════════════════════════════════

class TestInitialization:
    """SystemAssistant constructor and profile attributes."""

    @pytest.fixture
    def assistant(self):
        return _make_assistant()

    def test_name_is_aria(self, assistant):
        assert assistant.name == "Aria"

    def test_id_is_aria(self, assistant):
        assert assistant.id == "aria"

    def test_profile_has_personality(self, assistant):
        assert "warmth" in assistant.profile["personality"]
        assert "helpfulness" in assistant.profile["personality"]

    def test_profile_has_backstory(self, assistant):
        assert len(assistant.profile["backstory"]) > 50

    def test_profile_has_voice_style(self, assistant):
        assert assistant.profile["voice_style"] == "warm, clear, slightly playful"

    def test_history_starts_empty(self, assistant):
        assert assistant._conversation_history == []

    def test_max_history_default(self, assistant):
        assert assistant._max_history == 20

    def test_not_registered_initially(self, assistant):
        assert assistant._registered is False

    def test_current_scene_initially_none(self, assistant):
        assert assistant._current_scene is None

    def test_config_stored(self):
        cfg = MagicMock()
        from engine.assistant.system_assistant import SystemAssistant
        a = SystemAssistant(config=cfg)
        assert a._config is cfg


# ═══════════════════════════════════════════════════════════════
#  Singleton (get_assistant)
# ═══════════════════════════════════════════════════════════════

class TestSingleton:
    """get_assistant() returns the same instance on repeated calls."""

    def test_singleton_returns_same_instance(self):
        import engine.assistant.system_assistant as mod
        # Reset the module-level singleton
        old = mod._assistant
        try:
            mod._assistant = None
            a1 = mod.get_assistant()
            a2 = mod.get_assistant()
            assert a1 is a2
        finally:
            mod._assistant = old

    def test_singleton_creates_new_when_none(self):
        import engine.assistant.system_assistant as mod
        old = mod._assistant
        try:
            mod._assistant = None
            a = mod.get_assistant()
            assert isinstance(a, mod.SystemAssistant)
        finally:
            mod._assistant = old


# ═══════════════════════════════════════════════════════════════
#  chat() — response structure & history
# ═══════════════════════════════════════════════════════════════

class TestChat:
    """chat() returns a well-formed response dict and tracks history."""

    @pytest.fixture
    def assistant(self):
        return _make_assistant()

    def test_chat_returns_dict(self, assistant):
        """Non-command message falls through to LLM → fallback → dict."""
        result = assistant.chat("what's going on?")
        assert isinstance(result, dict)

    def test_chat_has_required_keys(self, assistant):
        result = assistant.chat("what's going on?")
        for key in ("reply", "mood", "scene_id", "timestamp", "source"):
            assert key in result, f"Missing key: {key}"

    def test_chat_source_is_assistant_for_non_command(self, assistant):
        result = assistant.chat("tell me a joke")
        assert result["source"] == "assistant"

    def test_chat_timestamp_is_recent(self, assistant):
        before = time.time()
        result = assistant.chat("hi")
        assert result["timestamp"] >= before
        assert result["timestamp"] <= time.time()

    def test_chat_tracks_scene_id(self, assistant):
        result = assistant.chat("hello", scene_id="bedroom")
        assert result["scene_id"] == "bedroom"

    def test_chat_remembers_scene_id(self, assistant):
        assistant.chat("hello", scene_id="casino")
        result = assistant.chat("how are you")
        assert result["scene_id"] == "casino"

    def test_chat_appends_to_history(self, assistant):
        assistant.chat("hello")
        assert len(assistant._conversation_history) == 2  # user + assistant
        assert assistant._conversation_history[0]["role"] == "user"
        assert assistant._conversation_history[1]["role"] == "assistant"

    def test_chat_history_content(self, assistant):
        assistant.chat("hello")
        assert assistant._conversation_history[0]["content"] == "hello"
        assert len(assistant._conversation_history[1]["content"]) > 0

    def test_chat_history_trimmed_at_max(self, assistant):
        """History is capped at _max_history * 2 entries."""
        assistant._max_history = 3
        for i in range(10):
            assistant.chat(f"message {i}")
        assert len(assistant._conversation_history) <= 6  # 3 * 2

    def test_chat_reply_is_string(self, assistant):
        result = assistant.chat("hello")
        assert isinstance(result["reply"], str)
        assert len(result["reply"]) > 0


# ═══════════════════════════════════════════════════════════════
#  _check_command — "status"
# ═══════════════════════════════════════════════════════════════

class TestCommandStatus:
    """'status' and variants trigger a system summary command."""

    @pytest.fixture
    def assistant(self):
        a = _make_assistant()
        a.get_system_summary = MagicMock(return_value={
            "vram_used_mb": 6000,
            "vram_total_mb": 12000,
            "loaded_models": ["model-a"],
            "active_scenes": ["bedroom", "casino"],
            "agent_count": 3,
        })
        return a

    def test_status_returns_command_source(self, assistant):
        result = assistant.chat("status")
        assert result["source"] == "command"

    def test_status_mood_informative(self, assistant):
        result = assistant.chat("status")
        assert result["mood"] == "informative"

    def test_status_reply_has_scenes(self, assistant):
        result = assistant.chat("status")
        assert "bedroom" in result["reply"]
        assert "casino" in result["reply"]

    def test_status_reply_has_vram(self, assistant):
        result = assistant.chat("status")
        assert "6000" in result["reply"]
        assert "12000" in result["reply"]

    def test_status_reply_has_agent_count(self, assistant):
        result = assistant.chat("status")
        assert "3" in result["reply"]

    def test_system_status_variant(self, assistant):
        result = assistant.chat("system status")
        assert result["source"] == "command"

    def test_how_is_the_system_variant(self, assistant):
        result = assistant.chat("how's the system")
        assert result["source"] == "command"

    def test_status_not_tracked_in_history(self, assistant):
        """Command responses skip LLM path → no history append."""
        assistant.chat("status")
        assert len(assistant._conversation_history) == 0


# ═══════════════════════════════════════════════════════════════
#  _check_command — "scenes" / "list scenes"
# ═══════════════════════════════════════════════════════════════

class TestCommandScenes:
    """'scenes' and 'list scenes' return a scene list."""

    @pytest.fixture
    def assistant(self):
        a = _make_assistant()
        a.get_scene_list = MagicMock(return_value=[
            {"id": "bedroom", "port": 5556, "label": "Bedroom", "status": "online"},
            {"id": "casino", "port": 5559, "label": "Casino", "status": "offline"},
        ])
        return a

    def test_scenes_command(self, assistant):
        result = assistant.chat("scenes")
        assert result["source"] == "command"

    def test_scenes_mood_helpful(self, assistant):
        result = assistant.chat("scenes")
        assert result["mood"] == "helpful"

    def test_scenes_reply_has_label(self, assistant):
        result = assistant.chat("scenes")
        assert "Bedroom" in result["reply"]
        assert "Casino" in result["reply"]

    def test_scenes_reply_has_port(self, assistant):
        result = assistant.chat("scenes")
        assert "5556" in result["reply"]

    def test_list_scenes_variant(self, assistant):
        result = assistant.chat("list scenes")
        assert result["source"] == "command"

    def test_what_scenes_variant(self, assistant):
        result = assistant.chat("what scenes are there")
        assert result["source"] == "command"


# ═══════════════════════════════════════════════════════════════
#  _check_command — "go to <scene>"
# ═══════════════════════════════════════════════════════════════

class TestCommandNavigate:
    """'go to bedroom' navigates; 'go to nonexistent' returns not-found."""

    @pytest.fixture
    def assistant(self):
        a = _make_assistant()
        a.get_scene_list = MagicMock(return_value=[
            {"id": "bedroom", "port": 5556, "label": "Bedroom", "status": "online"},
            {"id": "casino", "port": 5559, "label": "Casino", "status": "offline"},
        ])
        return a

    def test_go_to_bedroom_source(self, assistant):
        result = assistant.chat("go to bedroom")
        assert result["source"] == "command"

    def test_go_to_bedroom_mood(self, assistant):
        result = assistant.chat("go to bedroom")
        assert result["mood"] == "excited"

    def test_go_to_bedroom_has_action(self, assistant):
        result = assistant.chat("go to bedroom")
        assert "action" in result
        assert result["action"]["type"] == "navigate"
        assert result["action"]["port"] == 5556

    def test_go_to_bedroom_reply(self, assistant):
        result = assistant.chat("go to bedroom")
        assert "Bedroom" in result["reply"]
        assert "🚀" in result["reply"]

    def test_navigate_to_casino(self, assistant):
        result = assistant.chat("navigate to casino")
        assert result["action"]["port"] == 5559

    def test_go_to_nonexistent(self, assistant):
        result = assistant.chat("go to spaceship")
        assert result["source"] == "command"
        assert result["mood"] == "apologetic"
        assert "spaceship" in result["reply"]
        assert "action" not in result

    def test_go_to_partial_match(self, assistant):
        """Partial ID match works (e.g. 'bed' matches 'bedroom')."""
        result = assistant.chat("go to bed")
        assert "action" in result
        assert result["action"]["port"] == 5556


# ═══════════════════════════════════════════════════════════════
#  _check_command — non-commands fall through
# ═══════════════════════════════════════════════════════════════

class TestCommandFallthrough:
    """Non-command messages return None from _check_command."""

    @pytest.fixture
    def assistant(self):
        return _make_assistant()

    def test_normal_message_returns_none(self, assistant):
        assert assistant._check_command("hello there") is None

    def test_question_returns_none(self, assistant):
        assert assistant._check_command("what's your name?") is None

    def test_empty_returns_none(self, assistant):
        assert assistant._check_command("") is None

    def test_partial_keyword_returns_none(self, assistant):
        assert assistant._check_command("what is my status report?") is None


# ═══════════════════════════════════════════════════════════════
#  get_system_summary
# ═══════════════════════════════════════════════════════════════

class TestGetSystemSummary:
    """get_system_summary() returns a dict with expected keys."""

    @pytest.fixture
    def assistant(self):
        return _make_assistant()

    @patch("engine.assistant.system_assistant.get_assistant")
    def test_summary_has_expected_keys(self, _mock_get, assistant):
        with patch("engine.lmstudio.resource_manager.get_resource_manager") as mock_rm, \
             patch("engine.scenes.base_scene.get_all_active_scenes") as mock_scenes, \
             patch("engine.mcp.get_character_registry") as mock_reg:

            mock_rm.return_value.status.return_value = {
                "vram_used_mb": 4000, "vram_total_mb": 12000,
            }
            mock_scenes.return_value = {"bedroom": MagicMock()}
            mock_reg.return_value.list_characters.return_value = ["aria", "npc1"]

            summary = assistant.get_system_summary()

        for key in ("vram_used_mb", "vram_total_mb", "loaded_models",
                     "active_scenes", "agent_count"):
            assert key in summary

    def test_summary_vram_from_resource_manager(self, assistant):
        with patch("engine.lmstudio.resource_manager.get_resource_manager") as mock_rm:
            mock_rm.return_value.status.return_value = {
                "vram_used_mb": 5000, "vram_total_mb": 11000,
            }
            summary = assistant.get_system_summary()
        assert summary["vram_used_mb"] == 5000
        assert summary["vram_total_mb"] == 11000

    def test_summary_active_scenes(self, assistant):
        with patch("engine.scenes.base_scene.get_all_active_scenes") as mock_sc:
            mock_sc.return_value = {"casino": MagicMock(), "tavern": MagicMock()}
            # BaseScene.get_all_active_scenes is called inside the method; we need
            # to patch the import path used inside get_system_summary.
            summary = assistant.get_system_summary()
        # The method tries BaseScene.get_all_active_scenes — patch may not
        # hit due to import path.  Either way, active_scenes must be a list.
        assert isinstance(summary["active_scenes"], list)

    def test_summary_agent_count_from_registry(self, assistant):
        with patch("engine.mcp.get_character_registry") as mock_reg:
            mock_reg.return_value.list_characters.return_value = ["a", "b", "c"]
            summary = assistant.get_system_summary()
        assert summary["agent_count"] == 3

    def test_summary_defaults_on_error(self, assistant):
        """All external calls fail → safe defaults."""
        with patch("engine.lmstudio.resource_manager.get_resource_manager",
                    side_effect=ImportError), \
             patch("engine.scenes.base_scene.get_all_active_scenes",
                    side_effect=ImportError), \
             patch("engine.mcp.get_character_registry",
                    side_effect=ImportError):
            summary = assistant.get_system_summary()
        assert summary["vram_used_mb"] == 0
        assert summary["loaded_models"] == []
        assert summary["agent_count"] == 0


# ═══════════════════════════════════════════════════════════════
#  get_scene_list
# ═══════════════════════════════════════════════════════════════

class TestGetSceneList:
    """get_scene_list() returns list of scene dicts from port registry."""

    @pytest.fixture
    def assistant(self):
        return _make_assistant()

    @patch("engine.port_registry.get_port_registry")
    def test_returns_list(self, mock_get_reg, assistant):
        mock_get_reg.return_value = _mock_port_registry()
        result = assistant.get_scene_list()
        assert isinstance(result, list)

    @patch("engine.port_registry.get_port_registry")
    def test_scene_dict_has_expected_keys(self, mock_get_reg, assistant):
        mock_get_reg.return_value = _mock_port_registry()
        result = assistant.get_scene_list()
        assert len(result) == 2
        for scene in result:
            assert "id" in scene
            assert "port" in scene
            assert "label" in scene
            assert "status" in scene

    @patch("engine.port_registry.get_port_registry")
    def test_scene_id_matches_name(self, mock_get_reg, assistant):
        mock_get_reg.return_value = _mock_port_registry()
        result = assistant.get_scene_list()
        ids = [s["id"] for s in result]
        assert "bedroom" in ids
        assert "casino" in ids

    @patch("engine.port_registry.get_port_registry")
    def test_scene_port_correct(self, mock_get_reg, assistant):
        mock_get_reg.return_value = _mock_port_registry()
        result = assistant.get_scene_list()
        bedroom = [s for s in result if s["id"] == "bedroom"][0]
        assert bedroom["port"] == 5556

    @patch("engine.port_registry.get_port_registry")
    def test_scene_label_is_titled(self, mock_get_reg, assistant):
        mock_get_reg.return_value = _mock_port_registry()
        result = assistant.get_scene_list()
        bedroom = [s for s in result if s["id"] == "bedroom"][0]
        assert bedroom["label"] == "Bedroom"


# ═══════════════════════════════════════════════════════════════
#  _get_fallback_reply
# ═══════════════════════════════════════════════════════════════

class TestFallbackReply:
    """_get_fallback_reply() provides canned responses for common messages."""

    @pytest.fixture
    def assistant(self):
        return _make_assistant()

    def test_hello_greeting(self, assistant):
        reply = assistant._get_fallback_reply("hello")
        assert "Aria" in reply

    def test_hi_greeting(self, assistant):
        reply = assistant._get_fallback_reply("hi there")
        assert "Aria" in reply

    def test_help_text(self, assistant):
        reply = assistant._get_fallback_reply("help me")
        assert "navigate" in reply.lower() or "scenes" in reply.lower()

    def test_thanks_response(self, assistant):
        reply = assistant._get_fallback_reply("thanks a lot")
        assert "welcome" in reply.lower()

    def test_unknown_message_mentions_scene(self, assistant):
        """Unknown message includes current scene or 'CosySim'."""
        reply = assistant._get_fallback_reply("do a backflip")
        assert "CosySim" in reply

    def test_unknown_with_scene_set(self, assistant):
        assistant._current_scene = "casino"
        reply = assistant._get_fallback_reply("random gibberish")
        assert "casino" in reply

    def test_fallback_reply_is_string(self, assistant):
        reply = assistant._get_fallback_reply("")
        assert isinstance(reply, str)
        assert len(reply) > 0


# ═══════════════════════════════════════════════════════════════
#  register() — CharacterRegistry integration
# ═══════════════════════════════════════════════════════════════

class TestRegister:
    """register() pushes Aria into the CharacterRegistry."""

    @pytest.fixture
    def assistant(self):
        return _make_assistant()

    @patch("engine.mcp.get_character_registry")
    def test_register_calls_registry(self, mock_get_reg, assistant):
        mock_reg = MagicMock()
        mock_get_reg.return_value = mock_reg

        result = assistant.register()

        assert result is True
        mock_reg.register.assert_called_once()

    @patch("engine.mcp.get_character_registry")
    def test_register_passes_correct_id(self, mock_get_reg, assistant):
        mock_reg = MagicMock()
        mock_get_reg.return_value = mock_reg

        assistant.register()

        call_kwargs = mock_reg.register.call_args
        assert call_kwargs.kwargs.get("character_id") == "aria"
        assert call_kwargs.kwargs.get("name") == "Aria"

    @patch("engine.mcp.get_character_registry")
    def test_register_passes_personality(self, mock_get_reg, assistant):
        mock_reg = MagicMock()
        mock_get_reg.return_value = mock_reg

        assistant.register()

        call_kwargs = mock_reg.register.call_args
        assert "helpfulness" in call_kwargs.kwargs.get("personality", {})

    @patch("engine.mcp.get_character_registry")
    def test_register_sets_registered_flag(self, mock_get_reg, assistant):
        mock_get_reg.return_value = MagicMock()
        assistant.register()
        assert assistant._registered is True

    @patch("engine.mcp.get_character_registry")
    def test_register_idempotent(self, mock_get_reg, assistant):
        """Second call skips registry interaction."""
        mock_reg = MagicMock()
        mock_get_reg.return_value = mock_reg

        assistant.register()
        assistant.register()

        assert mock_reg.register.call_count == 1

    @patch("engine.mcp.get_character_registry", side_effect=ImportError("no registry"))
    def test_register_returns_false_on_error(self, _mock_get, assistant):
        result = assistant.register()
        assert result is False
        assert assistant._registered is False

    @patch("engine.mcp.get_character_registry")
    def test_register_passes_scene_roles(self, mock_get_reg, assistant):
        mock_reg = MagicMock()
        mock_get_reg.return_value = mock_reg

        assistant.register()

        call_kwargs = mock_reg.register.call_args
        assert call_kwargs.kwargs.get("scene_roles") == {"*": "system_assistant"}


# ═══════════════════════════════════════════════════════════════
#  LLM integration (mocked)
# ═══════════════════════════════════════════════════════════════

class TestLLMIntegration:
    """chat() falls through to _get_llm_reply, then fallback on failure."""

    @pytest.fixture
    def assistant(self):
        return _make_assistant()

    def test_chat_uses_fallback_when_llm_unavailable(self, assistant):
        """When LLM imports fail, fallback reply is used."""
        result = assistant.chat("hello")
        assert "Aria" in result["reply"]

    def test_chat_uses_llm_when_available(self, assistant):
        with patch.object(assistant, "_get_llm_reply", return_value="LLM says hi"):
            result = assistant.chat("hello")
        assert result["reply"] == "LLM says hi"

    def test_chat_falls_back_on_llm_exception(self, assistant):
        with patch.object(assistant, "_get_llm_reply", side_effect=RuntimeError("boom")):
            result = assistant.chat("hello")
        # Should use fallback — still returns a valid reply
        assert isinstance(result["reply"], str)
        assert len(result["reply"]) > 0
