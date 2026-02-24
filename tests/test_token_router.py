"""Tests for TokenAheadRouter — pre-warms MCP tools during generation."""

import time
import pytest

from engine.pipeline.token_router import TokenAheadRouter


# ── Helpers ─────────────────────────────────────────────────────────────

def make_executor(delay=0.01, result="ok"):
    """Create a mock tool executor."""
    def executor(tool_name, context):
        time.sleep(delay)
        return {"tool": tool_name, "result": result, **context}
    return executor


def make_failing_executor():
    """Executor that always raises."""
    def executor(tool_name, context):
        raise RuntimeError(f"Tool {tool_name} failed")
    return executor


# ── Tests ───────────────────────────────────────────────────────────────

class TestTokenAheadRouter:
    def test_on_intent_detected_known(self):
        router = TokenAheadRouter(tool_executor=make_executor())
        result = router.on_intent_detected("image_generation")
        assert result == "generate_image_request"

    def test_on_intent_detected_unknown(self):
        router = TokenAheadRouter(tool_executor=make_executor())
        result = router.on_intent_detected("unknown_intent")
        assert result is None

    def test_no_executor_returns_none(self):
        router = TokenAheadRouter(tool_executor=None)
        result = router.on_intent_detected("image_generation")
        assert result is None

    def test_dedup_same_intent(self):
        """Same intent should not start multiple pre-warms."""
        call_count = 0
        def counting_executor(tool, ctx):
            nonlocal call_count
            call_count += 1
            return "ok"

        router = TokenAheadRouter(tool_executor=counting_executor)
        router.on_intent_detected("image_generation")
        router.on_intent_detected("image_generation")
        time.sleep(0.05)
        assert call_count == 1

    def test_on_tag_detected(self):
        router = TokenAheadRouter(tool_executor=make_executor())
        result = router.on_tag_detected("image", "a cute selfie")
        assert result == "generate_image_request"

    def test_on_tag_detected_unknown(self):
        router = TokenAheadRouter(tool_executor=make_executor())
        result = router.on_tag_detected("unknown_tag", "value")
        assert result is None

    def test_collect_results_success(self):
        router = TokenAheadRouter(tool_executor=make_executor(delay=0.01), timeout=2.0)
        router.on_intent_detected("image_generation", {"prompt": "selfie"})
        time.sleep(0.05)  # Give thread time to finish
        results = router.collect_results()
        assert len(results) == 1
        assert results[0].success
        assert results[0].tool_name == "generate_image_request"
        assert results[0].latency_ms > 0

    def test_collect_results_timeout(self):
        router = TokenAheadRouter(tool_executor=make_executor(delay=5.0), timeout=0.1)
        router.on_intent_detected("image_generation")
        results = router.collect_results(timeout=0.1)
        assert len(results) == 1
        assert not results[0].success

    def test_collect_results_failure(self):
        router = TokenAheadRouter(tool_executor=make_failing_executor(), timeout=1.0)
        router.on_intent_detected("image_generation")
        time.sleep(0.05)
        results = router.collect_results()
        assert len(results) == 1
        assert not results[0].success

    def test_multiple_intents(self):
        router = TokenAheadRouter(tool_executor=make_executor(delay=0.01), timeout=2.0)
        router.on_intent_detected("image_generation")
        router.on_intent_detected("memory_lookup")
        time.sleep(0.1)
        results = router.collect_results()
        assert len(results) == 2
        tool_names = {r.tool_name for r in results}
        assert "generate_image_request" in tool_names
        assert "search_memory" in tool_names

    def test_mark_used(self):
        router = TokenAheadRouter(tool_executor=make_executor(delay=0.01), timeout=2.0)
        router.on_intent_detected("image_generation")
        time.sleep(0.05)
        router.collect_results()
        router.mark_used("generate_image_request")
        # Check the result was marked
        for r in router._results:
            if r.tool_name == "generate_image_request":
                assert r.was_used

    def test_reset(self):
        router = TokenAheadRouter(tool_executor=make_executor(delay=0.01))
        router.on_intent_detected("image_generation")
        time.sleep(0.05)
        router.reset()
        assert router.active_count == 0
        assert router._futures == {}

    def test_active_and_completed_counts(self):
        router = TokenAheadRouter(tool_executor=make_executor(delay=0.5))
        router.on_intent_detected("image_generation")
        assert router.active_count >= 0  # May or may not have started yet
        time.sleep(0.7)
        assert router.completed_count >= 1

    def test_custom_intent_map(self):
        custom_map = {"custom_action": "my_custom_tool"}
        router = TokenAheadRouter(
            tool_executor=make_executor(),
            intent_map=custom_map,
        )
        result = router.on_intent_detected("custom_action")
        assert result == "my_custom_tool"

    def test_shutdown(self):
        router = TokenAheadRouter(tool_executor=make_executor())
        router.shutdown()
        # Should not raise


class TestTokenAheadRouterIntentMap:
    """Test the default intent → tool mapping."""

    def test_all_default_intents(self):
        router = TokenAheadRouter(tool_executor=make_executor())
        expected = {
            "image_generation": "generate_image_request",
            "selfie": "generate_image_request",
            "memory_lookup": "search_memory",
            "memory_store": "store_memory",
            "character_state": "get_character_state",
            "mood_update": "update_mood",
            "relationship": "adjust_relationship",
            "dice_roll": "roll_dice",
            "voice_message": "send_voice_message",
        }
        for intent, tool in expected.items():
            result = router.on_intent_detected(intent)
            assert result == tool, f"Intent '{intent}' should map to '{tool}'"
            router.reset()  # Reset for next test
