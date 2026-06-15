"""phone_hack — player→NPC phone hacking (PH-T3, intercept / plant / steal).

This module lets the *player* break into an NPC's phone. It sits on top of the
PH-T1/PH-T2 phone-OS stack and the comms backbone built earlier on this branch:

* :func:`engine.world.phone_os.get_phone_os` supplies the derived stats the
  check needs — the player's :meth:`~engine.world.phone_os.PhoneOS.hack_power`
  (already folding in the equipped cyberdeck/ICE) versus the target NPC's
  :meth:`~engine.world.phone_os.PhoneOS.effective_security` plus
  :meth:`~engine.world.phone_os.PhoneOS.effective_firewall`. Success and a
  ``last_hacked`` stamp are written back through the same accessor.
* :func:`engine.world.comms_log.get_comms_log` is the single source of truth the
  hack reads (``intercept``/``read``), writes to (``plant``), and marks
  observed.
* :func:`engine.world.relationship_effects.apply_observed_effect` applies the
  recoverable standing hit when a breach is *noticed* (on failure).
* :func:`engine.world.player_state.get_player_state` carries the heat, the
  ``hacking`` skill that buffs the attack roll, and the credits a ``steal``
  grants.

Design — **moderate & recoverable stakes** (locked decision)
------------------------------------------------------------
* **The check** reuses a simple ``hack_power + d20`` attack model (mirroring the
  existing :mod:`engine.services.hack_engine` dice idea — a hex-grid minigame is
  the wrong surface for a headless, comms-driven phone breach, so we keep the
  clean skill-check + real comms-log effects rather than fake a puzzle). The
  attack is ``hack_power('user') + skill_weight * hacking_skill + d20`` and the
  defence is ``effective_security(target) + effective_firewall(target) +
  base_difficulty``. ``margin = attack - defence``; success when ``margin >= 0``.
* **Everything is bounded.** An intercept returns at most ``read_limit`` entries;
  a plant writes exactly ONE comms-log entry; a steal grants a small,
  margin-scaled credit reward inside ``[steal_credits_min, steal_credits_max]``.
* **Failure is recoverable.** A failed breach adds a bounded ``fail_heat`` and a
  single bounded standing nudge (``fail_rel_delta``) toward the player from the
  NPC who noticed — never a wipe. Success is *quieter* (``success_heat``).
* **Config-driven.** Every magnitude lives under ``phone.hack.*`` (via
  :func:`engine.config.get_config`) with in-code defaults — nothing tunable is
  hardcoded.
* **Never crashes on missing data.** No phone, no comms, no threads → a graceful
  result dict ("nothing to read"), never an exception. All notable events log in
  the Oracle format ``[phone_hack] ... (operation=...)``.

Usage::

    from content.scenes.phone.phone_hack import hack_phone

    result = hack_phone("aria", action="intercept")
    if result["success"]:
        for thread in result["read"]:
            ...

Version: v1.62.0 [2026-06-15]
Author:  CosySim Team

Change Log:
    v1.62.0 [2026-06-15] — PH-T4: reverse direction — an NPC hacks the PLAYER's
                            phone. NpcHackPlayerService reuses the same
                            hack_power+d20 check math, but flips it: attacker =
                            NPC ``hack_power``, defence = the PLAYER's
                            ``effective_security('user') + effective_firewall('user')``
                            (raised by PH-T2 firewall upgrades, so they ARE the
                            defence). On SUCCESS (moderate, recoverable) the NPC
                            reads the player's recent threads (mark_observed by the
                            attacker) and does at most ONE of leak-or-plant, plus a
                            bounded (player, attacker) standing hit + small heat. On
                            FAILURE the breach is blocked (no effect, ``blocked``
                            flag, optional notification). last_hacked('user') is
                            stamped either way. A rare, hostile-driven trigger
                            (``maybe_npc_hack_player``, config under
                            ``phone.hack.npc.*``) rolls the attempt from a HOSTILE
                            signal (low NPC→player standing / hostile faction);
                            wired into the NPC↔NPC scheduler tick. Surfaces a
                            ``phone_hacked`` / ``message_intercepted`` event + a
                            persisted breach notification (system comms entry).
                            Exposed as the @skill npc_hack_player().
    v1.62.0 [2026-06-15] — PH-T3: initial player→NPC phone hacking. HackPhoneService
                            resolves a config-driven hack_power+d20 vs
                            security+firewall check, then on success performs
                            intercept (bounded read + mark_observed), plant
                            (exactly one comms_log + phone-thread entry), or steal
                            (bounded credit reward); on failure adds bounded heat
                            + a recoverable standing hit. Sets last_hacked either
                            way. Exposed as the @skill(pack="phone_hack")
                            hack_phone() and registered in the SIGNAL phone pack.
"""
from __future__ import annotations

import logging
import random
from typing import Any, Dict, List, Optional

from engine.config import get_config
from engine.skills.skill import skill, SkillCategory

logger = logging.getLogger(__name__)

# ══════════════════════════════════════════════════════════════════════
#  CONSTANTS — config keys + in-code defaults
# ══════════════════════════════════════════════════════════════════════

PLAYER_ID = "user"

# Config root for every tunable magnitude in this module.
_CFG_ROOT = "phone.hack"

# Recognised actions a successful hack can perform.
ACTION_INTERCEPT = "intercept"
ACTION_READ = "read"          # alias of intercept
ACTION_PLANT = "plant"
ACTION_STEAL = "steal"
_VALID_ACTIONS = (ACTION_INTERCEPT, ACTION_READ, ACTION_PLANT, ACTION_STEAL)

# In-code fallbacks mirroring config/default.yaml ``phone.hack.*``.
_DEFAULTS: Dict[str, Any] = {
    "enabled": True,
    "die_sides": 20,
    "skill_weight": 2,
    "base_difficulty": 8,
    "read_limit": 5,
    "steal_credits_min": 40,
    "steal_credits_max": 120,
    "success_heat": 2,
    "fail_heat": 8,
    "fail_rel_delta": -0.08,
}

# ── PH-T4: reverse hack (NPC → PLAYER) ──────────────────────────────────
# Config root for the reverse-direction trigger + magnitudes.
_NPC_CFG_ROOT = "phone.hack.npc"

# Actions the NPC attacker can take on a successful breach of the player.
NPC_ACTION_OBSERVE = "observe"   # always: read + mark_observed (no extra effect)
NPC_ACTION_LEAK = "leak"         # leak one of the player's messages (drop standing)
NPC_ACTION_PLANT = "plant"       # plant ONE message in the player's inbox

# In-code fallbacks mirroring config/default.yaml ``phone.hack.npc.*``. These are
# bounded so a breach is always moderate & recoverable, and the trigger stays a
# rare spice rather than a nuisance.
_NPC_DEFAULTS: Dict[str, Any] = {
    "enabled": True,
    # Reverse check tuning. The attacker is an NPC: no player "hacking" skill on
    # their side, so the attack is purely ``hack_power(attacker) + d<die_sides>``
    # vs the player's defence + ``base_difficulty``.
    "die_sides": 20,
    "base_difficulty": 8,
    "attacker_power_floor": 2,   # NPCs lack offensive software → a small innate floor
    "read_limit": 3,             # max player threads the NPC reads (bounded)
    # Bounded, recoverable consequences of a successful breach.
    "success_heat": 3,           # capped heat the breach adds to the player
    "rel_delta": -0.08,          # bounded (player, attacker) standing hit (recoverable)
    # Trigger gate — keep it RARE.
    "trigger_probability": 0.05,         # P(roll a hack) once an attacker is hostile
    "hostility_standing_threshold": 0.3,  # NPC→player standing at/below this = hostile
    "hostile_factions": [],              # faction ids the player is hostile-standing with
    "faction_hostile_threshold": -40,    # player faction standing at/below this = hostile
}


# ══════════════════════════════════════════════════════════════════════
#  HackPhoneService
# ══════════════════════════════════════════════════════════════════════


class HackPhoneService:
    """Resolve and apply a player→NPC phone hack with moderate, recoverable stakes.

    The service is dependency-light: by default it pulls the process singletons
    (phone-OS, comms-log, player-state, simulation DB), but every collaborator can
    be injected for isolated testing. No collaborator failure may crash a hack —
    each is wrapped and degrades to a safe default.

    Attributes:
        phone_os: PhoneOS accessor for derived stats + ``set_last_hacked``.
        comms: GlobalCommsLog for read/plant/mark_observed.
        rng: Random source for the attack die (injectable for deterministic tests).
    """

    def __init__(
        self,
        *,
        phone_os: Optional[Any] = None,
        comms: Optional[Any] = None,
        player_state: Optional[Any] = None,
        db: Optional[Any] = None,
        phone_db: Optional[Any] = None,
        rng: Optional[random.Random] = None,
    ) -> None:
        """Initialise the service, wiring collaborators lazily.

        Args:
            phone_os: PhoneOS-like accessor. Defaults to the process singleton.
            comms: GlobalCommsLog-like accessor. Defaults to the singleton.
            player_state: PlayerState-like object (heat/skill/credits). Defaults
                to the singleton, resolved lazily so importing stays Flask-free.
            db: Simulation ``Database`` exposing the NPC↔NPC relationship store
                used for the noticed-breach standing hit. Defaults to the
                singleton, resolved lazily.
            phone_db: PhoneDB used to persist a planted message into the NPC's
                phone thread so it shows in the UI. Defaults to the PhoneOS DB.
            rng: Random source for the attack die. Defaults to a fresh
                :class:`random.Random` (system-seeded).
        """
        self._phone_os = phone_os
        self._comms = comms
        self._player_state = player_state
        self._db = db
        self._phone_db = phone_db
        self.rng = rng or random.Random()

    # ── config helper ───────────────────────────────────────────────────

    def _cfg(self, key: str) -> Any:
        """Return ``phone.hack.<key>`` from config, falling back to a default.

        Args:
            key: The leaf key under ``phone.hack`` (e.g. ``"die_sides"``).

        Returns:
            The configured value, or the in-code default from :data:`_DEFAULTS`.
        """
        try:
            return get_config().get(f"{_CFG_ROOT}.{key}", _DEFAULTS.get(key))
        except Exception:
            return _DEFAULTS.get(key)

    # ── lazy collaborators ──────────────────────────────────────────────

    @property
    def phone_os(self) -> Any:
        """Return the PhoneOS accessor, constructing the singleton if needed."""
        if self._phone_os is None:
            from engine.world.phone_os import get_phone_os
            self._phone_os = get_phone_os()
        return self._phone_os

    @property
    def comms(self) -> Any:
        """Return the GlobalCommsLog, constructing the singleton if needed."""
        if self._comms is None:
            from engine.world.comms_log import get_comms_log
            self._comms = get_comms_log()
        return self._comms

    def _ps(self) -> Optional[Any]:
        """Return the PlayerState, or ``None`` if unavailable (never raises)."""
        if self._player_state is not None:
            return self._player_state
        try:
            from engine.world.player_state import get_player_state
            self._player_state = get_player_state()
        except Exception as exc:
            logger.error(
                "[phone_hack] player state unavailable "
                "(operation=player_state): %s", exc,
            )
            self._player_state = None
        return self._player_state

    def _database(self) -> Optional[Any]:
        """Return the simulation Database for standing writes, or ``None``."""
        if self._db is not None:
            return self._db
        try:
            from content.simulation.database.db import Database
            self._db = Database()
        except Exception as exc:
            logger.error(
                "[phone_hack] simulation DB unavailable "
                "(operation=database): %s", exc,
            )
            self._db = None
        return self._db

    def _get_phone_db(self) -> Optional[Any]:
        """Return a PhoneDB for thread persistence, reusing the PhoneOS DB."""
        if self._phone_db is not None:
            return self._phone_db
        try:
            self._phone_db = self.phone_os._get_db()
        except Exception as exc:
            logger.error(
                "[phone_hack] phone DB unavailable (operation=phone_db): %s", exc,
            )
            self._phone_db = None
        return self._phone_db

    # ── public entry point ──────────────────────────────────────────────

    def hack(self, target_id: str, action: str = ACTION_INTERCEPT) -> Dict[str, Any]:
        """Attempt to hack *target_id*'s phone and perform *action* on success.

        Resolves the config-driven check (see :meth:`resolve_check`) then applies
        the outcome. ``last_hacked`` is stamped on the target either way. Result
        is always a plain dict — this method never raises.

        Args:
            target_id: The NPC whose phone is the target.
            action: One of ``'intercept'``/``'read'``, ``'plant'``, ``'steal'``.
                Unknown actions fall back to ``'intercept'``.

        Returns:
            A result dict with at least: ``success`` (bool), ``action`` (str),
            ``target`` (str), ``margin`` (int), ``attack``/``defence`` (int),
            ``heat_delta`` (int), ``rel_delta`` (float), ``message`` (str), and
            the action payload (``read``/``planted``/``stolen``).
        """
        if not bool(self._cfg("enabled")):
            return self._disabled_result(target_id, action)

        action = action if action in _VALID_ACTIONS else ACTION_INTERCEPT
        if action == ACTION_READ:
            action = ACTION_INTERCEPT

        result: Dict[str, Any] = {
            "success": False,
            "action": action,
            "target": target_id,
            "attack": 0,
            "defence": 0,
            "roll": 0,
            "margin": 0,
            "heat_delta": 0,
            "rel_delta": 0.0,
            "read": [],
            "planted": None,
            "stolen": None,
            "message": "",
        }

        try:
            check = self.resolve_check(target_id)
            result.update(check)
            if check["success"]:
                self._on_success(target_id, action, check["margin"], result)
            else:
                self._on_failure(target_id, result)
            # Stamp last_hacked regardless of outcome — a breach was attempted.
            try:
                self.phone_os.set_last_hacked(target_id)
            except Exception:
                # PhoneOS may expose set_last_hacked only via its DB.
                pdb = self._get_phone_db()
                if pdb is not None:
                    pdb.set_last_hacked(target_id)
        except Exception as exc:
            logger.error(
                "[phone_hack] hack crashed, returning safe failure "
                "(operation=hack, target=%s, action=%s): %s",
                target_id, action, exc,
            )
            result["message"] = "Connection lost — the hack fizzled."

        logger.info(
            "[phone_hack] hack resolved (operation=hack, target=%s, action=%s, "
            "success=%s, attack=%d, defence=%d, margin=%d, heat=%+d, rel=%+.3f)",
            target_id, action, result["success"], result["attack"],
            result["defence"], result["margin"], result["heat_delta"],
            result["rel_delta"],
        )
        return result

    # ── the check ───────────────────────────────────────────────────────

    def resolve_check(self, target_id: str) -> Dict[str, Any]:
        """Resolve the hack skill-check for *target_id*.

        Attack = player ``hack_power('user')`` + ``skill_weight`` × hacking-skill
        + a ``d<die_sides>`` roll. Defence = target ``effective_security`` +
        ``effective_firewall`` + ``base_difficulty``. Success when
        ``attack - defence >= 0``.

        Args:
            target_id: The NPC being hacked.

        Returns:
            Dict with ``success`` (bool), ``attack`` (int), ``defence`` (int),
            ``roll`` (int) and ``margin`` (int).
        """
        hack_power = int(self.phone_os.hack_power(PLAYER_ID))
        skill_weight = int(self._cfg("skill_weight") or 0)
        skill_level = self._hacking_skill()
        sides = max(1, int(self._cfg("die_sides") or 20))
        roll = self.rng.randint(1, sides)
        attack = hack_power + skill_weight * skill_level + roll

        security = int(self.phone_os.effective_security(target_id))
        firewall = int(self.phone_os.effective_firewall(target_id))
        base_diff = int(self._cfg("base_difficulty") or 0)
        defence = security + firewall + base_diff

        margin = attack - defence
        return {
            "success": margin >= 0,
            "attack": attack,
            "defence": defence,
            "roll": roll,
            "margin": margin,
        }

    def _hacking_skill(self) -> int:
        """Return the player's ``hacking`` skill level (0 if unavailable)."""
        ps = self._ps()
        if ps is None:
            return 0
        try:
            return int(ps.get_skill("hacking"))
        except Exception:
            return 0

    # ── success ─────────────────────────────────────────────────────────

    def _on_success(
        self, target_id: str, action: str, margin: int, result: Dict[str, Any]
    ) -> None:
        """Apply the success outcome for *action* and the quiet success heat.

        Args:
            target_id: The hacked NPC.
            action: The (normalised) action to perform.
            margin: The check margin (used to scale a steal reward).
            result: The result dict, mutated in place.
        """
        if action == ACTION_INTERCEPT:
            result["read"] = self._do_intercept(target_id)
            n = len(result["read"])
            result["message"] = (
                f"Breach successful — pulled {n} thread(s) off {target_id}'s phone."
                if n else
                f"Breach successful, but {target_id}'s phone had nothing to read."
            )
        elif action == ACTION_PLANT:
            result["planted"] = self._do_plant(target_id)
            result["message"] = (
                f"Breach successful — planted a message on {target_id}'s phone."
                if result["planted"] else
                f"Breach successful, but the plant could not be written."
            )
        elif action == ACTION_STEAL:
            result["stolen"] = self._do_steal(target_id, margin)
            amount = (result["stolen"] or {}).get("credits", 0)
            result["message"] = (
                f"Breach successful — skimmed {amount}cr of intel off {target_id}."
            )

        # Success is quieter than failure.
        heat = int(self._cfg("success_heat") or 0)
        result["heat_delta"] = self._add_heat(heat, reason=f"phone_hack:{action}:{target_id}")
        result["success"] = True

    def _do_intercept(self, target_id: str) -> List[Dict[str, Any]]:
        """Read up to ``read_limit`` of the NPC's comms and mark them observed.

        Args:
            target_id: The NPC whose comms are read.

        Returns:
            A bounded list of comms entry dicts (newest-first); empty when the
            NPC has no comms.
        """
        limit = max(1, int(self._cfg("read_limit") or 1))
        try:
            entries = self.comms.query(participants=[target_id], limit=limit)
        except Exception as exc:
            logger.error(
                "[phone_hack] intercept query failed, nothing to read "
                "(operation=intercept, target=%s): %s", target_id, exc,
            )
            return []
        for entry in entries:
            try:
                self.comms.mark_observed(int(entry["id"]), PLAYER_ID)
            except Exception as exc:
                logger.error(
                    "[phone_hack] mark_observed failed for one entry "
                    "(operation=intercept, target=%s, id=%s): %s",
                    target_id, entry.get("id"), exc,
                )
        logger.info(
            "[phone_hack] intercepted comms (operation=intercept, target=%s, count=%d)",
            target_id, len(entries),
        )
        return entries

    def _do_plant(self, target_id: str) -> Optional[Dict[str, Any]]:
        """Plant exactly ONE spoofed message into the NPC's comms + phone thread.

        The planted entry is logged to the comms backbone with
        ``metadata={'planted': True, 'by': 'user'}`` and is also written to the
        NPC's phone DM thread so it surfaces in the UI. The plant reuses the
        NPC's most recent thread when one exists, else opens the NPC↔player DM.

        Args:
            target_id: The NPC whose phone receives the plant.

        Returns:
            The planted entry summary dict, or ``None`` on failure.
        """
        content = (
            f"[forwarded] meet me at the old terminal, usual time. — burner"
        )
        # Reuse the NPC's most recent thread/channel when available.
        thread_id: Optional[str] = None
        channel = "phone_dm"
        try:
            recent = self.comms.query(participants=[target_id], limit=1)
            if recent:
                thread_id = recent[0].get("thread_id")
                channel = recent[0].get("channel") or channel
        except Exception as exc:
            logger.error(
                "[phone_hack] plant thread lookup failed, using DM default "
                "(operation=plant, target=%s): %s", target_id, exc,
            )

        phone_thread_id: Optional[str] = None
        pdb = self._get_phone_db()
        if thread_id is None and pdb is not None:
            try:
                phone_thread_id = pdb.get_or_create_dm(target_id)
                thread_id = phone_thread_id
            except Exception as exc:
                logger.error(
                    "[phone_hack] plant DM creation failed "
                    "(operation=plant, target=%s): %s", target_id, exc,
                )

        entry_id = -1
        try:
            entry_id = self.comms.log(
                channel,
                PLAYER_ID,
                [target_id],
                content,
                thread_id=thread_id,
                kind="message",
                metadata={"planted": True, "by": PLAYER_ID},
            )
        except Exception as exc:
            logger.error(
                "[phone_hack] plant comms_log write failed "
                "(operation=plant, target=%s): %s", target_id, exc,
            )
            return None
        if entry_id < 0:
            return None

        # Persist to the phone thread so it shows in the UI (best-effort).
        if pdb is not None:
            try:
                tid = phone_thread_id or pdb.get_or_create_dm(target_id)
                pdb.save_message(
                    tid, PLAYER_ID, content,
                    metadata={"planted": True, "by": PLAYER_ID},
                )
            except Exception as exc:
                logger.error(
                    "[phone_hack] plant phone-thread persist failed "
                    "(operation=plant, target=%s): %s", target_id, exc,
                )

        logger.info(
            "[phone_hack] planted message (operation=plant, target=%s, entry_id=%d)",
            target_id, entry_id,
        )
        return {
            "entry_id": entry_id,
            "thread_id": thread_id,
            "channel": channel,
            "content": content,
        }

    def _do_steal(self, target_id: str, margin: int) -> Dict[str, Any]:
        """Grant a bounded, margin-scaled credit reward to the player.

        Args:
            target_id: The NPC being skimmed.
            margin: The check margin; a wider margin nudges toward the cap.

        Returns:
            A dict with the ``credits`` granted and the player's new ``balance``
            (``balance`` is ``None`` if PlayerState is unavailable).
        """
        lo = int(self._cfg("steal_credits_min") or 0)
        hi = int(self._cfg("steal_credits_max") or lo)
        if hi < lo:
            hi = lo
        # Scale within [lo, hi] by margin (0..10 → lo..hi), bounded both ends.
        span = hi - lo
        scaled = lo + int(span * min(1.0, max(0.0, margin / 10.0)))
        amount = max(lo, min(hi, scaled))

        balance: Optional[int] = None
        ps = self._ps()
        if ps is not None:
            try:
                balance = ps.earn_credits(amount, reason=f"phone_hack:steal:{target_id}")
            except Exception as exc:
                logger.error(
                    "[phone_hack] steal credit grant failed "
                    "(operation=steal, target=%s): %s", target_id, exc,
                )
        logger.info(
            "[phone_hack] stole intel (operation=steal, target=%s, credits=%d)",
            target_id, amount,
        )
        return {"credits": amount, "balance": balance}

    # ── failure ─────────────────────────────────────────────────────────

    def _on_failure(self, target_id: str, result: Dict[str, Any]) -> None:
        """Apply the recoverable failure consequences: bounded heat + standing.

        Args:
            target_id: The NPC who noticed the breach.
            result: The result dict, mutated in place.
        """
        heat = int(self._cfg("fail_heat") or 0)
        result["heat_delta"] = self._add_heat(heat, reason=f"phone_hack_fail:{target_id}")
        result["rel_delta"] = self._apply_noticed_standing(target_id)
        result["message"] = (
            f"Breach FAILED — {target_id}'s firewall traced you. "
            f"Heat +{result['heat_delta']}, they trust you less."
        )

    def _apply_noticed_standing(self, target_id: str) -> float:
        """Apply a single bounded standing hit toward the player (NPC noticed).

        Uses :func:`engine.world.relationship_effects.apply_observed_effect` so
        the breach feeds the canonical pair store the rest of the sim reads. The
        magnitude is the bounded ``fail_rel_delta`` — recoverable, never a wipe.

        Args:
            target_id: The NPC whose standing toward the player drops.

        Returns:
            The signed standing delta actually requested (0.0 if no DB / disabled).
        """
        db = self._database()
        if db is None:
            return 0.0
        delta = float(self._cfg("fail_rel_delta") or 0.0)
        if not delta:
            return 0.0
        try:
            from engine.world.relationship_effects import apply_pair_delta
            # A direct, bounded nudge to the (NPC, player) pair — the NPC's
            # standing toward the player after catching the breach.
            apply_pair_delta(db, target_id, PLAYER_ID, delta)
            logger.info(
                "[phone_hack] standing hit applied (operation=failure, target=%s, "
                "delta=%+.3f)", target_id, delta,
            )
            return delta
        except Exception as exc:
            logger.error(
                "[phone_hack] standing hit failed "
                "(operation=failure, target=%s): %s", target_id, exc,
            )
            return 0.0

    # ── shared helpers ──────────────────────────────────────────────────

    def _add_heat(self, amount: int, *, reason: str) -> int:
        """Add *amount* heat via PlayerState, returning the delta actually applied.

        Args:
            amount: Heat points to add (non-negative).
            reason: Context label for the HUD/log.

        Returns:
            The heat delta applied (0 when PlayerState is unavailable or amount
            is non-positive).
        """
        if amount <= 0:
            return 0
        ps = self._ps()
        if ps is None:
            return 0
        try:
            ps.add_heat(amount, reason=reason)
            return amount
        except Exception as exc:
            logger.error(
                "[phone_hack] heat add failed (operation=add_heat, reason=%s): %s",
                reason, exc,
            )
            return 0

    def _disabled_result(self, target_id: str, action: str) -> Dict[str, Any]:
        """Return a no-op result when the feature is disabled in config.

        Args:
            target_id: The requested target.
            action: The requested action.

        Returns:
            A safe, fully-shaped result dict with ``success=False``.
        """
        return {
            "success": False,
            "action": action,
            "target": target_id,
            "attack": 0,
            "defence": 0,
            "roll": 0,
            "margin": 0,
            "heat_delta": 0,
            "rel_delta": 0.0,
            "read": [],
            "planted": None,
            "stolen": None,
            "message": "Phone hacking is disabled.",
        }


# ══════════════════════════════════════════════════════════════════════
#  NpcHackPlayerService — PH-T4 reverse direction (NPC → PLAYER)
# ══════════════════════════════════════════════════════════════════════


class NpcHackPlayerService:
    """Resolve and apply an NPC→PLAYER phone hack — the reverse of PH-T3.

    The check is the SAME ``hack_power + d`` model as :class:`HackPhoneService`,
    only flipped: the attacker is an NPC (``hack_power(attacker)`` plus a small
    innate floor — NPCs have no player ``hacking`` skill), and the defence is the
    PLAYER's ``effective_security('user') + effective_firewall('user')``. Because
    PH-T2 firewall/security upgrades raise those player stats, they ARE the
    defence here — install a firewall upgrade and the same attacker is blocked.

    Stakes are **moderate & recoverable**. On SUCCESS the NPC reads a bounded
    slice of the player's recent threads (mark_observed by the attacker, which
    colours that NPC's future behaviour) and does at most ONE of: leak one of the
    player's messages (a system comms entry exposing it + a bounded standing
    drop) OR plant ONE message in the player's inbox (``metadata.planted``,
    ``by=attacker``). A small bounded heat + standing hit are applied. On FAILURE
    the firewall blocks the breach — nothing material happens, only a logged
    blocked-breach record. ``last_hacked('user')`` is stamped either way.

    The service reuses :class:`HackPhoneService` for its comms/phone/DB
    collaborators and shared helpers (``_do_plant``-style writes, ``_add_heat``,
    ``set_last_hacked`` plumbing) rather than duplicating that code.

    Attributes:
        inner: The wrapped :class:`HackPhoneService` whose collaborators and
            helpers this service reuses.
        rng: Random source for the attack die (injectable for tests).
    """

    def __init__(
        self,
        *,
        phone_os: Optional[Any] = None,
        comms: Optional[Any] = None,
        player_state: Optional[Any] = None,
        db: Optional[Any] = None,
        phone_db: Optional[Any] = None,
        emit: Optional[Any] = None,
        rng: Optional[random.Random] = None,
    ) -> None:
        """Initialise the reverse-hack service, wiring collaborators lazily.

        Args:
            phone_os: PhoneOS-like accessor. Defaults to the process singleton.
            comms: GlobalCommsLog-like accessor. Defaults to the singleton.
            player_state: PlayerState-like object (heat). Defaults to the
                singleton, resolved lazily.
            db: Simulation ``Database`` for the (player, attacker) standing hit.
            phone_db: PhoneDB for planting into the player's inbox + last_hacked.
            emit: Optional ``callable(event, payload)`` used to surface the
                ``phone_hacked`` / ``message_intercepted`` Socket.IO events.
                Best-effort; falls back to the framework emitter when ``None``.
            rng: Random source for the attack die. Defaults to a fresh
                :class:`random.Random`.
        """
        self.rng = rng or random.Random()
        self._emit = emit
        # Reuse PH-T3's collaborators + helpers via composition.
        self.inner = HackPhoneService(
            phone_os=phone_os,
            comms=comms,
            player_state=player_state,
            db=db,
            phone_db=phone_db,
            rng=self.rng,
        )

    # ── config helper ───────────────────────────────────────────────────

    def _cfg(self, key: str) -> Any:
        """Return ``phone.hack.npc.<key>`` from config, with a default.

        Args:
            key: The leaf key under ``phone.hack.npc`` (e.g. ``"read_limit"``).

        Returns:
            The configured value, or the in-code default from :data:`_NPC_DEFAULTS`.
        """
        try:
            return get_config().get(f"{_NPC_CFG_ROOT}.{key}", _NPC_DEFAULTS.get(key))
        except Exception:
            return _NPC_DEFAULTS.get(key)

    # ── public entry point ──────────────────────────────────────────────

    def hack(self, attacker_id: str) -> Dict[str, Any]:
        """Attempt to have *attacker_id* hack the PLAYER's phone.

        Resolves the reverse check (see :meth:`resolve_check`). On success the
        attacker reads the player's recent threads (mark_observed) and performs
        at most ONE of leak-or-plant, plus bounded heat + standing. On failure
        the player's firewall blocks the breach (``blocked=True``).
        ``last_hacked('user')`` is stamped either way. Never raises.

        Args:
            attacker_id: The NPC attacking the player.

        Returns:
            A result dict with at least: ``success`` (bool), ``blocked`` (bool),
            ``attacker`` (str), ``action`` (str), ``attack``/``defence``/``roll``/
            ``margin`` (int), ``heat_delta`` (int), ``rel_delta`` (float),
            ``read`` (list), ``leaked``/``planted`` (dict|None), ``message`` (str).
        """
        result: Dict[str, Any] = {
            "success": False,
            "blocked": False,
            "attacker": attacker_id,
            "target": PLAYER_ID,
            "action": NPC_ACTION_OBSERVE,
            "attack": 0,
            "defence": 0,
            "roll": 0,
            "margin": 0,
            "heat_delta": 0,
            "rel_delta": 0.0,
            "read": [],
            "leaked": None,
            "planted": None,
            "message": "",
        }

        if not bool(self._cfg("enabled")):
            result["message"] = "NPC phone hacking is disabled."
            return result

        try:
            check = self.resolve_check(attacker_id)
            result.update(check)
            if check["success"]:
                self._on_success(attacker_id, result)
            else:
                self._on_blocked(attacker_id, result)
            # Stamp last_hacked on the PLAYER — a breach was attempted.
            try:
                self.inner.phone_os.set_last_hacked(PLAYER_ID)
            except Exception:
                pdb = self.inner._get_phone_db()
                if pdb is not None:
                    pdb.set_last_hacked(PLAYER_ID)
        except Exception as exc:
            logger.error(
                "[phone_hack] npc_hack_player crashed, returning safe failure "
                "(operation=npc_hack, attacker=%s): %s",
                attacker_id, exc,
            )
            result["message"] = "The intrusion fizzled out."

        # Surface the event + persist a breach notification (best-effort).
        self._surface(attacker_id, result)

        logger.info(
            "[phone_hack] npc_hack_player resolved (operation=npc_hack, "
            "attacker=%s, success=%s, blocked=%s, action=%s, attack=%d, "
            "defence=%d, margin=%d, heat=%+d, rel=%+.3f)",
            attacker_id, result["success"], result["blocked"], result["action"],
            result["attack"], result["defence"], result["margin"],
            result["heat_delta"], result["rel_delta"],
        )
        return result

    # ── the (reversed) check ─────────────────────────────────────────────

    def resolve_check(self, attacker_id: str) -> Dict[str, Any]:
        """Resolve the reverse hack check: NPC attack vs PLAYER defence.

        Attack = ``max(hack_power(attacker), attacker_power_floor)`` + a
        ``d<die_sides>`` roll. Defence = the PLAYER's ``effective_security('user')``
        + ``effective_firewall('user')`` + ``base_difficulty`` — so PH-T2 firewall
        upgrades directly raise the defence. Success when ``attack - defence >= 0``.

        Args:
            attacker_id: The NPC attacking the player.

        Returns:
            Dict with ``success`` (bool), ``attack`` (int), ``defence`` (int),
            ``roll`` (int) and ``margin`` (int).
        """
        pos = self.inner.phone_os
        floor = int(self._cfg("attacker_power_floor") or 0)
        power = max(int(pos.hack_power(attacker_id)), floor)
        sides = max(1, int(self._cfg("die_sides") or 20))
        roll = self.rng.randint(1, sides)
        attack = power + roll

        # The PLAYER's defence — raised by PH-T2 firewall/security upgrades.
        security = int(pos.effective_security(PLAYER_ID))
        firewall = int(pos.effective_firewall(PLAYER_ID))
        base_diff = int(self._cfg("base_difficulty") or 0)
        defence = security + firewall + base_diff

        margin = attack - defence
        return {
            "success": margin >= 0,
            "attack": attack,
            "defence": defence,
            "roll": roll,
            "margin": margin,
        }

    # ── success ─────────────────────────────────────────────────────────

    def _on_success(self, attacker_id: str, result: Dict[str, Any]) -> None:
        """Apply the bounded, recoverable success outcome of a breach.

        Always: read a bounded slice of the player's recent threads and mark
        each observed by the attacker. Then at most ONE of leak-or-plant (chosen
        by an RNG coin-flip). Finally a small bounded heat + standing hit.

        Args:
            attacker_id: The breaching NPC.
            result: The result dict, mutated in place.
        """
        result["success"] = True
        result["read"] = self._observe_player(attacker_id)

        # At most ONE side-effect: leak OR plant (never both) — keeps it bounded.
        if self.rng.random() < 0.5:
            result["action"] = NPC_ACTION_LEAK
            result["leaked"] = self._do_leak(attacker_id, result["read"])
        else:
            result["action"] = NPC_ACTION_PLANT
            result["planted"] = self._do_plant_in_inbox(attacker_id)

        heat = int(self._cfg("success_heat") or 0)
        result["heat_delta"] = self.inner._add_heat(
            heat, reason=f"npc_hack:{result['action']}:{attacker_id}"
        )
        result["rel_delta"] = self._apply_standing_hit(attacker_id)

        leak_or_plant = (
            "leaked one of your messages" if result["action"] == NPC_ACTION_LEAK
            else "planted a message in your inbox"
        )
        result["message"] = (
            f"⚠ Your phone was breached by {attacker_id} — they read your "
            f"recent threads and {leak_or_plant}."
        )

    def _observe_player(self, attacker_id: str) -> List[Dict[str, Any]]:
        """Read up to ``read_limit`` of the player's comms, marked by the attacker.

        Args:
            attacker_id: The NPC observer to record on each entry.

        Returns:
            A bounded list of comms entry dicts (newest-first); empty when the
            player has no comms.
        """
        limit = max(1, int(self._cfg("read_limit") or 1))
        try:
            entries = self.inner.comms.query(participants=[PLAYER_ID], limit=limit)
        except Exception as exc:
            logger.error(
                "[phone_hack] npc observe query failed "
                "(operation=npc_observe, attacker=%s): %s", attacker_id, exc,
            )
            return []
        for entry in entries:
            try:
                self.inner.comms.mark_observed(int(entry["id"]), attacker_id)
            except Exception as exc:
                logger.error(
                    "[phone_hack] npc mark_observed failed for one entry "
                    "(operation=npc_observe, attacker=%s, id=%s): %s",
                    attacker_id, entry.get("id"), exc,
                )
        logger.info(
            "[phone_hack] npc observed player comms "
            "(operation=npc_observe, attacker=%s, count=%d)",
            attacker_id, len(entries),
        )
        return entries

    def _do_leak(
        self, attacker_id: str, read: List[Dict[str, Any]]
    ) -> Optional[Dict[str, Any]]:
        """Leak ONE of the player's read messages as an exposing system entry.

        Writes exactly one ``system``-kind comms entry quoting the leaked
        content, tagged ``metadata={'leaked': True, 'by': attacker, ...}`` so the
        rest of the sim (and the Oracle) can see the player's message was exposed.
        A no-op returning ``None`` when there was nothing to read.

        Args:
            attacker_id: The NPC doing the leak.
            read: The bounded slice of player comms just observed.

        Returns:
            The leaked-entry summary dict, or ``None`` when nothing was leaked.
        """
        source = next((e for e in read if (e.get("content") or "").strip()), None)
        if source is None:
            return None
        leaked_content = str(source.get("content") or "")
        snippet = leaked_content if len(leaked_content) <= 140 else leaked_content[:137] + "..."
        content = f"[leaked] {attacker_id} exposed your message: \"{snippet}\""
        entry_id = -1
        try:
            entry_id = self.inner.comms.log(
                "system",
                attacker_id,
                [PLAYER_ID],
                content,
                kind="system",
                metadata={
                    "leaked": True,
                    "by": attacker_id,
                    "source_id": source.get("id"),
                },
            )
        except Exception as exc:
            logger.error(
                "[phone_hack] npc leak write failed "
                "(operation=npc_leak, attacker=%s): %s", attacker_id, exc,
            )
            return None
        if entry_id < 0:
            return None
        logger.info(
            "[phone_hack] npc leaked player message "
            "(operation=npc_leak, attacker=%s, entry_id=%d, source_id=%s)",
            attacker_id, entry_id, source.get("id"),
        )
        return {
            "entry_id": entry_id,
            "source_id": source.get("id"),
            "content": leaked_content,
        }

    def _do_plant_in_inbox(self, attacker_id: str) -> Optional[Dict[str, Any]]:
        """Plant exactly ONE spoofed message into the PLAYER's inbox.

        The planted entry is logged to the comms backbone on ``phone_dm`` with
        ``sender_id=attacker`` and ``metadata={'planted': True, 'by': attacker}``
        and is also written into the player↔attacker phone DM thread so it shows
        in the inbox UI. Exactly one comms entry is written.

        Args:
            attacker_id: The NPC whose spoofed message lands in the inbox.

        Returns:
            The planted-entry summary dict, or ``None`` on failure.
        """
        content = (
            "hey, it's me on a new number — call me back when you can, it's urgent."
        )
        thread_id: Optional[str] = None
        pdb = self.inner._get_phone_db()
        if pdb is not None:
            try:
                thread_id = pdb.get_or_create_dm(attacker_id)
            except Exception as exc:
                logger.error(
                    "[phone_hack] npc plant DM creation failed "
                    "(operation=npc_plant, attacker=%s): %s", attacker_id, exc,
                )

        entry_id = -1
        try:
            entry_id = self.inner.comms.log(
                "phone_dm",
                attacker_id,
                [PLAYER_ID],
                content,
                thread_id=thread_id,
                kind="message",
                metadata={"planted": True, "by": attacker_id},
            )
        except Exception as exc:
            logger.error(
                "[phone_hack] npc plant comms_log write failed "
                "(operation=npc_plant, attacker=%s): %s", attacker_id, exc,
            )
            return None
        if entry_id < 0:
            return None

        # Persist into the player's phone DM thread so it shows in the inbox.
        if pdb is not None:
            try:
                tid = thread_id or pdb.get_or_create_dm(attacker_id)
                pdb.save_message(
                    tid, attacker_id, content,
                    metadata={"planted": True, "by": attacker_id},
                )
            except Exception as exc:
                logger.error(
                    "[phone_hack] npc plant phone-thread persist failed "
                    "(operation=npc_plant, attacker=%s): %s", attacker_id, exc,
                )

        logger.info(
            "[phone_hack] npc planted message in player inbox "
            "(operation=npc_plant, attacker=%s, entry_id=%d)",
            attacker_id, entry_id,
        )
        return {
            "entry_id": entry_id,
            "thread_id": thread_id,
            "channel": "phone_dm",
            "content": content,
        }

    def _apply_standing_hit(self, attacker_id: str) -> float:
        """Apply a single bounded (player, attacker) standing hit (recoverable).

        Uses :func:`engine.world.relationship_effects.apply_pair_delta` so the
        breach feeds the canonical pair store. The magnitude is the bounded
        ``rel_delta`` — recoverable, never a wipe.

        Args:
            attacker_id: The NPC whose standing with the player drops.

        Returns:
            The signed standing delta requested (0.0 when no DB / disabled).
        """
        db = self.inner._database()
        if db is None:
            return 0.0
        delta = float(self._cfg("rel_delta") or 0.0)
        if not delta:
            return 0.0
        try:
            from engine.world.relationship_effects import apply_pair_delta
            apply_pair_delta(db, PLAYER_ID, attacker_id, delta)
            logger.info(
                "[phone_hack] npc breach standing hit "
                "(operation=npc_standing, attacker=%s, delta=%+.3f)",
                attacker_id, delta,
            )
            return delta
        except Exception as exc:
            logger.error(
                "[phone_hack] npc standing hit failed "
                "(operation=npc_standing, attacker=%s): %s", attacker_id, exc,
            )
            return 0.0

    # ── blocked (failure) ────────────────────────────────────────────────

    def _on_blocked(self, attacker_id: str, result: Dict[str, Any]) -> None:
        """Record a blocked breach — the player's firewall held; no effect.

        Args:
            attacker_id: The NPC whose breach was blocked.
            result: The result dict, mutated in place.
        """
        result["blocked"] = True
        result["action"] = NPC_ACTION_OBSERVE
        result["message"] = (
            f"⚠ Breach attempt blocked — {attacker_id} probed your phone but "
            f"your firewall held."
        )
        logger.info(
            "[phone_hack] npc breach BLOCKED by firewall "
            "(operation=npc_blocked, attacker=%s, attack=%d, defence=%d)",
            attacker_id, result["attack"], result["defence"],
        )

    # ── surfacing: event + persisted notification ────────────────────────

    def _surface(self, attacker_id: str, result: Dict[str, Any]) -> None:
        """Emit the phone Socket.IO event(s) + persist a breach notification.

        Emits ``phone_hacked`` always and ``message_intercepted`` when the NPC
        actually read the player's threads, then persists a ``system`` comms
        entry (``metadata.notification='phone_hacked'``) the PH-T5 notifications
        centre can read. Best-effort: surfacing never affects the breach outcome.

        Args:
            attacker_id: The breaching NPC.
            result: The resolved result dict (read-only here).
        """
        payload = {
            "attacker": attacker_id,
            "action": result["action"],
            "blocked": bool(result["blocked"]),
            "success": bool(result["success"]),
        }
        self._emit_event("phone_hacked", payload)
        if result["success"] and result["read"]:
            self._emit_event("message_intercepted", {
                "attacker": attacker_id,
                "count": len(result["read"]),
            })

        # Persist a notification record the UI can read (a system comms entry).
        try:
            self.inner.comms.log(
                "system",
                attacker_id,
                [PLAYER_ID],
                result.get("message") or "Phone breach event.",
                kind="notification",
                metadata={
                    "notification": "phone_hacked",
                    "attacker": attacker_id,
                    "action": result["action"],
                    "blocked": bool(result["blocked"]),
                    "success": bool(result["success"]),
                },
            )
        except Exception as exc:
            logger.error(
                "[phone_hack] breach notification persist failed "
                "(operation=npc_notify, attacker=%s): %s", attacker_id, exc,
            )

    def _emit_event(self, event: str, payload: Dict[str, Any]) -> None:
        """Emit one Socket.IO event via the injected emitter or the framework.

        Args:
            event: The event name (``'phone_hacked'`` / ``'message_intercepted'``).
            payload: The event payload dict.
        """
        if self._emit is not None:
            try:
                self._emit(event, payload)
                return
            except Exception as exc:
                logger.debug("[phone_hack] injected emit failed: %s", exc)
        try:
            from engine.mcp import get_framework
            get_framework().emit_event(event, payload)
        except Exception as exc:
            logger.debug("[phone_hack] framework emit unavailable: %s", exc)


# ══════════════════════════════════════════════════════════════════════
#  TRIGGER — rare, hostile-driven NPC→PLAYER hack attempt (PH-T4)
# ══════════════════════════════════════════════════════════════════════


def _npc_cfg(key: str) -> Any:
    """Return ``phone.hack.npc.<key>`` from config, with an in-code default.

    Args:
        key: The leaf key under ``phone.hack.npc``.

    Returns:
        The configured value, or the default from :data:`_NPC_DEFAULTS`.
    """
    try:
        return get_config().get(f"{_NPC_CFG_ROOT}.{key}", _NPC_DEFAULTS.get(key))
    except Exception:
        return _NPC_DEFAULTS.get(key)


def is_hostile_to_player(
    attacker_id: str,
    *,
    db: Optional[Any] = None,
    player_state: Optional[Any] = None,
) -> bool:
    """Return whether *attacker_id* is currently HOSTILE toward the player.

    An NPC is hostile when EITHER their ``(npc, user)`` relationship standing is
    at/below ``phone.hack.npc.hostility_standing_threshold``, OR the player is in
    bad standing (``<= faction_hostile_threshold``) with one of the NPC's
    configured ``hostile_factions``. Used to gate the rare hack trigger so only
    antagonistic NPCs ever roll an attempt.

    Args:
        attacker_id: The candidate attacker NPC id.
        db: Optional ``Database`` for the standing lookup. Resolved lazily.
        player_state: Optional PlayerState for faction standings. Resolved lazily.

    Returns:
        ``True`` if the NPC is hostile toward the player.
    """
    # 1) Direct NPC→player standing.
    threshold = float(_npc_cfg("hostility_standing_threshold") or 0.0)
    if db is None:
        try:
            from content.simulation.database.db import Database
            db = Database()
        except Exception:
            db = None
    if db is not None:
        try:
            rel = db.get_relationship(attacker_id, PLAYER_ID)
            if rel is not None and rel.get("relationship_level") is not None:
                if float(rel["relationship_level"]) <= threshold:
                    return True
        except Exception as exc:
            logger.debug(
                "[phone_hack] hostility standing lookup failed "
                "(operation=hostility, attacker=%s): %s", attacker_id, exc,
            )

    # 2) Faction hostility — player in bad standing with this NPC's faction(s).
    hostile_factions = list(_npc_cfg("hostile_factions") or [])
    if hostile_factions:
        fac_threshold = int(_npc_cfg("faction_hostile_threshold") or 0)
        if player_state is None:
            try:
                from engine.world.player_state import get_player_state
                player_state = get_player_state()
            except Exception:
                player_state = None
        if player_state is not None:
            try:
                standings = player_state.faction_standings
                for fac in hostile_factions:
                    if int(standings.get(fac, 0)) <= fac_threshold:
                        return True
            except Exception as exc:
                logger.debug(
                    "[phone_hack] faction hostility lookup failed "
                    "(operation=hostility, attacker=%s): %s", attacker_id, exc,
                )
    return False


def maybe_npc_hack_player(
    attacker_id: str,
    *,
    db: Optional[Any] = None,
    player_state: Optional[Any] = None,
    rng: Optional[random.Random] = None,
    service: Optional[NpcHackPlayerService] = None,
    emit: Optional[Any] = None,
) -> Optional[Dict[str, Any]]:
    """Rarely roll an NPC→player hack when *attacker_id* is hostile.

    The gate is two-stage and config-driven so the feature is a spice, not a
    nuisance: the NPC must be hostile (see :func:`is_hostile_to_player`) AND a
    ``phone.hack.npc.trigger_probability`` roll must succeed. Only then is the
    full :meth:`NpcHackPlayerService.hack` resolved. A no-op (returns ``None``)
    when disabled, not hostile, or the probability gate fails. Never raises.

    Args:
        attacker_id: The candidate attacker NPC id.
        db: Optional ``Database`` for standing lookups (shared with the service).
        player_state: Optional PlayerState for faction standings.
        rng: Random source for the probability gate + the attack die.
        service: Optional pre-built :class:`NpcHackPlayerService` (tests).
        emit: Optional Socket.IO emitter forwarded to the service.

    Returns:
        The breach result dict if a hack was rolled, else ``None``.
    """
    if not bool(_npc_cfg("enabled")):
        return None
    rng = rng or random.Random()
    if not is_hostile_to_player(attacker_id, db=db, player_state=player_state):
        return None
    probability = float(_npc_cfg("trigger_probability") or 0.0)
    if probability <= 0.0 or rng.random() >= probability:
        return None
    svc = service or NpcHackPlayerService(
        db=db, player_state=player_state, rng=rng, emit=emit,
    )
    logger.info(
        "[phone_hack] hostile NPC rolled a hack on the player "
        "(operation=trigger, attacker=%s, probability=%.3f)",
        attacker_id, probability,
    )
    return svc.hack(attacker_id)


# ══════════════════════════════════════════════════════════════════════
#  SKILL
# ══════════════════════════════════════════════════════════════════════


@skill(
    pack="phone_hack",
    tags=["game", "phone", "hacking"],
    category=SkillCategory.GAME,
    description="Hack an NPC's phone to intercept, plant, or steal (moderate stakes).",
)
def hack_phone(target_id: str = "", action: str = "intercept") -> Dict[str, Any]:
    """Hack *target_id*'s phone, performing *action* on a successful breach.

    Resolves a ``hack_power + d20`` vs ``security + firewall`` check (config under
    ``phone.hack.*``). On success, ``intercept`` returns and marks-observed a
    bounded slice of the NPC's recent comms, ``plant`` writes exactly one spoofed
    message into their comms + phone thread, and ``steal`` grants a small,
    margin-scaled credit reward. On failure, a bounded amount of heat is added
    and the NPC's standing toward the player drops (recoverable). ``last_hacked``
    is stamped either way. Never raises.

    Args:
        target_id: The NPC whose phone to hack.
        action: One of ``'intercept'``/``'read'``, ``'plant'``, ``'steal'``.
            Defaults to ``'intercept'``.

    Returns:
        The result dict from :meth:`HackPhoneService.hack` (success, action,
        margin, attack/defence, heat/rel deltas, and the action payload).
    """
    if not target_id:
        return {
            "success": False,
            "action": action,
            "target": target_id,
            "message": "Provide a target_id to hack.",
        }
    return HackPhoneService().hack(target_id, action=action)


@skill(
    pack="phone_hack",
    tags=["game", "phone", "hacking"],
    category=SkillCategory.GAME,
    description="Have a hostile NPC hack the PLAYER's phone (firewall-defended, recoverable).",
)
def npc_hack_player(attacker_id: str = "") -> Dict[str, Any]:
    """Have *attacker_id* hack the PLAYER's phone (the reverse of ``hack_phone``).

    Resolves an ``NPC hack_power + d20`` attack vs the PLAYER's
    ``effective_security('user') + effective_firewall('user')`` (config under
    ``phone.hack.npc.*``), so PH-T2 firewall/security upgrades ARE the defence.
    On success (moderate, recoverable) the NPC reads a bounded slice of the
    player's recent threads (mark_observed) and does at most ONE of leak-or-plant,
    plus a small bounded heat + standing hit. On failure the firewall blocks the
    breach (``blocked=True``, no effect). ``last_hacked('user')`` is stamped either
    way, and a ``phone_hacked`` event + breach notification are surfaced. Never
    raises.

    Args:
        attacker_id: The NPC attacking the player's phone.

    Returns:
        The result dict from :meth:`NpcHackPlayerService.hack` (success, blocked,
        attacker, action, attack/defence, heat/rel deltas, read/leaked/planted).
    """
    if not attacker_id:
        return {
            "success": False,
            "blocked": False,
            "attacker": attacker_id,
            "target": PLAYER_ID,
            "message": "Provide an attacker_id (the hostile NPC).",
        }
    return NpcHackPlayerService().hack(attacker_id)
