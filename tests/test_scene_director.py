"""Tests for engine.director.scene_director.

Covers: beat selection logic, cooldown guard, nudge, history, serialisation,
EventBus publishing, and the singleton accessor.

All Nexus and EventBus calls are fully mocked so the tests are offline and
hermetic.
"""

from __future__ import annotations

import time
import uuid
from unittest.mock import MagicMock, call, patch

import pytest

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_SCENE = "penthouse"


def _make_state(
    *,
    turn_count: int = 5,
    arousal: float = 30.0,
    idle_seconds: float = 0.0,
    credits: float = 500.0,
    last_beat_type: str | None = None,
) -> dict:
    return {
        "turn_count": turn_count,
        "emotion_levels": {"arousal": arousal},
        "idle_seconds": idle_seconds,
        "economy_balance": credits,
        "last_beat_type": last_beat_type,
    }


def _fresh_director(mock_nexus, mock_bus):
    """Return a SceneDirector with injected mock nexus."""
    from engine.director.scene_director import SceneDirector

    director = SceneDirector(nexus_client=mock_nexus)
    return director


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture(autouse=True)
def _patch_bus():
    """Patch the EventBus so no real network calls happen."""
    mock_bus = MagicMock()
    mock_bus.publish = MagicMock()
    with patch("engine.director.scene_director._bus", return_value=mock_bus):
        with patch("engine.director.scene_director._event_types") as mock_et:
            mock_et.return_value.DIRECTOR_BEAT_FIRED = "director.beat_fired"
            yield mock_bus


@pytest.fixture()
def mock_nexus():
    nx = MagicMock()
    nx.search.return_value = []  # default: no Nexus content
    nx.add_entry.return_value = str(uuid.uuid4())
    return nx


@pytest.fixture()
def director(mock_nexus):
    from engine.director.scene_director import SceneDirector

    return SceneDirector(nexus_client=mock_nexus)


# ---------------------------------------------------------------------------
# Cooldown
# ---------------------------------------------------------------------------

class TestCooldown:
    def test_tick_returns_none_within_cooldown(self, director):
        """Second tick within 60 s must return None."""
        state = _make_state(idle_seconds=200.0)
        first = director.tick(_SCENE, state)
        assert first is not None, "First tick should fire a beat"

        second = director.tick(_SCENE, state)
        assert second is None, "Second tick within cooldown should return None"

    def test_tick_fires_after_cooldown_expires(self, director):
        """A tick after the cooldown window fires a new beat."""
        state = _make_state(idle_seconds=200.0)
        director.tick(_SCENE, state)

        # Manually backdate last beat time by 70 s
        director._last_beat_time[_SCENE] -= 70.0

        second = director.tick(_SCENE, state)
        assert second is not None


# ---------------------------------------------------------------------------
# Beat selection logic
# ---------------------------------------------------------------------------

class TestBeatSelection:
    def test_tick_fires_story_beat_when_idle(self, director):
        """idle_seconds > 120 should fire a STORY_BEAT or COMPLICATION."""
        from engine.director.scene_director import BeatType

        state = _make_state(idle_seconds=180.0)
        beat = director.tick(_SCENE, state)

        assert beat is not None
        assert beat.beat_type in (BeatType.STORY_BEAT, BeatType.COMPLICATION)

    def test_tick_alternates_complication_after_story_beat(self, director):
        """After a STORY_BEAT, the next idle beat should be COMPLICATION."""
        from engine.director.scene_director import BeatType

        state = _make_state(idle_seconds=180.0)
        first = director.tick(_SCENE, state)
        assert first.beat_type == BeatType.STORY_BEAT

        # Expire cooldown
        director._last_beat_time[_SCENE] -= 70.0

        second = director.tick(_SCENE, state)
        assert second.beat_type == BeatType.COMPLICATION

    def test_tick_fires_escalation_on_high_arousal(self, director):
        """arousal > 80 should fire ESCALATION."""
        from engine.director.scene_director import BeatType

        beat = director.tick(_SCENE, _make_state(arousal=85.0))
        assert beat is not None
        assert beat.beat_type == BeatType.ESCALATION

    def test_tick_fires_cool_down_after_escalation(self, director):
        """arousal < 20 after escalation should fire COOL_DOWN."""
        from engine.director.scene_director import BeatType

        state = _make_state(arousal=10.0, last_beat_type="escalation")
        beat = director.tick(_SCENE, state)
        assert beat is not None
        assert beat.beat_type == BeatType.COOL_DOWN

    def test_tick_fires_revelation_on_milestone(self, director):
        """turn_count in milestone set should fire REVELATION."""
        from engine.director.scene_director import BeatType

        for milestone in (10, 25, 50):
            d2 = type(director)(nexus_client=director._nexus_client)
            beat = d2.tick(_SCENE, _make_state(turn_count=milestone))
            assert beat is not None, f"Expected beat for milestone {milestone}"
            assert beat.beat_type == BeatType.REVELATION, (
                f"Expected REVELATION at turn {milestone}, got {beat.beat_type}"
            )

    def test_tick_fires_reward_on_low_credits(self, director):
        """economy_balance < 100 should fire REWARD."""
        from engine.director.scene_director import BeatType

        beat = director.tick(_SCENE, _make_state(credits=50.0))
        assert beat is not None
        assert beat.beat_type == BeatType.REWARD

    def test_tick_returns_none_when_no_trigger(self, director):
        """Stable mid-range state with no milestone should produce no beat."""
        # Normal conditions — nothing should fire
        state = _make_state(
            turn_count=7,
            arousal=40.0,
            idle_seconds=30.0,
            credits=500.0,
        )
        beat = director.tick(_SCENE, state)
        assert beat is None


# ---------------------------------------------------------------------------
# Nudge
# ---------------------------------------------------------------------------

class TestNudge:
    def test_nudge_creates_beat(self, director):
        """nudge() must return a DirectorBeat without cooldown gate."""
        from engine.director.scene_director import DirectorBeat

        beat = director.nudge(_SCENE, "escalate")
        assert isinstance(beat, DirectorBeat)
        assert not beat.fired

    def test_nudge_directions(self, director):
        """All documented nudge directions should map to a valid BeatType."""
        from engine.director.scene_director import BeatType, _NUDGE_MAP

        for direction, expected_type in _NUDGE_MAP.items():
            # New director per direction to avoid cooldown interference
            d = type(director)(nexus_client=director._nexus_client)
            beat = d.nudge(_SCENE, direction)
            assert beat.beat_type == expected_type, (
                f"Direction {direction!r}: expected {expected_type}, got {beat.beat_type}"
            )

    def test_nudge_unknown_direction_raises(self, director):
        """nudge() with an unknown direction should raise ValueError."""
        with pytest.raises(ValueError, match="Unknown nudge direction"):
            director.nudge(_SCENE, "explode")

    def test_nudge_intensity_clamped(self, director):
        """intensity is clamped to 0–3 range."""
        beat = director.nudge(_SCENE, "reward", intensity=10)
        assert beat.content_intensity == 3

        d2 = type(director)(nexus_client=director._nexus_client)
        beat2 = d2.nudge(_SCENE, "reward", intensity=-5)
        assert beat2.content_intensity == 0


# ---------------------------------------------------------------------------
# History / pending / mark_fired
# ---------------------------------------------------------------------------

class TestHistory:
    def test_mark_fired(self, director):
        """mark_fired should flip the fired flag on the target beat."""
        beat = director.nudge(_SCENE, "story")
        assert not beat.fired

        director.mark_fired(beat.id)
        assert beat.fired

    def test_mark_fired_unknown_id_no_crash(self, director):
        """mark_fired with an unknown id should log a warning, not raise."""
        director.mark_fired("nonexistent-id-xyz")  # should not raise

    def test_get_pending_beats_excludes_fired(self, director):
        """Fired beats must not appear in get_pending_beats()."""
        b1 = director.nudge(_SCENE, "story")
        b2 = director.nudge(_SCENE, "reward")

        director.mark_fired(b1.id)

        pending = director.get_pending_beats(_SCENE)
        ids = [b.id for b in pending]
        assert b1.id not in ids
        assert b2.id in ids

    def test_get_history(self, director):
        """get_history should return beats newest-first, up to limit."""
        beats = [director.nudge(_SCENE, "story") for _ in range(5)]

        history = director.get_history(_SCENE, limit=3)
        assert len(history) == 3
        # Newest first — last nudge should be history[0]
        assert history[0].id == beats[-1].id

    def test_get_history_empty_scene(self, director):
        """get_history for an unseen scene should return empty list."""
        assert director.get_history("ghost_scene") == []

    def test_reset_scene(self, director):
        """reset_scene should clear all history and cooldown for the scene."""
        director.nudge(_SCENE, "story")
        director.nudge(_SCENE, "reward")
        assert len(director.get_history(_SCENE)) == 2

        director.reset_scene(_SCENE)

        assert director.get_history(_SCENE) == []
        assert _SCENE not in director._last_beat_time


# ---------------------------------------------------------------------------
# Beat serialisation
# ---------------------------------------------------------------------------

class TestBeatSerialisation:
    def test_beat_serialization(self, director):
        """to_dict() must return a JSON-serialisable dict with string beat_type."""
        beat = director.nudge(_SCENE, "escalate")
        d = beat.to_dict()

        assert isinstance(d, dict)
        assert d["beat_type"] == "escalation"
        assert isinstance(d["beat_type"], str)
        assert "id" in d
        assert "instruction" in d
        assert "timestamp" in d
        assert "fired" in d

    def test_beat_context_preserved(self, director):
        """Nudge context should be stored on the beat."""
        beat = director.nudge(_SCENE, "complicate", intensity=2)
        assert beat.context.get("nudge_direction") == "complicate"
        assert beat.context.get("nudge_intensity") == 2


# ---------------------------------------------------------------------------
# Singleton
# ---------------------------------------------------------------------------

class TestSingleton:
    def test_singleton(self):
        """get_scene_director() must return the same instance across calls."""
        import engine.director.scene_director as mod

        # Reset singleton for test isolation
        original = mod._director_instance
        mod._director_instance = None
        try:
            from engine.director.scene_director import get_scene_director

            a = get_scene_director()
            b = get_scene_director()
            assert a is b
        finally:
            mod._director_instance = original


# ---------------------------------------------------------------------------
# EventBus integration
# ---------------------------------------------------------------------------

class TestEventBus:
    def test_fires_event_bus(self, director, _patch_bus):
        """Each beat fired by nudge() should call bus.publish once."""
        director.nudge(_SCENE, "story")
        _patch_bus.publish.assert_called_once()
        call_kwargs = _patch_bus.publish.call_args
        assert call_kwargs.kwargs.get("scene") == _SCENE or _SCENE in call_kwargs.args

    def test_tick_fires_event_bus(self, director, _patch_bus):
        """tick() that produces a beat must call bus.publish."""
        director.tick(_SCENE, _make_state(idle_seconds=200.0))
        _patch_bus.publish.assert_called_once()

    def test_event_payload_contains_beat(self, director, _patch_bus):
        """The EventBus payload must be the beat's to_dict() representation."""
        beat = director.nudge(_SCENE, "reveal")
        call_kwargs = _patch_bus.publish.call_args

        # payload is the second positional or keyword argument
        payload = call_kwargs.kwargs.get("payload") or call_kwargs.args[1]
        assert payload["id"] == beat.id
        assert payload["beat_type"] == beat.beat_type.value
