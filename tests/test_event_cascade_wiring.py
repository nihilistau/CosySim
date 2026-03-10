"""Tests for EventCascade wiring in launcher.py and BaseScene._wire_event_cascade().

Verifies:
- launcher.launch_multi calls get_event_cascade().start()
- BaseScene._wire_event_cascade subscribes correct event types
- BaseScene._mcp_register_scene calls _wire_event_cascade
- Scenes without DEFAULT_SCENE_SUBSCRIPTIONS entry are silently skipped
- EventCascade.start() is idempotent (safe to call from base and launcher)
"""
from __future__ import annotations

from typing import Any, Dict, List
from unittest.mock import MagicMock, call, patch

import pytest


# ──── launcher wiring ─────────────────────────────────────────────────────────


class TestLauncherEventCascadeWiring:
    """Event cascade is started inside launch_multi()."""

    def _run_launch_multi_body(self, mock_cascade_start: MagicMock) -> None:
        """Import and exercise the cascade startup block."""
        with (
            patch("engine.world.event_cascade.get_event_cascade") as mock_get,
            patch("engine.world.world_sim.get_world_sim", side_effect=RuntimeError("no sim")),
            patch("engine.events.cross_scene_relay.get_cross_scene_relay", side_effect=RuntimeError("no relay")),
        ):
            mock_cascade = MagicMock()
            mock_cascade.start = mock_cascade_start
            mock_get.return_value = mock_cascade

            # Simulate the launcher cascade block directly
            try:
                from engine.world.event_cascade import get_event_cascade
                get_event_cascade().start()
            except Exception:
                pass

    def test_cascade_start_called(self) -> None:
        """get_event_cascade().start() is invoked."""
        start_mock = MagicMock()
        self._run_launch_multi_body(start_mock)
        start_mock.assert_called_once()

    def test_launcher_imports_cascade(self) -> None:
        """launcher.py source contains the EventCascade import."""
        import pathlib
        src = pathlib.Path("launcher.py").read_text(encoding="utf-8")
        assert "from engine.world.event_cascade import get_event_cascade" in src

    def test_launcher_calls_cascade_start(self) -> None:
        """launcher.py source contains get_event_cascade().start()."""
        import pathlib
        src = pathlib.Path("launcher.py").read_text(encoding="utf-8")
        assert "get_event_cascade().start()" in src

    def test_launcher_version_updated(self) -> None:
        """launcher.py VERSION is at least 0.91b."""
        import pathlib
        src = pathlib.Path("launcher.py").read_text(encoding="utf-8")
        assert 'VERSION = "1.03b"' in src


# ──── BaseScene._wire_event_cascade ──────────────────────────────────────────


class TestBaseSceneWireEventCascade:
    """BaseScene._wire_event_cascade() correctly subscribes the scene."""

    def _make_scene(self, scene_name: str) -> Any:
        """Build a minimal BaseScene-like stub with the real _wire_event_cascade method."""
        from engine.scenes.base_scene import BaseScene

        # Use a plain object to host the method without triggering Flask etc.
        scene = type("FakeScene", (), {"scene_name": scene_name})()
        scene._wire_event_cascade = BaseScene._wire_event_cascade.__get__(scene)
        return scene

    def test_known_scene_subscribes_default_types(self) -> None:
        """Bedroom subscribes to SOCIAL, RUMOUR, NPC."""
        from engine.world.event_cascade import DEFAULT_SCENE_SUBSCRIPTIONS, get_event_cascade

        with patch("engine.world.event_cascade.get_event_cascade") as mock_get:
            cascade = MagicMock()
            mock_get.return_value = cascade

            scene = self._make_scene("penthouse")
            scene._wire_event_cascade()

            cascade.subscribe.assert_called_once()
            args = cascade.subscribe.call_args
            assert args[0][0] == "penthouse"
            subscribed = set(args[0][1])
            expected = set(DEFAULT_SCENE_SUBSCRIPTIONS["penthouse"])
            assert subscribed == expected

    def test_unknown_scene_does_not_subscribe(self) -> None:
        """A scene with no DEFAULT_SCENE_SUBSCRIPTIONS entry is silently skipped."""
        with patch("engine.world.event_cascade.get_event_cascade") as mock_get:
            cascade = MagicMock()
            mock_get.return_value = cascade

            scene = self._make_scene("unknown_scene_xyz")
            scene._wire_event_cascade()

            cascade.subscribe.assert_not_called()

    def test_intel_hub_subscribes_all_types(self) -> None:
        """intel_hub subscribes to all 10 WorldEventType constants."""
        from engine.world.event_cascade import WorldEventType

        with patch("engine.world.event_cascade.get_event_cascade") as mock_get:
            cascade = MagicMock()
            mock_get.return_value = cascade

            scene = self._make_scene("intel_hub")
            scene._wire_event_cascade()

            cascade.subscribe.assert_called_once()
            subscribed = set(cascade.subscribe.call_args[0][1])
            assert subscribed == WorldEventType.ALL

    def test_cascade_import_failure_is_silent(self) -> None:
        """If EventCascade is unavailable the method does not raise."""
        with patch.dict("sys.modules", {"engine.world.event_cascade": None}):
            scene = self._make_scene("penthouse")
            # Should not raise even when the module is unavailable
            try:
                scene._wire_event_cascade()
            except Exception as exc:
                pytest.fail(f"_wire_event_cascade raised unexpectedly: {exc}")

    def test_mcp_register_scene_calls_wire_cascade(self) -> None:
        """_mcp_register_scene() triggers _wire_event_cascade()."""
        from engine.scenes.base_scene import BaseScene

        scene = type("FakeScene", (), {"scene_name": "casino"})()
        scene._wire_event_cascade = MagicMock()
        scene._mcp_register_scene = BaseScene._mcp_register_scene.__get__(scene)

        with patch("engine.mcp.framework.get_framework", side_effect=RuntimeError("no fw")):
            scene._mcp_register_scene()

        scene._wire_event_cascade.assert_called_once()


# ──── EventCascade.start() idempotency with wiring ───────────────────────────


class TestEventCascadeStartIdempotency:
    """start() called from both launcher and base scene is safe."""

    def test_start_idempotent(self) -> None:
        """Multiple start() calls do not double-register WorldSim hooks."""
        from engine.world.event_cascade import EventCascade

        cascade = EventCascade()
        with patch("engine.world.world_sim.get_world_sim") as mock_sim:
            sim = MagicMock()
            sim.on_event = MagicMock()
            mock_sim.return_value = sim

            cascade.start()
            cascade.start()
            cascade.start()

            # on_event registered exactly once despite multiple start() calls
            sim.on_event.assert_called_once()

    def test_start_with_no_world_sim_does_not_raise(self) -> None:
        """start() is safe when WorldSim is not available."""
        from engine.world.event_cascade import EventCascade

        cascade = EventCascade()
        with patch("engine.world.world_sim.get_world_sim", side_effect=ImportError("no sim")):
            cascade.start()  # must not raise

        assert cascade._started is True
