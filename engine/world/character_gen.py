"""Reusable random character generator + world-population seeding for CosySim.

This module is the reusable "populate the world" layer for the v1.63 Emergent
Engine. It manufactures believable cyberpunk/noir NPCs, persists them through the
existing :class:`~content.simulation.database.db.Database`, gives each one VARIED
personality traits (so the world is not a sea of identical 0.5s), registers them
with the :class:`~engine.world.npc_routines.RoutineManager` so they actually move,
and — crucially — stamps a **canonical faction** (one of the TerritoryManager's
six) onto each NPC's metadata so the emergent agency's ``contest`` verb can fire
LIVE against real territory.

Why metadata, not faction_context
---------------------------------
``engine.agents.interceptors.faction_context._FACTION_CHARACTERS`` uses a DIFFERENT
faction taxonomy (omnicorp/ghost_net/iron_collective/...) that does NOT match the
TerritoryManager's canonical set (OmniCorp/NeoTech/BlackMarket/Ghost_Net/SynthSec/
DeepState). Contests routed through TerritoryManager.shift_control therefore need
a *canonical* id. We store that canonical id on the character's ``metadata.faction``
and read it back via :func:`character_faction`, leaving the legacy interceptor map
untouched.

Reuse-first
-----------
Nothing here re-implements persistence, traits, or routines — it composes the
existing ``Database.create_character`` / ``Database.update_character_state`` /
``RoutineManager.register_npc`` seams. Seeding is IDEMPOTENT: a generated
population is detected via ``metadata.generated`` and only topped up to ``count``.

Usage::

    from engine.world.character_gen import (
        generate_character, seed_generated_population,
        seed_cast_factions, character_faction,
    )

    cid = generate_character(sex="female", faction="NeoTech", archetype="hacker")
    summary = seed_generated_population(count=15, faction_count=10)
    seed_cast_factions()
    fac = character_faction(cid)   # -> "NeoTech"

Version: v1.63.0 [2026-06-15]
Author:  CosySim Team

Change Log:
    v1.63.0 [2026-06-15] — Initial reusable random character generator + seed
                            mechanism (A7 "populate the world"): generate_character
                            with gendered name pools, varied seedable traits, and
                            canonical-faction metadata; idempotent
                            seed_generated_population (15 NPCs, 10 factioned across
                            the 6 canonical factions); seed_cast_factions for the
                            existing cast; character_faction metadata helper.

CONNECTS: Database (characters/character_states), RoutineManager (routines),
          TerritoryManager (canonical faction ids), EmergentAgency (faction read)
CALLED BY: neoncity_scene.on_before_serve (boot seeding), tests
EMITS: Nothing (DB + routine writes only)
"""
from __future__ import annotations

import logging
import random
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

# ──── Canonical factions (MUST match engine.world.territory.FACTION_NAMES) ────
# Imported lazily-by-value here so this stays the single source the agency reads;
# if territory ever grows a faction, this list is derived from it at seed time.
CANONICAL_FACTIONS: List[str] = [
    "OmniCorp",
    "NeoTech",
    "BlackMarket",
    "Ghost_Net",
    "SynthSec",
    "DeepState",
]

# ──── Name pools (tasteful cyberpunk / noir flavour) ────

MALE_FIRST_NAMES: List[str] = [
    "Kane", "Dorian", "Silas", "Vance", "Cassius", "Ezra", "Roman", "Jaxon",
    "Dante", "Lucian", "Cormac", "Ronan", "Thorne", "Magnus", "Caleb", "Dmitri",
    "Soren", "Augustus", "Rhys", "Idris", "Marcus", "Felix", "Orion", "Kai",
]

FEMALE_FIRST_NAMES: List[str] = [
    "Nadia", "Selene", "Vesper", "Ingrid", "Cleo", "Mara", "Zara", "Isolde",
    "Ramona", "Talia", "Sable", "Lena", "Octavia", "Esme", "Veronika", "Cassia",
    "Rowan", "Lux", "Anya", "Delphine", "Sasha", "Mireille", "Juno", "Ivy",
]

SURNAMES: List[str] = [
    "Voss", "Marlowe", "DeLuca", "Vex", "Cross", "Stark", "Kessler", "Nakamura",
    "Reyes", "Sorenson", "Calloway", "Drake", "Volkov", "Sato", "Bishop", "Mercer",
    "Vance", "Holloway", "Castellan", "Okafor", "Petrov", "Lindqvist", "Cain", "Rourke",
]

# ──── Physical pools ────

HAIR_COLORS: List[str] = [
    "jet black", "platinum blonde", "neon teal", "deep crimson", "silver",
    "ash brown", "electric violet", "chrome white", "dark auburn", "midnight blue",
]

EYE_COLORS: List[str] = [
    "amber", "ice blue", "emerald", "steel grey", "hazel", "violet",
    "cybernetic gold", "deep brown", "pale green", "obsidian",
]

HEIGHTS: List[str] = ["5'2", "5'4", "5'6", "5'8", "5'10", "6'0", "6'2", "6'4"]

BODY_TYPES: List[str] = [
    "lean", "athletic", "stocky", "wiry", "curvy", "broad-shouldered",
    "slender", "augmented-muscular",
]

# ──── Archetype pool + archetype → home district mapping ────
# Archetypes match engine.world.npc_routines.ARCHETYPE_SCHEDULES.
ARCHETYPES: List[str] = [
    "bartender", "fixer", "fighter", "hacker", "merchant",
    "guard", "socialite", "crime_boss", "generic",
]

# Sensible home district per archetype (districts match RoutineManager / territory).
ARCHETYPE_DISTRICT: Dict[str, str] = {
    "bartender": "COMBAT_ZONE",
    "fixer": "UNDERWORLD",
    "fighter": "COMBAT_ZONE",
    "hacker": "TECH_DISTRICT",
    "merchant": "DOWNTOWN",
    "guard": "HIGHRISE",
    "socialite": "HIGHRISE",
    "crime_boss": "UNDERWORLD",
    "generic": "DOWNTOWN",
}

# Personality-state traits that get a varied random value per generated NPC.
_TRAIT_KEYS: List[str] = [
    "warmth", "formality", "humor", "flirtiness", "intelligence", "creativity",
]

# ──── Backstory templates (formatted with name / archetype / district) ────
_BACKSTORY_TEMPLATES: List[str] = [
    "{name} clawed up from the {district} gutters and never looks back.",
    "Once a corporate asset, {name} burned that life down and went freelance as a {archetype}.",
    "{name} runs the {district} angles — everyone owes {name} a favour, or soon will.",
    "They say {name} died in the old net crash. They say wrong; {name} just went quiet.",
    "{name} works the {archetype} trade to bankroll a debt that can never be repaid.",
    "Raised in {district}, {name} learned early that loyalty is a currency like any other.",
    "{name} keeps a ledger of every slight. The {archetype} life is just the cover story.",
    "After the {district} riots, {name} chose survival over ideals and hasn't regretted it.",
]


def get_config():
    """Return the process config (thin wrapper so tests can monkeypatch it).

    Returns:
        The shared config object (``engine.config.get_config()``).
    """
    from engine.config import get_config as _gc

    return _gc()


def _cfg(key: str, default: Any) -> Any:
    """Return a ``char_gen.*`` knob from config with a built-in default.

    Args:
        key: Short key under ``char_gen.`` (e.g. ``"population_count"``).
        default: Fallback when config is unavailable or the key is unset.

    Returns:
        The configured value, or ``default``.
    """
    try:
        return get_config().get("char_gen." + key, default)
    except Exception as exc:  # config optional / malformed in minimal builds
        logger.error(
            "[char_gen] config lookup failed, using default (operation=cfg, key=%s): %s",
            key, exc,
        )
        return default


def _get_db():
    """Return a :class:`Database` instance (default path).

    Returns:
        A fresh ``Database`` bound to the configured simulation DB.
    """
    from content.simulation.database.db import Database

    return Database()


def _canonical_factions() -> List[str]:
    """Return the canonical faction ids, preferring TerritoryManager's list.

    Returns:
        The list of canonical faction names (falls back to the module constant
        if territory cannot be imported).
    """
    try:
        from engine.world.territory import FACTION_NAMES

        return list(FACTION_NAMES) or list(CANONICAL_FACTIONS)
    except Exception:
        return list(CANONICAL_FACTIONS)


def generate_character(
    *,
    sex: Optional[str] = None,
    faction: Optional[str] = None,
    archetype: Optional[str] = None,
    rng: Optional[random.Random] = None,
    db: Any = None,
) -> Optional[str]:
    """Generate, persist, and wire up one random NPC.

    Picks a sex (or honours the given one), a gendered name, age, physical
    traits, and an archetype; builds ``metadata`` carrying a generated
    ``backstory``, ``"generated": True``, and (when supplied) a canonical
    ``faction``; tags the character with its archetype + ``"generated"``; writes
    it via ``Database.create_character``; sets VARIED personality-state traits
    (random ``0..1`` per trait, seedable via ``rng``); and registers a routine
    via ``RoutineManager.register_npc`` so the NPC moves.

    Args:
        sex: ``"male"`` or ``"female"``; random when ``None``.
        faction: A canonical faction id to stamp on metadata; ``None`` leaves the
            NPC unaffiliated. Non-canonical values are stored as given (caller's
            responsibility) but a warning is logged.
        archetype: One of :data:`ARCHETYPES`; random when ``None``.
        rng: Optional ``random.Random`` for deterministic generation.
        db: Optional ``Database`` (mainly for tests / isolation); a default
            instance is created when omitted.

    Returns:
        The new character id, or ``None`` if creation failed (defensive).
    """
    rng = rng or random.Random()
    db = db if db is not None else _get_db()

    try:
        sex = (sex or rng.choice(["male", "female"])).lower()
        if sex not in ("male", "female"):
            sex = rng.choice(["male", "female"])

        first_pool = MALE_FIRST_NAMES if sex == "male" else FEMALE_FIRST_NAMES
        name = f"{rng.choice(first_pool)} {rng.choice(SURNAMES)}"

        archetype = archetype if archetype in ARCHETYPES else rng.choice(ARCHETYPES)
        district = ARCHETYPE_DISTRICT.get(archetype, "DOWNTOWN")

        if faction is not None and faction not in _canonical_factions():
            logger.warning(
                "[char_gen] non-canonical faction stored (operation=generate, faction=%s)",
                faction,
            )

        backstory = rng.choice(_BACKSTORY_TEMPLATES).format(
            name=name, archetype=archetype, district=district.replace("_", " ").lower()
        )

        metadata: Dict[str, Any] = {"backstory": backstory, "generated": True}
        if faction:
            metadata["faction"] = faction

        tags = [archetype, "generated"]

        char_id = db.create_character(
            name=name,
            age=rng.randint(21, 55),
            sex=sex,
            hair_color=rng.choice(HAIR_COLORS),
            eye_color=rng.choice(EYE_COLORS),
            height=rng.choice(HEIGHTS),
            body_type=rng.choice(BODY_TYPES),
            tags=tags,
            metadata=metadata,
        )

        # VARIED traits — random per-trait so generated NPCs are not all 0.5.
        traits = {k: round(rng.random(), 4) for k in _TRAIT_KEYS}
        try:
            db.update_character_state(char_id, **traits)
        except Exception as exc:  # state row exists from create_character; defensive
            logger.error(
                "[char_gen] trait update failed (operation=generate, char=%s): %s",
                char_id, exc,
            )

        # Register a routine so the NPC actually moves in the world.
        try:
            from engine.world.npc_routines import get_routine_manager

            get_routine_manager().register_npc(char_id, archetype, district)
        except Exception as exc:
            logger.error(
                "[char_gen] routine register failed (operation=generate, char=%s): %s",
                char_id, exc,
            )

        logger.info(
            "[char_gen] generated NPC (operation=generate, char=%s, sex=%s, archetype=%s, faction=%s)",
            char_id, sex, archetype, faction or "-",
        )
        return char_id
    except Exception as exc:
        logger.error("[char_gen] generation failed (operation=generate): %s", exc)
        return None


def _existing_generated(db: Any) -> List[Dict[str, Any]]:
    """Return all characters whose metadata marks them as generated.

    Args:
        db: The ``Database`` to scan.

    Returns:
        The list of character dicts with ``metadata.generated`` truthy.
    """
    out: List[Dict[str, Any]] = []
    try:
        for ch in db.get_all_characters():
            meta = ch.get("metadata") or {}
            if isinstance(meta, dict) and meta.get("generated"):
                out.append(ch)
    except Exception as exc:
        logger.error("[char_gen] existing-generated scan failed (operation=seed_pop): %s", exc)
    return out


def seed_generated_population(
    *,
    count: int = 15,
    faction_count: int = 10,
    rng: Optional[random.Random] = None,
    db: Any = None,
) -> Dict[str, Any]:
    """Idempotently seed a generated NPC population with canonical factions.

    Detects any existing generated population (via ``metadata.generated``) and
    only TOPS UP to ``count`` — a second call with the same ``count`` creates
    nothing. Newly generated NPCs are mixed-sex; the first ``faction_count`` of
    the *new* NPCs are assigned canonical factions distributed round-robin across
    the six, and the rest are left unaffiliated.

    Args:
        count: Target total generated population.
        faction_count: How many of the newly generated NPCs get a canonical
            faction (clamped to the number actually created).
        rng: Optional ``random.Random`` for deterministic seeding.
        db: Optional ``Database`` (for tests / isolation).

    Returns:
        A summary ``{"created", "factioned", "by_faction", "total"}``.
    """
    rng = rng or random.Random()
    db = db if db is not None else _get_db()

    factions = _canonical_factions()
    existing = _existing_generated(db)
    have = len(existing)
    to_create = max(0, int(count) - have)

    created_ids: List[str] = []
    by_faction: Dict[str, int] = {}
    factioned = 0

    fac_target = max(0, min(int(faction_count), to_create))

    for i in range(to_create):
        # Distribute factions round-robin across the canonical six for the
        # first fac_target new NPCs; the rest stay unaffiliated.
        faction = factions[i % len(factions)] if i < fac_target else None
        sex = "male" if rng.random() < 0.5 else "female"
        cid = generate_character(sex=sex, faction=faction, rng=rng, db=db)
        if cid is None:
            continue
        created_ids.append(cid)
        if faction:
            factioned += 1
            by_faction[faction] = by_faction.get(faction, 0) + 1

    summary = {
        "created": len(created_ids),
        "factioned": factioned,
        "by_faction": by_faction,
        "total": have + len(created_ids),
    }
    logger.info(
        "[char_gen] population seeded (operation=seed_population, created=%d, factioned=%d, total=%d)",
        summary["created"], summary["factioned"], summary["total"],
    )
    return summary


# Sensible canonical factions for the known cast (idempotent assignment).
_CAST_FACTIONS: Dict[str, str] = {
    "mira": "BlackMarket",
    "frankie": "Ghost_Net",
    "viktor": "SynthSec",
    "lola": "NeoTech",
    "aria": "OmniCorp",
}


def seed_cast_factions(*, db: Any = None) -> Dict[str, str]:
    """Assign canonical factions to the existing cast (idempotent).

    Writes a canonical ``metadata.faction`` for each known cast member that does
    not already have one — this is the "faction-seeding fix" that lets the
    established NPCs contest territory. Never overwrites an existing faction.

    Args:
        db: Optional ``Database`` (for tests / isolation).

    Returns:
        A ``{char_id: faction}`` map of the assignments made THIS call (empty
        when everything was already assigned).
    """
    db = db if db is not None else _get_db()
    assigned: Dict[str, str] = {}

    for cid, faction in _CAST_FACTIONS.items():
        try:
            char = db.get_character(cid)
            if char is None:
                continue
            meta = char.get("metadata") or {}
            if not isinstance(meta, dict):
                meta = {}
            if meta.get("faction"):
                continue  # idempotent — never overwrite
            meta["faction"] = faction
            db.update_character(cid, metadata=meta)
            assigned[cid] = faction
        except Exception as exc:
            logger.error(
                "[char_gen] cast faction assign failed (operation=seed_cast, char=%s): %s",
                cid, exc,
            )

    if assigned:
        logger.info(
            "[char_gen] cast factions seeded (operation=seed_cast, count=%d)", len(assigned)
        )
    return assigned


def character_faction(char_id: str, *, db: Any = None) -> Optional[str]:
    """Return a character's canonical faction from metadata, or ``None``.

    This is the single read-side helper the emergent agency uses so that
    ``ctx['faction']`` is a TerritoryManager-compatible id.

    Args:
        char_id: The character id.
        db: Optional ``Database`` (for tests / isolation).

    Returns:
        The canonical faction id stored on ``metadata.faction``, or ``None`` when
        the character is unknown / unaffiliated / on any failure.
    """
    try:
        db = db if db is not None else _get_db()
        char = db.get_character(char_id)
        if not char:
            return None
        meta = char.get("metadata") or {}
        if isinstance(meta, dict):
            fac = meta.get("faction")
            return str(fac) if fac else None
    except Exception as exc:
        logger.error(
            "[char_gen] faction read failed (operation=character_faction, char=%s): %s",
            char_id, exc,
        )
    return None
