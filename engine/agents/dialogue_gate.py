"""DialogueGate — reputation-based dialogue filtering interceptor."""
from __future__ import annotations

import logging
from typing import Dict, Optional

from engine.mcp.comms_framework import InterceptorBase, ResponseContext
from engine.mcp import get_framework

logger = logging.getLogger(__name__)


class DialogueGateInterceptor(InterceptorBase):
    """Blocks or modifies NPC dialogue based on player-NPC reputation score.

    Reputation scores live in MCP at: characters.{char_id}.reputation.{player_id}
    Scores range from -100 (hostile) to 100 (devoted).  Default: 0 (neutral).

    Gate thresholds (configurable via config):
      < -50  NPC refuses to engage — sets reply + skip_llm
      < -20  NPC is curt — injects [TONE:hostile] into system_prompt
      -20 to 20  neutral — no modification
      > 20   NPC is warm — injects [TONE:friendly] into system_prompt
      > 50   NPC shares secrets — injects [TONE:intimate] into system_prompt
    """

    name = "dialogue_gate"
    priority = 45  # after CharacterRegistry (8), before PersonalityGuard (50)

    def __init__(self, config: Optional[Dict] = None) -> None:
        self._config = config or {}
        self._thresholds = {
            "refuse":   self._config.get("refuse_threshold", -50),
            "hostile":  self._config.get("hostile_threshold", -20),
            "friendly": self._config.get("friendly_threshold", 20),
            "intimate": self._config.get("intimate_threshold", 50),
        }

    # ──────────────────────────────────────────────────────────────────────────
    #  Pipeline hooks
    # ──────────────────────────────────────────────────────────────────────────

    def pre_call(self, ctx: ResponseContext) -> None:
        char_id = ctx.get("agent_id", "")
        player_id = ctx.get("player_id", "player")
        if not char_id:
            return

        reputation = self._get_reputation(char_id, player_id)

        if reputation < self._thresholds["refuse"]:
            ctx["reply"] = self._refusal_message(char_id, reputation)
            ctx["skip_llm"] = True
            logger.debug("DialogueGate: BLOCKED %s (rep=%d)", char_id, reputation)
            return

        tone = self._get_tone(reputation)
        if tone:
            inject = (
                f"\n[TONE:{tone.upper()}] Your current disposition toward the player"
                f" is {tone}.  Let this colour your wording and willingness to share."
            )
            ctx["system_prompt"] = ctx.get("system_prompt", "") + inject
            logger.debug("DialogueGate: %s tone=%s rep=%d", char_id, tone, reputation)

    def post_call(self, ctx: ResponseContext) -> None:
        # Nothing extra needed — skip_llm already locks the reply in pre_call.
        pass

    # ──────────────────────────────────────────────────────────────────────────
    #  Helpers
    # ──────────────────────────────────────────────────────────────────────────

    def _get_reputation(self, char_id: str, player_id: str) -> int:
        try:
            fw = get_framework()
            return int(fw.get(f"characters.{char_id}.reputation.{player_id}", 0))
        except Exception:
            return 0

    def _get_tone(self, reputation: int) -> Optional[str]:
        if reputation >= self._thresholds["intimate"]:
            return "intimate"
        if reputation >= self._thresholds["friendly"]:
            return "friendly"
        if reputation < self._thresholds["hostile"]:
            return "hostile"
        return None

    def _refusal_message(self, char_id: str, reputation: int) -> str:
        return (
            f"*turns away coldly*  I have nothing to say to you."
            f"  [reputation: {reputation}]"
        )
