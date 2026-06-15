"""Unit tests for pairwise NPC↔NPC relationship effects (CB-T6).

Covers the delta model (warm/cool/neutral tone + keyword affect), the canonical
Database write path (read back via ``get_relationship``), clamping to the
store's ``[0, 1]`` range, and gradual accumulation toward the cap over repeated
friendly exchanges. Uses the project's ``temp_db`` fixture so the real DB is
never touched.

Version: v1.62.0 [2026-06-15]
"""
from __future__ import annotations

import pytest

from engine.world.relationship_effects import (
    apply_exchange_effect,
    apply_observed_effect,
    apply_pair_delta,
    compute_delta,
)


# ── delta model ───────────────────────────────────────────────────────────


def test_warm_tone_yields_positive_delta() -> None:
    """A warm-tone exchange produces a positive delta."""
    assert compute_delta("you around tonight?", "warm") > 0


def test_cool_tone_yields_negative_delta() -> None:
    """A cool-tone exchange produces a negative delta."""
    assert compute_delta("keep my name out of it.", "cool") < 0


def test_neutral_tone_yields_small_positive_delta() -> None:
    """A neutral-tone exchange drifts slightly positive (acquaintance growth)."""
    d = compute_delta("heard anything new lately?", "neutral")
    assert 0 < d < compute_delta("hey you", "warm")


def test_positive_keyword_boosts_delta() -> None:
    """A positive keyword adds on top of the tone delta."""
    base = compute_delta("just checking in", "neutral")
    boosted = compute_delta("can i get a hug later", "neutral")
    assert boosted > base


def test_negative_keyword_lowers_delta() -> None:
    """A negative keyword can flip a neutral exchange negative."""
    assert compute_delta("don't you dare insult me", "neutral") < 0


def test_delta_is_capped_by_max_step() -> None:
    """The net delta never exceeds max_step in magnitude."""
    # warm tone + positive keyword stacks but stays bounded.
    d = compute_delta("kiss kiss, miss you", "warm")
    assert abs(d) <= 0.06 + 1e-9


# ── canonical write path + clamping ───────────────────────────────────────


def test_friendly_exchange_raises_relationship_level(temp_db) -> None:
    """A warm/friendly exchange raises the pair's relationship_level."""
    temp_db.get_or_create_relationship("lola", "viktor", relationship_level=0.4)
    before = temp_db.get_relationship("lola", "viktor")["relationship_level"]
    apply_exchange_effect(temp_db, "lola", "viktor", "miss your face 💕", "warm")
    after = temp_db.get_relationship("lola", "viktor")["relationship_level"]
    assert after > before


def test_hostile_exchange_lowers_relationship_level(temp_db) -> None:
    """A cool/hostile exchange lowers the pair's relationship_level."""
    temp_db.get_or_create_relationship("lola", "viktor", relationship_level=0.6)
    before = temp_db.get_relationship("lola", "viktor")["relationship_level"]
    apply_exchange_effect(temp_db, "lola", "viktor", "we need to talk. not here.", "cool")
    after = temp_db.get_relationship("lola", "viktor")["relationship_level"]
    assert after < before


def test_effect_is_mutual_order_independent(temp_db) -> None:
    """The pair store is mutual: (a,b) and (b,a) resolve to the same row."""
    apply_exchange_effect(temp_db, "aria", "frankie", "drinks soon?", "warm")
    via_ab = temp_db.get_relationship("aria", "frankie")["relationship_level"]
    via_ba = temp_db.get_relationship("frankie", "aria")["relationship_level"]
    assert via_ab == via_ba


def test_deltas_are_small(temp_db) -> None:
    """A single exchange moves the level only a little (gradual drift)."""
    temp_db.get_or_create_relationship("lola", "mira", relationship_level=0.5)
    apply_exchange_effect(temp_db, "lola", "mira", "you around tonight?", "warm")
    after = temp_db.get_relationship("lola", "mira")["relationship_level"]
    assert abs(after - 0.5) <= 0.06 + 1e-9


def test_clamped_to_upper_bound(temp_db) -> None:
    """relationship_level never exceeds the store's max (1.0)."""
    temp_db.get_or_create_relationship("lola", "viktor", relationship_level=0.99)
    for _ in range(20):
        apply_exchange_effect(temp_db, "lola", "viktor", "kiss kiss 💕", "warm")
    after = temp_db.get_relationship("lola", "viktor")["relationship_level"]
    assert after <= 1.0


def test_clamped_to_lower_bound(temp_db) -> None:
    """relationship_level never drops below the store's min (0.0)."""
    temp_db.get_or_create_relationship("lola", "viktor", relationship_level=0.01)
    for _ in range(20):
        apply_exchange_effect(temp_db, "lola", "viktor", "i insult you", "cool")
    after = temp_db.get_relationship("lola", "viktor")["relationship_level"]
    assert after >= 0.0


def test_repeated_friendly_exchanges_accumulate(temp_db) -> None:
    """Repeated friendly exchanges accumulate toward the cap, monotonically."""
    temp_db.get_or_create_relationship("aria", "lola", relationship_level=0.3)
    levels = []
    for _ in range(8):
        apply_exchange_effect(temp_db, "aria", "lola", "wouldn't miss it", "warm")
        levels.append(temp_db.get_relationship("aria", "lola")["relationship_level"])
    # Strictly increasing until it would hit the cap.
    assert levels == sorted(levels)
    assert levels[-1] > 0.3


def test_creates_relationship_for_unseeded_pair(temp_db) -> None:
    """An unseeded pair is created at the store default then nudged."""
    assert temp_db.get_relationship("viktor", "mira") is None
    apply_exchange_effect(temp_db, "viktor", "mira", "drinks soon?", "warm")
    rel = temp_db.get_relationship("viktor", "mira")
    assert rel is not None and rel["relationship_level"] > 0.5


# ── helpers / forward-compat hook ─────────────────────────────────────────


def test_apply_pair_delta_returns_new_level(temp_db) -> None:
    """apply_pair_delta returns the new clamped level."""
    temp_db.get_or_create_relationship("lola", "viktor", relationship_level=0.5)
    new = apply_pair_delta(temp_db, "lola", "viktor", 0.05)
    assert new == pytest.approx(0.55)


def test_apply_pair_delta_noop_on_none_db() -> None:
    """No db → no-op, returns None."""
    assert apply_pair_delta(None, "a", "b", 0.05) is None


def test_apply_pair_delta_noop_on_zero_delta(temp_db) -> None:
    """A zero delta is a no-op."""
    assert apply_pair_delta(temp_db, "a", "b", 0.0) is None


def test_apply_observed_effect_wraps_delta_logic(temp_db) -> None:
    """The forward-compat observed hook applies a standing change like exchanges."""
    temp_db.get_or_create_relationship("aria", "viktor", relationship_level=0.5)
    before = temp_db.get_relationship("aria", "viktor")["relationship_level"]
    apply_observed_effect(temp_db, "aria", "viktor", "saw them kiss someone", "warm")
    after = temp_db.get_relationship("aria", "viktor")["relationship_level"]
    assert after > before
