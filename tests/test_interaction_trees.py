"""
tests/test_interaction_trees.py
================================

Unit tests for engine.mcp.interaction_trees:
  - InteractionSubtype / InteractionType data classes
  - BEDROOM_INTERACTIONS / PHONE_INTERACTIONS registries
  - get_interaction_result() resolver
  - list_interaction_types()
  - get_available_interactions()
  - Phase progression and requirement checking

All tests are offline — no LLM, no DB, no network required.
"""
from __future__ import annotations

import unittest

from engine.mcp.interaction_trees import (
    BEDROOM_INTERACTIONS,
    PHONE_INTERACTIONS,
    InteractionSubtype,
    InteractionType,
    get_available_interactions,
    get_interaction_result,
    list_interaction_types,
)


# ═══════════════════════════════════════════════════════════════════════
#  DATA-CLASS TESTS
# ═══════════════════════════════════════════════════════════════════════

class TestInteractionSubtype(unittest.TestCase):
    def test_fields(self):
        sub = InteractionSubtype(
            id="test", label="Test", description="A test subtype",
            duration=10.0, intimacy=2,
            stat_effects={"happiness": 10},
            phases=["start", "middle", "end"],
            fragments=["fragment one"],
        )
        self.assertEqual(sub.id, "test")
        self.assertEqual(sub.intimacy, 2)
        self.assertEqual(sub.phases, ["start", "middle", "end"])
        self.assertEqual(sub.requires, {})  # default empty

    def test_requires_default_factory(self):
        s1 = InteractionSubtype(id="a", label="A", description="", duration=5,
                                intimacy=1, stat_effects={}, phases=[], fragments=[])
        s2 = InteractionSubtype(id="b", label="B", description="", duration=5,
                                intimacy=1, stat_effects={}, phases=[], fragments=[])
        self.assertIsNot(s1.requires, s2.requires)


class TestInteractionType(unittest.TestCase):
    def _make_type(self):
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

    def test_get_subtype(self):
        it = self._make_type()
        self.assertEqual(it.get_subtype("mid").label, "Mid")
        self.assertIsNone(it.get_subtype("nonexistent"))

    def test_random_subtype_filters_by_intimacy(self):
        it = self._make_type()
        for _ in range(20):
            sub = it.random_subtype(min_intimacy=1, max_intimacy=1)
            self.assertEqual(sub.id, "low")

    def test_random_subtype_fallback(self):
        """If no subtypes match the range, returns first subtype."""
        it = self._make_type()
        sub = it.random_subtype(min_intimacy=99, max_intimacy=99)
        self.assertEqual(sub.id, "low")

    def test_subtype_ids(self):
        it = self._make_type()
        self.assertEqual(it.subtype_ids(), ["low", "mid", "high"])


# ═══════════════════════════════════════════════════════════════════════
#  BUILT-IN INTERACTION REGISTRIES
# ═══════════════════════════════════════════════════════════════════════

class TestBedroomInteractions(unittest.TestCase):
    def test_expected_types_exist(self):
        expected = {"cuddle", "kiss", "caress", "striptease"}
        self.assertTrue(expected.issubset(set(BEDROOM_INTERACTIONS.keys())))

    def test_each_type_has_subtypes(self):
        for iid, it in BEDROOM_INTERACTIONS.items():
            self.assertGreater(len(it.subtypes), 0, f"{iid} has no subtypes")

    def test_subtypes_have_phases(self):
        for iid, it in BEDROOM_INTERACTIONS.items():
            for sub in it.subtypes:
                self.assertGreater(len(sub.phases), 0,
                                   f"{iid}/{sub.id} has no phases")

    def test_subtypes_have_fragments(self):
        for iid, it in BEDROOM_INTERACTIONS.items():
            for sub in it.subtypes:
                self.assertGreater(len(sub.fragments), 0,
                                   f"{iid}/{sub.id} has no fragments")


class TestPhoneInteractions(unittest.TestCase):
    def test_expected_types_exist(self):
        expected = {"flirt_text", "voice_call", "video_call", "send_media"}
        self.assertTrue(expected.issubset(set(PHONE_INTERACTIONS.keys())))

    def test_each_type_has_subtypes(self):
        for iid, it in PHONE_INTERACTIONS.items():
            self.assertGreater(len(it.subtypes), 0, f"{iid} has no subtypes")


# ═══════════════════════════════════════════════════════════════════════
#  get_interaction_result
# ═══════════════════════════════════════════════════════════════════════

class TestGetInteractionResult(unittest.TestCase):
    def test_known_type_returns_result(self):
        result = get_interaction_result("cuddle", "embrace")
        self.assertEqual(result["type"], "cuddle")
        self.assertEqual(result["subtype"], "embrace")
        self.assertIn("phases", result)
        self.assertIn("stat_effects", result)
        self.assertIn("fragments", result)

    def test_unknown_type_returns_error(self):
        result = get_interaction_result("teleport")
        self.assertIn("error", result)

    def test_unknown_subtype_falls_back(self):
        result = get_interaction_result("cuddle", "nonexistent")
        # Should fall back to first subtype
        self.assertNotIn("error", result)
        self.assertEqual(result["type"], "cuddle")

    def test_auto_select_subtype(self):
        result = get_interaction_result("kiss", initiator_stats={"arousal": 10})
        self.assertNotIn("error", result)
        self.assertEqual(result["type"], "kiss")

    def test_intensity_override(self):
        result = get_interaction_result("kiss", intensity_override=1)
        self.assertNotIn("error", result)
        self.assertLessEqual(result["intimacy_level"], 2)

    def test_meets_requirements_true(self):
        result = get_interaction_result("cuddle", "embrace")
        self.assertTrue(result["meets_requirements"])
        self.assertEqual(result["missing_requirements"], {})

    def test_meets_requirements_false(self):
        # "deep" kiss requires arousal >= 25
        result = get_interaction_result(
            "kiss", "deep", initiator_stats={"arousal": 0}
        )
        self.assertFalse(result["meets_requirements"])
        self.assertIn("arousal", result["missing_requirements"])

    def test_result_has_narrative_opening(self):
        result = get_interaction_result("caress", "hair")
        self.assertIsInstance(result["narrative_opening"], str)
        self.assertGreater(len(result["narrative_opening"]), 0)

    def test_result_has_duration(self):
        result = get_interaction_result("cuddle", "spoon")
        self.assertEqual(result["duration_secs"], 30)

    def test_phone_scene(self):
        result = get_interaction_result("flirt_text", scene="phone")
        self.assertEqual(result["type"], "flirt_text")
        self.assertNotIn("error", result)

    def test_phases_progression(self):
        """Phases represent a narrative progression sequence."""
        result = get_interaction_result("cuddle", "spoon")
        phases = result["phases"]
        self.assertEqual(len(phases), 3)
        self.assertEqual(phases[0], "settling in")
        self.assertEqual(phases[-1], "warmth building")


# ═══════════════════════════════════════════════════════════════════════
#  list_interaction_types
# ═══════════════════════════════════════════════════════════════════════

class TestListInteractionTypes(unittest.TestCase):
    def test_bedroom_types(self):
        types = list_interaction_types("bedroom")
        self.assertIn("cuddle", types)
        self.assertIn("kiss", types)
        cuddle_info = types["cuddle"]
        self.assertIn("label", cuddle_info)
        self.assertIn("subtypes", cuddle_info)
        self.assertGreater(len(cuddle_info["subtypes"]), 0)

    def test_phone_types(self):
        types = list_interaction_types("phone")
        self.assertIn("flirt_text", types)

    def test_subtype_entries_have_expected_keys(self):
        types = list_interaction_types("bedroom")
        for sub in types["cuddle"]["subtypes"]:
            self.assertIn("id", sub)
            self.assertIn("label", sub)
            self.assertIn("intimacy", sub)
            self.assertIn("duration", sub)


# ═══════════════════════════════════════════════════════════════════════
#  get_available_interactions
# ═══════════════════════════════════════════════════════════════════════

class TestGetAvailableInteractions(unittest.TestCase):
    def test_low_stats_limits_options(self):
        avail = get_available_interactions({"arousal": 0, "openness": 0})
        # Should still include low-requirement types (cuddle/embrace requires nothing)
        type_ids = [a["type"] for a in avail]
        self.assertIn("cuddle", type_ids)

    def test_high_stats_unlocks_more(self):
        low_avail = get_available_interactions({"arousal": 0, "openness": 0})
        high_avail = get_available_interactions({"arousal": 80, "openness": 80,
                                                  "horniness": 60})
        # High stats should unlock at least as many subtypes
        low_subtypes = sum(len(a["accessible_subtypes"]) for a in low_avail)
        high_subtypes = sum(len(a["accessible_subtypes"]) for a in high_avail)
        self.assertGreaterEqual(high_subtypes, low_subtypes)

    def test_phone_scene(self):
        avail = get_available_interactions({"arousal": 50}, scene="phone")
        type_ids = [a["type"] for a in avail]
        self.assertIn("flirt_text", type_ids)

    def test_accessible_subtypes_structure(self):
        avail = get_available_interactions({"arousal": 0})
        for entry in avail:
            self.assertIn("type", entry)
            self.assertIn("label", entry)
            self.assertIn("accessible_subtypes", entry)
            for sub in entry["accessible_subtypes"]:
                self.assertIn("id", sub)
                self.assertIn("label", sub)
                self.assertIn("intimacy", sub)


# ═══════════════════════════════════════════════════════════════════════
#  EDGE CASES
# ═══════════════════════════════════════════════════════════════════════

class TestEdgeCases(unittest.TestCase):
    def test_empty_stats(self):
        result = get_interaction_result("cuddle", initiator_stats={})
        self.assertNotIn("error", result)

    def test_none_stats(self):
        result = get_interaction_result("cuddle", initiator_stats=None)
        self.assertNotIn("error", result)

    def test_fragments_capped_at_three(self):
        result = get_interaction_result("cuddle", "embrace")
        self.assertLessEqual(len(result["fragments"]), 3)

    def test_stat_effects_are_numeric(self):
        result = get_interaction_result("kiss", "soft")
        for k, v in result["stat_effects"].items():
            self.assertIsInstance(v, (int, float), f"{k} has non-numeric effect")


if __name__ == "__main__":
    unittest.main()
