"""Character neurochemistry engine for CosySim v1.0 "NeonCity 2".

Models 6 neurotransmitters per character that drive emotional state,
behaviour modifiers, and LLM prompt injection.  Each neurotransmitter
has a baseline, natural decay/recovery curve, and responds to stimuli.

Neurotransmitters
-----------------
- **Dopamine** — motivation, reward anticipation, focus
- **Serotonin** — contentment, mood stability, social confidence
- **Oxytocin** — bonding, trust, empathy, intimacy
- **Cortisol** — stress, vigilance, threat response
- **Adrenaline** — fight-or-flight, excitement, risk behaviour
- **Endorphins** — pain relief, euphoria, runner's high

Derived Emotions
~~~~~~~~~~~~~~~~
Emotions are *computed* from neurotransmitter combinations — no hardcoded
mood tags needed.  Examples:

- High dopamine + low cortisol → Confident
- High cortisol + high adrenaline → Panicked
- High oxytocin + high serotonin → Loved

Integration
~~~~~~~~~~~
- ``NeurochemistryInterceptor`` injects current state into LLM system prompt
- ``apply_stimulus()`` called by scenes, skills, and world events
- Persists per-character to JSON and optionally Nexus
- Hooks into ``EventBus`` for cross-system reactivity

Usage::

    from engine.characters.neurochemistry import get_neurochemistry_manager

    mgr = get_neurochemistry_manager()
    state = mgr.get_or_create("lola")
    mgr.apply_stimulus("lola", "received_compliment")
    prompt = mgr.get_prompt_context("lola")
"""
from __future__ import annotations

import json
import logging
import math
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Set, Tuple

from engine.mcp.comms_framework import InterceptorBase, ResponseContext

logger = logging.getLogger(__name__)

# ──── Event bus (optional) ────

try:
    from engine.events.event_bus import get_event_bus as _get_event_bus
    _HAS_EVENT_BUS: bool = True
except ImportError:  # pragma: no cover
    _get_event_bus = lambda: None  # type: ignore[assignment]
    _HAS_EVENT_BUS = False

# ──── Constants ────

NEUROTRANSMITTERS: List[str] = [
    "dopamine",
    "serotonin",
    "oxytocin",
    "cortisol",
    "adrenaline",
    "endorphins",
]

# Baseline values — characters gravitate back toward these over time
DEFAULT_BASELINES: Dict[str, float] = {
    "dopamine": 0.45,
    "serotonin": 0.50,
    "oxytocin": 0.30,
    "cortisol": 0.25,
    "adrenaline": 0.15,
    "endorphins": 0.40,
}

# Decay/recovery half-life in game ticks (1 tick ≈ 1 game hour ≈ 60s real)
# Lower = faster return to baseline
HALF_LIVES: Dict[str, float] = {
    "dopamine": 4.0,       # Quick reward cycle
    "serotonin": 12.0,     # Slow mood shift
    "oxytocin": 6.0,       # Medium bonding decay
    "cortisol": 3.0,       # Stress fades relatively fast
    "adrenaline": 2.0,     # Very fast spike/fade
    "endorphins": 5.0,     # Moderate afterglow
}

# ──── Stimulus Catalog ────
# Each stimulus maps to neurotransmitter deltas (additive, clamped 0.0–1.0)
# Positive = increase, negative = decrease

STIMULUS_CATALOG: Dict[str, Dict[str, float]] = {
    # ── Social / Positive ──
    "received_compliment":     {"dopamine": 0.12, "serotonin": 0.08, "oxytocin": 0.06},
    "gave_compliment":         {"dopamine": 0.05, "serotonin": 0.06, "oxytocin": 0.08},
    "deep_conversation":       {"serotonin": 0.10, "oxytocin": 0.12, "cortisol": -0.05},
    "made_friend":             {"dopamine": 0.15, "serotonin": 0.12, "oxytocin": 0.18},
    "joined_crew":             {"dopamine": 0.20, "oxytocin": 0.15, "serotonin": 0.10},
    "crew_victory":            {"dopamine": 0.25, "adrenaline": 0.10, "endorphins": 0.15},

    # ── Intimate / Bonding ──
    "physical_touch":          {"oxytocin": 0.15, "dopamine": 0.08, "cortisol": -0.05},
    "kiss":                    {"oxytocin": 0.20, "dopamine": 0.15, "endorphins": 0.10, "adrenaline": 0.08},
    "embrace":                 {"oxytocin": 0.25, "serotonin": 0.10, "cortisol": -0.10},
    "intimate_encounter":      {"oxytocin": 0.30, "dopamine": 0.25, "endorphins": 0.20, "adrenaline": 0.15},
    "rejection":               {"cortisol": 0.20, "dopamine": -0.15, "oxytocin": -0.10, "serotonin": -0.08},

    # ── Achievement / Reward ──
    "completed_mission":       {"dopamine": 0.20, "serotonin": 0.10, "endorphins": 0.08},
    "earned_credits":          {"dopamine": 0.12, "serotonin": 0.05},
    "level_up":                {"dopamine": 0.25, "serotonin": 0.15, "endorphins": 0.12},
    "successful_hack":         {"dopamine": 0.22, "adrenaline": 0.10, "endorphins": 0.08},
    "discovered_secret":       {"dopamine": 0.18, "adrenaline": 0.08},
    "won_fight":               {"dopamine": 0.18, "adrenaline": 0.12, "endorphins": 0.15},
    "won_gamble":              {"dopamine": 0.30, "adrenaline": 0.15, "endorphins": 0.10},

    # ── Threat / Stress ──
    "threatened":              {"cortisol": 0.25, "adrenaline": 0.30, "serotonin": -0.08},
    "attacked":                {"cortisol": 0.30, "adrenaline": 0.35, "dopamine": -0.10},
    "betrayed":                {"cortisol": 0.35, "oxytocin": -0.25, "serotonin": -0.15, "dopamine": -0.10},
    "witnessed_violence":      {"cortisol": 0.20, "adrenaline": 0.15, "serotonin": -0.05},
    "police_encounter":        {"cortisol": 0.22, "adrenaline": 0.18},
    "lost_fight":              {"cortisol": 0.25, "adrenaline": 0.10, "dopamine": -0.12, "endorphins": 0.05},
    "lost_gamble":             {"cortisol": 0.15, "dopamine": -0.20, "serotonin": -0.08},
    "lost_crew_member":        {"cortisol": 0.30, "oxytocin": -0.15, "serotonin": -0.15},

    # ── Substances / Consumables ──
    "consumed_stimulant":      {"dopamine": 0.25, "adrenaline": 0.20, "cortisol": 0.10},
    "consumed_depressant":     {"serotonin": 0.15, "cortisol": -0.20, "adrenaline": -0.15, "dopamine": -0.08},
    "consumed_euphoric":       {"endorphins": 0.30, "dopamine": 0.20, "serotonin": 0.15, "cortisol": -0.10},
    "consumed_food":           {"serotonin": 0.08, "cortisol": -0.05},
    "consumed_alcohol":        {"endorphins": 0.10, "serotonin": 0.08, "cortisol": -0.10, "adrenaline": -0.05},

    # ── Environment / World ──
    "entered_safe_zone":       {"cortisol": -0.15, "serotonin": 0.08},
    "entered_danger_zone":     {"cortisol": 0.15, "adrenaline": 0.20},
    "heard_good_news":         {"dopamine": 0.10, "serotonin": 0.08},
    "heard_bad_news":          {"cortisol": 0.12, "serotonin": -0.06},
    "rested":                  {"cortisol": -0.20, "serotonin": 0.12, "endorphins": 0.05, "adrenaline": -0.10},
    "exercised":               {"endorphins": 0.20, "adrenaline": 0.10, "cortisol": -0.08, "dopamine": 0.08},
    "listened_to_music":       {"serotonin": 0.10, "dopamine": 0.08, "cortisol": -0.05},
}

# ──── Emotion Derivation Rules ────
# Each emotion is a (condition_fn, label, intensity_fn) triple
# Condition uses neurotransmitter dict, returns bool
# Intensity returns float 0.0–1.0

EmotionRule = Tuple[Callable[[Dict[str, float]], bool],
                    str,
                    Callable[[Dict[str, float]], float]]

_EMOTION_RULES: List[EmotionRule] = [
    # Panic: high cortisol + high adrenaline
    (lambda n: n["cortisol"] > 0.65 and n["adrenaline"] > 0.60,
     "panicked",
     lambda n: min(1.0, (n["cortisol"] + n["adrenaline"]) / 2)),

    # Euphoric: high endorphins + high dopamine
    (lambda n: n["endorphins"] > 0.70 and n["dopamine"] > 0.65,
     "euphoric",
     lambda n: min(1.0, (n["endorphins"] + n["dopamine"]) / 2)),

    # In love: high oxytocin + high serotonin + low cortisol
    (lambda n: n["oxytocin"] > 0.65 and n["serotonin"] > 0.55 and n["cortisol"] < 0.30,
     "in_love",
     lambda n: min(1.0, (n["oxytocin"] + n["serotonin"]) / 2)),

    # Aroused: high dopamine + high adrenaline + moderate oxytocin
    (lambda n: n["dopamine"] > 0.55 and n["adrenaline"] > 0.40 and n["oxytocin"] > 0.35,
     "aroused",
     lambda n: min(1.0, (n["dopamine"] + n["adrenaline"] + n["oxytocin"]) / 3)),

    # Confident: high dopamine + low cortisol
    (lambda n: n["dopamine"] > 0.60 and n["cortisol"] < 0.30,
     "confident",
     lambda n: n["dopamine"]),

    # Stressed: high cortisol + low serotonin
    (lambda n: n["cortisol"] > 0.55 and n["serotonin"] < 0.35,
     "stressed",
     lambda n: n["cortisol"]),

    # Fearful: high cortisol + high adrenaline + low endorphins
    (lambda n: n["cortisol"] > 0.50 and n["adrenaline"] > 0.45 and n["endorphins"] < 0.30,
     "fearful",
     lambda n: min(1.0, (n["cortisol"] + n["adrenaline"]) / 2)),

    # Aggressive: high adrenaline + high dopamine + low serotonin
    (lambda n: n["adrenaline"] > 0.55 and n["dopamine"] > 0.45 and n["serotonin"] < 0.35,
     "aggressive",
     lambda n: n["adrenaline"]),

    # Trusting: high oxytocin + moderate serotonin
    (lambda n: n["oxytocin"] > 0.55 and n["serotonin"] > 0.45,
     "trusting",
     lambda n: n["oxytocin"]),

    # Content: high serotonin + low cortisol + moderate dopamine
    (lambda n: n["serotonin"] > 0.55 and n["cortisol"] < 0.30 and n["dopamine"] > 0.35,
     "content",
     lambda n: n["serotonin"]),

    # Happy: high serotonin + moderate dopamine
    (lambda n: n["serotonin"] > 0.50 and n["dopamine"] > 0.45,
     "happy",
     lambda n: (n["serotonin"] + n["dopamine"]) / 2),

    # Depressed: low serotonin + low dopamine + moderate cortisol
    (lambda n: n["serotonin"] < 0.25 and n["dopamine"] < 0.25,
     "depressed",
     lambda n: 1.0 - (n["serotonin"] + n["dopamine"]) / 2),

    # Anxious: moderate-high cortisol + low serotonin
    (lambda n: n["cortisol"] > 0.40 and n["serotonin"] < 0.35,
     "anxious",
     lambda n: n["cortisol"]),

    # Excited: high dopamine + moderate adrenaline
    (lambda n: n["dopamine"] > 0.55 and n["adrenaline"] > 0.30,
     "excited",
     lambda n: (n["dopamine"] + n["adrenaline"]) / 2),

    # Relaxed: low cortisol + low adrenaline + moderate serotonin
    (lambda n: n["cortisol"] < 0.25 and n["adrenaline"] < 0.20 and n["serotonin"] > 0.40,
     "relaxed",
     lambda n: n["serotonin"]),

    # Lonely: low oxytocin + moderate cortisol
    (lambda n: n["oxytocin"] < 0.20 and n["cortisol"] > 0.30,
     "lonely",
     lambda n: 1.0 - n["oxytocin"]),

    # Numb: low everything (burnout / withdrawal)
    (lambda n: all(n[k] < 0.25 for k in ("dopamine", "serotonin", "endorphins")),
     "numb",
     lambda n: 1.0 - (n["dopamine"] + n["serotonin"] + n["endorphins"]) / 3),
]


# ──── Behaviour Modifiers ────
# Maps neurotransmitter levels to gameplay multipliers

@dataclass
class BehaviourModifiers:
    """Gameplay modifiers derived from neurochemistry."""

    motivation: float = 1.0       # Affects XP gain rate, mission acceptance
    social_openness: float = 1.0  # Affects persuasion, relationship gains
    risk_tolerance: float = 1.0   # Affects gambling, combat engagement
    focus: float = 1.0            # Affects hacking, tech skill checks
    pain_tolerance: float = 1.0   # Affects combat damage thresholds
    stress_resistance: float = 1.0  # Affects cortisol gain rate
    trust_tendency: float = 1.0   # Affects crew loyalty gains
    creativity: float = 1.0      # Affects crafting, art, unconventional solutions

    def to_dict(self) -> Dict[str, float]:
        """Serialize to dict."""
        return {
            "motivation": round(self.motivation, 3),
            "social_openness": round(self.social_openness, 3),
            "risk_tolerance": round(self.risk_tolerance, 3),
            "focus": round(self.focus, 3),
            "pain_tolerance": round(self.pain_tolerance, 3),
            "stress_resistance": round(self.stress_resistance, 3),
            "trust_tendency": round(self.trust_tendency, 3),
            "creativity": round(self.creativity, 3),
        }


def compute_modifiers(levels: Dict[str, float]) -> BehaviourModifiers:
    """Derive gameplay modifiers from neurotransmitter levels.

    Args:
        levels: Dict of neurotransmitter name → 0.0–1.0 level.

    Returns:
        BehaviourModifiers with multipliers (0.3–2.0 range).
    """
    d = levels.get("dopamine", 0.5)
    s = levels.get("serotonin", 0.5)
    o = levels.get("oxytocin", 0.3)
    c = levels.get("cortisol", 0.25)
    a = levels.get("adrenaline", 0.15)
    e = levels.get("endorphins", 0.4)

    def _clamp(v: float, lo: float = 0.3, hi: float = 2.0) -> float:
        return max(lo, min(hi, v))

    return BehaviourModifiers(
        motivation=_clamp(0.5 + d * 1.2 - c * 0.4),
        social_openness=_clamp(0.4 + s * 0.8 + o * 0.6 - c * 0.3),
        risk_tolerance=_clamp(0.3 + a * 1.0 + d * 0.5 - s * 0.2),
        focus=_clamp(0.5 + d * 0.8 - c * 0.5 - a * 0.3),
        pain_tolerance=_clamp(0.4 + e * 1.0 + a * 0.3),
        stress_resistance=_clamp(0.5 + s * 0.6 + e * 0.4 - c * 0.3),
        trust_tendency=_clamp(0.3 + o * 1.2 + s * 0.3 - c * 0.2),
        creativity=_clamp(0.4 + d * 0.5 + s * 0.4 + e * 0.3 - c * 0.3),
    )


# ============================================================================
# NeurochemicalState — per-character neurotransmitter snapshot
# ============================================================================

@dataclass
class NeurochemicalState:
    """Snapshot of one character's neurotransmitter levels."""

    character_id: str
    levels: Dict[str, float] = field(default_factory=lambda: dict(DEFAULT_BASELINES))
    baselines: Dict[str, float] = field(default_factory=lambda: dict(DEFAULT_BASELINES))
    tolerance: Dict[str, float] = field(
        default_factory=lambda: {nt: 0.0 for nt in NEUROTRANSMITTERS}
    )
    last_tick: float = field(default_factory=time.time)
    stimulus_history: List[Dict[str, Any]] = field(default_factory=list)

    # ── Core operations ──

    def apply_delta(self, deltas: Dict[str, float]) -> Dict[str, float]:
        """Apply neurotransmitter deltas, respecting tolerance.

        Args:
            deltas: Dict of neurotransmitter → delta value.

        Returns:
            Dict of actual changes applied (after tolerance reduction).
        """
        actual_changes: Dict[str, float] = {}
        for nt, raw_delta in deltas.items():
            if nt not in self.levels:
                continue
            tol = self.tolerance.get(nt, 0.0)
            effective_delta = raw_delta * max(0.1, 1.0 - tol * 0.5)
            old = self.levels[nt]
            self.levels[nt] = max(0.0, min(1.0, old + effective_delta))
            actual_changes[nt] = self.levels[nt] - old

            if abs(raw_delta) > 0.05:
                self.tolerance[nt] = min(1.0, tol + abs(raw_delta) * 0.1)
        return actual_changes

    def tick(self, elapsed_ticks: float = 1.0) -> None:
        """Decay/recover neurotransmitters toward baselines.

        Uses exponential decay: level += (baseline - level) * (1 - e^(-t/half_life))

        Also decays tolerance back toward 0.

        Args:
            elapsed_ticks: Number of game ticks elapsed since last update.
        """
        for nt in NEUROTRANSMITTERS:
            half_life = HALF_LIVES.get(nt, 6.0)
            baseline = self.baselines.get(nt, DEFAULT_BASELINES.get(nt, 0.5))
            current = self.levels[nt]

            decay_factor = 1.0 - math.exp(-elapsed_ticks * 0.693 / half_life)
            self.levels[nt] = current + (baseline - current) * decay_factor
            self.levels[nt] = max(0.0, min(1.0, self.levels[nt]))

            # Tolerance decays slowly
            tol = self.tolerance.get(nt, 0.0)
            if tol > 0:
                self.tolerance[nt] = max(0.0, tol - elapsed_ticks * 0.02)

        self.last_tick = time.time()

    def get_emotions(self) -> List[Tuple[str, float]]:
        """Derive emotional states from current neurotransmitter levels.

        Returns:
            List of (emotion_name, intensity) sorted by intensity descending.
            Only includes emotions where the condition is met.
        """
        active: List[Tuple[str, float]] = []
        for condition_fn, label, intensity_fn in _EMOTION_RULES:
            try:
                if condition_fn(self.levels):
                    intensity = intensity_fn(self.levels)
                    active.append((label, round(intensity, 3)))
            except (KeyError, ZeroDivisionError):
                continue
        active.sort(key=lambda x: x[1], reverse=True)
        return active

    def get_primary_emotion(self) -> Tuple[str, float]:
        """Get the single strongest derived emotion.

        Returns:
            (emotion_name, intensity) or ("neutral", 0.5) if no conditions met.
        """
        emotions = self.get_emotions()
        return emotions[0] if emotions else ("neutral", 0.5)

    def get_modifiers(self) -> BehaviourModifiers:
        """Compute gameplay behaviour modifiers from current levels.

        Returns:
            BehaviourModifiers instance.
        """
        return compute_modifiers(self.levels)

    def get_mood_summary(self) -> str:
        """Generate a compact mood summary for LLM prompt injection.

        Returns:
            Human-readable mood string like "euphoric (0.85), trusting (0.62)".
        """
        emotions = self.get_emotions()
        if not emotions:
            return "neutral"
        parts = [f"{name} ({intensity:.0%})" for name, intensity in emotions[:3]]
        return ", ".join(parts)

    def get_detailed_summary(self) -> str:
        """Generate a detailed neurochemistry summary for LLM prompt injection.

        Returns:
            Multi-line summary including neurotransmitter levels, emotions,
            and behaviour modifiers.
        """
        lines = [f"[NEUROCHEMISTRY for {self.character_id}]"]

        level_parts = []
        for nt in NEUROTRANSMITTERS:
            val = self.levels[nt]
            bar = _level_bar(val)
            level_parts.append(f"  {nt}: {bar} {val:.0%}")
        lines.append("Neurotransmitters:")
        lines.extend(level_parts)

        emotions = self.get_emotions()
        if emotions:
            emo_str = ", ".join(f"{n} ({i:.0%})" for n, i in emotions[:4])
            lines.append(f"Emotional state: {emo_str}")

        mods = self.get_modifiers()
        notable = {k: v for k, v in mods.to_dict().items() if abs(v - 1.0) > 0.15}
        if notable:
            mod_str = ", ".join(f"{k}={v:.1f}x" for k, v in notable.items())
            lines.append(f"Behaviour modifiers: {mod_str}")

        return "\n".join(lines)

    # ── Persistence ──

    def to_dict(self) -> Dict[str, Any]:
        """Serialize to dictionary for JSON persistence."""
        return {
            "character_id": self.character_id,
            "levels": {k: round(v, 4) for k, v in self.levels.items()},
            "baselines": {k: round(v, 4) for k, v in self.baselines.items()},
            "tolerance": {k: round(v, 4) for k, v in self.tolerance.items()},
            "last_tick": self.last_tick,
            "stimulus_history": self.stimulus_history[-20:],
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> NeurochemicalState:
        """Reconstruct from dictionary.

        Args:
            data: Previously serialized state dict.

        Returns:
            New NeurochemicalState instance.
        """
        state = cls(character_id=data["character_id"])
        state.levels = {k: float(v) for k, v in data.get("levels", {}).items()}
        for nt in NEUROTRANSMITTERS:
            state.levels.setdefault(nt, DEFAULT_BASELINES.get(nt, 0.5))
        state.baselines = {k: float(v) for k, v in data.get("baselines", {}).items()}
        for nt in NEUROTRANSMITTERS:
            state.baselines.setdefault(nt, DEFAULT_BASELINES.get(nt, 0.5))
        state.tolerance = {k: float(v) for k, v in data.get("tolerance", {}).items()}
        for nt in NEUROTRANSMITTERS:
            state.tolerance.setdefault(nt, 0.0)
        state.last_tick = data.get("last_tick", time.time())
        state.stimulus_history = data.get("stimulus_history", [])
        return state


def _level_bar(val: float, width: int = 10) -> str:
    """Render a compact text bar for a 0.0–1.0 value."""
    filled = int(val * width)
    return "█" * filled + "░" * (width - filled)


# ============================================================================
# NeurochemistryManager — singleton managing all character states
# ============================================================================

_SAVE_DIR = Path("data")
_SAVE_FILE = "neurochemistry.json"
_MAX_STIMULUS_HISTORY = 20


class NeurochemistryManager:
    """Central manager for all character neurochemistry states.

    Thread-safe singleton.  Manages per-character NeurochemicalState instances,
    applies stimuli from the catalog, ticks decay, and persists to disk.
    """

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._states: Dict[str, NeurochemicalState] = {}
        self._custom_stimuli: Dict[str, Dict[str, float]] = {}
        self._listeners: List[Callable[[str, str, Dict[str, float]], None]] = []
        self._load()

    # ── Public API ──

    def get_or_create(self, character_id: str) -> NeurochemicalState:
        """Get or create neurochemical state for a character.

        Args:
            character_id: Unique character identifier.

        Returns:
            The character's NeurochemicalState.
        """
        with self._lock:
            if character_id not in self._states:
                self._states[character_id] = NeurochemicalState(
                    character_id=character_id
                )
                logger.info("Created neurochemical state for %s", character_id)
            return self._states[character_id]

    def get_state(self, character_id: str) -> Optional[NeurochemicalState]:
        """Get state if it exists, without creating.

        Args:
            character_id: Unique character identifier.

        Returns:
            NeurochemicalState or None.
        """
        with self._lock:
            return self._states.get(character_id)

    def apply_stimulus(
        self,
        character_id: str,
        stimulus_name: str,
        intensity: float = 1.0,
    ) -> Dict[str, float]:
        """Apply a named stimulus to a character's neurochemistry.

        Looks up the stimulus in the catalog (or custom stimuli), scales by
        intensity, applies via the character's state, logs to history, fires
        event bus notification, and auto-saves.

        Args:
            character_id: Target character.
            stimulus_name: Key in STIMULUS_CATALOG or custom stimuli.
            intensity: Multiplier for the deltas (default 1.0).

        Returns:
            Dict of actual neurotransmitter changes applied.

        Raises:
            KeyError: If stimulus_name is not found in any catalog.
        """
        catalog = {**STIMULUS_CATALOG, **self._custom_stimuli}
        if stimulus_name not in catalog:
            raise KeyError(
                f"Unknown stimulus '{stimulus_name}'. "
                f"Available: {sorted(catalog.keys())}"
            )

        raw_deltas = catalog[stimulus_name]
        scaled_deltas = {nt: delta * intensity for nt, delta in raw_deltas.items()}

        state = self.get_or_create(character_id)
        with self._lock:
            actual = state.apply_delta(scaled_deltas)

            state.stimulus_history.append({
                "stimulus": stimulus_name,
                "intensity": round(intensity, 3),
                "deltas": {k: round(v, 4) for k, v in actual.items()},
                "timestamp": time.time(),
            })
            if len(state.stimulus_history) > _MAX_STIMULUS_HISTORY:
                state.stimulus_history = state.stimulus_history[-_MAX_STIMULUS_HISTORY:]

        # Fire event
        if _HAS_EVENT_BUS:
            bus = _get_event_bus()
            if bus is not None:
                bus.publish("neurochemistry_changed", {
                    "character_id": character_id,
                    "stimulus": stimulus_name,
                    "intensity": intensity,
                    "changes": actual,
                    "emotions": state.get_emotions()[:3],
                    "primary_emotion": state.get_primary_emotion()[0],
                })

        # Notify listeners
        for listener in self._listeners:
            try:
                listener(character_id, stimulus_name, actual)
            except Exception:
                logger.exception("Neurochemistry listener error")

        self._save()
        logger.debug(
            "Applied '%s' (×%.1f) to %s: %s → emotion: %s",
            stimulus_name, intensity, character_id,
            {k: f"{v:+.3f}" for k, v in actual.items()},
            state.get_primary_emotion()[0],
        )
        return actual

    def apply_raw_delta(
        self,
        character_id: str,
        deltas: Dict[str, float],
        reason: str = "direct",
    ) -> Dict[str, float]:
        """Apply raw neurotransmitter deltas (no catalog lookup).

        Args:
            character_id: Target character.
            deltas: Dict of neurotransmitter → delta value.
            reason: Description of why this delta was applied.

        Returns:
            Dict of actual changes.
        """
        state = self.get_or_create(character_id)
        with self._lock:
            actual = state.apply_delta(deltas)
            state.stimulus_history.append({
                "stimulus": f"raw:{reason}",
                "intensity": 1.0,
                "deltas": {k: round(v, 4) for k, v in actual.items()},
                "timestamp": time.time(),
            })
            if len(state.stimulus_history) > _MAX_STIMULUS_HISTORY:
                state.stimulus_history = state.stimulus_history[-_MAX_STIMULUS_HISTORY:]
        self._save()
        return actual

    def tick_all(self, elapsed_ticks: float = 1.0) -> None:
        """Advance decay/recovery for all characters.

        Called by the world simulation on each game tick.

        Args:
            elapsed_ticks: Number of game ticks elapsed.
        """
        with self._lock:
            for state in self._states.values():
                state.tick(elapsed_ticks)
        self._save()

    def tick_character(self, character_id: str, elapsed_ticks: float = 1.0) -> None:
        """Advance decay/recovery for a single character.

        Args:
            character_id: Target character.
            elapsed_ticks: Number of game ticks elapsed.
        """
        state = self.get_state(character_id)
        if state:
            with self._lock:
                state.tick(elapsed_ticks)
            self._save()

    def get_prompt_context(self, character_id: str, detailed: bool = False) -> str:
        """Get LLM prompt injection string for a character.

        Args:
            character_id: Target character.
            detailed: If True, include full neurotransmitter levels.

        Returns:
            Formatted string for system prompt injection.
        """
        state = self.get_state(character_id)
        if not state:
            return ""
        if detailed:
            return state.get_detailed_summary()

        emotion, intensity = state.get_primary_emotion()
        secondary = state.get_emotions()[1:3]

        parts = [f"Current emotional state: {emotion} (intensity: {intensity:.0%})"]
        if secondary:
            sec_str = ", ".join(f"{n} ({i:.0%})" for n, i in secondary)
            parts.append(f"Secondary feelings: {sec_str}")

        mods = state.get_modifiers()
        notable = {k: v for k, v in mods.to_dict().items() if abs(v - 1.0) > 0.2}
        if notable:
            mod_parts = []
            for k, v in notable.items():
                direction = "heightened" if v > 1.0 else "reduced"
                mod_parts.append(f"{k.replace('_', ' ')} is {direction}")
            parts.append(f"Behavioural tendencies: {', '.join(mod_parts)}")

        return "\n".join(parts)

    def register_stimulus(self, name: str, deltas: Dict[str, float]) -> None:
        """Register a custom stimulus for use with apply_stimulus.

        Args:
            name: Stimulus identifier.
            deltas: Dict of neurotransmitter → delta value.
        """
        self._custom_stimuli[name] = deltas
        logger.info("Registered custom stimulus '%s': %s", name, deltas)

    def add_listener(
        self, callback: Callable[[str, str, Dict[str, float]], None]
    ) -> None:
        """Register a callback for neurochemistry changes.

        Callback receives (character_id, stimulus_name, actual_changes).

        Args:
            callback: Function to call on neurochemistry changes.
        """
        self._listeners.append(callback)

    def set_baseline(
        self, character_id: str, overrides: Dict[str, float]
    ) -> None:
        """Set custom baselines for a character (personality).

        Different characters have different natural set-points.
        E.g., an anxious character has higher cortisol baseline.

        Args:
            character_id: Target character.
            overrides: Dict of neurotransmitter → new baseline (0.0–1.0).
        """
        state = self.get_or_create(character_id)
        with self._lock:
            for nt, val in overrides.items():
                if nt in state.baselines:
                    state.baselines[nt] = max(0.0, min(1.0, val))
        self._save()
        logger.info("Set baselines for %s: %s", character_id, overrides)

    def get_all_states(self) -> Dict[str, Dict[str, Any]]:
        """Get serialized state for all characters.

        Returns:
            Dict of character_id → state dict.
        """
        with self._lock:
            return {cid: st.to_dict() for cid, st in self._states.items()}

    def list_stimuli(self) -> List[str]:
        """List all available stimulus names.

        Returns:
            Sorted list of stimulus identifiers.
        """
        return sorted({**STIMULUS_CATALOG, **self._custom_stimuli}.keys())

    def remove_character(self, character_id: str) -> bool:
        """Remove a character's neurochemical state.

        Args:
            character_id: Character to remove.

        Returns:
            True if removed, False if not found.
        """
        with self._lock:
            if character_id in self._states:
                del self._states[character_id]
                self._save()
                return True
        return False

    # ── Persistence ──

    def _save(self) -> None:
        """Persist all states to JSON file."""
        try:
            _SAVE_DIR.mkdir(parents=True, exist_ok=True)
            path = _SAVE_DIR / _SAVE_FILE
            data = {cid: st.to_dict() for cid, st in self._states.items()}
            path.write_text(json.dumps(data, indent=2), encoding="utf-8")
        except Exception:
            logger.exception("Failed to save neurochemistry state")

    def _load(self) -> None:
        """Load states from JSON file."""
        path = _SAVE_DIR / _SAVE_FILE
        if not path.exists():
            return
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
            for cid, state_data in raw.items():
                self._states[cid] = NeurochemicalState.from_dict(state_data)
            logger.info("Loaded neurochemistry for %d characters", len(self._states))
        except Exception:
            logger.exception("Failed to load neurochemistry state")


# ============================================================================
# NeurochemistryInterceptor — injects mood into LLM system prompt
# ============================================================================

class NeurochemistryInterceptor(InterceptorBase):
    """Interceptor that injects neurochemistry-derived mood into system prompts.

    Runs at priority 4 (before NaturalMoodDriftInterceptor at 5) so the LLM
    sees the character's current emotional state driven by biochemistry.

    Pre-call: Appends emotional state, behaviour tendencies to system prompt.
    Post-call: Detects mood-altering events in the LLM response and applies
    corresponding stimuli.
    """

    name: str = "neurochemistry"
    priority: int = 4

    def __init__(self) -> None:
        self._manager = get_neurochemistry_manager()

    def pre_call(self, ctx: ResponseContext) -> None:
        """Inject neurochemistry context into the system prompt."""
        character_id = ctx.get("character_id")
        if not character_id:
            return

        state = self._manager.get_state(character_id)
        if not state:
            state = self._manager.get_or_create(character_id)

        prompt_extra = self._manager.get_prompt_context(character_id, detailed=False)
        if prompt_extra:
            existing = ctx.get("system_prompt", "")
            ctx["system_prompt"] = f"{existing}\n\n{prompt_extra}"

        mods = state.get_modifiers()
        ctx.setdefault("neurochemistry", {})
        ctx["neurochemistry"]["modifiers"] = mods.to_dict()
        ctx["neurochemistry"]["primary_emotion"] = state.get_primary_emotion()
        ctx["neurochemistry"]["levels"] = dict(state.levels)

    def post_call(self, ctx: ResponseContext) -> None:
        """Detect mood events in the response and apply stimuli."""
        character_id = ctx.get("character_id")
        if not character_id:
            return

        reply = ctx.get("reply", "")
        if not reply:
            return

        reply_lower = reply.lower()
        _post_call_stimulus_map = {
            "kiss": "kiss",
            "embrace": "embrace",
            "hug": "physical_touch",
            "compliment": "received_compliment",
            "threaten": "threatened",
            "attack": "attacked",
            "betray": "betrayed",
        }
        for keyword, stimulus in _post_call_stimulus_map.items():
            if keyword in reply_lower:
                try:
                    self._manager.apply_stimulus(character_id, stimulus, intensity=0.5)
                except KeyError:
                    pass


# ============================================================================
# Module-level singleton
# ============================================================================

_manager_instance: Optional[NeurochemistryManager] = None
_manager_lock = threading.Lock()


def get_neurochemistry_manager() -> NeurochemistryManager:
    """Get the singleton NeurochemistryManager instance.

    Returns:
        The global NeurochemistryManager.
    """
    global _manager_instance
    if _manager_instance is None:
        with _manager_lock:
            if _manager_instance is None:
                _manager_instance = NeurochemistryManager()
    return _manager_instance


def get_character_modifier(character_id: str, modifier: str) -> float:
    """Get a specific behaviour modifier for a character.

    Convenience function for game systems (hack engine, market, combat)
    to apply neurochemistry-derived modifiers to gameplay outcomes.

    Args:
        character_id: Character to query.
        modifier: One of: motivation, social_openness, risk_tolerance, focus,
            pain_tolerance, stress_resistance, trust_tendency, creativity.

    Returns:
        Modifier multiplier (0.3–2.0), or 1.0 if character has no state.
    """
    try:
        mgr = get_neurochemistry_manager()
        state = mgr.get_state(character_id)
        if state is None:
            return 1.0
        mods = state.get_modifiers()
        return getattr(mods, modifier, 1.0)
    except Exception:
        return 1.0
