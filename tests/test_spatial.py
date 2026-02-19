"""Tests for engine.spatial — Location and SceneMap."""
import pytest
from engine.spatial.location import Location
from engine.spatial.scene_map import SceneMap


# ═══════════════════════════════════════════════════════════════════════════
#  Location
# ═══════════════════════════════════════════════════════════════════════════
class TestLocation:
    def _make(self, **kw):
        defaults = dict(id="bed", name="Bed", description="A big bed",
                        interactions=["sleep", "cuddle"], capacity=2,
                        properties={"privacy": 0.9, "comfort": 1.0, "spiciness": 5})
        defaults.update(kw)
        return Location(**defaults)

    def test_id_auto_generated(self):
        loc = Location(name="X")
        assert loc.id  # non-empty UUID

    def test_occupancy_starts_empty(self):
        loc = self._make()
        assert loc.occupants == []

    def test_add_occupant(self):
        loc = self._make()
        assert loc.add_occupant("c1") is True
        assert "c1" in loc.occupants

    def test_capacity_enforced(self):
        loc = self._make(capacity=1)
        loc.add_occupant("c1")
        assert loc.add_occupant("c2") is False

    def test_is_full(self):
        loc = self._make(capacity=1)
        assert loc.is_full is False
        loc.add_occupant("c1")
        assert loc.is_full is True

    def test_remove_occupant(self):
        loc = self._make()
        loc.add_occupant("c1")
        loc.remove_occupant("c1")
        assert "c1" not in loc.occupants

    def test_remove_nonexistent_ok(self):
        loc = self._make()
        assert loc.remove_occupant("ghost") is True

    def test_has_occupant(self):
        loc = self._make()
        assert loc.has_occupant("c1") is False
        loc.add_occupant("c1")
        assert loc.has_occupant("c1") is True

    def test_property_shortcuts(self):
        loc = self._make()
        assert loc.privacy == 0.9
        assert loc.comfort == 1.0
        assert loc.spiciness == 5

    def test_property_defaults(self):
        loc = Location(id="x", name="X")
        assert loc.privacy == 0.5
        assert loc.comfort == 0.5
        assert loc.spiciness == 1

    def test_to_dict(self):
        loc = self._make()
        loc.add_occupant("c1")
        d = loc.to_dict()
        assert d["id"] == "bed"
        assert d["name"] == "Bed"
        assert "c1" in d["occupants"]

    def test_context_for_llm(self):
        loc = self._make()
        loc.add_occupant("c1")
        ctx = loc.context_for_llm({"c1": "Luna"})
        assert "Bed" in ctx
        assert "Luna" in ctx
        assert "sleep" in ctx

    def test_context_no_names(self):
        loc = self._make()
        ctx = loc.context_for_llm()
        assert "no one else" in ctx


# ═══════════════════════════════════════════════════════════════════════════
#  SceneMap
# ═══════════════════════════════════════════════════════════════════════════
class TestSceneMap:
    def _make_map(self):
        sm = SceneMap()
        sm.add_location(Location(id="bed", name="Bed", capacity=2))
        sm.add_location(Location(id="bar", name="Bar", capacity=2))
        sm.add_location(Location(id="vanity", name="Vanity", capacity=1))
        return sm

    def test_add_and_get_location(self):
        sm = self._make_map()
        assert sm.get_location("bed") is not None
        assert sm.get_location("missing") is None

    def test_get_location_by_name(self):
        sm = self._make_map()
        assert sm.get_location_by_name("Bed").id == "bed"
        assert sm.get_location_by_name("bed").id == "bed"  # case-insensitive
        assert sm.get_location_by_name("nope") is None

    def test_locations_list(self):
        sm = self._make_map()
        assert len(sm.locations) == 3

    def test_location_names(self):
        sm = self._make_map()
        assert set(sm.location_names) == {"Bed", "Bar", "Vanity"}

    def test_place_character(self):
        sm = self._make_map()
        assert sm.place_character("c1", "bed") is True
        assert sm.get_character_location("c1").id == "bed"

    def test_place_at_full_location_fails(self):
        sm = self._make_map()
        sm.place_character("c1", "vanity")
        assert sm.place_character("c2", "vanity") is False

    def test_place_at_nonexistent_location_fails(self):
        sm = self._make_map()
        assert sm.place_character("c1", "roof") is False

    def test_move_character(self):
        sm = self._make_map()
        sm.place_character("c1", "bed")
        assert sm.move_character("c1", "bar") is True
        assert sm.get_character_location("c1").id == "bar"
        assert "c1" not in sm.get_occupants("bed")

    def test_remove_character(self):
        sm = self._make_map()
        sm.place_character("c1", "bed")
        sm.remove_character("c1")
        assert sm.get_character_location("c1") is None
        assert "c1" not in sm.get_occupants("bed")

    def test_get_nearby_characters(self):
        sm = self._make_map()
        sm.place_character("c1", "bed")
        sm.place_character("c2", "bed")
        assert sm.get_nearby_characters("c1") == ["c2"]
        assert sm.get_nearby_characters("c2") == ["c1"]

    def test_nearby_empty_when_alone(self):
        sm = self._make_map()
        sm.place_character("c1", "bed")
        sm.place_character("c2", "bar")
        assert sm.get_nearby_characters("c1") == []

    def test_can_interact_same_location(self):
        sm = self._make_map()
        sm.place_character("c1", "bed")
        sm.place_character("c2", "bed")
        assert sm.can_interact("c1", "c2") is True

    def test_cannot_interact_different_locations(self):
        sm = self._make_map()
        sm.place_character("c1", "bed")
        sm.place_character("c2", "bar")
        assert sm.can_interact("c1", "c2") is False

    def test_cannot_interact_unplaced(self):
        sm = self._make_map()
        assert sm.can_interact("c1", "c2") is False

    def test_get_empty_locations(self):
        sm = self._make_map()
        sm.place_character("c1", "bed")
        empty = sm.get_empty_locations()
        ids = [l.id for l in empty]
        assert "bed" not in ids
        assert "bar" in ids

    def test_snapshot(self):
        sm = self._make_map()
        sm.place_character("c1", "bed")
        snap = sm.snapshot()
        assert "locations" in snap
        assert "character_locations" in snap
        assert snap["character_locations"]["c1"] == "bed"

    def test_context_for_character(self):
        sm = self._make_map()
        sm.place_character("c1", "bed")
        ctx = sm.context_for_character("c1", {"c1": "Luna"})
        assert "Bed" in ctx
        assert "Other places" in ctx

    def test_context_unplaced_character(self):
        sm = self._make_map()
        ctx = sm.context_for_character("c1")
        assert "nowhere" in ctx

    def test_remove_location_evicts(self):
        sm = self._make_map()
        sm.place_character("c1", "bar")
        sm.remove_location("bar")
        assert sm.get_character_location("c1") is None
        assert sm.get_location("bar") is None
