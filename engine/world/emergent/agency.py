"""Emergent agency driver for the v1.63 Emergent Engine (A5).

This module is the genuinely-new *driver* that makes NPCs act on their own. It
ties the per-NPC goal layer (A3, :mod:`engine.world.emergent.goals`) and the
hybrid planner (A4, :mod:`engine.world.emergent.planner`) together and runs them
on the EXISTING world cadence — it deliberately does NOT start a second daemon.

Reuse-first seam
----------------
The :class:`~engine.world.living_world.LivingWorld` daemon already ticks every
game hour and publishes a ``living_world_tick`` event on the shared
:class:`~engine.events.event_bus.EventBus` (see ``LivingWorld.tick`` →
``bus.publish("living_world_tick", ...)``). Rather than spin up a parallel
thread, :class:`EmergentAgency` simply *subscribes* to that event, so the agency
pass runs on the LivingWorld's existing schedule with zero new timers. ``start()``
subscribes; ``stop()`` unsubscribes. No edit to ``living_world.py`` is required.

Each tick → :meth:`EmergentAgency.run_pass`
-------------------------------------------
1. Enumerate NPCs (live ``Database.get_all_characters()`` / ``RoutineManager``,
   falling back to the npc_comms roster ``lola/viktor/aria/frankie/mira``).
2. Pick at most ``emergent.agency.active_npcs_per_tick`` of them (default 3) so
   the model stays calm — only a handful act per hour.
3. For each chosen NPC: build a ``ctx`` from REAL sources (relationships via the
   sim Database, faction via ``faction_context._get_character_faction``, district
   via ``RoutineManager.get_npc_location``, ``recently_hacked`` from the emergent
   world-event feed, ``crew`` from ``CrewManager``, and a rare ``pivotal`` flag),
   then ``load_goals`` (or ``generate_goals`` + ``save_goals`` when none),
   ``plan_action`` → ``execute`` → ``reprioritize`` + ``save_goals``, and finally
   publish an ``emergent_action`` event to the existing feed so scenes/Oracle can
   pick it up. ``execute`` already logs a world_event on success; the agency adds
   a per-pass summary to the store as well.

Caps & calm
-----------
Only ``active_npcs_per_tick`` NPCs act per tick, and at most
``emergent.agency.pivotal_per_tick`` of them are flagged ``pivotal`` (the
planner gates the LLM behind ``pivotal`` AND its own low ``llm_chance`` roll, so
the LLM stays rare). All knobs come from ``get_config().get("emergent.agency.*")``
— nothing is hardcoded.

NPC trade settlement (A4 follow-up)
-----------------------------------
The A4 planner's ``trade`` verb routes through ``Market.buy``/``sell``, whose
settlement is gated *globally* by ``economy.settle`` and ALWAYS draws on the
singleton player wallet (``Market._settle_buy`` ignores ``player_id``). Letting
an autonomous NPC trade through that path would silently drain the real player's
credits. So the agency intercepts the ``trade`` verb and instead applies a
*non-settling supply nudge* via ``Market.apply_event`` (``surplus``/``shortage``)
— a documented sim approximation that MOVES supply/demand without touching any
wallet. Every other verb dispatches through the planner's ``execute`` unchanged.

Defensive
---------
The whole pass is wrapped so a failure (planner, execute, a manager, the roster
source, …) is logged in the Oracle format ``[emergent] ... (operation=...)`` and
NEVER propagates into the LivingWorld tick — the event handler must always return
cleanly so the world keeps ticking.

Usage::

    from engine.world.emergent.agency import get_emergent_agency

    get_emergent_agency().start()   # subscribe to the LivingWorld tick
    ...
    get_emergent_agency().stop()    # unsubscribe cleanly

Version: v1.63.0 [2026-06-15]
Author:  CosySim Team

Change Log:
    v1.63.0 [2026-06-15] — Initial emergent agency driver (A5): subscribes to the
                            EXISTING living_world_tick EventBus event (no 2nd
                            daemon), bounded per-tick agency pass
                            (goals→plan→execute→reprioritize→persist→emit) with
                            ctx built from real sources, active-npcs + pivotal
                            caps, a non-settling Market supply-nudge for NPC
                            trades (no player-wallet drain), an emergent_action
                            feed event, and a never-raises tick handler.
"""
from __future__ import annotations

import logging
import random
import threading
from typing import Any, Dict, List, Optional

# ── Collaborator seams (bound at module level so tests can monkeypatch them) ──
# Goals (A3) + planner (A4) are imported as module-level names; the unit tests
# replace each with a fake via ``monkeypatch.setattr(agency, "<name>", ...)``.
from engine.world.emergent.goals import (
    Goal,
    generate_goals,
    load_goals,
    reprioritize,
    save_goals,
)
from engine.world.emergent.planner import PlannedAction, execute, plan_action

logger = logging.getLogger(__name__)

# ── tick event name (matches LivingWorld.tick's bus.publish) ─────────────────
TICK_EVENT = "living_world_tick"
#: Event published to the existing feed for each acted NPC.
ACTION_EVENT = "emergent_action"

# ── config keys + their built-in defaults ──────────────────────────────
_CFG = "emergent.agency."
_DEFAULTS: Dict[str, Any] = {
    "enabled": True,             # master switch; start() is a no-op when False
    "active_npcs_per_tick": 3,   # how many NPCs act per LivingWorld tick
    "pivotal_per_tick": 1,       # max NPCs flagged pivotal in one tick
    "pivotal_chance": 0.05,      # P(an NPC is considered for the pivotal flag)
}

#: Fallback roster when neither the live DB nor the RoutineManager yields NPCs.
_FALLBACK_ROSTER = ["lola", "viktor", "aria", "frankie", "mira"]

#: Maps a planned trade ``side`` to a non-settling Market.apply_event nudge that
#: moves supply/demand without a wallet (the documented NPC-trade approximation).
_TRADE_NUDGE = {"buy": "shortage", "sell": "surplus"}


def get_config():  # bound at module level so tests can monkeypatch it
    """Return the process config (thin wrapper so tests can patch it).

    Returns:
        The shared config object (``engine.config.get_config()``).
    """
    from engine.config import get_config as _gc

    return _gc()


def _cfg(key: str) -> Any:
    """Return an ``emergent.agency.*`` knob from config with a built-in default.

    Args:
        key: The short key under ``emergent.agency.`` (e.g. ``"enabled"``).

    Returns:
        The configured value, or the module default if config is unavailable.
    """
    default = _DEFAULTS[key]
    try:
        return get_config().get(_CFG + key, default)
    except Exception as exc:  # config optional / malformed in minimal builds
        logger.error(
            "[emergent] config lookup failed, using default (operation=cfg, key=%s): %s",
            key, exc,
        )
        return default


# ══════════════════════════════════════════════════════════════════════
#  EVENT-BUS / STORE SEAMS (module level for monkeypatching)
# ══════════════════════════════════════════════════════════════════════


def get_event_bus():
    """Return the shared EventBus, or ``None`` when unavailable.

    Returns:
        The :class:`~engine.events.event_bus.EventBus` singleton, or ``None`` in
        minimal builds where it cannot be constructed.
    """
    try:
        from engine.events.event_bus import get_event_bus as _geb

        return _geb()
    except Exception as exc:
        logger.error("[emergent] EventBus unavailable (operation=get_event_bus): %s", exc)
        return None


def _default_store():
    """Return the process-wide EmergentStore singleton.

    Returns:
        The shared :class:`~engine.world.emergent.store.EmergentStore`.
    """
    from engine.world.emergent.store import get_emergent_store

    return get_emergent_store()


# ══════════════════════════════════════════════════════════════════════
#  EMERGENT AGENCY
# ══════════════════════════════════════════════════════════════════════


class EmergentAgency:
    """Drives autonomous NPC behaviour on the EXISTING LivingWorld tick.

    Subscribes to the ``living_world_tick`` event and, on each tick, runs one
    bounded agency pass over a handful of NPCs (goals→plan→execute). Holds no
    timer of its own — it reuses the LivingWorld cadence. All public methods are
    safe to call from any thread; the tick handler never raises.

    Attributes:
        rng: The random source used for NPC selection and the pivotal roll.
    """

    def __init__(self, rng: Optional[random.Random] = None) -> None:
        """Create the agency (does not subscribe — call :meth:`start`).

        Args:
            rng: Optional ``random.Random`` for deterministic tests. Defaults to
                a fresh system-seeded instance.
        """
        self._lock = threading.RLock()
        self._sub_id: Optional[str] = None
        self._bus: Any = None
        self._tick_count = 0
        self.rng: random.Random = rng or random.Random()

    # ── lifecycle ──────────────────────────────────────────────────────

    def start(self) -> None:
        """Subscribe to the LivingWorld tick (idempotent; config-gated).

        A no-op when ``emergent.agency.enabled`` is false or when already
        subscribed. Never raises — a subscription failure is logged and the
        agency simply stays inactive.
        """
        with self._lock:
            if not bool(_cfg("enabled")):
                logger.info("[emergent] agency disabled, not starting (operation=start)")
                return
            if self._sub_id is not None:
                return  # already subscribed — idempotent
            bus = get_event_bus()
            if bus is None:
                logger.error("[emergent] no EventBus, agency inactive (operation=start)")
                return
            try:
                self._sub_id = bus.subscribe(TICK_EVENT, self._on_tick, "emergent_agency")
                self._bus = bus
                logger.info(
                    "[emergent] agency subscribed to %s (operation=start, sub=%s)",
                    TICK_EVENT, self._sub_id,
                )
            except Exception as exc:
                logger.error("[emergent] agency subscribe failed (operation=start): %s", exc)
                self._sub_id = None
                self._bus = None

    def stop(self) -> None:
        """Unsubscribe from the LivingWorld tick (idempotent, never raises)."""
        with self._lock:
            if self._sub_id is None:
                return
            try:
                if self._bus is not None:
                    self._bus.unsubscribe(self._sub_id)
                logger.info("[emergent] agency unsubscribed (operation=stop, sub=%s)", self._sub_id)
            except Exception as exc:
                logger.error("[emergent] agency unsubscribe failed (operation=stop): %s", exc)
            finally:
                self._sub_id = None
                self._bus = None

    def is_running(self) -> bool:
        """Return whether the agency is currently subscribed to the tick.

        Returns:
            ``True`` when subscribed (``start`` succeeded and ``stop`` has not
            run), else ``False``.
        """
        with self._lock:
            return self._sub_id is not None

    # ── tick handler (must NEVER raise into the LivingWorld tick) ───────

    def _on_tick(self, event: Dict[str, Any]) -> None:
        """EventBus handler for ``living_world_tick`` — runs one agency pass.

        Wrapped end-to-end: any failure is logged in the Oracle format and
        swallowed so it can never propagate back into the publishing
        LivingWorld tick.

        Args:
            event: The full EventBus event dict (payload unused — the agency
                rebuilds its own context from live sources).
        """
        try:
            self.run_pass()
        except Exception as exc:  # belt-and-braces: run_pass is already guarded
            logger.error("[emergent] agency tick failed (operation=on_tick): %s", exc)

    # ── the agency pass ────────────────────────────────────────────────

    def run_pass(self) -> Dict[str, Any]:
        """Run one bounded agency pass over a handful of NPCs.

        Enumerates NPCs, picks up to ``active_npcs_per_tick`` of them, flags up
        to ``pivotal_per_tick`` as pivotal, then drives each through the
        goals→plan→execute→reprioritize→persist→emit loop. Each NPC is isolated
        in its own try/except so one bad NPC never aborts the pass; the whole
        method also never raises.

        Returns:
            A summary dict ``{"acted", "npcs", "tick"}`` (``acted`` = number of
            NPCs that produced an action this pass).
        """
        with self._lock:
            self._tick_count += 1
            tick = self._tick_count

        acted: List[str] = []
        try:
            roster = _enumerate_npcs(self)
        except Exception as exc:
            logger.error("[emergent] roster enumeration failed (operation=run_pass): %s", exc)
            return {"acted": 0, "npcs": [], "tick": tick}

        if not roster:
            return {"acted": 0, "npcs": [], "tick": tick}

        cap = _as_int(_cfg("active_npcs_per_tick"), _DEFAULTS["active_npcs_per_tick"])
        chosen = self._pick(roster, cap)
        pivotal_cap = _as_int(_cfg("pivotal_per_tick"), _DEFAULTS["pivotal_per_tick"])
        pivotal_ids = self._pick_pivotal(chosen, pivotal_cap)

        for npc_id in chosen:
            try:
                if self._act(npc_id, pivotal=npc_id in pivotal_ids):
                    acted.append(npc_id)
            except Exception as exc:  # one bad NPC must not abort the pass
                logger.error(
                    "[emergent] npc agency failed (operation=run_pass, npc=%s): %s",
                    npc_id, exc,
                )

        self._log_pass_summary(tick, acted)
        return {"acted": len(acted), "npcs": acted, "tick": tick}

    def _act(self, npc_id: str, *, pivotal: bool) -> bool:
        """Run the full goals→plan→execute loop for a single NPC.

        Args:
            npc_id: The NPC to act for.
            pivotal: Whether this turn is flagged pivotal (gates the planner's
                LLM marker — never calls the LLM here).

        Returns:
            ``True`` when an action was planned and dispatched, else ``False``.
        """
        ctx = _build_ctx(self, npc_id)
        ctx["pivotal"] = pivotal

        store = _default_store()

        # 1) Load existing goals, or generate + persist a fresh set.
        goals = load_goals(npc_id, store=store)
        if not goals:
            goals = generate_goals(npc_id, ctx=ctx, rng=self.rng)
            save_goals(npc_id, goals, store=store)
        if not goals:
            return False

        # 2) Plan the highest-utility action.
        action = plan_action(npc_id, goals=goals, ctx=ctx, rng=self.rng)
        if action is None:
            return False

        # 3) Dispatch — NPC trades take the non-settling supply-nudge path so
        #    they never drain the player's wallet (see module docstring).
        if action.verb == "trade":
            result = self._npc_trade(npc_id, action)
        else:
            ctx_exec = dict(ctx)
            ctx_exec["store"] = store
            result = execute(npc_id, action, ctx=ctx_exec)

        # 4) Re-prioritise the goal set from the outcome and persist it.
        outcome = {
            "goal_type": _verb_to_goal_type(action.verb),
            "target": action.target,
            "success": bool(result.get("ok")),
        }
        goals = reprioritize(goals, outcome)
        save_goals(npc_id, goals, store=store)

        # 5) Emit an agency event to the EXISTING feed (scenes/Oracle pick it up).
        self._emit_action(npc_id, action, result)
        return True

    # ── NPC trade: a non-settling supply nudge (no player-wallet drain) ──

    def _npc_trade(self, npc_id: str, action: PlannedAction) -> Dict[str, Any]:
        """Approximate an NPC trade by nudging Market supply/demand only.

        Uses ``Market.apply_event`` (``shortage`` for a buy-pressure, ``surplus``
        for a sell-pressure) so the trade MOVES the economy but settles against
        NO wallet — ``Market.buy``/``sell`` would draw on the singleton player
        wallet regardless of ``player_id``. Documented sim approximation; verify
        the Market still reflects the trade via its supply/demand drift.

        Args:
            npc_id: The trading NPC (informational; the nudge is market-wide).
            action: The planned ``trade`` action (``params.side`` selects the
                nudge direction; defaults to a buy-pressure).

        Returns:
            A result dict ``{verb, ok, detail, nudge}``; ``ok`` is ``False`` on
            any failure (never raises).
        """
        side = str((action.params or {}).get("side", "buy"))
        nudge = _TRADE_NUDGE.get(side, "shortage")
        try:
            from engine.world.market import get_market

            res = get_market().apply_event(nudge)
            ok = bool(res) and res.get("status") != "error"
            return {"verb": "trade", "ok": ok, "detail": "supply_nudge", "nudge": nudge}
        except Exception as exc:
            logger.error(
                "[emergent] npc-trade supply nudge failed (operation=npc_trade, npc=%s): %s",
                npc_id, exc,
            )
            return {"verb": "trade", "ok": False, "detail": f"error:{exc}", "nudge": nudge}

    # ── selection helpers ──────────────────────────────────────────────

    def _pick(self, roster: List[str], cap: int) -> List[str]:
        """Pick up to ``cap`` NPCs from the roster (random, capped).

        Args:
            roster: The candidate NPC ids.
            cap: Maximum number to pick.

        Returns:
            Up to ``cap`` NPC ids (the whole roster when it is smaller).
        """
        if cap <= 0:
            return []
        if len(roster) <= cap:
            return list(roster)
        return self.rng.sample(list(roster), cap)

    def _pick_pivotal(self, chosen: List[str], cap: int) -> set:
        """Choose which acting NPCs are flagged pivotal this tick (rare, capped).

        Each chosen NPC passes a low ``pivotal_chance`` roll; the set is then
        clamped to ``cap`` so at most a handful are ever pivotal in one tick.

        Args:
            chosen: The NPCs acting this tick.
            cap: Maximum number that may be pivotal.

        Returns:
            The set of pivotal NPC ids (possibly empty).
        """
        if cap <= 0:
            return set()
        chance = _as_float(_cfg("pivotal_chance"), _DEFAULTS["pivotal_chance"])
        candidates = [n for n in chosen if self.rng.random() < chance]
        if len(candidates) > cap:
            candidates = candidates[:cap]
        return set(candidates)

    # ── emission / logging ─────────────────────────────────────────────

    def _emit_action(self, npc_id: str, action: PlannedAction, result: Dict[str, Any]) -> None:
        """Publish an ``emergent_action`` event to the existing feed (best-effort).

        Args:
            npc_id: The acting NPC.
            action: The action performed.
            result: The dispatch result dict.
        """
        bus = self._bus or get_event_bus()
        if bus is None:
            return
        try:
            bus.publish(
                ACTION_EVENT,
                {
                    "npc_id": npc_id,
                    "verb": action.verb,
                    "target": action.target,
                    "ok": bool(result.get("ok")),
                    "detail": result.get("detail", ""),
                    "use_llm": bool(getattr(action, "use_llm", False)),
                },
                scene="emergent",
            )
        except Exception as exc:
            logger.error(
                "[emergent] action emit failed (operation=emit_action, npc=%s): %s",
                npc_id, exc,
            )

    def _log_pass_summary(self, tick: int, acted: List[str]) -> None:
        """Append a one-line per-pass summary to the emergent world feed.

        Args:
            tick: This pass's tick counter.
            acted: The NPC ids that produced an action.
        """
        try:
            store = _default_store()
            store.log_event(
                kind="agency_pass",
                actor="emergent_agency",
                summary=f"agency pass #{tick}: {len(acted)} NPC(s) acted",
                payload={"tick": tick, "acted": acted},
                persistent=False,
            )
        except Exception as exc:
            logger.error(
                "[emergent] pass-summary log failed (operation=log_pass, tick=%s): %s",
                tick, exc,
            )


# ══════════════════════════════════════════════════════════════════════
#  NPC ENUMERATION + CTX BUILDING (module level so tests can patch them)
#  Each takes the agency instance as first arg, mirroring a bound method,
#  so a single monkeypatch swaps the whole sub-source out.
# ══════════════════════════════════════════════════════════════════════


def _enumerate_npcs(self: EmergentAgency) -> List[str]:
    """Enumerate candidate NPC ids from live sources, with a roster fallback.

    Order of preference: the sim ``Database.get_all_characters()``, then the
    ``RoutineManager`` registered NPCs, then the static npc_comms roster. Every
    source is defensive — a failure simply falls through to the next.

    Args:
        self: The agency instance (unused; present for monkeypatch symmetry).

    Returns:
        A de-duplicated list of NPC ids (never empty unless every source is).
    """
    ids: List[str] = []

    # 1) Live character database.
    try:
        from content.simulation.database.db import Database

        for row in Database().get_all_characters():
            cid = str(row.get("id") or row.get("character_id") or "")
            if cid:
                ids.append(cid)
    except Exception as exc:
        logger.error("[emergent] DB enumeration failed (operation=enumerate_npcs): %s", exc)

    # 2) RoutineManager-registered NPCs.
    if not ids:
        try:
            from engine.world.npc_routines import get_routine_manager

            ids.extend(get_routine_manager().list_npcs())
        except Exception as exc:
            logger.error("[emergent] routine enumeration failed (operation=enumerate_npcs): %s", exc)

    # 3) Static roster fallback.
    if not ids:
        ids = list(_FALLBACK_ROSTER)

    # de-dup, preserve order
    seen: set = set()
    out: List[str] = []
    for cid in ids:
        if cid and cid not in seen:
            seen.add(cid)
            out.append(cid)
    return out


def _build_ctx(self: EmergentAgency, npc_id: str) -> Dict[str, Any]:
    """Build a planning/goal context for an NPC from REAL sources.

    Recognised keys produced (all best-effort, each from its own guarded
    sub-source so a single failure degrades gracefully):

        * ``relationships`` — signed levels vs. other known NPCs + the player,
          from the sim ``Database``;
        * ``faction`` — from ``faction_context._get_character_faction``;
        * ``district`` — from ``RoutineManager.get_npc_location``;
        * ``recently_hacked`` / ``in_trouble`` — from the emergent world-event
          feed (a recent ``hack`` against this NPC);
        * ``crew`` — current crew member ids from ``CrewManager``.

    Args:
        self: The agency instance.
        npc_id: The NPC to build context for.

    Returns:
        A ctx dict consumed by ``generate_goals`` and ``plan_action``.
    """
    others = [n for n in _enumerate_npcs(self) if n != npc_id]
    recently_hacked = _recently_hacked(self, npc_id)
    return {
        "relationships": _relationships_for(self, npc_id, others),
        "faction": _faction_for(self, npc_id),
        "district": _district_for(self, npc_id),
        "crew": _crew_for(self, npc_id),
        "recently_hacked": recently_hacked,
        "in_trouble": recently_hacked,
    }


def _relationships_for(self: EmergentAgency, npc_id: str, others: List[str]) -> Dict[str, float]:
    """Return signed relationship levels for an NPC vs. others + the player.

    The sim Database stores ``relationship_level`` in ``[0, 1]`` (0.5 = neutral).
    The goals layer expects a signed ``[-1, 1]`` level (negative = hostile), so
    each is mapped ``signed = (level - 0.5) * 2``.

    Args:
        self: The agency instance (unused; monkeypatch symmetry).
        npc_id: The subject NPC.
        others: The other known NPC ids to score against.

    Returns:
        A ``{other_id: signed_level}`` map (empty on any failure).
    """
    rels: Dict[str, float] = {}
    try:
        from content.simulation.database.db import Database

        db = Database()
        for other in list(others) + ["player"]:
            try:
                rel = db.get_relationship(npc_id, other)
            except Exception:
                rel = None
            if not rel:
                continue
            level = rel.get("relationship_level")
            if level is None:
                continue
            rels[other] = round((float(level) - 0.5) * 2.0, 4)
    except Exception as exc:
        logger.error(
            "[emergent] relationship build failed (operation=relationships, npc=%s): %s",
            npc_id, exc,
        )
    return rels


def _faction_for(self: EmergentAgency, npc_id: str) -> Optional[str]:
    """Return the NPC's faction via the faction-context lookup, or ``None``.

    Args:
        self: The agency instance (unused; monkeypatch symmetry).
        npc_id: The NPC id.

    Returns:
        The faction name, or ``None`` if unknown / on failure.
    """
    try:
        from engine.agents.interceptors.faction_context import _get_character_faction

        return _get_character_faction(npc_id)
    except Exception as exc:
        logger.error("[emergent] faction lookup failed (operation=faction, npc=%s): %s", npc_id, exc)
        return None


def _district_for(self: EmergentAgency, npc_id: str) -> str:
    """Return the NPC's current district via the RoutineManager, or ``""``.

    Args:
        self: The agency instance (unused; monkeypatch symmetry).
        npc_id: The NPC id.

    Returns:
        The current location/district string, or empty on failure.
    """
    try:
        from engine.world.npc_routines import get_routine_manager

        loc = get_routine_manager().get_npc_location(npc_id)
        if isinstance(loc, dict):
            return str(loc.get("location") or loc.get("district") or "")
    except Exception as exc:
        logger.error("[emergent] district lookup failed (operation=district, npc=%s): %s", npc_id, exc)
    return ""


def _crew_for(self: EmergentAgency, npc_id: str) -> List[str]:
    """Return the current crew member ids (shared crew) for context.

    The crew is the player's roster of recruited NPCs; it gives crew_op planning
    something to work with. An absent / empty crew yields ``[]``.

    Args:
        self: The agency instance (unused; monkeypatch symmetry).
        npc_id: The NPC id (informational).

    Returns:
        A list of crew member character ids (empty on failure).
    """
    try:
        from engine.world.crew import get_crew_manager

        return [m.character_id for m in get_crew_manager().get_all_members()]
    except Exception as exc:
        logger.error("[emergent] crew lookup failed (operation=crew, npc=%s): %s", npc_id, exc)
        return []


def _recently_hacked(self: EmergentAgency, npc_id: str) -> bool:
    """Return whether the NPC was recently hacked, from the world-event feed.

    Reuses the emergent store's append-only feed (``execute`` logs a ``hack``
    event with the target in its payload) rather than reaching into the phone
    DB, keeping this defensive and dependency-light.

    Args:
        self: The agency instance (unused; monkeypatch symmetry).
        npc_id: The NPC id.

    Returns:
        ``True`` when a recent ``hack`` event targeted this NPC, else ``False``.
    """
    try:
        store = _default_store()
        for ev in store.recent_events(limit=20):
            if ev.get("kind") != "hack":
                continue
            payload = ev.get("payload") or {}
            if payload.get("target") == npc_id or ev.get("actor") == npc_id:
                return True
    except Exception as exc:
        logger.error(
            "[emergent] recently-hacked probe failed (operation=recently_hacked, npc=%s): %s",
            npc_id, exc,
        )
    return False


# ══════════════════════════════════════════════════════════════════════
#  SMALL HELPERS
# ══════════════════════════════════════════════════════════════════════

#: Inverse of the planner's goal→verb map, used to attribute an outcome back to
#: the goal it (partly) satisfied for reprioritisation.
_VERB_GOAL_TYPE: Dict[str, str] = {
    "trade": "wealth",
    "contest": "territory",
    "crew_op": "rank",
    "romance": "romance",
    "hack": "revenge",
    "betray": "revenge",
    "lay_low": "lay_low",
    "message": "",
}


def _verb_to_goal_type(verb: str) -> str:
    """Map an action verb back to the goal type it serves (for reprioritise).

    Args:
        verb: The action verb.

    Returns:
        The goal type string, or ``""`` when the verb serves no durable goal.
    """
    return _VERB_GOAL_TYPE.get(verb, "")


def _as_int(value: Any, default: int) -> int:
    """Coerce a config value to a non-negative int, falling back on failure.

    Args:
        value: The raw config value.
        default: The fallback when coercion fails.

    Returns:
        The coerced int (or ``default``).
    """
    try:
        return max(0, int(value))
    except (TypeError, ValueError):
        return default


def _as_float(value: Any, default: float) -> float:
    """Coerce a config value to a float, falling back on failure.

    Args:
        value: The raw config value.
        default: The fallback when coercion fails.

    Returns:
        The coerced float (or ``default``).
    """
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


# ══════════════════════════════════════════════════════════════════════
#  MODULE-LEVEL SINGLETON
# ══════════════════════════════════════════════════════════════════════

_instance: Optional[EmergentAgency] = None
_instance_lock = threading.Lock()


def get_emergent_agency() -> EmergentAgency:
    """Return the process-wide :class:`EmergentAgency` singleton.

    Returns:
        The shared :class:`EmergentAgency` instance.
    """
    global _instance
    if _instance is None:
        with _instance_lock:
            if _instance is None:
                _instance = EmergentAgency()
    return _instance


def reset_emergent_agency() -> None:
    """Reset the singleton (for testing): stops it if running, then clears it."""
    global _instance
    if _instance is not None:
        _instance.stop()
    _instance = None
