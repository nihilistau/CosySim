"""The Sprawl — the living city map scene.
============================================

A real-time map of NEONCITY: watch the city move, walk its streets and change
its fate. Territory contests, NPC movement and the player's avatar render on a
live map fed by the engine's :class:`LivingWorld` simulation.

B-T1 shipped the SCAFFOLD: a bootable placeholder scene serving a neon page and
a stub ``/api/state`` endpoint. B-T2 (this revision) wires the scene to the
LIVE world: read-only ``GET /api/sprawl/state`` and ``GET /api/sprawl/events``
endpoints sourced from the EXISTING managers, plus a Socket.IO push that emits
fresh state on every ``living_world_tick`` (throttled) and individual
``sprawl_event``s on ``emergent_action`` / ``territory_shift``.

Reuse-first / read-only
-----------------------
The scene OWNS NO WORLD STATE. It composes the existing singletons:
:class:`~engine.world.territory.TerritoryManager` (district control + faction
ranking + territory events), :class:`~engine.world.npc_routines.RoutineManager`
(NPC location/activity), :class:`~content.simulation.database.db.Database`
(canonical NPC faction via ``metadata.faction``),
:class:`~engine.world.emergent.store.EmergentStore` (agency event feed),
:class:`~engine.world.player_state.PlayerState` (player credits/heat/location),
and the :class:`~engine.events.event_bus.EventBus` for live push. Every source
is read through a small private seam (``_territory`` / ``_routine`` / etc.) so
tests can inject fakes and so a failing source degrades to a safe default — the
endpoints must NEVER 500.

RoutineManager reports SCENE names; the canonical district is resolved by
reversing :data:`engine.world.territory.DISTRICT_SCENES`.

Version: v1.63.0 [2026-06-15]
Author:  CosySim Team

Change Log:
    v1.63.0 [2026-06-15] — Initial scaffold (B-T1): bootable placeholder scene,
                            registered for launcher/TUI/hub + auto-start
    v1.63.0 [2026-06-15] — Live data backend (B-T2): _build_state assembled from
                            the existing managers; GET /api/sprawl/state +
                            GET /api/sprawl/events?since=; EventBus subscription
                            pushing sprawl_update (throttled) + sprawl_event;
                            per-source defensive (never 500).

CONNECTS: FlaskScene, SocketIO, TerritoryManager, RoutineManager, Database,
          EmergentStore, PlayerState, EventBus, get_config
CALLED BY: launcher.py, TUI, hub
EMITS: state_update, sprawl_update, sprawl_event Socket.IO events
"""
from __future__ import annotations

import logging
import time
from typing import Any, Dict, List, Optional, Tuple

from flask import jsonify, render_template, request
from flask_socketio import emit

from engine.scenes.flask_scene import FlaskScene

logger = logging.getLogger(__name__)

SCENE_ID = "the_sprawl"
# v1.63.0 [2026-06-15] — Structured logging context (SCENE_ID prefix + operation tags)

# v1.63.0 [2026-06-15] — EventBus event names published by the running stack.
_EVT_TICK = "living_world_tick"        # LivingWorld.tick → result.to_dict()
_EVT_ACTION = "emergent_action"        # EmergentAgency → {npc_id,verb,target,ok,...}
_EVT_TERRITORY = "territory_shift"     # TerritoryManager → TerritoryEvent.to_dict()


# ──── Scene Implementation ────────────────────────────────────

# v1.63.0 [2026-06-15] — Living-city map scaffold on FlaskScene base
class TheSprawlScene(FlaskScene):
    """The Sprawl: a live map of NEONCITY (the living city).

    Serves a full-screen neon city map — territory, NPCs and the player's
    avatar. B-T1 ships the bootable scaffold; the live map renders against the
    engine :class:`LivingWorld` simulation in later v1.63 tasks.

    CONNECTS: FlaskScene, SocketIO, WorldState, get_config
    CALLED BY: launcher.py, TUI, hub
    EMITS: state_update Socket.IO event
    """

    SCENE_METADATA = {
        "name": "the_sprawl",
        "display_name": "THE SPRAWL",
        "port": 5597,
        "type": "game",
        "accent_color": "#39ff14",
        "description": "The living city — watch it move, walk its streets, change its fate.",
        "version": "1.0.0",
    }

    def __init__(self, config: Optional[Dict[str, Any]] = None,
                 host: str = "0.0.0.0") -> None:
        super().__init__(host=host, port=self.SCENE_METADATA["port"])
        self.config = config or {}

        # Scene-specific secret key
        self.app.config["SECRET_KEY"] = "the-sprawl-scene"

        # v1.63.0 [2026-06-15] — EventBus subscription ids (unsubscribed on shutdown)
        self._sub_ids: List[str] = []
        # Throttle: last time we pushed a full sprawl_update from a tick.
        self._last_push_ts: float = 0.0
        # Cached scene→district reverse map (built lazily, defensively).
        self._scene_to_district: Optional[Dict[str, str]] = None

        # Scene-specific route registrations
        self.register_bench_route(self.app, self.socketio)
        self._register_routes()
        self._setup_socketio_handlers()

    # ── Config ─────────────────────────────────────────────────────

    def _cfg(self, key: str, default: Any) -> Any:
        """Return a ``the_sprawl.*`` knob from config with a built-in default.

        Args:
            key: Short key under ``the_sprawl.`` (e.g. ``"push_throttle_s"``).
            default: Fallback when config is unavailable or the key is unset.

        Returns:
            The configured value, or ``default`` (never raises).
        """
        try:
            from engine.config import get_config  # noqa: PLC0415
            return get_config().get("the_sprawl." + key, default)
        except Exception as exc:  # config optional in minimal builds
            logger.debug("[%s] config lookup failed (operation=cfg, key=%s): %s",
                         SCENE_ID, key, exc)
            return default

    # ── Routes ─────────────────────────────────────────────────────

    def _register_routes(self) -> None:
        """Register all Flask API routes."""
        app = self.app

        @app.route("/")
        def index():
            return render_template(
                "the_sprawl.html",
                scene_data=self._get_scene_state(),
            )

        @app.route("/api/state")
        def get_state():
            return jsonify(self._get_scene_state())

        # v1.63.0 [2026-06-15] — Live world-state read endpoint (B-T2)
        @app.route("/api/sprawl/state")
        def get_sprawl_state():
            return jsonify(self._build_state())

        # v1.63.0 [2026-06-15] — Live merged event feed (B-T2)
        @app.route("/api/sprawl/events")
        def get_sprawl_events():
            since = self._parse_since(request.args.get("since"))
            return jsonify({"events": self._merged_events(since=since), "since": since})

    def _setup_socketio_handlers(self) -> None:
        """Register Socket.IO event handlers."""
        sio = self.socketio

        @sio.on("connect")
        def on_connect():
            emit("state_update", self._get_scene_state())
            # v1.63.0 [2026-06-15] — Push the current live world-state on connect.
            emit("sprawl_update", self._build_state())

        # v1.63.0 [2026-06-15] — Clients can poll fresh state over the socket
        @sio.on("request_state")
        def on_request_state():
            emit("state_update", self._get_scene_state())
            emit("sprawl_update", self._build_state())

    # ── State ──────────────────────────────────────────────────────

    def _get_scene_state(self) -> Dict[str, Any]:
        """Return the scene state for the template + future live map.

        B-T1 returns a stub (scene identity + live game clock). The live
        territory / NPC / avatar layers populate this in later v1.63 tasks.
        All lookups degrade gracefully — the scaffold must boot even when the
        world/config subsystems are offline.
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

    # ──── Manager seams (read-only; injectable for tests) ────────────
    # v1.63.0 [2026-06-15] — Each source behind a tiny seam so a failing
    # source degrades to a safe default and tests can monkeypatch it.

    def _territory(self):
        """Return the singleton TerritoryManager (read-only world territory)."""
        from engine.world.territory import get_territory_manager  # noqa: PLC0415
        return get_territory_manager()

    def _routine(self):
        """Return the singleton RoutineManager (read-only NPC locations)."""
        from engine.world.npc_routines import get_routine_manager  # noqa: PLC0415
        return get_routine_manager()

    def _characters(self) -> List[Dict[str, Any]]:
        """Return all character rows (id/name/sex/tags/metadata)."""
        from content.simulation.database.db import Database  # noqa: PLC0415
        return Database().get_all_characters()

    def _emergent_store(self):
        """Return the singleton EmergentStore (read-only agency event feed)."""
        from engine.world.emergent.store import get_emergent_store  # noqa: PLC0415
        return get_emergent_store()

    def _player(self) -> Dict[str, Any]:
        """Return the player's location/credits/heat (read-only)."""
        from engine.world.player_state import get_player_state  # noqa: PLC0415
        ps = get_player_state()
        return {
            "location": ps.active_location,
            "credits": ps.credits,
            "heat": ps.heat,
        }

    # ──── Live world-state assembly (B-T2) ───────────────────────────

    def _build_state(self) -> Dict[str, Any]:
        """Assemble the live world-state from the existing managers.

        Composes — defensively, per source — district control + dominant +
        contested flags (TerritoryManager), the faction power ranking, the
        registered NPCs with their canonical faction (Database metadata) and
        canonical district (RoutineManager scene → district), and the player
        block (PlayerState). A failure in any one source yields that source's
        safe empty/default; the whole call NEVER raises.

        Returns:
            ``{districts, factions, npcs, player, ts}`` ready for JSON / socket.
        """
        contest_margin = float(self._cfg("contest_margin", 10.0))

        districts = self._build_districts(contest_margin)
        factions = self._build_factions()
        npcs = self._build_npcs()
        player = self._build_player()

        return {
            "districts": districts,
            "factions": factions,
            "npcs": npcs,
            "player": player,
            "ts": time.time(),
        }

    def _build_districts(self, contest_margin: float) -> List[Dict[str, Any]]:
        """Build the per-district control/dominant/contested list (defensive).

        Args:
            contest_margin: A district is ``contested`` when the dominant
                faction leads the runner-up by less than this many points.

        Returns:
            List of ``{id, control, dominant, contested}`` (empty on failure).
        """
        out: List[Dict[str, Any]] = []
        try:
            mgr = self._territory()
            all_control = mgr.get_all_control()
            for district, control in all_control.items():
                ctrl = {f: round(float(p), 2) for f, p in (control or {}).items()}
                try:
                    dom_f, dom_p = mgr.get_dominant_faction(district)
                    dominant = [dom_f, round(float(dom_p), 2)]
                except Exception:
                    dominant = ["none", 0.0]
                # Contested when the lead over the runner-up is small.
                ranked = sorted(ctrl.values(), reverse=True)
                lead = (ranked[0] - ranked[1]) if len(ranked) >= 2 else (
                    ranked[0] if ranked else 0.0)
                contested = bool(ranked) and lead < contest_margin
                out.append({
                    "id": district,
                    "control": ctrl,
                    "dominant": dominant,
                    "contested": contested,
                })
        except Exception as exc:
            logger.error("[%s] districts unavailable (operation=build_state): %s",
                         SCENE_ID, exc)
            return []
        return out

    def _build_factions(self) -> List[Dict[str, Any]]:
        """Build the faction power ranking list (defensive).

        Returns:
            List of ``{faction, total}`` newest-strongest-first (empty on fail).
        """
        try:
            ranking = self._territory().get_faction_ranking()
            return [{"faction": f, "total": round(float(t), 2)} for f, t in ranking]
        except Exception as exc:
            logger.error("[%s] faction ranking unavailable (operation=build_state): %s",
                         SCENE_ID, exc)
            return []

    def _build_npcs(self) -> List[Dict[str, Any]]:
        """Build the NPC list with canonical faction + district (defensive).

        The roster is the UNION of the live RoutineManager (whoever is
        registered in *this* process) and the persisted character DB (the
        durable source of truth — generated + cast NPCs carry
        ``metadata.faction``). This matters because the RoutineManager singleton
        is per-process: when the scene boots alongside (not inside) the world
        process its routine table is empty, so the DB roster is what surfaces
        the real population. Live location/activity from RoutineManager is
        overlaid when present; otherwise the district falls back to the NPC's
        archetype home district. Defensive per source — a failing source simply
        contributes nothing.

        Returns:
            List of ``{id, name, sex, faction, district, activity}``.
        """
        # Index character rows by id for name/sex/faction/archetype lookup.
        char_by_id: Dict[str, Dict[str, Any]] = {}
        try:
            for ch in self._characters():
                cid = ch.get("id")
                if cid is not None:
                    char_by_id[str(cid)] = ch
        except Exception as exc:
            logger.error("[%s] character rows unavailable (operation=build_state): %s",
                         SCENE_ID, exc)

        # Live routine roster (per-process; may be empty when booted alongside).
        rm = None
        routine_ids: List[str] = []
        try:
            rm = self._routine()
            routine_ids = [str(i) for i in rm.list_npcs()]
        except Exception as exc:
            logger.error("[%s] routine roster unavailable (operation=build_state): %s",
                         SCENE_ID, exc)

        # Union, preserving routine order first then any DB-only NPCs.
        seen: set = set()
        ordered_ids: List[str] = []
        for nid in routine_ids + list(char_by_id.keys()):
            if nid not in seen:
                seen.add(nid)
                ordered_ids.append(nid)

        out: List[Dict[str, Any]] = []
        for npc_id in ordered_ids:
            loc: Dict[str, Any] = {}
            if rm is not None:
                try:
                    loc = rm.get_npc_location(npc_id) or {}
                except Exception:
                    loc = {}
            ch = char_by_id.get(npc_id, {})
            meta = ch.get("metadata") if isinstance(ch.get("metadata"), dict) else {}
            faction = meta.get("faction") if isinstance(meta, dict) else None

            scene_loc = loc.get("location", "")
            district = self._district_for_scene(scene_loc)
            if district == "unknown":
                # Fall back to the archetype's canonical home district.
                district = self._home_district_for(ch)

            out.append({
                "id": npc_id,
                "name": ch.get("name", npc_id),
                "sex": ch.get("sex", ""),
                "faction": faction,
                "district": district,
                "activity": loc.get("activity", ""),
            })
        return out

    @staticmethod
    def _home_district_for(char: Dict[str, Any]) -> str:
        """Resolve an NPC's canonical home district from its archetype tags.

        Reuses :data:`engine.world.character_gen.ARCHETYPE_DISTRICT`. Falls back
        to ``"unknown"`` when no archetype tag is present or the map is
        unavailable.

        Args:
            char: A character DB row (``tags`` lists its archetype).

        Returns:
            A canonical district name, or ``"unknown"``.
        """
        try:
            from engine.world.character_gen import ARCHETYPE_DISTRICT  # noqa: PLC0415
            tags = char.get("tags") or []
            if isinstance(tags, list):
                for tag in tags:
                    if tag in ARCHETYPE_DISTRICT:
                        return ARCHETYPE_DISTRICT[tag]
        except Exception:
            pass
        return "unknown"

    def _build_player(self) -> Dict[str, Any]:
        """Build the player block (defensive).

        Returns:
            ``{location, credits, heat}`` — safe defaults on failure.
        """
        try:
            p = self._player()
            return {
                "location": p.get("location", ""),
                "credits": int(p.get("credits", 0) or 0),
                "heat": int(p.get("heat", 0) or 0),
            }
        except Exception as exc:
            logger.error("[%s] player state unavailable (operation=build_state): %s",
                         SCENE_ID, exc)
            return {"location": "", "credits": 0, "heat": 0}

    def _district_for_scene(self, scene_name: str) -> str:
        """Resolve a RoutineManager scene name to its canonical district.

        Reverses :data:`engine.world.territory.DISTRICT_SCENES` (cached). An
        unknown / empty scene resolves to ``"unknown"``.

        Args:
            scene_name: A scene location string from RoutineManager.

        Returns:
            The canonical district name, or ``"unknown"``.
        """
        if not scene_name:
            return "unknown"
        if self._scene_to_district is None:
            mapping: Dict[str, str] = {}
            try:
                from engine.world.territory import DISTRICT_SCENES  # noqa: PLC0415
                for district, scenes in DISTRICT_SCENES.items():
                    for scene in scenes:
                        mapping[scene] = district
            except Exception as exc:
                logger.debug("[%s] district map unavailable (operation=resolve): %s",
                             SCENE_ID, exc)
            self._scene_to_district = mapping
        return self._scene_to_district.get(scene_name, "unknown")

    # ──── Event feed (B-T2) ──────────────────────────────────────────

    @staticmethod
    def _parse_since(raw: Optional[str]) -> int:
        """Parse the ``since`` query param to an int id (defensive).

        Args:
            raw: The raw query value (may be ``None`` / non-numeric).

        Returns:
            The integer cursor, or ``0`` on any failure.
        """
        try:
            return int(raw) if raw is not None else 0
        except (TypeError, ValueError):
            return 0

    def _merged_events(self, since: int = 0) -> List[Dict[str, Any]]:
        """Return merged agency + territory events, normalized, newest-first.

        Merges :meth:`EmergentStore.recent_events` and
        :meth:`TerritoryManager.get_event_history`, normalizing each to
        ``{id?, ts, kind, actor, summary, district?}``. Events whose integer
        ``id`` is ``<= since`` are dropped (territory events carry no id and
        always pass). Defensive per source.

        Args:
            since: Drop emergent events with ``id <= since``.

        Returns:
            Normalized event dicts, newest-first.
        """
        events: List[Dict[str, Any]] = []

        # Emergent agency feed (carries integer ids).
        try:
            limit = int(self._cfg("events_limit", 50))
            for ev in self._emergent_store().recent_events(limit):
                eid = ev.get("id")
                if eid is not None and isinstance(eid, int) and eid <= since:
                    continue
                events.append({
                    "id": eid,
                    "ts": ev.get("ts", ""),
                    "kind": ev.get("kind", "event"),
                    "actor": ev.get("actor", ""),
                    "summary": ev.get("summary", ""),
                })
        except Exception as exc:
            logger.error("[%s] emergent events unavailable (operation=events): %s",
                         SCENE_ID, exc)

        # Territory shift history (no ids; normalized to the same shape).
        try:
            limit = int(self._cfg("territory_events_limit", 20))
            for ev in self._territory().get_event_history(limit):
                events.append(self._normalize_territory_event(ev))
        except Exception as exc:
            logger.error("[%s] territory events unavailable (operation=events): %s",
                         SCENE_ID, exc)

        # Newest-first: prefer ts, falling back to a 0 sort key.
        events.sort(key=lambda e: self._event_sort_key(e), reverse=True)
        return events

    @staticmethod
    def _normalize_territory_event(ev: Dict[str, Any]) -> Dict[str, Any]:
        """Normalize a TerritoryEvent dict to the merged-feed contract.

        Args:
            ev: A ``TerritoryManager.get_event_history`` entry.

        Returns:
            ``{ts, kind, actor, summary, district}``.
        """
        district = ev.get("district", "")
        faction = ev.get("faction", "")
        delta = ev.get("delta", 0.0)
        kind = "faction_war" if ev.get("triggered_war") else "territory_shift"
        summary = f"{faction} {delta:+.1f}% in {district} ({ev.get('reason', '')})"
        return {
            "ts": ev.get("timestamp", ""),
            "kind": kind,
            "actor": faction,
            "summary": summary,
            "district": district,
        }

    @staticmethod
    def _event_sort_key(ev: Dict[str, Any]) -> float:
        """Best-effort numeric sort key (newer → larger) for mixed event shapes.

        Territory events carry a float epoch ``ts``; emergent events carry an
        ISO string ``ts`` plus an integer ``id``. We prefer a numeric ts, then
        the id, else 0.

        Args:
            ev: A normalized event dict.

        Returns:
            A float sort key.
        """
        ts = ev.get("ts")
        if isinstance(ts, (int, float)):
            return float(ts)
        eid = ev.get("id")
        if isinstance(eid, int):
            return float(eid)
        # ISO-8601 strings sort lexicographically in chronological order; map a
        # best-effort ordinal so they at least cluster after epoch floats below.
        return 0.0

    # ──── Socket push (B-T2) ─────────────────────────────────────────

    def _push_state_throttled(self) -> None:
        """Emit a fresh ``sprawl_update`` to all clients, throttled (never raises).

        Called from the EventBus ``living_world_tick`` handler. Coalesces bursts
        to at most one push per ``the_sprawl.push_throttle_s`` seconds.
        """
        try:
            throttle = float(self._cfg("push_throttle_s", 2.0))
            now = time.time()
            if now - self._last_push_ts < throttle:
                return
            self._last_push_ts = now
            self.socketio.emit("sprawl_update", self._build_state())
        except Exception as exc:
            logger.error("[%s] state push failed (operation=push): %s", SCENE_ID, exc)

    def _push_event(self, normalized: Dict[str, Any]) -> None:
        """Emit a single normalized ``sprawl_event`` to all clients (never raises).

        Args:
            normalized: A normalized event dict.
        """
        try:
            self.socketio.emit("sprawl_event", normalized)
        except Exception as exc:
            logger.error("[%s] event push failed (operation=push): %s", SCENE_ID, exc)

    def _on_bus_tick(self, event: Dict[str, Any]) -> None:
        """EventBus handler for ``living_world_tick`` → throttled state push.

        Args:
            event: The full EventBus envelope (payload ignored — we rebuild
                fresh state from the managers).
        """
        self._push_state_throttled()

    def _on_bus_action(self, event: Dict[str, Any]) -> None:
        """EventBus handler for ``emergent_action`` → push a sprawl_event.

        Args:
            event: The full EventBus envelope; the agency payload lives under
                ``event["payload"]`` ``{npc_id, verb, target, ok, detail, ...}``.
        """
        try:
            payload = event.get("payload", {}) if isinstance(event, dict) else {}
            npc = payload.get("npc_id", "")
            verb = payload.get("verb", "acted")
            target = payload.get("target", "")
            detail = payload.get("detail", "")
            summary = detail or f"{npc} {verb} {target}".strip()
            self._push_event({
                "ts": event.get("timestamp", "") if isinstance(event, dict) else "",
                "kind": "emergent_action",
                "actor": npc,
                "summary": summary,
            })
        except Exception as exc:
            logger.error("[%s] action handler failed (operation=push): %s", SCENE_ID, exc)

    def _on_bus_territory(self, event: Dict[str, Any]) -> None:
        """EventBus handler for ``territory_shift`` → push a sprawl_event.

        Args:
            event: The full EventBus envelope; the TerritoryEvent dict lives
                under ``event["payload"]``.
        """
        try:
            payload = event.get("payload", {}) if isinstance(event, dict) else {}
            self._push_event(self._normalize_territory_event(payload))
        except Exception as exc:
            logger.error("[%s] territory handler failed (operation=push): %s", SCENE_ID, exc)

    # ──── FlaskScene Lifecycle Hooks ─────────────────────────────
    # v1.63.0 [2026-06-15] — FlaskScene handles start()/stop(); use hooks

    def on_before_serve(self) -> None:
        """Subscribe to the EventBus for live push (read-only, defensive)."""
        try:
            from engine.events.event_bus import get_event_bus  # noqa: PLC0415
            bus = get_event_bus()
            self._sub_ids.append(bus.subscribe(_EVT_TICK, self._on_bus_tick, SCENE_ID))
            self._sub_ids.append(bus.subscribe(_EVT_ACTION, self._on_bus_action, SCENE_ID))
            self._sub_ids.append(bus.subscribe(_EVT_TERRITORY, self._on_bus_territory, SCENE_ID))
            logger.info("[%s] live world online — subscribed to %d bus events (operation=lifecycle)",
                        SCENE_ID, len(self._sub_ids))
        except Exception as exc:
            # The scene still serves REST even if the bus is unavailable.
            logger.error("[%s] EventBus subscription failed (operation=lifecycle): %s",
                         SCENE_ID, exc)

    def on_shutdown(self) -> None:
        """Unsubscribe from the EventBus and clean up (defensive)."""
        try:
            from engine.events.event_bus import get_event_bus  # noqa: PLC0415
            bus = get_event_bus()
            for sub_id in self._sub_ids:
                try:
                    bus.unsubscribe(sub_id)
                except Exception:
                    pass
        except Exception as exc:
            logger.debug("[%s] bus unsubscribe skipped (operation=lifecycle): %s",
                         SCENE_ID, exc)
        self._sub_ids = []
        logger.info("[%s] Scene stopping (operation=lifecycle)", SCENE_ID)
