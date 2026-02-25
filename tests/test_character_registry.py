"""
tests/test_character_registry.py
=================================

Unit tests for engine.mcp.character_registry:
  - CharacterProfile, CharacterState, SkillEntry, CharacterRecord data classes
  - CharacterRegistry: register, get_profile, list_characters, state, skills,
    restrictions, get_character_summary, load_from_dict, ensure
  - get_character_registry() singleton

All tests are offline — no LLM, no DB, no network required.
"""
from __future__ import annotations

import threading
import unittest
from unittest.mock import patch

from engine.mcp.character_registry import (
    CharacterProfile,
    CharacterRecord,
    CharacterRegistry,
    CharacterState,
    SkillEntry,
    get_character_registry,
)


# ── helpers ──────────────────────────────────────────────────────────────

def _fresh_registry() -> CharacterRegistry:
    """Return a brand-new, empty CharacterRegistry (not the singleton)."""
    return CharacterRegistry()


def _register_aria(reg: CharacterRegistry) -> CharacterRecord:
    """Register a sample character and return the record."""
    return reg.register(
        "aria",
        name="Aria",
        age=26,
        appearance={"hair": "brunette", "eyes": "green", "height": "5'7"},
        personality={"warmth": 0.9, "curiosity": 0.8, "assertiveness": 0.5},
        backstory="A creative writer who loves late-night conversations.",
        voice_style="warm, playful",
        scene_roles=["bedroom", "phone"],
    )


# ═══════════════════════════════════════════════════════════════════════
#  DATA-CLASS TESTS
# ═══════════════════════════════════════════════════════════════════════

class TestCharacterProfile(unittest.TestCase):
    def test_to_dict_roundtrip(self):
        p = CharacterProfile(character_id="x", name="X", age=30,
                             appearance={"hair": "red"}, personality={"wit": 0.7})
        d = p.to_dict()
        self.assertEqual(d["character_id"], "x")
        self.assertEqual(d["appearance"]["hair"], "red")

    def test_get_attribute_appearance(self):
        p = CharacterProfile(character_id="x", name="X", appearance={"eyes": "blue"})
        self.assertEqual(p.get_attribute("eyes"), "blue")

    def test_get_attribute_top_level(self):
        p = CharacterProfile(character_id="x", name="X", age=25)
        self.assertEqual(p.get_attribute("age"), 25)

    def test_get_attribute_default(self):
        p = CharacterProfile(character_id="x", name="X")
        self.assertIsNone(p.get_attribute("nonexistent"))
        self.assertEqual(p.get_attribute("nonexistent", "fallback"), "fallback")


class TestCharacterState(unittest.TestCase):
    def test_defaults(self):
        s = CharacterState()
        self.assertEqual(s.mood, "neutral")
        self.assertIsInstance(s.restrictions, set)

    def test_to_dict(self):
        s = CharacterState(mood="happy", restrictions={"no_violence", "keep_calm"})
        d = s.to_dict()
        self.assertEqual(d["mood"], "happy")
        self.assertEqual(d["restrictions"], ["keep_calm", "no_violence"])  # sorted


class TestSkillEntry(unittest.TestCase):
    def test_to_dict_uses_label_or_skill_id(self):
        s = SkillEntry(skill_id="web_lookup", skill_type="web_lookup")
        d = s.to_dict()
        # label defaults to empty string; to_dict falls back to skill_id
        self.assertEqual(d["label"], "web_lookup")

        s2 = SkillEntry(skill_id="mem", skill_type="memory_recall", label="Remember")
        self.assertEqual(s2.to_dict()["label"], "Remember")


class TestCharacterRecord(unittest.TestCase):
    def test_to_dict_composite(self):
        rec = CharacterRecord(
            profile=CharacterProfile(character_id="t", name="T"),
            skills={"s1": SkillEntry(skill_id="s1", skill_type="custom")},
        )
        d = rec.to_dict()
        self.assertIn("profile", d)
        self.assertIn("state", d)
        self.assertIn("s1", d["skills"])


# ═══════════════════════════════════════════════════════════════════════
#  REGISTRY — REGISTRATION
# ═══════════════════════════════════════════════════════════════════════

class TestRegistryRegister(unittest.TestCase):
    def setUp(self):
        self.reg = _fresh_registry()

    def test_register_adds_character(self):
        rec = _register_aria(self.reg)
        self.assertIsNotNone(rec)
        self.assertEqual(rec.profile.name, "Aria")

    def test_register_returns_record(self):
        rec = _register_aria(self.reg)
        self.assertIsInstance(rec, CharacterRecord)

    def test_duplicate_register_replaces_profile_keeps_state(self):
        rec1 = _register_aria(self.reg)
        self.reg.set_state("aria", mood="excited")
        rec2 = self.reg.register("aria", name="Aria V2", age=27)
        self.assertEqual(rec2.profile.name, "Aria V2")
        self.assertEqual(rec2.state.mood, "excited")  # preserved
        self.assertIs(rec1, rec2)  # same object

    def test_duplicate_register_preserves_skills(self):
        _register_aria(self.reg)
        self.reg.assign_skill("aria", "mem", skill_type="memory_recall")
        self.reg.register("aria", name="Aria V2")
        self.assertTrue(self.reg.has_skill("aria", "mem"))


# ═══════════════════════════════════════════════════════════════════════
#  REGISTRY — PROFILE QUERIES
# ═══════════════════════════════════════════════════════════════════════

class TestRegistryProfileQueries(unittest.TestCase):
    def setUp(self):
        self.reg = _fresh_registry()
        _register_aria(self.reg)

    def test_get_profile(self):
        p = self.reg.get_profile("aria")
        self.assertIsNotNone(p)
        self.assertEqual(p.name, "Aria")

    def test_get_profile_unknown_returns_none(self):
        self.assertIsNone(self.reg.get_profile("nobody"))

    def test_get_attribute_appearance_key(self):
        self.assertEqual(self.reg.get_attribute("aria", "eyes"), "green")

    def test_get_attribute_field(self):
        self.assertEqual(self.reg.get_attribute("aria", "age"), 26)

    def test_get_attribute_unknown_char(self):
        self.assertIsNone(self.reg.get_attribute("nobody", "eyes"))

    def test_list_characters_all(self):
        self.reg.register("lena", name="Lena")
        ids = self.reg.list_characters()
        self.assertIn("aria", ids)
        self.assertIn("lena", ids)

    def test_list_characters_by_scene_role(self):
        self.reg.register("lena", name="Lena", scene_roles=["phone"])
        bed = self.reg.list_characters(scene_role="bedroom")
        self.assertIn("aria", bed)
        self.assertNotIn("lena", bed)

    def test_personality_access(self):
        p = self.reg.get_profile("aria")
        self.assertAlmostEqual(p.personality["warmth"], 0.9)


# ═══════════════════════════════════════════════════════════════════════
#  REGISTRY — STATE MANAGEMENT
# ═══════════════════════════════════════════════════════════════════════

class TestRegistryState(unittest.TestCase):
    def setUp(self):
        self.reg = _fresh_registry()
        _register_aria(self.reg)

    def test_get_state_defaults(self):
        state = self.reg.get_state("aria")
        self.assertEqual(state["mood"], "neutral")
        self.assertEqual(state["energy"], 80.0)

    def test_set_state_known_fields(self):
        self.reg.set_state("aria", mood="excited", energy=60)
        state = self.reg.get_state("aria")
        self.assertEqual(state["mood"], "excited")
        self.assertEqual(state["energy"], 60)

    def test_set_state_unknown_field_goes_to_flags(self):
        self.reg.set_state("aria", custom_field="hello")
        state = self.reg.get_state("aria")
        self.assertEqual(state["flags"]["custom_field"], "hello")

    def test_get_state_unknown_char_auto_creates(self):
        state = self.reg.get_state("unknown_char")
        self.assertEqual(state["mood"], "neutral")
        self.assertIn("unknown_char", self.reg.list_characters())


# ═══════════════════════════════════════════════════════════════════════
#  REGISTRY — RESTRICTIONS
# ═══════════════════════════════════════════════════════════════════════

class TestRegistryRestrictions(unittest.TestCase):
    def setUp(self):
        self.reg = _fresh_registry()
        _register_aria(self.reg)

    def test_add_restriction(self):
        self.reg.add_restriction("aria", "refuse_explicit")
        r = self.reg.get_restrictions("aria")
        self.assertIn("refuse_explicit", r)

    def test_remove_restriction(self):
        self.reg.add_restriction("aria", "refuse_explicit")
        self.reg.remove_restriction("aria", "refuse_explicit")
        r = self.reg.get_restrictions("aria")
        self.assertNotIn("refuse_explicit", r)

    def test_remove_nonexistent_restriction_is_safe(self):
        self.reg.remove_restriction("aria", "never_added")  # should not raise

    def test_restrictions_appear_in_state_dict(self):
        self.reg.add_restriction("aria", "no_violence")
        state = self.reg.get_state("aria")
        self.assertIn("no_violence", state["restrictions"])


# ═══════════════════════════════════════════════════════════════════════
#  REGISTRY — SKILLS
# ═══════════════════════════════════════════════════════════════════════

class TestRegistrySkills(unittest.TestCase):
    def setUp(self):
        self.reg = _fresh_registry()
        _register_aria(self.reg)

    def test_assign_and_get_skill(self):
        self.reg.assign_skill("aria", "mem", skill_type="memory_recall",
                              params={"top_k": 5})
        skill = self.reg.get_skill("aria", "mem")
        self.assertIsNotNone(skill)
        self.assertEqual(skill.params["top_k"], 5)

    def test_has_skill(self):
        self.reg.assign_skill("aria", "mem", skill_type="memory_recall")
        self.assertTrue(self.reg.has_skill("aria", "mem"))
        self.assertFalse(self.reg.has_skill("aria", "nonexistent"))

    def test_revoke_skill(self):
        self.reg.assign_skill("aria", "mem", skill_type="memory_recall")
        removed = self.reg.revoke_skill("aria", "mem")
        self.assertTrue(removed)
        self.assertFalse(self.reg.has_skill("aria", "mem"))

    def test_revoke_nonexistent_returns_false(self):
        self.assertFalse(self.reg.revoke_skill("aria", "nope"))

    def test_toggle_skill(self):
        self.reg.assign_skill("aria", "mem", skill_type="memory_recall")
        self.reg.toggle_skill("aria", "mem", enabled=False)
        skills = self.reg.get_skills("aria", enabled_only=True)
        self.assertFalse(any(s.skill_id == "mem" for s in skills))

        self.reg.toggle_skill("aria", "mem", enabled=True)
        skills = self.reg.get_skills("aria", enabled_only=True)
        self.assertTrue(any(s.skill_id == "mem" for s in skills))

    def test_get_skills_sorted_by_priority(self):
        self.reg.assign_skill("aria", "a", skill_type="custom", priority=50)
        self.reg.assign_skill("aria", "b", skill_type="custom", priority=10)
        skills = self.reg.get_skills("aria")
        self.assertEqual(skills[0].skill_id, "b")  # lower priority = first

    def test_get_skills_filter_by_trigger(self):
        self.reg.assign_skill("aria", "a", skill_type="custom", trigger="auto")
        self.reg.assign_skill("aria", "b", skill_type="custom", trigger="optional")
        auto = self.reg.get_skills("aria", trigger="auto")
        self.assertEqual(len(auto), 1)
        self.assertEqual(auto[0].skill_id, "a")


# ═══════════════════════════════════════════════════════════════════════
#  REGISTRY — FULL RECORD & SUMMARY
# ═══════════════════════════════════════════════════════════════════════

class TestRegistryRecordAndSummary(unittest.TestCase):
    def setUp(self):
        self.reg = _fresh_registry()
        _register_aria(self.reg)

    def test_get_record(self):
        rec = self.reg.get_record("aria")
        self.assertIsNotNone(rec)
        self.assertEqual(rec.profile.name, "Aria")

    def test_get_record_unknown_returns_none(self):
        self.assertIsNone(self.reg.get_record("ghost"))

    def test_get_character_summary(self):
        self.reg.set_state("aria", mood="excited")
        self.reg.assign_skill("aria", "mem", skill_type="memory_recall")
        summary = self.reg.get_character_summary("aria")
        self.assertEqual(summary["name"], "Aria")
        self.assertEqual(summary["mood"], "excited")
        self.assertIn("mem", summary["active_skills"])
        self.assertIn("warmth", summary["top_traits"])

    def test_ensure_creates_stub(self):
        rec = self.reg.ensure("new_char")
        self.assertIsNotNone(rec)
        self.assertEqual(rec.profile.name, "New Char")

    def test_ensure_returns_existing(self):
        _register_aria(self.reg)
        rec = self.reg.ensure("aria")
        self.assertEqual(rec.profile.name, "Aria")


# ═══════════════════════════════════════════════════════════════════════
#  REGISTRY — load_from_dict
# ═══════════════════════════════════════════════════════════════════════

class TestRegistryLoadFromDict(unittest.TestCase):
    def test_load_from_dict(self):
        reg = _fresh_registry()
        data = {
            "profile": {
                "name": "Lena",
                "age": 24,
                "appearance": {"hair": "blonde"},
                "personality": {"warmth": 0.7},
                "backstory": "A barista.",
            },
            "state": {
                "mood": "happy",
                "energy": 90,
            },
            "skills": {
                "web": {"skill_type": "web_lookup", "label": "Search web"},
            },
        }
        rec = reg.load_from_dict("lena", data)
        self.assertEqual(rec.profile.name, "Lena")
        self.assertEqual(rec.profile.appearance["hair"], "blonde")
        state = reg.get_state("lena")
        self.assertEqual(state["mood"], "happy")
        self.assertTrue(reg.has_skill("lena", "web"))


# ═══════════════════════════════════════════════════════════════════════
#  SINGLETON
# ═══════════════════════════════════════════════════════════════════════

class TestSingleton(unittest.TestCase):
    def test_get_character_registry_returns_same_instance(self):
        r1 = get_character_registry()
        r2 = get_character_registry()
        self.assertIs(r1, r2)

    def test_singleton_has_framework_character(self):
        reg = get_character_registry()
        self.assertIn("__framework__", reg.list_characters())

    def test_singleton_thread_safety(self):
        results = []

        def _get():
            results.append(id(get_character_registry()))

        threads = [threading.Thread(target=_get) for _ in range(8)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        self.assertEqual(len(set(results)), 1)


if __name__ == "__main__":
    unittest.main()
