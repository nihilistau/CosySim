"""Tests for ActivityBus — real-time activity tracker."""

import time
import threading
import pytest

from engine.services.activity_bus import ActivityBus, Activity, HistoryEntry


# ── Fixtures ───────────────────────────────────────────────────────────


@pytest.fixture
def bus():
    """Fresh ActivityBus per test — no shared mutable state."""
    return ActivityBus()


# ── Activity dataclass ─────────────────────────────────────────────────


class TestActivityDataclass:
    """Tests for the Activity dataclass itself."""

    def test_create_with_required_fields(self):
        """Minimal Activity only needs kind and label."""
        act = Activity(kind="thinking", label="Pondering life")
        assert act.kind == "thinking"
        assert act.label == "Pondering life"
        assert act.agent_id == ""
        assert act.scene == ""
        assert act.model == ""
        assert isinstance(act.token, str) and len(act.token) == 8
        assert act.extra == {}

    def test_create_with_all_fields(self):
        """Activity accepts every optional field."""
        act = Activity(
            kind="tool_call",
            label="Calling search_web",
            agent_id="char-aria",
            scene="phone",
            model="qwen3-8b",
            extra={"url": "https://example.com"},
        )
        assert act.agent_id == "char-aria"
        assert act.scene == "phone"
        assert act.model == "qwen3-8b"
        assert act.extra["url"] == "https://example.com"

    def test_elapsed_ms_increases(self):
        """elapsed_ms should grow as real time passes."""
        act = Activity(kind="thinking", label="slow")
        time.sleep(0.05)
        elapsed = act.elapsed_ms()
        assert elapsed >= 40  # allow small scheduling slack

    def test_to_dict_keys(self):
        """to_dict returns the expected key set."""
        act = Activity(kind="tts", label="Generating speech", agent_id="a1")
        d = act.to_dict()
        expected_keys = {"kind", "label", "agent_id", "scene", "model",
                         "elapsed_ms", "token"}
        assert set(d.keys()) == expected_keys

    def test_to_dict_elapsed_is_rounded(self):
        """elapsed_ms in to_dict is rounded to 0 decimal places."""
        act = Activity(kind="x", label="y")
        d = act.to_dict()
        assert d["elapsed_ms"] == round(d["elapsed_ms"], 0)

    def test_unique_tokens(self):
        """Each Activity auto-generates a unique token."""
        tokens = {Activity(kind="a", label="b").token for _ in range(50)}
        assert len(tokens) == 50


# ── HistoryEntry dataclass ─────────────────────────────────────────────


class TestHistoryEntryDataclass:
    """Tests for the HistoryEntry dataclass."""

    def test_create(self):
        """HistoryEntry captures kind, label, agent_id, duration_ms."""
        entry = HistoryEntry(
            kind="thinking",
            label="Deep thoughts",
            agent_id="char-lola",
            duration_ms=123.456,
        )
        assert entry.kind == "thinking"
        assert entry.duration_ms == 123.456
        assert isinstance(entry.timestamp, float)

    def test_to_dict_keys(self):
        """to_dict contains exactly the expected keys."""
        entry = HistoryEntry(kind="k", label="l", agent_id="a", duration_ms=10)
        d = entry.to_dict()
        assert set(d.keys()) == {"kind", "label", "agent_id", "duration_ms",
                                  "timestamp"}

    def test_to_dict_rounds_values(self):
        """duration_ms is rounded to 0 decimals; timestamp to 2."""
        ts = 1700000000.12345
        entry = HistoryEntry(kind="k", label="l", agent_id="a",
                             duration_ms=99.999, timestamp=ts)
        d = entry.to_dict()
        assert d["duration_ms"] == 100.0
        assert d["timestamp"] == 1700000000.12


# ── Push / Pop lifecycle ──────────────────────────────────────────────


class TestPushPop:
    """Tests for the push/pop write API."""

    def test_push_returns_token(self, bus):
        """push() returns the activity's token string."""
        act = Activity(kind="thinking", label="hmm")
        token = bus.push(act)
        assert token == act.token
        assert isinstance(token, str)

    def test_push_makes_activity_visible(self, bus):
        """Pushed activity appears in current_activities."""
        bus.push(Activity(kind="tool_call", label="test"))
        assert len(bus.current_activities) == 1
        assert bus.current_activities[0]["kind"] == "tool_call"

    def test_pop_removes_activity(self, bus):
        """pop() removes the activity from current list."""
        token = bus.push(Activity(kind="x", label="y"))
        popped = bus.pop(token)
        assert popped is not None
        assert popped.kind == "x"
        assert len(bus.current_activities) == 0

    def test_pop_adds_to_history(self, bus):
        """Popped activity ends up in recent_history."""
        token = bus.push(Activity(kind="image_gen", label="generating",
                                  agent_id="char-aria"))
        bus.pop(token)
        history = bus.recent_history
        assert len(history) == 1
        assert history[0]["kind"] == "image_gen"
        assert history[0]["agent_id"] == "char-aria"
        assert "duration_ms" in history[0]

    def test_pop_invalid_token_returns_none(self, bus):
        """Popping a token that doesn't exist returns None."""
        result = bus.pop("nonexistent-token")
        assert result is None

    def test_pop_invalid_token_no_history(self, bus):
        """Invalid pop should NOT add anything to history."""
        bus.pop("bogus")
        assert bus.recent_history == []

    def test_pop_same_token_twice(self, bus):
        """Second pop of the same token returns None — idempotent."""
        token = bus.push(Activity(kind="x", label="y"))
        first = bus.pop(token)
        second = bus.pop(token)
        assert first is not None
        assert second is None


# ── Context manager ───────────────────────────────────────────────────


class TestActivityContextManager:
    """Tests for the bus.activity() context manager."""

    def test_activity_visible_inside_block(self, bus):
        """Activity should be active during the with-block."""
        with bus.activity(kind="thinking", label="inside") as act:
            assert not bus.is_idle
            assert any(a["token"] == act.token for a in bus.current_activities)

    def test_activity_removed_after_block(self, bus):
        """Activity is popped once the with-block exits."""
        with bus.activity(kind="tool_call", label="done"):
            pass
        assert bus.is_idle
        assert len(bus.recent_history) == 1

    def test_activity_removed_on_exception(self, bus):
        """Activity is popped even when an exception fires."""
        with pytest.raises(ValueError):
            with bus.activity(kind="tts", label="kaboom"):
                raise ValueError("test error")
        assert bus.is_idle
        assert len(bus.recent_history) == 1
        assert bus.recent_history[0]["kind"] == "tts"

    def test_context_manager_yields_activity(self, bus):
        """The yielded object is a proper Activity instance."""
        with bus.activity(kind="memory", label="storing",
                          agent_id="char-lola", scene="bedroom",
                          model="qwen3-8b") as act:
            assert isinstance(act, Activity)
            assert act.kind == "memory"
            assert act.agent_id == "char-lola"
            assert act.scene == "bedroom"
            assert act.model == "qwen3-8b"

    def test_context_manager_passes_extra(self, bus):
        """Extra dict propagates through the context manager."""
        extras = {"key": "value", "count": 42}
        with bus.activity(kind="x", label="y", extra=extras) as act:
            assert act.extra == extras


# ── Snapshot ──────────────────────────────────────────────────────────


class TestSnapshot:
    """Tests for the snapshot() read API."""

    def test_snapshot_idle_structure(self, bus):
        """Idle bus snapshot has correct keys and default values."""
        snap = bus.snapshot()
        assert snap["active"] == []
        assert snap["history"] == []
        assert snap["count"] == 0
        assert snap["idle"] is True

    def test_snapshot_with_active_activity(self, bus):
        """Snapshot reflects a pushed activity."""
        bus.push(Activity(kind="thinking", label="busy", agent_id="a1"))
        snap = bus.snapshot()
        assert snap["count"] == 1
        assert snap["idle"] is False
        assert snap["active"][0]["kind"] == "thinking"

    def test_snapshot_includes_history(self, bus):
        """Snapshot history contains recently completed activities."""
        token = bus.push(Activity(kind="done", label="finished"))
        bus.pop(token)
        snap = bus.snapshot()
        assert snap["count"] == 0
        assert snap["idle"] is True
        assert len(snap["history"]) == 1
        assert snap["history"][0]["kind"] == "done"

    def test_snapshot_history_capped_at_10(self, bus):
        """Snapshot only returns the last 10 history entries."""
        for i in range(20):
            token = bus.push(Activity(kind="x", label=f"item-{i}"))
            bus.pop(token)
        snap = bus.snapshot()
        assert len(snap["history"]) == 10


# ── Clear ─────────────────────────────────────────────────────────────


class TestClear:
    """Tests for the emergency clear() method."""

    def test_clear_removes_active(self, bus):
        """clear() removes all in-flight activities."""
        bus.push(Activity(kind="a", label="1"))
        bus.push(Activity(kind="b", label="2"))
        assert not bus.is_idle
        bus.clear()
        assert bus.is_idle
        assert bus.current_activities == []

    def test_clear_preserves_history(self, bus):
        """clear() does NOT wipe history — only active."""
        token = bus.push(Activity(kind="x", label="y"))
        bus.pop(token)
        bus.push(Activity(kind="still_active", label="z"))
        bus.clear()
        assert bus.is_idle
        assert len(bus.recent_history) == 1  # history survives


# ── Concurrent activities ─────────────────────────────────────────────


class TestConcurrentActivities:
    """Tests for multiple simultaneous activities."""

    def test_multiple_push(self, bus):
        """Multiple activities can be live at the same time."""
        t1 = bus.push(Activity(kind="thinking", label="a", agent_id="a1"))
        t2 = bus.push(Activity(kind="tts", label="b", agent_id="a2"))
        t3 = bus.push(Activity(kind="tool_call", label="c", agent_id="a3"))
        assert len(bus.current_activities) == 3
        assert not bus.is_idle

        # Pop one — others remain
        bus.pop(t2)
        assert len(bus.current_activities) == 2
        kinds = {a["kind"] for a in bus.current_activities}
        assert kinds == {"thinking", "tool_call"}

    def test_thread_safety(self, bus):
        """Push/pop from multiple threads should not corrupt state."""
        errors = []

        def worker(worker_id: int):
            try:
                for i in range(20):
                    token = bus.push(Activity(
                        kind="work",
                        label=f"w{worker_id}-{i}",
                    ))
                    time.sleep(0.001)
                    bus.pop(token)
            except Exception as exc:
                errors.append(exc)

        threads = [threading.Thread(target=worker, args=(i,))
                   for i in range(6)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert errors == [], f"Thread errors: {errors}"
        assert bus.is_idle
        # 6 threads × 20 iterations = 120 history entries (trimmed by ring buffer)
        assert len(bus.recent_history) > 0


# ── Properties / edge cases ──────────────────────────────────────────


class TestProperties:
    """Tests for is_idle, current_activities, recent_history."""

    def test_is_idle_initially(self, bus):
        """Freshly created bus is idle."""
        assert bus.is_idle is True

    def test_is_idle_false_with_activity(self, bus):
        """Bus is not idle when activities are pushed."""
        bus.push(Activity(kind="x", label="y"))
        assert bus.is_idle is False

    def test_recent_history_capped_at_20(self, bus):
        """recent_history returns at most 20 entries."""
        for i in range(30):
            token = bus.push(Activity(kind="x", label=f"h-{i}"))
            bus.pop(token)
        assert len(bus.recent_history) == 20

    def test_history_ring_buffer_trims(self, bus):
        """Internal history list is trimmed when it exceeds _HISTORY_MAX (50)."""
        for i in range(60):
            token = bus.push(Activity(kind="x", label=f"trim-{i}"))
            bus.pop(token)
        # After 51st push/pop the buffer trims to last 25 entries,
        # then grows back; the internal list should stay bounded.
        assert len(bus._history) <= 50
