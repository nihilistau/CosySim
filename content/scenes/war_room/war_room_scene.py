"""The War Room — faction command center scene.
============================================

Pick a faction. Command crews. Take the city. The War Room is the player's
strategic command center for NEONCITY's emergent metagame — choose an
allegiance, issue crew orders and direct territory operations against the
rival factions that the living world simulates.

C-T1 ships the SCAFFOLD: a bootable placeholder scene serving a neon page and
a stub ``/api/state`` endpoint. The faction-select, crew-command and
territory-operations command center renders against the engine's existing
managers in later v1.63 tasks.

Version: v1.63.0 [2026-06-16]
Author:  CosySim Team

Change Log:
    v1.63.0 [2026-06-16] — Initial scaffold (C-T1): bootable placeholder scene,
                            registered for launcher/TUI/hub + auto-start
    v1.63.0 [2026-06-16] — C-T2: player allegiance + live faction dashboard
                            backend. Reads the existing territory / faction-AI /
                            crew / faction-politics managers (read-only except
                            the player's own allegiance), exposes
                            ``/api/warroom/{factions,allegiance,state}`` and a
                            throttled ``warroom_update`` socket push wired to the
                            EventBus (living_world_tick / territory_shift /
                            faction_decision).

CONNECTS: FlaskScene, SocketIO, get_config, EventBus, PlayerState,
          TerritoryManager, FactionAI, CrewManager, FactionManager
CALLED BY: launcher.py, TUI, hub
EMITS: state_update, warroom_update Socket.IO events
"""
from __future__ import annotations

import logging
import time
from typing import Any, Dict, List, Optional

from flask import jsonify, render_template, request
from flask_socketio import emit

from engine.scenes.flask_scene import FlaskScene

logger = logging.getLogger(__name__)

SCENE_ID = "war_room"
# v1.63.0 [2026-06-16] — Structured logging context (SCENE_ID prefix + operation tags)

# v1.63.0 [2026-06-16] — C-T2: the 6 canonical factions (single source of truth)
CANONICAL_FACTIONS: List[str] = [
    "OmniCorp",
    "NeoTech",
    "BlackMarket",
    "Ghost_Net",
    "SynthSec",
    "DeepState",
]

# v1.63.0 [2026-06-16] — C-T2: EventBus events that should refresh the dashboard
_PUSH_EVENTS: List[str] = [
    "living_world_tick",
    "territory_shift",
    "faction_decision",
]

# v1.63.0 [2026-06-16] — C-T2: default rank ladder (config-overridable via
# war_room.rank_thresholds). Power = TerritoryManager.get_faction_total_control.
_DEFAULT_RANK_THRESHOLDS: List[Dict[str, Any]] = [
    {"min": 0, "rank": "Unknown"},
    {"min": 60, "rank": "Street Crew"},
    {"min": 120, "rank": "Contender"},
    {"min": 200, "rank": "Power Player"},
    {"min": 320, "rank": "Kingpin"},
]


# ──── Scene Implementation ────────────────────────────────────

# v1.63.0 [2026-06-16] — Faction command-center scaffold on FlaskScene base
class WarRoomScene(FlaskScene):
    """The War Room: the player's faction command center.

    Serves the faction command center — pick a faction, command crews and take
    the city. C-T1 ships the bootable scaffold; the live command center renders
    against the engine's emergent managers in later v1.63 tasks.

    CONNECTS: FlaskScene, SocketIO, get_config
    CALLED BY: launcher.py, TUI, hub
    EMITS: state_update Socket.IO event
    """

    SCENE_METADATA = {
        "name": "war_room",
        "display_name": "THE WAR ROOM",
        "port": 5598,
        "type": "game",
        "accent_color": "#ef4444",
        "description": "Pick a faction. Command crews. Take the city.",
        "version": "1.0.0",
    }

    def __init__(self, config: Optional[Dict[str, Any]] = None,
                 host: str = "0.0.0.0") -> None:
        super().__init__(host=host, port=self.SCENE_METADATA["port"])
        self.config = config or {}

        # Scene-specific secret key
        self.app.config["SECRET_KEY"] = "war-room-scene"

        # v1.63.0 [2026-06-16] — C-T2: EventBus subscription ids + push throttle
        self._sub_ids: List[str] = []
        self._last_push: float = 0.0

        # Scene-specific route registrations
        self.register_bench_route(self.app, self.socketio)
        self._register_routes()
        self._setup_socketio_handlers()

    # ── Config ─────────────────────────────────────────────────────

    def _cfg(self, key: str, default: Any) -> Any:
        """Return a ``war_room.*`` knob from config with a built-in default.

        Args:
            key: Short key under ``war_room.`` (e.g. ``"contest_delta"``).
            default: Fallback when config is unavailable or the key is unset.

        Returns:
            The configured value, or ``default`` (never raises).
        """
        try:
            from engine.config import get_config  # noqa: PLC0415
            return get_config().get("war_room." + key, default)
        except Exception as exc:  # config optional in minimal builds
            logger.debug("[%s] config lookup failed (operation=cfg, key=%s): %s",
                         SCENE_ID, key, exc)
            return default

    # ── Manager accessors (read-only except player allegiance) ──────
    # Each returns the live singleton, or raises — callers wrap defensively.
    # Patched in unit tests with in-memory fakes.

    def _territory(self):
        """Return the live :class:`TerritoryManager` singleton."""
        from engine.world.territory import get_territory_manager  # noqa: PLC0415
        return get_territory_manager()

    def _faction_ai(self):
        """Return the live :class:`FactionAI` singleton."""
        from engine.world.faction_ai import get_faction_ai  # noqa: PLC0415
        return get_faction_ai()

    def _crew(self):
        """Return the live :class:`CrewManager` singleton."""
        from engine.world.crew import get_crew_manager  # noqa: PLC0415
        return get_crew_manager()

    def _player(self):
        """Return the live :class:`PlayerState` singleton."""
        from engine.world.player_state import get_player_state  # noqa: PLC0415
        return get_player_state()

    def _faction_mgr(self):
        """Return the live :class:`FactionManager` singleton."""
        from engine.story.faction_politics import FactionManager  # noqa: PLC0415
        return FactionManager.get_instance()

    # ── State assembly (pure, defensive, unit-tested) ───────────────

    def _dominant_districts(self, faction: str) -> List[str]:
        """Return districts where *faction* holds the plurality of control.

        Reads :meth:`TerritoryManager.get_all_control`. Never raises — returns
        ``[]`` if territory data is unavailable.

        Args:
            faction: Canonical faction name.

        Returns:
            Sorted list of district ids the faction dominates.
        """
        try:
            all_control = self._territory().get_all_control()
        except Exception as exc:
            logger.debug("[%s] territory control unavailable (operation=districts): %s",
                         SCENE_ID, exc)
            return []
        owned: List[str] = []
        for district, ctrl in (all_control or {}).items():
            if not ctrl:
                continue
            try:
                top = max(ctrl.items(), key=lambda kv: kv[1])
            except ValueError:
                continue
            if top[0] == faction and top[1] > 0:
                owned.append(district)
        return sorted(owned)

    def _faction_power(self, faction: str) -> float:
        """Return a faction's total control (power), 0.0 if unavailable."""
        try:
            return round(float(self._territory().get_faction_total_control(faction)), 2)
        except Exception as exc:
            logger.debug("[%s] power lookup failed (operation=power, faction=%s): %s",
                         SCENE_ID, faction, exc)
            return 0.0

    def _faction_relation(self, faction: str) -> int:
        """Return the player's standing with *faction* via FactionManager.

        Falls back to 0 (neutral) when the faction is unregistered or the
        manager is unavailable. Read-only.

        Args:
            faction: Canonical faction name.

        Returns:
            Player standing (-100..100), or 0.
        """
        try:
            entry = self._faction_mgr().get(faction)
            if entry is not None:
                return int(getattr(entry, "player_standing", 0) or 0)
        except Exception as exc:
            logger.debug("[%s] relation lookup failed (operation=relation, faction=%s): %s",
                         SCENE_ID, faction, exc)
        return 0

    def _faction_traits(self, faction: str) -> Dict[str, Any]:
        """Return a faction's personality traits from FACTION_TRAITS (or {})."""
        try:
            from engine.world.territory import FACTION_TRAITS  # noqa: PLC0415
            return dict(FACTION_TRAITS.get(faction, {}))
        except Exception as exc:
            logger.debug("[%s] traits unavailable (operation=traits): %s", SCENE_ID, exc)
            return {}

    def _assemble_factions(self) -> List[Dict[str, Any]]:
        """Build the list of the 6 canonical factions for the picker / overview.

        Each entry carries power (total control), territory (districts owned),
        relations (player standing), and traits (FACTION_TRAITS). ``treasury`` is
        omitted — the TerritoryManager has no treasury concept. Fully defensive:
        a failure in any single source degrades that field, never the list.

        Returns:
            List of 6 faction dicts.
        """
        out: List[Dict[str, Any]] = []
        for faction in CANONICAL_FACTIONS:
            out.append({
                "faction": faction,
                "power": self._faction_power(faction),
                "territory": self._dominant_districts(faction),
                "relations": self._faction_relation(faction),
                "traits": self._faction_traits(faction),
            })
        return out

    def _rank_for_power(self, power: float) -> str:
        """Map a power value to a rank label via config thresholds.

        Reads ``war_room.rank_thresholds`` (list of ``{min, rank}``, ascending).
        Returns the rank of the highest threshold whose ``min`` is ``<= power``.

        Args:
            power: A faction's total control value.

        Returns:
            The matching rank label (defaults to the lowest band's rank).
        """
        thresholds = self._cfg("rank_thresholds", _DEFAULT_RANK_THRESHOLDS)
        try:
            ordered = sorted(thresholds, key=lambda t: float(t.get("min", 0)))
        except Exception:
            ordered = _DEFAULT_RANK_THRESHOLDS
        rank = ordered[0].get("rank", "Unknown") if ordered else "Unknown"
        for entry in ordered:
            try:
                if power >= float(entry.get("min", 0)):
                    rank = str(entry.get("rank", rank))
            except Exception:
                continue
        return rank

    def _player_standings(self) -> Dict[str, int]:
        """Return the player's faction_standings map (defensive copy, {} on fail)."""
        try:
            return dict(self._player().faction_standings)
        except Exception as exc:
            logger.debug("[%s] standings unavailable (operation=standings): %s", SCENE_ID, exc)
            return {}

    def _my_crews(self) -> List[Dict[str, Any]]:
        """Return the player's crew members as dicts (defensive, [] on fail)."""
        try:
            members = self._crew().get_all_members()
        except Exception as exc:
            logger.debug("[%s] crew unavailable (operation=crews): %s", SCENE_ID, exc)
            return []
        out: List[Dict[str, Any]] = []
        for m in members or []:
            try:
                out.append(m.to_dict())
            except Exception:
                out.append({"character_id": getattr(m, "character_id", "?")})
        return out

    def _active_wars(self) -> Any:
        """Return active faction wars from FactionAI (defensive, {} on fail)."""
        try:
            return self._faction_ai().get_active_wars()
        except Exception as exc:
            logger.debug("[%s] active wars unavailable (operation=wars): %s", SCENE_ID, exc)
            return {}

    def _recent_decisions(self, limit: int = 20) -> List[Dict[str, Any]]:
        """Return recent FactionAI decisions (defensive, [] on fail)."""
        try:
            return self._faction_ai().get_history(limit=limit)
        except Exception as exc:
            logger.debug("[%s] decisions unavailable (operation=decisions): %s", SCENE_ID, exc)
            return []

    def _assemble_state(self) -> Dict[str, Any]:
        """Assemble the full live War Room dashboard state.

        Shape when an allegiance is set::

            {allegiance, my:{faction, power, territory, rank, crews, hq},
             rivals:[{faction, power, relation}], wars, recent_decisions,
             standings, clock}

        When no allegiance is set, returns ``{allegiance: null, factions: [...]}``
        (plus clock) so the UI shows the faction picker. Every sub-source is read
        defensively; a manager failure degrades that field rather than 500ing.

        Returns:
            The dashboard state dict.
        """
        try:
            allegiance = self._player().allegiance
        except Exception as exc:
            logger.debug("[%s] player state unavailable (operation=state): %s", SCENE_ID, exc)
            allegiance = None

        # No allegiance → picker payload.
        if not allegiance:
            return {
                "allegiance": None,
                "factions": self._assemble_factions(),
                "clock": self._read_clock(),
            }

        my_power = self._faction_power(allegiance)
        my_block: Dict[str, Any] = {
            "faction": allegiance,
            "power": my_power,
            "territory": self._dominant_districts(allegiance),
            "rank": self._rank_for_power(my_power),
            "crews": self._my_crews(),
        }
        hq = self._my_hq()
        if hq is not None:
            my_block["hq"] = hq

        rivals: List[Dict[str, Any]] = []
        for faction in CANONICAL_FACTIONS:
            if faction == allegiance:
                continue
            rivals.append({
                "faction": faction,
                "power": self._faction_power(faction),
                "relation": self._faction_relation(faction),
            })

        return {
            "allegiance": allegiance,
            "my": my_block,
            "rivals": rivals,
            "wars": self._active_wars(),
            "recent_decisions": self._recent_decisions(limit=20),
            "standings": self._player_standings(),
            "clock": self._read_clock(),
        }

    def _my_hq(self) -> Optional[Dict[str, Any]]:
        """Return the player's first crew HQ as a dict, or None.

        Crews are keyed by character_id in CrewManager / TerritoryManager. We
        surface the first crew member's HQ if one has been established. Fully
        defensive — returns ``None`` on any failure or when no HQ exists.
        """
        try:
            members = self._crew().get_all_members()
            terr = self._territory()
            for m in members or []:
                cid = getattr(m, "character_id", None)
                if not cid:
                    continue
                hq = terr.get_hq(cid)
                if hq is not None:
                    return hq.to_dict() if hasattr(hq, "to_dict") else hq
        except Exception as exc:
            logger.debug("[%s] hq lookup failed (operation=hq): %s", SCENE_ID, exc)
        return None

    # ── Routes ─────────────────────────────────────────────────────

    def _register_routes(self) -> None:
        """Register all Flask API routes."""
        app = self.app

        @app.route("/")
        def index():
            return render_template(
                "war_room.html",
                scene_data=self._get_scene_state(),
            )

        @app.route("/api/state")
        def get_state():
            return jsonify(self._get_scene_state())

        # v1.63.0 [2026-06-16] — C-T2: live faction dashboard endpoints
        @app.route("/api/warroom/factions")
        def warroom_factions():
            try:
                return jsonify({"factions": self._assemble_factions()})
            except Exception as exc:  # never 500
                logger.warning("[%s] factions endpoint failed (operation=api_factions): %s",
                               SCENE_ID, exc)
                return jsonify({"factions": [], "error": "unavailable"})

        @app.route("/api/warroom/state")
        def warroom_state():
            try:
                return jsonify(self._assemble_state())
            except Exception as exc:  # never 500
                logger.warning("[%s] state endpoint failed (operation=api_state): %s",
                               SCENE_ID, exc)
                return jsonify({"allegiance": None, "factions": [], "error": "unavailable"})

        @app.route("/api/warroom/allegiance", methods=["POST"])
        def warroom_allegiance():
            return jsonify(self._set_allegiance_from_request())

    def _set_allegiance_from_request(self) -> Dict[str, Any]:
        """Validate + persist a posted allegiance, then return the new state.

        Reads ``{faction}`` from the JSON body, validates against the 6 canonical
        factions, calls :meth:`PlayerState.set_allegiance`, refreshes FactionAI's
        player context so rivals react, and returns the freshly assembled state.
        Never raises — returns an ``{ok: False, error}`` payload on bad input.

        Returns:
            The new dashboard state (with ``ok: True``) or an error payload.
        """
        try:
            body = request.get_json(silent=True) or {}
        except Exception:
            body = {}
        faction = body.get("faction")
        if faction not in CANONICAL_FACTIONS:
            logger.info("[%s] rejected allegiance %r (operation=allegiance)", SCENE_ID, faction)
            return {
                "ok": False,
                "error": "invalid faction",
                "valid": CANONICAL_FACTIONS,
                "allegiance": self._safe_allegiance(),
            }
        try:
            ok = self._player().set_allegiance(faction)
        except Exception as exc:
            logger.warning("[%s] set_allegiance failed (operation=allegiance): %s", SCENE_ID, exc)
            return {"ok": False, "error": "persist failed", "allegiance": self._safe_allegiance()}

        # Let rivals react to the new allegiance (best-effort, read-only inputs).
        try:
            self._faction_ai().set_player_context(
                self._player_standings(),
                self._safe_active_location(),
            )
        except Exception as exc:
            logger.debug("[%s] set_player_context failed (operation=allegiance): %s", SCENE_ID, exc)

        logger.info("[%s] allegiance set to %s (operation=allegiance)", SCENE_ID, faction)
        state = self._assemble_state()
        state["ok"] = bool(ok)
        # Push the fresh state to all connected dashboards immediately.
        self._broadcast_update()
        return state

    def _safe_allegiance(self) -> Optional[str]:
        """Return the current allegiance, or None (defensive)."""
        try:
            return self._player().allegiance
        except Exception:
            return None

    def _safe_active_location(self) -> str:
        """Return the player's active_location, or '' (defensive)."""
        try:
            return str(self._player().active_location or "")
        except Exception:
            return ""

    def _setup_socketio_handlers(self) -> None:
        """Register Socket.IO event handlers."""
        sio = self.socketio

        @sio.on("connect")
        def on_connect():
            emit("state_update", self._get_scene_state())
            # v1.63.0 [2026-06-16] — C-T2: push current dashboard state on connect
            try:
                emit("warroom_update", self._assemble_state())
            except Exception as exc:  # never break the handshake
                logger.debug("[%s] connect push failed (operation=socket): %s", SCENE_ID, exc)

        # v1.63.0 [2026-06-16] — Clients can poll fresh state over the socket
        @sio.on("request_state")
        def on_request_state():
            emit("state_update", self._get_scene_state())

        # v1.63.0 [2026-06-16] — C-T2: clients can poll the live dashboard state
        @sio.on("request_warroom")
        def on_request_warroom():
            try:
                emit("warroom_update", self._assemble_state())
            except Exception as exc:
                logger.debug("[%s] request_warroom failed (operation=socket): %s", SCENE_ID, exc)

    # ── Live push (EventBus → warroom_update, throttled) ────────────

    def _subscribe_push_events(self) -> None:
        """Subscribe to the EventBus events that should refresh the dashboard.

        Wires ``living_world_tick`` / ``territory_shift`` / ``faction_decision``
        to a throttled ``warroom_update`` broadcast. Best-effort — a missing
        EventBus simply means no live push (REST/socket polling still work).
        """
        try:
            from engine.events.event_bus import get_event_bus  # noqa: PLC0415
            bus = get_event_bus()
        except Exception as exc:
            logger.debug("[%s] EventBus unavailable (operation=subscribe): %s", SCENE_ID, exc)
            return
        for event_type in _PUSH_EVENTS:
            try:
                sid = bus.subscribe(event_type, self._on_world_event, SCENE_ID)
                self._sub_ids.append(sid)
            except Exception as exc:
                logger.debug("[%s] subscribe failed (operation=subscribe, event=%s): %s",
                             SCENE_ID, event_type, exc)
        logger.info("[%s] subscribed to %d live events (operation=subscribe)",
                    SCENE_ID, len(self._sub_ids))

    def _unsubscribe_push_events(self) -> None:
        """Remove all EventBus subscriptions registered by this scene."""
        try:
            from engine.events.event_bus import get_event_bus  # noqa: PLC0415
            bus = get_event_bus()
        except Exception:
            self._sub_ids = []
            return
        for sid in self._sub_ids:
            try:
                bus.unsubscribe(sid)
            except Exception as exc:
                logger.debug("[%s] unsubscribe failed (operation=unsubscribe): %s", SCENE_ID, exc)
        self._sub_ids = []

    def _on_world_event(self, event: Dict[str, Any]) -> None:
        """EventBus handler — broadcast a throttled fresh dashboard state.

        Args:
            event: The full EventBus event record (unused beyond triggering).
        """
        self._broadcast_update()

    def _broadcast_update(self) -> None:
        """Emit a fresh ``warroom_update`` to all clients, throttled to ~2s.

        Reads ``war_room.push_throttle_secs`` (default 2.0). Never raises — a
        socket/emit failure is logged at debug and swallowed.
        """
        now = time.time()
        throttle = float(self._cfg("push_throttle_secs", 2.0))
        if now - self._last_push < throttle:
            return
        self._last_push = now
        try:
            self.socketio.emit("warroom_update", self._assemble_state())
        except Exception as exc:
            logger.debug("[%s] broadcast failed (operation=broadcast): %s", SCENE_ID, exc)

    # ── State ──────────────────────────────────────────────────────

    def _get_scene_state(self) -> Dict[str, Any]:
        """Return the scene state for the template + future command center.

        C-T1 returns a stub (scene identity + live game clock). The faction /
        crew / territory layers populate this in later v1.63 tasks. All lookups
        degrade gracefully — the scaffold must boot even when the world/config
        subsystems are offline.
        """
        state: Dict[str, Any] = {
            "scene": SCENE_ID,
            "display_name": self.SCENE_METADATA["display_name"],
            "status": "booting",
            "accent_color": self.SCENE_METADATA["accent_color"],
            "version": self.SCENE_METADATA["version"],
        }
        state["clock"] = self._read_clock()
        return state

    def _read_clock(self) -> Dict[str, Any]:
        """Return the current in-game clock (falls back to a static label)."""
        try:
            from engine.world.world_state import get_world_state  # noqa: PLC0415
            wt = get_world_state().get_time()
            return {
                "game_hour": wt.game_hour,
                "game_day": wt.game_day,
                "game_day_name": wt.game_day_name,
                "time_of_day": wt.time_of_day,
                "display": wt.to_display(),
            }
        except Exception as exc:  # WorldState optional — never block boot
            logger.debug("[%s] clock unavailable (operation=state): %s", SCENE_ID, exc)
            return {
                "game_hour": 0,
                "game_day": 0,
                "game_day_name": "Mon",
                "time_of_day": "night",
                "display": "",
            }

    # ──── FlaskScene Lifecycle Hooks ─────────────────────────────
    # v1.63.0 [2026-06-16] — FlaskScene handles start()/stop(); use hooks

    def on_before_serve(self) -> None:
        """Subclass hook — wire the live dashboard push to the EventBus."""
        self._subscribe_push_events()
        logger.info("[%s] command center online (operation=lifecycle)", SCENE_ID)

    def on_shutdown(self) -> None:
        """Subclass hook — tear down EventBus subscriptions."""
        self._unsubscribe_push_events()
        logger.info("[%s] Scene stopping (operation=lifecycle)", SCENE_ID)
