"""Tests for vision skills, evaluation skills, and activity logger data collection wiring."""

from __future__ import annotations

import base64
import json
import os
import tempfile
from pathlib import Path
from unittest.mock import MagicMock, patch, PropertyMock

import pytest


# ── Vision Skills Tests ──────────────────────────────────────────────


class TestVisionHelpers:
    """Tests for vision skill helper functions."""

    def test_image_to_data_url_png(self, tmp_path):
        """PNG files produce correct data URL prefix."""
        from engine.skills.builtin.vision_skills import _image_to_data_url

        img = tmp_path / "test.png"
        img.write_bytes(b"\x89PNG\r\n\x1a\n" + b"\x00" * 16)
        result = _image_to_data_url(str(img))
        assert result.startswith("data:image/png;base64,")

    def test_image_to_data_url_jpeg(self, tmp_path):
        """JPEG files produce correct MIME type."""
        from engine.skills.builtin.vision_skills import _image_to_data_url

        img = tmp_path / "test.jpg"
        img.write_bytes(b"\xff\xd8\xff" + b"\x00" * 16)
        result = _image_to_data_url(str(img))
        assert result.startswith("data:image/jpeg;base64,")

    def test_image_to_data_url_missing_file(self):
        """Missing file raises FileNotFoundError."""
        from engine.skills.builtin.vision_skills import _image_to_data_url

        with pytest.raises(FileNotFoundError):
            _image_to_data_url("/nonexistent/image.png")

    def test_image_to_data_url_roundtrip(self, tmp_path):
        """Encoded content round-trips correctly."""
        from engine.skills.builtin.vision_skills import _image_to_data_url

        content = b"test image content bytes"
        img = tmp_path / "test.webp"
        img.write_bytes(content)
        result = _image_to_data_url(str(img))
        _, encoded = result.split(",", 1)
        decoded = base64.b64decode(encoded)
        assert decoded == content

    def test_resolve_vision_model_default(self):
        """Default vision model returned when config unavailable."""
        from engine.skills.builtin.vision_skills import _resolve_vision_model, VISION_MODEL

        with patch("engine.config.get_config", side_effect=ImportError):
            result = _resolve_vision_model()
        assert result == VISION_MODEL

    def test_resolve_vision_model_from_config(self):
        """Vision model loaded from config when available."""
        from engine.skills.builtin.vision_skills import _resolve_vision_model

        mock_cfg = MagicMock()
        mock_cfg.get.return_value = "custom/vision-model"
        with patch("engine.config.get_config", return_value=mock_cfg):
            result = _resolve_vision_model()
        assert result == "custom/vision-model"


class TestScreenToText:
    """Tests for the screen_to_text skill."""

    def test_basic_call(self, tmp_path):
        """Basic screenshot analysis returns model response."""
        from engine.skills.builtin.vision_skills import screen_to_text

        img = tmp_path / "screen.png"
        img.write_bytes(b"\x89PNG" + b"\x00" * 20)

        mock_response = MagicMock()
        mock_response.text = "A desktop showing a code editor"

        with patch("engine.skills.builtin.vision_skills._get_client") as mock_client, \
             patch("engine.skills.builtin.vision_skills._resolve_vision_model", return_value="test-model"):
            mock_client.return_value.chat_with_images.return_value = mock_response
            result = screen_to_text(str(img))

        assert "code editor" in result

    def test_with_focus_area(self, tmp_path):
        """Focus parameter modifies the question."""
        from engine.skills.builtin.vision_skills import screen_to_text

        img = tmp_path / "screen.png"
        img.write_bytes(b"\x89PNG" + b"\x00" * 20)

        mock_response = MagicMock()
        mock_response.text = "The toolbar has 5 buttons"

        with patch("engine.skills.builtin.vision_skills._get_client") as mock_client, \
             patch("engine.skills.builtin.vision_skills._resolve_vision_model", return_value="test-model"):
            mock_client.return_value.chat_with_images.return_value = mock_response
            result = screen_to_text(str(img), focus="the toolbar")

        assert "toolbar" in result or "buttons" in result

    def test_missing_file_returns_error(self):
        """Missing file returns error message instead of raising."""
        from engine.skills.builtin.vision_skills import screen_to_text

        result = screen_to_text("/nonexistent/image.png")
        assert "Error" in result
        assert "not found" in result

    def test_data_url_input(self):
        """Data URL inputs are passed through without file conversion."""
        from engine.skills.builtin.vision_skills import screen_to_text

        mock_response = MagicMock()
        mock_response.text = "Test content"

        with patch("engine.skills.builtin.vision_skills._get_client") as mock_client, \
             patch("engine.skills.builtin.vision_skills._resolve_vision_model", return_value="m"):
            mock_client.return_value.chat_with_images.return_value = mock_response
            result = screen_to_text("data:image/png;base64,dGVzdA==")

        assert result == "Test content"


class TestUIAnalysis:
    """Tests for the ui_analysis skill."""

    def test_basic_analysis(self, tmp_path):
        """UI analysis returns structured element list."""
        from engine.skills.builtin.vision_skills import ui_analysis

        img = tmp_path / "ui.png"
        img.write_bytes(b"\x89PNG" + b"\x00" * 20)

        mock_response = MagicMock()
        mock_response.text = "1. Button: Submit (center, enabled)\n2. Input: Search (top, focused)"

        with patch("engine.skills.builtin.vision_skills._get_client") as mock_client, \
             patch("engine.skills.builtin.vision_skills._resolve_vision_model", return_value="m"):
            mock_client.return_value.chat_with_images.return_value = mock_response
            result = ui_analysis(str(img))

        assert "Button" in result or "Submit" in result

    def test_filtered_element_types(self, tmp_path):
        """Element type filter modifies the question."""
        from engine.skills.builtin.vision_skills import ui_analysis

        img = tmp_path / "ui.png"
        img.write_bytes(b"\x89PNG" + b"\x00" * 20)

        mock_response = MagicMock()
        mock_response.text = "Found 3 buttons"

        with patch("engine.skills.builtin.vision_skills._get_client") as mock_client, \
             patch("engine.skills.builtin.vision_skills._resolve_vision_model", return_value="m"):
            mock_client.return_value.chat_with_images.return_value = mock_response
            result = ui_analysis(str(img), element_types="buttons,inputs")

        assert "buttons" in result.lower() or "3" in result


class TestCompareScreenshots:
    """Tests for the compare_screenshots skill."""

    def test_basic_comparison(self, tmp_path):
        """Two screenshots are compared and differences described."""
        from engine.skills.builtin.vision_skills import compare_screenshots

        before = tmp_path / "before.png"
        after = tmp_path / "after.png"
        before.write_bytes(b"\x89PNG" + b"\x00" * 20)
        after.write_bytes(b"\x89PNG" + b"\x00" * 20)

        mock_response = MagicMock()
        mock_response.text = "A new dialog appeared in the center"

        with patch("engine.skills.builtin.vision_skills._get_client") as mock_client, \
             patch("engine.skills.builtin.vision_skills._resolve_vision_model", return_value="m"):
            mock_client.return_value.chat.return_value = mock_response
            result = compare_screenshots(str(before), str(after))

        assert "dialog" in result

    def test_with_context(self, tmp_path):
        """Context about the action is included in the prompt."""
        from engine.skills.builtin.vision_skills import compare_screenshots

        before = tmp_path / "before.png"
        after = tmp_path / "after.png"
        before.write_bytes(b"\x89PNG" + b"\x00" * 20)
        after.write_bytes(b"\x89PNG" + b"\x00" * 20)

        mock_response = MagicMock()
        mock_response.text = "Button state changed"

        with patch("engine.skills.builtin.vision_skills._get_client") as mock_client, \
             patch("engine.skills.builtin.vision_skills._resolve_vision_model", return_value="m"):
            mock_client.return_value.chat.return_value = mock_response
            result = compare_screenshots(
                str(before), str(after), context="Clicked the submit button"
            )

        assert isinstance(result, str) and len(result) > 0

    def test_missing_before_file(self):
        """Missing before file returns error."""
        from engine.skills.builtin.vision_skills import compare_screenshots

        result = compare_screenshots("/missing/before.png", "/missing/after.png")
        assert "Error" in result


class TestReadTextFromImage:
    """Tests for the read_text_from_image skill."""

    def test_basic_ocr(self, tmp_path):
        """Text extraction returns readable text."""
        from engine.skills.builtin.vision_skills import read_text_from_image

        img = tmp_path / "text.png"
        img.write_bytes(b"\x89PNG" + b"\x00" * 20)

        mock_response = MagicMock()
        mock_response.text = "Error: Connection refused\nRetry in 5 seconds"

        with patch("engine.skills.builtin.vision_skills._get_client") as mock_client, \
             patch("engine.skills.builtin.vision_skills._resolve_vision_model", return_value="m"):
            mock_client.return_value.chat_with_images.return_value = mock_response
            result = read_text_from_image(str(img))

        assert "Connection refused" in result

    def test_with_region(self, tmp_path):
        """Region parameter narrows the extraction focus."""
        from engine.skills.builtin.vision_skills import read_text_from_image

        img = tmp_path / "text.png"
        img.write_bytes(b"\x89PNG" + b"\x00" * 20)

        mock_response = MagicMock()
        mock_response.text = "File Edit View Help"

        with patch("engine.skills.builtin.vision_skills._get_client") as mock_client, \
             patch("engine.skills.builtin.vision_skills._resolve_vision_model", return_value="m"):
            mock_client.return_value.chat_with_images.return_value = mock_response
            result = read_text_from_image(str(img), region="menu bar")

        assert "File" in result


class TestCaptureScreenshot:
    """Tests for the capture_screenshot skill."""

    def test_successful_capture(self, tmp_path):
        """Successful capture returns file path."""
        from engine.skills.builtin.vision_skills import capture_screenshot

        with patch("subprocess.run") as mock_run, \
             patch("engine.skills.builtin.vision_skills.Path") as MockPath:
            mock_run.return_value = MagicMock(returncode=0)
            # Make the output path "exist"
            mock_instance = MagicMock()
            mock_instance.exists.return_value = True
            mock_instance.__str__ = lambda self: "artifacts/screenshots/capture_1234.png"
            mock_instance.__truediv__ = lambda self, other: mock_instance
            mock_instance.as_posix.return_value = "artifacts/screenshots/capture_1234.png"
            MockPath.return_value = mock_instance
            MockPath.return_value.mkdir = MagicMock()

            result = capture_screenshot()

        assert isinstance(result, str)

    def test_failed_capture(self):
        """Failed capture returns error message."""
        from engine.skills.builtin.vision_skills import capture_screenshot

        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(
                returncode=1, stderr="Permission denied"
            )
            result = capture_screenshot()

        assert "failed" in result.lower() or "Permission" in result


# ── Evaluation Skills Tests ──────────────────────────────────────────


class TestEvalLeaderboard:
    """Tests for eval_leaderboard skill."""

    def test_returns_json(self):
        """Leaderboard returns valid JSON."""
        from engine.skills.builtin.evaluation_skills import eval_leaderboard

        mock_runner = MagicMock()
        mock_runner.get_leaderboard.return_value = {
            "router_v2": {"best_score": 0.85, "last_run": "2026-03-01"},
        }
        with patch("engine.skills.builtin.evaluation_skills._get_benchmark_runner", return_value=mock_runner):
            result = eval_leaderboard()

        data = json.loads(result)
        assert "router_v2" in data
        assert data["router_v2"]["best_score"] == 0.85

    def test_handles_error(self):
        """Leaderboard handles errors gracefully."""
        from engine.skills.builtin.evaluation_skills import eval_leaderboard

        with patch("engine.skills.builtin.evaluation_skills._get_benchmark_runner", side_effect=RuntimeError("DB locked")):
            result = eval_leaderboard()

        assert "unavailable" in result.lower()


class TestEvalHistory:
    """Tests for eval_history skill."""

    def test_filtered_history(self):
        """History filtered by model type."""
        from engine.skills.builtin.evaluation_skills import eval_history

        mock_runner = MagicMock()
        mock_runner.get_history.return_value = [
            {"model_type": "router_v2", "score": 0.82, "timestamp": "2026-03-01"},
        ]
        with patch("engine.skills.builtin.evaluation_skills._get_benchmark_runner", return_value=mock_runner):
            result = eval_history(model_type="router_v2", limit=5)

        data = json.loads(result)
        assert len(data) == 1
        mock_runner.get_history.assert_called_with(model_type="router_v2", limit=5)

    def test_all_history(self):
        """Empty model_type returns all history."""
        from engine.skills.builtin.evaluation_skills import eval_history

        mock_runner = MagicMock()
        mock_runner.get_history.return_value = []
        with patch("engine.skills.builtin.evaluation_skills._get_benchmark_runner", return_value=mock_runner):
            eval_history()

        mock_runner.get_history.assert_called_with(model_type=None, limit=10)


class TestEvalRunBenchmark:
    """Tests for eval_run_benchmark skill."""

    def test_single_model(self):
        """Benchmark single model type."""
        from engine.skills.builtin.evaluation_skills import eval_run_benchmark

        mock_result = MagicMock()
        mock_result.model_type = "router_v2"
        mock_result.accuracy = 0.88
        mock_result.f1 = 0.85
        mock_result.aggregate_score = 0.86
        mock_result.promoted = True
        mock_result.latency_ms_avg = 42.5
        mock_result.error = None

        mock_runner = MagicMock()
        mock_runner.run.return_value = mock_result

        with patch("engine.skills.builtin.evaluation_skills._get_benchmark_runner", return_value=mock_runner):
            result = eval_run_benchmark(model_type="router_v2")

        data = json.loads(result)
        assert data["accuracy"] == 0.88
        assert data["promoted"] is True

    def test_all_models(self):
        """Benchmark all models returns list."""
        from engine.skills.builtin.evaluation_skills import eval_run_benchmark

        mock_r1 = MagicMock(model_type="r1", accuracy=0.8, aggregate_score=0.7, promoted=False, error=None)
        mock_r2 = MagicMock(model_type="r2", accuracy=0.9, aggregate_score=0.85, promoted=True, error=None)

        mock_runner = MagicMock()
        mock_runner.run_all.return_value = [mock_r1, mock_r2]

        with patch("engine.skills.builtin.evaluation_skills._get_benchmark_runner", return_value=mock_runner):
            result = eval_run_benchmark()

        data = json.loads(result)
        assert isinstance(data, list)
        assert len(data) == 2


class TestEvalCollectorStats:
    """Tests for eval_collector_stats skill."""

    def test_returns_stats(self):
        """Collector stats returns JSON with counts."""
        from engine.skills.builtin.evaluation_skills import eval_collector_stats

        mock_collector = MagicMock()
        mock_collector.get_stats.return_value = {
            "live_buffers": {"conversational": 42, "tool_dispatch": 15},
            "total_flushed": 1200,
        }
        with patch("engine.skills.builtin.evaluation_skills._get_data_collector", return_value=mock_collector):
            result = eval_collector_stats()

        data = json.loads(result)
        assert data["live_buffers"]["conversational"] == 42


class TestEvalFlushData:
    """Tests for eval_flush_data skill."""

    def test_flush_specific(self):
        """Flush specific model type."""
        from engine.skills.builtin.evaluation_skills import eval_flush_data

        mock_collector = MagicMock()
        mock_collector.flush.return_value = 25
        with patch("engine.skills.builtin.evaluation_skills._get_data_collector", return_value=mock_collector):
            result = eval_flush_data(model_type="conversational")

        data = json.loads(result)
        assert data["conversational"] == 25

    def test_flush_all(self):
        """Flush all model types."""
        from engine.skills.builtin.evaluation_skills import eval_flush_data

        mock_collector = MagicMock()
        mock_collector.flush_all.return_value = {"conversational": 10, "tool_dispatch": 5}
        with patch("engine.skills.builtin.evaluation_skills._get_data_collector", return_value=mock_collector):
            result = eval_flush_data()

        data = json.loads(result)
        assert data["conversational"] == 10


class TestEvalFlywheelStats:
    """Tests for eval_flywheel_stats skill."""

    def test_returns_stats(self):
        """Flywheel stats returns JSON."""
        from engine.skills.builtin.evaluation_skills import eval_flywheel_stats

        mock_fw = MagicMock()
        mock_fw.get_stats.return_value = {"total_examples": 500, "exported": 200}
        with patch("engine.skills.builtin.evaluation_skills._get_training_flywheel", return_value=mock_fw):
            result = eval_flywheel_stats()

        data = json.loads(result)
        assert data["total_examples"] == 500


class TestEvalStoreResult:
    """Tests for eval_store_result skill."""

    def test_successful_store(self):
        """Successful Nexus store returns entry ID."""
        from engine.skills.builtin.evaluation_skills import eval_store_result

        mock_client = MagicMock()
        mock_client.add_entry.return_value = "abc123"
        with patch("engine.skills.builtin.evaluation_skills._get_nexus_client", return_value=mock_client):
            result = eval_store_result("Test Result", '{"score": 0.9}')

        assert "abc123" in result
        mock_client.add_entry.assert_called_once()

    def test_failed_store(self):
        """Failed Nexus store returns error."""
        from engine.skills.builtin.evaluation_skills import eval_store_result

        mock_client = MagicMock()
        mock_client.add_entry.return_value = None
        with patch("engine.skills.builtin.evaluation_skills._get_nexus_client", return_value=mock_client):
            result = eval_store_result("Test", "content")

        assert "Failed" in result


class TestEvalPruneLowQuality:
    """Tests for eval_prune_low_quality skill."""

    def test_prune_returns_count(self):
        """Prune returns count of removed examples."""
        from engine.skills.builtin.evaluation_skills import eval_prune_low_quality

        mock_collector = MagicMock()
        mock_collector.prune_low_quality.return_value = 15
        with patch("engine.skills.builtin.evaluation_skills._get_data_collector", return_value=mock_collector):
            result = eval_prune_low_quality(min_quality=0.4)

        assert "15" in result
        mock_collector.prune_low_quality.assert_called_with(0.4)


# ── ActivityLogger DataCollector Wiring Tests ────────────────────────


class TestActivityLoggerDataCollection:
    """Tests for DataCollector wiring in ActivityLoggerInterceptor."""

    def _make_ctx(self, **overrides):
        """Create a mock ResponseContext."""
        defaults = {
            "chain_id": "chain-1",
            "agent_id": "agent-1",
            "agent_name": "Aria",
            "reply": "Hello! How can I help?",
            "scene": "bedroom",
            "auto_results": {},
            "game_state": True,
            "user_input": "Hi there",
            "system_prompt": "You are Aria, a helpful assistant.",
            "history": [
                {"role": "user", "content": "Hi there"},
            ],
        }
        defaults.update(overrides)
        ctx = MagicMock()
        ctx.get = lambda k, d=None: defaults.get(k, d)
        return ctx

    def test_collects_conversational_data(self):
        """Interceptor feeds conversation data to DataCollector."""
        from engine.agents.interceptors.activity_logger import ActivityLoggerInterceptor

        interceptor = ActivityLoggerInterceptor()
        ctx = self._make_ctx()

        mock_collector = MagicMock()
        mock_ec = MagicMock()

        with patch("content.simulation.database.events.get_event_chain", return_value=mock_ec), \
             patch("training.data_collector.get_data_collector", return_value=mock_collector):
            interceptor.post_call(ctx)

        mock_collector.collect_conversation.assert_called_once()
        call_args = mock_collector.collect_conversation.call_args
        assert call_args.kwargs.get("character_id") == "agent-1" or \
               (len(call_args.args) >= 4 and call_args.args[3] == "")

    def test_collects_tool_dispatch_data(self):
        """Interceptor feeds tool call data to DataCollector."""
        from engine.agents.interceptors.activity_logger import ActivityLoggerInterceptor

        interceptor = ActivityLoggerInterceptor()
        ctx = self._make_ctx(
            auto_results={"generate_portrait": "portrait_url.png"},
        )

        mock_collector = MagicMock()
        mock_ec = MagicMock()

        with patch("content.simulation.database.events.get_event_chain", return_value=mock_ec), \
             patch("training.data_collector.get_data_collector", return_value=mock_collector):
            interceptor.post_call(ctx)

        mock_collector.collect_tool_call.assert_called_once()
        call_kwargs = mock_collector.collect_tool_call.call_args
        assert call_kwargs.kwargs.get("tool_name") == "generate_portrait" or \
               (len(call_kwargs.args) >= 2 and call_kwargs.args[1] == "generate_portrait")

    def test_skips_short_replies(self):
        """Short replies are not collected as training data."""
        from engine.agents.interceptors.activity_logger import ActivityLoggerInterceptor

        interceptor = ActivityLoggerInterceptor()
        ctx = self._make_ctx(reply="Ok")

        mock_collector = MagicMock()
        mock_ec = MagicMock()

        with patch("content.simulation.database.events.get_event_chain", return_value=mock_ec), \
             patch("training.data_collector.get_data_collector", return_value=mock_collector):
            interceptor.post_call(ctx)

        mock_collector.collect_conversation.assert_not_called()

    def test_handles_collector_import_failure(self):
        """Interceptor continues even if DataCollector import fails."""
        from engine.agents.interceptors.activity_logger import ActivityLoggerInterceptor

        interceptor = ActivityLoggerInterceptor()
        ctx = self._make_ctx()

        mock_ec = MagicMock()

        with patch("content.simulation.database.events.get_event_chain", return_value=mock_ec), \
             patch("training.data_collector.get_data_collector", side_effect=ImportError("no module")):
            # Should not raise
            interceptor.post_call(ctx)

    def test_no_user_input_skips_tool_collection(self):
        """Without user input, tool dispatch data is not collected."""
        from engine.agents.interceptors.activity_logger import ActivityLoggerInterceptor

        interceptor = ActivityLoggerInterceptor()
        ctx = self._make_ctx(
            user_input="",
            auto_results={"some_skill": "result"},
        )

        mock_collector = MagicMock()
        mock_ec = MagicMock()

        with patch("content.simulation.database.events.get_event_chain", return_value=mock_ec), \
             patch("training.data_collector.get_data_collector", return_value=mock_collector):
            interceptor.post_call(ctx)

        mock_collector.collect_tool_call.assert_not_called()


# ── Skill Registration Tests ────────────────────────────────────────


class TestSkillRegistration:
    """Verify all new skills are properly registered."""

    def test_vision_skills_registered(self):
        """All 5 vision skills are in the registry."""
        from engine.skills.registry import SKILL_REGISTRY
        import engine.skills.builtin.vision_skills  # Force import

        names = set()
        for metas in SKILL_REGISTRY._skills.values():
            for m in metas:
                names.add(m.name)
        expected = {
            "screen_to_text", "ui_analysis", "compare_screenshots",
            "read_text_from_image", "capture_screenshot",
        }
        assert expected.issubset(names), f"Missing: {expected - names}"

    def test_evaluation_skills_registered(self):
        """All 8 evaluation skills are in the registry."""
        from engine.skills.registry import SKILL_REGISTRY
        import engine.skills.builtin.evaluation_skills  # Force import

        names = set()
        for metas in SKILL_REGISTRY._skills.values():
            for m in metas:
                names.add(m.name)
        expected = {
            "eval_leaderboard", "eval_history", "eval_run_benchmark",
            "eval_collector_stats", "eval_flush_data",
            "eval_flywheel_stats", "eval_store_result",
            "eval_prune_low_quality",
        }
        assert expected.issubset(names), f"Missing: {expected - names}"

    def test_vision_skills_have_correct_pack(self):
        """Vision skills are in the 'vision' pack."""
        from engine.skills.registry import SKILL_REGISTRY
        import engine.skills.builtin.vision_skills

        vision_names = {"screen_to_text", "ui_analysis", "compare_screenshots",
                        "read_text_from_image", "capture_screenshot"}
        for metas in SKILL_REGISTRY._skills.values():
            for meta in metas:
                if meta.name in vision_names:
                    assert meta.pack == "vision", f"{meta.name} has pack={meta.pack}"

    def test_evaluation_skills_have_correct_pack(self):
        """Evaluation skills are in the 'evaluation' pack."""
        from engine.skills.registry import SKILL_REGISTRY
        import engine.skills.builtin.evaluation_skills

        for metas in SKILL_REGISTRY._skills.values():
            for meta in metas:
                if meta.name.startswith("eval_"):
                    assert meta.pack == "evaluation", f"{meta.name} has pack={meta.pack}"
