"""Oracle skill pack — comms-sourced intel (OR-T1).

The Oracle "sees all": it reads the :class:`~engine.world.comms_log.GlobalCommsLog`
and turns overheard chatter into genuine, in-world intel. This pack exposes that
power as ``@skill`` tools so LLM agents and the game engine can ask the Oracle to
"read the signal".

Findings are real (sourced from the log via
:mod:`engine.world.oracle_comms`): the closest NPC pair by chatter volume, an NPC
discussing the player, or a low-security hack opportunity. A small, bounded
reward (credits + an intel item) is granted, gated by the skill cooldown/cost and
``oracle.comms.*`` config. Everything is conservative, cryptic, and privacy-aware.

Version: v1.62.0 [2026-06-15]
Author:  CosySim Team

Change Log:
    v1.62.0 [2026-06-15] — OR-T1: initial oracle pack with read_the_signal.

CONNECTS: engine.world.oracle_comms, GlobalCommsLog, PhoneOS, PlayerState
CALLED BY: LMStudio act(), Oracle scene, AgentGovernor
EMITS: human-readable intel strings
"""
from __future__ import annotations

import logging

from engine.skills.skill import SkillCategory, skill

logger = logging.getLogger(__name__)


def _player():
    """Lazy PlayerState accessor (avoids import cycles at module load)."""
    from engine.world.player_state import get_player_state
    return get_player_state()


# ──── Skills ───────────────────────────────────────────────────────────────────


@skill(
    pack="oracle",
    description=(
        "Ask the Oracle to read the city's comms streams and surface ONE genuine "
        "piece of intel — the closest NPC pair, an NPC discussing the player, or a "
        "low-security hack opportunity — granting a small bounded reward."
    ),
    category=SkillCategory.GAME,
    cooldown=900.0,
    cost=2.0,
    tags=["oracle", "intel", "comms", "recon"],
)
def read_the_signal() -> str:
    """Surface a genuine intel finding sourced from the comms log.

    Reads the GlobalCommsLog (player↔NPC + NPC↔NPC chatter) via
    :func:`engine.world.oracle_comms.find_signal`, marks the referenced entries
    observed by ``'oracle'``, and grants a small bounded reward (credits + an
    intel item) gated by ``oracle.comms.*`` config. Phrasing is in-world and
    useful but never a raw dump.

    Returns:
        A human-readable intel string. If no comms exist yet, an in-world
        message saying the streams are silent (no reward granted).
    """
    from engine.world import oracle_comms

    try:
        finding = oracle_comms.find_signal()
    except Exception as exc:
        logger.error("[oracle] read_the_signal failed (operation=read_the_signal): %s", exc)
        return "The streams writhe and refuse me. Return when the static settles."

    if not finding:
        logger.info(
            "[oracle] read_the_signal: no comms to read (operation=read_the_signal)"
        )
        return (
            "Silence. The city's channels lie still tonight — there is nothing for me "
            "to read. Stir the waters and ask again."
        )

    # Mark every referenced entry observed by the Oracle (privacy/audit trail).
    for entry in finding.get("entries", []):
        oracle_comms.mark_observed(entry)

    reward_text = _grant_signal_reward()
    logger.info(
        "[oracle] read_the_signal: %s finding (operation=read_the_signal, refs=%d)",
        finding.get("kind"), len(finding.get("entries", [])),
    )

    text = finding["text"]
    if reward_text:
        text = f"{text} {reward_text}"
    return text


# ──── Reward (bounded) ──────────────────────────────────────────────────────────


def _grant_signal_reward() -> str:
    """Grant the bounded read_the_signal reward (credits + intel item).

    Amounts come from ``oracle.comms.signal_reward_credits`` and
    ``oracle.comms.signal_reward_item``; ``0`` / ``""`` disable each half.

    Returns:
        A short in-world string describing the reward, or ``""`` if nothing was
        granted (or the grant failed).
    """
    from engine.world import oracle_comms

    cfg = oracle_comms.get_oracle_comms_config()
    credits = int(cfg.get("signal_reward_credits", 0) or 0)
    item = (cfg.get("signal_reward_item") or "").strip()

    parts = []
    try:
        ps = _player()
        if credits > 0:
            ps.earn_credits(credits, reason="oracle_read_the_signal")
            parts.append(f"+₵{credits}")
        if item:
            ps.add_item(item)
            label = item.replace("_", " ")
            article = "an" if label[:1].lower() in "aeiou" else "a"
            parts.append(f"{article} {label}")
    except Exception as exc:
        logger.error(
            "[oracle] signal reward grant failed (operation=read_the_signal): %s", exc
        )
        return ""

    if not parts:
        return ""
    return f"(The Oracle leaves you {', '.join(parts)}.)"
