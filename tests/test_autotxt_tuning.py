"""Unit tests for CB-T5 — calmer + more varied user autotext.

Covers the user-facing autotext tuning added in v1.62.0:

* ``autotxt_cooldown`` honours ``comms.autotxt.user_multiplier`` (global and
  per-character) and stays within the configured bounds for each conv mode,
* topic-seed selection returns a valid seed or ``None`` and never raises when
  no world events / comms exist,
* the per-character anti-repeat style picker never returns the same opener
  twice in a row.

A fake config object is injected via monkeypatching ``engine.config.get_config``
so no real config / database is touched.

Version: v1.62.0 [2026-06-15]
"""
from __future__ import annotations

from typing import Any, Dict, Optional

import pytest

from content.scenes.phone import phone_rules_v2 as rules


# ── config fixture ─────────────────────────────────────────────────────


class _FakeConfig:
    """Minimal stand-in for ConfigManager supporting dotted ``get``."""

    def __init__(self, values: Dict[str, Any]) -> None:
        self._values = values

    def get(self, path: str, default: Any = None) -> Any:
        return self._values.get(path, default)


@pytest.fixture
def set_config(monkeypatch):
    """Return a setter that installs a fake config with the given values."""

    def _set(values: Dict[str, Any]) -> None:
        monkeypatch.setattr(
            "engine.config.get_config", lambda: _FakeConfig(values), raising=True
        )

    return _set


# ── user_multiplier scaling ────────────────────────────────────────────


def _warmth_for_mode(mode: str) -> tuple:
    """Return (trust, affection) that lands in the requested cooldown tier."""
    return {
        "cold": (0.0, 0.0),
        "warm": (0.0, 30.0),
        "hot": (0.0, 50.0),
        "obsessed": (0.0, 75.0),
    }[mode]


@pytest.mark.parametrize("mode", ["cold", "warm", "hot", "obsessed"])
def test_cooldown_within_configured_bounds(set_config, mode) -> None:
    """Every draw stays within ``[lo, hi] * multiplier`` for each tier."""
    mult = 1.5
    set_config({"comms.autotxt.user_multiplier": mult})
    lo, hi = rules.AUTOTXT_COOLDOWN[mode]
    trust, affection = _warmth_for_mode(mode)
    for _ in range(200):
        val = rules.autotxt_cooldown(trust, affection)
        assert lo * mult <= val <= hi * mult


def test_multiplier_doubles_ranges(set_config) -> None:
    """A multiplier of 2.0 yields ~double the mean of a multiplier of 1.0."""
    trust, affection = _warmth_for_mode("warm")

    set_config({"comms.autotxt.user_multiplier": 1.0})
    base = [rules.autotxt_cooldown(trust, affection) for _ in range(500)]
    set_config({"comms.autotxt.user_multiplier": 2.0})
    doubled = [rules.autotxt_cooldown(trust, affection) for _ in range(500)]

    mean_base = sum(base) / len(base)
    mean_doubled = sum(doubled) / len(doubled)
    # Doubled mean should be close to 2x (allow sampling slack).
    assert 1.8 <= mean_doubled / mean_base <= 2.2


def test_per_character_override_takes_precedence(set_config) -> None:
    """A per-character multiplier overrides the global one for that char."""
    lo, hi = rules.AUTOTXT_COOLDOWN["cold"]
    set_config({
        "comms.autotxt.user_multiplier": 1.0,
        "comms.autotxt.per_character": {"clingy": 3.0},
    })
    for _ in range(200):
        eager = rules.autotxt_cooldown(0, 0, char_id="someone_else")
        clingy = rules.autotxt_cooldown(0, 0, char_id="clingy")
        assert lo * 1.0 <= eager <= hi * 1.0
        assert lo * 3.0 <= clingy <= hi * 3.0


def test_cooldown_defaults_when_config_missing(monkeypatch) -> None:
    """A config failure falls back to the module default multiplier."""

    def _boom():
        raise RuntimeError("no config")

    monkeypatch.setattr("engine.config.get_config", _boom, raising=True)
    lo, hi = rules.AUTOTXT_COOLDOWN["cold"]
    val = rules.autotxt_cooldown(0, 0)
    assert lo * rules._DEFAULT_USER_MULTIPLIER <= val <= hi * rules._DEFAULT_USER_MULTIPLIER


# ── topic seeds ────────────────────────────────────────────────────────


def test_pick_topic_seed_returns_none_when_no_sources(monkeypatch) -> None:
    """No world events and no comms → ``None`` (and no exception)."""

    def _boom():  # both sources unavailable
        raise RuntimeError("offline")

    monkeypatch.setattr("engine.world.world_sim.get_world_sim", _boom, raising=True)
    monkeypatch.setattr("engine.world.comms_log.get_comms_log", _boom, raising=True)
    assert rules.pick_topic_seed("aria") is None


def test_pick_topic_seed_returns_world_event_topic(monkeypatch) -> None:
    """A world event title is returned as a valid seed."""

    class _Ev:
        title = "Corpo blackout hits the Sprawl"
        description = ""

    class _Sim:
        def get_all_events(self, limit: int = 8):
            return [_Ev()]

    def _boom():
        raise RuntimeError("no comms")

    monkeypatch.setattr("engine.world.world_sim.get_world_sim", lambda: _Sim(), raising=True)
    monkeypatch.setattr("engine.world.comms_log.get_comms_log", _boom, raising=True)
    seed = rules.pick_topic_seed("aria")
    assert seed == "Corpo blackout hits the Sprawl"


def test_pick_topic_seed_uses_comms(monkeypatch) -> None:
    """A recent comms entry is usable as a seed when no world events exist."""

    class _Sim:
        def get_all_events(self, limit: int = 8):
            return []

    class _Log:
        def about(self, char_id, limit=8):
            return [{"content": "did you hear about the raid?", "sender_id": "user", "kind": "message"}]

    monkeypatch.setattr("engine.world.world_sim.get_world_sim", lambda: _Sim(), raising=True)
    monkeypatch.setattr("engine.world.comms_log.get_comms_log", lambda: _Log(), raising=True)
    seed = rules.pick_topic_seed("aria")
    assert seed == "did you hear about the raid?"


def test_seed_prompt_noop_when_no_topic() -> None:
    """``seed_prompt`` returns the base unchanged when topic is falsy."""
    base = "BASE PROMPT"
    assert rules.seed_prompt(base, None) == base
    assert rules.seed_prompt(base, "") == base


def test_seed_prompt_weaves_topic() -> None:
    """A topic is woven into the prompt as a reference directive."""
    out = rules.seed_prompt("BASE", "neon riots downtown")
    assert "BASE" in out
    assert "neon riots downtown" in out


def test_topic_seed_chance_default(monkeypatch) -> None:
    """``topic_seed_chance`` falls back to the module default on config error."""

    def _boom():
        raise RuntimeError("no config")

    monkeypatch.setattr("engine.config.get_config", _boom, raising=True)
    assert rules.topic_seed_chance() == rules._DEFAULT_TOPIC_CHANCE


# ── anti-repeat style picker ───────────────────────────────────────────


def test_pick_style_never_repeats_back_to_back() -> None:
    """Consecutive picks for one character use different opener styles."""
    char_id = "test_char_antirepeat"
    prev: Optional[str] = None
    for _ in range(50):
        label, prompt = rules.pick_style("warm", char_id)
        assert prompt  # non-empty scaffold
        if prev is not None:
            assert label != prev
        prev = label
    assert rules.style_label(char_id) == prev


def test_pick_style_single_entry_pool_is_stable() -> None:
    """A pool with one style returns it without crashing on the anti-repeat."""
    # 'sext' pool has 3, but force a single-entry pool to exercise the fallback.
    original = rules.AUTOTXT_STYLE_POOLS["warm"]
    try:
        rules.AUTOTXT_STYLE_POOLS["warm"] = [("only", "ONLY PROMPT")]
        label1, _ = rules.pick_style("warm", "single_pool_char")
        label2, _ = rules.pick_style("warm", "single_pool_char")
        assert label1 == label2 == "only"
    finally:
        rules.AUTOTXT_STYLE_POOLS["warm"] = original


def test_autotxt_prompt_backwards_compatible() -> None:
    """The legacy accessor still returns the canonical opener per mode."""
    assert rules.autotxt_prompt("intimate") == rules.AUTOTXT_PROMPT_INTIMATE
    assert rules.autotxt_prompt("sext") == rules.AUTOTXT_PROMPT_SEXT
    assert rules.autotxt_prompt("flirty") == rules.AUTOTXT_PROMPT_WARM
    assert rules.autotxt_prompt("anything_else") == rules.AUTOTXT_PROMPT_COLD
