"""Oracle comms reading — privacy-budgeted view over the GlobalCommsLog.

OR-T1 "Oracle omniscience": the Oracle "sees all" by reading the
:class:`~engine.world.comms_log.GlobalCommsLog` and turning overheard chatter
(player↔NPC + NPC↔NPC) into cryptic fortunes, genuine intel, and rare autonomous
omens. This module is the *shared* read layer used by the Oracle scene
(``content/scenes/oracle/oracle_scene.py``), the ``read_the_signal`` skill
(``engine/skills/builtin/oracle_skills.py``), and the autonomous
``OracleCompanion`` so the privacy/spoiler budget lives in exactly one place.

Design notes
------------
* **Privacy/spoiler budget.** Everything here is conservative and config-driven
  (``oracle.comms.*``): how often comms are referenced (``fortune_chance``), how
  many entries a single reading may cite (``max_refs`` — a HARD cap, never a
  dump), and how wide a window to scan (``recent_window``).
* **Crypticness.** References are woven cryptically (templated poetic phrasing);
  raw message bodies are never surfaced verbatim — only short, abstracted hints.
* **Consent / sensitivity.** When ``oracle.comms.respect_sensitive`` is on,
  entries flagged sensitive/mature/intimate (via ``metadata`` flags or ``kind``)
  are skipped so private moments stay private.
* **Observation marking.** Every referenced entry is marked
  ``mark_observed(entry_id, 'oracle')`` so the rest of the sim knows the Oracle
  saw it.
* **Defensive.** Any comms-log failure is logged in Oracle format
  (``[oracle] ... (operation=...)``) and degrades gracefully — callers fall back
  to plain atmospheric behaviour, never crash.

Version: v1.62.0 [2026-06-15]
Author:  CosySim Team

Change Log:
    v1.62.0 [2026-06-15] — OR-T1: shared privacy-budgeted comms reader for the
                            Oracle (fortune weaving, signal intel, omens).
"""
from __future__ import annotations

import logging
import random
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)

# Canonical participant ids.
PLAYER_ID = "user"          # the player is 'user' in the comms log / phone DB
ORACLE_OBSERVER = "oracle"  # observer id stamped on every referenced entry
NPC_DM_CHANNEL = "npc_dm"   # NPC↔NPC chatter channel

# Config defaults (mirror config/default.yaml `oracle.comms.*`).
_DEFAULTS: Dict[str, Any] = {
    "fortune_chance": 0.4,
    "max_refs": 2,
    "recent_window": 30,
    "omen_weight": 6,
    "signal_reward_credits": 75,
    "signal_reward_item": "intel_fragment",
    "signal_cooldown_sec": 900,
    "respect_sensitive": True,
}

# metadata flags / kinds that mark an entry as private (skipped or abstracted).
_SENSITIVE_FLAGS = ("sensitive", "mature", "nsfw", "private", "intimate")
_SENSITIVE_KINDS = ("intimate", "nsfw")


# ══════════════════════════════════════════════════════════════════════
#  CONFIG
# ══════════════════════════════════════════════════════════════════════


def get_oracle_comms_config() -> Dict[str, Any]:
    """Return the merged ``oracle.comms.*`` config (defaults + overrides).

    Reads each knob via ``get_config().get("oracle.comms.<key>", default)`` so
    overrides in any profile layer apply. Falls back to module defaults if the
    config system is unavailable (minimal builds / tests).

    Returns:
        A dict with every ``oracle.comms.*`` key resolved to a concrete value.
    """
    cfg = dict(_DEFAULTS)
    try:
        from engine.config import get_config
        gc = get_config()
        for key, default in _DEFAULTS.items():
            cfg[key] = gc.get(f"oracle.comms.{key}", default)
    except Exception as exc:  # config optional
        logger.error(
            "[oracle] comms config lookup failed, using defaults (operation=config): %s",
            exc,
        )
    return cfg


# ══════════════════════════════════════════════════════════════════════
#  SENSITIVITY / PRIVACY
# ══════════════════════════════════════════════════════════════════════


def is_sensitive(entry: Dict[str, Any]) -> bool:
    """Return whether a comms entry is private/sensitive and should be guarded.

    An entry is sensitive when its ``kind`` is intimate/nsfw, or its
    ``metadata`` carries a truthy sensitive/mature/private flag.

    Args:
        entry: A deserialized comms-log entry dict.

    Returns:
        ``True`` if the entry should be skipped or abstracted under the privacy
        budget.
    """
    kind = (entry.get("kind") or "").lower()
    if kind in _SENSITIVE_KINDS:
        return True
    meta = entry.get("metadata") or {}
    if isinstance(meta, dict):
        for flag in _SENSITIVE_FLAGS:
            if meta.get(flag):
                return True
    return False


def _display_name(participant_id: Optional[str]) -> str:
    """Return a human-friendly display name for a participant id.

    Strips a leading ``char-`` prefix and title-cases the remainder; the player
    id renders as ``"you"``.

    Args:
        participant_id: A sender/recipient id, possibly ``None``.

    Returns:
        A short display name suitable for cryptic phrasing.
    """
    if not participant_id:
        return "a stranger"
    if participant_id == PLAYER_ID:
        return "you"
    name = participant_id
    if name.startswith("char-"):
        name = name[len("char-"):]
    return name.replace("_", " ").strip().title() or "a stranger"


# ══════════════════════════════════════════════════════════════════════
#  SELECTION (privacy-budgeted)
# ══════════════════════════════════════════════════════════════════════


def select_entries(
    *,
    log: Any = None,
    max_refs: Optional[int] = None,
    recent_window: Optional[int] = None,
    respect_sensitive: Optional[bool] = None,
) -> List[Dict[str, Any]]:
    """Select up to ``max_refs`` real comms entries for the Oracle to weave.

    Pulls entries about the player plus recent NPC↔NPC chatter, drops sensitive
    entries (when configured), de-duplicates by id, and returns at most
    ``max_refs`` — the HARD privacy cap that prevents a full dump.

    Args:
        log: A comms-log instance (defaults to the process singleton).
        max_refs: Override for the per-reading reference cap.
        recent_window: Override for how many recent entries to scan.
        respect_sensitive: Override for the sensitivity filter.

    Returns:
        A list (0..max_refs) of comms-log entry dicts, newest-first.
    """
    cfg = get_oracle_comms_config()
    cap = int(max_refs if max_refs is not None else cfg["max_refs"])
    window = int(recent_window if recent_window is not None else cfg["recent_window"])
    guard = bool(respect_sensitive if respect_sensitive is not None else cfg["respect_sensitive"])
    if cap <= 0:
        return []

    log = log or _get_log()
    if log is None:
        return []

    pool: List[Dict[str, Any]] = []
    try:
        pool.extend(log.about(PLAYER_ID, limit=window))
    except Exception as exc:
        logger.error("[oracle] comms about(player) failed (operation=select): %s", exc)
    try:
        pool.extend(log.query(channel=NPC_DM_CHANNEL, limit=window))
    except Exception as exc:
        logger.error("[oracle] comms npc_dm query failed (operation=select): %s", exc)

    # De-dup by id, preserving newest-first order, dropping sensitive entries.
    seen: set = set()
    candidates: List[Dict[str, Any]] = []
    for entry in pool:
        eid = entry.get("id")
        if eid in seen:
            continue
        seen.add(eid)
        if guard and is_sensitive(entry):
            continue
        candidates.append(entry)

    if not candidates:
        return []

    # Sample within the cap so readings vary; keep deterministic when cap covers all.
    if len(candidates) <= cap:
        return candidates
    return random.sample(candidates, cap)


# ══════════════════════════════════════════════════════════════════════
#  CRYPTIC WEAVING
# ══════════════════════════════════════════════════════════════════════

_CRYPTIC_TEMPLATES = (
    "{sender} spoke {recipient_poss} name to the rain… trust is a currency that spends both ways.",
    "{sender} and {recipient} traded words in the dark; the city kept the echo for me.",
    "A signal crossed between {sender} and {recipient}. What was hidden is hidden no longer — to me.",
    "{sender} reached toward {recipient} through the static. The data remembers what flesh forgets.",
    "I heard {sender} whisper of {recipient}. Some bonds are wires; some are nooses.",
)


def cryptic_hint(entry: Dict[str, Any]) -> str:
    """Render a single comms entry as a cryptic, abstracted one-liner.

    Never surfaces the raw message body — only the participants, woven into a
    poetic template. Sensitive entries are abstracted to a faceless omen.

    Args:
        entry: A comms-log entry dict.

    Returns:
        A short cryptic string referencing the overheard exchange.
    """
    if is_sensitive(entry):
        return "Two souls met where I do not look closely; even I grant the dark its privacy."

    sender = _display_name(entry.get("sender_id"))
    recipients = entry.get("recipient_ids") or []
    recipient_id = recipients[0] if recipients else None
    recipient = _display_name(recipient_id)
    recipient_poss = "your" if recipient_id == PLAYER_ID else f"{recipient}'s"

    template = random.choice(_CRYPTIC_TEMPLATES)
    return template.format(
        sender=sender, recipient=recipient, recipient_poss=recipient_poss
    )


def weave_into(base_text: str, entries: List[Dict[str, Any]]) -> str:
    """Append cryptic hints for ``entries`` onto a base prophecy/message.

    Marks every woven entry ``mark_observed(id, 'oracle')`` as a side effect.

    Args:
        base_text: The atmospheric fortune/message to extend.
        entries: Comms entries to weave (already budget-capped).

    Returns:
        ``base_text`` with cryptic comms hints appended (or unchanged if none).
    """
    if not entries:
        return base_text
    hints = []
    for entry in entries:
        hints.append(cryptic_hint(entry))
        mark_observed(entry)
    return (base_text.rstrip() + " " + " ".join(hints)).strip()


# ══════════════════════════════════════════════════════════════════════
#  OBSERVATION MARKING
# ══════════════════════════════════════════════════════════════════════


def mark_observed(entry: Dict[str, Any], log: Any = None) -> bool:
    """Mark a comms entry as observed by the Oracle.

    Args:
        entry: A comms-log entry dict (must carry an ``id``).
        log: A comms-log instance (defaults to the process singleton).

    Returns:
        ``True`` if the entry was marked, ``False`` on missing id / failure.
    """
    eid = entry.get("id")
    if eid is None:
        return False
    log = log or _get_log()
    if log is None:
        return False
    try:
        return bool(log.mark_observed(eid, ORACLE_OBSERVER))
    except Exception as exc:
        logger.error(
            "[oracle] mark_observed failed (operation=mark_observed, id=%s): %s", eid, exc
        )
        return False


# ══════════════════════════════════════════════════════════════════════
#  SIGNAL INTEL (read_the_signal sourcing)
# ══════════════════════════════════════════════════════════════════════


def find_signal(
    *,
    log: Any = None,
    recent_window: Optional[int] = None,
    respect_sensitive: Optional[bool] = None,
) -> Optional[Dict[str, Any]]:
    """Derive ONE genuine intel finding from the comms log.

    Tries, in order of value:

    1. **hack_opportunity** — an NPC with low effective phone security who
       appears in recent chatter (a soft target).
    2. **player_interest** — an NPC who has been discussing the player.
    3. **closest_pair** — the NPC↔NPC pair with the highest chatter volume.

    Each finding carries the referenced entries so the caller can mark them
    observed and respect the privacy budget.

    Args:
        log: A comms-log instance (defaults to the process singleton).
        recent_window: Override for the scan window.
        respect_sensitive: Override for the sensitivity filter.

    Returns:
        A finding dict with ``kind``, ``text`` (in-world phrasing), and
        ``entries`` (list, possibly empty); or ``None`` when no comms exist.
    """
    cfg = get_oracle_comms_config()
    window = int(recent_window if recent_window is not None else cfg["recent_window"])
    guard = bool(respect_sensitive if respect_sensitive is not None else cfg["respect_sensitive"])
    log = log or _get_log()
    if log is None:
        return None

    try:
        recent = log.recent(window)
    except Exception as exc:
        logger.error("[oracle] signal recent() failed (operation=find_signal): %s", exc)
        return None
    if guard:
        recent = [e for e in recent if not is_sensitive(e)]
    if not recent:
        return None

    npc_dm = [e for e in recent if (e.get("channel") == NPC_DM_CHANNEL)]

    # 1) hack opportunity — low-security NPC present in recent chatter.
    finding = _find_hack_opportunity(recent)
    if finding:
        return finding

    # 2) an NPC discussing the player.
    finding = _find_player_interest(recent)
    if finding:
        return finding

    # 3) closest NPC↔NPC pair by chatter volume.
    finding = _find_closest_pair(npc_dm)
    if finding:
        return finding

    return None


def _participants(entry: Dict[str, Any]) -> List[str]:
    """Return all participant ids (sender + recipients) for an entry."""
    ids: List[str] = []
    if entry.get("sender_id"):
        ids.append(entry["sender_id"])
    ids.extend(entry.get("recipient_ids") or [])
    return ids


def _find_hack_opportunity(recent: List[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    """Find a low-security NPC active in recent chatter (a hack opportunity).

    Args:
        recent: Recent comms entries (sensitivity already filtered).

    Returns:
        A ``hack_opportunity`` finding, or ``None`` if phone security data is
        unavailable or no soft target appears.
    """
    try:
        from engine.world.phone_os import get_phone_os
        phone_os = get_phone_os()
    except Exception as exc:
        logger.error("[oracle] phone_os unavailable (operation=find_signal): %s", exc)
        return None

    best: Optional[Tuple[str, int, Dict[str, Any]]] = None
    for entry in recent:
        for pid in _participants(entry):
            if pid == PLAYER_ID or pid in ("system",):
                continue
            try:
                sec = phone_os.effective_security(pid)
            except Exception:
                continue
            if best is None or sec < best[1]:
                best = (pid, sec, entry)

    if best is None or best[1] > 2:  # only surface genuinely soft targets
        return None
    pid, sec, entry = best
    name = _display_name(pid)
    return {
        "kind": "hack_opportunity",
        "target_id": pid,
        "security": sec,
        "text": (
            f"The chatter betrays a weakness: {name}'s wall is thin "
            f"(security {sec}). Their signal lies open to one who knows where to push."
        ),
        "entries": [entry],
    }


def _find_player_interest(recent: List[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    """Find an NPC who has been discussing the player.

    Args:
        recent: Recent comms entries (sensitivity already filtered).

    Returns:
        A ``player_interest`` finding, or ``None``.
    """
    for entry in recent:
        sender = entry.get("sender_id")
        if not sender or sender == PLAYER_ID:
            continue
        recipients = entry.get("recipient_ids") or []
        content = (entry.get("content") or "").lower()
        mentions_player = (
            PLAYER_ID in recipients
            or PLAYER_ID in content
            or "you" in content
        )
        # NPC→NPC entry that names the player is the strongest "talking about you".
        if entry.get("channel") == NPC_DM_CHANNEL and PLAYER_ID not in recipients and mentions_player:
            name = _display_name(sender)
            return {
                "kind": "player_interest",
                "subject_id": sender,
                "text": (
                    f"{name} has been speaking your name where they thought no one listened. "
                    f"Interest is a blade with two edges — guard which way it points."
                ),
                "entries": [entry],
            }
    return None


def _find_closest_pair(npc_dm: List[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    """Find the NPC↔NPC pair with the most chatter (the closest pair).

    Args:
        npc_dm: Recent ``npc_dm`` entries (sensitivity already filtered).

    Returns:
        A ``closest_pair`` finding, or ``None`` when there is no NPC↔NPC traffic.
    """
    counts: Dict[Tuple[str, str], int] = {}
    examples: Dict[Tuple[str, str], Dict[str, Any]] = {}
    for entry in npc_dm:
        ids = [p for p in _participants(entry) if p and p != PLAYER_ID and p != "system"]
        ids = sorted(set(ids))
        for i in range(len(ids)):
            for j in range(i + 1, len(ids)):
                key = (ids[i], ids[j])
                counts[key] = counts.get(key, 0) + 1
                examples.setdefault(key, entry)
    if not counts:
        return None
    pair, volume = max(counts.items(), key=lambda kv: kv[1])
    a, b = _display_name(pair[0]), _display_name(pair[1])
    return {
        "kind": "closest_pair",
        "pair": list(pair),
        "volume": volume,
        "text": (
            f"The densest thread in the dark binds {a} and {b} — "
            f"{volume} exchanges and counting. Where two grow close, a third becomes a stranger."
        ),
        "entries": [examples[pair]],
    }


# ══════════════════════════════════════════════════════════════════════
#  INTERNAL
# ══════════════════════════════════════════════════════════════════════


def _get_log() -> Any:
    """Return the process comms-log singleton, or ``None`` on failure."""
    try:
        from engine.world.comms_log import get_comms_log
        return get_comms_log()
    except Exception as exc:
        logger.error("[oracle] comms log unavailable (operation=get_log): %s", exc)
        return None
