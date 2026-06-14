"""
Tests: StimulusDetectInterceptor
================================

Hermetic unit tests for the NLP stimulus-detection interceptor that closes the
neurochemistry feedback loop (v1.60.0 Living Systems).

These tests are fully self-contained:
    * a FRESH NeurochemistryManager is built per test (no shared singleton),
    * persistence is redirected to a tmp dir (no data/neurochemistry.json
      pollution while the parallel agent fleet runs),
    * the interceptor's manager is swapped for the fresh one.

Version: v1.60.0 [2026-06-13]
Author:  CosySim Team

Change Log:
    v1.60.0 [2026-06-13] — Initial test suite for StimulusDetectInterceptor.
"""
from __future__ import annotations

# ──── Imports ─────────────────────────────────────────────────────────────
from typing import Tuple

import pytest

import engine.characters.neurochemistry as neuro
from engine.agents.interceptors.stimulus_detect import (
    StimulusDetectInterceptor,
    _RULES,
)
from engine.characters.neurochemistry import (
    DEFAULT_BASELINES,
    STIMULUS_CATALOG,
    NeurochemistryManager,
)
from engine.mcp.comms_framework import ResponseContext


# ──── Fixtures ────────────────────────────────────────────────────────────


@pytest.fixture()
def fresh_interceptor(tmp_path, monkeypatch) -> Tuple[StimulusDetectInterceptor, NeurochemistryManager]:
    """Build an interceptor backed by an isolated, fresh manager.

    Redirects neurochemistry persistence to ``tmp_path`` so no global state
    leaks between parallel agents/tests.
    """
    # Redirect persistence + isolate from any existing save file.
    monkeypatch.setattr(neuro, "_SAVE_DIR", tmp_path)
    mgr = NeurochemistryManager()  # _load() finds nothing in tmp_path → empty
    assert mgr.get_all_states() == {}

    interceptor = StimulusDetectInterceptor()
    interceptor._manager = mgr  # swap in the isolated manager
    # Force-enable + deterministic intensities regardless of repo config.
    interceptor._enabled = True
    interceptor._incoming_intensity = 0.6
    interceptor._reply_intensity = 0.5
    interceptor._max_rules = 4
    interceptor._min_len = 2
    return interceptor, mgr


def _ctx(**kw) -> ResponseContext:
    """Build a minimal ResponseContext."""
    base = ResponseContext(agent_id="lola", agent_name="Lola", reply="", user_message="")
    base.update(kw)
    return base


# ──── Rule-catalog integrity ──────────────────────────────────────────────


def test_all_rules_reference_real_catalog_stimuli() -> None:
    """Every rule must map to existing STIMULUS_CATALOG names."""
    for rule in _RULES:
        for stim in (rule.addressee_stimulus, rule.speaker_stimulus):
            if stim is not None:
                assert stim in STIMULUS_CATALOG, f"{rule.name}->{stim} not in catalog"


def test_construction_validates_rules(fresh_interceptor) -> None:
    """Interceptor construction validated rules without raising."""
    interceptor, _ = fresh_interceptor
    assert interceptor.name == "stimulus_detect"
    assert interceptor.priority == 88  # before MoodSync (92)


# ──── Detection ───────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    "text,expected_rule",
    [
        ("You're so beautiful tonight.", "compliment"),
        ("Thank you so much for helping me.", "gratitude"),
        ("It's okay, I'm here for you.", "comfort"),
        ("She leans in to kiss him softly.", "kiss"),
        ("He wraps his arms around you in a warm hug.", "embrace"),
        ("I gently caress your cheek.", "physical_touch"),
        ("Leave me alone, we're done.", "rejection"),
        ("You're such a pathetic idiot.", "insult"),
        ("I'll kill you if you come back.", "threat"),
        ("You betrayed me, I trusted you.", "betrayal"),
    ],
)
def test_detect_matches_expected_rule(fresh_interceptor, text, expected_rule) -> None:
    """Each distinctive phrasing fires the intended rule."""
    interceptor, _ = fresh_interceptor
    names = {r.name for r in interceptor.detect(text)}
    assert expected_rule in names, f"{expected_rule!r} not detected in {text!r}; got {names}"


def test_detect_neutral_text_no_match(fresh_interceptor) -> None:
    """Neutral chatter triggers nothing (precision over recall)."""
    interceptor, _ = fresh_interceptor
    assert interceptor.detect("The market opens at nine and closes at five.") == []
    assert interceptor.detect("") == []
    assert interceptor.detect("ok") == []  # below min_len boundary handled


def test_detect_respects_max_rules_cap(fresh_interceptor) -> None:
    """The per-text rule cap is honored."""
    interceptor, _ = fresh_interceptor
    interceptor._max_rules = 1
    # A line that is both a compliment and a kiss → would match 2, capped to 1.
    text = "You're so beautiful, she said as she kissed him."
    assert len(interceptor.detect(text)) == 1


# ──── Application: incoming line affects the addressed agent ───────────────


def test_incoming_compliment_raises_dopamine(fresh_interceptor) -> None:
    """A compliment in the user_message lifts the agent's reward chemistry."""
    interceptor, mgr = fresh_interceptor
    ctx = _ctx(user_message="You're absolutely brilliant!", reply="Thanks.")
    applied = interceptor.post_call(ctx)
    assert applied >= 1
    state = mgr.get_state("lola")
    assert state is not None
    # received_compliment moves dopamine/serotonin/oxytocin up from baseline.
    assert state.levels["dopamine"] > DEFAULT_BASELINES["dopamine"]
    assert state.levels["oxytocin"] > DEFAULT_BASELINES["oxytocin"]


def test_incoming_threat_raises_cortisol_and_adrenaline(fresh_interceptor) -> None:
    """A threat addressed to the agent spikes stress chemistry."""
    interceptor, mgr = fresh_interceptor
    ctx = _ctx(user_message="I'll destroy you, watch your back.", reply="...")
    interceptor.post_call(ctx)
    state = mgr.get_state("lola")
    assert state is not None
    assert state.levels["cortisol"] > DEFAULT_BASELINES["cortisol"]
    assert state.levels["adrenaline"] > DEFAULT_BASELINES["adrenaline"]


def test_incoming_rejection_lowers_dopamine(fresh_interceptor) -> None:
    """Rejection addressed to the agent depresses reward chemistry."""
    interceptor, mgr = fresh_interceptor
    ctx = _ctx(user_message="Go away, I never want to see you again.", reply="ok")
    interceptor.post_call(ctx)
    state = mgr.get_state("lola")
    assert state is not None
    assert state.levels["dopamine"] < DEFAULT_BASELINES["dopamine"]
    assert state.levels["cortisol"] > DEFAULT_BASELINES["cortisol"]


# ──── Application: reflexive (speaker) effect from the reply ───────────────


def test_reply_gave_compliment_is_reflexive_on_speaker(fresh_interceptor) -> None:
    """The agent complimenting someone gives itself a small oxytocin lift."""
    interceptor, mgr = fresh_interceptor
    ctx = _ctx(user_message="hi", reply="You look gorgeous, truly.")
    applied = interceptor.post_call(ctx)
    assert applied >= 1
    state = mgr.get_state("lola")
    assert state is not None
    # gave_compliment raises oxytocin/serotonin for the speaker.
    assert state.levels["oxytocin"] > DEFAULT_BASELINES["oxytocin"]


def test_reply_kiss_affects_known_ai_target(fresh_interceptor) -> None:
    """When target_id resolves to another AI, the reply kiss lands on it too."""
    interceptor, mgr = fresh_interceptor
    ctx = _ctx(
        user_message="hey",
        reply="She leans in and kisses him deeply.",
        target_id="viktor",
    )
    interceptor.post_call(ctx)
    # Speaker (lola) gets reflexive kiss; target (viktor) gets addressee kiss.
    lola = mgr.get_state("lola")
    viktor = mgr.get_state("viktor")
    assert lola is not None and viktor is not None
    assert lola.levels["oxytocin"] > DEFAULT_BASELINES["oxytocin"]
    assert viktor.levels["oxytocin"] > DEFAULT_BASELINES["oxytocin"]


def test_target_equal_to_speaker_is_ignored(fresh_interceptor) -> None:
    """A target_id identical to the speaker must not create a phantom state."""
    interceptor, mgr = fresh_interceptor
    ctx = _ctx(user_message="hi", reply="I kiss you.", target_id="lola")
    interceptor.post_call(ctx)
    # Only 'lola' exists, no duplicate / self-target double-apply path crash.
    assert set(mgr.get_all_states().keys()) == {"lola"}


# ──── Guards ──────────────────────────────────────────────────────────────


def test_disabled_interceptor_does_nothing(fresh_interceptor) -> None:
    """When disabled, no stimuli are applied and no state is created."""
    interceptor, mgr = fresh_interceptor
    interceptor._enabled = False
    ctx = _ctx(user_message="You're amazing!", reply="You're amazing too!")
    assert interceptor.post_call(ctx) == 0
    assert mgr.get_all_states() == {}


def test_missing_agent_id_is_noop(fresh_interceptor) -> None:
    """No agent_id → nothing happens, no crash."""
    interceptor, mgr = fresh_interceptor
    ctx = ResponseContext(reply="You're beautiful", user_message="hi")
    assert interceptor.post_call(ctx) == 0
    assert mgr.get_all_states() == {}


def test_neutral_turn_is_noop(fresh_interceptor) -> None:
    """A fully neutral exchange applies zero stimuli."""
    interceptor, mgr = fresh_interceptor
    ctx = _ctx(
        user_message="What time does the shop open?",
        reply="It opens at nine in the morning.",
    )
    assert interceptor.post_call(ctx) == 0
    assert mgr.get_all_states() == {}
