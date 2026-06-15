"""FactionRegistry — the faction model for the v1.63 Emergent Engine.

This module turns the raw :class:`~engine.world.emergent.store.EmergentStore`
rows into a coherent, living faction layer. The six canonical NeonCity factions
gain and lose power, hold and lose territory, accumulate or burn treasury, and
form alliances or go to war — all persisted through the store so the world
survives restarts.

Design notes
------------
* The six faction ids and the district ids are the canonical game lists. The
  faction ids MUST match ``engine.world.player_state._FACTION_NAMES`` exactly;
  both the player-state list and the public :data:`territory.FACTION_NAMES` are
  identical, so we import the public copy and assert the contract at import time.
  The districts come from :data:`territory.DISTRICT_NAMES` (the canonical city
  map used by the faction-AI / territory systems).
* All tunables (start power/treasury, flip/recovery deltas, floors) are read via
  ``get_config().get("emergent.faction.*", default)`` — never hardcoded — with a
  safe default so a missing config can never break the sim.
* State is persisted through the store. A faction's ``data`` blob carries its
  ``territory`` set (as a sorted list) and its ``relations`` map. The
  ``territory`` table is the source of truth for ownership; the per-faction set
  is a denormalised mirror kept in sync on every flip.
* Defensive throughout: unknown factions, store failures, and malformed data
  degrade gracefully (safe return values + an Oracle-format
  ``[emergent] ... (operation=...)`` log) rather than raising.

Usage::

    from engine.world.emergent.factions import get_factions

    reg = get_factions()
    reg.seed_if_empty()
    reg.flip_territory("DOWNTOWN", "Ghost_Net", by="raid")
    reg.declare_war("OmniCorp", "BlackMarket")
    reg.recovery_tick()

Version: v1.63.0 [2026-06-15]
Author:  CosySim Team

Change Log:
    v1.63.0 [2026-06-15] — Initial faction model (A2): seed_if_empty, power /
                            treasury / territory / relation accessors,
                            shift_power, adjust_treasury, flip_territory,
                            set_relation + declare_war / form_alliance, and a
                            recovery_tick so the world never flat-lines.
"""
from __future__ import annotations

import logging
import threading
from typing import Any, Dict, List, Optional, Set

from engine.world.emergent.store import EmergentStore, get_emergent_store

logger = logging.getLogger(__name__)

# ══════════════════════════════════════════════════════════════════════
#  CANONICAL GAME CONSTANTS
# ══════════════════════════════════════════════════════════════════════

# The six factions and the city districts are the canonical game lists. We pull
# them from the public copies in ``engine.world.territory`` (identical to
# ``player_state._FACTION_NAMES``) and fall back to a literal mirror so this
# module imports cleanly even in minimal builds.
try:  # pragma: no cover - exercised implicitly by every test
    from engine.world.territory import (
        DISTRICT_NAMES as _CANON_DISTRICTS,
        FACTION_NAMES as _CANON_FACTIONS,
    )
except Exception as exc:  # pragma: no cover - defensive import guard
    logger.error(
        "[emergent] canonical faction/district import failed, using mirror "
        "(operation=import_constants): %s",
        exc,
    )
    _CANON_FACTIONS = [
        "OmniCorp", "NeoTech", "BlackMarket", "Ghost_Net", "SynthSec", "DeepState",
    ]
    _CANON_DISTRICTS = [
        "DOWNTOWN", "COMBAT_ZONE", "HIGHRISE", "UNDERWORLD", "TECH_DISTRICT",
        "OUTSKIRTS",
    ]

#: The six canonical faction ids, in declaration order. MUST match
#: ``engine.world.player_state._FACTION_NAMES``.
FACTION_IDS: List[str] = list(_CANON_FACTIONS)

#: The canonical city district ids used for territory. Sourced from
#: ``engine.world.territory.DISTRICT_NAMES`` (the real game list).
DISTRICTS: List[str] = list(_CANON_DISTRICTS)

# Contract check: the player-state faction list is the authority for faction
# identity. We assert (best-effort) that our list still matches it so a future
# rename can't silently desync the emergent engine from the player.
try:  # pragma: no cover - guard only fires on a real desync
    from engine.world.player_state import _FACTION_NAMES as _PS_FACTIONS

    if list(_PS_FACTIONS) != FACTION_IDS:
        logger.error(
            "[emergent] faction id list desynced from player_state "
            "(operation=verify_factions): %s != %s",
            FACTION_IDS, list(_PS_FACTIONS),
        )
except Exception:  # player_state optional in minimal builds
    pass

# Relation kinds.
_REL_ALLY = "ally"
_REL_WAR = "war"
_REL_NEUTRAL = "neutral"

# Config keys + safe defaults (single source of truth for tunables).
_CFG_START_POWER = ("emergent.faction.start_power", 50.0)
_CFG_START_TREASURY = ("emergent.faction.start_treasury", 1000)
_CFG_FLIP_DELTA = ("emergent.faction.flip_power_delta", 5.0)
_CFG_RECOVERY_FLOOR = ("emergent.faction.recovery_floor", 15.0)
_CFG_RECOVERY_RATE = ("emergent.faction.recovery_rate", 2.0)

_POWER_MIN = 0.0
_POWER_MAX = 100.0


# ══════════════════════════════════════════════════════════════════════
#  CONFIG HELPER
# ══════════════════════════════════════════════════════════════════════


def _cfg(key_default: tuple[str, Any]) -> Any:
    """Read a config value, falling back to the supplied default.

    Args:
        key_default: A ``(dotted_key, default)`` tuple.

    Returns:
        The configured value, or the default when config is unavailable or
        the key is missing.
    """
    key, default = key_default
    try:
        from engine.config import get_config

        return get_config().get(key, default)
    except Exception as exc:  # config optional in minimal builds
        logger.error(
            "[emergent] config lookup failed, using default (operation=cfg, key=%s): %s",
            key, exc,
        )
        return default


# ══════════════════════════════════════════════════════════════════════
#  FACTION REGISTRY
# ══════════════════════════════════════════════════════════════════════


class FactionRegistry:
    """Living-world faction model backed by an :class:`EmergentStore`.

    Wraps the store's faction/territory/event rows in faction-aware operations:
    seeding, power/treasury/territory/relation accessors, power and treasury
    mutation with bounds, territory flips (with the matching world event and
    power nudges), symmetric relations, and a recovery tick. Every operation is
    defensive — failures log in Oracle format and return safe values.

    Attributes:
        store: The backing :class:`EmergentStore`.
    """

    def __init__(self, store: Optional[EmergentStore] = None) -> None:
        """Initialize the registry over a store.

        Args:
            store: An explicit :class:`EmergentStore` (tests pass an isolated
                temp-path store). When ``None`` the process-wide singleton from
                :func:`~engine.world.emergent.store.get_emergent_store` is used.
        """
        self.store: EmergentStore = store if store is not None else get_emergent_store()
        self._lock = threading.Lock()

    # ── seeding ────────────────────────────────────────────────────────

    def seed_if_empty(self) -> bool:
        """Create the six factions with starting state if none exist yet.

        Each faction starts with the configured power and treasury, an empty
        ``relations`` map, and one home district (the districts are distributed
        round-robin so every district is owned by exactly one faction and none
        is orphaned). Idempotent: if any faction already exists this is a no-op.

        Returns:
            ``True`` if seeding ran, ``False`` if the world was already seeded
            or on failure.
        """
        try:
            with self._lock:
                if self.store.all_factions():
                    return False  # already seeded — idempotent no-op

                start_power = float(_cfg(_CFG_START_POWER))
                start_treasury = int(_cfg(_CFG_START_TREASURY))

                # Round-robin districts → factions (home-district map).
                home: Dict[str, List[str]] = {fid: [] for fid in FACTION_IDS}
                for i, district in enumerate(DISTRICTS):
                    home[FACTION_IDS[i % len(FACTION_IDS)]].append(district)

                for fid in FACTION_IDS:
                    territory = sorted(home[fid])
                    self.store.upsert_faction(
                        fid,
                        power=start_power,
                        treasury=start_treasury,
                        data={"territory": territory, "relations": {}},
                    )
                    for district in territory:
                        self.store.set_territory(district, fid, contested=False)

                logger.info(
                    "[emergent] seeded %d factions across %d districts "
                    "(operation=seed_if_empty)",
                    len(FACTION_IDS), len(DISTRICTS),
                )
                return True
        except Exception as exc:  # never break a caller
            logger.error("[emergent] seed failed (operation=seed_if_empty): %s", exc)
            return False

    # ── accessors ──────────────────────────────────────────────────────

    def power_of(self, fid: str) -> float:
        """Return a faction's current power (``0.0`` if unknown)."""
        f = self.store.get_faction(fid)
        if not f or f.get("power") is None:
            return 0.0
        try:
            return float(f["power"])
        except (TypeError, ValueError):
            return 0.0

    def treasury_of(self, fid: str) -> int:
        """Return a faction's current treasury (``0`` if unknown)."""
        f = self.store.get_faction(fid)
        if not f or f.get("treasury") is None:
            return 0
        try:
            return int(f["treasury"])
        except (TypeError, ValueError):
            return 0

    def territory_of(self, fid: str) -> Set[str]:
        """Return the set of district ids a faction controls.

        Args:
            fid: The faction id.

        Returns:
            A set of district ids (empty if the faction is unknown).
        """
        f = self.store.get_faction(fid)
        if not f:
            return set()
        data = f.get("data") or {}
        terr = data.get("territory") or []
        if isinstance(terr, (list, set, tuple)):
            return {str(d) for d in terr}
        return set()

    def relation(self, a: str, b: str) -> str:
        """Return the relation between two factions.

        Args:
            a: One faction id.
            b: The other faction id.

        Returns:
            ``'ally'``, ``'war'``, or ``'neutral'`` (the default for any
            unrecorded or unknown pair, and for a faction with itself).
        """
        if a == b:
            return _REL_NEUTRAL
        f = self.store.get_faction(a)
        if not f:
            return _REL_NEUTRAL
        relations = (f.get("data") or {}).get("relations") or {}
        kind = relations.get(b, _REL_NEUTRAL)
        return kind if kind in (_REL_ALLY, _REL_WAR, _REL_NEUTRAL) else _REL_NEUTRAL

    # ── power / treasury mutation ──────────────────────────────────────

    def shift_power(self, fid: str, delta: float) -> float:
        """Adjust a faction's power by *delta*, clamped to ``[0, 100]``.

        Args:
            fid: The faction id.
            delta: The signed change to apply.

        Returns:
            The new, clamped power value (``0.0`` if the faction is unknown).
        """
        try:
            with self._lock:
                return self._shift_power_locked(fid, delta)
        except Exception as exc:
            logger.error(
                "[emergent] shift_power failed (operation=shift_power, faction=%s): %s",
                fid, exc,
            )
            return self.power_of(fid)

    def _shift_power_locked(self, fid: str, delta: float) -> float:
        """Apply a clamped power delta (caller must hold ``self._lock``).

        Args:
            fid: The faction id.
            delta: The signed change to apply.

        Returns:
            The new, clamped power value (``0.0`` if the faction is unknown).
        """
        f = self.store.get_faction(fid)
        if not f:
            return 0.0
        current = float(f.get("power") or 0.0)
        new_power = max(_POWER_MIN, min(_POWER_MAX, current + float(delta)))
        self.store.upsert_faction(fid, power=new_power)
        return new_power

    def adjust_treasury(self, fid: str, delta: int) -> int:
        """Adjust a faction's treasury by *delta*, floored at ``0``.

        Args:
            fid: The faction id.
            delta: The signed change (credits) to apply.

        Returns:
            The new, floored treasury value (``0`` if the faction is unknown).
        """
        try:
            with self._lock:
                f = self.store.get_faction(fid)
                if not f:
                    return 0
                current = int(f.get("treasury") or 0)
                new_treasury = max(0, current + int(delta))
                self.store.upsert_faction(fid, treasury=new_treasury)
                return new_treasury
        except Exception as exc:
            logger.error(
                "[emergent] adjust_treasury failed "
                "(operation=adjust_treasury, faction=%s): %s",
                fid, exc,
            )
            return self.treasury_of(fid)

    # ── territory ──────────────────────────────────────────────────────

    def flip_territory(self, district_id: str, new_fid: str, *, by: str = "") -> bool:
        """Reassign a district to *new_fid*, syncing both factions' state.

        Updates the ``territory`` table and both the loser's and winner's
        denormalised territory sets, logs a persistent ``faction_territory``
        world event, and nudges power (loser down, winner up) by
        ``emergent.faction.flip_power_delta``. A flip to the current owner is a
        no-op (no event, no power change).

        Args:
            district_id: The district changing hands.
            new_fid: The faction taking control.
            by: Optional actor attribution recorded on the world event.

        Returns:
            ``True`` on success (or harmless no-op), ``False`` on failure or for
            an unknown ``new_fid``.
        """
        try:
            with self._lock:
                if new_fid not in FACTION_IDS and self.store.get_faction(new_fid) is None:
                    logger.error(
                        "[emergent] flip to unknown faction "
                        "(operation=flip_territory, district=%s, faction=%s)",
                        district_id, new_fid,
                    )
                    return False

                prior = self.store.get_territory(district_id)
                loser = prior.get("faction_id") if prior else None
                if loser == new_fid:
                    return True  # already owned — nothing to do

                # 1) Source of truth: the territory table.
                self.store.set_territory(district_id, new_fid, contested=False)

                # 2) Mirror into both factions' denormalised territory sets.
                if loser:
                    self._remove_from_territory(loser, district_id)
                self._add_to_territory(new_fid, district_id)

                # 3) World event (persistent feed).
                summary = (
                    f"{new_fid} seized {district_id}"
                    + (f" from {loser}" if loser else "")
                )
                self.store.log_event(
                    "faction_territory",
                    by,
                    summary,
                    payload={
                        "district": district_id,
                        "winner": new_fid,
                        "loser": loser,
                        "by": by,
                    },
                    persistent=True,
                )

                # 4) Power nudge: loser down, winner up.
                delta = float(_cfg(_CFG_FLIP_DELTA))
                self._shift_power_locked(new_fid, +delta)
                if loser:
                    self._shift_power_locked(loser, -delta)

                logger.info(
                    "[emergent] %s (operation=flip_territory, by=%s)", summary, by or "?",
                )
                return True
        except Exception as exc:
            logger.error(
                "[emergent] flip_territory failed "
                "(operation=flip_territory, district=%s): %s",
                district_id, exc,
            )
            return False

    def _add_to_territory(self, fid: str, district_id: str) -> None:
        """Add a district to a faction's denormalised territory set."""
        f = self.store.get_faction(fid)
        if not f:
            return
        data = dict(f.get("data") or {})
        terr = set(data.get("territory") or [])
        terr.add(district_id)
        data["territory"] = sorted(terr)
        self.store.upsert_faction(fid, data=data)

    def _remove_from_territory(self, fid: str, district_id: str) -> None:
        """Remove a district from a faction's denormalised territory set."""
        f = self.store.get_faction(fid)
        if not f:
            return
        data = dict(f.get("data") or {})
        terr = set(data.get("territory") or [])
        terr.discard(district_id)
        data["territory"] = sorted(terr)
        self.store.upsert_faction(fid, data=data)

    # ── relations ──────────────────────────────────────────────────────

    def set_relation(self, a: str, b: str, kind: str) -> bool:
        """Set a symmetric relation between two factions.

        The relation is stored on BOTH factions' ``data.relations`` maps so it
        reads the same from either side.

        Args:
            a: One faction id.
            b: The other faction id.
            kind: ``'ally'``, ``'war'``, or ``'neutral'``.

        Returns:
            ``True`` on success, ``False`` on failure or invalid input.
        """
        if a == b:
            return False
        if kind not in (_REL_ALLY, _REL_WAR, _REL_NEUTRAL):
            logger.error(
                "[emergent] invalid relation kind (operation=set_relation, kind=%s)",
                kind,
            )
            return False
        try:
            with self._lock:
                self._set_relation_one(a, b, kind)
                self._set_relation_one(b, a, kind)
                return True
        except Exception as exc:
            logger.error(
                "[emergent] set_relation failed "
                "(operation=set_relation, a=%s, b=%s): %s",
                a, b, exc,
            )
            return False

    def _set_relation_one(self, owner: str, other: str, kind: str) -> None:
        """Write one direction of a relation onto *owner*'s data blob."""
        f = self.store.get_faction(owner)
        if not f:
            return
        data = dict(f.get("data") or {})
        relations = dict(data.get("relations") or {})
        relations[other] = kind
        data["relations"] = relations
        self.store.upsert_faction(owner, data=data)

    def declare_war(self, a: str, b: str) -> bool:
        """Set the relation between two factions to ``'war'`` (symmetric).

        Args:
            a: One faction id.
            b: The other faction id.

        Returns:
            ``True`` on success, ``False`` otherwise.
        """
        return self.set_relation(a, b, _REL_WAR)

    def form_alliance(self, a: str, b: str) -> bool:
        """Set the relation between two factions to ``'ally'`` (symmetric).

        Args:
            a: One faction id.
            b: The other faction id.

        Returns:
            ``True`` on success, ``False`` otherwise.
        """
        return self.set_relation(a, b, _REL_ALLY)

    # ── recovery ───────────────────────────────────────────────────────

    def recovery_tick(self) -> int:
        """Nudge under-powered factions up so the world never flat-lines.

        Any faction whose power is below ``emergent.faction.recovery_floor`` is
        bumped up by ``emergent.faction.recovery_rate`` (clamped to the floor /
        100). Healthy factions are left untouched, and territory is never
        modified — recovery only restores a sliver of power.

        Returns:
            The number of factions nudged this tick.
        """
        try:
            with self._lock:
                floor = float(_cfg(_CFG_RECOVERY_FLOOR))
                rate = float(_cfg(_CFG_RECOVERY_RATE))
                nudged = 0
                for f in self.store.all_factions():
                    power = float(f.get("power") or 0.0)
                    if power < floor:
                        new_power = min(_POWER_MAX, power + rate)
                        self.store.upsert_faction(f["faction_id"], power=new_power)
                        nudged += 1
                if nudged:
                    logger.info(
                        "[emergent] recovery nudged %d faction(s) toward floor=%.1f "
                        "(operation=recovery_tick)",
                        nudged, floor,
                    )
                return nudged
        except Exception as exc:
            logger.error(
                "[emergent] recovery_tick failed (operation=recovery_tick): %s", exc
            )
            return 0


# ══════════════════════════════════════════════════════════════════════
#  MODULE-LEVEL SINGLETON
# ══════════════════════════════════════════════════════════════════════

_registry: Optional[FactionRegistry] = None
_singleton_lock = threading.Lock()


def get_factions() -> FactionRegistry:
    """Return the process-wide :class:`FactionRegistry` singleton.

    Backed by the shared :class:`EmergentStore`. Tests that need isolation
    should construct ``FactionRegistry(store=EmergentStore(path=...))`` directly.

    Returns:
        The shared :class:`FactionRegistry` instance.
    """
    global _registry
    if _registry is None:
        with _singleton_lock:
            if _registry is None:
                _registry = FactionRegistry()
    return _registry
