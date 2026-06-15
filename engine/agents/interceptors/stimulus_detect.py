"""
Stimulus Detection Interceptor
==============================

Post-call interceptor that closes the neurochemistry feedback loop: it reads
the *actual dialogue text* (both the incoming player/user message and the
agent's reply) and auto-fires neurochemistry stimuli on the relevant
character(s). Before this, the 6-neurotransmitter / 40+-stimulus engine in
``engine.characters.neurochemistry`` only ever moved when a scene/skill called
``apply_stimulus()`` *manually* — agents never affected each other emotionally
from what they actually *said*.

This interceptor detects compliment / insult / kiss / touch / rejection /
threat / comfort / gratitude (etc.) patterns via lightweight keyword + regex
matching (NO LLM call) and maps them onto the existing stimulus catalog names
(see ``STIMULUS_CATALOG`` in ``engine.characters.neurochemistry``).

Two effects are applied per matched pattern:

* **Addressee effect** — what the line *does to* the listener. The agent is the
  addressee of the incoming ``user_message`` (e.g. the player complimented the
  agent → agent receives ``received_compliment``). When a downstream target
  character is known (``ctx["target_id"]``), reply-directed effects land on it.
* **Reflexive (speaker) effect** — what saying the line does to the *speaker*
  (e.g. the agent giving a compliment gets a small ``gave_compliment`` lift).

Runs at **priority 88** — after the reply text is finalized by ResponseShaper
(80) / TTSStyle (85) but *before* MoodSyncInterceptor (92), so the derived mood
that MoodSync pushes to the CharacterRegistry already reflects the chemistry
shift this turn.

All thresholds, intensities and the master enable flag are config-driven via
``get_config().get("neurochemistry.stimulus_detect.*")`` with sensible
defaults — nothing is hardcoded that a tuner would want to change.

Version: v1.60.0 [2026-06-13]
Author:  CosySim Team

Change Log:
    v1.60.0 [2026-06-13] — Initial release. NLP stimulus detection closing the
        neurochemistry feedback loop (Living Systems / v1.60.0 audit finding).
"""
from __future__ import annotations

# ──── Imports ─────────────────────────────────────────────────────────────
import logging
import re
from typing import Dict, List, Optional, Pattern, Tuple

from engine.characters.neurochemistry import (
    STIMULUS_CATALOG,
    get_neurochemistry_manager,
)
from engine.mcp.comms_framework import InterceptorBase, ResponseContext

logger = logging.getLogger(__name__)

# ──── Detection rule model ────────────────────────────────────────────────
# A rule maps a compiled regex to:
#   - addressee_stimulus : stimulus applied to the *listener* of the line
#                          (catalog name, or None to skip)
#   - speaker_stimulus   : stimulus applied to the *speaker* of the line
#                          (catalog name, or None to skip)
# Every stimulus name MUST exist in STIMULUS_CATALOG (validated at construction).


class _StimulusRule:
    """A single text→stimulus detection rule.

    Attributes:
        name: Human-readable label for logging/debugging.
        pattern: Compiled, case-insensitive regex matched against dialogue text.
        addressee_stimulus: Catalog stimulus applied to whoever the line is
            addressed *to* (the listener). ``None`` to apply nothing.
        speaker_stimulus: Catalog stimulus applied to whoever *spoke* the line
            (reflexive). ``None`` to apply nothing.
    """

    __slots__ = ("name", "pattern", "addressee_stimulus", "speaker_stimulus")

    def __init__(
        self,
        name: str,
        pattern: Pattern[str],
        addressee_stimulus: Optional[str],
        speaker_stimulus: Optional[str],
    ) -> None:
        self.name = name
        self.pattern = pattern
        self.addressee_stimulus = addressee_stimulus
        self.speaker_stimulus = speaker_stimulus


def _rx(pattern: str) -> Pattern[str]:
    """Compile a case-insensitive regex with word-boundary friendliness."""
    return re.compile(pattern, re.IGNORECASE)


# ──── Rule catalog ────────────────────────────────────────────────────────
# Ordered list; ALL matching rules fire (a line can be both a compliment and a
# kiss). Stimulus names are reused verbatim from STIMULUS_CATALOG.
#
# Detection is deliberately lightweight (keyword/regex). It favors precision —
# distinctive phrasings — over recall, to avoid spuriously drugging characters
# on every neutral turn.

_RULES: List[_StimulusRule] = [
    # ── Compliment / praise ──
    _StimulusRule(
        "compliment",
        _rx(
            r"\b(you'?re|you are|you look|that'?s)\s+"
            r"(so\s+|really\s+|very\s+|absolutely\s+)?"
            r"(beautiful|gorgeous|stunning|amazing|wonderful|brilliant|"
            r"incredible|perfect|lovely|cute|hot|sexy|smart|clever|talented|"
            r"impressive|kind|sweet|adorable|magnificent)\b"
            r"|\bi\s+(love|adore|admire)\s+(your|how you)\b"
            r"|\bwell\s+done\b|\bgood\s+job\b|\bi'?m\s+proud\s+of\s+you\b"
        ),
        addressee_stimulus="received_compliment",
        speaker_stimulus="gave_compliment",
    ),
    # ── Gratitude / good news → mild positive ──
    _StimulusRule(
        "gratitude",
        _rx(r"\bthank\s+you\b|\bthanks\b|\bi\s+appreciate\b|\bgrateful\b"),
        addressee_stimulus="received_compliment",
        speaker_stimulus=None,
    ),
    # ── Comfort / reassurance ──
    _StimulusRule(
        "comfort",
        _rx(
            r"\bit'?s\s+(ok|okay|alright|gonna be ok|going to be ok)\b"
            r"|\bdon'?t\s+(worry|be afraid|be scared)\b"
            r"|\bi'?m\s+here\s+for\s+you\b|\byou'?re\s+safe\b"
            r"|\bi'?ve\s+got\s+you\b|\beverything'?s\s+(fine|alright|ok)\b"
            r"|\bcalm\s+down\b|\btake\s+a\s+deep\s+breath\b"
        ),
        addressee_stimulus="embrace",  # reassurance soothes like an embrace
        speaker_stimulus="deep_conversation",
    ),
    # ── Kiss ──
    _StimulusRule(
        "kiss",
        _rx(
            r"\b(kiss(es|ed|ing)?|smooch(es|ed)?|peck(s|ed)?\s+(your|his|her)\s+"
            r"(lips|cheek|mouth)|press(es|ed)?\s+(my|her|his)\s+lips)\b"
            r"|\blean\s+in\s+(for\s+a\s+kiss|to\s+kiss)\b"
        ),
        addressee_stimulus="kiss",
        speaker_stimulus="kiss",
    ),
    # ── Embrace / hug ──
    _StimulusRule(
        "embrace",
        _rx(
            r"\b(hug(s|ged|ging)?|embrace(s|d)?|hold(s|ing)?\s+you\s+close|"
            r"wrap(s|ped)?\s+(my|her|his)\s+arms\s+around|pull(s|ed)?\s+you\s+"
            r"(in|close)|cradle(s|d)?)\b"
        ),
        addressee_stimulus="embrace",
        speaker_stimulus="embrace",
    ),
    # ── Non-embrace physical touch ──
    _StimulusRule(
        "physical_touch",
        _rx(
            r"\b(caress(es|ed|ing)?|stroke(s|d)?\s+(your|her|his)|"
            r"touch(es|ed)?\s+(your|her|his)\s+(hand|arm|face|cheek|hair|"
            r"shoulder)|brush(es|ed)?\s+(your|a)\s+(hair|strand)|"
            r"take(s)?\s+(your|her|his)\s+hand|hold(s)?\s+(your|her|his)\s+hand)\b"
        ),
        addressee_stimulus="physical_touch",
        speaker_stimulus="physical_touch",
    ),
    # ── Rejection / dismissal ──
    _StimulusRule(
        "rejection",
        _rx(
            r"\b(leave\s+me\s+alone|go\s+away|get\s+out|i\s+don'?t\s+want\s+"
            r"(you|to see you)|i\s+don'?t\s+love\s+you|stay\s+away\s+from\s+me|"
            r"we'?re\s+(done|over|through)|i\s+never\s+want\s+to\s+see\s+you|"
            r"i\s+hate\s+you|not\s+interested|stop\s+(bothering|talking\s+to)\s+me)\b"
        ),
        addressee_stimulus="rejection",
        speaker_stimulus=None,
    ),
    # ── Insult / contempt (lands like a rejection on the target) ──
    _StimulusRule(
        "insult",
        _rx(
            r"\byou'?re\s+(so\s+|such\s+(a|an)\s+)?(stupid|idiot|ugly|pathetic|"
            r"worthless|disgusting|useless|a\s+loser|a\s+fool|trash|garbage|"
            r"a\s+coward|weak|a\s+liar)\b"
            r"|\bshut\s+up\b|\byou\s+disgust\s+me\b|\byou\s+make\s+me\s+sick\b"
        ),
        addressee_stimulus="rejection",
        speaker_stimulus=None,
    ),
    # ── Threat ──
    _StimulusRule(
        "threat",
        _rx(
            r"\bi'?ll\s+(kill|hurt|destroy|end|ruin|break)\s+you\b"
            r"|\byou'?re\s+(dead|finished|going\s+to\s+regret)\b"
            r"|\b(watch\s+your\s+back|i'?m\s+warning\s+you|or\s+else|"
            r"don'?t\s+make\s+me|you'?ll\s+pay\s+for\s+(this|that))\b"
            r"|\bi\s+swear\s+i'?ll\b"
        ),
        addressee_stimulus="threatened",
        speaker_stimulus=None,
    ),
    # ── Betrayal admission ──
    _StimulusRule(
        "betrayal",
        _rx(
            r"\b(you\s+betrayed\s+me|you\s+lied\s+to\s+me|you\s+sold\s+me\s+out|"
            r"i\s+trusted\s+you|how\s+could\s+you\s+do\s+this|you\s+backstabbed)\b"
        ),
        addressee_stimulus="betrayed",
        speaker_stimulus=None,
    ),
]


# ──── Interceptor ─────────────────────────────────────────────────────────


class StimulusDetectInterceptor(InterceptorBase):
    """Detects emotional stimuli in dialogue text and drives neurochemistry.

    Post-call only. For the current turn it analyses:

    * ``ctx["user_message"]`` — the line addressed *to* this agent. The agent is
      the addressee, so addressee-stimuli land on the agent and (if a human
      speaker had neuro state, which they normally don't) speaker-stimuli would
      land on them. Player has no neuro state, so only the agent is touched.
    * ``ctx["reply"]`` — the line the agent just *spoke*. Reflexive
      speaker-stimuli land on the agent; addressee-stimuli land on
      ``ctx["target_id"]`` when that resolves to another neuro-tracked character.

    Detection is keyword/regex only (no LLM). Every applied stimulus reuses an
    existing catalog name from ``STIMULUS_CATALOG``.

    CONNECTS: NeurochemistryManager (apply_stimulus), MoodSyncInterceptor (92)
    CALLED BY: InterceptorPipeline.run_post (registered at priority 88)
    EMITS: neurochemistry_changed (indirectly, via manager.apply_stimulus)
    """

    name: str = "stimulus_detect"
    priority: int = 88

    # v1.60.0 [2026-06-13] — Config defaults (overridable via get_config()).
    _DEFAULT_ENABLED: bool = True
    _DEFAULT_INCOMING_INTENSITY: float = 0.6   # effect of the player's line on agent
    _DEFAULT_REPLY_INTENSITY: float = 0.5      # reflexive effect of the agent's own line
    _DEFAULT_MAX_RULES_PER_TEXT: int = 4       # cap stimuli per text to avoid overload
    _DEFAULT_MIN_TEXT_LEN: int = 2             # ignore empty/trivial fragments

    def __init__(self) -> None:
        """Initialise with the singleton neurochemistry manager + config."""
        self._manager = get_neurochemistry_manager()
        (
            self._enabled,
            self._incoming_intensity,
            self._reply_intensity,
            self._max_rules,
            self._min_len,
        ) = self._load_config()

        # Validate the rule catalog against the live stimulus catalog so a
        # typo here fails loudly at import rather than silently swallowing.
        self._validate_rules()

    # ──── Config ──────────────────────────────────────────────────────────

    def _load_config(self) -> Tuple[bool, float, float, int, int]:
        """Read tunables from config with safe defaults.

        Returns:
            (enabled, incoming_intensity, reply_intensity, max_rules, min_len)
        """
        try:
            from engine.config import get_config

            cfg = get_config()
            base = "neurochemistry.stimulus_detect"
            return (
                bool(cfg.get(f"{base}.enabled", self._DEFAULT_ENABLED)),
                float(cfg.get(f"{base}.incoming_intensity", self._DEFAULT_INCOMING_INTENSITY)),
                float(cfg.get(f"{base}.reply_intensity", self._DEFAULT_REPLY_INTENSITY)),
                int(cfg.get(f"{base}.max_rules_per_text", self._DEFAULT_MAX_RULES_PER_TEXT)),
                int(cfg.get(f"{base}.min_text_len", self._DEFAULT_MIN_TEXT_LEN)),
            )
        except Exception as exc:  # pragma: no cover - config optional in tests
            logger.debug(
                "[stimulus_detect] Config load failed, using defaults "
                "(operation=load_config): %s",
                exc,
            )
            return (
                self._DEFAULT_ENABLED,
                self._DEFAULT_INCOMING_INTENSITY,
                self._DEFAULT_REPLY_INTENSITY,
                self._DEFAULT_MAX_RULES_PER_TEXT,
                self._DEFAULT_MIN_TEXT_LEN,
            )

    def _validate_rules(self) -> None:
        """Ensure every rule references a real catalog stimulus."""
        for rule in _RULES:
            for stim in (rule.addressee_stimulus, rule.speaker_stimulus):
                if stim is not None and stim not in STIMULUS_CATALOG:
                    raise ValueError(
                        f"[stimulus_detect] Rule '{rule.name}' references unknown "
                        f"stimulus '{stim}' not in STIMULUS_CATALOG"
                    )

    # ──── Detection ───────────────────────────────────────────────────────

    def detect(self, text: str) -> List[_StimulusRule]:
        """Return all rules whose pattern matches ``text`` (capped).

        Args:
            text: Dialogue text to scan.

        Returns:
            Ordered list of matching rules, truncated to ``max_rules``.
        """
        if not text or len(text.strip()) < self._min_len:
            return []
        matches: List[_StimulusRule] = [
            rule for rule in _RULES if rule.pattern.search(text)
        ]
        if len(matches) > self._max_rules:
            matches = matches[: self._max_rules]
        return matches

    # ──── Application helpers ─────────────────────────────────────────────

    def _apply(self, character_id: str, stimulus: str, intensity: float) -> bool:
        """Apply one catalog stimulus to a character, swallowing lookup errors.

        Args:
            character_id: Target neuro-tracked character id.
            stimulus: Catalog stimulus name.
            intensity: Scaling multiplier.

        Returns:
            True if the stimulus was applied, False otherwise.
        """
        if not character_id or not stimulus:
            return False
        try:
            self._manager.apply_stimulus(character_id, stimulus, intensity=intensity)
            logger.debug(
                "[stimulus_detect] Applied '%s' x%.2f to %s "
                "(operation=apply_stimulus)",
                stimulus,
                intensity,
                character_id,
            )
            return True
        except KeyError:
            # Should not happen (rules are validated), but never crash the turn.
            logger.warning(
                "[stimulus_detect] Unknown stimulus '%s' skipped "
                "(operation=apply_stimulus, character=%s)",
                stimulus,
                character_id,
            )
            return False
        except Exception as exc:  # pragma: no cover - defensive
            logger.warning(
                "[stimulus_detect] apply_stimulus failed "
                "(operation=apply_stimulus, character=%s, stimulus=%s): %s",
                character_id,
                stimulus,
                exc,
            )
            return False

    @staticmethod
    def _resolve_target_id(ctx: ResponseContext) -> Optional[str]:
        """Resolve the reply addressee's character id, if neuro-trackable.

        The reply is spoken by ``agent_id`` *to* a target. Only another tracked
        character (not the human player) should receive addressee-stimuli from
        the reply. We look for an explicit ``target_id`` / ``target_agent_id``
        in the context; absent that, there is no AI addressee to affect.

        Args:
            ctx: The response context.

        Returns:
            A target character id distinct from the speaker, or None.
        """
        speaker = ctx.get("agent_id", "")
        for key in ("target_id", "target_agent_id", "addressee_id"):
            tid = ctx.get(key)
            if tid and tid != speaker:
                return str(tid)
        return None

    # ──── Pipeline hook ───────────────────────────────────────────────────

    def post_call(self, ctx: ResponseContext) -> int:
        """Detect stimuli in this turn's text and drive neurochemistry.

        Args:
            ctx: The mutable response context for this interaction.

        Returns:
            The number of stimuli actually applied (useful for tests/metrics).
        """
        if not self._enabled:
            return 0

        agent_id = ctx.get("agent_id") or ctx.get("character_id") or ""
        if not agent_id:
            return 0

        applied = 0

        # 1) Incoming line (player/user → THIS agent is the addressee).
        #    The agent FEELS what was said to it.
        user_message = ctx.get("user_message") or ctx.get("message") or ""
        for rule in self.detect(str(user_message)):
            if rule.addressee_stimulus:
                if self._apply(
                    agent_id, rule.addressee_stimulus, self._incoming_intensity
                ):
                    applied += 1

        # 2) Reply line (THIS agent is the speaker).
        #    Reflexive effect on the speaker + addressee effect on a known
        #    AI target character (not the human player).
        reply = ctx.get("reply") or ""
        target_id = self._resolve_target_id(ctx)
        for rule in self.detect(str(reply)):
            if rule.speaker_stimulus:
                if self._apply(
                    agent_id, rule.speaker_stimulus, self._reply_intensity
                ):
                    applied += 1
            if target_id and rule.addressee_stimulus:
                if self._apply(
                    target_id, rule.addressee_stimulus, self._incoming_intensity
                ):
                    applied += 1

        if applied:
            logger.info(
                "[stimulus_detect] Closed neuro loop: %d stimuli applied this "
                "turn (operation=post_call, agent=%s)",
                applied,
                agent_id,
            )
        return applied
