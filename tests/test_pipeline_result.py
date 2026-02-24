"""Tests for engine.pipeline.pipeline_result data structures."""

import time
from engine.pipeline.pipeline_result import (
    PipelineConfig,
    PipelineResult,
    PreWarmResult,
    WatcherAnalysis,
    WatcherSignal,
)


class TestWatcherSignal:
    def test_values(self):
        assert WatcherSignal.CONTINUE.value == "continue"
        assert WatcherSignal.KILL.value == "kill"
        assert WatcherSignal.PRE_WARM.value == "pre_warm"
        assert WatcherSignal.ROUTE.value == "route"


class TestWatcherAnalysis:
    def test_defaults(self):
        a = WatcherAnalysis()
        assert a.intent == ""
        assert a.acceptability == 1.0
        assert a.signals == []
        assert a.tokens_analyzed == 0
        assert a.latency_ms == 0.0

    def test_with_values(self):
        a = WatcherAnalysis(
            intent="image_gen",
            acceptability=0.85,
            signals=[WatcherSignal.PRE_WARM],
            tokens_analyzed=8,
            latency_ms=42.5,
            predicted_tools=["generate_image"],
        )
        assert a.intent == "image_gen"
        assert a.acceptability == 0.85
        assert a.predicted_tools == ["generate_image"]


class TestPipelineConfig:
    def test_defaults(self):
        c = PipelineConfig()
        assert c.watcher_enabled is True
        assert c.kill_threshold == 0.3
        assert c.max_retries == 2
        assert c.watcher_trigger_tokens == 8
        assert c.pre_warm_enabled is True

    def test_from_dict_empty(self):
        c = PipelineConfig.from_dict({})
        assert c.watcher_enabled is True  # default

    def test_from_dict_full(self):
        d = {
            "enabled": False,
            "watcher": {"model_key": "gemma-270m", "trigger_tokens": 12, "batch_size": 32},
            "kill_switch": {"enabled": False, "threshold": 0.5, "max_retries": 3, "repetition_limit": 5},
            "token_ahead": {"enabled": False, "pre_warm_timeout": 10.0},
            "conversation": {"max_branches": 20, "branch_ttl": 600},
        }
        c = PipelineConfig.from_dict(d)
        assert c.watcher_enabled is False
        assert c.watcher_model_key == "gemma-270m"
        assert c.watcher_trigger_tokens == 12
        assert c.kill_switch_enabled is False
        assert c.kill_threshold == 0.5
        assert c.max_retries == 3
        assert c.pre_warm_enabled is False
        assert c.pre_warm_timeout == 10.0
        assert c.max_branches == 20
        assert c.branch_ttl == 600


class TestPreWarmResult:
    def test_defaults(self):
        r = PreWarmResult()
        assert r.tool_name == ""
        assert r.success is True
        assert r.was_used is False

    def test_with_values(self):
        r = PreWarmResult(
            tool_name="generate_image",
            arguments={"prompt": "a selfie"},
            result="image_url",
            latency_ms=500.0,
            was_used=True,
        )
        assert r.tool_name == "generate_image"
        assert r.was_used is True


class TestPipelineResult:
    def test_defaults(self):
        r = PipelineResult()
        assert r.clean_text == ""
        assert r.mood_tags == []
        assert r.generation_killed is False
        assert r.retry_count == 0
        assert r.has_images is False
        assert r.has_mood is False
        assert r.primary_mood == ""
        assert r.watcher_active is False

    def test_properties(self):
        r = PipelineResult(
            clean_text="hello",
            mood_tags=["happy", "excited"],
            image_requests=["a selfie"],
            response_id="resp_abc",
        )
        assert r.has_images is True
        assert r.has_mood is True
        assert r.primary_mood == "happy"
        assert r.is_stateful is True

    def test_pre_warm_hit_rate(self):
        r = PipelineResult(
            pre_warmed_results=[
                PreWarmResult(tool_name="a", was_used=True),
                PreWarmResult(tool_name="b", was_used=False),
                PreWarmResult(tool_name="c", was_used=True),
            ]
        )
        assert abs(r.pre_warm_hit_rate - 2 / 3) < 0.001

    def test_pre_warm_hit_rate_empty(self):
        assert PipelineResult().pre_warm_hit_rate == 0.0

    def test_draft_acceptance_ratio(self):
        r = PipelineResult(draft_accepted=80, draft_rejected=20)
        assert r.draft_acceptance_ratio == 0.8

    def test_draft_acceptance_ratio_zero(self):
        assert PipelineResult().draft_acceptance_ratio == 0.0

    def test_to_inference_response_kwargs(self):
        r = PipelineResult(
            clean_text="hello",
            model="qwen3-8b",
            response_id="resp_x",
            input_tokens=50,
            output_tokens=100,
            pipeline_latency_ms=420.0,
            mood_tags=["happy"],
            image_requests=["selfie"],
            action_tags=["wave"],
        )
        kw = r.to_inference_response_kwargs()
        assert kw["content"] == "hello"
        assert kw["model"] == "qwen3-8b"
        assert kw["response_id"] == "resp_x"
        assert kw["latency_ms"] == 420.0
        assert kw["mood_tags"] == ["happy"]

    def test_watcher_active_property(self):
        r = PipelineResult(
            watcher_analysis=WatcherAnalysis(tokens_analyzed=10)
        )
        assert r.watcher_active is True
