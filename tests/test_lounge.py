"""Tests for The Velvet Lounge scene — LoungeScene lifecycle, heat, songs, state."""

from __future__ import annotations

import time
import threading
from unittest.mock import MagicMock, patch, PropertyMock

import pytest

from content.scenes.lounge.lounge_mcp import (
    SCENE_ID, LOLA_ID, VIKTOR_ID,
    COCKTAILS, SONGS, LOLA_SECRETS, VIKTOR_SECRETS,
    get_cocktail, get_all_cocktails, get_song_by_mood,
    get_available_secrets, pick_random_event,
)


# ══════════════════════════════════════════════════════════════════════
#  Helpers — build a LoungeScene with every external dependency mocked
# ══════════════════════════════════════════════════════════════════════

def _mock_framework():
    """Return a MagicMock that satisfies MCPFramework calls."""
    fw = MagicMock()
    fw.start_timer.return_value = "timer_001"
    fw.tick.return_value = []
    fw.random_pick.return_value = {"picks": ["quiet"]}
    fw.get_cross_scene_inbox.return_value = []
    fw.turn = 0
    return fw


def _mock_ssm():
    """Return a MagicMock SceneStateManager."""
    ssm = MagicMock()
    ssm.get_atmosphere.return_value = {}
    ssm.get_narrative_entries.return_value = []
    ssm.get_scene_state.return_value = {}
    return ssm


def _mock_registry():
    """Return a MagicMock CharacterRegistry."""
    reg = MagicMock()
    reg.get_state.return_value = {"mood": "calm", "mood_intensity": 0.5, "energy": 75.0}
    reg.get_profile.return_value = None
    register_result = MagicMock()
    register_result.profile = MagicMock()
    reg.register.return_value = register_result
    return reg


def _mock_rules_engine():
    """Return a MagicMock SceneRulesEngine."""
    eng = MagicMock()
    eng.apply_rule.return_value = {}
    eng.get_rules.return_value = []
    eng.get_rules_summary.return_value = ""
    return eng


def _mock_dialog_system():
    ds = MagicMock()
    return ds


@pytest.fixture
def lounge():
    """Create a LoungeScene with all heavy externals mocked out.

    Every external (Flask, SocketIO, MCP framework, Nexus, etc.) is stubbed
    so the test runs entirely in-process without network calls.
    """
    fw  = _mock_framework()
    ssm = _mock_ssm()
    reg = _mock_registry()
    eng = _mock_rules_engine()
    ds  = _mock_dialog_system()

    # Collect all patches so we can stop them in finally
    active_patches = []

    def _start(target, **kw):
        p = patch(target, **kw)
        active_patches.append(p)
        return p.start()

    # Infrastructure mocks (Flask, SocketIO, CORS, overlay, asset manager)
    _start("content.scenes.lounge.lounge_scene.Flask")
    _start("content.scenes.lounge.lounge_scene.SocketIO")
    _start("content.scenes.lounge.lounge_scene.CORS")
    _start("content.scenes.lounge.lounge_scene.register_shared_assets")
    _start("content.scenes.lounge.lounge_scene.register_lounge_rules")
    _start("content.scenes.lounge.lounge_scene.TagRegistry")
    _start("engine.scenes.base_scene.AssetManager")
    _start("engine.overlay.mount_overlay")
    _start("engine.scenes.base_scene.BaseScene._mcp_register_scene")

    # Nexus — patch nexus_init so it sets the right attrs without real Nexus
    _start("engine.scenes.nexus_mixin.NexusSceneMixin.nexus_init")

    # MCP singletons accessed during __init__
    _start("content.scenes.lounge.lounge_scene.get_scene_state_manager", return_value=ssm)

    # Character registry — _seed_lounge_registry imports these directly
    _start("engine.mcp.character_registry.get_character_registry", return_value=reg)
    _start("engine.mcp.character_registry.apply_default_skills")

    # Property mocks — stay active for the lifetime of the fixture
    _start("content.scenes.lounge.lounge_scene.LoungeScene._fw",
           new_callable=PropertyMock, return_value=fw)
    _start("content.scenes.lounge.lounge_scene.LoungeScene._ssm",
           new_callable=PropertyMock, return_value=ssm)
    _start("content.scenes.lounge.lounge_scene.LoungeScene._reg",
           new_callable=PropertyMock, return_value=reg)
    _start("content.scenes.lounge.lounge_scene.LoungeScene._eng",
           new_callable=PropertyMock, return_value=eng)
    _start("content.scenes.lounge.lounge_scene.LoungeScene._ds",
           new_callable=PropertyMock, return_value=ds)

    try:
        from content.scenes.lounge.lounge_scene import LoungeScene
        scene = LoungeScene(host="127.0.0.1", port=15557)

        # Nexus attrs normally set by nexus_init (mocked above)
        scene._nexus_available = False
        scene._nexus_client = None
        scene._nexus_event_buffer = []
        scene._nexus_buffer_lock = threading.Lock()

        # Attach mocks for assertions
        scene._test_fw  = fw
        scene._test_ssm = ssm
        scene._test_reg = reg
        scene._test_eng = eng
        scene._test_ds  = ds

        # Replace the property-proxied socketio with a simple MagicMock
        scene.socketio = MagicMock()

        yield scene

    finally:
        for p in active_patches:
            p.stop()


# ══════════════════════════════════════════════════════════════════════
#  Scene metadata & initialisation
# ══════════════════════════════════════════════════════════════════════

class TestSceneMetadata:
    def test_scene_name_is_lounge(self, lounge):
        assert lounge.scene_name == SCENE_ID

    def test_scene_metadata_title(self, lounge):
        assert lounge.SCENE_METADATA["title"] == "The Lounge"

    def test_scene_metadata_genre(self, lounge):
        assert lounge.SCENE_METADATA["genre"] == "social"

    def test_scene_metadata_features(self, lounge):
        feats = lounge.SCENE_METADATA["features"]
        assert "music_system" in feats
        assert "conversation_heat" in feats

    def test_max_characters(self, lounge):
        assert lounge.SCENE_METADATA["max_characters"] == 5


class TestSceneInit:
    def test_initial_heat_zero(self, lounge):
        assert lounge.heat_level == 0

    def test_initial_trust(self, lounge):
        assert lounge.guest_trust == 10

    def test_initial_turn_count(self, lounge):
        assert lounge.turn_count == 0

    def test_not_in_back_room(self, lounge):
        assert lounge.in_back_room is False

    def test_secrets_empty(self, lounge):
        assert lounge.secrets_revealed == []

    def test_events_log_empty(self, lounge):
        assert lounge.events_log == []


# ══════════════════════════════════════════════════════════════════════
#  start / stop lifecycle
# ══════════════════════════════════════════════════════════════════════

class TestLifecycle:
    def test_start_runs_socketio(self, lounge):
        """start() should call socketio.run with the Flask app."""
        lounge.start()
        lounge.socketio.run.assert_called_once()
        args = lounge.socketio.run.call_args
        assert args[1]["port"] == 15557

    def test_stop_calls_socketio_stop(self, lounge):
        """stop() should attempt to halt the socketio server."""
        lounge.stop()
        lounge.socketio.stop.assert_called_once()

    @patch("engine.scenes.nexus_mixin.NexusSceneMixin.nexus_flush")
    def test_stop_flushes_nexus(self, mock_flush, lounge):
        lounge.stop()
        mock_flush.assert_called_once()

    def test_stop_saves_framework_state(self, lounge):
        lounge.stop()
        lounge._test_fw.save_state.assert_called_once()


# ══════════════════════════════════════════════════════════════════════
#  Heat management — _tick_heat / _cool_heat
# ══════════════════════════════════════════════════════════════════════

class TestHeatManagement:
    def test_tick_heat_increases(self, lounge):
        lounge._tick_heat(10)
        assert lounge.heat_level == 10

    def test_tick_heat_cumulative(self, lounge):
        lounge._tick_heat(10)
        lounge._tick_heat(10)
        assert lounge.heat_level == 20

    def test_tick_heat_clamped_at_100(self, lounge):
        lounge._tick_heat(120)
        assert lounge.heat_level == 100

    def test_tick_heat_default_delta(self, lounge):
        """Default delta is 5."""
        lounge._tick_heat()
        assert lounge.heat_level == 5

    def test_tick_heat_emits_update(self, lounge):
        lounge._tick_heat(10)
        lounge.socketio.emit.assert_any_call(
            "heat_update", {"heat": 10}, namespace="/"
        )

    def test_tick_heat_syncs_state(self, lounge):
        lounge._tick_heat(10)
        lounge._test_ssm.set_scene_state.assert_called_with(SCENE_ID, heat_level=10)

    def test_tick_heat_warning_threshold(self, lounge):
        """Heat >= 65 should fire heat_warning_rule."""
        lounge._tick_heat(65)
        lounge._test_eng.apply_rule.assert_called_with(
            SCENE_ID, "heat_warning_rule",
            target_ids=[VIKTOR_ID], issuer="lounge_scene",
        )

    def test_tick_heat_critical_threshold(self, lounge):
        """Heat >= 85 should fire heat_critical_rule."""
        lounge._tick_heat(85)
        lounge._test_eng.apply_rule.assert_called_with(
            SCENE_ID, "heat_critical_rule",
            target_ids=[VIKTOR_ID], issuer="lounge_scene",
        )

    def test_tick_heat_cross_scene_message_at_65(self, lounge):
        """When heat >= 65, Viktor should warn Lola via cross_scene_send."""
        lounge._tick_heat(65)
        lounge._test_fw.cross_scene_send.assert_called_once()
        call_kw = lounge._test_fw.cross_scene_send.call_args[1]
        assert call_kw["from_char"] == VIKTOR_ID
        assert call_kw["to_char"] == LOLA_ID
        assert "HEAT 65" in call_kw["message"]

    def test_tick_heat_no_cross_scene_below_65(self, lounge):
        """Below 65 Viktor stays quiet."""
        lounge._tick_heat(30)
        lounge._test_fw.cross_scene_send.assert_not_called()

    def test_cool_heat_reduces(self, lounge):
        lounge.heat_level = 50
        lounge._cool_heat(15)
        assert lounge.heat_level == 35

    def test_cool_heat_clamped_at_zero(self, lounge):
        lounge.heat_level = 5
        lounge._cool_heat(20)
        assert lounge.heat_level == 0

    def test_cool_heat_clears_below_40(self, lounge):
        lounge.heat_level = 50
        lounge._cool_heat(20)  # → 30
        lounge._test_eng.apply_rule.assert_called_with(
            SCENE_ID, "heat_clear_rule",
            target_ids=[VIKTOR_ID], issuer="lounge_scene",
        )

    def test_heat_thread_safe(self, lounge):
        """Multiple threads ticking heat should not corrupt the value."""
        errors = []

        def tick_many():
            try:
                for _ in range(50):
                    lounge._tick_heat(1)
            except Exception as exc:
                errors.append(exc)

        threads = [threading.Thread(target=tick_many) for _ in range(4)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert not errors
        assert 0 <= lounge.heat_level <= 200  # 4*50 = 200 max, clamped to 100
        assert lounge.heat_level == 100  # 200 attempts but clamped


# ══════════════════════════════════════════════════════════════════════
#  Song selection — _start_next_song
# ══════════════════════════════════════════════════════════════════════

class TestSongSelection:
    def test_start_next_song_sets_current(self, lounge):
        """After starting a song, current_song should be populated."""
        assert lounge.current_song is not None
        assert "id" in lounge.current_song
        assert "title" in lounge.current_song

    def test_start_next_song_sets_start_time(self, lounge):
        assert lounge.song_start_time is not None
        assert lounge.song_start_time <= time.time()

    def test_start_next_song_starts_timer(self, lounge):
        """Framework start_timer should be called for the song."""
        lounge._test_fw.start_timer.assert_called()
        timer_calls = lounge._test_fw.start_timer.call_args_list
        # At least one call should be for a song
        song_timer = [c for c in timer_calls if str(c).startswith("call(name='song_")]
        assert len(song_timer) >= 1

    def test_start_next_song_emits_event(self, lounge):
        """Frontend should be notified of the song starting."""
        # Call _start_next_song fresh so the emit goes to our test socketio mock
        song = lounge._start_next_song()
        assert song  # should have returned a song dict
        lounge.socketio.emit.assert_any_call(
            "song_started",
            {
                "song": {
                    "id"      : song["id"],
                    "title"   : song["title"],
                    "duration": song["duration"],
                    "note"    : song.get("note", ""),
                }
            },
            namespace="/",
        )

    def test_start_next_song_sets_directive(self, lounge):
        """A mood directive should be set on Lola for the song."""
        lounge._test_ds.set_directive.assert_called()
        call_kw = lounge._test_ds.set_directive.call_args[1]
        assert call_kw["character_id"] == LOLA_ID
        assert call_kw["directive_type"] == "mood_set"

    def test_requested_song_valid(self, lounge):
        """Requesting a song by ID should switch to that song."""
        song = lounge._start_next_song(requested_id="blue_moon")
        assert song["id"] == "blue_moon"
        assert lounge.current_song["id"] == "blue_moon"

    def test_requested_song_falls_back_on_invalid(self, lounge):
        """An invalid song_id should still return a song (fallback)."""
        song = lounge._start_next_song(requested_id="nonexistent_song_999")
        assert song  # should not be empty
        assert "id" in song

    def test_get_song_by_mood_low(self):
        """Low mood score should return a low-mood_req song."""
        song = get_song_by_mood(0)
        assert song is not None
        assert song["mood_req"] == 0

    def test_get_song_by_mood_high(self):
        """High mood allows the highest-req songs."""
        song = get_song_by_mood(100)
        assert song is not None
        assert song["mood_req"] == max(s["mood_req"] for s in SONGS)


# ══════════════════════════════════════════════════════════════════════
#  get_plugin_info
# ══════════════════════════════════════════════════════════════════════

class TestGetPluginInfo:
    def test_returns_dict(self, lounge):
        info = lounge.get_plugin_info()
        assert isinstance(info, dict)

    def test_required_keys(self, lounge):
        info = lounge.get_plugin_info()
        for key in ("name", "description", "version", "author", "port", "tags", "routes"):
            assert key in info, f"Missing key: {key}"

    def test_port_matches(self, lounge):
        info = lounge.get_plugin_info()
        assert info["port"] == 5557

    def test_name(self, lounge):
        info = lounge.get_plugin_info()
        assert info["name"] == "The Velvet Lounge"

    def test_tags_include_mcp(self, lounge):
        info = lounge.get_plugin_info()
        assert "mcp" in info["tags"]

    def test_routes_structure(self, lounge):
        info = lounge.get_plugin_info()
        for route in info["routes"]:
            assert "path" in route
            assert "methods" in route
            assert "description" in route

    def test_skill_packs(self, lounge):
        info = lounge.get_plugin_info()
        assert "skill_packs" in info
        assert "memory" in info["skill_packs"]


class TestAgentReplyRuntimeEnforcement:
    def test_get_agent_reply_marks_degraded_when_agent_missing(self, lounge):
        """Missing agents should surface explicit degraded runtime metadata."""
        with patch.object(lounge, "_get_or_create_agent", return_value=None):
            result = lounge._get_agent_reply(LOLA_ID, "hello")

        assert result["degraded"] is True
        assert result["error"] == "agent unavailable"
        assert isinstance(result["text"], str) and result["text"]


# ══════════════════════════════════════════════════════════════════════
#  MCP state syncing
# ══════════════════════════════════════════════════════════════════════

class TestStateSyncing:
    def test_get_state_snapshot_keys(self, lounge):
        snap = lounge._get_state_snapshot()
        expected = {
            "trust", "heat", "turn", "in_back_room", "back_room_avail",
            "current_song", "atmosphere", "lola_mood", "viktor_mood",
            "secrets_revealed", "narrative", "active_rules", "fw_turn",
        }
        assert expected == set(snap.keys())

    def test_snapshot_reflects_trust(self, lounge):
        lounge.guest_trust = 42
        snap = lounge._get_state_snapshot()
        assert snap["trust"] == 42

    def test_snapshot_reflects_heat(self, lounge):
        lounge.heat_level = 77
        snap = lounge._get_state_snapshot()
        assert snap["heat"] == 77

    def test_back_room_avail_at_70(self, lounge):
        lounge.guest_trust = 70
        snap = lounge._get_state_snapshot()
        assert snap["back_room_avail"] is True

    def test_back_room_unavail_below_70(self, lounge):
        lounge.guest_trust = 69
        snap = lounge._get_state_snapshot()
        assert snap["back_room_avail"] is False

    def test_sync_guest_state(self, lounge):
        """_sync_guest_state pushes trust/heat through StateCoordinator."""
        with patch("engine.mcp.state_coordinator.get_coordinator") as mock_coord_fn:
            mock_coord = MagicMock()
            mock_coord_fn.return_value = mock_coord
            lounge.guest_trust = 55
            lounge.heat_level = 30
            lounge._sync_guest_state()
            mock_coord.update.assert_called_once()
            kw = mock_coord.update.call_args[1]
            assert kw["trust"] == 55
            assert kw["heat"] == 30

    def test_current_song_info_when_playing(self, lounge):
        lounge.current_song = SONGS[0]
        lounge.song_start_time = time.time() - 10
        info = lounge._current_song_info()
        assert info is not None
        assert info["id"] == SONGS[0]["id"]
        assert info["elapsed"] >= 10
        assert 0 <= info["progress"] <= 1.0

    def test_current_song_info_when_none(self, lounge):
        lounge.current_song = None
        assert lounge._current_song_info() is None


# ══════════════════════════════════════════════════════════════════════
#  Character loading (registry seeding)
# ══════════════════════════════════════════════════════════════════════

class TestCharacterLoading:
    def test_lola_registered(self, lounge):
        """_seed_lounge_registry should register Lola."""
        calls = lounge._test_reg.register.call_args_list
        lola_calls = [c for c in calls if c[0][0] == LOLA_ID]
        assert len(lola_calls) >= 1

    def test_viktor_registered(self, lounge):
        """_seed_lounge_registry should register Viktor."""
        calls = lounge._test_reg.register.call_args_list
        viktor_calls = [c for c in calls if c[0][0] == VIKTOR_ID]
        assert len(viktor_calls) >= 1

    def test_lola_state_set(self, lounge):
        """Initial Lola state should include mood='calm'."""
        set_state_calls = lounge._test_reg.set_state.call_args_list
        lola_state = [c for c in set_state_calls if c[0][0] == LOLA_ID]
        assert len(lola_state) >= 1
        kw = lola_state[0][1]
        assert kw["mood"] == "calm"

    def test_viktor_state_set(self, lounge):
        """Initial Viktor state should include mood='neutral'."""
        set_state_calls = lounge._test_reg.set_state.call_args_list
        vik_state = [c for c in set_state_calls if c[0][0] == VIKTOR_ID]
        assert len(vik_state) >= 1
        kw = vik_state[0][1]
        assert kw["mood"] == "neutral"

    def test_base_scene_has_active_characters_dict(self, lounge):
        """BaseScene should initialise the active_characters mapping."""
        assert isinstance(lounge.active_characters, dict)

    def test_get_or_create_agent_unknown_id(self, lounge):
        """Unknown character_id should return None."""
        assert lounge._get_or_create_agent("nobody") is None


# ══════════════════════════════════════════════════════════════════════
#  Drink system
# ══════════════════════════════════════════════════════════════════════

class TestDrinkSystem:
    def test_serve_known_drink(self, lounge):
        result = lounge._serve_drink("gin_fizz")
        assert result["ok"] is True
        assert result["drink"] == "Gin Fizz"

    def test_serve_unknown_drink(self, lounge):
        result = lounge._serve_drink("unicorn_tears")
        assert result["ok"] is False

    def test_serve_trust_locked_drink(self, lounge):
        """Champagne requires trust >= 35; guest starts at 10."""
        result = lounge._serve_drink("champagne")
        assert result["ok"] is False

    def test_serve_trust_unlocked_drink(self, lounge):
        lounge.guest_trust = 50
        result = lounge._serve_drink("champagne")
        assert result["ok"] is True

    def test_back_room_drink_blocked_outside(self, lounge):
        lounge.guest_trust = 100  # trust is fine
        lounge.in_back_room = False
        result = lounge._serve_drink("the_velvet")
        assert result["ok"] is False

    def test_back_room_drink_allowed_inside(self, lounge):
        lounge.guest_trust = 100
        lounge.in_back_room = True
        result = lounge._serve_drink("the_velvet")
        assert result["ok"] is True


# ══════════════════════════════════════════════════════════════════════
#  Trust gates
# ══════════════════════════════════════════════════════════════════════

class TestTrustGates:
    def test_back_room_unlocks_at_70(self, lounge):
        lounge.guest_trust = 70
        lounge._check_trust_gates()
        lounge._test_eng.apply_rule.assert_any_call(
            SCENE_ID, "back_room_gate",
            target_ids=[VIKTOR_ID], issuer="lounge_scene",
        )

    def test_back_room_emits_event(self, lounge):
        lounge.guest_trust = 70
        lounge._check_trust_gates()
        lounge.socketio.emit.assert_any_call("back_room_unlocked", {}, namespace="/")


# ══════════════════════════════════════════════════════════════════════
#  Event log trimming
# ══════════════════════════════════════════════════════════════════════

class TestEventLog:
    def test_log_event_appends(self, lounge):
        lounge._log_event("Test event", event_type="test")
        assert len(lounge.events_log) == 1
        assert lounge.events_log[0]["text"] == "Test event"

    def test_log_event_trims_at_100(self, lounge):
        for i in range(110):
            lounge._log_event(f"event_{i}", event_type="test")
        assert len(lounge.events_log) <= 100

    def test_log_event_emits_socketio(self, lounge):
        lounge._log_event("noise", event_type="test")
        lounge.socketio.emit.assert_any_call(
            "lounge_event",
            pytest.approx(lounge.events_log[-1], abs=0),
            namespace="/",
        )


# ══════════════════════════════════════════════════════════════════════
#  Lounge MCP helpers (pure functions — no scene fixture needed)
# ══════════════════════════════════════════════════════════════════════

class TestLoungeMCPHelpers:
    def test_get_cocktail_valid(self):
        c = get_cocktail("gin_fizz")
        assert c is not None
        assert c["name"] == "Gin Fizz"

    def test_get_cocktail_invalid(self):
        assert get_cocktail("fake") is None

    def test_get_all_cocktails_trust_0(self):
        available = get_all_cocktails(0)
        ids = {c["id"] for c in available}
        assert "gin_fizz" in ids
        assert "champagne" not in ids  # requires trust 35

    def test_get_all_cocktails_excludes_back_room(self):
        """get_all_cocktails never includes back-room-only drinks."""
        available = get_all_cocktails(100)
        ids = {c["id"] for c in available}
        assert "the_velvet" not in ids

    def test_songs_all_have_required_keys(self):
        for song in SONGS:
            for key in ("id", "title", "mood_req", "duration", "effects"):
                assert key in song, f"Song {song.get('id', '?')} missing {key}"

    def test_pick_random_event_returns_dict(self):
        event = pick_random_event(0)
        assert isinstance(event, dict)
        assert "id" in event
        assert "text" in event

    def test_get_available_secrets_lola(self):
        secs = get_available_secrets(LOLA_ID, 100)
        assert len(secs) == len(LOLA_SECRETS)

    def test_get_available_secrets_viktor(self):
        secs = get_available_secrets(VIKTOR_ID, 100)
        assert len(secs) == len(VIKTOR_SECRETS)

    def test_get_available_secrets_low_trust(self):
        secs = get_available_secrets(LOLA_ID, 0)
        assert len(secs) == 0
