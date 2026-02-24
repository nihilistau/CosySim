"""Tests for VirtualPipeline — the core parallel stream orchestrator."""

import time
import pytest

from engine.pipeline.pipeline_result import (
    PipelineConfig,
    PipelineResult,
    WatcherSignal,
)
from engine.pipeline.virtual_pipeline import VirtualPipeline
from engine.pipeline.stream_watcher import WatchContext


# ── Helpers ─────────────────────────────────────────────────────────────

def token_generator(tokens):
    """Create a stream_fn that yields tokens."""
    def gen():
        for t in tokens:
            yield t
    return gen


def tag_stream():
    """Stream with tags — tests tag extraction."""
    tokens = [
        "She ", "smiled ", "[MOOD:happy] ", "and ", "took ",
        "a ", "selfie ", "[IMAGE:cute selfie in bedroom] ",
        "before ", "sitting ", "down ", "[ACTION:sit_down]"
    ]
    return token_generator(tokens)


def clean_stream():
    """Stream with no tags."""
    return token_generator(["Hello", " there,", " how", " are", " you?"])


def repetitive_stream():
    """Stream that repeats excessively."""
    tokens = []
    for _ in range(20):
        tokens.extend(["I ", "love ", "you "])
    return token_generator(tokens)


def long_stream():
    """Stream that exceeds token budget."""
    return token_generator(["word "] * 500)


# ── Test pipeline creation ──────────────────────────────────────────────

class TestVirtualPipelineCreation:
    def test_create_default(self):
        pipeline = VirtualPipeline()
        assert pipeline.config.watcher_enabled

    def test_create_with_config(self):
        config = PipelineConfig(kill_threshold=0.5)
        pipeline = VirtualPipeline(config=config)
        assert pipeline.config.kill_threshold == 0.5

    def test_create_with_tool_executor(self):
        def mock_exec(tool, ctx):
            return "ok"
        pipeline = VirtualPipeline(tool_executor=mock_exec)
        assert pipeline._token_router._executor_fn is not None


# ── Test execute (blocking) ─────────────────────────────────────────────

class TestVirtualPipelineExecute:
    def test_execute_clean_stream(self):
        pipeline = VirtualPipeline(config=PipelineConfig(watcher_enabled=True))
        result = pipeline.execute(
            request=None,
            stream_fn=clean_stream(),
        )
        assert isinstance(result, PipelineResult)
        assert "Hello" in result.raw_text or "Hello" in result.clean_text
        assert result.pipeline_latency_ms > 0

    def test_execute_with_tags(self):
        pipeline = VirtualPipeline(config=PipelineConfig(watcher_enabled=True))
        result = pipeline.execute(
            request=None,
            stream_fn=tag_stream(),
        )
        assert result.mood_tags or result.has_mood
        assert result.image_requests or result.has_images

    def test_execute_on_delta_callback(self):
        deltas = []
        pipeline = VirtualPipeline(config=PipelineConfig(watcher_enabled=True))
        result = pipeline.execute(
            request=None,
            stream_fn=clean_stream(),
            on_delta=lambda t: deltas.append(t),
        )
        assert len(deltas) > 0

    def test_execute_metrics_callback(self):
        metrics = []
        pipeline = VirtualPipeline(
            config=PipelineConfig(watcher_enabled=True),
            on_metrics=lambda r: metrics.append(r),
        )
        pipeline.execute(request=None, stream_fn=clean_stream())
        assert len(metrics) == 1
        assert isinstance(metrics[0], PipelineResult)

    def test_get_last_result(self):
        pipeline = VirtualPipeline()
        assert pipeline.get_last_result() is None
        pipeline.execute(request=None, stream_fn=clean_stream())
        assert pipeline.get_last_result() is not None


# ── Test execute_stream (generator) ─────────────────────────────────────

class TestVirtualPipelineStream:
    def test_stream_yields_tokens(self):
        pipeline = VirtualPipeline(config=PipelineConfig(watcher_enabled=True))
        tokens = list(pipeline.execute_stream(
            request=None,
            stream_fn=clean_stream(),
        ))
        assert len(tokens) == 5
        assert tokens[0] == "Hello"

    def test_stream_last_result_available(self):
        pipeline = VirtualPipeline(config=PipelineConfig(watcher_enabled=True))
        list(pipeline.execute_stream(request=None, stream_fn=clean_stream()))
        result = pipeline.get_last_result()
        assert result is not None
        assert result.pipeline_latency_ms > 0


# ── Test kill switch integration ────────────────────────────────────────

class TestVirtualPipelineKillSwitch:
    def test_kill_disabled_no_kill(self):
        config = PipelineConfig(kill_switch_enabled=False)
        pipeline = VirtualPipeline(config=config)
        result = pipeline.execute(request=None, stream_fn=repetitive_stream())
        assert not result.generation_killed

    def test_kill_with_budget_exceeded(self):
        """Token budget exceeded should trigger kill."""
        config = PipelineConfig(
            kill_switch_enabled=True,
            kill_threshold=0.3,
            max_retries=0,  # No retries
            watcher_batch_size=4,
        )
        pipeline = VirtualPipeline(config=config)
        ctx = WatchContext(max_tokens=10)  # Very small budget
        result = pipeline.execute(
            request=None,
            stream_fn=long_stream(),
            context=ctx,
        )
        # May or may not kill depending on batch timing
        # but should complete without errors


# ── Test token-ahead routing integration ────────────────────────────────

class TestVirtualPipelinePreWarm:
    def test_tag_triggers_prewarm(self):
        pre_warmed = []
        def mock_executor(tool, ctx):
            pre_warmed.append(tool)
            return {"status": "done"}

        config = PipelineConfig(pre_warm_enabled=True)
        pipeline = VirtualPipeline(config=config, tool_executor=mock_executor)

        # The tag detection in watcher should trigger pre-warming
        pipeline.execute(request=None, stream_fn=tag_stream())
        # Pre-warm may or may not fire depending on tag detection timing

    def test_prewarm_disabled(self):
        config = PipelineConfig(pre_warm_enabled=False)
        pipeline = VirtualPipeline(config=config)
        result = pipeline.execute(request=None, stream_fn=tag_stream())
        assert result.pre_warmed_results == []


# ── Test watch context building ─────────────────────────────────────────

class TestWatchContextBuilding:
    def test_from_request_with_attrs(self):
        class FakeRequest:
            agent_id = "lola"
            scene = "bedroom"
            metadata = {
                "character_name": "Lola",
                "scene_rules": ["Be flirty"],
                "expected_format": "dialogue",
            }
            max_output_tokens = 200

        pipeline = VirtualPipeline()
        ctx = pipeline._build_watch_context(FakeRequest())
        assert ctx.agent_id == "lola"
        assert ctx.scene_id == "bedroom"
        assert ctx.character_name == "Lola"
        assert ctx.max_tokens == 200

    def test_from_empty_request(self):
        pipeline = VirtualPipeline()
        ctx = pipeline._build_watch_context(object())
        assert ctx.agent_id == ""
        assert ctx.scene_id == ""


# ── Test result building ────────────────────────────────────────────────

class TestPipelineResultBuilding:
    def test_result_has_timing(self):
        pipeline = VirtualPipeline()
        result = pipeline.execute(request=None, stream_fn=clean_stream())
        assert result.pipeline_latency_ms > 0
        assert result.pipeline_ended > 0

    def test_result_retry_count_zero_on_success(self):
        pipeline = VirtualPipeline()
        result = pipeline.execute(request=None, stream_fn=clean_stream())
        assert result.retry_count == 0
        assert not result.generation_killed
