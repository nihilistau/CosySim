"""Tests for Gallery scene — GalleryScene lifecycle, tick, state, dataclasses."""

from __future__ import annotations

import threading
import time
from datetime import datetime
from unittest.mock import MagicMock, patch, PropertyMock

import pytest

from content.scenes.gallery.gallery_scene import (
    ART_STYLES,
    GALLERY_ROOMS,
    PREMADE_EXHIBITIONS,
    SCENE_ID,
    Artwork,
    GalleryCharacter,
    GalleryScene,
    create_app,
)


# ══════════════════════════════════════════════════════════════════════
#  Helpers — heavy external deps are patched out for every scene test
# ══════════════════════════════════════════════════════════════════════

# All patches needed to safely instantiate GalleryScene without real services.
_SCENE_PATCHES = {
    "db":        "content.scenes.gallery.gallery_scene.Database",
    "flask":     "content.scenes.gallery.gallery_scene.Flask",
    "sio":       "content.scenes.gallery.gallery_scene.SocketIO",
    "shared":    "content.scenes.gallery.gallery_scene.register_shared_assets",
    "state_mgr": "content.scenes.gallery.gallery_scene.get_scene_state_manager",
    "tag_reg":   "content.scenes.gallery.gallery_scene.TagRegistry",
    "nexus":     "content.scenes.gallery.gallery_scene.NexusSceneMixin.nexus_init",
    "overlay":   "engine.overlay.mount_overlay",
}


@pytest.fixture
def gallery():
    """Return a GalleryScene with all heavy deps mocked out."""
    with (
        patch(_SCENE_PATCHES["db"]) as mock_db_cls,
        patch(_SCENE_PATCHES["flask"]) as mock_flask,
        patch(_SCENE_PATCHES["sio"]) as mock_sio_cls,
        patch(_SCENE_PATCHES["shared"]),
        patch(_SCENE_PATCHES["state_mgr"]),
        patch(_SCENE_PATCHES["tag_reg"]),
        patch(_SCENE_PATCHES["nexus"]),
    ):
        mock_app = MagicMock()
        mock_app.secret_key = None
        mock_flask.return_value = mock_app

        mock_sio = MagicMock()
        mock_sio_cls.return_value = mock_sio

        scene = GalleryScene(host="127.0.0.1", port=15560)
        scene.socketio = mock_sio  # ensure the mock is wired
        yield scene

        # Ensure ticker is stopped if any test started it
        scene._ticker_stop.set()
        if scene._ticker_thread and scene._ticker_thread.is_alive():
            scene._ticker_thread.join(timeout=2)


# ══════════════════════════════════════════════════════════════════════
#  Artwork dataclass
# ══════════════════════════════════════════════════════════════════════

class TestArtworkDataclass:
    def test_default_fields(self):
        art = Artwork()
        assert art.id == ""
        assert art.title == ""
        assert art.room == "main_hall"
        assert art.evaluations == []
        assert art.image_path is None

    def test_to_dict_contains_all_keys(self):
        art = Artwork(id="a1", title="Sunset", style="impressionist")
        d = art.to_dict()
        expected = {
            "id", "title", "style", "description", "room",
            "artist_id", "image_prompt", "image_path",
            "evaluations", "created_at",
        }
        assert set(d.keys()) == expected
        assert d["title"] == "Sunset"

    def test_evaluations_list_independent(self):
        """Each Artwork instance has its own evaluations list."""
        a1 = Artwork()
        a2 = Artwork()
        a1.evaluations.append({"score": 9})
        assert len(a2.evaluations) == 0


# ══════════════════════════════════════════════════════════════════════
#  GalleryCharacter dataclass
# ══════════════════════════════════════════════════════════════════════

class TestGalleryCharacterDataclass:
    def test_default_role_is_visitor(self):
        gc = GalleryCharacter()
        assert gc.role == "visitor"
        assert gc.current_room == "main_hall"
        assert gc.mood == "neutral"
        assert gc.artworks_evaluated == 0

    def test_to_dict_round_trip(self):
        gc = GalleryCharacter(char_id="c1", name="Ada", role="curator")
        d = gc.to_dict()
        assert d["char_id"] == "c1"
        assert d["name"] == "Ada"
        assert d["role"] == "curator"

    def test_mood_is_mutable(self):
        gc = GalleryCharacter(mood="happy")
        gc.mood = "melancholic"
        assert gc.mood == "melancholic"


# ══════════════════════════════════════════════════════════════════════
#  Scene initialisation & metadata
# ══════════════════════════════════════════════════════════════════════

class TestSceneInit:
    def test_scene_name(self, gallery):
        assert gallery.scene_name == "gallery"

    def test_host_and_port(self, gallery):
        assert gallery.host == "127.0.0.1"
        assert gallery.port == 15560

    def test_scene_metadata_title(self, gallery):
        assert gallery.SCENE_METADATA["title"] == "Art Gallery"
        assert gallery.SCENE_METADATA["genre"] == "creative"

    def test_scene_metadata_features(self, gallery):
        feats = gallery.SCENE_METADATA["features"]
        assert "image_generation" in feats
        assert "art_evaluation" in feats

    def test_initial_state_empty(self, gallery):
        assert gallery.artworks == {}
        assert gallery.characters == {}
        assert gallery.active_exhibition is None
        assert gallery.gallery_log == []

    def test_streaming_enabled_by_default(self, gallery):
        assert gallery.streaming_enabled is True


# ══════════════════════════════════════════════════════════════════════
#  get_plugin_info
# ══════════════════════════════════════════════════════════════════════

class TestGetPluginInfo:
    def test_returns_dict(self, gallery):
        info = gallery.get_plugin_info()
        assert isinstance(info, dict)

    def test_required_keys(self, gallery):
        info = gallery.get_plugin_info()
        for key in ("name", "scene_id", "description", "version", "port",
                     "skill_packs", "features"):
            assert key in info, f"Missing key: {key}"

    def test_scene_id_matches(self, gallery):
        info = gallery.get_plugin_info()
        assert info["scene_id"] == SCENE_ID

    def test_features_list(self, gallery):
        feats = gallery.get_plugin_info()["features"]
        assert "streaming" in feats
        assert "image_gen" in feats


# ══════════════════════════════════════════════════════════════════════
#  start / stop lifecycle
# ══════════════════════════════════════════════════════════════════════

class TestLifecycle:
    @patch("content.scenes.gallery.gallery_scene.get_framework")
    @patch("content.scenes.gallery.gallery_scene.register_gallery_rules")
    def test_start_seeds_characters_and_runs(self, mock_rules, mock_fw, gallery):
        """start() seeds chars, inits MCP, and launches socketio.run."""
        gallery._seed_characters = MagicMock()
        gallery._mcp_init = MagicMock()
        gallery._start_ticker = MagicMock()

        # socketio.run blocks normally — mock it to return immediately
        gallery.socketio.run = MagicMock()

        gallery.start()

        gallery._seed_characters.assert_called_once()
        gallery._mcp_init.assert_called_once()
        mock_rules.assert_called_once()
        gallery._start_ticker.assert_called_once()
        gallery.socketio.run.assert_called_once()

    @patch("content.scenes.gallery.gallery_scene.get_framework")
    def test_stop_sets_ticker_flag(self, mock_fw, gallery):
        """stop() sets the ticker stop event and flushes nexus."""
        gallery.nexus_flush = MagicMock()
        gallery.stop()
        assert gallery._ticker_stop.is_set()
        gallery.nexus_flush.assert_called_once()

    @patch("content.scenes.gallery.gallery_scene.get_framework")
    def test_stop_joins_ticker_thread(self, mock_fw, gallery):
        """stop() joins the ticker thread if alive."""
        fake_thread = MagicMock()
        fake_thread.is_alive.return_value = True
        gallery._ticker_thread = fake_thread
        gallery.nexus_flush = MagicMock()

        gallery.stop()

        fake_thread.join.assert_called_once_with(timeout=3)

    @patch("content.scenes.gallery.gallery_scene.get_framework")
    def test_stop_saves_framework_state(self, mock_fw, gallery):
        """stop() calls framework.save_state()."""
        gallery.nexus_flush = MagicMock()
        gallery.stop()
        mock_fw.return_value.save_state.assert_called_once()


# ══════════════════════════════════════════════════════════════════════
#  _start_ticker
# ══════════════════════════════════════════════════════════════════════

class TestStartTicker:
    def test_creates_daemon_thread(self, gallery):
        gallery._gallery_tick = MagicMock()
        gallery._start_ticker(interval=0.05)

        assert gallery._ticker_thread is not None
        assert gallery._ticker_thread.daemon is True
        assert gallery._ticker_thread.name == "GalleryTicker"
        assert gallery._ticker_thread.is_alive()

    def test_ticker_stops_on_event(self, gallery):
        """Ticker thread exits when _ticker_stop is set."""
        call_count = {"n": 0}

        def counting_tick():
            call_count["n"] += 1

        gallery._gallery_tick = counting_tick
        gallery._start_ticker(interval=0.02)

        # Let a few ticks fire
        time.sleep(0.12)
        gallery._ticker_stop.set()
        gallery._ticker_thread.join(timeout=2)

        assert not gallery._ticker_thread.is_alive()
        assert call_count["n"] >= 1  # at least one tick fired

    def test_ticker_survives_tick_exception(self, gallery):
        """If _gallery_tick raises, the loop keeps running."""
        call_count = {"n": 0}

        def failing_tick():
            call_count["n"] += 1
            if call_count["n"] <= 2:
                raise RuntimeError("boom")

        gallery._gallery_tick = failing_tick
        gallery._start_ticker(interval=0.02)
        time.sleep(0.15)
        gallery._ticker_stop.set()
        gallery._ticker_thread.join(timeout=2)

        # Should have been called more than 2 times despite first 2 failures
        assert call_count["n"] >= 3


# ══════════════════════════════════════════════════════════════════════
#  _gallery_tick — mood drift & ambient events
# ══════════════════════════════════════════════════════════════════════

class TestGalleryTick:
    def _add_char(self, gallery, cid="c1", mood=0.5):
        gc = GalleryCharacter(char_id=cid, name="Test", mood=mood)
        gallery.characters[cid] = gc
        return gc

    def _add_art(self, gallery, aid="a1"):
        art = Artwork(id=aid, title="Test Art", style="abstract")
        gallery.artworks[aid] = art
        return art

    def test_no_op_with_empty_characters(self, gallery):
        """Tick does nothing when no characters are loaded."""
        gallery._gallery_tick()
        assert gallery.gallery_log == []

    @patch("content.scenes.gallery.gallery_scene.random")
    def test_mood_drift_applied(self, mock_random, gallery):
        """Character mood shifts by the random drift amount."""
        gc = self._add_char(gallery, mood=0.5)
        # Force a +0.02 drift every call, and no ambient event
        mock_random.choice.return_value = 0.02
        mock_random.random.return_value = 0.99  # no ambient event

        gallery._gallery_tick()
        assert gc.mood == pytest.approx(0.52, abs=1e-6)

    @patch("content.scenes.gallery.gallery_scene.random")
    def test_mood_clamped_at_boundaries(self, mock_random, gallery):
        gc_low = self._add_char(gallery, cid="lo", mood=0.0)
        gc_high = self._add_char(gallery, cid="hi", mood=1.0)

        mock_random.choice.return_value = -0.02  # drift down
        mock_random.random.return_value = 0.99

        gallery._gallery_tick()
        assert gc_low.mood >= 0.0
        assert gc_high.mood <= 1.0

    @patch("content.scenes.gallery.gallery_scene.random")
    def test_ambient_event_logged(self, mock_random, gallery):
        """When random < 0.10, an ambient event is added to gallery_log."""
        self._add_char(gallery, mood=0.5)
        art = self._add_art(gallery)

        # random.choice is called 3 times:
        #  1) mood drift  2) pick artwork  3) pick event message
        mock_random.choice.side_effect = [
            0.0,   # mood drift (zero → no mood change reported)
            art,   # pick artwork from list
            f"A visitor pauses to admire '{art.title}'.",
        ]
        mock_random.random.return_value = 0.05  # < 0.10 → trigger event

        gallery._gallery_tick()

        assert len(gallery.gallery_log) == 1
        entry = gallery.gallery_log[0]
        assert entry["type"] == "ambient"
        assert "Test Art" in entry["message"]

    @patch("content.scenes.gallery.gallery_scene.random")
    def test_no_ambient_without_artworks(self, mock_random, gallery):
        """No ambient event when artworks dict is empty even if roll passes."""
        self._add_char(gallery, mood=0.5)
        # No artworks added

        mock_random.choice.return_value = 0.0
        mock_random.random.return_value = 0.01  # would trigger, but no artworks

        gallery._gallery_tick()
        assert len(gallery.gallery_log) == 0

    @patch("content.scenes.gallery.gallery_scene.random")
    def test_tick_broadcasts_on_change(self, mock_random, gallery):
        """socketio.emit is called when there are state changes."""
        self._add_char(gallery, mood=0.5)
        mock_random.choice.return_value = 0.02  # non-zero drift
        mock_random.random.return_value = 0.99

        gallery._gallery_tick()

        gallery.socketio.emit.assert_called_once()
        call_args = gallery.socketio.emit.call_args
        assert call_args[0][0] == "gallery_update"

    @patch("content.scenes.gallery.gallery_scene.random")
    def test_tick_no_broadcast_on_zero_drift(self, mock_random, gallery):
        """No broadcast when mood doesn't change and no ambient event."""
        self._add_char(gallery, mood=0.5)
        mock_random.choice.return_value = 0.0  # zero drift
        mock_random.random.return_value = 0.99  # no event

        gallery._gallery_tick()
        gallery.socketio.emit.assert_not_called()


# ══════════════════════════════════════════════════════════════════════
#  _get_governor_context
# ══════════════════════════════════════════════════════════════════════

class TestGetGovernorContext:
    @patch("engine.mcp.comms_framework.build_governance_context")
    def test_returns_governance_context(self, mock_build, gallery):
        """When build_governance_context succeeds, its result is returned."""
        mock_build.return_value = "mood: excited | heat: 7"
        ctx = gallery._get_governor_context("c1")
        assert ctx == "mood: excited | heat: 7"
        mock_build.assert_called_once_with("c1", "gallery", "")

    @patch("engine.mcp.comms_framework.build_governance_context")
    def test_fallback_on_governance_failure(self, mock_build, gallery):
        """When build_governance_context raises, falls back to state_coordinator."""
        mock_build.side_effect = RuntimeError("no framework")

        with patch("engine.mcp.state_coordinator.get_coordinator") as mock_coord:
            mock_coord.return_value.get_full_state.return_value = {
                "mood": "pensive", "energy": 42,
            }
            ctx = gallery._get_governor_context("c1")

        assert "pensive" in ctx
        assert "42" in ctx

    @patch("engine.mcp.comms_framework.build_governance_context")
    def test_empty_string_when_all_fail(self, mock_build, gallery):
        """When every path fails, return empty string without crashing."""
        mock_build.side_effect = RuntimeError("fail")

        with patch("engine.mcp.state_coordinator.get_coordinator", side_effect=ImportError):
            ctx = gallery._get_governor_context("c1")

        assert ctx == ""


# ══════════════════════════════════════════════════════════════════════
#  _get_state — MCP state syncing
# ══════════════════════════════════════════════════════════════════════

class TestGetState:
    def test_empty_state_structure(self, gallery):
        state = gallery._get_state()
        assert state["characters"] == {}
        assert state["artworks"] == {}
        assert state["rooms"] == GALLERY_ROOMS
        assert state["active_exhibition"] is None
        assert state["streaming_enabled"] is True

    def test_state_includes_characters(self, gallery):
        gc = GalleryCharacter(char_id="c1", name="Alice", role="curator")
        gallery.characters["c1"] = gc

        state = gallery._get_state()
        assert "c1" in state["characters"]
        assert state["characters"]["c1"]["name"] == "Alice"

    def test_state_includes_artworks(self, gallery):
        art = Artwork(id="a1", title="Blue Horizon")
        gallery.artworks["a1"] = art

        state = gallery._get_state()
        assert "a1" in state["artworks"]
        assert state["artworks"]["a1"]["title"] == "Blue Horizon"

    def test_state_log_capped_at_50(self, gallery):
        gallery.gallery_log = [{"idx": i} for i in range(100)]
        state = gallery._get_state()
        assert len(state["log"]) == 50

    def test_state_includes_exhibition_info(self, gallery):
        gallery.active_exhibition = "neon_futures"
        state = gallery._get_state()
        assert state["active_exhibition"] == "neon_futures"
        assert state["exhibition_info"]["label"] == "Neon Futures"


# ══════════════════════════════════════════════════════════════════════
#  _log helper
# ══════════════════════════════════════════════════════════════════════

class TestLogHelper:
    def test_log_appends_entry(self, gallery):
        gallery._log("test_event", "something happened")
        assert len(gallery.gallery_log) == 1
        entry = gallery.gallery_log[0]
        assert entry["type"] == "test_event"
        assert entry["text"] == "something happened"
        assert "timestamp" in entry

    def test_log_emits_to_socketio(self, gallery):
        gallery._log("test_event", "hello")
        gallery.socketio.emit.assert_called_once()
        call_args = gallery.socketio.emit.call_args
        assert call_args[0][0] == "gallery_log"

    def test_log_truncates_at_200(self, gallery):
        gallery.gallery_log = [{"i": i} for i in range(200)]
        gallery._log("overflow", "trim check")
        # 200 + 1 append = 201 > 200 → truncated to last 100
        assert len(gallery.gallery_log) == 100


# ══════════════════════════════════════════════════════════════════════
#  Static data — rooms, styles, exhibitions
# ══════════════════════════════════════════════════════════════════════

class TestStaticData:
    def test_gallery_rooms_count(self):
        assert len(GALLERY_ROOMS) == 5

    def test_all_rooms_have_required_keys(self):
        for room_id, room in GALLERY_ROOMS.items():
            assert "name" in room
            assert "description" in room
            assert "capacity" in room
            assert "lighting" in room
            assert isinstance(room["capacity"], int)

    def test_art_styles_non_empty(self):
        assert len(ART_STYLES) >= 5
        assert "impressionist" in ART_STYLES
        assert "cyberpunk" in ART_STYLES

    def test_premade_exhibitions_have_seed_artworks(self):
        for key, ex in PREMADE_EXHIBITIONS.items():
            assert "label" in ex
            assert "emoji" in ex
            assert "theme" in ex
            assert "style_hint" in ex
            assert "seed_artworks" in ex
            assert len(ex["seed_artworks"]) >= 1

    def test_scene_id_constant(self):
        assert SCENE_ID == "gallery"


# ══════════════════════════════════════════════════════════════════════
#  create_app factory
# ══════════════════════════════════════════════════════════════════════

class TestCreateApp:
    def test_returns_gallery_scene(self):
        with (
            patch(_SCENE_PATCHES["db"]),
            patch(_SCENE_PATCHES["flask"]) as mock_flask,
            patch(_SCENE_PATCHES["sio"]),
            patch(_SCENE_PATCHES["shared"]),
            patch(_SCENE_PATCHES["state_mgr"]),
            patch(_SCENE_PATCHES["tag_reg"]),
            patch(_SCENE_PATCHES["nexus"]),
        ):
            mock_flask.return_value = MagicMock()
            scene = create_app(host="0.0.0.0", port=9999)
            assert isinstance(scene, GalleryScene)
            assert scene.port == 9999


# ══════════════════════════════════════════════════════════════════════
#  _on_art_event
# ══════════════════════════════════════════════════════════════════════

class TestOnArtEvent:
    def test_emits_payload(self, gallery):
        evt = MagicMock()
        evt.payload = {"artwork_id": "a1", "title": "Test"}
        gallery._on_art_event(evt)
        gallery.socketio.emit.assert_called_once_with("art_event", evt.payload)

    def test_swallows_emit_error(self, gallery):
        """_on_art_event should not raise if socketio.emit fails."""
        gallery.socketio.emit.side_effect = RuntimeError("socket dead")
        evt = MagicMock()
        evt.payload = {}
        gallery._on_art_event(evt)  # should not raise
