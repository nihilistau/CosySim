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
    v1.63.0 [2026-06-16] — C-T4: live faction commands. ``POST
                            /api/warroom/command {cmd, ...}`` dispatches
                            contest / assign_op / recruit / build_hq /
                            upgrade_room / diplomacy to the existing
                            TerritoryManager / CrewManager / FactionManager /
                            FactionAI managers (the scene only orchestrates).
                            Adds ``GET /api/warroom/op_preview`` for the strike
                            success-chance preview. Each successful command
                            re-broadcasts a fresh ``warroom_update``. Every
                            handler is defensively wrapped — never 500s.

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
        """Return the player's standing with *faction*.

        Prefers :class:`PlayerState.faction_standings` — the single source of
        truth that carries all 6 canonical factions and is what the diplomacy
        command writes to (so a declared war / alliance flips here immediately).
        Falls back to :class:`FactionManager` (scene factions) and finally 0
        (neutral). Read-only, never raises.

        Args:
            faction: Canonical faction name.

        Returns:
            Player standing (-100..100), or 0.
        """
        # v1.63.0 [2026-06-16] — C-T4: PlayerState standings are authoritative for
        # the 6 canonical factions and reflect diplomacy commands directly.
        try:
            standings = self._player().faction_standings
            if faction in standings:
                return int(standings.get(faction, 0) or 0)
        except Exception as exc:
            logger.debug("[%s] player standings lookup failed (operation=relation, faction=%s): %s",
                         SCENE_ID, faction, exc)
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

        # v1.63.0 [2026-06-16] — C-T4: the live command endpoint. One POST,
        # ``{cmd, ...}``, dispatched to the existing managers. Never 500s.
        @app.route("/api/warroom/command", methods=["POST"])
        def warroom_command():
            return jsonify(self._dispatch_command_from_request())

        # v1.63.0 [2026-06-16] — C-T4: success-chance preview for Order Strike.
        @app.route("/api/warroom/op_preview")
        def warroom_op_preview():
            op_type = request.args.get("op_type", "")
            crew_raw = request.args.get("crew", "")
            crew = [c for c in crew_raw.split(",") if c]
            return jsonify(self._op_preview(op_type, crew))

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

    # ──── C-T4 · Faction commands (dispatch → existing managers) ─────
    # v1.63.0 [2026-06-16] — The War Room commands. Each handler reuses an
    # existing engine manager (TerritoryManager / CrewManager / FactionManager /
    # FactionAI) — the scene only orchestrates. Every command is wrapped so a
    # manager failure becomes a clean ``{ok: False, error}`` payload, never a 500.

    def _player_faction(self) -> Optional[str]:
        """Return the player's faction (= allegiance), or None.

        The faction every command acts on. ``None`` means the player hasn't
        pledged yet — commands short-circuit with ``{ok: False, reason}``.
        """
        return self._safe_allegiance()

    def _dispatch_command_from_request(self) -> Dict[str, Any]:
        """Read a ``{cmd, ...}`` body and dispatch to the matching handler.

        Validates the player has an allegiance (the faction every command acts
        for), routes ``cmd`` to its handler, and on success attaches a freshly
        assembled state and broadcasts a ``warroom_update``. Fully defensive —
        any handler exception degrades to ``{ok: False, error}``.

        Returns:
            The command result dict (always carries an ``ok`` flag).
        """
        try:
            body = request.get_json(silent=True) or {}
        except Exception:
            body = {}
        cmd = str(body.get("cmd", "")).strip()

        faction = self._player_faction()
        if not faction:
            logger.info("[%s] command %r blocked — no allegiance (operation=command)", SCENE_ID, cmd)
            return {"ok": False, "reason": "no allegiance", "cmd": cmd}

        handlers = {
            "contest": self._cmd_contest,
            "assign_op": self._cmd_assign_op,
            "recruit": self._cmd_recruit,
            "build_hq": self._cmd_build_hq,
            "upgrade_room": self._cmd_upgrade_room,
            "diplomacy": self._cmd_diplomacy,
        }
        handler = handlers.get(cmd)
        if handler is None:
            return {"ok": False, "error": f"unknown command '{cmd}'", "cmd": cmd}

        try:
            result = handler(faction, body)
        except Exception as exc:  # never 500 — defensive shell around every handler
            logger.warning("[%s] command %s failed (operation=command): %s", SCENE_ID, cmd, exc)
            return {"ok": False, "error": "command failed", "cmd": cmd}

        result.setdefault("cmd", cmd)
        if result.get("ok"):
            # Push fresh state + log the world-mutating success.
            result["state"] = self._assemble_state()
            self._broadcast_update()
            logger.info("[%s] command %s ok (operation=command, faction=%s)",
                        SCENE_ID, cmd, faction)
        return result

    def _cmd_contest(self, faction: str, body: Dict[str, Any]) -> Dict[str, Any]:
        """Claim/contest a district — shift control toward the player's faction.

        Reuses :meth:`TerritoryManager.shift_control` with a config-driven delta
        clamped to ``CONTROL_SHIFT_RANGE``, attributing the move to the player's
        faction (``source_faction=faction`` so it pulls from the dominant rival's
        share is handled by the manager).

        Args:
            faction: The player's faction (gains control).
            body: Command body; expects ``{district}``.

        Returns:
            ``{ok, district, control, delta}`` or ``{ok: False, error}``.
        """
        from engine.world.territory import CONTROL_SHIFT_RANGE, DISTRICT_NAMES  # noqa: PLC0415

        district = str(body.get("district", "")).strip().upper()
        if district not in DISTRICT_NAMES:
            return {"ok": False, "error": "invalid district", "valid": DISTRICT_NAMES}

        lo, hi = CONTROL_SHIFT_RANGE
        delta = float(self._cfg("contest_delta", 5.0))
        delta = max(lo, min(hi, delta))

        terr = self._territory()
        event = terr.shift_control(district, faction, delta, reason="war_room", source_faction=None)
        control = terr.get_district_control(district)
        applied = getattr(event, "delta", delta)
        logger.info("[%s] contest %s for %s %+.1f (operation=command)",
                    SCENE_ID, district, faction, applied)
        return {
            "ok": True,
            "district": district,
            "delta": round(float(applied), 2),
            "control": control,
            "your_control": round(float(control.get(faction, 0.0)), 2),
            "message": f"{faction} pressed into {district} ({applied:+.1f}%).",
        }

    def _op_preview(self, op_type: str, crew: List[str]) -> Dict[str, Any]:
        """Return the success-chance preview for an op_type + crew (no side effects).

        Args:
            op_type: Operation type key (see crew.OPERATION_TYPES).
            crew: character_ids assigned.

        Returns:
            ``{ok, op_type, crew, chance, percent}`` (defensive defaults on fail).
        """
        from engine.world.crew import OPERATION_TYPES  # noqa: PLC0415

        if op_type not in OPERATION_TYPES:
            return {"ok": False, "error": "invalid op_type",
                    "valid": sorted(OPERATION_TYPES.keys())}
        try:
            mgr = self._crew()
            chance = mgr.preview_success_chance(op_type, crew)
        except Exception as exc:
            logger.debug("[%s] op preview failed (operation=op_preview): %s", SCENE_ID, exc)
            return {"ok": False, "error": "preview unavailable", "op_type": op_type}
        min_crew = int(OPERATION_TYPES[op_type].get("min_crew", 1))
        return {
            "ok": True,
            "op_type": op_type,
            "crew": list(crew),
            "chance": round(float(chance), 4),
            "percent": round(float(chance) * 100, 1),
            "min_crew": min_crew,
            "enough_crew": len(crew) >= min_crew,
        }

    def _cmd_assign_op(self, faction: str, body: Dict[str, Any]) -> Dict[str, Any]:
        """Order a crew operation (Order Strike).

        Computes the success-chance preview via
        :meth:`CrewManager.compute_success_chance`, then launches the op through
        :meth:`CrewManager.start_operation` (which honours min-crew + availability
        gates and records the odds). Rewards/duration come from config.

        Args:
            faction: The player's faction (unused by CrewManager but logged).
            body: ``{op_type, crew:[ids], label?}``.

        Returns:
            ``{ok, started, message, preview, ...}`` or a clean gated failure.
        """
        from engine.world.crew import OPERATION_TYPES  # noqa: PLC0415

        op_type = str(body.get("op_type", "")).strip()
        crew = body.get("crew") or []
        if not isinstance(crew, list):
            crew = [crew]
        crew = [str(c) for c in crew if c]

        if op_type not in OPERATION_TYPES:
            return {"ok": False, "error": "invalid op_type",
                    "valid": sorted(OPERATION_TYPES.keys())}

        mgr = self._crew()
        preview = self._op_preview(op_type, crew)

        started, message = mgr.start_operation(
            op_type,
            crew,
            label=str(body.get("label", "")) or "",
            duration_secs=float(self._cfg("op_duration_secs", 1800)),
            reward_credits=int(self._cfg("op_reward_credits", 1500)),
            reward_xp=int(self._cfg("op_reward_xp", 40)),
        )
        if not started:
            # Gated (too few crew / unavailable) — clean message, not an error 500.
            return {"ok": False, "error": message, "op_type": op_type, "preview": preview}

        logger.info("[%s] assign_op %s crew=%d (operation=command, faction=%s)",
                    SCENE_ID, op_type, len(crew), faction)
        return {
            "ok": True,
            "started": True,
            "op_type": op_type,
            "crew": crew,
            "preview": preview,
            "message": message,
        }

    def _cmd_recruit(self, faction: str, body: Dict[str, Any]) -> Dict[str, Any]:
        """Recruit a candidate into the crew (honours the can_recruit gate).

        Args:
            faction: The player's faction (logged).
            body: ``{character_id, role?}``.

        Returns:
            ``{ok, message, character_id}`` or a clean gated failure.
        """
        character_id = str(body.get("character_id", "")).strip()
        if not character_id:
            return {"ok": False, "error": "character_id required"}
        role = str(body.get("role", "")).strip() or "unknown"

        mgr = self._crew()
        ok, message = mgr.recruit(character_id, role=role)
        logger.info("[%s] recruit %s as %s → %s (operation=command, faction=%s)",
                    SCENE_ID, character_id, role, ok, faction)
        return {
            "ok": bool(ok),
            "character_id": character_id,
            "role": role,
            "message": message,
            **({} if ok else {"error": message}),
        }

    def _crew_id_for(self, faction: str, body: Dict[str, Any]) -> str:
        """Resolve the crew_id for HQ commands (body override → first crew → faction).

        Crews/HQs are keyed by an id in TerritoryManager. We prefer an explicit
        ``crew_id`` in the body, else the first crew member's id, else fall back
        to the faction name so the player always has a valid HQ owner.
        """
        explicit = str(body.get("crew_id", "")).strip()
        if explicit:
            return explicit
        try:
            members = self._crew().get_all_members()
            for m in members or []:
                cid = getattr(m, "character_id", None)
                if cid:
                    return str(cid)
        except Exception as exc:
            logger.debug("[%s] crew_id resolve failed (operation=command): %s", SCENE_ID, exc)
        return faction

    def _cmd_build_hq(self, faction: str, body: Dict[str, Any]) -> Dict[str, Any]:
        """Establish a crew HQ in a district.

        Reuses :meth:`TerritoryManager.establish_hq`. The HQ owner (crew_id)
        defaults to the player's first crew member, falling back to the faction.

        Args:
            faction: The player's faction (HQ owner fallback).
            body: ``{district, crew_id?}``.

        Returns:
            ``{ok, hq, district, crew_id}`` or ``{ok: False, error}``.
        """
        from engine.world.territory import DISTRICT_NAMES  # noqa: PLC0415

        district = str(body.get("district", "")).strip().upper()
        if district not in DISTRICT_NAMES:
            return {"ok": False, "error": "invalid district", "valid": DISTRICT_NAMES}

        crew_id = self._crew_id_for(faction, body)
        hq = self._territory().establish_hq(district, crew_id)
        hq_dict = hq.to_dict() if hasattr(hq, "to_dict") else hq
        logger.info("[%s] build_hq %s for %s (operation=command, faction=%s)",
                    SCENE_ID, district, crew_id, faction)
        return {
            "ok": True,
            "district": district,
            "crew_id": crew_id,
            "hq": hq_dict,
            "message": f"HQ established in {district}.",
        }

    def _cmd_upgrade_room(self, faction: str, body: Dict[str, Any]) -> Dict[str, Any]:
        """Build or upgrade an HQ room.

        Reuses :meth:`TerritoryManager.build_room` (first build) /
        :meth:`upgrade_room` (subsequent levels). Tries build first; if the room
        already exists, falls through to an upgrade.

        Args:
            faction: The player's faction (HQ owner fallback).
            body: ``{room_type, crew_id?}``.

        Returns:
            ``{ok, action, room_type, hq}`` or a clean gated failure.
        """
        from engine.world.territory import HQ_ROOM_TYPES  # noqa: PLC0415

        room_type = str(body.get("room_type", "")).strip().lower()
        if room_type not in HQ_ROOM_TYPES:
            return {"ok": False, "error": "invalid room_type",
                    "valid": sorted(HQ_ROOM_TYPES.keys())}

        crew_id = self._crew_id_for(faction, body)
        terr = self._territory()
        if terr.get_hq(crew_id) is None:
            return {"ok": False, "error": "no HQ — build one first", "crew_id": crew_id}

        built = terr.build_room(crew_id, room_type)
        action = "built"
        if not built:
            upgraded = terr.upgrade_room(crew_id, room_type)
            if not upgraded:
                return {"ok": False, "error": "room maxed or unavailable",
                        "room_type": room_type, "crew_id": crew_id}
            action = "upgraded"

        hq = terr.get_hq(crew_id)
        hq_dict = hq.to_dict() if (hq and hasattr(hq, "to_dict")) else None
        logger.info("[%s] %s room %s for %s (operation=command, faction=%s)",
                    SCENE_ID, action, room_type, crew_id, faction)
        return {
            "ok": True,
            "action": action,
            "room_type": room_type,
            "crew_id": crew_id,
            "hq": hq_dict,
            "message": f"{room_type.title()} {action}.",
        }

    # Map canonical faction names → faction_politics scene ids (where they exist).
    # v1.63.0 [2026-06-16] — C-T4: the neoncity scene registers 3 of the 6.
    _FACTION_MGR_IDS: Dict[str, str] = {
        "OmniCorp": "omnicorp",
        "Ghost_Net": "ghost_net",
        "SynthSec": "synthsec",
    }

    def _cmd_diplomacy(self, faction: str, body: Dict[str, Any]) -> Dict[str, Any]:
        """Set the player's relation with a rival faction (ally / war / neutral).

        Writes the new standing to :class:`PlayerState` (the authoritative source
        for all 6 canonical factions, and what the dashboard's rival relation +
        ``standings`` read) and best-effort mirrors it into
        :meth:`FactionManager.modify_standing` (scene factions, with cascade) so
        the wider political sim reacts. Refreshes FactionAI's player context so
        rivals respond on later ticks.

        Args:
            faction: The player's faction (the actor).
            body: ``{target_faction, kind}`` where kind ∈ {ally, war, neutral}.

        Returns:
            ``{ok, target_faction, kind, relation, standing}`` or an error.
        """
        target = str(body.get("target_faction", "")).strip()
        kind = str(body.get("kind", "")).strip().lower()
        if target not in CANONICAL_FACTIONS:
            return {"ok": False, "error": "invalid target_faction", "valid": CANONICAL_FACTIONS}
        if target == faction:
            return {"ok": False, "error": "cannot set diplomacy with your own faction"}
        if kind not in ("ally", "war", "neutral"):
            return {"ok": False, "error": "kind must be ally|war|neutral"}

        cfg_key = {"ally": "ally_standing", "war": "war_standing",
                   "neutral": "neutral_standing"}[kind]
        cfg_default = {"ally": 60, "war": -80, "neutral": 0}[kind]
        target_standing = int(self._cfg("diplomacy." + cfg_key, cfg_default))
        cascade = bool(self._cfg("diplomacy.cascade", True))

        # 1) Authoritative: set PlayerState standing absolutely to the target.
        ps = self._player()
        try:
            current = int(ps.faction_standings.get(target, 0))
        except Exception:
            current = 0
        new_standing = current
        try:
            new_standing = ps.update_faction_standing(target, target_standing - current)
        except Exception as exc:
            logger.warning("[%s] diplomacy standing write failed (operation=command): %s",
                           SCENE_ID, exc)
            return {"ok": False, "error": "standing write failed", "target_faction": target}

        # 2) Best-effort: mirror into FactionManager (scene faction sim, cascades).
        mgr_id = self._FACTION_MGR_IDS.get(target)
        if mgr_id:
            try:
                self._faction_mgr().modify_standing(mgr_id, target_standing - current, cascade=cascade)
            except Exception as exc:
                logger.debug("[%s] FactionManager mirror failed (operation=command): %s", SCENE_ID, exc)

        # 3) Declaring war → register an active war so FactionAI / the map react.
        if kind == "war":
            try:
                district = self._first_held_or_default(faction)
                fai = self._faction_ai()
                war_map = getattr(fai, "_war_active", None)
                if isinstance(war_map, dict):
                    war_map[district] = {"attacker": faction, "defender": target}
            except Exception as exc:
                logger.debug("[%s] war registration failed (operation=command): %s", SCENE_ID, exc)
        elif kind in ("ally", "neutral"):
            # Stand down any war the player is running in their own districts.
            try:
                fai = self._faction_ai()
                war_map = getattr(fai, "_war_active", {})
                for d in [k for k, v in dict(war_map).items()
                          if isinstance(v, dict) and v.get("defender") == target]:
                    fai.end_war(d)
            except Exception as exc:
                logger.debug("[%s] war stand-down failed (operation=command): %s", SCENE_ID, exc)

        # 4) Refresh FactionAI player context so rivals react on later ticks.
        try:
            self._faction_ai().set_player_context(self._player_standings(), self._safe_active_location())
        except Exception as exc:
            logger.debug("[%s] set_player_context failed (operation=command): %s", SCENE_ID, exc)

        relation_label = "ally" if new_standing >= 25 else "war" if new_standing <= -25 else "neutral"
        logger.info("[%s] diplomacy %s → %s (kind=%s, standing=%d) (operation=command, faction=%s)",
                    SCENE_ID, target, relation_label, kind, new_standing, faction)
        return {
            "ok": True,
            "target_faction": target,
            "kind": kind,
            "relation": relation_label,
            "standing": int(new_standing),
            "message": f"{faction} now {relation_label} with {target}.",
        }

    def _first_held_or_default(self, faction: str) -> str:
        """Return a district the faction dominates, else the first canonical one.

        Used to anchor a declared war to a concrete district (FactionAI tracks
        wars per district). Never raises.
        """
        from engine.world.territory import DISTRICT_NAMES  # noqa: PLC0415
        held = self._dominant_districts(faction)
        if held:
            return held[0]
        return DISTRICT_NAMES[0]

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
