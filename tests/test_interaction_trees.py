"""
Test Interaction Trees
======================

Tests for the interaction tree system (types, subtypes, phases, availability).

Version: v1.52.0 [2026-03-25]
Author:  CosySim Team

Change Log:
    v1.52.0 [2026-03-25] — Migrated from unittest.TestCase to plain pytest (audit remediation)
"""
from __future__ import annotations

from engine.mcp.interaction_trees import (
    PENTHOUSE_INTERACTIONS,
    PHONE_INTERACTIONS,
    InteractionSubtype,
    InteractionType,
    get_available_interactions,
    get_interaction_result,
    list_interaction_types,
)


# ═══════════════════════════════════════════════════════════════════════
#  Helpers
# ═══════════════════════════════════════════════════════════════════════

def _make_interaction_type() -> InteractionType:
    """Build a simple InteractionType with low/mid/high subtypes."""
    subs = [
        InteractionSubtype(id="low", label="Low", description="", duration=5,
                           intimacy=1, stat_effects={}, phases=["p1"], fragments=["f1"]),
        InteractionSubtype(id="mid", label="Mid", description="", duration=10,
                           intimacy=3, stat_effects={}, phases=["p1", "p2"],
                           fragments=["f1", "f2"]),
        InteractionSubtype(id="high", label="High", description="", duration=20,
                           intimacy=5, stat_effects={}, phases=["p1", "p2", "p3"],
                           fragments=["f1", "f2", "f3"]),
    ]
    return InteractionType(id="test", label="Test", description="desc",
                           subtypes=subs, default_subtype="low")


# ═══════════════════════════════════════════════════════════════════════
#  DATA-CLASS TESTS
# ═══════════════════════════════════════════════════════════════════════

def test_subtype_fields():
    sub = InteractionSubtype(
        id="test", label="Test", description="A test subtype",
        duration=10.0, intimacy=2,
        stat_effects={"happiness": 10},
        phases=["start", "middle", "end"],
        fragments=["fragment one"],
    )
    assert sub.id == "test"
    assert sub.intimacy == 2
    assert sub.phases == ["start", "middle", "end"]
    assert sub.requires == {}  # default empty


def test_subtype_requires_default_factory():
    s1 = InteractionSubtype(id="a", label="A", description="", duration=5,
                            intimacy=1, stat_effects={}, phases=[], fragments=[])
    s2 = InteractionSubtype(id="b", label="B", description="", duration=5,
                            intimacy=1, stat_effects={}, phases=[], fragments=[])
    assert s1.requires is not s2.requires


def test_type_get_subtype():
    it = _make_interaction_type()
    assert it.get_subtype("mid").label == "Mid"
    assert it.get_subtype("nonexistent") is None


def test_type_random_subtype_filters_by_intimacy():
    it = _make_interaction_type()
    for _ in range(20):
        sub = it.random_subtype(min_intimacy=1, max_intimacy=1)
        assert sub.id == "low"


def test_type_random_subtype_fallback():
    """If no subtypes match the range, returns first subtype."""
    it = _make_interaction_type()
    sub = it.random_subtype(min_intimacy=99, max_intimacy=99)
    assert sub.id == "low"


def test_type_subtype_ids():
    it = _make_interaction_type()
    assert it.subtype_ids() == ["low", "mid", "high"]


# ═══════════════════════════════════════════════════════════════════════
#  BUILT-IN INTERACTION REGISTRIES
# ═══════════════════════════════════════════════════════════════════════

def test_bedroom_expected_types_exist():
    expected = {"cuddle", "kiss", "caress", "striptease"}
    assert expected.issubset(set(PENTHOUSE_INTERACTIONS.keys()))


def test_bedroom_each_type_has_subtypes():
    for iid, it in PENTHOUSE_INTERACTIONS.items():
        assert len(it.subtypes) > 0, f"{iid} has no subtypes"


def test_bedroom_subtypes_have_phases():
    for iid, it in PENTHOUSE_INTERACTIONS.items():
        for sub in it.subtypes:
            assert len(sub.phases) > 0, f"{iid}/{sub.id} has no phases"


def test_bedroom_subtypes_have_fragments():
    for iid, it in PENTHOUSE_INTERACTIONS.items():
        for sub in it.subtypes:
            assert len(sub.fragments) > 0, f"{iid}/{sub.id} has no fragments"


def test_phone_expected_types_exist():
    expected = {"flirt_text", "voice_call", "video_call", "send_media"}
    assert expected.issubset(set(PHONE_INTERACTIONS.keys()))


def test_phone_each_type_has_subtypes():
    for iid, it in PHONE_INTERACTIONS.items():
        assert len(it.subtypes) > 0, f"{iid} has no subtypes"


# ═══════════════════════════════════════════════════════════════════════
#  get_interaction_result
# ═══════════════════════════════════════════════════════════════════════

def test_result_known_type_returns_result():
    result = get_interaction_result("cuddle", "embrace")
    assert result["type"] == "cuddle"
    assert result["subtype"] == "embrace"
    assert "phases" in result
    assert "stat_effects" in result
    assert "fragments" in result


def test_result_unknown_type_returns_error():
    result = get_interaction_result("teleport")
    assert "error" in result


def test_result_unknown_subtype_falls_back():
    result = get_interaction_result("cuddle", "nonexistent")
    # Should fall back to first subtype
    assert "error" not in result
    assert result["type"] == "cuddle"


def test_result_auto_select_subtype():
    result = get_interaction_result("kiss", initiator_stats={"arousal": 10})
    assert "error" not in result
    assert result["type"] == "kiss"


def test_result_intensity_override():
    result = get_interaction_result("kiss", intensity_override=1)
    assert "error" not in result
    assert result["intimacy_level"] <= 2


def test_result_meets_requirements_true():
    result = get_interaction_result("cuddle", "embrace")
    assert result["meets_requirements"]
    assert result["missing_requirements"] == {}


def test_result_meets_requirements_false():
    # "deep" kiss requires arousal >= 25
    result = get_interaction_result(
        "kiss", "deep", initiator_stats={"arousal": 0}
    )
    assert not result["meets_requirements"]
    assert "arousal" in result["missing_requirements"]


def test_result_has_narrative_opening():
    result = get_interaction_result("caress", "hair")
    assert isinstance(result["narrative_opening"], str)
    assert len(result["narrative_opening"]) > 0


def test_result_has_duration():
    result = get_interaction_result("cuddle", "spoon")
    assert result["duration_secs"] == 30


def test_result_phone_scene():
    result = get_interaction_result("flirt_text", scene="phone")
    assert result["type"] == "flirt_text"
    assert "error" not in result


def test_result_phases_progression():
    """Phases represent a narrative progression sequence."""
    result = get_interaction_result("cuddle", "spoon")
    phases = result["phases"]
    assert len(phases) == 3
    assert phases[0] == "settling in"
    assert phases[-1] == "warmth building"


# ═══════════════════════════════════════════════════════════════════════
#  list_interaction_types
# ═══════════════════════════════════════════════════════════════════════

def test_list_bedroom_types():
    types = list_interaction_types("penthouse")
    assert "cuddle" in types
    assert "kiss" in types
    cuddle_info = types["cuddle"]
    assert "label" in cuddle_info
    assert "subtypes" in cuddle_info
    assert len(cuddle_info["subtypes"]) > 0


def test_list_phone_types():
    types = list_interaction_types("phone")
    assert "flirt_text" in types


def test_list_subtype_entries_have_expected_keys():
    types = list_interaction_types("penthouse")
    for sub in types["cuddle"]["subtypes"]:
        assert "id" in sub
        assert "label" in sub
        assert "intimacy" in sub
        assert "duration" in sub


# ═══════════════════════════════════════════════════════════════════════
#  get_available_interactions
# ═══════════════════════════════════════════════════════════════════════

def test_available_low_stats_limits_options():
    avail = get_available_interactions({"arousal": 0, "openness": 0})
    # Should still include low-requirement types (cuddle/embrace requires nothing)
    type_ids = [a["type"] for a in avail]
    assert "cuddle" in type_ids


def test_available_high_stats_unlocks_more():
    low_avail = get_available_interactions({"arousal": 0, "openness": 0})
    high_avail = get_available_interactions({"arousal": 80, "openness": 80,
                                              "horniness": 60})
    # High stats should unlock at least as many subtypes
    low_subtypes = sum(len(a["accessible_subtypes"]) for a in low_avail)
    high_subtypes = sum(len(a["accessible_subtypes"]) for a in high_avail)
    assert high_subtypes >= low_subtypes


def test_available_phone_scene():
    avail = get_available_interactions({"arousal": 50}, scene="phone")
    type_ids = [a["type"] for a in avail]
    assert "flirt_text" in type_ids


def test_available_accessible_subtypes_structure():
    avail = get_available_interactions({"arousal": 0})
    for entry in avail:
        assert "type" in entry
        assert "label" in entry
        assert "accessible_subtypes" in entry
        for sub in entry["accessible_subtypes"]:
            assert "id" in sub
            assert "label" in sub
            assert "intimacy" in sub


# ═══════════════════════════════════════════════════════════════════════
#  EDGE CASES
# ═══════════════════════════════════════════════════════════════════════

def test_edge_case_empty_stats():
    result = get_interaction_result("cuddle", initiator_stats={})
    assert "error" not in result


def test_edge_case_none_stats():
    result = get_interaction_result("cuddle", initiator_stats=None)
    assert "error" not in result


def test_edge_case_fragments_capped_at_three():
    result = get_interaction_result("cuddle", "embrace")
    assert len(result["fragments"]) <= 3


def test_edge_case_stat_effects_are_numeric():
    result = get_interaction_result("kiss", "soft")
    for k, v in result["stat_effects"].items():
        assert isinstance(v, (int, float)), f"{k} has non-numeric effect"
