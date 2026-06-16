"""Hybrid action planner for the v1.63 Emergent Engine (A4).

This module turns an NPC's durable *goals* (from
:mod:`engine.world.emergent.goals`) into a concrete, executable *action*, then
DISPATCHES that action to the systems that already model the world. It is the
seam between "what does this NPC want" (A3) and "what actually happens" — and it
is deliberately reuse-first: it owns the genuinely-new planning/utility logic
only, and delegates every effect to an EXISTING manager rather than
re-implementing territory, economy, crews, hacking, relationships, or comms.

Two halves, mirroring the goals module:

* **Pure planning** — :func:`plan_action` scores candidate actions built from the
  top goals (``utility = priority * fit * feasibility``, weights from
  ``emergent.planner.*`` config) and returns the argmax as a
  :class:`PlannedAction`. It touches no live manager and is deterministic given a
  seeded ``rng``. A ``LAY_LOW`` goal suppresses every aggressive verb. The
  ``use_llm`` flag is set only for a *pivotal* action and only when an
  ``emergent.planner.llm_chance`` roll succeeds (default low) — the LLM is never
  called here; the flag merely marks the action for a later, guarded path.

* **Defensive dispatch** — :func:`execute` maps each verb onto the real manager:

  ===========  ====================================================================
  verb         manager / call
  ===========  ====================================================================
  ``trade``    :func:`engine.world.market.get_market` → ``buy`` / ``sell``
  ``contest``  :func:`engine.world.territory.get_territory_manager` → ``shift_control``
  ``crew_op``  :func:`engine.world.crew.get_crew_manager` → ``start_operation``
  ``hack``     :func:`content.scenes.phone.phone_hack.hack_phone` (``intercept``)
  ``betray``   :func:`engine.world.relationship_effects.apply_exchange_effect` (cool)
  ``romance``  :func:`engine.world.relationship_effects.apply_exchange_effect` (warm)
  ``message``  :func:`engine.world.npc_comms.get_npc_comms_scheduler` → ``run_exchange``
  ``lay_low``  no-op (low profile)
  ===========  ====================================================================

  After a SUCCESSFUL dispatch the action is recorded on the world feed via
  :meth:`engine.world.emergent.store.EmergentStore.log_event`. Every dispatch is
  wrapped: a manager failure is logged in the Oracle format
  (``[emergent] ... (operation=...)``) and surfaced as ``{"ok": False, ...}`` —
  :func:`execute` NEVER raises and NEVER calls the LLM inline (so it is
  unit-testable with the managers mocked at the boundary).

All tunable weights live under ``emergent.planner.*`` (read via
``get_config().get(...)`` with in-code defaults) so the designer can retune NPC
decision-making without code changes.

Manager imports are bound at MODULE level (``from ... import get_market`` etc.)
specifically so unit tests can ``monkeypatch.setattr(planner, "get_market", ...)``
to mock each system at the dispatch boundary without standing up live services.

Version: v1.63.0 [2026-06-15]
Author:  CosySim Team

Change Log:
    v1.63.0 [2026-06-15] — Initial hybrid planner (A4): PlannedAction dataclass,
                            pure utility-scoring plan_action with goal→verb
                            mapping + lay-low suppression + config-gated llm
                            flag, and a defensive execute() dispatching each verb
                            to the EXISTING manager (market/territory/crew/
                            phone_hack/relationship_effects/npc_comms) with
                            world-event logging and never-raises guarantees.
"""
from __future__ import annotations

import logging
import random
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional

from engine.world.emergent.goals import (
    LAY_LOW,
    RANK,
    REVENGE,
    ROMANCE,
    TERRITORY,
    WEALTH,
    Goal,
)

# ── Manager seams (bound at module level so tests can monkeypatch them) ──────
# Each import is the EXISTING system the matching verb dispatches to. Importing
# the accessor (not constructing it) keeps this module Flask-free and lets the
# unit tests replace each accessor with a fake at the dispatch boundary.
from engine.world.market import get_market
from engine.world.territory import (
    CONTROL_SHIFT_RANGE,
    DISTRICT_NAMES,
    get_territory_manager,
)
from engine.world.crew import get_crew_manager
from engine.world.npc_comms import get_npc_comms_scheduler
from engine.world.relationship_effects import apply_exchange_effect
from content.scenes.phone.phone_hack import hack_phone

logger = logging.getLogger(__name__)

# ══════════════════════════════════════════════════════════════════════
#  GOAL → VERB MAPPING + VERB SETS
# ══════════════════════════════════════════════════════════════════════

#: Map each goal type to the verb the planner proposes for it. REVENGE maps to a
#: pair — the planner chooses ``hack`` or ``betray`` by feasibility (see below).
_GOAL_VERB: Dict[str, str] = {
    WEALTH: "trade",
    TERRITORY: "contest",
    RANK: "crew_op",
    ROMANCE: "romance",
    LAY_LOW: "lay_low",
}

#: Verbs considered AGGRESSIVE — suppressed entirely while a LAY_LOW goal is the
#: NPC's top drive (the NPC is keeping its head down).
_AGGRESSIVE_VERBS = frozenset({"hack", "betray", "contest", "crew_op"})

# ── config keys + their built-in defaults ──────────────────────────────
# Centralised so the lookups and the test suite agree on the defaults.
_CFG = "emergent.planner."
_PLANNER_DEFAULTS: Dict[str, float] = {
    "priority_weight": 1.0,    # weight on the goal's own priority
    "fit_weight": 1.0,         # weight on how well the verb fits the goal
    "feasibility_weight": 1.0,  # weight on whether the action is even possible
    "min_utility": 0.01,       # below this, nothing sensible -> plan returns None
    "llm_chance": 0.05,        # P(use_llm) for a PIVOTAL action (kept low)
    "trade_default_qty": 1.0,  # default quantity for a trade dispatch
    "contest_delta": 3.0,      # control delta for a contest (clamped to range)
}


def _planner_cfg(key: str) -> float:
    """Return a tunable planner weight from config with a built-in default.

    Args:
        key: The short key under ``emergent.planner.`` (e.g. ``"fit_weight"``).

    Returns:
        The configured float, or the module default if config is unavailable.
    """
    default = _PLANNER_DEFAULTS[key]
    try:
        from engine.config import get_config

        return float(get_config().get(_CFG + key, default))
    except Exception as exc:  # config optional / malformed in minimal builds
        logger.error(
            "[emergent] config lookup failed, using default (operation=cfg, key=%s): %s",
            key, exc,
        )
        return default


# ══════════════════════════════════════════════════════════════════════
#  PLANNED ACTION
# ══════════════════════════════════════════════════════════════════════


@dataclass
class PlannedAction:
    """A single concrete action chosen for an NPC to perform.

    Attributes:
        verb: The action verb (``"trade"``, ``"contest"``, ``"crew_op"``,
            ``"hack"``, ``"betray"``, ``"romance"``, ``"message"``,
            ``"lay_low"``).
        target: The object of the action — another NPC id, a district, a faction,
            etc. Empty for self-directed actions such as ``lay_low``.
        params: Verb-specific parameters used by :func:`execute` (e.g. the
            ``district``/``good_id`` for a trade, the ``faction`` for a contest).
        use_llm: Whether this (pivotal) action should later be elaborated by the
            LLM. Set only by :func:`plan_action`; :func:`execute` NEVER calls the
            LLM inline, so this is a marker for a separate, guarded path.
    """

    verb: str
    target: str = ""
    params: Dict[str, Any] = field(default_factory=dict)
    use_llm: bool = False


# ══════════════════════════════════════════════════════════════════════
#  PURE PLANNING
# ══════════════════════════════════════════════════════════════════════


@dataclass
class _Candidate:
    """An internal scored candidate action (pre-argmax)."""

    action: PlannedAction
    goal: Goal
    fit: float
    feasibility: float

    @property
    def utility(self) -> float:
        """The composite utility ``priority * fit * feasibility`` (weighted)."""
        return (
            _planner_cfg("priority_weight") * self.goal.priority
            * (_planner_cfg("fit_weight") * self.fit)
            * (_planner_cfg("feasibility_weight") * self.feasibility)
        )


def plan_action(
    npc_id: str,
    *,
    goals: List[Goal],
    ctx: Dict[str, Any],
    rng: Optional[random.Random] = None,
) -> Optional[PlannedAction]:
    """Choose the highest-utility action for an NPC from its goals.

    PURE: every input arrives via ``goals`` + ``ctx`` so the planner can be unit
    tested with hand-built data and never touches a live manager. For a given
    input (and seeded ``rng``) the result is deterministic.

    Each top goal yields one or more candidate actions; each candidate is scored
    ``utility = goal.priority * fit * feasibility`` (weights from
    ``emergent.planner.*``). The argmax is returned (``rng`` breaks ties). A
    ``LAY_LOW`` goal among the inputs suppresses every aggressive verb
    (:data:`_AGGRESSIVE_VERBS`); a contest needs a faction + a district; a
    crew_op needs a faction; a romance/betray/hack needs a target. When nothing
    scores above ``emergent.planner.min_utility``, ``None`` is returned.

    Args:
        npc_id: The acting NPC (used for logging/identity, not scoring).
        goals: The NPC's prioritised goals (typically from
            :func:`engine.world.emergent.goals.generate_goals`).
        ctx: Pure planning context. Recognised keys: ``faction`` (``str``),
            ``district`` (``str``), ``crew`` (``list[str]``), ``pivotal``
            (``bool`` — marks the turn as pivotal, gating ``use_llm``), and an
            optional ``relationships`` map.
        rng: Optional ``random.Random`` used for tie-breaks and the ``use_llm``
            roll. Defaults to a fresh system-seeded instance.

    Returns:
        The chosen :class:`PlannedAction`, or ``None`` when no candidate is
        sensible.
    """
    rng = rng or random.Random()
    if not goals:
        return None

    laying_low = any(g.type == LAY_LOW for g in goals)
    candidates: List[_Candidate] = []
    for goal in goals:
        for cand in _candidates_for_goal(goal, ctx):
            if laying_low and cand.action.verb in _AGGRESSIVE_VERBS:
                continue  # head down: no aggressive moves while laying low
            candidates.append(cand)

    if not candidates:
        return None

    min_utility = _planner_cfg("min_utility")
    viable = [c for c in candidates if c.utility >= min_utility]
    if not viable:
        return None

    best = _argmax(viable, rng)
    action = best.action
    # LLM is reserved for a pivotal action, gated by a low-chance roll. The flag
    # is a marker only — execute() never calls the LLM inline.
    action.use_llm = _should_use_llm(ctx, rng)
    logger.info(
        "[emergent] planned action (operation=plan_action, npc=%s, verb=%s, "
        "target=%s, utility=%.4f, use_llm=%s)",
        npc_id, action.verb, action.target, best.utility, action.use_llm,
    )
    return action


def _candidates_for_goal(goal: Goal, ctx: Dict[str, Any]) -> List[_Candidate]:
    """Build the candidate action(s) a single goal proposes.

    Args:
        goal: The goal to expand into candidate actions.
        ctx: The planning context (see :func:`plan_action`).

    Returns:
        Zero or more :class:`_Candidate` objects (zero when the goal proposes
        nothing actionable in this context).
    """
    faction = ctx.get("faction") or ""
    district = ctx.get("district") or ""
    crew = list(ctx.get("crew") or [])

    if goal.type == REVENGE:
        # REVENGE → hack OR betray, both targeting the wronged-against id. Need a
        # target to act on; hack is always feasible (phone breach), betray is
        # feasible too (relationship hit). Offer both; argmax + rng decide.
        if not goal.target:
            return []
        return [
            _Candidate(
                PlannedAction(verb="hack", target=goal.target),
                goal, fit=1.0, feasibility=1.0,
            ),
            _Candidate(
                PlannedAction(verb="betray", target=goal.target),
                goal, fit=0.9, feasibility=1.0,
            ),
        ]

    verb = _GOAL_VERB.get(goal.type)
    if verb is None:
        return []

    if verb == "trade":
        params = {"district": district or _default_district(), "good_id": ctx.get("good_id", "")}
        return [_Candidate(PlannedAction(verb="trade", target="", params=params), goal, 1.0, 1.0)]

    if verb == "contest":
        # Needs a faction to contest FOR and a district to contest IN.
        if not faction or not district:
            return []
        params = {"faction": faction, "district": district}
        return [_Candidate(PlannedAction(verb="contest", target=district, params=params), goal, 1.0, 1.0)]

    if verb == "crew_op":
        # Needs a faction; crew members improve feasibility but are not required
        # (the manager enforces min_crew at dispatch time).
        if not faction:
            return []
        feasibility = 1.0 if crew else 0.6
        params = {"faction": faction, "crew": crew}
        return [_Candidate(PlannedAction(verb="crew_op", target=faction, params=params), goal, 1.0, feasibility)]

    if verb == "romance":
        if not goal.target:
            return []
        return [_Candidate(PlannedAction(verb="romance", target=goal.target), goal, 1.0, 1.0)]

    if verb == "lay_low":
        return [_Candidate(PlannedAction(verb="lay_low", target=""), goal, 1.0, 1.0)]

    return []


def _argmax(candidates: List[_Candidate], rng: random.Random) -> _Candidate:
    """Return the highest-utility candidate, breaking ties with ``rng``.

    Args:
        candidates: Non-empty list of scored candidates.
        rng: Random source used to pick uniformly among tied maxima.

    Returns:
        The chosen candidate.
    """
    best_utility = max(c.utility for c in candidates)
    top = [c for c in candidates if c.utility >= best_utility - 1e-9]
    if len(top) == 1:
        return top[0]
    # Deterministic tie-break: order by (verb, target) then pick via rng so the
    # choice is reproducible for a seeded rng.
    top.sort(key=lambda c: (c.action.verb, c.action.target))
    return top[rng.randrange(len(top))]


def _should_use_llm(ctx: Dict[str, Any], rng: random.Random) -> bool:
    """Decide whether a PIVOTAL action should be marked for the LLM path.

    Gated twice: the turn must be flagged ``pivotal`` in ``ctx`` AND an
    ``emergent.planner.llm_chance`` roll must succeed. Kept low by default so the
    LLM is reserved for rare, important beats.

    Args:
        ctx: The planning context (``pivotal`` is read here).
        rng: Random source for the chance roll.

    Returns:
        ``True`` when the action should later be elaborated by the LLM.
    """
    if not bool(ctx.get("pivotal")):
        return False
    chance = _planner_cfg("llm_chance")
    if chance <= 0.0:
        return False
    if chance >= 1.0:
        return True
    return rng.random() < chance


def _default_district() -> str:
    """Return a stable default district for a trade with no explicit one."""
    return DISTRICT_NAMES[0] if DISTRICT_NAMES else "DOWNTOWN"


# ══════════════════════════════════════════════════════════════════════
#  DEFENSIVE DISPATCH
# ══════════════════════════════════════════════════════════════════════


def execute(npc_id: str, action: PlannedAction, *, ctx: Dict[str, Any]) -> Dict[str, Any]:
    """Dispatch a planned action to the EXISTING manager and record the result.

    Each verb is routed to the real system (see the module docstring table). On a
    SUCCESSFUL dispatch a world event is appended via the emergent store's
    :meth:`~engine.world.emergent.store.EmergentStore.log_event`. Every dispatch
    is wrapped in try/except: a manager failure is logged in the Oracle format
    and surfaced as ``{"ok": False, ...}``. This function NEVER raises and NEVER
    calls the LLM inline.

    Args:
        npc_id: The acting NPC.
        action: The :class:`PlannedAction` to perform.
        ctx: Execution context. Recognised keys: ``faction`` (the NPC's faction,
            used as ``shift_control``'s ``source_faction``), ``crew``
            (``list[str]`` for a crew_op), ``db`` (an explicit ``Database`` for
            relationship writes), and ``store`` (an explicit ``EmergentStore``
            for world-event logging — tests pass an isolated one).

    Returns:
        A result dict with at least ``{"verb", "ok", "detail"}``; verb-specific
        keys (``result``, ``new_level``, …) are merged in on success.
    """
    handler = _DISPATCH.get(action.verb)
    if handler is None:
        logger.error(
            "[emergent] unknown verb, nothing dispatched (operation=execute, "
            "npc=%s, verb=%s)", npc_id, action.verb,
        )
        return {"verb": action.verb, "ok": False, "detail": "unknown_verb"}

    try:
        result = handler(npc_id, action, ctx)
    except Exception as exc:
        logger.error(
            "[emergent] dispatch failed (operation=execute, npc=%s, verb=%s, "
            "target=%s): %s", npc_id, action.verb, action.target, exc,
        )
        return {"verb": action.verb, "ok": False, "detail": f"error:{exc}"}

    if result.get("ok"):
        _log_world_event(npc_id, action, result, ctx)
    return result


# ── per-verb handlers ───────────────────────────────────────────────────


def _do_trade(npc_id: str, action: PlannedAction, ctx: Dict[str, Any]) -> Dict[str, Any]:
    """Dispatch a ``trade`` to the live Market (buy by default).

    Args:
        npc_id: The acting NPC (used as ``player_id`` so the trade is attributed).
        action: The planned trade; ``params`` may carry ``district``/``good_id``/
            ``quantity``/``side`` (``"buy"`` | ``"sell"``).
        ctx: Execution context (``district`` fallback).

    Returns:
        A result dict ``{verb, ok, detail, result}``.
    """
    params = action.params or {}
    district = params.get("district") or ctx.get("district") or _default_district()
    good_id = params.get("good_id") or _DEFAULT_GOOD
    qty = int(params.get("quantity") or _planner_cfg("trade_default_qty"))
    side = params.get("side", "buy")

    market = get_market()
    if side == "sell":
        res = market.sell(district, good_id, quantity=qty, player_id=npc_id)
    else:
        res = market.buy(district, good_id, quantity=qty, player_id=npc_id)

    ok = bool(res) and res.get("status") == "ok"
    return {
        "verb": "trade", "ok": ok,
        "detail": res.get("status") if isinstance(res, dict) else "no_result",
        "result": res,
    }


def _do_contest(npc_id: str, action: PlannedAction, ctx: Dict[str, Any]) -> Dict[str, Any]:
    """Dispatch a ``contest`` to TerritoryManager.shift_control.

    The control delta is clamped into ``CONTROL_SHIFT_RANGE`` and the NPC's own
    faction is passed as both the gaining ``faction`` and the ``source_faction``
    (it takes turf FROM rivals FOR itself).

    Args:
        npc_id: The acting NPC.
        action: The planned contest; ``params`` carry ``faction``/``district``.
        ctx: Execution context (``faction`` fallback for the source).

    Returns:
        A result dict ``{verb, ok, detail, delta, event}``.
    """
    params = action.params or {}
    faction = params.get("faction") or ctx.get("faction") or ""
    district = params.get("district") or action.target or ctx.get("district") or ""
    if not faction or not district:
        return {"verb": "contest", "ok": False, "detail": "missing_faction_or_district"}

    lo, hi = CONTROL_SHIFT_RANGE
    delta = max(lo, min(hi, float(_planner_cfg("contest_delta"))))

    mgr = get_territory_manager()
    event = mgr.shift_control(
        district, faction, delta,
        reason=f"emergent:{npc_id}",
        source_faction=faction,
    )
    event_dict = event.to_dict() if hasattr(event, "to_dict") else {"delta": getattr(event, "delta", delta)}
    return {
        "verb": "contest", "ok": True, "detail": "shifted",
        "delta": delta, "event": event_dict,
    }


def _do_crew_op(npc_id: str, action: PlannedAction, ctx: Dict[str, Any]) -> Dict[str, Any]:
    """Dispatch a ``crew_op`` to CrewManager.start_operation.

    Args:
        npc_id: The acting NPC.
        action: The planned op; ``params`` may carry ``crew`` (character ids) and
            ``op_type``.
        ctx: Execution context (``crew`` fallback).

    Returns:
        A result dict ``{verb, ok, detail, chance}``.
    """
    params = action.params or {}
    crew = list(params.get("crew") or ctx.get("crew") or [])
    op_type = params.get("op_type", _DEFAULT_OP_TYPE)

    mgr = get_crew_manager()
    chance = 0.0
    try:
        chance, _ = mgr.compute_success_chance(op_type, crew)
    except Exception as exc:  # odds are advisory; a failure here must not abort
        logger.error(
            "[emergent] success-chance probe failed (operation=crew_op, npc=%s): %s",
            npc_id, exc,
        )
    ok, message = mgr.start_operation(op_type, crew)
    return {"verb": "crew_op", "ok": bool(ok), "detail": message, "chance": chance}


def _do_hack(npc_id: str, action: PlannedAction, ctx: Dict[str, Any]) -> Dict[str, Any]:
    """Dispatch a ``hack`` to phone_hack.hack_phone (``intercept``).

    Args:
        npc_id: The acting NPC (the attacker; informational here — the existing
            ``hack_phone`` models the player→NPC breach math).
        action: The planned hack; ``target`` is the NPC whose phone is hit.
        ctx: Execution context (unused).

    Returns:
        A result dict ``{verb, ok, detail, result}``.
    """
    res = hack_phone(action.target, action="intercept")
    ok = bool(res) and bool(res.get("success"))
    return {
        "verb": "hack", "ok": ok,
        "detail": (res.get("message") if isinstance(res, dict) else "no_result"),
        "result": res,
    }


def _do_betray(npc_id: str, action: PlannedAction, ctx: Dict[str, Any]) -> Dict[str, Any]:
    """Dispatch a ``betray`` — a relationship hit + crew dismissal if applicable.

    Applies a cool-tone exchange effect to the ``(npc, target)`` pair via
    :func:`engine.world.relationship_effects.apply_exchange_effect`, and, when the
    target is in the crew, dismisses them through CrewManager.

    Args:
        npc_id: The betraying NPC.
        action: The planned betrayal; ``target`` is the betrayed id.
        ctx: Execution context (``db`` for the relationship write).

    Returns:
        A result dict ``{verb, ok, detail, new_level, dismissed}``.
    """
    db = _get_database(ctx)
    new_level = apply_exchange_effect(
        db, npc_id, action.target,
        "You crossed me. We're done.",
        tone="cool",
    )
    dismissed = False
    try:
        mgr = get_crew_manager()
        if mgr.get_member(action.target) is not None:
            dismissed = bool(mgr.dismiss(action.target, reason=f"betrayed by {npc_id}"))
    except Exception as exc:  # crew dismissal is best-effort, never aborts betray
        logger.error(
            "[emergent] betray crew-dismiss failed (operation=betray, npc=%s, "
            "target=%s): %s", npc_id, action.target, exc,
        )
    return {
        "verb": "betray", "ok": True, "detail": "relationship_hit",
        "new_level": new_level, "dismissed": dismissed,
    }


def _do_romance(npc_id: str, action: PlannedAction, ctx: Dict[str, Any]) -> Dict[str, Any]:
    """Dispatch a ``romance`` — a warm-tone relationship effect to the pair.

    Args:
        npc_id: The wooing NPC.
        action: The planned romance; ``target`` is the wooed id.
        ctx: Execution context (``db`` for the relationship write).

    Returns:
        A result dict ``{verb, ok, detail, new_level}``.
    """
    db = _get_database(ctx)
    new_level = apply_exchange_effect(
        db, npc_id, action.target,
        "Been thinking about you. Let's get out of here together.",
        tone="warm",
    )
    return {"verb": "romance", "ok": True, "detail": "relationship_warm", "new_level": new_level}


def _do_message(npc_id: str, action: PlannedAction, ctx: Dict[str, Any]) -> Dict[str, Any]:
    """Dispatch a ``message`` to the NPC↔NPC comms scheduler exchange.

    Args:
        npc_id: The sending NPC.
        action: The planned message; ``target`` is the recipient id.
        ctx: Execution context (unused).

    Returns:
        A result dict ``{verb, ok, detail, result}``.
    """
    scheduler = get_npc_comms_scheduler()
    res = scheduler.run_exchange(npc_id, action.target)
    ok = bool(res)
    return {"verb": "message", "ok": ok, "detail": "exchanged", "result": res}


def _do_lay_low(npc_id: str, action: PlannedAction, ctx: Dict[str, Any]) -> Dict[str, Any]:
    """Dispatch a ``lay_low`` — a deliberate low-profile no-op.

    Args:
        npc_id: The NPC keeping its head down.
        action: The planned (empty) action.
        ctx: Execution context (unused).

    Returns:
        A result dict ``{verb, ok, detail}``.
    """
    logger.info("[emergent] laying low, no action (operation=lay_low, npc=%s)", npc_id)
    return {"verb": "lay_low", "ok": True, "detail": "low_profile"}


#: Verb → handler table. Bound after the handlers are defined.
_DISPATCH: Dict[str, Callable[[str, PlannedAction, Dict[str, Any]], Dict[str, Any]]] = {
    "trade": _do_trade,
    "contest": _do_contest,
    "crew_op": _do_crew_op,
    "hack": _do_hack,
    "betray": _do_betray,
    "romance": _do_romance,
    "message": _do_message,
    "lay_low": _do_lay_low,
}

# Sensible dispatch defaults (kept tiny; designer-tunable knobs live in config).
_DEFAULT_GOOD = "stim_pack"   # cheap, broadly-stocked consumable for a trade
_DEFAULT_OP_TYPE = "recon"    # lowest min_crew / difficulty crew operation


# ══════════════════════════════════════════════════════════════════════
#  HELPERS
# ══════════════════════════════════════════════════════════════════════


def _log_world_event(
    npc_id: str, action: PlannedAction, result: Dict[str, Any], ctx: Dict[str, Any]
) -> None:
    """Append a world event for a successful action (best-effort).

    Args:
        npc_id: The acting NPC (the event ``actor``).
        action: The performed action (the event ``kind`` is its verb).
        result: The dispatch result dict (merged into the event ``payload``).
        ctx: Execution context (``store`` for an explicit EmergentStore).
    """
    try:
        store = _get_store(ctx)
        summary = f"{npc_id} performed {action.verb}" + (
            f" on {action.target}" if action.target else ""
        )
        store.log_event(
            kind=action.verb,
            actor=npc_id,
            summary=summary,
            payload={"target": action.target, "detail": result.get("detail", "")},
        )
    except Exception as exc:
        logger.error(
            "[emergent] world-event log failed (operation=log_event, npc=%s, "
            "verb=%s): %s", npc_id, action.verb, exc,
        )


def _get_store(ctx: Dict[str, Any]) -> Any:
    """Return the EmergentStore for world-event logging.

    Args:
        ctx: Execution context; an explicit ``store`` (tests pass an isolated
            one) takes precedence over the process singleton.

    Returns:
        An :class:`~engine.world.emergent.store.EmergentStore`.
    """
    store = ctx.get("store")
    if store is not None:
        return store
    from engine.world.emergent.store import get_emergent_store

    return get_emergent_store()


def _get_database(ctx: Dict[str, Any]) -> Any:
    """Return the simulation Database for relationship writes, or ``None``.

    Args:
        ctx: Execution context; an explicit ``db`` takes precedence. When absent,
            the singleton ``Database`` is constructed lazily — a failure degrades
            to ``None`` (relationship_effects treats ``None`` as a no-op).

    Returns:
        A ``Database`` instance, or ``None`` when unavailable.
    """
    db = ctx.get("db")
    if db is not None:
        return db
    try:
        from content.simulation.database.db import Database

        return Database()
    except Exception as exc:
        logger.error(
            "[emergent] simulation DB unavailable (operation=database): %s", exc
        )
        return None
