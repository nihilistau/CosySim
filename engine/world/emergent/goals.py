"""Per-NPC goal generation + persistence for the v1.63 Emergent Engine (A3).

This module owns the genuinely-new "what does this NPC *want*" logic for the
emergent world. It is deliberately split into two halves:

* **Pure logic** — :func:`generate_goals` and :func:`reprioritize` take all of
  their inputs as plain data (a ``ctx`` dict, an outcome dict) and never touch
  live managers, the database, or global state. This keeps them trivially
  unit-testable and deterministic given a seeded ``rng``.
* **Persistence** — :func:`load_goals` / :func:`save_goals` adapt the
  :class:`Goal` dataclass to the existing
  :class:`~engine.world.emergent.store.EmergentStore` (which owns the
  ``npc_goal`` table). No new storage is introduced here — reuse-first.

All weights and thresholds are read from
``get_config().get("emergent.goals.*", default)`` rather than hardcoded, so the
designer can retune NPC drives without code changes. Every store interaction is
defensive: a failure is logged in the Oracle format
(``[emergent] ... (operation=...)``) and a safe value is returned so a goal
failure can never break a caller.

Usage::

    from engine.world.emergent.goals import generate_goals, save_goals

    goals = generate_goals("npc-1", ctx={
        "relationships": {"rival": -0.8, "lover": 0.9},
        "faction": "arasaka",
        "recently_hacked": True,
    })
    save_goals("npc-1", goals)

Version: v1.63.0 [2026-06-15]
Author:  CosySim Team

Change Log:
    v1.63.0 [2026-06-15] — Initial per-NPC goal layer (A3): Goal dataclass with
                            store row mapping, pure generate_goals (baseline
                            wealth, revenge/romance from relationships, faction
                            rank+territory, lay-low priority boost), deterministic
                            reprioritize (decay-on-success / bump-on-failure),
                            and defensive load/save via EmergentStore.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

# ══════════════════════════════════════════════════════════════════════
#  GOAL TYPES
# ══════════════════════════════════════════════════════════════════════

WEALTH = "wealth"
RANK = "rank"
REVENGE = "revenge"
ROMANCE = "romance"
LAY_LOW = "lay_low"
TERRITORY = "territory"

#: All recognised goal-type string values, for validation/iteration.
GOAL_TYPES = (WEALTH, RANK, REVENGE, ROMANCE, LAY_LOW, TERRITORY)

# ── config keys + their built-in defaults ──────────────────────────────
# Centralised so the lookups below and the test suite agree on the defaults.
_CFG = "emergent.goals."
_DEFAULTS: Dict[str, float] = {
    "rel_negative": -0.4,   # relationship <= this is hostile -> revenge
    "rel_positive": 0.6,    # relationship >= this is close   -> romance
    "base_wealth": 0.30,    # baseline priority of the always-on wealth goal
    "revenge_weight": 0.80,  # multiplies |relationship| for revenge priority
    "romance_weight": 0.70,  # multiplies relationship for romance priority
    "rank_priority": 0.45,
    "territory_priority": 0.40,
    "lay_low_boost": 0.50,   # added ON TOP of the current max so it sorts first
    "success_decay": 0.30,   # subtracted from a satisfied goal's priority
    "failure_bump": 0.30,    # added to a thwarted goal's priority
}


def _cfg(key: str) -> float:
    """Return a tunable weight/threshold from config with a built-in default.

    Args:
        key: The short key under ``emergent.goals.`` (e.g. ``"rel_negative"``).

    Returns:
        The configured float, or the module default if config is unavailable.
    """
    default = _DEFAULTS[key]
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
#  GOAL DATACLASS
# ══════════════════════════════════════════════════════════════════════


@dataclass
class Goal:
    """A single durable NPC drive.

    Attributes:
        type: One of :data:`GOAL_TYPES` (e.g. ``"wealth"``, ``"revenge"``).
        target: The object of the goal — another NPC id, a faction, etc. Empty
            for self-directed goals such as baseline wealth.
        priority: Sort weight; higher means more urgent. Goals are returned
            sorted by this descending.
        progress: Completion fraction in ``[0, 1]``.
    """

    type: str
    target: str = ""
    priority: float = 0.0
    progress: float = 0.0

    def to_row(self) -> Dict[str, Any]:
        """Map this goal to the store's ``npc_goal`` column names.

        Returns:
            A dict with keys ``goal_type``, ``target``, ``priority``,
            ``progress`` and an (empty) ``data`` dict, ready for
            :meth:`~engine.world.emergent.store.EmergentStore.set_goals`.
        """
        return {
            "goal_type": self.type,
            "target": self.target,
            "priority": float(self.priority),
            "progress": float(self.progress),
            "data": {},
        }

    @classmethod
    def from_row(cls, row: Dict[str, Any]) -> "Goal":
        """Build a :class:`Goal` from a store row dict.

        Defensive: missing keys fall back to dataclass defaults and numeric
        fields are coerced, so a malformed row can never raise.

        Args:
            row: A dict using the store's column names (``goal_type``,
                ``target``, ``priority``, ``progress``).

        Returns:
            The reconstructed :class:`Goal`.
        """
        return cls(
            type=str(row.get("goal_type", "") or ""),
            target=str(row.get("target", "") or ""),
            priority=_to_float(row.get("priority")),
            progress=_to_float(row.get("progress")),
        )


# ══════════════════════════════════════════════════════════════════════
#  PURE GENERATION
# ══════════════════════════════════════════════════════════════════════


def generate_goals(
    npc_id: str,
    *,
    ctx: Dict[str, Any],
    rng: Optional[Any] = None,
) -> List[Goal]:
    """Generate a prioritised goal list for an NPC from pure inputs.

    This function is PURE: every input arrives via ``ctx`` so it can be unit
    tested with hand-built data and never calls a live manager. The result is
    deterministic for a given ``ctx`` (and seeded ``rng``).

    Rules (all weights/thresholds from ``emergent.goals.*`` config):
        * Always include a baseline :data:`WEALTH` goal.
        * For each relationship ``<= rel_negative``: a :data:`REVENGE` goal
          targeting that id, priority scaling with how negative it is.
        * For the single strongest relationship ``>= rel_positive``: one
          :data:`ROMANCE` goal targeting it.
        * If ``faction`` is set: a :data:`RANK` goal and a :data:`TERRITORY`
          goal, both targeting the faction.
        * If ``recently_hacked`` or ``in_trouble``: a :data:`LAY_LOW` goal whose
          priority is boosted above every other goal, so it sorts first.

    Args:
        npc_id: The NPC the goals are for (used only for logging/identity).
        ctx: Pure context. Recognised keys: ``relationships``
            (``dict[other_id, float]``), ``faction`` (``str | None``),
            ``recently_hacked`` (``bool``), ``in_trouble`` (``bool``), and an
            optional ``stats`` dict.
        rng: Optional ``random.Random``-like instance used only for tie-break
            jitter (kept deterministic). Currently generation is fully
            deterministic without jitter, but the parameter is accepted so the
            signature is stable.

    Returns:
        Goals sorted by ``priority`` descending (ties broken by ``type`` then
        ``target`` for stable, deterministic ordering).
    """
    del rng  # generation is fully deterministic; reserved for future jitter
    relationships: Dict[str, float] = dict(ctx.get("relationships") or {})
    faction = ctx.get("faction")
    recently_hacked = bool(ctx.get("recently_hacked"))
    in_trouble = bool(ctx.get("in_trouble"))

    rel_negative = _cfg("rel_negative")
    rel_positive = _cfg("rel_positive")

    goals: List[Goal] = []

    # 1) Baseline wealth — every NPC wants to get paid.
    goals.append(Goal(type=WEALTH, target="", priority=_cfg("base_wealth")))

    # 2) Revenge for each hostile relationship; the more negative, the higher.
    revenge_weight = _cfg("revenge_weight")
    for other_id, level in relationships.items():
        if level <= rel_negative:
            goals.append(
                Goal(
                    type=REVENGE,
                    target=other_id,
                    priority=round(abs(level) * revenge_weight, 6),
                )
            )

    # 3) Romance for the single strongest close relationship.
    close = {oid: lvl for oid, lvl in relationships.items() if lvl >= rel_positive}
    if close:
        # Strongest by level; tie-break on id for determinism.
        best_id = max(close, key=lambda oid: (close[oid], oid))
        goals.append(
            Goal(
                type=ROMANCE,
                target=best_id,
                priority=round(close[best_id] * _cfg("romance_weight"), 6),
            )
        )

    # 4) Faction ambitions: climb the ranks and grab turf.
    if faction:
        goals.append(Goal(type=RANK, target=str(faction), priority=_cfg("rank_priority")))
        goals.append(
            Goal(type=TERRITORY, target=str(faction), priority=_cfg("territory_priority"))
        )

    # 5) Lay low when hacked or in trouble — must out-rank everything else.
    if recently_hacked or in_trouble:
        current_max = max((g.priority for g in goals), default=0.0)
        goals.append(
            Goal(
                type=LAY_LOW,
                target="",
                priority=round(current_max + _cfg("lay_low_boost"), 6),
            )
        )

    return _sorted(goals)


def reprioritize(goals: List[Goal], outcome: Dict[str, Any]) -> List[Goal]:
    """Adjust goal priorities after an action outcome and re-sort.

    Deterministic. The goal matching ``outcome`` by ``(type, target)`` is
    decayed on success (it has been partly satisfied) or bumped on failure
    (it was thwarted, so it presses harder). Non-matching goals are untouched.

    Args:
        goals: The current goal list. Not mutated in place — a new sorted list
            is returned.
        outcome: ``{"goal_type": str, "target": str, "success": bool}``.

    Returns:
        A new list of :class:`Goal` sorted by priority descending.
    """
    goal_type = str(outcome.get("goal_type", "") or "")
    target = str(outcome.get("target", "") or "")
    success = bool(outcome.get("success"))
    delta = -_cfg("success_decay") if success else _cfg("failure_bump")

    out: List[Goal] = []
    for g in goals:
        if g.type == goal_type and g.target == target:
            out.append(
                Goal(
                    type=g.type,
                    target=g.target,
                    priority=round(g.priority + delta, 6),
                    progress=g.progress,
                )
            )
        else:
            out.append(Goal(type=g.type, target=g.target, priority=g.priority, progress=g.progress))
    return _sorted(out)


def _sorted(goals: List[Goal]) -> List[Goal]:
    """Return goals sorted by priority desc with deterministic tie-breaks.

    Args:
        goals: Goals to sort.

    Returns:
        A new list ordered by ``(-priority, type, target)``.
    """
    return sorted(goals, key=lambda g: (-g.priority, g.type, g.target))


# ══════════════════════════════════════════════════════════════════════
#  PERSISTENCE (adapts Goal <-> EmergentStore)
# ══════════════════════════════════════════════════════════════════════


def load_goals(npc_id: str, store: Optional[Any] = None) -> List[Goal]:
    """Load an NPC's persisted goals as :class:`Goal` objects.

    Args:
        npc_id: The NPC identifier.
        store: An :class:`~engine.world.emergent.store.EmergentStore`. Defaults
            to the process singleton via ``get_emergent_store()``.

    Returns:
        The deserialized goals (empty on any failure — never raises).
    """
    try:
        store = store or _default_store()
        rows = store.get_goals(npc_id)
        return [Goal.from_row(r) for r in rows]
    except Exception as exc:
        logger.error(
            "[emergent] load_goals failed (operation=load_goals, npc=%s): %s",
            npc_id, exc,
        )
        return []


def save_goals(npc_id: str, goals: List[Goal], store: Optional[Any] = None) -> bool:
    """Persist an NPC's goals, replacing any prior set atomically.

    Args:
        npc_id: The NPC identifier.
        goals: The goals to persist (serialized via :meth:`Goal.to_row`).
        store: An :class:`~engine.world.emergent.store.EmergentStore`. Defaults
            to the process singleton via ``get_emergent_store()``.

    Returns:
        ``True`` on success, ``False`` on any failure (never raises).
    """
    try:
        store = store or _default_store()
        return bool(store.set_goals(npc_id, [g.to_row() for g in goals]))
    except Exception as exc:
        logger.error(
            "[emergent] save_goals failed (operation=save_goals, npc=%s): %s",
            npc_id, exc,
        )
        return False


def _default_store() -> Any:
    """Return the process-wide EmergentStore singleton.

    Returns:
        The shared :class:`~engine.world.emergent.store.EmergentStore`.
    """
    from engine.world.emergent.store import get_emergent_store

    return get_emergent_store()


# ══════════════════════════════════════════════════════════════════════
#  HELPERS
# ══════════════════════════════════════════════════════════════════════


def _to_float(value: Any) -> float:
    """Coerce a value to float, returning ``0.0`` on failure.

    Args:
        value: Any value (number, numeric string, or ``None``).

    Returns:
        The float value, or ``0.0`` when coercion fails.
    """
    try:
        return float(value) if value is not None else 0.0
    except (TypeError, ValueError):
        return 0.0
