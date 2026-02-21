"""
tests/test_governance.py
========================

Comprehensive unit tests for the CosySim governance / MCP layer:

  * IAgent protocol (protocols.py)
  * InterceptorPipeline (comms_framework)
  * Individual interceptors (interceptors.py)
  * GameState — CRUD + observers
  * AgentRouter — inbox messaging
  * SkillManifest — defaults + YAML loading
  * AgentGovernor — dry-run context_dump, quick_query delegation

All tests are offline — no LLM, no DB, no network required.
"""
from __future__ import annotations

import threading
import types
import unittest
from typing import Any, Dict, List, Optional
from unittest.mock import MagicMock, patch


# ── Helpers ──────────────────────────────────────────────────────────────────

def _make_character(name: str = "Test", cid: str = "char-001") -> object:
    """Return a minimal character-data-like object."""
    obj = types.SimpleNamespace()
    obj.id         = cid
    obj.name       = name
    obj.mood       = "neutral"
    obj.arousal    = 0.0
    obj.energy     = 1.0
    obj.warmth     = 0.5
    obj.formality  = 0.5
    obj.humor      = 0.5
    obj.flirtiness = 0.5
    obj.intelligence = 0.5
    obj.creativity = 0.5
    obj.description = "A test character."
    obj.backstory   = ""
    obj.appearance  = ""
    return obj


class _DummyAgent:
    """Minimal IAgent-compatible object for testing governors without a real LLM."""

    def __init__(self, character=None, reply_text: str = "test reply") -> None:
        self.character    = character or _make_character()
        self._reply_text  = reply_text
        self._cancel_called = False
        self.capabilities = set()

    def reply(self, user_message: str, *, chain_id=None, history=None, **kwargs) -> str:
        return self._reply_text

    def quick_query(self, prompt: str, *, max_tokens: int = 200) -> str:
        return f"decision: {prompt[:20]}"

    def cancel(self) -> None:
        self._cancel_called = True


# ══════════════════════════════════════════════════════════════════════════════
#  1. IAgent Protocol Tests
# ══════════════════════════════════════════════════════════════════════════════

class TestIAgentProtocol(unittest.TestCase):
    """Verify structural protocol satisfaction."""

    def test_dummy_agent_satisfies_iagent(self):
        from engine.agents.protocols import IAgent
        agent = _DummyAgent()
        self.assertIsInstance(agent, IAgent)

    def test_missing_reply_not_iagent(self):
        from engine.agents.protocols import IAgent

        class Incomplete:
            character = None
            def quick_query(self, p): ...
            def cancel(self): ...

        self.assertNotIsInstance(Incomplete(), IAgent)

    def test_agent_capability_enum(self):
        from engine.agents.protocols import AgentCapability
        self.assertEqual(AgentCapability.TEXT, "text")
        self.assertEqual(AgentCapability.GOVERNED, "governed")
        self.assertIn(AgentCapability.MEMORY, AgentCapability)

    def test_iinterceptor_protocol(self):
        from engine.agents.protocols import IInterceptor

        class MyHook:
            name     = "test_hook"
            priority = 50
            def pre_call(self, ctx): ...
            def post_call(self, ctx): ...

        self.assertIsInstance(MyHook(), IInterceptor)


# ══════════════════════════════════════════════════════════════════════════════
#  2. InterceptorPipeline Tests
# ══════════════════════════════════════════════════════════════════════════════

class TestInterceptorPipeline(unittest.TestCase):

    def _make_pipeline(self):
        from engine.mcp.comms_framework import InterceptorPipeline
        return InterceptorPipeline()

    def _make_interceptor(self, name: str, priority: int, pre_fn=None, post_fn=None):
        from engine.mcp.comms_framework import InterceptorBase

        class _I(InterceptorBase):
            pass
        _I.name     = name
        _I.priority = priority
        if pre_fn:
            _I.pre_call = lambda self, ctx: pre_fn(ctx)
        if post_fn:
            _I.post_call = lambda self, ctx: post_fn(ctx)
        return _I()

    def test_add_sorts_by_priority(self):
        pl = self._make_pipeline()
        pl.add(self._make_interceptor("b", 50))
        pl.add(self._make_interceptor("a", 10))
        pl.add(self._make_interceptor("c", 90))
        self.assertEqual(pl.names, ["a", "b", "c"])

    def test_run_pre_order(self):
        pl = self._make_pipeline()
        order = []
        pl.add(self._make_interceptor("b", 50, pre_fn=lambda ctx: order.append("b")))
        pl.add(self._make_interceptor("a", 10, pre_fn=lambda ctx: order.append("a")))
        from engine.mcp.comms_framework import ResponseContext
        ctx = ResponseContext(system_prompt="", reply="", user_message="hi")
        pl.run_pre(ctx)
        self.assertEqual(order, ["a", "b"])

    def test_abort_stops_pipeline(self):
        pl = self._make_pipeline()
        calls = []

        def aborter(ctx):
            calls.append("aborter")
            ctx["abort"] = True

        pl.add(self._make_interceptor("first",  10, pre_fn=aborter))
        pl.add(self._make_interceptor("second", 20, pre_fn=lambda ctx: calls.append("second")))
        from engine.mcp.comms_framework import ResponseContext
        ctx = ResponseContext(system_prompt="", reply="", user_message="hi")
        pl.run_pre(ctx)
        self.assertNotIn("second", calls)

    def test_remove_by_name(self):
        pl = self._make_pipeline()
        pl.add(self._make_interceptor("x", 10))
        pl.add(self._make_interceptor("y", 20))
        pl.remove("x")
        self.assertEqual(pl.names, ["y"])

    def test_interceptor_exception_does_not_break_pipeline(self):
        """A failing interceptor should be skipped, not crash the pipeline."""
        from engine.mcp.comms_framework import InterceptorBase, InterceptorPipeline, ResponseContext

        class BadInterceptor(InterceptorBase):
            name     = "bad"
            priority = 10
            def pre_call(self, ctx):
                raise RuntimeError("boom!")

        pl = InterceptorPipeline()
        pl.add(BadInterceptor())

        reached = []
        from engine.mcp.comms_framework import InterceptorBase as IB

        class GoodInterceptor(IB):
            name     = "good"
            priority = 20
            def pre_call(self, ctx):
                reached.append(True)

        pl.add(GoodInterceptor())
        ctx = ResponseContext(system_prompt="", reply="", user_message="hi")
        pl.run_pre(ctx)   # should not raise
        self.assertTrue(reached)


# ══════════════════════════════════════════════════════════════════════════════
#  3. GameState Tests
# ══════════════════════════════════════════════════════════════════════════════

class TestGameState(unittest.TestCase):

    def _fresh(self):
        from engine.mcp.comms_framework import GameState
        return GameState()

    def test_set_and_get(self):
        gs = self._fresh()
        gs.set("game1", "round", 3)
        self.assertEqual(gs.get("game1", "round"), 3)

    def test_get_default(self):
        gs = self._fresh()
        self.assertIsNone(gs.get("x", "missing"))
        self.assertEqual(gs.get("x", "missing", 42), 42)

    def test_increment(self):
        gs = self._fresh()
        gs.set("game1", "score", 0)
        result = gs.increment("game1", "score", 5)
        self.assertEqual(result, 5)
        self.assertEqual(gs.get("game1", "score"), 5)

    def test_get_all(self):
        gs = self._fresh()
        gs.set("g", "a", 1)
        gs.set("g", "b", 2)
        self.assertEqual(gs.get_all("g"), {"a": 1, "b": 2})

    def test_reset_clears_game(self):
        gs = self._fresh()
        gs.set("g", "x", 99)
        gs.reset("g")
        self.assertEqual(gs.get("g", "x"), None)
        self.assertNotIn("g", gs.all_games())

    def test_all_games(self):
        gs = self._fresh()
        gs.set("alpha", "k", 1)
        gs.set("beta",  "k", 2)
        self.assertIn("alpha", gs.all_games())
        self.assertIn("beta",  gs.all_games())

    def test_observer_fires_on_set(self):
        gs = self._fresh()
        events = []
        gs.subscribe("game1", lambda g, k, v: events.append((g, k, v)))
        gs.set("game1", "score", 10)
        self.assertEqual(events, [("game1", "score", 10)])

    def test_observer_fires_on_increment(self):
        gs = self._fresh()
        events = []
        gs.subscribe("game1", lambda g, k, v: events.append(v))
        gs.increment("game1", "score", 3)
        self.assertEqual(events, [3])

    def test_observer_fires_on_reset(self):
        gs = self._fresh()
        events = []
        gs.subscribe("game1", lambda g, k, v: events.append(k))
        gs.reset("game1")
        self.assertIn("__reset__", events)

    def test_subscribe_all_catches_all_games(self):
        gs = self._fresh()
        games_seen = set()
        gs.subscribe_all(lambda g, k, v: games_seen.add(g))
        gs.set("alpha", "x", 1)
        gs.set("beta",  "y", 2)
        self.assertIn("alpha", games_seen)
        self.assertIn("beta",  games_seen)

    def test_unsubscribe(self):
        gs = self._fresh()
        calls = []
        fn = lambda g, k, v: calls.append(v)
        gs.subscribe("g", fn)
        gs.unsubscribe("g", fn)
        gs.set("g", "k", 99)
        self.assertEqual(calls, [])

    def test_thread_safety(self):
        """Concurrent sets from many threads should not lose data."""
        gs = self._fresh()
        threads = []
        for i in range(50):
            t = threading.Thread(target=gs.increment, args=("game", "counter", 1))
            threads.append(t)
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        self.assertEqual(gs.get("game", "counter"), 50)


# ══════════════════════════════════════════════════════════════════════════════
#  4. AgentRouter Tests
# ══════════════════════════════════════════════════════════════════════════════

class TestAgentRouter(unittest.TestCase):

    def _fresh(self):
        from engine.mcp.comms_framework import AgentRouter
        return AgentRouter()

    def test_send_and_drain(self):
        r = self._fresh()
        r.send("agent-b", "hello", sender_id="agent-a")
        msgs = r.drain("agent-b")
        self.assertEqual(len(msgs), 1)
        self.assertEqual(msgs[0]["message"], "hello")
        self.assertEqual(msgs[0]["sender"],  "agent-a")

    def test_drain_empties_inbox(self):
        r = self._fresh()
        r.send("x", "msg1")
        r.drain("x")
        self.assertEqual(r.drain("x"), [])

    def test_peek_does_not_empty(self):
        r = self._fresh()
        r.send("x", "hi")
        r.peek("x")
        self.assertTrue(r.has_messages("x"))

    def test_has_messages(self):
        r = self._fresh()
        self.assertFalse(r.has_messages("unknown"))
        r.send("z", "test")
        self.assertTrue(r.has_messages("z"))

    def test_multiple_recipients(self):
        r = self._fresh()
        r.send("alice", "for alice")
        r.send("bob",   "for bob")
        a = r.drain("alice")
        b = r.drain("bob")
        self.assertEqual(a[0]["message"], "for alice")
        self.assertEqual(b[0]["message"], "for bob")

    def test_meta_attached(self):
        r = self._fresh()
        r.send("x", "msg", meta={"priority": "high"})
        msgs = r.drain("x")
        self.assertEqual(msgs[0]["meta"]["priority"], "high")


# ══════════════════════════════════════════════════════════════════════════════
#  5. SkillManifest Tests
# ══════════════════════════════════════════════════════════════════════════════

class TestSkillManifest(unittest.TestCase):

    def test_defaults_loaded(self):
        from engine.mcp.comms_framework import SkillManifest
        sm = SkillManifest()
        phone = sm.get("phone")
        self.assertEqual(phone.scene, "phone")
        self.assertTrue(len(phone.skills) > 0)

    def test_auto_skills(self):
        from engine.mcp.comms_framework import SkillManifest, TRIGGER_AUTO
        sm    = SkillManifest()
        phone = sm.get("phone")
        autos = phone.auto_skills()
        self.assertTrue(all(s.trigger == TRIGGER_AUTO for s in autos))

    def test_optional_skills(self):
        from engine.mcp.comms_framework import SkillManifest, TRIGGER_OPTIONAL
        sm       = SkillManifest()
        bedroom  = sm.get("bedroom")
        optional = bedroom.optional_skills()
        self.assertTrue(all(s.trigger == TRIGGER_OPTIONAL for s in optional))

    def test_unknown_scene_returns_empty_manifest(self):
        from engine.mcp.comms_framework import SkillManifest
        sm  = SkillManifest()
        uk  = sm.get("non_existent_scene_xyz")
        self.assertEqual(uk.scene, "non_existent_scene_xyz")
        self.assertEqual(uk.skills, [])

    def test_all_scenes_non_empty(self):
        from engine.mcp.comms_framework import SkillManifest
        sm = SkillManifest()
        scenes = sm.all_scenes()
        self.assertGreater(len(scenes), 0)


# ══════════════════════════════════════════════════════════════════════════════
#  6. AgentGovernor Unit Tests  (no real LLM — mocked agent)
# ══════════════════════════════════════════════════════════════════════════════

class TestAgentGovernor(unittest.TestCase):

    def _make_governor(self, reply_text: str = "governor reply", scene: str = "phone"):
        from engine.mcp.comms_framework import AgentGovernor, InterceptorPipeline
        agent = _DummyAgent(reply_text=reply_text)
        # Empty pipeline: no interceptors, so no external service calls
        gov = AgentGovernor(agent, scene=scene, pipeline=InterceptorPipeline())
        return gov, agent

    def test_reply_returns_agent_reply(self):
        gov, _ = self._make_governor("hello world")
        result = gov.reply("test message")
        self.assertEqual(result, "hello world")

    def test_skip_gov_bypasses_pipeline(self):
        """skip_gov=True should call agent.reply directly."""
        from engine.mcp.comms_framework import AgentGovernor, InterceptorPipeline
        agent = _DummyAgent(reply_text="direct")
        pipeline_called = []
        from engine.mcp.comms_framework import InterceptorBase

        class Spy(InterceptorBase):
            name     = "spy"
            priority = 10
            def pre_call(self, ctx):
                pipeline_called.append(True)

        pipeline = InterceptorPipeline()
        pipeline.add(Spy())
        gov = AgentGovernor(agent, scene="phone", pipeline=pipeline)
        result = gov.reply("hi", skip_gov=True)
        self.assertEqual(result, "direct")
        self.assertEqual(pipeline_called, [])

    def test_quick_query_delegates_to_agent(self):
        gov, _ = self._make_governor()
        result = gov.quick_query("what action?")
        self.assertIn("decision:", result)

    def test_cancel_delegates_to_agent(self):
        gov, agent = self._make_governor()
        gov.cancel()
        self.assertTrue(agent._cancel_called)

    def test_character_property(self):
        gov, agent = self._make_governor()
        self.assertIs(gov.character, agent.character)

    def test_capabilities_includes_governed(self):
        from engine.agents.protocols import AgentCapability
        gov, _ = self._make_governor()
        self.assertIn(AgentCapability.GOVERNED, gov.capabilities)

    def test_context_dump_does_not_call_agent(self):
        """context_dump is a dry run — agent.reply must NOT be called."""
        from engine.mcp.comms_framework import AgentGovernor, InterceptorPipeline
        agent = _DummyAgent(reply_text="<<SHOULD NOT BE RETURNED>>")
        called = []
        original_reply = agent.reply

        def spy_reply(*a, **kw):
            called.append(True)
            return original_reply(*a, **kw)

        agent.reply = spy_reply
        gov = AgentGovernor(agent, scene="phone", pipeline=InterceptorPipeline())
        dump = gov.context_dump("test message")
        self.assertFalse(called, "agent.reply should not be called during context_dump")
        self.assertIn("user_message", dump)

    def test_kwargs_absorbed(self):
        """reply() should accept arbitrary kwargs without raising."""
        gov, _ = self._make_governor()
        # Should NOT raise with extra kwargs
        result = gov.reply("hi", use_tools=False, skip_gov=False, unknown_kwarg=True)
        self.assertEqual(result, "governor reply")


# ══════════════════════════════════════════════════════════════════════════════
#  7. Specific Interceptor Unit Tests
# ══════════════════════════════════════════════════════════════════════════════

class TestResponseShaperInterceptor(unittest.TestCase):

    def _make_ctx(self, reply: str) -> dict:
        from engine.mcp.comms_framework import ResponseContext
        return ResponseContext(reply=reply, system_prompt="", user_message="")

    def test_strips_leaked_skills_section(self):
        from engine.agents.interceptors import ResponseShaperInterceptor
        interceptor = ResponseShaperInterceptor()
        ctx = self._make_ctx("Here's my reply.\n--- Skills & Tools ---\nREQUIRED: ...")
        interceptor.post_call(ctx)
        self.assertEqual(ctx["reply"], "Here's my reply.")

    def test_does_not_modify_clean_reply(self):
        from engine.agents.interceptors import ResponseShaperInterceptor
        interceptor = ResponseShaperInterceptor()
        ctx = self._make_ctx("A perfectly clean reply.")
        interceptor.post_call(ctx)
        self.assertEqual(ctx["reply"], "A perfectly clean reply.")

    def test_strips_whitespace(self):
        from engine.agents.interceptors import ResponseShaperInterceptor
        interceptor = ResponseShaperInterceptor()
        ctx = self._make_ctx("  good reply   ")
        interceptor.post_call(ctx)
        self.assertEqual(ctx["reply"], "good reply")


class TestMoodSyncInterceptor(unittest.TestCase):

    def _make_ctx(self, reply: str, agent_id: str = "char-001") -> dict:
        from engine.mcp.comms_framework import ResponseContext
        return ResponseContext(reply=reply, agent_id=agent_id, system_prompt="", user_message="")

    def test_strip_mood_tag_from_reply(self):
        from engine.agents.interceptors import MoodSyncInterceptor
        interceptor = MoodSyncInterceptor()
        ctx = self._make_ctx("I feel alive tonight.[MOOD:happy]")
        with patch("engine.mcp.character_registry.get_character_registry") as mock_reg:
            mock_reg.return_value = MagicMock()
            interceptor.post_call(ctx)
        self.assertNotIn("[MOOD:", ctx["reply"])
        self.assertIn("I feel alive tonight.", ctx["reply"])

    def test_no_mood_tag_leaves_reply_intact(self):
        from engine.agents.interceptors import MoodSyncInterceptor
        interceptor = MoodSyncInterceptor()
        ctx = self._make_ctx("Just a normal reply.")
        interceptor.post_call(ctx)
        self.assertEqual(ctx["reply"], "Just a normal reply.")

    def test_mood_tag_with_intensity(self):
        from engine.agents.interceptors import MoodSyncInterceptor
        interceptor = MoodSyncInterceptor()
        ctx = self._make_ctx("So excited![MOOD:excited intensity=0.9]")
        registry_state = {}

        def mock_set_state(agent_id, **kwargs):
            registry_state.update(kwargs)

        with patch("engine.mcp.character_registry.get_character_registry") as mock_reg:
            mr = MagicMock()
            mr.set_state.side_effect = mock_set_state
            mock_reg.return_value = mr
            interceptor.post_call(ctx)

        self.assertEqual(registry_state.get("mood"), "excited")
        self.assertAlmostEqual(registry_state.get("mood_intensity", 0), 0.9, places=1)


class TestTTSStyleInterceptor(unittest.TestCase):

    def _make_ctx(self, reply: str = "Hello there.", agent_id: str = "char-001",
                  scene: str = "phone") -> dict:
        from engine.mcp.comms_framework import ResponseContext
        return ResponseContext(reply=reply, agent_id=agent_id, scene=scene,
                               system_prompt="", user_message="")

    def test_tts_meta_created(self):
        from engine.agents.interceptors import TTSStyleInterceptor
        interceptor = TTSStyleInterceptor()
        ctx = self._make_ctx()
        with patch("engine.mcp.character_registry.get_character_registry") as mock_reg:
            mock_reg.return_value.get_character_summary.return_value = {
                "mood": "happy", "mood_intensity": 0.7, "voice_id": "lola"
            }
            interceptor.post_call(ctx)
        meta = ctx.get("tts_meta", {})
        self.assertEqual(meta.get("emotion"), "happy")
        self.assertEqual(meta.get("voice_id"), "lola")
        self.assertIn("speed", meta)

    def test_tts_meta_fallback_on_registry_error(self):
        from engine.agents.interceptors import TTSStyleInterceptor
        interceptor = TTSStyleInterceptor()
        ctx = self._make_ctx()
        with patch("engine.mcp.character_registry.get_character_registry",
                   side_effect=Exception("db down")):
            interceptor.post_call(ctx)
        # Should still produce tts_meta with fallback values
        meta = ctx.get("tts_meta", {})
        self.assertIn("emotion", meta)
        self.assertEqual(meta.get("scene"), "phone")

    def test_empty_reply_skipped(self):
        from engine.agents.interceptors import TTSStyleInterceptor
        interceptor = TTSStyleInterceptor()
        ctx = self._make_ctx(reply="")
        interceptor.post_call(ctx)
        self.assertNotIn("tts_meta", ctx)


class TestPersonalityGuardInterceptor(unittest.TestCase):

    def test_forbidden_topics_injected(self):
        from engine.agents.interceptors import PersonalityGuardInterceptor
        from engine.mcp.comms_framework import InteractionPolicy, ResponseContext
        interceptor = PersonalityGuardInterceptor()
        policy = InteractionPolicy(forbidden_topics=["violence", "politics"])
        ctx = ResponseContext(system_prompt="", policy=policy, user_message="hi", reply="")
        interceptor.pre_call(ctx)
        self.assertIn("violence", ctx["system_prompt"])
        self.assertIn("politics", ctx["system_prompt"])

    def test_required_tone_injected(self):
        from engine.agents.interceptors import PersonalityGuardInterceptor
        from engine.mcp.comms_framework import InteractionPolicy, ResponseContext
        interceptor = PersonalityGuardInterceptor()
        policy = InteractionPolicy(required_tone="mysterious")
        ctx = ResponseContext(system_prompt="", policy=policy, user_message="hi", reply="")
        interceptor.pre_call(ctx)
        self.assertIn("mysterious", ctx["system_prompt"])


class TestSkillAwarenessInterceptor(unittest.TestCase):

    def test_required_skills_injected_as_mandatory(self):
        from engine.agents.interceptors import SkillAwarenessInterceptor
        from engine.mcp.comms_framework import (
            ResponseContext, SceneManifest, SkillEntry, TRIGGER_REQUIRED
        )
        interceptor = SkillAwarenessInterceptor()
        manifest = SceneManifest(
            scene="test",
            skills=[SkillEntry(name="roll_dice", trigger=TRIGGER_REQUIRED,
                               description="Roll the dice")]
        )
        ctx = ResponseContext(
            system_prompt="",
            skill_manifest=manifest,
            user_message="hi",
            reply="",
        )
        interceptor.pre_call(ctx)
        self.assertIn("REQUIRED", ctx["system_prompt"])
        self.assertIn("roll_dice", ctx["system_prompt"])

    def test_optional_skills_injected_as_available(self):
        from engine.agents.interceptors import SkillAwarenessInterceptor
        from engine.mcp.comms_framework import (
            ResponseContext, SceneManifest, SkillEntry, TRIGGER_OPTIONAL
        )
        interceptor = SkillAwarenessInterceptor()
        manifest = SceneManifest(
            scene="test",
            skills=[SkillEntry(name="search_memory", trigger=TRIGGER_OPTIONAL,
                               description="Search memories")]
        )
        ctx = ResponseContext(
            system_prompt="",
            skill_manifest=manifest,
            user_message="hi",
            reply="",
        )
        interceptor.pre_call(ctx)
        self.assertIn("AVAILABLE TOOLS", ctx["system_prompt"])
        self.assertIn("search_memory",   ctx["system_prompt"])


# ══════════════════════════════════════════════════════════════════════════════
#  8. AgentCapability / IAgent integration with CharacterAgent
# ══════════════════════════════════════════════════════════════════════════════

class TestCharacterAgentProtocolCompliance(unittest.TestCase):

    def _make_agent(self, skill_packs=None):
        from engine.agents.character_agent import CharacterAgent
        char = _make_character()
        return CharacterAgent(char, skill_packs=skill_packs)

    def test_satisfies_iagent(self):
        from engine.agents.protocols import IAgent
        agent = self._make_agent()
        self.assertIsInstance(agent, IAgent)

    def test_text_capability_always_present(self):
        from engine.agents.protocols import AgentCapability
        agent = self._make_agent()
        self.assertIn(AgentCapability.TEXT,   agent.capabilities)
        self.assertIn(AgentCapability.MEMORY, agent.capabilities)

    def test_tools_capability_with_skill_packs(self):
        from engine.agents.protocols import AgentCapability
        agent = self._make_agent(skill_packs=["memory"])
        self.assertIn(AgentCapability.TOOLS, agent.capabilities)

    def test_no_tools_capability_without_skill_packs(self):
        from engine.agents.protocols import AgentCapability
        agent = self._make_agent(skill_packs=[])
        self.assertNotIn(AgentCapability.TOOLS, agent.capabilities)

    def test_cancel_sets_cancel_event(self):
        agent = self._make_agent()
        self.assertFalse(agent._cancel_event.is_set())
        agent.cancel()
        self.assertTrue(agent._cancel_event.is_set())

    def test_quick_query_returns_string(self):
        """quick_query should return a string even if LLM is unavailable."""
        from engine.agents.character_agent import CharacterAgent
        char = _make_character()
        agent = CharacterAgent(char)
        # With no LMStudio running, it should return "" not raise
        result = agent.quick_query("what should I do?")
        self.assertIsInstance(result, str)

    def test_reply_accepts_extra_kwargs(self):
        """reply() must absorb use_tools=False and any unexpected kwargs."""
        import sys
        import types
        from engine.agents.character_agent import CharacterAgent

        char  = _make_character()
        agent = CharacterAgent(char)

        # Stub out the `lmstudio` package so the import inside reply() succeeds
        fake_lms = types.ModuleType("lmstudio")
        fake_chat_instance = MagicMock()
        fake_lms.Chat = MagicMock(return_value=fake_chat_instance)

        with patch.dict(sys.modules, {"lmstudio": fake_lms}):
            with patch.object(agent, "_reply_via_rest", return_value="patched reply"):
                result = agent.reply("hi", use_tools=False, unknown_kwarg="ignored")

        self.assertEqual(result, "patched reply")


# ══════════════════════════════════════════════════════════════════════════════
#  9. Module Exports Tests
# ══════════════════════════════════════════════════════════════════════════════

class TestModuleExports(unittest.TestCase):

    def test_engine_mcp_exports_get_governor(self):
        from engine.mcp import get_governor
        self.assertTrue(callable(get_governor))

    def test_engine_mcp_exports_game_state(self):
        from engine.mcp import get_game_state, GameState
        gs = get_game_state()
        self.assertIsInstance(gs, GameState)

    def test_engine_mcp_exports_agent_router(self):
        from engine.mcp import get_router, AgentRouter
        r = get_router()
        self.assertIsInstance(r, AgentRouter)

    def test_engine_mcp_exports_interaction_policy(self):
        from engine.mcp import InteractionPolicy
        p = InteractionPolicy(max_reply_tokens=300)
        self.assertEqual(p.max_reply_tokens, 300)

    def test_engine_mcp_exports_interceptor_base(self):
        from engine.mcp import InterceptorBase, InterceptorPipeline
        self.assertTrue(hasattr(InterceptorBase, "pre_call"))
        self.assertTrue(hasattr(InterceptorPipeline, "add"))

    def test_engine_agents_exports(self):
        from engine.agents import (
            CharacterAgent, AgentLoop, SceneAgent, get_scene_agent,
            AgentGovernor, get_governor, IAgent, AgentCapability,
        )
        self.assertTrue(callable(get_governor))
        self.assertTrue(callable(get_scene_agent))

    def test_skill_manifest_trigger_constants_exported(self):
        from engine.mcp import TRIGGER_AUTO, TRIGGER_OPTIONAL, TRIGGER_REQUIRED
        self.assertEqual(TRIGGER_AUTO,     "auto")
        self.assertEqual(TRIGGER_OPTIONAL, "optional")
        self.assertEqual(TRIGGER_REQUIRED, "required")


# ══════════════════════════════════════════════════════════════════════════════
#  10. InteractionPolicy Tests
# ══════════════════════════════════════════════════════════════════════════════

class TestInteractionPolicy(unittest.TestCase):

    def test_defaults(self):
        from engine.mcp.comms_framework import InteractionPolicy
        p = InteractionPolicy()
        self.assertEqual(p.max_reply_tokens, 500)
        self.assertEqual(p.min_reply_tokens, 10)
        self.assertTrue(p.enforce_in_character)
        self.assertFalse(p.allow_explicit)
        self.assertEqual(p.tool_call_limit, 6)

    def test_custom_values(self):
        from engine.mcp.comms_framework import InteractionPolicy
        p = InteractionPolicy(
            max_reply_tokens=200,
            required_tone="flirty",
            forbidden_topics=["work", "money"],
            allow_explicit=True,
        )
        self.assertEqual(p.max_reply_tokens, 200)
        self.assertEqual(p.required_tone, "flirty")
        self.assertEqual(p.forbidden_topics, ["work", "money"])
        self.assertTrue(p.allow_explicit)


# ══════════════════════════════════════════════════════════════════════════════
#  Entry point
# ══════════════════════════════════════════════════════════════════════════════

if __name__ == "__main__":
    unittest.main(verbosity=2)
