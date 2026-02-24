"""Tests for TrainingCapture — auto-captures training data from pipeline events."""

import json
import pytest
from unittest.mock import MagicMock

from engine.observability.metrics_db import MetricsDB
from engine.observability.training_capture import TrainingCapture


@pytest.fixture
def tmp_db(tmp_path):
    return MetricsDB(tmp_path / "test_training.db")


def make_result(
    raw_text="She smiled [MOOD:happy] and took a selfie [IMAGE:cute selfie]",
    clean_text="She smiled and took a selfie",
    mood_tags=None,
    image_requests=None,
    action_tags=None,
    voice_style="",
    tool_calls=None,
    generation_killed=False,
    killed_content="",
    tier="gpu",
    watcher_analysis=None,
):
    result = MagicMock()
    result.raw_text = raw_text
    result.clean_text = clean_text
    result.mood_tags = mood_tags if mood_tags is not None else ["happy"]
    result.image_requests = image_requests if image_requests is not None else ["cute selfie"]
    result.action_tags = action_tags if action_tags is not None else []
    result.voice_style = voice_style
    result.tool_calls = tool_calls if tool_calls is not None else []
    result.generation_killed = generation_killed
    result.killed_content = killed_content
    result.tier = tier
    if watcher_analysis:
        result.watcher_analysis = watcher_analysis
    else:
        wa = MagicMock()
        wa.acceptability = 0.9
        wa.kill_reason = ""
        result.watcher_analysis = wa
    return result


def make_request(scene="bedroom", agent_id="lola", priority="interactive"):
    req = MagicMock()
    req.scene = scene
    req.agent_id = agent_id
    req.priority = priority
    req.metadata = {"character_name": "Lola", "expected_format": "dialogue"}
    return req


class TestTrainingCapture:
    def test_enabled_by_default(self, tmp_db):
        tc = TrainingCapture(db=tmp_db)
        assert tc.enabled

    def test_disabled_captures_nothing(self, tmp_db):
        tc = TrainingCapture(db=tmp_db, enabled=False)
        result = make_result()
        request = make_request()
        count = tc.on_pipeline_complete(request, result)
        assert count == 0

    def test_captures_tag_extraction(self, tmp_db):
        tc = TrainingCapture(db=tmp_db)
        result = make_result()
        request = make_request()
        count = tc.on_pipeline_complete(request, result)
        assert count >= 1  # At least tag_extraction + priority

        candidates = tmp_db.get_training_candidates(dataset="tag_extraction")
        assert len(candidates) >= 1
        c = candidates[0]
        assert "MOOD:happy" in c["input_text"]
        assert "route_tags" in c["output_text"]

    def test_captures_priority_classify(self, tmp_db):
        tc = TrainingCapture(db=tmp_db)
        result = make_result()
        request = make_request()
        tc.on_pipeline_complete(request, result)

        candidates = tmp_db.get_training_candidates(dataset="priority_classify")
        assert len(candidates) == 1
        c = candidates[0]
        assert "bedroom" in c["input_text"]
        assert "lola" in c["input_text"]

    def test_captures_tool_routing(self, tmp_db):
        tc = TrainingCapture(db=tmp_db)

        tool_call = MagicMock()
        tool_call.name = "search_memory"
        tool_call.arguments = {"query": "coffee"}
        tool_call.success = True

        result = make_result(tool_calls=[tool_call], mood_tags=[], image_requests=[])
        request = make_request()
        tc.on_pipeline_complete(request, result)

        candidates = tmp_db.get_training_candidates(dataset="tool_routing")
        assert len(candidates) == 1
        assert "search_memory" in candidates[0]["output_text"]

    def test_captures_validation_on_kill(self, tmp_db):
        tc = TrainingCapture(db=tmp_db)

        wa = MagicMock()
        wa.acceptability = 0.1
        wa.kill_reason = "repetition_detected"

        result = make_result(
            generation_killed=True,
            killed_content="I I I I I I",
            mood_tags=[],
            image_requests=[],
            watcher_analysis=wa,
        )
        request = make_request()
        tc.on_pipeline_complete(request, result)

        candidates = tmp_db.get_training_candidates(dataset="response_validate")
        assert len(candidates) == 1
        output = json.loads(candidates[0]["output_text"])
        assert output["valid"] is False

    def test_no_tags_no_tag_capture(self, tmp_db):
        tc = TrainingCapture(db=tmp_db)
        result = make_result(
            raw_text="Just normal text",
            clean_text="Just normal text",
            mood_tags=[],
            image_requests=[],
            action_tags=[],
        )
        request = make_request()
        tc.on_pipeline_complete(request, result)

        candidates = tmp_db.get_training_candidates(dataset="tag_extraction")
        assert len(candidates) == 0

    def test_quality_filter(self, tmp_db):
        tc = TrainingCapture(db=tmp_db, min_quality=0.8)

        wa = MagicMock()
        wa.acceptability = 0.5  # Below min_quality

        result = make_result(watcher_analysis=wa)
        request = make_request()
        tc.on_pipeline_complete(request, result)

        # tag_extraction should be filtered out (quality 0.5 < 0.8)
        candidates = tmp_db.get_training_candidates(dataset="tag_extraction")
        assert len(candidates) == 0

    def test_capture_count(self, tmp_db):
        tc = TrainingCapture(db=tmp_db)
        assert tc.capture_count == 0

        result = make_result()
        request = make_request()
        tc.on_pipeline_complete(request, result)
        assert tc.capture_count >= 1

    def test_get_stats(self, tmp_db):
        tc = TrainingCapture(db=tmp_db)
        result = make_result()
        request = make_request()
        tc.on_pipeline_complete(request, result)

        stats = tc.get_stats()
        assert "tag_extraction" in stats
        assert stats["tag_extraction"]["total"] >= 1

    def test_toggle_enabled(self, tmp_db):
        tc = TrainingCapture(db=tmp_db)
        tc.enabled = False
        assert not tc.enabled
        tc.enabled = True
        assert tc.enabled
