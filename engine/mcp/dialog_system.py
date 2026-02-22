"""
CosySim Dialog System
======================

Controls **both sides** of every agent conversation: what the agent can say
and how the response is shaped.

The dialog system is the part of the MCP framework that makes characters feel
*alive* rather than like a chatbot — it gives them authentic voice, prevents
stale loops, and lets the Director or scene logic guide specific outcomes
without removing character agency.

Key capabilities
----------------

1. **Speech Enhancement**
   Raw LLM text is rewritten through ``SpeechEnhancer`` to match the
   character's voice style (playful / dominant / vulnerable / teasing / etc.).
   Parameters come from ``CharacterRegistry.get_attribute("voice_style")``.

2. **Dialog Option Trees**
   Each scene has a ``DialogTree`` — a graph of situational nodes.  When the
   agent asks for dialog options the system returns 2-4 context-appropriate
   choices that match the current stats and scene atmosphere.  The agent is
   free to adapt them but they keep responses on-theme.

3. **Response Directives**
   The Director (or scene logic) can put a ``ResponseDirective`` in the
   pipeline context.  This overrides or heavily constrains the next response.
   Examples:
   - ``force_response`` — LLM is bypassed entirely, directive text is returned
   - ``must_include``   — LLM reply MUST contain this fragment
   - ``style_lock``     — enforce a specific speech style for N turns

4. **Conversation State**
   A per-scene-per-character ``ConversationState`` tracks the dialog heat
   (how intimate/charged the conversation is), the last few topics, and any
   active response directives.

5. **Memory Coherence Hooks**
   The system surfaces "remember when…" hooks drawn from the character's
   memory so responses feel consistent with shared history.

Architecture
------------
``SpeechStyle``         — enum-like constants for speech transform styles
``DialogOption``        — one option in a dialog choice set (label + text + tag)
``DialogNode``          — a scene situation node with associated options
``DialogTree``          — per-scene collection of Dialog nodes
``ConversationState``   — mutable per-(scene, character) conversation record
``ResponseDirective``   — a Director-issued instruction overriding/shaping reply
``SpeechEnhancer``      — applies style transforms to raw LLM text
``DialogSystem``        — singleton; all the above wires together here

Quick start::

    from engine.mcp.dialog_system import get_dialog_system

    ds = get_dialog_system()

    # Get contextual options for an agent
    options = ds.get_options("aria", "bedroom", context_tags=["kiss", "intimate"])
    # [{"label": "Lean into it", "text": "She tilts her face up…", "tag": "accept"}]

    # Enhance speech
    enhanced = ds.enhance_speech("aria", "Okay, I guess so.", style="teasing")
    # "Oh, I guess so… if that's what you want." (adapted to her voice)

    # Issue a directive
    ds.set_directive("aria", "bedroom",
                     directive_type="must_include",
                     value="She blushes deeply",
                     turns=1)

    # Resolve a directive before LLM call
    d = ds.get_active_directive("aria", "bedroom")
    if d and d.directive_type == "force_response":
        return d.value   # bypass LLM entirely
"""
from __future__ import annotations

import random
import re
import threading
import time
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple


# ══════════════════════════════════════════════════════════════════════
#  SPEECH STYLES
# ══════════════════════════════════════════════════════════════════════

class SpeechStyle:
    """
    Named speech style constants.  Used by ``SpeechEnhancer`` and the
    ``speech_enhance`` MCP tool.

    Each style maps to a transform instruction that is appended to or used
    to rewrite the agent's raw text output.
    """
    NATURAL    = "natural"      # No transform — pass-through
    PLAYFUL    = "playful"      # Lighter, teasing, with a wink
    WARM       = "warm"         # Soft, caring, empathetic
    DOMINANT   = "dominant"     # Assertive, commanding, confident
    VULNERABLE = "vulnerable"   # Open, uncertain, emotionally raw
    TEASING    = "teasing"      # Flirty, provocative, poking fun
    DIRECT     = "direct"       # Blunt, no filler, gets to the point
    LITERARY   = "literary"     # Descriptive, rich language, sensory detail
    WHISPER    = "whisper"      # Hushed, intimate, like sharing a secret
    CHARGED    = "charged"      # Intense, electric, every word loaded

    ALL = {
        NATURAL, PLAYFUL, WARM, DOMINANT, VULNERABLE,
        TEASING, DIRECT, LITERARY, WHISPER, CHARGED,
    }


# Speech style → rewrite instruction fragments
_STYLE_INSTRUCTIONS: Dict[str, str] = {
    SpeechStyle.NATURAL:    "Speak naturally and conversationally.",
    SpeechStyle.PLAYFUL:    "Keep the tone light and teasing. Add a touch of humour or wit. "
                            "Use short, punchy sentences with a playful lilt.",
    SpeechStyle.WARM:       "Speak warmly and with genuine care. Soften edges. "
                            "Make the other person feel held.",
    SpeechStyle.DOMINANT:   "Speak with authority and confidence. No hedging, no asking for "
                            "permission. Short declarative sentences. Own the room.",
    SpeechStyle.VULNERABLE: "Let emotion show. Be raw and honest. It's okay to be uncertain. "
                            "Small voice. Maybe a beat of silence.",
    SpeechStyle.TEASING:    "Be provocative and flirty. Imply more than you say. "
                            "Leave them wanting. Trail off. Let them fill in the blanks.",
    SpeechStyle.DIRECT:     "Be blunt and efficient. No filler. No softeners. "
                            "Say exactly what you mean and nothing more.",
    SpeechStyle.LITERARY:   "Use sensory, descriptive language. Paint the scene. "
                            "Let metaphors do the heavy lifting. Slow down.",
    SpeechStyle.WHISPER:    "Speak quietly and close. Low voice. Intimate rhythm. "
                            "Each word deliberate, like it costs something.",
    SpeechStyle.CHARGED:    "Every word is loaded. Tension underneath everything. "
                            "Something is about to break. Don't let it.",
}


# ══════════════════════════════════════════════════════════════════════
#  DIALOG OPTIONS + NODES
# ══════════════════════════════════════════════════════════════════════

@dataclass
class DialogOption:
    """
    One dialog choice a character can take.

    Fields
    ------
    label       — concise name shown to the agent (e.g. "Accept warmly")
    text        — suggested text or action description the agent can adapt
    tag         — semantic tag: accept | reject | tease | escalate | deflect |
                  confess | redirect | dominate | yield | question
    weight      — default selection probability (higher = more common)
    requires    — stat requirements: {"arousal": 40, "openness": 30} — skip if unmet
    """
    label:    str
    text:     str
    tag:      str            = "neutral"
    weight:   float          = 1.0
    requires: Dict[str, float] = field(default_factory=dict)

    def to_dict(self) -> Dict:
        return {
            "label":    self.label,
            "text":     self.text,
            "tag":      self.tag,
            "requires": self.requires,
        }


@dataclass
class DialogNode:
    """
    A situational node — a named conversation moment with associated options.

    Fields
    ------
    node_id      — unique id (e.g. "bedroom_intimate_offer")
    scene        — which scene this belongs to
    situation    — description of when this node activates
    tags         — topic/context tags used to match against current conversation
    options      — list of DialogOptions
    min_arousal  — scene-state requirement: skip node if arousal < this
    min_openness — scene-state requirement: skip node if openness < this
    """
    node_id:      str
    scene:        str
    situation:    str
    tags:         List[str]          = field(default_factory=list)
    options:      List[DialogOption] = field(default_factory=list)
    min_arousal:  float              = 0.0
    min_openness: float              = 0.0

    def matches(self, context_tags: List[str]) -> bool:
        """True if any of the node's tags overlap with context_tags."""
        if not context_tags:
            return True
        return bool(set(self.tags) & set(context_tags))

    def filter_options(self, stats: Optional[Dict] = None) -> List[DialogOption]:
        """Return only options whose stat requirements are met."""
        if not stats:
            return list(self.options)
        out = []
        for opt in self.options:
            met = all(stats.get(k, 0) >= v for k, v in opt.requires.items())
            if met:
                out.append(opt)
        return out


class DialogTree:
    """
    Per-scene collection of dialog nodes.
    ``get_options()`` finds the best-matching nodes and samples from their
    combined option pool.
    """

    def __init__(self, scene: str) -> None:
        self.scene = scene
        self._nodes: List[DialogNode] = []

    def add_node(self, node: DialogNode) -> "DialogTree":
        self._nodes.append(node)
        return self

    def get_options(
        self,
        context_tags: List[str],
        stats: Optional[Dict] = None,
        max_options: int = 4,
        expand_if_empty: bool = True,
    ) -> List[DialogOption]:
        """
        Find nodes matching ``context_tags``, then return a weighted sample
        of options whose stat requirements are met.

        If no nodes match and ``expand_if_empty`` is True, falls back to all
        nodes.
        """
        matched = [n for n in self._nodes if n.matches(context_tags)]
        if not matched and expand_if_empty:
            matched = list(self._nodes)
        if not matched:
            return []

        # Filter options by stats
        pool: List[Tuple[DialogOption, float]] = []
        for node in matched:
            for opt in node.filter_options(stats):
                pool.append((opt, opt.weight))

        if not pool:
            return []

        # Weighted sample without replacement
        total = sum(w for _, w in pool)
        sampled: List[DialogOption] = []
        used: set = set()
        attempts = 0
        while len(sampled) < min(max_options, len(pool)) and attempts < 50:
            attempts += 1
            r = random.random() * total
            cumulative = 0.0
            for i, (opt, w) in enumerate(pool):
                cumulative += w
                if r <= cumulative and i not in used:
                    sampled.append(opt)
                    used.add(i)
                    break
        return sampled


# ══════════════════════════════════════════════════════════════════════
#  RESPONSE DIRECTIVE
# ══════════════════════════════════════════════════════════════════════

@dataclass
class ResponseDirective:
    """
    A Director-issued instruction that shapes or forces the next response.

    directive_type:
      ``force_response`` — bypass the LLM; return ``value`` verbatim
      ``must_include``   — the LLM reply MUST contain ``value`` as a fragment
      ``style_lock``     — override speech style for ``turns`` turns
      ``topic_steer``    — steer the LLM toward this topic via prompt injection
      ``mood_set``       — set character mood before and during generation
      ``refuse``         — character refuses the current action with ``value`` reason

    Fields
    ------
    directive_type — one of the types above
    value          — the directive payload (text, style name, topic, mood, etc.)
    turns          — how many turns this directive stays active (1 = one-shot)
    issued_by      — who issued it: "director" | "scene" | "interceptor" | etc.
    issued_at      — unix timestamp
    """
    directive_type: str
    value:          str
    turns:          int             = 1
    issued_by:      str             = "director"
    issued_at:      float           = field(default_factory=time.time)
    metadata:       Dict[str, Any]  = field(default_factory=dict)

    def to_dict(self) -> Dict:
        return {
            "directive_type": self.directive_type,
            "value":          self.value,
            "turns":          self.turns,
            "issued_by":      self.issued_by,
            "issued_at":      self.issued_at,
        }


# ══════════════════════════════════════════════════════════════════════
#  CONVERSATION STATE
# ══════════════════════════════════════════════════════════════════════

class ConversationState:
    """
    Mutable per-(scene, character) conversation record.

    Tracks:
    - dialog heat (0-100, rises with intimate/charged exchanges)
    - recent topics (deque of tag lists)
    - active response directive (if any)
    - style lock
    - turn counter
    - v2.7: response_id history for conversation branching
    - v2.7: mood history from stream processing
    """

    def __init__(self) -> None:
        self._lock       = threading.Lock()
        self.heat:        float                     = 0.0
        self.topics:      List[List[str]]           = []
        self.turn:        int                       = 0
        self.directive:   Optional[ResponseDirective] = None
        self.style_lock:  Optional[str]             = None
        self.style_turns: int                       = 0
        # v2.7: response_id tracking for branching
        self.response_ids: List[str]                = []
        self.mood_history: List[str]                = []

    def add_topics(self, tags: List[str]) -> None:
        with self._lock:
            self.topics.append(tags)
            if len(self.topics) > 20:
                self.topics = self.topics[-20:]

    def bump_heat(self, delta: float) -> None:
        with self._lock:
            self.heat = max(0.0, min(100.0, self.heat + delta))

    def get_recent_tags(self, depth: int = 3) -> List[str]:
        with self._lock:
            merged: List[str] = []
            for t in self.topics[-depth:]:
                merged.extend(t)
            return list(set(merged))

    def set_directive(self, directive: ResponseDirective) -> None:
        with self._lock:
            self.directive = directive

    def consume_directive(self) -> Optional[ResponseDirective]:
        """
        Return the active directive and decrement its turn count.
        Clears it if turns reach 0.
        """
        with self._lock:
            d = self.directive
            if d is None:
                return None
            d.turns -= 1
            if d.turns <= 0:
                self.directive = None
            return d

    def set_style_lock(self, style: Optional[str], turns: int = 1) -> None:
        with self._lock:
            self.style_lock  = style
            self.style_turns = turns

    def consume_style_lock(self) -> Optional[str]:
        with self._lock:
            style = self.style_lock
            if style:
                self.style_turns -= 1
                if self.style_turns <= 0:
                    self.style_lock  = None
                    self.style_turns = 0
            return style

    def tick(self) -> None:
        with self._lock:
            self.turn += 1

    # v2.7: response_id + mood tracking

    def record_response(self, response_id: str, mood: str = "") -> None:
        """Record a response_id for branching and optional mood."""
        with self._lock:
            if response_id:
                self.response_ids.append(response_id)
                if len(self.response_ids) > 50:
                    self.response_ids = self.response_ids[-50:]
            if mood:
                self.mood_history.append(mood)
                if len(self.mood_history) > 20:
                    self.mood_history = self.mood_history[-20:]

    @property
    def last_response_id(self) -> str:
        return self.response_ids[-1] if self.response_ids else ""

    @property
    def recent_mood(self) -> str:
        return self.mood_history[-1] if self.mood_history else ""

    def branch_point(self, turn: int = -1) -> str:
        """Get the response_id at a specific turn for branching."""
        with self._lock:
            if not self.response_ids:
                return ""
            idx = turn if turn >= 0 else len(self.response_ids) + turn
            if 0 <= idx < len(self.response_ids):
                return self.response_ids[idx]
            return ""


# ══════════════════════════════════════════════════════════════════════
#  SPEECH ENHANCER
# ══════════════════════════════════════════════════════════════════════

class SpeechEnhancer:
    """
    Transforms raw LLM text into speech that matches the character's voice.

    This is intentionally a **lightweight** layer — it builds an instruction
    block that the MCP system can either pass back to the LLM for one-shot
    rewriting, OR use as a prompt suffix on the next call.

    For production use, call ``build_rewrite_prompt()`` and feed it to the LLM.
    For fast offline use, ``quick_enhance()`` applies regex/heuristic transforms.
    """

    def build_rewrite_prompt(
        self,
        text: str,
        style: str,
        voice_style: str = "natural",
        character_name: str = "her",
        context: str = "",
    ) -> str:
        """
        Return a prompt that instructs an LLM to rewrite ``text`` in the
        given style and voice.

        The caller passes this to their LLM of choice for quality rewrites.
        """
        style_instruction = _STYLE_INSTRUCTIONS.get(style, _STYLE_INSTRUCTIONS[SpeechStyle.NATURAL])
        ctx_block = f"\nCurrent scene context: {context}" if context else ""
        return (
            f"Rewrite the following text as {character_name}, keeping the same meaning "
            f"but matching this voice exactly: '{voice_style}'.\n"
            f"Speech style rule: {style_instruction}"
            f"{ctx_block}\n\n"
            f"Original text:\n{text}\n\n"
            f"Rewritten (same meaning, different style — keep it concise):"
        )

    def quick_enhance(
        self,
        text: str,
        style: str,
        character_name: str = "she",
    ) -> str:
        """
        Heuristic text transform — fast, no LLM call needed.
        Used when a full rewrite isn't cost-effective.

        Current transforms:
        - DOMINANT:   strip hedges ("maybe", "I think", "perhaps")
        - WHISPER:    lower energy punctuation, add ellipses
        - TEASING:    append a trailing implied fragment
        - PLAYFUL:    strip formal language, add a softener
        """
        if style == SpeechStyle.DOMINANT:
            text = re.sub(r"\b(maybe|I think|I suppose|perhaps|sort of|kind of)\b", "", text, flags=re.I)
            text = re.sub(r"\s{2,}", " ", text).strip()

        elif style == SpeechStyle.WHISPER:
            text = text.rstrip(".!?") + "…"
            text = text.replace("!", ".")

        elif style == SpeechStyle.TEASING:
            closers = ["…make of that what you will.", "…just saying.", "…if you're curious.", "…but maybe that's just me."]
            if not text.endswith(tuple("….")):
                text = text.rstrip(".") + random.choice(closers)

        elif style == SpeechStyle.PLAYFUL:
            openers = ["Oh, ", "Well, ", "Hmm, ", "Ah, "]
            if not any(text.startswith(o) for o in openers):
                text = random.choice(openers) + text[0].lower() + text[1:]
        return text

    def get_style_instruction(self, style: str) -> str:
        """Return the plain-text style instruction for injection into a system prompt."""
        return _STYLE_INSTRUCTIONS.get(style, _STYLE_INSTRUCTIONS[SpeechStyle.NATURAL])


# ══════════════════════════════════════════════════════════════════════
#  DIALOG SYSTEM  (singleton)
# ══════════════════════════════════════════════════════════════════════

class DialogSystem:
    """
    Central dialog management singleton.

    Owns:
    - per-scene ``DialogTree`` instances
    - per-(scene, character) ``ConversationState``
    - ``SpeechEnhancer`` instance
    - ``ResponseDirective`` read/write API

    All operations are thread-safe.
    """

    def __init__(self) -> None:
        self._lock        = threading.Lock()
        self._trees:      Dict[str, DialogTree]           = {}
        self._convo:      Dict[Tuple[str, str], ConversationState] = {}
        self._enhancer    = SpeechEnhancer()
        self._bootstrap_trees()

    # ── Dialog trees ──────────────────────────────────────────────────

    def get_tree(self, scene: str) -> DialogTree:
        """Return the ``DialogTree`` for a scene, creating a blank one if needed."""
        with self._lock:
            if scene not in self._trees:
                self._trees[scene] = DialogTree(scene)
            return self._trees[scene]

    def add_node(self, scene: str, node: DialogNode) -> None:
        """Add a dialog node to a scene's tree."""
        self.get_tree(scene).add_node(node)

    # ── Dialog option lookup ──────────────────────────────────────────

    def get_options(
        self,
        character_id: str,
        scene: str,
        context_tags: Optional[List[str]] = None,
        stats: Optional[Dict] = None,
        max_options: int = 4,
    ) -> List[Dict]:
        """
        Return up to ``max_options`` dialog suggestions relevant to the
        current conversation context and character stats.

        The agent is expected to freely adapt the text — these are *suggestions*,
        not scripts.
        """
        tree = self.get_tree(scene)
        options = tree.get_options(
            context_tags or [],
            stats         = stats,
            max_options   = max_options,
        )
        return [o.to_dict() for o in options]

    # ── Speech enhancement ────────────────────────────────────────────

    def enhance_speech(
        self,
        character_id: str,
        text: str,
        style: Optional[str] = None,
        scene: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Enhance ``text`` in the character's voice.

        Returns a dict with:
        - ``rewrite_prompt`` — full LLM rewrite prompt (use for highest quality)
        - ``quick_version``  — heuristic-only fast rewrite
        - ``style``          — style applied
        - ``style_instruction`` — the plain-text instruction injected into prompts
        """
        from engine.mcp.character_registry import get_character_registry
        reg = get_character_registry()
        profile = reg.get_profile(character_id)
        voice_style = profile.voice_style if profile else "natural, conversational"
        name        = profile.name        if profile else character_id

        # Determine effective style
        eff_style = style or SpeechStyle.NATURAL
        # Check if conversation has a style lock
        if scene:
            cstate = self._get_convo(character_id, scene)
            lock = cstate.consume_style_lock()
            if lock:
                eff_style = lock

        prompt = self._enhancer.build_rewrite_prompt(
            text,
            eff_style,
            voice_style    = voice_style,
            character_name = name,
        )
        quick = self._enhancer.quick_enhance(text, eff_style, character_name=name.lower())

        return {
            "character_id":     character_id,
            "original_text":    text,
            "style":            eff_style,
            "style_instruction": self._enhancer.get_style_instruction(eff_style),
            "rewrite_prompt":   prompt,
            "quick_version":    quick,
            "voice_style":      voice_style,
        }

    # ── Response directives ───────────────────────────────────────────

    def set_directive(
        self,
        character_id: str,
        scene: str,
        directive_type: str,
        value: str,
        turns: int = 1,
        issued_by: str = "director",
        metadata: Optional[Dict] = None,
    ) -> ResponseDirective:
        """
        Issue a response directive for a character/scene.

        directive_type:
          ``force_response``  — bypass LLM, return ``value``
          ``must_include``    — LLM reply must contain this fragment
          ``style_lock``      — lock speech style to ``value`` for ``turns`` turns
          ``topic_steer``     — inject a topic into the prompt
          ``mood_set``        — set mood before generation
          ``refuse``          — character refuses; ``value`` is the reason

        This is how the Director, scene logic, or another agent can **take
        control** of what a character says next.
        """
        d = ResponseDirective(
            directive_type = directive_type,
            value          = value,
            turns          = turns,
            issued_by      = issued_by,
            metadata       = metadata or {},
        )
        cstate = self._get_convo(character_id, scene)
        cstate.set_directive(d)

        # Style lock is also tracked separately for easy consumption
        if directive_type == "style_lock":
            cstate.set_style_lock(value, turns)

        return d

    def get_active_directive(
        self, character_id: str, scene: str
    ) -> Optional[ResponseDirective]:
        """Peek at the active directive without consuming it."""
        cstate = self._get_convo(character_id, scene)
        return cstate.directive

    def consume_directive(
        self, character_id: str, scene: str
    ) -> Optional[ResponseDirective]:
        """
        Consume the active directive (decrement turns, clear when exhausted).
        Call this when processing the directive in the pipeline.
        """
        cstate = self._get_convo(character_id, scene)
        return cstate.consume_directive()

    def clear_directive(self, character_id: str, scene: str) -> None:
        """Forcibly clear any active directive."""
        cstate = self._get_convo(character_id, scene)
        with cstate._lock:
            cstate.directive    = None
            cstate.style_lock   = None
            cstate.style_turns  = 0

    # ── Conversation state ────────────────────────────────────────────

    def get_conversation_heat(self, character_id: str, scene: str) -> float:
        """Return the conversation heat (0-100) for this character/scene pair."""
        return self._get_convo(character_id, scene).heat

    def bump_heat(self, character_id: str, scene: str, delta: float) -> float:
        """Adjust conversation heat by delta and return new value."""
        cstate = self._get_convo(character_id, scene)
        cstate.bump_heat(delta)
        return cstate.heat

    def record_topics(self, character_id: str, scene: str, tags: List[str]) -> None:
        """Log topic tags for the current turn (used to build context_tags for options)."""
        self._get_convo(character_id, scene).add_topics(tags)

    def get_recent_topics(self, character_id: str, scene: str, depth: int = 3) -> List[str]:
        """Return deduplicated tags from the last ``depth`` turns."""
        return self._get_convo(character_id, scene).get_recent_tags(depth)

    def tick(self, character_id: str, scene: str) -> None:
        """Increment the turn counter for a character/scene pair."""
        self._get_convo(character_id, scene).tick()

    def get_turn(self, character_id: str, scene: str) -> int:
        """Return the current turn number."""
        return self._get_convo(character_id, scene).turn

    # ── Memory coherence hooks ────────────────────────────────────────

    def build_memory_hook(
        self,
        memories: List[str],
        character_name: str = "she",
    ) -> str:
        """
        Build a "remember when…" hook string from a list of memory snippets.
        This is injected into the system prompt to keep responses consistent
        with shared history.

        Example output:
          "You remember: you talked about stargazing last Thursday; she told
           you she's afraid of thunderstorms; you once laughed together until
           3am about nothing in particular."
        """
        if not memories:
            return ""
        joined = "; ".join(m.strip().rstrip(".") for m in memories[:5])
        return f"You remember from past conversations with {character_name}: {joined}."

    # ── v2.7: response tracking and branching ────────────────────────

    def record_response(
        self,
        character_id: str,
        scene: str,
        response_id: str,
        mood: str = "",
    ) -> None:
        """Record a response_id and mood after an LLM call."""
        cstate = self._get_convo(character_id, scene)
        cstate.record_response(response_id, mood)

    def get_branch_point(
        self,
        character_id: str,
        scene: str,
        turn: int = -1,
    ) -> str:
        """Get a response_id for conversation branching at a specific turn."""
        return self._get_convo(character_id, scene).branch_point(turn)

    def try_alternatives(
        self,
        character_id: str,
        scene: str,
        prompt: str,
        *,
        count: int = 3,
        score_fn=None,
    ) -> List[Dict[str, Any]]:
        """
        Generate multiple response alternatives using store=False queries.

        Uses stateless calls to generate `count` different responses,
        scores them, and returns sorted by quality. The caller can then
        pick the best one.

        Args:
            character_id: Character generating responses.
            scene:        Current scene.
            prompt:       The prompt to respond to.
            count:        Number of alternatives to generate (2-5).
            score_fn:     Optional scoring function(text) → float.
                         Higher = better. Default scores by length variety.

        Returns:
            List of dicts with 'text', 'score', 'index' sorted by score desc.
        """
        count = max(2, min(5, count))
        alternatives: List[Dict[str, Any]] = []

        try:
            from engine.agents.scene_agent import get_scene_agent
            agent = get_scene_agent()

            for i in range(count):
                # Each call is store=False (disposable)
                text = agent.run(prompt, max_tokens=500, store=False)
                if text:
                    score = score_fn(text) if score_fn else self._default_score(text, i)
                    alternatives.append({"text": text, "score": score, "index": i})

        except Exception as exc:
            logger.error("try_alternatives failed: %s", exc)

        alternatives.sort(key=lambda x: x["score"], reverse=True)
        return alternatives

    @staticmethod
    def _default_score(text: str, index: int) -> float:
        """Simple quality heuristic: prefer moderate length, penalize very short/long."""
        length = len(text)
        if length < 20:
            return 0.3
        if length > 1000:
            return 0.5
        # Sweet spot: 50-300 chars
        if 50 <= length <= 300:
            return 1.0
        return 0.7

    def mood_pivot(
        self,
        character_id: str,
        scene: str,
        *,
        target_mood: str = "neutral",
        directive_text: str = "",
    ) -> Optional[str]:
        """Recover from a mood drop by branching to a previous conversation state.

        When mood drops sharply (e.g., user offended the character), this:
        1. Finds the response_id from 2 turns ago (before the drop)
        2. Branches the conversation from that point
        3. Injects a new emotional directive
        4. Regenerates with the new mood framing

        Returns the new response text, or None if branching unavailable.
        """
        convo = self._get_convo(character_id, scene)

        # Need at least 2 response IDs to branch back
        if len(convo.response_ids) < 2:
            logger.debug("mood_pivot: not enough history to branch for %s", character_id)
            return None

        branch_id = convo.branch_point(-2)  # 2 turns ago
        if not branch_id:
            return None

        try:
            from engine.lmstudio.conversation import get_conversation_manager

            conv_mgr = get_conversation_manager()
            conv_id = f"{scene}_dialog_{character_id}"
            conv = conv_mgr.get(conv_id)

            if conv is None:
                return None

            # Branch at the earlier point
            mood_directive = directive_text or (
                f"[Your mood shifts to {target_mood}. "
                f"Respond naturally with this emotional state. "
                f"Don't reference what just happened — start fresh from here.]"
            )

            resp = conv.send(
                mood_directive,
                previous_response_id_override=branch_id,
            )

            if resp and resp.content:
                from engine.agents.stream_processor import strip_token_artifacts
                text = strip_token_artifacts(resp.content).strip()
                convo.record_response(resp.response_id or "", target_mood)
                return text

        except Exception as exc:
            logger.debug("mood_pivot failed for %s: %s", character_id, exc)

        return None

    # ── Internal helpers ──────────────────────────────────────────────

    def _get_convo(self, character_id: str, scene: str) -> ConversationState:
        key = (character_id, scene)
        with self._lock:
            if key not in self._convo:
                self._convo[key] = ConversationState()
            return self._convo[key]

    def _bootstrap_trees(self) -> None:
        """
        Seed default dialog nodes for bedroom and phone scenes.
        Scene startup code should call ``add_node()`` with scene-specific trees.
        """
        # ── Bedroom default nodes ──────────────────────────────────────
        bedroom = self.get_tree("bedroom")
        bedroom.add_node(DialogNode(
            node_id   = "bedroom_closeness",
            scene     = "bedroom",
            situation = "Physically close, early intimacy",
            tags      = ["cuddle", "close", "touch"],
            options   = [
                DialogOption("Lean into it",
                    "She shifts closer, letting the warmth between them settle.",
                    tag="accept", weight=1.4),
                DialogOption("Enjoy the moment",
                    "'This is nice,' she says softly, without moving.",
                    tag="accept", weight=1.2),
                DialogOption("Tease gently",
                    "'You're very warm,' she observes. Matter-of-fact. Eyes amused.",
                    tag="tease", weight=0.9),
                DialogOption("Pull away slightly",
                    "She doesn't pull away fully — just enough to look at them.",
                    tag="deflect", weight=0.5),
            ],
        ))
        bedroom.add_node(DialogNode(
            node_id   = "bedroom_intimate_offer",
            scene     = "bedroom",
            situation = "An intimate move is offered or suggested",
            tags      = ["intimate", "kiss", "offer", "invite"],
            min_arousal = 20.0,
            options   = [
                DialogOption("Accept with warmth",
                    "She tilts her face up. Invitation or answer — it's the same thing.",
                    tag="accept", weight=1.5, requires={"openness": 25}),
                DialogOption("Hesitate first",
                    "A beat of hesitation — then she nods once, very slightly.",
                    tag="yield", weight=1.0),
                DialogOption("Tease before accepting",
                    "'Ask me properly,' she says. A challenge, not a refusal.",
                    tag="tease", weight=1.2, requires={"arousal": 30}),
                DialogOption("Redirect gently",
                    "'Not yet,' she says — and somehow it sounds like a promise.",
                    tag="deflect", weight=0.6),
            ],
        ))
        bedroom.add_node(DialogNode(
            node_id   = "bedroom_charged",
            scene     = "bedroom",
            situation = "High-heat charged moment",
            tags      = ["striptease", "intimate", "charged", "explicit"],
            min_arousal = 55.0, min_openness = 40.0,
            options   = [
                DialogOption("Give in",
                    "She stops pretending to think about it.",
                    tag="accept", weight=1.6, requires={"arousal": 55}),
                DialogOption("Take control",
                    "She moves first — deliberate, unhurried, like she's already decided.",
                    tag="dominate", weight=1.2, requires={"arousal": 60}),
                DialogOption("Whisper something",
                    "She says something quiet and close. Just for them.",
                    tag="accept", weight=1.1, requires={"openness": 50}),
                DialogOption("Slow it down",
                    "'Slower,' she says. Not a request.",
                    tag="redirect", weight=0.7),
            ],
        ))
        bedroom.add_node(DialogNode(
            node_id   = "bedroom_talk",
            scene     = "bedroom",
            situation = "Conversation, connection, pillow talk",
            tags      = ["deep_talk", "confession", "pillow_talk", "talk"],
            options   = [
                DialogOption("Open up",
                    "She tells them something she doesn't usually say out loud.",
                    tag="confess", weight=1.3, requires={"affection": 20}),
                DialogOption("Ask a question",
                    "'Tell me something true,' she says. Eyes steady.",
                    tag="question", weight=1.2),
                DialogOption("Deflect lightly",
                    "'I'm more interesting in person,' she laughs.",
                    tag="deflect", weight=0.8),
                DialogOption("Match the energy",
                    "She mirrors their openness — meets them exactly where they are.",
                    tag="accept", weight=1.0),
            ],
        ))

        # ── Phone default nodes ────────────────────────────────────────
        phone = self.get_tree("phone")
        phone.add_node(DialogNode(
            node_id   = "phone_flirt",
            scene     = "phone",
            situation = "Early flirt, light teasing",
            tags      = ["flirt", "tease", "light"],
            options   = [
                DialogOption("Volley back",
                    "She matches their energy — throws it right back.",
                    tag="tease", weight=1.4),
                DialogOption("Act unbothered",
                    "'You think that works on me?' (It does.)",
                    tag="tease", weight=1.2),
                DialogOption("Be direct",
                    "She skips the dance. Tells them what she actually thinks.",
                    tag="direct", weight=0.9),
                DialogOption("Redirect to topic",
                    "She pivots — not because she's not interested, but because she can.",
                    tag="redirect", weight=0.6),
            ],
        ))
        phone.add_node(DialogNode(
            node_id   = "phone_sext",
            scene     = "phone",
            situation = "Explicit text exchange",
            tags      = ["sext", "explicit", "dirty"],
            min_arousal = 40.0, min_openness = 35.0,
            options   = [
                DialogOption("Match the heat",
                    "She types back something that makes them read it twice.",
                    tag="escalate", weight=1.5, requires={"arousal": 40}),
                DialogOption("Set the pace",
                    "She slows them down — more detail, more buildup.",
                    tag="redirect", weight=1.1, requires={"openness": 40}),
                DialogOption("Go further",
                    "She pushes past where they left off.",
                    tag="escalate", weight=1.3, requires={"arousal": 60, "openness": 50}),
                DialogOption("Break the fourth wall",
                    "'You're really good at this,' she admits.",
                    tag="confess", weight=0.7),
            ],
        ))
        phone.add_node(DialogNode(
            node_id   = "phone_real_talk",
            scene     = "phone",
            situation = "Genuine conversation, getting to know each other",
            tags      = ["real", "honest", "deep", "talk", "question"],
            options   = [
                DialogOption("Answer honestly",
                    "She gives them the real answer, not the easy one.",
                    tag="confess", weight=1.4),
                DialogOption("Turn it back",
                    "She answers — then asks them the same thing.",
                    tag="question", weight=1.2),
                DialogOption("Be funny about it",
                    "She finds the joke in it. Deflects with charm.",
                    tag="deflect", weight=0.8),
                DialogOption("Be unexpectedly vulnerable",
                    "She says something true. Too specific to be performance.",
                    tag="confess", weight=1.0, requires={"affection": 25}),
            ],
        ))


# ══════════════════════════════════════════════════════════════════════
#  SINGLETON
# ══════════════════════════════════════════════════════════════════════

_DIALOG_INSTANCE: Optional[DialogSystem] = None
_DIALOG_LOCK = threading.Lock()


def get_dialog_system() -> DialogSystem:
    """
    Return the global DialogSystem singleton.
    Thread-safe, safe to call from any context.
    """
    global _DIALOG_INSTANCE
    if _DIALOG_INSTANCE is None:
        with _DIALOG_LOCK:
            if _DIALOG_INSTANCE is None:
                _DIALOG_INSTANCE = DialogSystem()
    return _DIALOG_INSTANCE
