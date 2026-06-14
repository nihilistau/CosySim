"""
Interceptor: StatSyncInterceptor
================================

Post-call interceptor that APPLIES the ``[STAT:name±value]`` tags an agent
emits in its reply to actual character game state.

Before v1.59.0 these tags were parsed into ``ParsedResponse.stat_updates``
and then **discarded** — agents could say ``[STAT:arousal+10]`` but nothing
happened. This interceptor closes that feedback loop: a character's words
now have mechanical consequences, and because it runs at priority 91 (just
before MoodSyncInterceptor at 92), the updated stats are visible to the
threshold-rule auto-evaluation that MoodSync performs.

Tag grammar (case-insensitive stat names):
    [STAT:arousal+10]   → delta  +10
    [STAT:trust-5]      → delta   -5
    [STAT:happiness=70] → set to   70

Only fields known to the CharacterStateCoordinator (STATS_FIELDS +
REGISTRY_FIELDS) are applied; unknown stats are logged and ignored.

Version: v1.59.0 [2026-06-13]
Author:  CosySim Team

Change Log:
    v1.59.0 [2026-06-13] — Initial: apply [STAT:] tags to game state
                            (keystone of the "consequential world" pass)

CONNECTS: ContentRouter.parse_full, CharacterStateCoordinator, EventChain
CALLED BY: InterceptorPipeline.run_post (priority 91)
EMITS: character state updates via state_coordinator; stat_applied EventChain entries
"""
from __future__ import annotations

import logging
import re
from typing import Dict, List, Tuple

from engine.mcp.comms_framework import InterceptorBase, ResponseContext
from engine.mcp.state_coordinator import REGISTRY_FIELDS, STATS_FIELDS

logger = logging.getLogger(__name__)

# name±value or name=value — value is an integer (sign optional)
_RE_STAT = re.compile(r"^\s*([a-zA-Z_]+)\s*([+\-=])\s*(\d+)\s*$")

# Stat names the coordinator knows how to route.
_KNOWN_STATS = STATS_FIELDS | REGISTRY_FIELDS

# Common aliases LLMs emit → canonical field names.
_STAT_ALIASES: Dict[str, str] = {
    "desire": "horniness",
    "lust": "horniness",
    "joy": "happiness",
    "rage": "anger",
    "intoxication": "drunkenness",
    "drunk": "drunkenness",
    "tired": "tiredness",
    "fatigue": "tiredness",
    "love": "affection",
    "bond": "relationship",
}


class StatSyncInterceptor(InterceptorBase):
    """Apply ``[STAT:...]`` tags from a reply to the character's game state."""

    name = "stat_sync"
    priority = 91  # before MoodSync (92) so threshold rules see the new stats

    def post_call(self, ctx: ResponseContext) -> None:
        agent_id = ctx.get("agent_id", "")
        reply = ctx.get("reply", "")
        if not agent_id or not reply:
            return

        # Reuse the canonical parse if a prior interceptor already did it.
        parsed = ctx.get("parsed")
        if parsed is None:
            from engine.agents.content_router import ContentRouter
            parsed = ContentRouter.parse_full(reply)
            ctx["parsed"] = parsed

        raw_updates: List[str] = getattr(parsed, "stat_updates", None) or []
        if not raw_updates:
            return

        delta_fields, set_fields, ignored = self._parse_updates(raw_updates)
        if not delta_fields and not set_fields:
            if ignored:
                logger.debug("StatSyncInterceptor: all stat tags unknown (%s)", ignored)
            return

        # Keep the reply clean (tags already stripped in parsed.content).
        clean = getattr(parsed, "content", "")
        if clean:
            ctx["reply"] = clean

        scene = ctx.get("scene", "")
        try:
            from engine.mcp.state_coordinator import get_coordinator
            coord = get_coordinator()
            if delta_fields:
                coord.update(agent_id, mode="delta", scene=scene,
                             source="stat_tags", **delta_fields)
            if set_fields:
                coord.update(agent_id, mode="set", scene=scene,
                             source="stat_tags", **set_fields)
        except Exception as exc:
            logger.debug("StatSyncInterceptor: coordinator update failed: %s", exc)
            return

        applied = {**delta_fields, **set_fields}
        logger.info(
            "[stat_sync] Applied stat tags (operation=stat_apply, agent=%s, scene=%s): %s%s",
            agent_id, scene or "?", applied,
            f"  (ignored: {ignored})" if ignored else "",
        )

        # Surface to the EventChain / training stream if available.
        try:
            ec = ctx.get("event_chain")
            if ec is not None and hasattr(ec, "add"):
                ec.add("stat_applied", {"agent_id": agent_id, "scene": scene,
                                        "deltas": delta_fields, "sets": set_fields})
        except Exception:
            logger.debug("Suppressed exception", exc_info=True)

    # ── helpers ───────────────────────────────────────────────────────────

    @staticmethod
    def _parse_updates(
        raw_updates: List[str],
    ) -> Tuple[Dict[str, int], Dict[str, int], List[str]]:
        """Split raw [STAT:] strings into delta fields, set fields, ignored.

        Delta fields accumulate (two ``arousal+5`` tags → +10).
        """
        deltas: Dict[str, int] = {}
        sets: Dict[str, int] = {}
        ignored: List[str] = []
        for raw in raw_updates:
            m = _RE_STAT.match(raw)
            if not m:
                ignored.append(raw)
                continue
            stat = m.group(1).lower()
            stat = _STAT_ALIASES.get(stat, stat)
            op = m.group(2)
            value = int(m.group(3))
            if stat not in _KNOWN_STATS:
                ignored.append(raw)
                continue
            if op == "=":
                sets[stat] = value
                deltas.pop(stat, None)
            else:
                signed = value if op == "+" else -value
                if stat in sets:  # an absolute set wins; skip later deltas
                    continue
                deltas[stat] = deltas.get(stat, 0) + signed
        return deltas, sets, ignored
