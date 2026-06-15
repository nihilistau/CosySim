"""Unit tests for PlayerState.allegiance (v1.63.0 C-T2).

Covers the persisted faction-allegiance field added for the War Room:
validation against the 6 canonical factions, persistence + save/load
round-trip, inclusion in ``to_dict``, and backward-compatibility with old
save files that lack the field (must load as ``None``).
"""
from __future__ import annotations

from pathlib import Path

from engine.world.player_state import PlayerState


def _fresh_state(tmp_path: Path) -> PlayerState:
    """Return a PlayerState whose save path points at an isolated temp file.

    Args:
        tmp_path: pytest tmp dir.

    Returns:
        A PlayerState with no pre-existing save loaded.
    """
    orig = PlayerState._SAVE_PATH
    try:
        PlayerState._SAVE_PATH = tmp_path / "player_state.json"
        return PlayerState()
    finally:
        PlayerState._SAVE_PATH = orig


def test_default_allegiance_is_none(tmp_path: Path) -> None:
    ps = _fresh_state(tmp_path)
    assert ps.allegiance is None


def test_set_allegiance_valid_faction(tmp_path: Path) -> None:
    ps = _fresh_state(tmp_path)
    assert ps.set_allegiance("Ghost_Net") is True
    assert ps.allegiance == "Ghost_Net"


def test_set_allegiance_all_six_canonical(tmp_path: Path) -> None:
    canonical = [
        "OmniCorp", "NeoTech", "BlackMarket",
        "Ghost_Net", "SynthSec", "DeepState",
    ]
    ps = _fresh_state(tmp_path)
    for f in canonical:
        assert ps.set_allegiance(f) is True
        assert ps.allegiance == f


def test_set_allegiance_rejects_unknown(tmp_path: Path) -> None:
    ps = _fresh_state(tmp_path)
    ps.set_allegiance("Ghost_Net")
    # An invalid faction must be rejected and leave the prior value intact.
    assert ps.set_allegiance("MegaCorp_X") is False
    assert ps.allegiance == "Ghost_Net"


def test_set_allegiance_none_clears(tmp_path: Path) -> None:
    ps = _fresh_state(tmp_path)
    ps.set_allegiance("SynthSec")
    assert ps.set_allegiance(None) is True
    assert ps.allegiance is None


def test_allegiance_in_to_dict(tmp_path: Path) -> None:
    ps = _fresh_state(tmp_path)
    assert ps.to_dict()["allegiance"] is None
    ps.set_allegiance("DeepState")
    assert ps.to_dict()["allegiance"] == "DeepState"


def test_allegiance_persists_round_trip(tmp_path: Path) -> None:
    save = tmp_path / "ps.json"
    ps = _fresh_state(tmp_path)
    ps.set_allegiance("BlackMarket")
    ps.save_to_file(save)

    # Fresh instance loading the saved file recovers the allegiance.
    other = _fresh_state(tmp_path)
    assert other.allegiance is None
    assert other.load_from_file(save) is True
    assert other.allegiance == "BlackMarket"


def test_old_save_without_field_loads_as_none(tmp_path: Path) -> None:
    import json

    # Simulate a legacy save file with no 'allegiance' key.
    legacy = tmp_path / "legacy.json"
    legacy.write_text(json.dumps({"credits": 1234, "reputation": 60}), encoding="utf-8")

    ps = _fresh_state(tmp_path)
    ps.set_allegiance("OmniCorp")  # prior in-memory value
    assert ps.load_from_file(legacy) is True
    # Absent field => None (backward compatible, not the stale prior value).
    assert ps.allegiance is None
    assert ps.credits == 1234
