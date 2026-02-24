"""Tests for VirtualAgentManager pipeline integration (Phase 5)."""

import pytest
from unittest.mock import MagicMock, patch

from engine.pipeline.pipeline_result import PipelineConfig, PipelineResult


# ── Helpers ──────────────────────────────────────────────────────────────

def make_mock_vam():
    """Create a minimal mock VAM with pipeline support."""
    from engine.agents.virtual_agent_manager import VirtualAgentManager
    vam = VirtualAgentManager.__new__(VirtualAgentManager)
    # Minimal init — just the attributes needed
    vam._agents = {}
    vam._conversations = {}
    vam._total_requests = 0
    vam._total_errors = 0
    vam._total_retries = 0
    vam._repair_successes = 0
    vam._repair_attempts = 0
    vam._quality_gate_calls = 0
    vam._total_tokens_in = 0
    vam._total_tokens_out = 0
    vam._total_latency_ms = 0.0
    vam._stateless_requests = 0
    vam._stateful_requests = 0
    vam._router = None
    vam._router_enabled = False
    vam._router_init_attempted = False
    vam._pipeline = None
    vam._pipeline_init_attempted = False
    vam._pre_hooks = []
    vam._post_hooks = []
    import threading
    vam._router_lock = threading.Lock()
    vam._pipeline_lock = threading.Lock()
    return vam


class TestPipelineLazyInit:
    """Test pipeline lazy initialization in VAM."""

    def test_get_pipeline_returns_none_when_disabled(self):
        vam = make_mock_vam()
        with patch("engine.config.get_config",
                    return_value={"pipeline": {"enabled": False}}):
            assert vam.get_pipeline() is None

    def test_get_pipeline_returns_none_when_no_config(self):
        vam = make_mock_vam()
        with patch("engine.config.get_config",
                    return_value={}):
            assert vam.get_pipeline() is None

    def test_get_pipeline_caches_none_on_failure(self):
        vam = make_mock_vam()
        with patch("engine.config.get_config",
                    return_value={}):
            result1 = vam.get_pipeline()
            result2 = vam.get_pipeline()
            assert result1 is None
            assert result2 is None
            assert vam._pipeline_init_attempted is True

    def test_get_pipeline_creates_pipeline_when_enabled(self):
        vam = make_mock_vam()
        cfg = {
            "pipeline": {
                "enabled": True,
                "watcher": {"enabled": False},
                "kill_switch": {"enabled": False},
                "token_ahead": {"enabled": False},
            }
        }
        with patch("engine.config.get_config",
                    return_value=cfg):
            pipeline = vam.get_pipeline()
            assert pipeline is not None
            assert not pipeline.config.watcher_enabled
            assert not pipeline.config.kill_switch_enabled

    def test_get_pipeline_returns_cached_instance(self):
        vam = make_mock_vam()
        cfg = {
            "pipeline": {
                "enabled": True,
                "watcher": {"enabled": False},
                "kill_switch": {"enabled": False},
                "token_ahead": {"enabled": False},
            }
        }
        with patch("engine.config.get_config",
                    return_value=cfg):
            p1 = vam.get_pipeline()
            p2 = vam.get_pipeline()
            assert p1 is p2


class TestInferWithPipeline:
    """Test infer_with_pipeline fallback and integration."""

    def test_fallback_to_infer_processed_when_no_pipeline(self):
        """When pipeline is unavailable, falls back to infer_processed."""
        vam = make_mock_vam()
        vam._pipeline_init_attempted = True  # Already tried, failed

        mock_result = MagicMock()
        mock_result.clean_text = "Hello!"
        mock_result.mood_tags = []
        mock_result.image_requests = []
        mock_result.action_tags = []
        mock_result.stat_deltas = []
        mock_result.voice_style = None
        mock_result.tool_calls = []
        mock_result.raw_content = "Hello!"

        vam.infer_processed = MagicMock(return_value=mock_result)

        request = MagicMock()
        result = vam.infer_with_pipeline(request)

        # Should have called infer_processed
        vam.infer_processed.assert_called_once()
        # Result should be PipelineResult
        assert isinstance(result, PipelineResult)

    def test_uses_pipeline_when_available(self):
        """When pipeline is available, uses it."""
        vam = make_mock_vam()

        # Set up a real pipeline with a simple stream
        from engine.pipeline.virtual_pipeline import VirtualPipeline
        from engine.pipeline.pipeline_result import PipelineConfig

        config = PipelineConfig(
            watcher_enabled=False,
            kill_switch_enabled=False,
            pre_warm_enabled=False,
        )
        pipeline = VirtualPipeline(vam=vam, config=config)
        vam._pipeline = pipeline

        # Mock infer_stream to yield tokens
        def mock_infer_stream(request, on_event=None):
            yield "Hello "
            yield "world!"

        vam.infer_stream = mock_infer_stream

        request = MagicMock()
        request.messages = [{"role": "user", "content": "Hi"}]
        request.agent_id = "test"
        request.scene_id = "test_scene"

        result = vam.infer_with_pipeline(request)
        assert isinstance(result, PipelineResult)
        # The raw_text should contain the streamed content
        assert "Hello" in result.raw_text or "world" in result.raw_text


class TestVAMStats:
    """Test that pipeline info appears in stats."""

    def test_stats_includes_pipeline_disabled(self):
        vam = make_mock_vam()
        stats = vam.get_stats()
        assert "pipeline_enabled" in stats
        assert stats["pipeline_enabled"] is False

    def test_stats_includes_pipeline_enabled(self):
        vam = make_mock_vam()
        from engine.pipeline.virtual_pipeline import VirtualPipeline
        vam._pipeline = VirtualPipeline(
            config=PipelineConfig(
                watcher_enabled=True,
                kill_switch_enabled=True,
                pre_warm_enabled=False,
            )
        )
        stats = vam.get_stats()
        assert stats["pipeline_enabled"] is True
        assert "pipeline" in stats
        assert stats["pipeline"]["watcher_enabled"] is True
        assert stats["pipeline"]["kill_switch_enabled"] is True
        assert stats["pipeline"]["pre_warm_enabled"] is False
