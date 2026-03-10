"""Comprehensive tests for engine/story — StoryArcEngine, arc templates, skills, blueprint.

All tests run offline with no real MCP/LMStudio/Nexus calls.
"""
from __future__ import annotations

import copy
from unittest.mock import MagicMock, patch

import pytest

# ──── Helpers ────


def _fresh_engine():
    """Return a new, isolated StoryArcEngine (not the singleton)."""
    from engine.story.story_arc import StoryArcEngine
    engine = StoryArcEngine()
    return engine


def _sample_arc(arc_id: str = "test_arc", scene: str = "penthouse"):
    from engine.story.story_arc import ArcStep, StoryArc
    return StoryArc(
        id=arc_id,
        name="Test Arc",
        scene=scene,
        steps=[
            ArcStep("s1", "Step one"),
            ArcStep("s2", "Step two"),
            ArcStep("s3", "Step three"),
            ArcStep("s4", "Step four"),
        ],
    )


# ──── ArcStep ────────────────────────────────────────────────────────────────


class TestArcStep:
    def test_defaults(self):
        from engine.story.story_arc import ArcStep
        step = ArcStep("id1", "description")
        assert step.id == "id1"
        assert step.description == "description"
        assert step.required is True
        assert step.completed is False
        assert step.failed is False
        assert step.metadata == {}

    def test_optional_required_flag(self):
        from engine.story.story_arc import ArcStep
        step = ArcStep("id2", "optional step", required=False)
        assert step.required is False

    def test_metadata_stored(self):
        from engine.story.story_arc import ArcStep
        step = ArcStep("id3", "meta step", metadata={"key": "value"})
        assert step.metadata["key"] == "value"


# ──── StoryArc ───────────────────────────────────────────────────────────────


class TestStoryArc:
    def test_initial_state(self):
        from engine.story.story_arc import ArcStatus
        arc = _sample_arc()
        assert arc.status == ArcStatus.INACTIVE
        assert arc.progress == 0.0
        assert arc.outcome is None

    def test_advance_unknown_step_returns_false(self):
        arc = _sample_arc()
        assert arc.advance("nonexistent") is False

    def test_advance_known_step_returns_true(self):
        arc = _sample_arc()
        assert arc.advance("s1") is True

    def test_first_step_activates_arc(self):
        from engine.story.story_arc import ArcStatus
        arc = _sample_arc()
        arc.advance("s1")
        assert arc.status == ArcStatus.ACTIVE

    def test_progress_at_25_percent(self):
        arc = _sample_arc()
        arc.advance("s1")
        assert arc.progress == pytest.approx(0.25)

    def test_progress_at_50_percent(self):
        arc = _sample_arc()
        arc.advance("s1")
        arc.advance("s2")
        assert arc.progress == pytest.approx(0.5)

    def test_progress_at_75_percent(self):
        arc = _sample_arc()
        arc.advance("s1")
        arc.advance("s2")
        arc.advance("s3")
        assert arc.progress == pytest.approx(0.75)

    def test_all_steps_complete_wins(self):
        from engine.story.story_arc import ArcStatus
        arc = _sample_arc()
        for step_id in ("s1", "s2", "s3", "s4"):
            arc.advance(step_id)
        assert arc.status == ArcStatus.COMPLETED
        assert arc.outcome == "win"
        assert arc.progress == pytest.approx(1.0)

    def test_required_step_fail_loses(self):
        from engine.story.story_arc import ArcStatus
        arc = _sample_arc()
        arc.advance("s1")
        arc.advance("s2", success=False)
        assert arc.status == ArcStatus.FAILED
        assert arc.outcome == "lose"

    def test_optional_step_fail_does_not_lose(self):
        from engine.story.story_arc import ArcStatus, ArcStep, StoryArc
        arc = StoryArc(
            id="opt_arc",
            name="Optional",
            scene="test",
            steps=[
                ArcStep("s1", "Required step"),
                ArcStep("s2", "Optional step", required=False),
            ],
        )
        arc.advance("s1")
        arc.advance("s2", success=False)
        assert arc.status != ArcStatus.FAILED
        assert arc.outcome != "lose"

    def test_no_further_change_after_completed(self):
        from engine.story.story_arc import ArcStatus
        arc = _sample_arc()
        for step_id in ("s1", "s2", "s3", "s4"):
            arc.advance(step_id)
        result = arc.advance("s1", success=False)  # already completed, no change
        assert result is False
        assert arc.status == ArcStatus.COMPLETED

    def test_no_further_change_after_failed(self):
        from engine.story.story_arc import ArcStatus
        arc = _sample_arc()
        arc.advance("s1", success=False)
        arc.advance("s2")  # would complete step, but arc is failed
        assert arc.status == ArcStatus.FAILED

    def test_zero_steps_progress(self):
        from engine.story.story_arc import StoryArc
        arc = StoryArc(id="empty", name="Empty", scene="test")
        arc._recalculate()
        assert arc.progress == 0.0


# ──── StoryArcEngine ─────────────────────────────────────────────────────────


class TestStoryArcEngine:
    def test_create_and_get_arc(self):
        engine = _fresh_engine()
        arc = _sample_arc("arc1")
        engine.create_arc(arc)
        assert engine.get_arc("arc1") is arc

    def test_get_nonexistent_arc_returns_none(self):
        engine = _fresh_engine()
        assert engine.get_arc("ghost") is None

    def test_get_scene_arcs_empty(self):
        engine = _fresh_engine()
        assert engine.get_scene_arcs("penthouse") == []

    def test_get_scene_arcs_returns_registered(self):
        engine = _fresh_engine()
        arc = _sample_arc("a1", scene="casino")
        engine.create_arc(arc)
        result = engine.get_scene_arcs("casino")
        assert len(result) == 1
        assert result[0].id == "a1"

    def test_multiple_arcs_same_scene(self):
        engine = _fresh_engine()
        engine.create_arc(_sample_arc("arc_x", scene="arena"))
        engine.create_arc(_sample_arc("arc_y", scene="arena"))
        assert len(engine.get_scene_arcs("arena")) == 2

    def test_advance_arc_returns_arc(self):
        engine = _fresh_engine()
        arc = _sample_arc("adv1")
        engine.create_arc(arc)
        result = engine.advance_arc("adv1", "s1")
        assert result is arc

    def test_advance_arc_unknown_id_returns_none(self):
        engine = _fresh_engine()
        assert engine.advance_arc("missing", "s1") is None

    def test_advance_arc_updates_progress(self):
        engine = _fresh_engine()
        engine.create_arc(_sample_arc("prog1"))
        arc = engine.advance_arc("prog1", "s1")
        assert arc.progress == pytest.approx(0.25)

    def test_reset_clears_everything(self):
        engine = _fresh_engine()
        engine.create_arc(_sample_arc("r1"))
        engine.register_hook("arc_advanced", lambda a: None)
        engine.reset()
        assert engine.get_arc("r1") is None
        assert engine.get_scene_arcs("penthouse") == []

    def test_get_scene_state_no_arcs(self):
        engine = _fresh_engine()
        state = engine.get_scene_state("penthouse")
        assert state["total_arcs"] == 0
        assert state["overall_progress"] == 0.0

    def test_get_scene_state_counts(self):
        from engine.story.story_arc import ArcStatus
        engine = _fresh_engine()
        arc = _sample_arc("sc1")
        engine.create_arc(arc)
        engine.advance_arc("sc1", "s1")
        state = engine.get_scene_state("penthouse")
        assert state["total_arcs"] == 1
        assert state["active"] == 1
        assert state["completed"] == 0
        assert state["failed"] == 0

    def test_get_scene_state_completed(self):
        engine = _fresh_engine()
        arc = _sample_arc("sc_done")
        engine.create_arc(arc)
        for sid in ("s1", "s2", "s3", "s4"):
            engine.advance_arc("sc_done", sid)
        state = engine.get_scene_state("penthouse")
        assert state["completed"] == 1
        assert state["overall_progress"] == pytest.approx(1.0)

    def test_get_scene_state_failed(self):
        engine = _fresh_engine()
        arc = _sample_arc("sc_fail")
        engine.create_arc(arc)
        engine.advance_arc("sc_fail", "s1", success=False)
        state = engine.get_scene_state("penthouse")
        assert state["failed"] == 1

    def test_get_scene_state_arc_list_shape(self):
        engine = _fresh_engine()
        engine.create_arc(_sample_arc("shape1"))
        state = engine.get_scene_state("penthouse")
        entry = state["arcs"][0]
        assert "id" in entry
        assert "name" in entry
        assert "status" in entry
        assert "progress" in entry
        assert "outcome" in entry


# ──── Hooks ──────────────────────────────────────────────────────────────────


class TestHooks:
    def test_arc_advanced_hook_fires(self):
        engine = _fresh_engine()
        engine.create_arc(_sample_arc("h1"))
        calls = []
        engine.register_hook("arc_advanced", lambda arc: calls.append(arc.id))
        engine.advance_arc("h1", "s1")
        assert "h1" in calls

    def test_arc_completed_hook_fires(self):
        engine = _fresh_engine()
        engine.create_arc(_sample_arc("h2"))
        calls = []
        engine.register_hook("arc_completed", lambda arc: calls.append(arc.id))
        for sid in ("s1", "s2", "s3", "s4"):
            engine.advance_arc("h2", sid)
        assert "h2" in calls

    def test_arc_failed_hook_fires(self):
        engine = _fresh_engine()
        engine.create_arc(_sample_arc("h3"))
        calls = []
        engine.register_hook("arc_failed", lambda arc: calls.append(arc.id))
        engine.advance_arc("h3", "s1", success=False)
        assert "h3" in calls

    def test_failing_hook_does_not_raise(self):
        engine = _fresh_engine()
        engine.create_arc(_sample_arc("h4"))

        def bad_hook(arc):
            raise RuntimeError("boom")

        engine.register_hook("arc_advanced", bad_hook)
        # Should not raise
        engine.advance_arc("h4", "s1")

    def test_multiple_hooks_all_fire(self):
        engine = _fresh_engine()
        engine.create_arc(_sample_arc("h5"))
        fired = []
        engine.register_hook("arc_advanced", lambda a: fired.append(1))
        engine.register_hook("arc_advanced", lambda a: fired.append(2))
        engine.advance_arc("h5", "s1")
        assert fired == [1, 2]


# ──── Singleton ──────────────────────────────────────────────────────────────


class TestSingleton:
    def test_get_instance_returns_same(self):
        from engine.story.story_arc import StoryArcEngine
        a = StoryArcEngine.get_instance()
        b = StoryArcEngine.get_instance()
        assert a is b

    def test_get_story_arc_engine(self):
        from engine.story.story_arc import StoryArcEngine, get_story_arc_engine
        engine = get_story_arc_engine()
        assert isinstance(engine, StoryArcEngine)


# ──── Arc Templates ──────────────────────────────────────────────────────────


class TestArcTemplates:
    EXPECTED_SCENES = {
        "penthouse", "casino", "arena", "tavern",
        "lounge", "gallery", "realm", "neoncity", "phone",
    }

    def test_all_9_scenes_present(self):
        from engine.story.arc_templates import SCENE_ARC_TEMPLATES
        assert set(SCENE_ARC_TEMPLATES.keys()) == self.EXPECTED_SCENES

    def test_each_scene_has_at_least_one_arc(self):
        from engine.story.arc_templates import SCENE_ARC_TEMPLATES
        for scene, arcs in SCENE_ARC_TEMPLATES.items():
            assert len(arcs) >= 1, f"{scene} has no arcs"

    def test_each_arc_has_four_steps(self):
        from engine.story.arc_templates import SCENE_ARC_TEMPLATES
        for scene, arcs in SCENE_ARC_TEMPLATES.items():
            for arc in arcs:
                assert len(arc.steps) == 4, f"{arc.id} has wrong step count"

    def test_seed_default_arcs_registers_all(self):
        from engine.story.story_arc import StoryArcEngine
        engine = StoryArcEngine()
        # Patch get_story_arc_engine to return our isolated engine
        with patch("engine.story.arc_templates.get_story_arc_engine", return_value=engine):
            from engine.story.arc_templates import seed_default_arcs
            seed_default_arcs()
        for scene in self.EXPECTED_SCENES:
            assert len(engine.get_scene_arcs(scene)) >= 1

    def test_seed_uses_deep_copy(self):
        """Templates must be deep-copied so seeding twice is safe."""
        from engine.story.story_arc import StoryArcEngine
        engine1 = StoryArcEngine()
        engine2 = StoryArcEngine()
        with patch("engine.story.arc_templates.get_story_arc_engine", return_value=engine1):
            from engine.story.arc_templates import seed_default_arcs
            seed_default_arcs()
        with patch("engine.story.arc_templates.get_story_arc_engine", return_value=engine2):
            seed_default_arcs()
        # Advance an arc in engine1, engine2's copy should be unaffected
        arc1 = engine1.get_scene_arcs("penthouse")[0]
        arc2 = engine2.get_scene_arcs("penthouse")[0]
        arc1.advance("open")
        assert arc2.steps[0].completed is False


# ──── Skills ─────────────────────────────────────────────────────────────────


class TestStorySkills:
    def _engine_with_arc(self, arc_id="sk_arc", scene="penthouse"):
        engine = _fresh_engine()
        arc = _sample_arc(arc_id, scene=scene)
        engine.create_arc(arc)
        return engine

    def test_get_scene_story_state_no_arcs(self):
        engine = _fresh_engine()
        with patch("engine.skills.builtin.story_skills.get_story_arc_engine", return_value=engine):
            from engine.skills.builtin.story_skills import get_scene_story_state
            result = get_scene_story_state("penthouse")
        assert "No active story arcs" in result

    def test_get_scene_story_state_with_arc(self):
        engine = self._engine_with_arc("sk1")
        with patch("engine.skills.builtin.story_skills.get_story_arc_engine", return_value=engine):
            from engine.skills.builtin.story_skills import get_scene_story_state
            result = get_scene_story_state("penthouse")
        assert "penthouse" in result
        assert "Test Arc" in result

    def test_advance_story_step_not_found(self):
        engine = _fresh_engine()
        with patch("engine.skills.builtin.story_skills.get_story_arc_engine", return_value=engine):
            from engine.skills.builtin.story_skills import advance_story_step
            result = advance_story_step("ghost_arc", "s1")
        assert "not found" in result

    def test_advance_story_step_success(self):
        engine = self._engine_with_arc("sk2")
        with patch("engine.skills.builtin.story_skills.get_story_arc_engine", return_value=engine):
            from engine.skills.builtin.story_skills import advance_story_step
            result = advance_story_step("sk2", "s1")
        assert "succeeded" in result
        assert "25%" in result

    def test_advance_story_step_failure(self):
        engine = self._engine_with_arc("sk3")
        with patch("engine.skills.builtin.story_skills.get_story_arc_engine", return_value=engine):
            from engine.skills.builtin.story_skills import advance_story_step
            result = advance_story_step("sk3", "s1", success=False)
        assert "failed" in result

    def test_advance_story_step_win_emoji(self):
        engine = self._engine_with_arc("sk4")
        with patch("engine.skills.builtin.story_skills.get_story_arc_engine", return_value=engine):
            from engine.skills.builtin.story_skills import advance_story_step
            for sid in ("s1", "s2", "s3"):
                advance_story_step("sk4", sid)
            result = advance_story_step("sk4", "s4")
        assert "🏆" in result

    def test_check_arc_outcome_not_found(self):
        engine = _fresh_engine()
        with patch("engine.skills.builtin.story_skills.get_story_arc_engine", return_value=engine):
            from engine.skills.builtin.story_skills import check_arc_outcome
            result = check_arc_outcome("missing")
        assert "not found" in result

    def test_check_arc_outcome_win(self):
        engine = self._engine_with_arc("sk5")
        for sid in ("s1", "s2", "s3", "s4"):
            engine.advance_arc("sk5", sid)
        with patch("engine.skills.builtin.story_skills.get_story_arc_engine", return_value=engine):
            from engine.skills.builtin.story_skills import check_arc_outcome
            result = check_arc_outcome("sk5")
        assert "Victory" in result
        assert "🏆" in result

    def test_check_arc_outcome_lose(self):
        engine = self._engine_with_arc("sk6")
        engine.advance_arc("sk6", "s1", success=False)
        with patch("engine.skills.builtin.story_skills.get_story_arc_engine", return_value=engine):
            from engine.skills.builtin.story_skills import check_arc_outcome
            result = check_arc_outcome("sk6")
        assert "Defeat" in result
        assert "💀" in result

    def test_check_arc_outcome_in_progress(self):
        engine = self._engine_with_arc("sk7")
        engine.advance_arc("sk7", "s1")
        with patch("engine.skills.builtin.story_skills.get_story_arc_engine", return_value=engine):
            from engine.skills.builtin.story_skills import check_arc_outcome
            result = check_arc_outcome("sk7")
        assert "25%" in result

    def test_list_scene_arcs_empty(self):
        engine = _fresh_engine()
        with patch("engine.skills.builtin.story_skills.get_story_arc_engine", return_value=engine):
            from engine.skills.builtin.story_skills import list_scene_arcs
            result = list_scene_arcs("penthouse")
        assert "No arcs" in result

    def test_list_scene_arcs_lists_arcs(self):
        engine = self._engine_with_arc("sk8")
        with patch("engine.skills.builtin.story_skills.get_story_arc_engine", return_value=engine):
            from engine.skills.builtin.story_skills import list_scene_arcs
            result = list_scene_arcs("penthouse")
        assert "sk8" in result
        assert "Test Arc" in result


# ──── Blueprint ──────────────────────────────────────────────────────────────


class TestStoryBlueprint:
    @pytest.fixture()
    def client(self):
        from flask import Flask
        from engine.story.story_blueprint import story_bp
        app = Flask(__name__)
        app.register_blueprint(story_bp)
        app.config["TESTING"] = True
        return app.test_client()

    def _engine_with_arc(self, arc_id="bp_arc", scene="casino"):
        engine = _fresh_engine()
        arc = _sample_arc(arc_id, scene=scene)
        engine.create_arc(arc)
        return engine

    def test_story_state_returns_200(self, client):
        engine = _fresh_engine()
        with patch("engine.story.story_blueprint.get_story_arc_engine", return_value=engine):
            resp = client.get("/api/story/state/casino")
        assert resp.status_code == 200

    def test_story_state_json_shape(self, client):
        engine = _fresh_engine()
        with patch("engine.story.story_blueprint.get_story_arc_engine", return_value=engine):
            resp = client.get("/api/story/state/casino")
        data = resp.get_json()
        assert data["scene"] == "casino"
        assert "total_arcs" in data
        assert "overall_progress" in data

    def test_arc_detail_not_found(self, client):
        engine = _fresh_engine()
        with patch("engine.story.story_blueprint.get_story_arc_engine", return_value=engine):
            resp = client.get("/api/story/arc/ghost_arc")
        assert resp.status_code == 404

    def test_arc_detail_found(self, client):
        engine = self._engine_with_arc("bp1")
        with patch("engine.story.story_blueprint.get_story_arc_engine", return_value=engine):
            resp = client.get("/api/story/arc/bp1")
        assert resp.status_code == 200
        data = resp.get_json()
        assert data["id"] == "bp1"
        assert "steps" in data
        assert len(data["steps"]) == 4

    def test_arc_detail_steps_shape(self, client):
        engine = self._engine_with_arc("bp2")
        with patch("engine.story.story_blueprint.get_story_arc_engine", return_value=engine):
            resp = client.get("/api/story/arc/bp2")
        step = resp.get_json()["steps"][0]
        assert "id" in step
        assert "description" in step
        assert "completed" in step
        assert "failed" in step

    def test_story_state_with_arc_reflects_progress(self, client):
        engine = self._engine_with_arc("bp3", scene="casino")
        engine.advance_arc("bp3", "s1")
        engine.advance_arc("bp3", "s2")
        with patch("engine.story.story_blueprint.get_story_arc_engine", return_value=engine):
            resp = client.get("/api/story/state/casino")
        data = resp.get_json()
        assert data["overall_progress"] == pytest.approx(0.5)
