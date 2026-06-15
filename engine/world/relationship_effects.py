"""relationship_effects — pairwise NPC↔NPC relationship drift (CB-T6).

This module closes the loop opened by CB-T3's NPC↔NPC scheduler
(:mod:`engine.world.npc_comms`): each autonomous exchange now *changes* how the
two NPCs feel about each other. Friendly (warm-tone / affectionate-keyword)
exchanges raise the pair's ``character_relationships.relationship_level``;
hostile (cool-tone / negative-keyword) ones lower it. Because CB-T3 selection
already reads ``relationship_level`` as a pair-affinity signal, close pairs
gradually talk more and become more likely to escalate to a live LLM turn,
while soured pairs drift apart.

Design
------
* **Canonical write path.** Deltas are applied via
  :meth:`Database.get_or_create_relationship` +
  :meth:`Database.update_relationship` — the same mutual (order-independent,
  ``0.0``–``1.0``) store CB-T3 reads. We never write the column directly.
* **Small, config-driven deltas.** Magnitudes live under
  ``comms.npc.relationship.*`` so affinity drifts over many exchanges rather
  than snapping. The net per-exchange delta is the tone delta plus an optional
  keyword bonus/penalty, capped by ``max_step`` and clamped to
  ``[min_level, max_level]``.
* **Keyword reuse.** Positive/negative keyword sets are derived from
  :class:`~engine.agents.interceptors.relationship_event.RelationshipEventInterceptor`'s
  ``_INTERACTION_BUFFS`` (kiss/cuddle/apologize → +, argue/insult/yell → −) so
  the NPC↔NPC affect model stays consistent with the player↔NPC one rather than
  inventing a parallel vocabulary.
* **Forward-compat hook.** :func:`apply_observed_effect` is a thin wrapper over
  the same delta logic for the future hacking/oracle work (SP3/SP4): a standing
  change applied to an observer's feeling *about* a third party from OBSERVED
  content. No observation plumbing is built here.

Version: v1.62.0 [2026-06-15]
Author:  CosySim Team

Change Log:
    v1.62.0 [2026-06-15] — CB-T6: initial pairwise relationship effects.
        Tone+keyword → small clamped delta applied to the pair's
        relationship_level via the canonical Database write path; called from
        npc_comms.run_exchange for both template and LLM exchanges. Adds the
        apply_observed_effect forward-compat hook for SP3/SP4.
"""
from __future__ import annotations

import logging
from typing import Any, Optional

logger = logging.getLogger(__name__)

# ══════════════════════════════════════════════════════════════════════
#  DEFAULTS  (mirrored in config/default.yaml under comms.npc.relationship)
# ══════════════════════════════════════════════════════════════════════

_DEFAULT_ENABLED = True
_DEFAULT_WARM_DELTA = 0.02
_DEFAULT_NEUTRAL_DELTA = 0.005
_DEFAULT_COOL_DELTA = -0.02
_DEFAULT_KEYWORD_POSITIVE = 0.015
_DEFAULT_KEYWORD_NEGATIVE = -0.03
_DEFAULT_MAX_STEP = 0.06
_DEFAULT_MIN_LEVEL = 0.0
_DEFAULT_MAX_LEVEL = 1.0

# Tone → which config delta key to use. Keeps the tone vocabulary aligned with
# npc_comms.TEMPLATE_POOL / _affinity_tone ('warm' / 'neutral' / 'cool').
_TONE_KEYS = {
    "warm": "warm_delta",
    "neutral": "neutral_delta",
    "cool": "cool_delta",
}
_TONE_DEFAULTS = {
    "warm": _DEFAULT_WARM_DELTA,
    "neutral": _DEFAULT_NEUTRAL_DELTA,
    "cool": _DEFAULT_COOL_DELTA,
}


def _interaction_keywords() -> tuple[frozenset[str], frozenset[str]]:
    """Derive positive/negative keyword sets from the player↔NPC affect model.

    Reuses :class:`RelationshipEventInterceptor._INTERACTION_BUFFS` so the
    NPC↔NPC vocabulary matches the existing player-facing one: a keyword is
    "positive" when its buff's ``affection`` delta is ``> 0`` and "negative"
    when ``< 0``. Falls back to a small hard-coded set if the interceptor cannot
    be imported (minimal builds).

    Returns:
        A ``(positive_keywords, negative_keywords)`` tuple of frozensets.
    """
    try:
        from engine.agents.interceptors.relationship_event import (
            RelationshipEventInterceptor,
        )
        pos: set[str] = set()
        neg: set[str] = set()
        for keyword, (_suffix, deltas, _dur) in (
            RelationshipEventInterceptor._INTERACTION_BUFFS.items()
        ):
            affection = deltas.get("affection", 0)
            if affection > 0:
                pos.add(keyword)
            elif affection < 0:
                neg.add(keyword)
        if pos or neg:
            return frozenset(pos), frozenset(neg)
    except Exception as exc:  # pragma: no cover - defensive
        logger.debug(
            "[relationship_effects] keyword import failed (operation=keywords): %s",
            exc,
        )
    # Defensive fallback mirroring the interceptor's intent.
    return (
        frozenset({"kiss", "cuddle", "hug", "compliment", "apologize", "flirt"}),
        frozenset({"argue", "insult", "yell"}),
    )


def _cfg(key: str, default: Any) -> Any:
    """Read a ``comms.npc.relationship.<key>`` value via get_config.

    Args:
        key: The leaf config key under ``comms.npc.relationship``.
        default: Value returned when config is unavailable or unset.

    Returns:
        The configured value, or ``default`` on any failure.
    """
    try:
        from engine.config import get_config
        return get_config().get(f"comms.npc.relationship.{key}", default)
    except Exception:
        return default


def classify_tone(content: str, fallback: str = "neutral") -> str:
    """Classify an exchange body into a tone bucket from the template pool.

    Matches ``content`` against :data:`engine.world.npc_comms.TEMPLATE_POOL` so
    the relationship delta reflects the tone of the line actually SENT, not the
    pair's prior affinity (which is how the line was originally selected — using
    that here would make low-affinity pairs spiral and never recover). For LLM
    lines (not in the pool) the caller's ``fallback`` is used, and keyword affect
    in :func:`compute_delta` still applies on top.

    Args:
        content: The exchange body to classify. May be empty.
        fallback: Tone returned when the content is not a known template line.

    Returns:
        One of ``'warm'``, ``'neutral'``, ``'cool'``.
    """
    text = (content or "").strip().lower()
    if text:
        try:
            from engine.world.npc_comms import TEMPLATE_POOL
            for tone, lines in TEMPLATE_POOL.items():
                if any(text == line.strip().lower() for line in lines):
                    return tone
        except Exception:  # pragma: no cover - defensive
            pass
    return fallback


def compute_delta(content: str, tone: str) -> float:
    """Compute the net relationship delta for one exchange.

    The delta combines the template *tone* (warm → +, cool → −, neutral →
    small +) with a keyword affect bonus/penalty detected in ``content`` (reused
    from the player↔NPC keyword model). The result is capped by ``max_step``.

    Args:
        content: The exchange body (template line or LLM output). May be empty.
        tone: One of ``'warm'``, ``'neutral'``, ``'cool'``. Unknown tones are
            treated as ``'neutral'``.

    Returns:
        A signed float delta, capped to ``±max_step``.
    """
    tone_key = _TONE_KEYS.get(tone, "neutral_delta")
    tone_default = _TONE_DEFAULTS.get(tone, _DEFAULT_NEUTRAL_DELTA)
    delta = float(_cfg(tone_key, tone_default))

    text = (content or "").lower()
    if text:
        positives, negatives = _interaction_keywords()
        if any(k in text for k in positives):
            delta += float(_cfg("keyword_positive", _DEFAULT_KEYWORD_POSITIVE))
        if any(k in text for k in negatives):
            delta += float(_cfg("keyword_negative", _DEFAULT_KEYWORD_NEGATIVE))

    max_step = abs(float(_cfg("max_step", _DEFAULT_MAX_STEP)))
    if delta > max_step:
        delta = max_step
    elif delta < -max_step:
        delta = -max_step
    return delta


def apply_pair_delta(db: Any, a: str, b: str, delta: float) -> Optional[float]:
    """Apply a relationship delta to the ``(a, b)`` pair via the canonical store.

    The relationship store is mutual (order-independent) and clamped to
    ``[min_level, max_level]``. Uses :meth:`Database.get_or_create_relationship`
    so an unseeded pair is created at the store default before being nudged, then
    :meth:`Database.update_relationship` to persist the new level.

    Args:
        db: A ``Database`` exposing ``get_or_create_relationship`` and
            ``update_relationship``. ``None`` is a no-op.
        a: First NPC id.
        b: Second NPC id.
        delta: The signed change to apply to ``relationship_level``.

    Returns:
        The new clamped ``relationship_level``, or ``None`` if no write
        happened (db missing, error, or zero delta).
    """
    if db is None or not delta:
        return None
    try:
        rel = db.get_or_create_relationship(a, b)
        current = float((rel or {}).get("relationship_level", 0.5))
        lo = float(_cfg("min_level", _DEFAULT_MIN_LEVEL))
        hi = float(_cfg("max_level", _DEFAULT_MAX_LEVEL))
        new_level = current + delta
        if new_level < lo:
            new_level = lo
        elif new_level > hi:
            new_level = hi
        db.update_relationship(a, b, relationship_level=new_level)
        logger.info(
            "[relationship_effects] pair updated (operation=apply_pair_delta, "
            "a=%s, b=%s, delta=%+.4f, level=%.4f→%.4f)",
            a, b, delta, current, new_level,
        )
        return new_level
    except Exception as exc:
        logger.error(
            "[relationship_effects] pair update failed (operation=apply_pair_delta, "
            "a=%s, b=%s): %s",
            a, b, exc,
        )
        return None


def apply_exchange_effect(
    db: Any, sender: str, recipient: str, content: str, tone: str = "neutral"
) -> Optional[float]:
    """Apply the relationship effect of one NPC↔NPC exchange to the pair.

    The effective tone is classified from ``content`` against the template pool
    (see :func:`classify_tone`) so the delta reflects the tone of the line
    actually sent — a warm line raises affinity even for a currently-distant
    pair, letting soured pairs recover. The supplied ``tone`` is used only as a
    fallback for LLM lines that are not in the pool. The delta (tone + keyword
    affect, see :func:`compute_delta`) is applied mutually to the
    ``(sender, recipient)`` pair (see :func:`apply_pair_delta`). A no-op when the
    feature is disabled via ``comms.npc.relationship.enabled``.

    Args:
        db: The ``Database`` used to read/write the pair relationship.
        sender: The sending NPC id.
        recipient: The receiving NPC id.
        content: The exchange body (template line or LLM output).
        tone: Fallback tone bucket for non-template (LLM) content.

    Returns:
        The new clamped ``relationship_level``, or ``None`` if nothing was
        written (disabled, db missing, or zero delta).
    """
    if not bool(_cfg("enabled", _DEFAULT_ENABLED)):
        return None
    effective_tone = classify_tone(content, fallback=tone)
    delta = compute_delta(content, effective_tone)
    return apply_pair_delta(db, sender, recipient, delta)


def apply_observed_effect(
    db: Any, observer: str, about: str, content: str, tone: str = "neutral"
) -> Optional[float]:
    """Forward-compat hook: apply a standing change from OBSERVED content (SP3/SP4).

    A thin wrapper over the same delta logic for the future hacking/oracle work:
    when ``observer`` learns something ``about`` another character from observed
    content (e.g. an intercepted message), nudge how ``observer`` feels about
    ``about``. No observation plumbing is built here — SP3/SP4 will supply the
    ``content`` and ``tone`` and call this.

    Args:
        db: The ``Database`` used to read/write the pair relationship.
        observer: The character whose feelings change.
        about: The character the standing is about.
        content: The observed content driving the change.
        tone: Optional tone hint; defaults to ``'neutral'``.

    Returns:
        The new clamped ``relationship_level``, or ``None`` if nothing was
        written.
    """
    return apply_exchange_effect(db, observer, about, content, tone)
