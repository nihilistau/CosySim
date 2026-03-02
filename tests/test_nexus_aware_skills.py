"""Tests for NexusAwareSkillMixin, @nexus_aware decorator, and NexusContextInjector."""
from __future__ import annotations

from unittest.mock import MagicMock, patch, call
import pytest


# ── helpers ──────────────────────────────────────────────────────────────────

def _make_client(answer: str | None = None, confidence: float = 0.8) -> MagicMock:
    """Return a mock NexusClient."""
    client = MagicMock()
    if answer is not None:
        client.ask.return_value = {"answer": answer, "confidence": confidence}
    else:
        client.ask.return_value = {}
    client.add_qa.return_value = "qa-id-1"
    client.search.return_value = []
    return client


# ══════════════════════════════════════════════════════════════════════════════
#  NexusAwareSkillMixin
# ══════════════════════════════════════════════════════════════════════════════

class TestNexusAwareSkillMixinLookup:
    """nexus_lookup() behaviour."""

    def _subject(self):
        from engine.skills.nexus_aware import NexusAwareSkillMixin
        return NexusAwareSkillMixin()

    def test_returns_none_on_empty_response(self):
        mixin = self._subject()
        with patch("engine.skills.nexus_aware.get_nexus_client") as mock_gc:
            mock_gc.return_value = _make_client(answer=None)
            assert mixin.nexus_lookup("what is gravity?") is None

    def test_returns_answer_on_cache_hit(self):
        mixin = self._subject()
        with patch("engine.skills.nexus_aware.get_nexus_client") as mock_gc:
            mock_gc.return_value = _make_client(answer="It is 9.8 m/s²", confidence=0.9)
            result = mixin.nexus_lookup("what is gravity?")
        assert result == "It is 9.8 m/s²"

    def test_returns_none_when_confidence_below_threshold(self):
        mixin = self._subject()
        with patch("engine.skills.nexus_aware.get_nexus_client") as mock_gc:
            mock_gc.return_value = _make_client(answer="Maybe...", confidence=0.3)
            result = mixin.nexus_lookup("what is gravity?", min_confidence=0.6)
        assert result is None

    def test_respects_custom_min_confidence(self):
        mixin = self._subject()
        with patch("engine.skills.nexus_aware.get_nexus_client") as mock_gc:
            mock_gc.return_value = _make_client(answer="Low conf answer", confidence=0.5)
            result = mixin.nexus_lookup("question", min_confidence=0.4)
        assert result == "Low conf answer"

    def test_returns_none_when_nexus_raises(self):
        mixin = self._subject()
        with patch("engine.skills.nexus_aware.get_nexus_client") as mock_gc:
            mock_gc.side_effect = ConnectionRefusedError("offline")
            result = mixin.nexus_lookup("any question")
        assert result is None

    def test_returns_none_when_ask_raises(self):
        mixin = self._subject()
        with patch("engine.skills.nexus_aware.get_nexus_client") as mock_gc:
            client = MagicMock()
            client.ask.side_effect = TimeoutError("timed out")
            mock_gc.return_value = client
            result = mixin.nexus_lookup("any question")
        assert result is None

    def test_calls_client_ask_with_query(self):
        mixin = self._subject()
        with patch("engine.skills.nexus_aware.get_nexus_client") as mock_gc:
            client = _make_client(answer="ans", confidence=0.9)
            mock_gc.return_value = client
            mixin.nexus_lookup("test query")
        client.ask.assert_called_once_with("test query")

    def test_returns_none_when_ask_returns_none(self):
        mixin = self._subject()
        with patch("engine.skills.nexus_aware.get_nexus_client") as mock_gc:
            client = MagicMock()
            client.ask.return_value = None
            mock_gc.return_value = client
            result = mixin.nexus_lookup("q")
        assert result is None


class TestNexusAwareSkillMixinStore:
    """nexus_store() behaviour."""

    def _subject(self):
        from engine.skills.nexus_aware import NexusAwareSkillMixin
        return NexusAwareSkillMixin()

    def test_calls_add_qa(self):
        mixin = self._subject()
        with patch("engine.skills.nexus_aware.get_nexus_client") as mock_gc:
            client = _make_client()
            mock_gc.return_value = client
            mixin.nexus_store("Q?", "A!", category="test")
        client.add_qa.assert_called_once_with("Q?", "A!", category="test")

    def test_default_category_is_skills(self):
        mixin = self._subject()
        with patch("engine.skills.nexus_aware.get_nexus_client") as mock_gc:
            client = _make_client()
            mock_gc.return_value = client
            mixin.nexus_store("Q?", "A!")
        client.add_qa.assert_called_once_with("Q?", "A!", category="skills")

    def test_store_does_not_raise_when_nexus_offline(self):
        mixin = self._subject()
        with patch("engine.skills.nexus_aware.get_nexus_client") as mock_gc:
            mock_gc.side_effect = ConnectionRefusedError("offline")
            # Should not raise
            mixin.nexus_store("Q?", "A!")

    def test_store_does_not_raise_when_add_qa_fails(self):
        mixin = self._subject()
        with patch("engine.skills.nexus_aware.get_nexus_client") as mock_gc:
            client = MagicMock()
            client.add_qa.side_effect = RuntimeError("db error")
            mock_gc.return_value = client
            mixin.nexus_store("Q?", "A!")  # must not raise


# ══════════════════════════════════════════════════════════════════════════════
#  @nexus_aware decorator
# ══════════════════════════════════════════════════════════════════════════════

class TestNexusAwareDecorator:
    """@nexus_aware behaviour."""

    def test_cache_hit_returns_cached_answer_without_calling_inner(self):
        from engine.skills.nexus_aware import nexus_aware

        called = []

        def inner(x: str) -> str:
            called.append(x)
            return "fresh"

        wrapped = nexus_aware(inner)

        with patch("engine.skills.nexus_aware.get_nexus_client") as mock_gc:
            mock_gc.return_value = _make_client(answer="cached", confidence=0.9)
            result = wrapped("arg1")

        assert result == "cached"
        assert called == []

    def test_cache_miss_calls_inner_function(self):
        from engine.skills.nexus_aware import nexus_aware

        called = []

        def inner(x: str) -> str:
            called.append(x)
            return "computed"

        wrapped = nexus_aware(inner)

        with patch("engine.skills.nexus_aware.get_nexus_client") as mock_gc:
            mock_gc.return_value = _make_client(answer=None)
            result = wrapped("arg1")

        assert result == "computed"
        assert called == ["arg1"]

    def test_cache_miss_stores_result_to_nexus(self):
        from engine.skills.nexus_aware import nexus_aware

        def inner(x: str) -> str:
            return "result_to_store"

        wrapped = nexus_aware(inner)

        client = _make_client(answer=None)
        with patch("engine.skills.nexus_aware.get_nexus_client") as mock_gc:
            mock_gc.return_value = client
            wrapped("x")

        client.add_qa.assert_called_once()
        stored_answer = client.add_qa.call_args[0][1]
        assert stored_answer == "result_to_store"

    def test_preserves_function_name_and_docstring(self):
        from engine.skills.nexus_aware import nexus_aware

        def my_special_skill(x: str) -> str:
            """My docstring."""
            return x

        wrapped = nexus_aware(my_special_skill)
        assert wrapped.__name__ == "my_special_skill"
        assert wrapped.__doc__ == "My docstring."

    def test_key_includes_function_name_and_args(self):
        from engine.skills.nexus_aware import nexus_aware

        def my_fn(a: str, b: str) -> str:
            return "r"

        wrapped = nexus_aware(my_fn)

        client = _make_client(answer=None)
        with patch("engine.skills.nexus_aware.get_nexus_client") as mock_gc:
            mock_gc.return_value = client
            wrapped("alpha", "beta")

        asked_key = client.ask.call_args[0][0]
        assert "alpha" in asked_key
        assert "beta" in asked_key

    def test_does_not_raise_when_nexus_offline_on_hit(self):
        from engine.skills.nexus_aware import nexus_aware

        def inner(q: str) -> str:
            return "fallback"

        wrapped = nexus_aware(inner)

        with patch("engine.skills.nexus_aware.get_nexus_client") as mock_gc:
            mock_gc.side_effect = ConnectionRefusedError("offline")
            result = wrapped("q")

        assert result == "fallback"

    def test_does_not_raise_when_nexus_offline_on_store(self):
        from engine.skills.nexus_aware import nexus_aware

        def inner(q: str) -> str:
            return "value"

        call_count = 0

        def get_client_side_effect():
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                # First call (lookup) — miss
                c = _make_client(answer=None)
                return c
            # Second call (store) — offline
            raise ConnectionRefusedError("offline")

        with patch("engine.skills.nexus_aware.get_nexus_client", side_effect=get_client_side_effect):
            result = nexus_aware(inner)("q")  # must not raise

        assert result == "value"

    def test_low_confidence_treated_as_cache_miss(self):
        from engine.skills.nexus_aware import nexus_aware

        called = []

        def inner(q: str) -> str:
            called.append(q)
            return "fresh_result"

        wrapped = nexus_aware(inner)

        with patch("engine.skills.nexus_aware.get_nexus_client") as mock_gc:
            mock_gc.return_value = _make_client(answer="stale", confidence=0.2)
            result = wrapped("q")

        assert result == "fresh_result"
        assert called == ["q"]


# ══════════════════════════════════════════════════════════════════════════════
#  NexusContextInjector
# ══════════════════════════════════════════════════════════════════════════════

class TestNexusContextInjectorPreCall:
    """pre_call() behaviour."""

    def _subject(self, max_results: int = 3, min_score: float = 0.5):
        from engine.agents.nexus_context_injector import NexusContextInjector
        return NexusContextInjector(max_results=max_results, min_score=min_score)

    def _request(self, user_msg: str = "Tell me about faction lore") -> dict:
        return {
            "messages": [
                {"role": "system", "content": "You are a helpful assistant."},
                {"role": "user", "content": user_msg},
            ]
        }

    def test_injects_nexus_knowledge_section(self):
        inj = self._subject()
        client = _make_client()
        client.search.return_value = [
            {"title": "Faction lore", "content": "The Syndicate rules the underworld."}
        ]

        with patch("engine.agents.nexus_context_injector.get_nexus_client", return_value=client):
            result = inj.pre_call(self._request(), {})

        sys_content = result["messages"][0]["content"]
        assert "[NEXUS KNOWLEDGE]" in sys_content
        assert "Syndicate" in sys_content

    def test_handles_empty_messages_gracefully(self):
        inj = self._subject()
        request = {"messages": []}
        result = inj.pre_call(request, {})
        assert result == {"messages": []}

    def test_handles_no_messages_key(self):
        inj = self._subject()
        request: dict = {}
        result = inj.pre_call(request, {})
        assert result == {}

    def test_handles_nexus_offline_gracefully(self):
        inj = self._subject()
        with patch(
            "engine.agents.nexus_context_injector.get_nexus_client",
            side_effect=ConnectionRefusedError("offline"),
        ):
            result = inj.pre_call(self._request(), {})
        # Original request returned unchanged, no raise
        assert result["messages"][0]["role"] == "system"

    def test_does_not_inject_when_no_search_results(self):
        inj = self._subject()
        client = _make_client()
        client.search.return_value = []

        with patch("engine.agents.nexus_context_injector.get_nexus_client", return_value=client):
            result = inj.pre_call(self._request(), {})

        sys_content = result["messages"][0]["content"]
        assert "[NEXUS KNOWLEDGE]" not in sys_content

    def test_skips_short_user_message(self):
        inj = self._subject()
        client = _make_client()
        client.search.return_value = [{"title": "T", "content": "C"}]

        req = {
            "messages": [
                {"role": "system", "content": "sys"},
                {"role": "user", "content": "Hi"},  # < 10 chars
            ]
        }
        with patch("engine.agents.nexus_context_injector.get_nexus_client", return_value=client):
            result = inj.pre_call(req, {})

        assert "[NEXUS KNOWLEDGE]" not in result["messages"][0]["content"]

    def test_respects_max_results_limit(self):
        inj = self._subject(max_results=2)
        client = _make_client()
        client.search.return_value = [
            {"title": f"Entry {i}", "content": f"Content {i}"} for i in range(5)
        ]

        with patch("engine.agents.nexus_context_injector.get_nexus_client", return_value=client):
            result = inj.pre_call(self._request(), {})

        sys_content = result["messages"][0]["content"]
        # max 2 entries injected
        assert sys_content.count("[Entry") <= 2

    def test_uses_last_user_message_as_query(self):
        inj = self._subject()
        client = _make_client()
        client.search.return_value = []

        req = {
            "messages": [
                {"role": "system", "content": "sys"},
                {"role": "user", "content": "First message here"},
                {"role": "assistant", "content": "Got it"},
                {"role": "user", "content": "Second user message"},
            ]
        }
        with patch("engine.agents.nexus_context_injector.get_nexus_client", return_value=client):
            inj.pre_call(req, {})

        query_used = client.search.call_args[0][0]
        assert "Second user message" in query_used

    def test_does_not_modify_request_when_no_system_message(self):
        inj = self._subject()
        client = _make_client()
        client.search.return_value = [{"title": "T", "content": "C"}]

        req = {"messages": [{"role": "user", "content": "Long enough message here"}]}
        with patch("engine.agents.nexus_context_injector.get_nexus_client", return_value=client):
            result = inj.pre_call(req, {})

        # No system message to inject into — request unchanged
        assert len(result["messages"]) == 1

    def test_search_raises_returns_original_request(self):
        inj = self._subject()
        client = _make_client()
        client.search.side_effect = RuntimeError("db failure")

        with patch("engine.agents.nexus_context_injector.get_nexus_client", return_value=client):
            result = inj.pre_call(self._request(), {})

        assert "[NEXUS KNOWLEDGE]" not in result["messages"][0]["content"]


class TestNexusContextInjectorPostCall:
    """post_call() must pass response through unchanged."""

    def test_post_call_returns_response_unchanged(self):
        from engine.agents.nexus_context_injector import NexusContextInjector
        inj = NexusContextInjector()
        response = {"choices": [{"message": {"content": "hello"}}]}
        result = inj.post_call(response, {})
        assert result is response

    def test_post_call_with_empty_response(self):
        from engine.agents.nexus_context_injector import NexusContextInjector
        inj = NexusContextInjector()
        result = inj.post_call({}, {})
        assert result == {}


# ══════════════════════════════════════════════════════════════════════════════
#  @skill nexus_first=True integration
# ══════════════════════════════════════════════════════════════════════════════

class TestSkillNexusFirst:
    """Verify nexus_first=True in @skill wraps the registered function."""

    def test_nexus_first_true_wraps_function(self):
        from engine.skills.skill import skill, SkillCategory
        from engine.skills.registry import SKILL_REGISTRY

        @skill(
            pack="_test_nexus_first",
            description="test",
            nexus_first=True,
        )
        def _test_nf_skill(x: str) -> str:
            return f"fresh:{x}"

        # The original function is returned unchanged by @skill
        assert _test_nf_skill("hi") == "fresh:hi"

        # The registered meta.func should be the nexus_aware-wrapped version
        meta = SKILL_REGISTRY.get_skill("_test_nf_skill")
        assert meta is not None
        assert meta.func is not _test_nf_skill  # wrapped, not original

    def test_nexus_first_false_does_not_wrap(self):
        from engine.skills.skill import skill
        from engine.skills.registry import SKILL_REGISTRY

        @skill(pack="_test_no_wrap", description="test", nexus_first=False)
        def _test_no_wrap_skill(x: str) -> str:
            return f"direct:{x}"

        meta = SKILL_REGISTRY.get_skill("_test_no_wrap_skill")
        assert meta is not None
        assert meta.func is _test_no_wrap_skill  # not wrapped

    def test_nexus_first_skill_uses_cache_when_available(self):
        """Registered wrapped function returns cached answer on hit."""
        from engine.skills.skill import skill
        from engine.skills.registry import SKILL_REGISTRY

        called = []

        @skill(pack="_test_nf_cache", description="test", nexus_first=True)
        def _test_cache_skill(topic: str) -> str:
            called.append(topic)
            return f"computed:{topic}"

        meta = SKILL_REGISTRY.get_skill("_test_cache_skill")
        assert meta is not None

        with patch("engine.skills.nexus_aware.get_nexus_client") as mock_gc:
            mock_gc.return_value = _make_client(answer="cached_answer", confidence=0.95)
            result = meta.func("dragons")

        assert result == "cached_answer"
        assert called == []  # inner was not called
