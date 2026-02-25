"""
tests/test_character_agent.py
==============================

Unit tests for engine.agents.character_agent.CharacterAgent:
  - Construction with mocked VirtualAgentManager
  - reply() delegation to underlying VirtualAgent
  - Capabilities assignment (TEXT, MEMORY, TOOLS, GOVERNED)
  - State/model accessors
  - Governance context forwarding
  - Edge cases: missing character data

All tests are offline — no LLM, no DB, no network required.
"""
from __future__ import annotations

import types
import unittest
from unittest.mock import MagicMock, patch

from engine.agents.protocols import AgentCapability


# ── helpers ──────────────────────────────────────────────────────────────

def _make_character(name: str = "Aria", cid: str = "aria") -> object:
    """Return a minimal character-data-like object."""
    obj = types.SimpleNamespace()
    obj.id = cid
    obj.name = name
    obj.mood = "neutral"
    obj.arousal = 0.0
    obj.energy = 1.0
    obj.warmth = 0.8
    obj.description = "A test character."
    obj.backstory = "Backstory text."
    obj.appearance = "brunette hair, green eyes"
    obj.personality = {"warmth": 0.9, "curiosity": 0.8}
    return obj


def _mock_config():
    """Return a dict-based mock config."""
    defaults = {
        "lmstudio.base_url": "http://localhost:1234",
        "lmstudio.mcp_enabled": False,
    }
    mock = MagicMock()
    mock.get = lambda key, default=None: defaults.get(key, default)
    return mock


def _build_agent(character=None, config=None, skill_packs=None,
                 use_mcp=False, scene=None, **kwargs):
    """Create a CharacterAgent with mocked VirtualAgentManager."""
    if character is None:
        character = _make_character()
    if config is None:
        config = _mock_config()

    mock_virtual = MagicMock()
    mock_virtual.reply.return_value = "Hello from virtual agent."
    mock_virtual.quick_query.return_value = "Quick answer."

    mock_mgr = MagicMock()
    mock_mgr.create_agent.return_value = mock_virtual

    with patch("engine.agents.virtual_agent_manager.get_virtual_agent_manager",
               return_value=mock_mgr):
        from engine.agents.character_agent import CharacterAgent
        agent = CharacterAgent(
            character,
            config=config,
            skill_packs=skill_packs,
            use_mcp=use_mcp,
            scene=scene,
            **kwargs,
        )
    return agent, mock_virtual, mock_mgr


# ═══════════════════════════════════════════════════════════════════════
#  CONSTRUCTION
# ═══════════════════════════════════════════════════════════════════════

class TestCharacterAgentConstruction(unittest.TestCase):
    def test_creates_with_character(self):
        agent, _, _ = _build_agent()
        self.assertEqual(agent.character.name, "Aria")

    def test_creates_virtual_agent_via_manager(self):
        _, _, mgr = _build_agent()
        mgr.create_agent.assert_called_once()

    def test_stores_config(self):
        cfg = _mock_config()
        agent, _, _ = _build_agent(config=cfg)
        self.assertIs(agent.config, cfg)

    def test_stores_scene(self):
        agent, _, _ = _build_agent(scene="bedroom")
        self.assertEqual(agent.scene, "bedroom")

    def test_default_skill_packs_empty(self):
        agent, _, _ = _build_agent()
        self.assertEqual(agent.skill_packs, [])

    def test_model_stored(self):
        agent, _, _ = _build_agent(model="test-model")
        self.assertEqual(agent.model, "test-model")

    def test_max_context_memories_default(self):
        agent, _, _ = _build_agent()
        self.assertEqual(agent.max_context_memories, 5)

    def test_max_context_memories_override(self):
        agent, _, _ = _build_agent(max_context_memories=10)
        self.assertEqual(agent.max_context_memories, 10)


# ═══════════════════════════════════════════════════════════════════════
#  CAPABILITIES
# ═══════════════════════════════════════════════════════════════════════

class TestCharacterAgentCapabilities(unittest.TestCase):
    def test_base_capabilities(self):
        agent, _, _ = _build_agent()
        self.assertIn(AgentCapability.TEXT, agent.capabilities)
        self.assertIn(AgentCapability.MEMORY, agent.capabilities)

    def test_tools_capability_with_skill_packs(self):
        agent, _, _ = _build_agent(skill_packs=["comfyui"])
        self.assertIn(AgentCapability.TOOLS, agent.capabilities)

    def test_no_tools_capability_without_skill_packs(self):
        agent, _, _ = _build_agent(skill_packs=None)
        self.assertNotIn(AgentCapability.TOOLS, agent.capabilities)

    def test_governed_capability_with_mcp(self):
        agent, _, _ = _build_agent(use_mcp=True)
        self.assertIn(AgentCapability.GOVERNED, agent.capabilities)

    def test_no_governed_capability_without_mcp(self):
        agent, _, _ = _build_agent(use_mcp=False)
        self.assertNotIn(AgentCapability.GOVERNED, agent.capabilities)

    def test_mcp_from_config(self):
        cfg = MagicMock()
        cfg.get = lambda key, default=None: True if key == "lmstudio.mcp_enabled" else default
        agent, _, _ = _build_agent(config=cfg, use_mcp=False)
        self.assertTrue(agent.use_mcp)
        self.assertIn(AgentCapability.GOVERNED, agent.capabilities)


# ═══════════════════════════════════════════════════════════════════════
#  REPLY DELEGATION
# ═══════════════════════════════════════════════════════════════════════

class TestCharacterAgentReply(unittest.TestCase):
    def test_reply_delegates_to_virtual(self):
        agent, mock_v, _ = _build_agent()
        result = agent.reply("Hello")
        mock_v.reply.assert_called_once_with(
            "Hello",
            chain_id=None,
            history=None,
            use_tools=True,
            governance_context=None,
        )
        self.assertEqual(result, "Hello from virtual agent.")

    def test_reply_passes_governance_context(self):
        agent, mock_v, _ = _build_agent()
        agent.reply("Hello", governance_context="Be gentle.")
        call_kwargs = mock_v.reply.call_args
        self.assertEqual(call_kwargs.kwargs.get("governance_context"), "Be gentle.")

    def test_reply_passes_chain_id(self):
        agent, mock_v, _ = _build_agent()
        agent.reply("Hello", chain_id="chain-123")
        self.assertEqual(mock_v.reply.call_args.kwargs["chain_id"], "chain-123")

    def test_reply_passes_history(self):
        agent, mock_v, _ = _build_agent()
        history = [{"role": "user", "content": "Hi"}]
        agent.reply("Hello", history=history)
        self.assertEqual(mock_v.reply.call_args.kwargs["history"], history)

    def test_reply_passes_use_tools_false(self):
        agent, mock_v, _ = _build_agent()
        agent.reply("Hello", use_tools=False)
        self.assertEqual(mock_v.reply.call_args.kwargs["use_tools"], False)

    def test_quick_query_delegates(self):
        agent, mock_v, _ = _build_agent()
        result = agent.quick_query("Sum 2+2")
        mock_v.quick_query.assert_called_once_with("Sum 2+2", max_tokens=2000)
        self.assertEqual(result, "Quick answer.")

    def test_cancel_delegates(self):
        agent, mock_v, _ = _build_agent()
        agent.cancel()
        mock_v.cancel.assert_called_once()


# ═══════════════════════════════════════════════════════════════════════
#  STATE & MODEL ACCESSORS
# ═══════════════════════════════════════════════════════════════════════

class TestCharacterAgentStateModel(unittest.TestCase):
    def test_get_state_delegates(self):
        agent, mock_v, _ = _build_agent()
        mock_v.get_state.return_value = {"mood": "happy"}
        state = agent.get_state()
        mock_v.get_state.assert_called_once()
        self.assertEqual(state["mood"], "happy")

    def test_update_state_delegates(self):
        agent, mock_v, _ = _build_agent()
        agent.update_state(mood="sad")
        mock_v.update_state.assert_called_once_with(mood="sad")

    def test_set_model_updates_both(self):
        agent, mock_v, _ = _build_agent()
        agent.set_model("new-model")
        self.assertEqual(agent.model, "new-model")
        mock_v.set_model.assert_called_once_with("new-model")

    def test_virtual_property(self):
        agent, mock_v, _ = _build_agent()
        self.assertIs(agent.virtual, mock_v)

    def test_repr(self):
        agent, _, _ = _build_agent()
        r = repr(agent)
        self.assertIn("CharacterAgent", r)


# ═══════════════════════════════════════════════════════════════════════
#  EDGE CASES
# ═══════════════════════════════════════════════════════════════════════

class TestCharacterAgentEdgeCases(unittest.TestCase):
    def test_character_without_personality(self):
        char = types.SimpleNamespace(id="x", name="X")
        agent, _, _ = _build_agent(character=char)
        self.assertEqual(agent.character.name, "X")

    def test_none_db_accepted(self):
        agent, _, _ = _build_agent(db=None)
        self.assertIsNone(agent.db)

    def test_empty_mcp_servers(self):
        agent, _, _ = _build_agent(mcp_servers=None)
        self.assertEqual(agent.mcp_servers, [])

    def test_use_virtual_param_ignored(self):
        agent, _, _ = _build_agent(use_virtual=False)
        # use_virtual is kept for compat but always True internally
        self.assertIsNotNone(agent.virtual)

    def test_config_auto_loaded_when_none(self):
        """When config=None, CharacterAgent imports and uses get_config()."""
        char = _make_character()
        mock_virtual = MagicMock()
        mock_virtual.reply.return_value = "ok"
        mock_mgr = MagicMock()
        mock_mgr.create_agent.return_value = mock_virtual
        mock_cfg = _mock_config()

        with patch("engine.agents.virtual_agent_manager.get_virtual_agent_manager",
                    return_value=mock_mgr), \
             patch("engine.config.get_config", return_value=mock_cfg):
            from engine.agents.character_agent import CharacterAgent
            agent = CharacterAgent(char, config=None)
        self.assertIsNotNone(agent.config)

    def test_reply_with_extra_kwargs(self):
        """Extra kwargs should be forwarded to the virtual agent."""
        agent, mock_v, _ = _build_agent()
        agent.reply("Hello", custom_param="value")
        self.assertIn("custom_param", mock_v.reply.call_args.kwargs)


if __name__ == "__main__":
    unittest.main()
