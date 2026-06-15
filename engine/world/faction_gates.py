"""
Faction Gates — Reusable standing-driven access, pricing & mission helpers
==========================================================================

Closes the long-standing audit gap where faction standing was *cosmetic*: prior
to v1.60.0 the only thing player standing gated anywhere in the codebase was
casino VIP access. This module provides the reusable primitives every scene can
call so that standing finally drives real consequences:

* :func:`shop_access_allowed`   — gate a vendor / shop behind a minimum standing.
* :func:`price_multiplier_for`  — matching faction discount (-10%), rival surcharge
  (+15%), graded by how allied / hostile the player is.
* :func:`filter_missions_by_standing` — hide missions the player isn't trusted
  enough to see (and surface standing-locked ones with a reason).
* :func:`npc_standing_note`     — short dialogue-ready note an NPC can drop based
  on the player's standing with their faction.

All thresholds and multipliers are configurable via ``get_config()`` under the
``faction_gates`` key, with sensible defaults baked in so the module works
stand-alone (and in hermetic tests) with no config file present.

Standing scale matches :class:`engine.world.player_state.PlayerState`:
``-100`` (sworn enemy) … ``0`` (neutral) … ``+100`` (trusted ally). Labels match
:mod:`engine.agents.interceptors.faction_context` so dialogue stays consistent.

Version: v1.60.0 [2026-06-13]
Author:  CosySim Team

Change Log:
    v1.60.0 [2026-06-13] — Initial implementation. Reusable faction-gating
        helpers (shop access, price multiplier, mission filtering, NPC notes)
        for the "Living Systems" release. Configurable thresholds.

CONNECTS: PlayerState (faction_standings), get_config, FactionAI
CALLED BY: scene vendors (grid, casino, neoncity), mission systems, NPC dialogue
EMITS: Nothing (pure decision helpers — no side effects, no events)
"""
from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)


# ──── Default thresholds & multipliers ───────────────────────────────────
# These mirror engine.agents.interceptors.faction_context so the numeric→label
# mapping stays consistent across the whole game. Override any of them via
# config under the ``faction_gates`` key (see integration_requests).

# Standing band thresholds (player standing >= threshold ⇒ band).
_DEFAULT_ALLIED: int = 50      # trusted ally
_DEFAULT_FRIENDLY: int = 20    # on good terms
_DEFAULT_HOSTILE: int = -20    # unwelcome
_DEFAULT_ENEMY: int = -50      # sworn enemy

# Pricing. A *matching* faction (the shop's own faction, player in good standing)
# gets a discount; a *rival* faction gets a surcharge. Graded by band so an ally
# beats a friendly, and an enemy pays more than the merely unwelcome.
_DEFAULT_MATCH_DISCOUNT: float = 0.10   # matching faction → -10%
_DEFAULT_RIVAL_SURCHARGE: float = 0.15  # rival faction   → +15%
_DEFAULT_ALLY_BONUS_DISCOUNT: float = 0.05   # extra off for full allies
_DEFAULT_ENEMY_BONUS_SURCHARGE: float = 0.15  # extra on for sworn enemies

# Default minimum standing a shop requires to even let the player in.
_DEFAULT_SHOP_MIN_STANDING: int = -50

# Clamp the final price multiplier so a single faction relationship can never
# make goods free or absurdly expensive.
_PRICE_MULT_FLOOR: float = 0.5
_PRICE_MULT_CEIL: float = 2.0


# ──── Standing band labels (match faction_context) ───────────────────────

class StandingBand:
    """Named standing bands. String values double as dialogue-ready labels."""

    ALLIED: str = "allied"
    FRIENDLY: str = "friendly"
    NEUTRAL: str = "neutral"
    UNFRIENDLY: str = "unfriendly"
    HOSTILE: str = "hostile"


# ──── Config loading ─────────────────────────────────────────────────────


def _cfg(key: str, default: Any) -> Any:
    """Fetch a ``faction_gates.<key>`` config value with a safe fallback.

    Never raises — if config is unavailable (e.g. in a hermetic unit test) the
    supplied *default* is returned so the helpers remain pure and predictable.

    Args:
        key: Sub-key under the ``faction_gates`` config namespace.
        default: Value returned when config is missing or errors.

    Returns:
        The configured value, or *default*.
    """
    try:
        from engine.config import get_config

        return get_config().get(f"faction_gates.{key}", default)
    except Exception:  # pragma: no cover - config absent in unit tests
        return default


def get_thresholds() -> Dict[str, int]:
    """Return the configured standing-band thresholds.

    Returns:
        Mapping with keys ``allied``, ``friendly``, ``hostile``, ``enemy``.
    """
    return {
        "allied": int(_cfg("allied_threshold", _DEFAULT_ALLIED)),
        "friendly": int(_cfg("friendly_threshold", _DEFAULT_FRIENDLY)),
        "hostile": int(_cfg("hostile_threshold", _DEFAULT_HOSTILE)),
        "enemy": int(_cfg("enemy_threshold", _DEFAULT_ENEMY)),
    }


# ──── Standing classification ────────────────────────────────────────────


def standing_band(standing: int) -> str:
    """Classify a numeric standing into a named :class:`StandingBand`.

    Args:
        standing: Player standing with a faction (-100 … +100).

    Returns:
        One of ``allied``, ``friendly``, ``neutral``, ``unfriendly``, ``hostile``.
    """
    t = get_thresholds()
    s = int(standing)
    if s >= t["allied"]:
        return StandingBand.ALLIED
    if s >= t["friendly"]:
        return StandingBand.FRIENDLY
    if s <= t["enemy"]:
        return StandingBand.HOSTILE
    if s <= t["hostile"]:
        return StandingBand.UNFRIENDLY
    return StandingBand.NEUTRAL


def is_ally(standing: int) -> bool:
    """Return ``True`` if standing is friendly or better."""
    return standing_band(standing) in (StandingBand.ALLIED, StandingBand.FRIENDLY)


def is_rival(standing: int) -> bool:
    """Return ``True`` if standing is unfriendly or worse."""
    return standing_band(standing) in (StandingBand.UNFRIENDLY, StandingBand.HOSTILE)


def _resolve_standing(
    faction: str,
    standing: Optional[int],
) -> int:
    """Resolve a standing value, reading PlayerState when *standing* is None.

    Args:
        faction: Faction name to look up if *standing* not supplied.
        standing: Explicit standing, or ``None`` to read live PlayerState.

    Returns:
        Integer standing (0 when unknown / unavailable).
    """
    if standing is not None:
        return int(standing)
    try:
        from engine.world.player_state import get_player_state

        return int(get_player_state().faction_standings.get(faction, 0))
    except Exception:  # pragma: no cover - PlayerState absent in unit tests
        return 0


# ──── Shop / vendor access gate ──────────────────────────────────────────


def shop_access_allowed(
    faction: str,
    standing: Optional[int] = None,
    *,
    min_standing: Optional[int] = None,
) -> bool:
    """Decide whether a player may shop at a faction-aligned vendor.

    Args:
        faction: The vendor's owning faction (e.g. ``"BlackMarket"``).
        standing: Player's standing with *faction*. If ``None``, read live from
            :class:`PlayerState`.
        min_standing: Per-shop minimum standing override. When ``None`` the
            global ``faction_gates.shop_min_standing`` default is used.

    Returns:
        ``True`` if the player is allowed in, ``False`` if turned away.

    Example::

        if not shop_access_allowed("BlackMarket", player_standing):
            return "The fixer waves you off. 'Not for your kind.'"
    """
    s = _resolve_standing(faction, standing)
    threshold = (
        int(min_standing)
        if min_standing is not None
        else int(_cfg("shop_min_standing", _DEFAULT_SHOP_MIN_STANDING))
    )
    allowed = s >= threshold
    if not allowed:
        logger.info(
            "[faction_gates] Shop access denied (operation=shop_access, "
            "faction=%s, standing=%d, required=%d)",
            faction,
            s,
            threshold,
        )
    return allowed


# ──── Pricing ────────────────────────────────────────────────────────────


def price_multiplier_for(
    faction: str,
    standing: Optional[int] = None,
    *,
    relation: str = "match",
) -> float:
    """Compute a price multiplier driven by player standing.

    A *matching* faction (the shop's own faction) rewards loyalty with a
    discount; a *rival* faction punishes the player with a surcharge. The base
    -10% / +15% is graded by standing band so full allies and sworn enemies see
    a stronger effect.

    Args:
        faction: Faction the price is relative to.
        standing: Player standing with *faction*. ``None`` reads live PlayerState.
        relation: ``"match"`` (the vendor's own faction) or ``"rival"`` (a rival
            of the vendor). Unknown values are treated as neutral (1.0).

    Returns:
        A multiplier to apply to a base price, clamped to
        ``[0.5, 2.0]``. ``1.0`` means full price.

    Example::

        final = base_price * price_multiplier_for("BlackMarket", standing, relation="match")
    """
    s = _resolve_standing(faction, standing)
    band = standing_band(s)

    match_disc = float(_cfg("match_discount", _DEFAULT_MATCH_DISCOUNT))
    rival_sur = float(_cfg("rival_surcharge", _DEFAULT_RIVAL_SURCHARGE))
    ally_bonus = float(_cfg("ally_bonus_discount", _DEFAULT_ALLY_BONUS_DISCOUNT))
    enemy_bonus = float(_cfg("enemy_bonus_surcharge", _DEFAULT_ENEMY_BONUS_SURCHARGE))

    mult = 1.0
    rel = (relation or "").lower()

    if rel == "match":
        # Reward standing with this faction: discount for allies/friends, but a
        # *negative* standing with your own faction earns a surcharge.
        if band == StandingBand.ALLIED:
            mult = 1.0 - match_disc - ally_bonus
        elif band == StandingBand.FRIENDLY:
            mult = 1.0 - match_disc
        elif band == StandingBand.UNFRIENDLY:
            mult = 1.0 + match_disc
        elif band == StandingBand.HOSTILE:
            mult = 1.0 + match_disc + ally_bonus
        # neutral → 1.0
    elif rel == "rival":
        # Punish loyalty to a rival faction: surcharge scales with how friendly
        # the player is with the rival.
        if band == StandingBand.ALLIED:
            mult = 1.0 + rival_sur + enemy_bonus
        elif band == StandingBand.FRIENDLY:
            mult = 1.0 + rival_sur
        elif band == StandingBand.HOSTILE:
            # Player hates the rival too → small goodwill discount.
            mult = 1.0 - match_disc
        # neutral / unfriendly → 1.0
    # unknown relation → neutral 1.0

    mult = max(_PRICE_MULT_FLOOR, min(_PRICE_MULT_CEIL, round(mult, 3)))
    return mult


def apply_price(
    base_price: float,
    faction: str,
    standing: Optional[int] = None,
    *,
    relation: str = "match",
) -> int:
    """Convenience: apply :func:`price_multiplier_for` and round to credits.

    Args:
        base_price: The unadjusted price in credits.
        faction: Faction the price is relative to.
        standing: Player standing. ``None`` reads live PlayerState.
        relation: ``"match"`` or ``"rival"``.

    Returns:
        Final price in whole credits (minimum 1).
    """
    mult = price_multiplier_for(faction, standing, relation=relation)
    return max(1, int(round(float(base_price) * mult)))


# ──── Mission filtering ──────────────────────────────────────────────────


def mission_unlocked(
    mission: Dict[str, Any],
    standings: Optional[Dict[str, int]] = None,
) -> Tuple[bool, str]:
    """Decide if a single mission is unlocked by the player's standings.

    A mission may declare gating via either:

    * ``mission["faction"]`` + ``mission["min_standing"]`` — requires that
      standing with the named faction, or
    * ``mission["max_standing"]`` — an upper bound (e.g. anti-corp jobs only
      offered while you're NOT an ally).

    Missions with no gating keys are always unlocked.

    Args:
        mission: Mission dict (may contain ``faction``, ``min_standing``,
            ``max_standing``, ``title``/``id``).
        standings: Player faction→standing map. ``None`` reads live PlayerState.

    Returns:
        ``(unlocked, reason)``. *reason* is empty when unlocked, otherwise a
        short human-readable explanation suitable for a locked-mission tooltip.
    """
    faction = mission.get("faction")
    if not faction:
        return True, ""

    if standings is None:
        try:
            from engine.world.player_state import get_player_state

            standings = get_player_state().faction_standings
        except Exception:  # pragma: no cover
            standings = {}

    current = int(standings.get(faction, 0))
    fac_label = str(faction).replace("_", " ").title()

    min_req = mission.get("min_standing")
    if min_req is not None and current < int(min_req):
        return (
            False,
            f"Requires {fac_label} standing {int(min_req):+d} (you: {current:+d}).",
        )

    max_req = mission.get("max_standing")
    if max_req is not None and current > int(max_req):
        return (
            False,
            f"Only offered while {fac_label} standing is at or below "
            f"{int(max_req):+d} (you: {current:+d}).",
        )

    return True, ""


def filter_missions_by_standing(
    missions: List[Dict[str, Any]],
    standings: Optional[Dict[str, int]] = None,
    *,
    include_locked: bool = False,
) -> List[Dict[str, Any]]:
    """Filter a mission list by the player's faction standings.

    Args:
        missions: List of mission dicts.
        standings: Player faction→standing map. ``None`` reads live PlayerState.
        include_locked: When ``True``, locked missions are *kept* but annotated
            with ``locked=True`` and ``lock_reason=<why>`` (useful for showing
            greyed-out entries). When ``False`` (default), locked missions are
            dropped entirely.

    Returns:
        A new list. Unlocked missions are returned unmodified; locked ones are
        either omitted or annotated depending on *include_locked*.

    Example::

        visible = filter_missions_by_standing(all_missions, include_locked=True)
        for m in visible:
            grey = m.get("locked")
    """
    out: List[Dict[str, Any]] = []
    for mission in missions:
        unlocked, reason = mission_unlocked(mission, standings)
        if unlocked:
            out.append(mission)
        elif include_locked:
            annotated = dict(mission)
            annotated["locked"] = True
            annotated["lock_reason"] = reason
            out.append(annotated)
    return out


# ──── NPC dialogue notes ─────────────────────────────────────────────────

# Band → list-of-templates. Chosen deterministically by faction name hash so a
# given NPC says a consistent line across calls (no global random state, keeps
# tests hermetic).
_STANDING_NOTES: Dict[str, List[str]] = {
    StandingBand.ALLIED: [
        "You've more than earned {fac}'s trust — anything you need, it's yours.",
        "{fac} remembers its friends. You're one of ours now.",
        "Word travels fast. {fac} knows what you've done for us. Welcome.",
    ],
    StandingBand.FRIENDLY: [
        "{fac} appreciates what you've done. You're on the right side of us.",
        "You've been good to {fac}. Keep it up and doors start opening.",
    ],
    StandingBand.NEUTRAL: [
        "{fac} has no quarrel with you. Yet. Prove yourself either way.",
        "You're a stranger to {fac}. Could go any direction from here.",
    ],
    StandingBand.UNFRIENDLY: [
        "{fac} hasn't forgotten your missteps. Watch your step here.",
        "You're not welcome the way you used to be. {fac} is watching you.",
    ],
    StandingBand.HOSTILE: [
        "You've got nerve showing your face. {fac} wants you gone.",
        "{fac} counts you an enemy. Don't expect mercy on our turf.",
    ],
}


def npc_standing_note(
    faction: str,
    standing: Optional[int] = None,
) -> str:
    """Produce a short dialogue-ready note an NPC drops based on standing.

    Deterministic for a given (faction, band) pair — no global RNG — so NPCs
    stay consistent and tests stay hermetic.

    Args:
        faction: The NPC's faction.
        standing: Player standing with *faction*. ``None`` reads live PlayerState.

    Returns:
        A single line of NPC flavour text.

    Example::

        line = npc_standing_note("BlackMarket", player_standing)
    """
    s = _resolve_standing(faction, standing)
    band = standing_band(s)
    fac_label = str(faction).replace("_", " ").title()
    templates = _STANDING_NOTES.get(band, _STANDING_NOTES[StandingBand.NEUTRAL])
    # Deterministic pick: stable across calls for the same faction+band.
    idx = (abs(hash(faction)) + len(band)) % len(templates)
    return templates[idx].format(fac=fac_label)


__all__ = [
    "StandingBand",
    "get_thresholds",
    "standing_band",
    "is_ally",
    "is_rival",
    "shop_access_allowed",
    "price_multiplier_for",
    "apply_price",
    "mission_unlocked",
    "filter_missions_by_standing",
    "npc_standing_note",
]
