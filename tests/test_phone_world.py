"""Tests for phone scene living-world integration (Track D, v0.75 NEON CITY).

Covers:
- /api/world/incoming endpoint
- Message formatting (type, from, text, heat_impact)
- /api/world/send_ghost endpoint and credit earning
- world_alert Socket.IO emission for high-intensity events
- world event bus subscription handlers
- get_ghost_messages skill
- send_ghost_tip skill
"""
from __future__ import annotations

import pytest
from unittest.mock import MagicMock, patch, call
from dataclasses import dataclass, field
from typing import Any, Dict


# ---------------------------------------------------------------------------
# Shared fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def reset_player_state():
    """Reset PlayerState singleton before each test."""
    from engine.world.player_state import reset_player_state
    reset_player_state()
    yield
    reset_player_state()


def _make_sim_event(
    scene: str = "phone",
    actor: str = "0xGH0ST",
    intensity: float = 2.5,
    description: str = "Test ghost message",
    heat_impact: int = 3,
    created_at: str = "Day 1 12:00",
) -> Any:
    """Build a minimal SimEvent-like object for testing."""
    from engine.world.world_sim import SimEvent, SimEventType
    import uuid
    return SimEvent(
        id=str(uuid.uuid4()),
        event_type=SimEventType.HACKER_MESSAGE,
        title="Test Event",
        description=description,
        scene=scene,
        actor=actor,
        intensity=intensity,
        payload={"heat_impact": heat_impact},
        created_at=created_at,
    )


def _make_flask_client():
    """Create a test Flask client from PhoneSceneV2 with mocked deps."""
    with (
        patch("content.scenes.phone.phone_scene_v2.PhoneDB"),
        patch("content.scenes.phone.phone_scene_v2.Database"),
        patch("content.scenes.phone.phone_scene_v2.get_llm_service"),
        patch("content.scenes.phone.phone_scene_v2.get_framework"),
        patch("content.scenes.phone.phone_scene_v2.get_scene_state_manager"),
        patch("content.scenes.phone.phone_scene_v2.TagRegistry"),
        patch("content.scenes.phone.phone_scene_v2.register_shared_assets"),
        patch("engine.scenes.nexus_mixin.NexusSceneMixin.nexus_init"),
        patch("engine.overlay.mount_overlay"),
        patch("content.scenes.phone.phone_scene_v2.PhoneSceneV2.register_health_route"),
        patch("content.scenes.phone.phone_scene_v2.PhoneSceneV2.register_tts_route"),
    ):
        from content.scenes.phone.phone_scene_v2 import PhoneSceneV2
        scene = PhoneSceneV2.__new__(PhoneSceneV2)
        # Minimal init without calling super chain
        from flask import Flask
        from flask_socketio import SocketIO
        scene.app = Flask(__name__)
        scene.socketio = SocketIO(scene.app, async_mode="threading")
        scene.phone_db = MagicMock()
        scene.db = MagicMock()
        scene.llm = MagicMock()
        scene._agents = {}
        scene._autotxt_deadlines = {}
        import threading
        scene._autotxt_lock = threading.Lock()
        scene._autotxt_muted = False
        scene._tick_lock = threading.RLock()
        scene._ticker_stop = threading.Event()
        scene._ticker_thread = None
        scene._state_mgr = MagicMock()
        scene._tag_registry = MagicMock()
        # Register routes
        scene._register_routes()
        return scene


# ---------------------------------------------------------------------------
# Tests: /api/world/incoming
# ---------------------------------------------------------------------------


class TestWorldIncomingEndpoint:
    def test_returns_list(self):
        """/api/world/incoming returns a JSON list."""
        scene = _make_flask_client()
        with scene.app.test_client() as client:
            with patch.object(scene, "_get_incoming_world_messages", return_value=[]):
                r = client.get("/api/world/incoming")
        assert r.status_code == 200
        data = r.get_json()
        assert isinstance(data, list)

    def test_returns_messages_from_helper(self):
        """Endpoint forwards whatever _get_incoming_world_messages returns."""
        msgs = [{"from": "0xGH0ST", "text": "Stay dark.", "time": "Day 1 00:00", "type": "ghost", "heat_impact": 3}]
        scene = _make_flask_client()
        with scene.app.test_client() as client:
            with patch.object(scene, "_get_incoming_world_messages", return_value=msgs):
                r = client.get("/api/world/incoming")
        data = r.get_json()
        assert len(data) == 1
        assert data[0]["from"] == "0xGH0ST"

    def test_returns_empty_list_when_no_events(self):
        """Returns [] when no world events match filter."""
        scene = _make_flask_client()
        with scene.app.test_client() as client:
            with patch.object(scene, "_get_incoming_world_messages", return_value=[]):
                r = client.get("/api/world/incoming")
        assert r.get_json() == []


# ---------------------------------------------------------------------------
# Tests: message formatting
# ---------------------------------------------------------------------------


class TestMessageFormatting:
    def test_ghost_event_type_is_ghost(self):
        """Events with actor 0xGH0ST get type='ghost'."""
        event = _make_sim_event(actor="0xGH0ST", scene="phone", intensity=2.5)
        with patch("engine.world.world_sim.get_world_sim") as mock_sim:
            mock_sim.return_value.get_all_events.return_value = [event]
            from content.scenes.phone.phone_scene_v2 import PhoneSceneV2
            scene = object.__new__(PhoneSceneV2)
            msgs = scene._get_incoming_world_messages()
        assert msgs[0]["type"] == "ghost"
        assert msgs[0]["from"] == "0xGH0ST"

    def test_non_ghost_event_type_is_world(self):
        """Non-ghost events get type='world'."""
        event = _make_sim_event(actor="corp_drone", scene="phone", intensity=2.8, description="Corp sweep incoming")
        with patch("engine.world.world_sim.get_world_sim") as mock_sim:
            mock_sim.return_value.get_all_events.return_value = [event]
            from content.scenes.phone.phone_scene_v2 import PhoneSceneV2
            scene = object.__new__(PhoneSceneV2)
            msgs = scene._get_incoming_world_messages()
        assert msgs[0]["type"] == "world"
        assert msgs[0]["from"] == "corp_drone"

    def test_message_has_required_fields(self):
        """Each message dict has from, text, time, type, heat_impact fields."""
        event = _make_sim_event()
        with patch("engine.world.world_sim.get_world_sim") as mock_sim:
            mock_sim.return_value.get_all_events.return_value = [event]
            from content.scenes.phone.phone_scene_v2 import PhoneSceneV2
            scene = object.__new__(PhoneSceneV2)
            msgs = scene._get_incoming_world_messages()
        msg = msgs[0]
        for key in ("from", "text", "time", "type", "heat_impact"):
            assert key in msg, f"Missing key: {key}"

    def test_heat_impact_propagated(self):
        """heat_impact from event payload is included in message dict."""
        event = _make_sim_event(heat_impact=7)
        with patch("engine.world.world_sim.get_world_sim") as mock_sim:
            mock_sim.return_value.get_all_events.return_value = [event]
            from content.scenes.phone.phone_scene_v2 import PhoneSceneV2
            scene = object.__new__(PhoneSceneV2)
            msgs = scene._get_incoming_world_messages()
        assert msgs[0]["heat_impact"] == 7

    def test_filters_low_intensity_non_phone_events(self):
        """Events not in phone scene with intensity < 2.5 are excluded."""
        low_event = _make_sim_event(scene="arena", intensity=1.0)
        high_event = _make_sim_event(scene="neoncity", intensity=2.9, actor="corp_drone")
        with patch("engine.world.world_sim.get_world_sim") as mock_sim:
            mock_sim.return_value.get_all_events.return_value = [low_event, high_event]
            from content.scenes.phone.phone_scene_v2 import PhoneSceneV2
            scene = object.__new__(PhoneSceneV2)
            msgs = scene._get_incoming_world_messages()
        assert len(msgs) == 1
        assert msgs[0]["text"] == high_event.description

    def test_returns_at_most_five_messages(self):
        """At most 5 messages are returned."""
        events = [_make_sim_event(scene="phone") for _ in range(10)]
        with patch("engine.world.world_sim.get_world_sim") as mock_sim:
            mock_sim.return_value.get_all_events.return_value = events
            from content.scenes.phone.phone_scene_v2 import PhoneSceneV2
            scene = object.__new__(PhoneSceneV2)
            msgs = scene._get_incoming_world_messages()
        assert len(msgs) <= 5


# ---------------------------------------------------------------------------
# Tests: /api/world/send_ghost
# ---------------------------------------------------------------------------


class TestSendGhostEndpoint:
    def test_earns_credits(self):
        """POST /api/world/send_ghost earns 50 credits."""
        scene = _make_flask_client()
        with scene.app.test_client() as client:
            with (
                patch("engine.nexus.client.get_nexus_client") as mock_nexus,
            ):
                mock_nexus.return_value.add_entry = MagicMock()
                r = client.post(
                    "/api/world/send_ghost",
                    json={"message": "They moved the package."},
                    content_type="application/json",
                )
        data = r.get_json()
        assert data["ok"] is True
        assert data["credits_earned"] == 50

    def test_returns_new_balance(self):
        """/api/world/send_ghost returns current balance in response."""
        from engine.world.player_state import get_player_state
        ps = get_player_state()
        starting = ps.to_dict()["credits"]

        scene = _make_flask_client()
        with scene.app.test_client() as client:
            with patch("engine.nexus.client.get_nexus_client") as mock_nexus:
                mock_nexus.return_value.add_entry = MagicMock()
                r = client.post(
                    "/api/world/send_ghost",
                    json={"message": "Intel confirmed."},
                    content_type="application/json",
                )
        data = r.get_json()
        assert data["balance"] == starting + 50

    def test_missing_message_returns_400(self):
        """/api/world/send_ghost returns 400 when message is missing."""
        scene = _make_flask_client()
        with scene.app.test_client() as client:
            r = client.post(
                "/api/world/send_ghost",
                json={},
                content_type="application/json",
            )
        assert r.status_code == 400

    def test_stores_to_nexus(self):
        """/api/world/send_ghost stores message in Nexus under phone_messages."""
        scene = _make_flask_client()
        with scene.app.test_client() as client:
            with patch("engine.nexus.client.get_nexus_client") as mock_nexus:
                add_entry = MagicMock()
                mock_nexus.return_value.add_entry = add_entry
                client.post(
                    "/api/world/send_ghost",
                    json={"message": "Corp comms compromised."},
                    content_type="application/json",
                )
        add_entry.assert_called_once()
        kwargs = add_entry.call_args.kwargs if add_entry.call_args.kwargs else {}
        args = add_entry.call_args.args if add_entry.call_args.args else ()
        # Accept both positional and keyword calls
        call_flat = str(add_entry.call_args)
        assert "ghost_outgoing" in call_flat
        assert "phone_messages" in call_flat


# ---------------------------------------------------------------------------
# Tests: world_alert Socket.IO emission
# ---------------------------------------------------------------------------


class TestWorldAlertEmission:
    def test_high_intensity_event_emits_world_alert(self):
        """_on_world_major_event emits world_alert for intensity >= 2.5."""
        from content.scenes.phone.phone_scene_v2 import PhoneSceneV2
        scene = object.__new__(PhoneSceneV2)
        scene.socketio = MagicMock()

        high_event = _make_sim_event(scene="neoncity", intensity=3.0)
        payload = {
            "title": "Corp Raid",
            "scene": "neoncity",
            "event_type": "corp_raid",
            "sim_event_id": high_event.id,
        }

        with patch("engine.world.world_sim.get_world_sim") as mock_sim:
            sim = MagicMock()
            sim._lock = __import__("threading").Lock()
            sim._event_log = [high_event]
            mock_sim.return_value = sim
            scene._on_world_major_event(payload)

        scene.socketio.emit.assert_called_once()
        event_name = scene.socketio.emit.call_args[0][0]
        assert event_name == "world_alert"

    def test_low_intensity_event_does_not_emit_world_alert(self):
        """_on_world_major_event does NOT emit world_alert for intensity < 2.5."""
        from content.scenes.phone.phone_scene_v2 import PhoneSceneV2
        scene = object.__new__(PhoneSceneV2)
        scene.socketio = MagicMock()

        low_event = _make_sim_event(intensity=1.5)
        payload = {"sim_event_id": low_event.id, "title": "Minor NPC", "scene": "arena", "event_type": "npc"}

        with patch("engine.world.world_sim.get_world_sim") as mock_sim:
            sim = MagicMock()
            sim._lock = __import__("threading").Lock()
            sim._event_log = [low_event]
            mock_sim.return_value = sim
            scene._on_world_major_event(payload)

        scene.socketio.emit.assert_not_called()

    def test_hacker_event_emits_incoming_message(self):
        """_on_world_hacker_event emits incoming_message Socket.IO event."""
        from content.scenes.phone.phone_scene_v2 import PhoneSceneV2
        scene = object.__new__(PhoneSceneV2)
        scene.socketio = MagicMock()

        scene._on_world_hacker_event({"message": "They found the node."})

        scene.socketio.emit.assert_called_once()
        args = scene.socketio.emit.call_args[0]
        assert args[0] == "incoming_message"
        assert args[1]["from"] == "0xGH0ST"
        assert args[1]["type"] == "ghost"


# ---------------------------------------------------------------------------
# Tests: skills
# ---------------------------------------------------------------------------


class TestGetGhostMessagesSkill:
    def test_no_scene_returns_not_active(self):
        """Returns 'not active' message when scene is unavailable."""
        with patch("content.scenes.phone.phone_skills._get_phone_scene", return_value=None):
            from content.scenes.phone.phone_skills import get_ghost_messages
            result = get_ghost_messages()
        assert "not active" in result.lower()

    def test_empty_messages_returns_no_transmissions(self):
        """Returns 'no incoming' message when there are no world messages."""
        mock_scene = MagicMock()
        mock_scene._get_incoming_world_messages.return_value = []
        with patch("content.scenes.phone.phone_skills._get_phone_scene", return_value=mock_scene):
            from content.scenes.phone.phone_skills import get_ghost_messages
            result = get_ghost_messages()
        assert "0xGH0ST" in result or "transmissions" in result.lower()

    def test_returns_formatted_messages(self):
        """Returns formatted string including sender and message text."""
        msgs = [
            {"from": "0xGH0ST", "text": "Stay dark.", "type": "ghost", "heat_impact": 2, "time": "Day 1"},
        ]
        mock_scene = MagicMock()
        mock_scene._get_incoming_world_messages.return_value = msgs
        with patch("content.scenes.phone.phone_skills._get_phone_scene", return_value=mock_scene):
            from content.scenes.phone.phone_skills import get_ghost_messages
            result = get_ghost_messages()
        assert "0xGH0ST" in result
        assert "Stay dark." in result

    def test_includes_heat_impact_when_nonzero(self):
        """Heat impact is shown in formatted output when > 0."""
        msgs = [
            {"from": "0xGH0ST", "text": "Corp sweep incoming.", "type": "ghost", "heat_impact": 5, "time": ""},
        ]
        mock_scene = MagicMock()
        mock_scene._get_incoming_world_messages.return_value = msgs
        with patch("content.scenes.phone.phone_skills._get_phone_scene", return_value=mock_scene):
            from content.scenes.phone.phone_skills import get_ghost_messages
            result = get_ghost_messages()
        assert "5" in result


class TestSendGhostTipSkill:
    def test_no_message_returns_provide_prompt(self):
        """Returns guidance when message is empty."""
        from content.scenes.phone.phone_skills import send_ghost_tip
        result = send_ghost_tip()
        assert "intel" in result.lower() or "message" in result.lower() or "provide" in result.lower()

    def test_earns_credits_and_returns_balance(self):
        """Earns 50 credits and includes balance in response."""
        from engine.world.player_state import get_player_state
        ps = get_player_state()
        starting = ps.to_dict()["credits"]

        with patch("engine.nexus.client.get_nexus_client") as mock_nexus:
            mock_nexus.return_value.add_entry = MagicMock()
            from content.scenes.phone.phone_skills import send_ghost_tip
            result = send_ghost_tip(message="Corp data cache located at node 7.")

        new_balance = get_player_state().to_dict()["credits"]
        assert new_balance == starting + 50
        assert "50" in result
        assert str(new_balance) in result

    def test_stores_message_in_nexus(self):
        """Stores the tip in Nexus with category=phone_messages."""
        with patch("engine.nexus.client.get_nexus_client") as mock_nexus:
            add_entry = MagicMock()
            mock_nexus.return_value.add_entry = add_entry
            from content.scenes.phone.phone_skills import send_ghost_tip
            send_ghost_tip(message="Blackmarket cache confirmed.")

        add_entry.assert_called_once()
        call_repr = str(add_entry.call_args)
        assert "ghost_outgoing" in call_repr
        assert "phone_messages" in call_repr
