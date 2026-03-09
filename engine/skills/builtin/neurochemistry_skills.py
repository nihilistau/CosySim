"""Neurochemistry skills — query and modify character neurochemistry."""
from __future__ import annotations

import logging
from typing import Optional

from engine.skills.skill import skill

logger = logging.getLogger(__name__)


@skill(
    pack="neurochemistry",
    description="Check a character's current emotional state driven by neurochemistry",
    category="SOCIAL",
)
def check_mood(character_id: str) -> str:
    """Return the character's current neurochemistry-derived emotional state."""
    from engine.characters.neurochemistry import get_neurochemistry_manager

    mgr = get_neurochemistry_manager()
    state = mgr.get_or_create(character_id)
    primary_emotion, intensity = state.get_primary_emotion()
    secondary = state.get_emotions()[1:3]
    mods = state.get_modifiers()

    lines = [f"🧠 {character_id}'s neurochemistry:"]
    lines.append(f"  Primary emotion: {primary_emotion} ({intensity:.0%})")
    if secondary:
        sec_str = ", ".join(f"{n} ({i:.0%})" for n, i in secondary)
        lines.append(f"  Secondary: {sec_str}")

    notable = {k: v for k, v in mods.to_dict().items() if abs(v - 1.0) > 0.15}
    if notable:
        mod_str = ", ".join(f"{k}={v:.1f}x" for k, v in notable.items())
        lines.append(f"  Modifiers: {mod_str}")

    return "\n".join(lines)


@skill(
    pack="neurochemistry",
    description="View detailed neurotransmitter levels for a character",
    category="SOCIAL",
)
def read_neurochem(character_id: str) -> str:
    """Return full neurotransmitter breakdown with levels and bars."""
    from engine.characters.neurochemistry import get_neurochemistry_manager

    mgr = get_neurochemistry_manager()
    state = mgr.get_or_create(character_id)
    return state.get_detailed_summary()


@skill(
    pack="neurochemistry",
    description="Apply a stimulus to a character (e.g. compliment, threat, kiss)",
    category="SOCIAL",
    cost=1.0,
)
def stimulate(
    character_id: str,
    stimulus: str,
    intensity: float = 1.0,
) -> str:
    """Apply a named stimulus from the catalog to a character's neurochemistry.

    Args:
        character_id: Target character.
        stimulus: Stimulus name (e.g. 'received_compliment', 'threatened', 'kiss').
        intensity: Multiplier 0.1–2.0 (default 1.0).
    """
    from engine.characters.neurochemistry import get_neurochemistry_manager

    mgr = get_neurochemistry_manager()
    intensity = max(0.1, min(2.0, intensity))

    try:
        changes = mgr.apply_stimulus(character_id, stimulus, intensity)
    except KeyError:
        available = mgr.list_stimuli()
        return (
            f"❌ Unknown stimulus '{stimulus}'. "
            f"Available: {', '.join(available[:15])}..."
        )

    state = mgr.get_or_create(character_id)
    primary, pct = state.get_primary_emotion()

    change_str = ", ".join(
        f"{nt}: {delta:+.1%}" for nt, delta in changes.items() if abs(delta) > 0.001
    )
    return (
        f"💉 Applied '{stimulus}' (×{intensity:.1f}) to {character_id}\n"
        f"  Changes: {change_str}\n"
        f"  New mood: {primary} ({pct:.0%})"
    )


@skill(
    pack="neurochemistry",
    description="List all available neurochemistry stimuli",
    category="SOCIAL",
)
def list_stimuli() -> str:
    """Return a formatted list of all available stimuli names."""
    from engine.characters.neurochemistry import get_neurochemistry_manager

    mgr = get_neurochemistry_manager()
    stimuli = mgr.list_stimuli()

    categories = {
        "Social": [s for s in stimuli if any(k in s for k in ("compliment", "friend", "crew", "conversation"))],
        "Intimate": [s for s in stimuli if any(k in s for k in ("touch", "kiss", "embrace", "intimate", "rejection"))],
        "Achievement": [s for s in stimuli if any(k in s for k in ("completed", "earned", "level", "hack", "won", "discovered"))],
        "Threat": [s for s in stimuli if any(k in s for k in ("threatened", "attacked", "betrayed", "witnessed", "police", "lost"))],
        "Substance": [s for s in stimuli if any(k in s for k in ("consumed", "food", "alcohol"))],
        "Environment": [s for s in stimuli if any(k in s for k in ("entered", "heard", "rested", "exercised", "listened"))],
    }
    categorized = set()
    for items in categories.values():
        categorized.update(items)
    categories["Other"] = [s for s in stimuli if s not in categorized]

    lines = ["Available neurochemistry stimuli:"]
    for cat, items in categories.items():
        if items:
            lines.append(f"\n  {cat}:")
            for item in sorted(items):
                lines.append(f"    • {item}")
    return "\n".join(lines)


@skill(
    pack="neurochemistry",
    description="Set custom neurochemistry baselines for a character's personality",
    category="SOCIAL",
    cost=2.0,
)
def set_personality_baselines(
    character_id: str,
    dopamine: Optional[float] = None,
    serotonin: Optional[float] = None,
    oxytocin: Optional[float] = None,
    cortisol: Optional[float] = None,
    adrenaline: Optional[float] = None,
    endorphins: Optional[float] = None,
) -> str:
    """Set custom neurotransmitter baselines that define a character's personality.

    Higher cortisol baseline = naturally anxious character.
    Higher oxytocin baseline = naturally trusting character.
    """
    from engine.characters.neurochemistry import get_neurochemistry_manager

    mgr = get_neurochemistry_manager()
    overrides: dict[str, float] = {}
    if dopamine is not None:
        overrides["dopamine"] = dopamine
    if serotonin is not None:
        overrides["serotonin"] = serotonin
    if oxytocin is not None:
        overrides["oxytocin"] = oxytocin
    if cortisol is not None:
        overrides["cortisol"] = cortisol
    if adrenaline is not None:
        overrides["adrenaline"] = adrenaline
    if endorphins is not None:
        overrides["endorphins"] = endorphins

    if not overrides:
        return "❌ No baselines specified. Provide at least one neurotransmitter value (0.0–1.0)."

    mgr.set_baseline(character_id, overrides)
    formatted = ", ".join(f"{k}={v:.2f}" for k, v in overrides.items())
    return f"🧬 Set baselines for {character_id}: {formatted}"
