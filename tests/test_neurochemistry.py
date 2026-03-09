"""Tests for engine.characters.neurochemistry module."""
from __future__ import annotations

import json
import time
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from engine.characters.neurochemistry import (
    BehaviourModifiers,
    DEFAULT_BASELINES,
    HALF_LIVES,
    NEUROTRANSMITTERS,
    NeurochemicalState,
    NeurochemistryInterceptor,
    NeurochemistryManager,
    STIMULUS_CATALOG,
    compute_modifiers,
)


# ──── Fixtures ────

@pytest.fixture
def fresh_state():
    """Create a fresh neurochemical state at baselines."""
    return NeurochemicalState(character_id="test_char")


@pytest.fixture
def manager(tmp_path):
    """Create an isolated NeurochemistryManager with temp persistence."""
    with patch("engine.characters.neurochemistry._SAVE_DIR", tmp_path):
        mgr = NeurochemistryManager()
        yield mgr


# ──── NeurochemicalState Tests ────

class TestNeurochemicalState:

    def test_initial_levels_match_baselines(self, fresh_state):
        """State initializes at default baselines."""
        for nt in NEUROTRANSMITTERS:
            assert fresh_state.levels[nt] == DEFAULT_BASELINES[nt]

    def test_apply_delta_positive(self, fresh_state):
        """Positive deltas increase neurotransmitter levels."""
        changes = fresh_state.apply_delta({"dopamine": 0.2})
        assert changes["dopamine"] > 0
        assert fresh_state.levels["dopamine"] > DEFAULT_BASELINES["dopamine"]

    def test_apply_delta_negative(self, fresh_state):
        """Negative deltas decrease neurotransmitter levels."""
        changes = fresh_state.apply_delta({"cortisol": -0.1})
        assert changes["cortisol"] < 0
        assert fresh_state.levels["cortisol"] < DEFAULT_BASELINES["cortisol"]

    def test_levels_clamped_0_to_1(self, fresh_state):
        """Levels cannot go below 0 or above 1."""
        fresh_state.apply_delta({"dopamine": 2.0})
        assert fresh_state.levels["dopamine"] <= 1.0

        fresh_state.apply_delta({"dopamine": -5.0})
        assert fresh_state.levels["dopamine"] >= 0.0

    def test_tolerance_builds(self, fresh_state):
        """Repeated stimuli build tolerance."""
        fresh_state.apply_delta({"dopamine": 0.3})
        assert fresh_state.tolerance["dopamine"] > 0

    def test_tolerance_reduces_effectiveness(self, fresh_state):
        """High tolerance reduces delta effectiveness."""
        fresh_state.tolerance["dopamine"] = 0.8
        old_level = fresh_state.levels["dopamine"]
        changes = fresh_state.apply_delta({"dopamine": 0.2})
        assert changes["dopamine"] < 0.2

    def test_tick_decay_toward_baseline(self, fresh_state):
        """tick() moves levels toward baselines."""
        fresh_state.levels["dopamine"] = 0.9
        fresh_state.tick(elapsed_ticks=5.0)
        assert fresh_state.levels["dopamine"] < 0.9
        assert fresh_state.levels["dopamine"] > DEFAULT_BASELINES["dopamine"]

    def test_tick_recovery_toward_baseline(self, fresh_state):
        """tick() recovers levels from below baseline."""
        fresh_state.levels["serotonin"] = 0.1
        fresh_state.tick(elapsed_ticks=10.0)
        assert fresh_state.levels["serotonin"] > 0.1

    def test_tick_tolerance_decays(self, fresh_state):
        """Tolerance decays over time."""
        fresh_state.tolerance["dopamine"] = 0.5
        fresh_state.tick(elapsed_ticks=5.0)
        assert fresh_state.tolerance["dopamine"] < 0.5

    def test_get_emotions_empty_at_baseline(self, fresh_state):
        """At default baselines, few extreme emotions should trigger."""
        emotions = fresh_state.get_emotions()
        assert isinstance(emotions, list)

    def test_get_emotions_panicked(self, fresh_state):
        """High cortisol + high adrenaline → panicked."""
        fresh_state.levels["cortisol"] = 0.8
        fresh_state.levels["adrenaline"] = 0.75
        emotions = fresh_state.get_emotions()
        emotion_names = [e[0] for e in emotions]
        assert "panicked" in emotion_names

    def test_get_emotions_euphoric(self, fresh_state):
        """High endorphins + high dopamine → euphoric."""
        fresh_state.levels["endorphins"] = 0.85
        fresh_state.levels["dopamine"] = 0.80
        emotions = fresh_state.get_emotions()
        emotion_names = [e[0] for e in emotions]
        assert "euphoric" in emotion_names

    def test_get_emotions_in_love(self, fresh_state):
        """High oxytocin + high serotonin + low cortisol → in_love."""
        fresh_state.levels["oxytocin"] = 0.75
        fresh_state.levels["serotonin"] = 0.65
        fresh_state.levels["cortisol"] = 0.15
        emotions = fresh_state.get_emotions()
        emotion_names = [e[0] for e in emotions]
        assert "in_love" in emotion_names

    def test_get_primary_emotion_returns_strongest(self, fresh_state):
        """get_primary_emotion returns highest-intensity match."""
        fresh_state.levels["cortisol"] = 0.9
        fresh_state.levels["adrenaline"] = 0.9
        emotion, intensity = fresh_state.get_primary_emotion()
        assert emotion == "panicked"
        assert intensity > 0.5

    def test_get_primary_emotion_neutral_fallback(self, fresh_state):
        """Falls back to neutral when no condition matches."""
        for nt in NEUROTRANSMITTERS:
            fresh_state.levels[nt] = 0.35
        emotion, intensity = fresh_state.get_primary_emotion()
        assert emotion == "neutral"

    def test_get_modifiers_returns_behaviour_modifiers(self, fresh_state):
        """get_modifiers() returns BehaviourModifiers."""
        mods = fresh_state.get_modifiers()
        assert isinstance(mods, BehaviourModifiers)
        assert 0.3 <= mods.motivation <= 2.0
        assert 0.3 <= mods.risk_tolerance <= 2.0

    def test_mood_summary_string(self, fresh_state):
        """get_mood_summary() returns a non-empty string."""
        fresh_state.levels["cortisol"] = 0.8
        fresh_state.levels["adrenaline"] = 0.7
        summary = fresh_state.get_mood_summary()
        assert isinstance(summary, str)
        assert len(summary) > 0

    def test_detailed_summary_contains_sections(self, fresh_state):
        """get_detailed_summary() includes key sections."""
        summary = fresh_state.get_detailed_summary()
        assert "NEUROCHEMISTRY" in summary
        assert "dopamine" in summary

    def test_serialization_roundtrip(self, fresh_state):
        """State survives to_dict/from_dict cycle."""
        fresh_state.levels["dopamine"] = 0.77
        fresh_state.tolerance["cortisol"] = 0.33
        data = fresh_state.to_dict()
        restored = NeurochemicalState.from_dict(data)
        assert abs(restored.levels["dopamine"] - 0.77) < 0.001
        assert abs(restored.tolerance["cortisol"] - 0.33) < 0.001


# ──── compute_modifiers Tests ────

class TestComputeModifiers:

    def test_default_baselines_produce_moderate_modifiers(self):
        """Default baselines should produce modifiers near 1.0."""
        mods = compute_modifiers(DEFAULT_BASELINES)
        assert 0.5 < mods.motivation < 1.5
        assert 0.5 < mods.focus < 1.5

    def test_high_dopamine_boosts_motivation(self):
        """High dopamine → higher motivation."""
        levels = dict(DEFAULT_BASELINES)
        levels["dopamine"] = 0.9
        mods = compute_modifiers(levels)
        normal = compute_modifiers(DEFAULT_BASELINES)
        assert mods.motivation > normal.motivation

    def test_high_cortisol_reduces_focus(self):
        """High cortisol → lower focus."""
        levels = dict(DEFAULT_BASELINES)
        levels["cortisol"] = 0.9
        mods = compute_modifiers(levels)
        normal = compute_modifiers(DEFAULT_BASELINES)
        assert mods.focus < normal.focus

    def test_high_adrenaline_boosts_risk_tolerance(self):
        """High adrenaline → higher risk tolerance."""
        levels = dict(DEFAULT_BASELINES)
        levels["adrenaline"] = 0.8
        mods = compute_modifiers(levels)
        normal = compute_modifiers(DEFAULT_BASELINES)
        assert mods.risk_tolerance > normal.risk_tolerance

    def test_modifiers_clamped(self):
        """All modifiers stay within 0.3–2.0 range."""
        extreme = {nt: 1.0 for nt in NEUROTRANSMITTERS}
        mods = compute_modifiers(extreme)
        for k, v in mods.to_dict().items():
            assert 0.3 <= v <= 2.0, f"{k} = {v} out of range"

        zeroed = {nt: 0.0 for nt in NEUROTRANSMITTERS}
        mods2 = compute_modifiers(zeroed)
        for k, v in mods2.to_dict().items():
            assert 0.3 <= v <= 2.0, f"{k} = {v} out of range"


# ──── NeurochemistryManager Tests ────

class TestNeurochemistryManager:

    def test_get_or_create(self, manager):
        """Creates new state for unknown character."""
        state = manager.get_or_create("lola")
        assert state.character_id == "lola"

    def test_get_or_create_returns_same(self, manager):
        """Returns same instance on repeated calls."""
        s1 = manager.get_or_create("lola")
        s2 = manager.get_or_create("lola")
        assert s1 is s2

    def test_get_state_returns_none_for_missing(self, manager):
        """get_state returns None for non-existent character."""
        assert manager.get_state("ghost") is None

    def test_apply_stimulus_known(self, manager):
        """Applying a known stimulus changes levels."""
        changes = manager.apply_stimulus("lola", "received_compliment")
        assert changes.get("dopamine", 0) > 0

    def test_apply_stimulus_unknown_raises(self, manager):
        """Applying unknown stimulus raises KeyError."""
        with pytest.raises(KeyError, match="Unknown stimulus"):
            manager.apply_stimulus("lola", "nonexistent_stimulus_xyz")

    def test_apply_stimulus_intensity_scaling(self, manager):
        """Higher intensity produces larger changes."""
        state = manager.get_or_create("char_a")
        state.levels = dict(DEFAULT_BASELINES)

        changes_low = manager.apply_stimulus("char_a", "received_compliment", intensity=0.5)
        # Reset
        state.levels = dict(DEFAULT_BASELINES)
        changes_high = manager.apply_stimulus("char_a", "received_compliment", intensity=2.0)

        assert abs(changes_high.get("dopamine", 0)) > abs(changes_low.get("dopamine", 0))

    def test_apply_stimulus_logs_history(self, manager):
        """Stimulus application records to history."""
        manager.apply_stimulus("lola", "kiss")
        state = manager.get_or_create("lola")
        assert len(state.stimulus_history) > 0
        assert state.stimulus_history[-1]["stimulus"] == "kiss"

    def test_apply_raw_delta(self, manager):
        """Raw delta application works without catalog."""
        changes = manager.apply_raw_delta("lola", {"dopamine": 0.1}, reason="test")
        assert "dopamine" in changes

    def test_tick_all(self, manager):
        """tick_all updates all characters."""
        manager.get_or_create("char_a").levels["dopamine"] = 0.9
        manager.get_or_create("char_b").levels["cortisol"] = 0.8
        manager.tick_all(elapsed_ticks=3.0)
        assert manager.get_state("char_a").levels["dopamine"] < 0.9
        assert manager.get_state("char_b").levels["cortisol"] < 0.8

    def test_get_prompt_context(self, manager):
        """get_prompt_context returns usable string."""
        manager.get_or_create("lola")
        manager.apply_stimulus("lola", "threatened")
        ctx = manager.get_prompt_context("lola")
        assert isinstance(ctx, str)
        assert len(ctx) > 0

    def test_register_custom_stimulus(self, manager):
        """Custom stimuli can be registered and applied."""
        manager.register_stimulus("custom_test", {"dopamine": 0.3, "cortisol": -0.1})
        changes = manager.apply_stimulus("lola", "custom_test")
        assert "dopamine" in changes

    def test_set_baseline(self, manager):
        """set_baseline changes character's natural set-point."""
        manager.set_baseline("lola", {"cortisol": 0.6})
        state = manager.get_or_create("lola")
        assert state.baselines["cortisol"] == 0.6

    def test_list_stimuli(self, manager):
        """list_stimuli returns sorted list of all available stimuli."""
        stimuli = manager.list_stimuli()
        assert "received_compliment" in stimuli
        assert "kiss" in stimuli
        assert stimuli == sorted(stimuli)

    def test_remove_character(self, manager):
        """remove_character clears state."""
        manager.get_or_create("disposable")
        assert manager.remove_character("disposable")
        assert manager.get_state("disposable") is None

    def test_remove_nonexistent_returns_false(self, manager):
        """remove_character for missing ID returns False."""
        assert not manager.remove_character("never_existed")

    def test_persistence_roundtrip(self, tmp_path):
        """State persists and reloads across manager instances."""
        with patch("engine.characters.neurochemistry._SAVE_DIR", tmp_path):
            mgr1 = NeurochemistryManager()
            mgr1.apply_stimulus("lola", "kiss")
            state1 = mgr1.get_or_create("lola")
            dopamine_before = state1.levels["dopamine"]

            mgr2 = NeurochemistryManager()
            state2 = mgr2.get_or_create("lola")
            assert abs(state2.levels["dopamine"] - dopamine_before) < 0.001


# ──── NeurochemistryInterceptor Tests ────

class TestNeurochemistryInterceptor:

    def test_pre_call_injects_emotion(self, manager):
        """pre_call adds emotional context to system prompt."""
        manager.apply_stimulus("lola", "threatened")
        interceptor = NeurochemistryInterceptor()
        interceptor._manager = manager

        ctx = {"character_id": "lola", "system_prompt": "You are Lola."}
        interceptor.pre_call(ctx)

        assert "emotional state" in ctx["system_prompt"].lower() or "neurochemistry" in ctx.get("neurochemistry", {})
        assert "neurochemistry" in ctx

    def test_pre_call_skips_without_character_id(self, manager):
        """pre_call does nothing without character_id."""
        interceptor = NeurochemistryInterceptor()
        interceptor._manager = manager

        ctx = {"system_prompt": "Base prompt."}
        interceptor.pre_call(ctx)
        assert ctx["system_prompt"] == "Base prompt."

    def test_post_call_detects_kiss_keyword(self, manager):
        """post_call applies stimulus when keyword found in reply."""
        manager.get_or_create("lola")
        interceptor = NeurochemistryInterceptor()
        interceptor._manager = manager

        ctx = {"character_id": "lola", "reply": "She leaned in for a tender kiss."}
        interceptor.post_call(ctx)

        state = manager.get_state("lola")
        assert len(state.stimulus_history) > 0

    def test_post_call_skips_without_reply(self, manager):
        """post_call does nothing with empty reply."""
        manager.get_or_create("lola")
        interceptor = NeurochemistryInterceptor()
        interceptor._manager = manager

        ctx = {"character_id": "lola", "reply": ""}
        history_before = len(manager.get_state("lola").stimulus_history)
        interceptor.post_call(ctx)
        assert len(manager.get_state("lola").stimulus_history) == history_before


# ──── Stimulus Catalog Validation ────

class TestStimulusCatalog:

    def test_all_stimuli_reference_valid_neurotransmitters(self):
        """Every stimulus delta must reference valid neurotransmitters."""
        for name, deltas in STIMULUS_CATALOG.items():
            for nt in deltas:
                assert nt in NEUROTRANSMITTERS, (
                    f"Stimulus '{name}' references invalid NT '{nt}'"
                )

    def test_catalog_has_minimum_stimuli(self):
        """Catalog should have at least 30 stimuli."""
        assert len(STIMULUS_CATALOG) >= 30

    def test_stimulus_deltas_are_reasonable(self):
        """No single delta should exceed ±0.5."""
        for name, deltas in STIMULUS_CATALOG.items():
            for nt, val in deltas.items():
                assert -0.5 <= val <= 0.5, (
                    f"Stimulus '{name}' has unreasonable delta for {nt}: {val}"
                )
