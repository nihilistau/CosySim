"""PhoneOS — derived security/capability stats for every phone in CosySim.

This module is the read-side accessor that sits on top of the ``npc_phone``
records owned by :class:`content.scenes.phone.phone_db.PhoneDB`. Where PhoneDB
stores the *base* facts about a phone (os version, installed apps, base
security/firewall), :class:`PhoneOS` computes the *effective* stats a caller
actually needs:

* ``effective_security`` / ``effective_firewall`` — base values plus any bonuses
  granted by installed software/hardware, and (for the player) by equipped
  cyberdeck/ICE via :func:`engine.world.inventory.get_equipment_bonuses`.
* ``hack_power`` — how strong this phone is *as an attacker* (driven by the
  player's cyberdeck crack-speed and offensive software).
* ``app_slots`` — how many apps the phone can hold (base + per-tier bonus).

This is the FOUNDATION for the phone-OS hacking/upgrades sub-project (PH-T2+).
PH-T2 adds the real software/hardware catalog; for now a small, extensible
internal map (:data:`_SOFTWARE_BONUSES`) covers whatever already exists so the
derivation is meaningful today.

Design notes
------------
* All magnitudes are config-driven under ``phone.os.*`` (via
  :func:`engine.config.get_config`) with sane in-code defaults — nothing is
  hardcoded that a designer might want to tune.
* Import-safe without Flask: only stdlib + ``engine.config`` are imported at
  module load; PhoneDB and inventory are imported lazily inside methods.
* Defensive: a phone-OS read must NEVER crash a caller. Every public accessor
  wraps its work and, on failure, logs in the Oracle format
  (``[phone_os] ... (operation=...)``) and returns a safe default.

Usage::

    from engine.world.phone_os import get_phone_os

    pos = get_phone_os()
    pos.ensure_phone("aria")
    sec = pos.effective_security("aria")     # int
    pos.seed_npc_phones(["lola", "viktor"])  # idempotent

Version: v1.62.0 [2026-06-15]
Author:  CosySim Team

Change Log:
    v1.62.0 [2026-06-15] — PH-T1: initial PhoneOS accessor. Wraps PhoneDB
                            ``npc_phone`` records with derived effective
                            security/firewall/hack_power/app_slots, player
                            cyberdeck integration, ``ensure_phone`` and
                            archetype-varied ``seed_npc_phones``. Config-driven
                            magnitudes under ``phone.os.*``; defensive,
                            Flask-free, lazy DB/inventory imports.
"""
from __future__ import annotations

import logging
import threading
from typing import Any, Dict, List, Optional

from engine.config import get_config

logger = logging.getLogger(__name__)

# ══════════════════════════════════════════════════════════════════════
#  CONSTANTS — config keys + in-code defaults
# ══════════════════════════════════════════════════════════════════════

PLAYER_ID = "user"

# Config root for every tunable magnitude in this module.
_CFG_ROOT = "phone.os"

# Default per-installed-software/hardware bonuses. Extensible: PH-T2 replaces
# this with the real upgrade catalog. Keys are ``installed_apps`` entries; each
# maps to the derived stats it boosts. Only items that already exist in the game
# (see engine.world.inventory.ITEM_CATALOG) are listed today.
_SOFTWARE_BONUSES: Dict[str, Dict[str, int]] = {
    # Defensive software → harder to crack / better firewall.
    "shadow_protocol": {"security": 2, "firewall": 1},
    "tracer_kill":     {"firewall": 2},
    # Offensive software → more hacking power.
    "ice_breaker_v1":  {"hack_power": 1},
    "data_mine":       {"hack_power": 1},
    # Generic "firewall app" archetype kept for forward-compat / tests.
    "firewall_app":    {"firewall": 2, "security": 1},
    "security_suite":  {"security": 3, "firewall": 2},
}

# In-code fallbacks for every config-driven magnitude. Mirrors what a designer
# would put under ``phone.os.*`` in config/default.yaml.
_DEFAULTS: Dict[str, Any] = {
    "base_security": 1,
    "base_firewall": 1,
    "base_app_slots": 6,
    "app_slots_per_security": 1,   # extra slots per point of base security
    # Player cyberdeck contribution (inventory.get_equipment_bonuses()).
    "deck_crack_to_hack": 1.0,     # crack_speed → hack_power multiplier
    "deck_trace_to_firewall": 1.0,  # trace_resist → firewall multiplier
    "hacking_bonus_to_hack": 1.0,  # equipment "hacking" bonus → hack_power
    # Seeding: default base-security spread when no archetype is known.
    "seed_security_spread": [1, 2, 3],
    # Archetype → base security override for seeding (optional, extensible).
    "seed_archetype_security": {
        "netrunner": 4,
        "corpo": 3,
        "fixer": 2,
        "civilian": 1,
    },
}


# ══════════════════════════════════════════════════════════════════════
#  PhoneOS
# ══════════════════════════════════════════════════════════════════════


class PhoneOS:
    """Derived-stat accessor over PhoneDB ``npc_phone`` records.

    Instances are cheap; the process normally uses the :func:`get_phone_os`
    singleton. Tests may inject an isolated PhoneDB via the *db* argument.
    """

    def __init__(self, db: Optional[Any] = None) -> None:
        """Initialise the accessor.

        Args:
            db: Optional PhoneDB-like instance. When ``None`` a PhoneDB is
                created lazily on first use (so importing this module never
                touches the filesystem or requires Flask).
        """
        self._db = db
        self._db_lock = threading.Lock()

    # ── config helpers ─────────────────────────────────────────────────

    def _cfg(self, key: str) -> Any:
        """Return ``phone.os.<key>`` from config, falling back to a default.

        Args:
            key: The leaf key under ``phone.os`` (e.g. ``"base_security"``).

        Returns:
            The configured value, or the in-code default from :data:`_DEFAULTS`.
        """
        try:
            return get_config().get(f"{_CFG_ROOT}.{key}", _DEFAULTS.get(key))
        except Exception:
            return _DEFAULTS.get(key)

    # ── DB access ───────────────────────────────────────────────────────

    def _get_db(self) -> Any:
        """Return the backing PhoneDB, constructing one lazily if needed.

        Returns:
            A PhoneDB-like instance.
        """
        if self._db is None:
            with self._db_lock:
                if self._db is None:
                    from content.scenes.phone.phone_db import PhoneDB
                    self._db = PhoneDB()
        return self._db

    # ── record passthrough ──────────────────────────────────────────────

    def get_phone(self, char_id: str) -> Dict[str, Any]:
        """Return the raw phone record for *char_id* (creating a default).

        Args:
            char_id: The character id (``'user'`` for the player).

        Returns:
            The phone record dict, or a synthetic safe-default dict if the DB
            is unavailable.
        """
        try:
            return self._get_db().get_phone(char_id)
        except Exception as exc:
            logger.error(
                "[phone_os] get_phone failed, returning default "
                "(operation=get_phone, char_id=%s): %s",
                char_id, exc,
            )
            return self._default_record(char_id)

    def ensure_phone(self, char_id: str, **base: Any) -> Dict[str, Any]:
        """Ensure *char_id* has a phone record, applying any *base* overrides.

        Idempotent: existing records are preserved; only the supplied *base*
        fields are written. Useful for lazily creating a phone on first access.

        Args:
            char_id: The character id.
            **base: Optional base-field overrides forwarded to
                ``PhoneDB.set_phone_fields`` (e.g. ``security_level=3``).

        Returns:
            The phone record dict.
        """
        try:
            db = self._get_db()
            rec = db.get_phone(char_id)
            if base:
                rec = db.set_phone_fields(char_id, **base)
            return rec
        except Exception as exc:
            logger.error(
                "[phone_os] ensure_phone failed, returning default "
                "(operation=ensure_phone, char_id=%s): %s",
                char_id, exc,
            )
            return self._default_record(char_id, **base)

    # ── derived stats ───────────────────────────────────────────────────

    def effective_security(self, char_id: str) -> int:
        """Return *char_id*'s effective security (base + installed-software).

        Args:
            char_id: The character id.

        Returns:
            The effective security level (always ``>= 0``).
        """
        try:
            rec = self.get_phone(char_id)
            base = int(rec.get("security_level", self._cfg("base_security")) or 0)
            bonus = self._software_bonus(rec, "security")
            bonus += self._player_bonus(char_id, "firewall")  # trace_resist hardens too
            return max(0, base + bonus)
        except Exception as exc:
            logger.error(
                "[phone_os] effective_security failed, returning base default "
                "(operation=effective_security, char_id=%s): %s",
                char_id, exc,
            )
            return int(self._cfg("base_security") or 1)

    def effective_firewall(self, char_id: str) -> int:
        """Return *char_id*'s effective firewall (base + software + deck).

        For the player, the equipped cyberdeck's ``trace_resist`` contributes
        via :func:`engine.world.inventory.get_equipment_bonuses`.

        Args:
            char_id: The character id.

        Returns:
            The effective firewall level (always ``>= 0``).
        """
        try:
            rec = self.get_phone(char_id)
            base = int(rec.get("firewall", self._cfg("base_firewall")) or 0)
            bonus = self._software_bonus(rec, "firewall")
            bonus += self._player_bonus(char_id, "firewall")
            return max(0, base + bonus)
        except Exception as exc:
            logger.error(
                "[phone_os] effective_firewall failed, returning base default "
                "(operation=effective_firewall, char_id=%s): %s",
                char_id, exc,
            )
            return int(self._cfg("base_firewall") or 1)

    def hack_power(self, char_id: str) -> int:
        """Return *char_id*'s offensive hacking power.

        Driven by offensive installed software and — for the player — the
        equipped cyberdeck's ``crack_speed`` and any ``hacking`` equipment
        bonus.

        Args:
            char_id: The character id.

        Returns:
            The hack power (always ``>= 0``).
        """
        try:
            rec = self.get_phone(char_id)
            power = self._software_bonus(rec, "hack_power")
            power += self._player_bonus(char_id, "hack_power")
            return max(0, power)
        except Exception as exc:
            logger.error(
                "[phone_os] hack_power failed, returning 0 "
                "(operation=hack_power, char_id=%s): %s",
                char_id, exc,
            )
            return 0

    def app_slots(self, char_id: str) -> int:
        """Return how many apps *char_id*'s phone can hold.

        Computed as a base slot count plus a per-security-point bonus, so more
        secure phones also tend to be more capable.

        Args:
            char_id: The character id.

        Returns:
            The app slot capacity (always ``>= 1``).
        """
        try:
            rec = self.get_phone(char_id)
            base_slots = int(self._cfg("base_app_slots") or 1)
            per_sec = int(self._cfg("app_slots_per_security") or 0)
            sec = int(rec.get("security_level", 1) or 0)
            return max(1, base_slots + per_sec * sec)
        except Exception as exc:
            logger.error(
                "[phone_os] app_slots failed, returning base default "
                "(operation=app_slots, char_id=%s): %s",
                char_id, exc,
            )
            return int(self._cfg("base_app_slots") or 6)

    # ── seeding ─────────────────────────────────────────────────────────

    def seed_npc_phones(self, npc_ids: List[str]) -> Dict[str, Dict[str, Any]]:
        """Ensure each id in *npc_ids* has a phone with a varied base security.

        Idempotent: an NPC that already has a phone keeps its record (security
        is not overwritten). New phones get a base security derived from the
        NPC's archetype/faction when available (see
        ``phone.os.seed_archetype_security``), else a deterministic value from
        the configured spread (``phone.os.seed_security_spread``) so phones are
        varied but stable across runs.

        Args:
            npc_ids: Character ids to seed phones for.

        Returns:
            Mapping of char_id → phone record dict for every seeded id.
        """
        out: Dict[str, Dict[str, Any]] = {}
        for cid in npc_ids:
            try:
                db = self._get_db()
                existing = None
                for rec in db.list_phones():
                    if rec.get("char_id") == cid:
                        existing = rec
                        break
                if existing is not None:
                    out[cid] = existing
                    continue
                sec = self._seed_security_for(cid)
                fw = max(1, sec)  # firewall tracks base security at seed time
                out[cid] = self.ensure_phone(
                    cid, security_level=sec, firewall=fw,
                )
                logger.info(
                    "[phone_os] seeded NPC phone "
                    "(operation=seed_npc_phones, char_id=%s, security=%d)",
                    cid, sec,
                )
            except Exception as exc:
                logger.error(
                    "[phone_os] seed_npc_phones failed for one NPC "
                    "(operation=seed_npc_phones, char_id=%s): %s",
                    cid, exc,
                )
        return out

    # ── internals ───────────────────────────────────────────────────────

    def _software_bonus(self, rec: Dict[str, Any], stat: str) -> int:
        """Sum the *stat* bonus granted by a record's installed apps.

        Args:
            rec: A phone record dict.
            stat: One of ``"security"``, ``"firewall"``, ``"hack_power"``.

        Returns:
            The summed bonus (0 when no installed app grants *stat*).
        """
        total = 0
        for app in rec.get("installed_apps", []) or []:
            grant = _SOFTWARE_BONUSES.get(app)
            if grant:
                total += int(grant.get(stat, 0))
        return total

    def _player_bonus(self, char_id: str, stat: str) -> int:
        """Return the player's equipment contribution to *stat*.

        Only the player (``char_id == PLAYER_ID``) draws on the inventory; NPCs
        return 0. Uses the equipped cyberdeck stats and aggregate equipment
        bonuses from :func:`engine.world.inventory.get_equipment_bonuses`.

        Args:
            char_id: The character id.
            stat: One of ``"firewall"`` or ``"hack_power"``.

        Returns:
            The contribution from equipped gear (0 for NPCs or on error).
        """
        if char_id != PLAYER_ID:
            return 0
        try:
            from engine.world.inventory import get_inventory
            inv = get_inventory()
            deck = inv.get_cyberdeck_stats()
            bonuses = inv.get_equipment_bonuses()
            if stat == "firewall":
                return int(
                    round(deck.get("trace_resist", 0)
                          * float(self._cfg("deck_trace_to_firewall") or 0))
                )
            if stat == "hack_power":
                from_deck = deck.get("crack_speed", 0) * float(
                    self._cfg("deck_crack_to_hack") or 0)
                from_skill = bonuses.get("hacking", 0) * float(
                    self._cfg("hacking_bonus_to_hack") or 0)
                return int(round(from_deck + from_skill))
            return 0
        except Exception as exc:
            logger.error(
                "[phone_os] player equipment bonus failed, returning 0 "
                "(operation=player_bonus, char_id=%s, stat=%s): %s",
                char_id, stat, exc,
            )
            return 0

    def _seed_security_for(self, char_id: str) -> int:
        """Pick a base security level for a newly-seeded NPC phone.

        Prefers an archetype/faction-driven value when the character registry
        exposes one; otherwise falls back to a deterministic pick from the
        configured spread so the value is varied but stable per character.

        Args:
            char_id: The character id.

        Returns:
            A base security level (always ``>= 1``).
        """
        arch_map = self._cfg("seed_archetype_security") or {}
        archetype = self._lookup_archetype(char_id)
        if archetype and archetype in arch_map:
            return max(1, int(arch_map[archetype]))
        spread = list(self._cfg("seed_security_spread") or [1])
        if not spread:
            spread = [1]
        idx = sum(ord(ch) for ch in char_id) % len(spread)
        return max(1, int(spread[idx]))

    def _lookup_archetype(self, char_id: str) -> Optional[str]:
        """Best-effort archetype/faction lookup for *char_id* from the registry.

        Args:
            char_id: The character id.

        Returns:
            A lowercase archetype string, or ``None`` if unavailable.
        """
        try:
            from engine.mcp.character_registry import get_character_registry
            reg = get_character_registry()
            for key in ("archetype", "faction", "role"):
                val = reg.get_attribute(char_id, key, None)
                if val:
                    return str(val).lower()
        except Exception:
            pass  # registry optional / not populated — fall back to spread
        return None

    def _default_record(self, char_id: str, **base: Any) -> Dict[str, Any]:
        """Return a synthetic safe-default phone record (no DB needed).

        Args:
            char_id: The character id.
            **base: Optional overrides applied on top of the defaults.

        Returns:
            A phone record dict mirroring PhoneDB's default shape.
        """
        rec = {
            "char_id": char_id,
            "enabled": True,
            "os_version": "NeonOS 1.0",
            "installed_apps": [],
            "security_level": int(self._cfg("base_security") or 1),
            "firewall": int(self._cfg("base_firewall") or 1),
            "last_hacked": None,
            "created_at": None,
        }
        rec.update(base)
        return rec


# ══════════════════════════════════════════════════════════════════════
#  MODULE-LEVEL SINGLETON
# ══════════════════════════════════════════════════════════════════════

_phone_os: Optional[PhoneOS] = None
_singleton_lock = threading.Lock()


def get_phone_os() -> PhoneOS:
    """Return the process-wide :class:`PhoneOS` singleton.

    The singleton lazily constructs a default PhoneDB on first use. Tests that
    need isolation should construct ``PhoneOS(db=...)`` directly with an
    isolated PhoneDB instead.

    Returns:
        The shared :class:`PhoneOS` instance.
    """
    global _phone_os
    if _phone_os is None:
        with _singleton_lock:
            if _phone_os is None:
                _phone_os = PhoneOS()
    return _phone_os
