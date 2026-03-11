"""
Tests for the animation framework — AnimationConfig, PoseLibrary, ModelCatalog.

Covers YAML/JSON loading, dot-notation config access, state machine helpers,
interaction lookups, pose CRUD with builtin protection, model catalog scanning,
bone mapping, and statistics.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any, Dict

import pytest
import yaml

from engine.animation.animation_config import AnimationConfig
from engine.animation.pose_library import PoseLibrary
from engine.animation.model_catalog import ModelCatalog


# ═══════════════════════════════════════════════════════════════════════
#  Fixtures — reusable YAML/JSON data for every test class
# ═══════════════════════════════════════════════════════════════════════

def _write_yaml(path: Path, data: Dict[str, Any]) -> None:
    """Write a dictionary to a YAML file."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        yaml.dump(data, f, default_flow_style=False)


def _write_json(path: Path, data: Dict[str, Any]) -> None:
    """Write a dictionary to a JSON file."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)


ANIMATIONS_YAML = {
    "state_categories": {
        "idle": {
            "priority": 0,
            "states": ["idle", "idle_sit", "idle_stand"],
        },
        "emotive": {
            "priority": 1,
            "states": ["laugh", "cry", "wave"],
        },
        "intimate": {
            "priority": 2,
            "states": ["cuddle", "kiss", "hug"],
        },
    },
    "blend_overrides": {
        "default": 0.6,
        "idle -> laugh": 0.3,
        "any -> kiss": 0.8,
        "cuddle -> any": 0.5,
    },
    "expressions": {
        "happy": {"mouth_smile": 0.8, "eye_squint": 0.3},
        "sad": {"mouth_frown": 0.7, "brow_down": 0.5},
        "neutral": {"mouth_smile": 0.0, "eye_squint": 0.0},
    },
    "paired_animations": {
        "cuddle": {
            "role_a": "cuddle_big_spoon",
            "role_b": "cuddle_little_spoon",
            "sync_mode": "root_motion",
        },
    },
}

INTERACTIONS_YAML = {
    "locations": {
        "bed": {
            "default_state": "idle_sit",
            "interactions": {
                "sleep": {"state": "sleeping", "expression": "neutral"},
                "cuddle": {"state": "cuddle", "expression": "happy", "paired": True},
                "read": {"state": "sitting_read", "expression": "neutral"},
            },
        },
        "couch": {
            "default_state": "idle_sit",
            "interactions": {
                "watch_tv": {"state": "sitting_tv", "expression": "neutral"},
                "nap": {"state": "sleeping", "expression": "neutral"},
            },
        },
    },
    "universal": {
        "wave": {"state": "wave", "expression": "happy"},
        "dance": {"state": "dancing", "expression": "happy", "paired": True},
    },
    "chains": {
        "morning_routine": {
            "steps": [
                {"action": "wake_up", "duration": 2.0},
                {"action": "stretch", "duration": 3.0},
                {"action": "stand_up", "duration": 1.5},
            ],
        },
    },
}

CHARACTERS_YAML = {
    "characters": {
        "lola": {
            "height": 1.65,
            "body_type": "slim",
            "skin_tone": "warm_medium",
        },
        "viktor": {
            "height": 1.85,
            "body_type": "athletic",
            "skin_tone": "fair",
        },
    },
}

OUTFITS_YAML = {
    "outfits": {
        "casual": {
            "top": "t_shirt_white",
            "bottom": "jeans_blue",
        },
        "formal": {
            "top": "blouse_black",
            "bottom": "skirt_midi",
        },
    },
}

SCENE_YAML = {
    "name": "penthouse",
    "version": "1.0",
    "max_characters": 4,
}


@pytest.fixture
def config_dir(tmp_path: Path) -> Path:
    """Create a complete config directory with all YAML files."""
    cfg = tmp_path / "config"
    cfg.mkdir()
    _write_yaml(cfg / "animations.yaml", ANIMATIONS_YAML)
    _write_yaml(cfg / "interactions.yaml", INTERACTIONS_YAML)
    _write_yaml(cfg / "characters.yaml", CHARACTERS_YAML)
    _write_yaml(cfg / "outfits.yaml", OUTFITS_YAML)
    _write_yaml(cfg / "scene.yaml", SCENE_YAML)
    return cfg


@pytest.fixture
def anim_config(config_dir: Path) -> AnimationConfig:
    """AnimationConfig loaded from the temporary config directory."""
    return AnimationConfig(str(config_dir))


def _sample_joints() -> Dict[str, Dict[str, float]]:
    """Return minimal valid joint data for pose tests."""
    return {
        "head": {"x": 0.0, "y": 0.0, "z": 0.0},
        "torso": {"x": 0.0, "y": 0.0, "z": 10.0},
    }


@pytest.fixture
def pose_file(tmp_path: Path) -> Path:
    """Create a poses.json file with seeded test data."""
    data = {
        "idle_stand": {
            "name": "Idle Standing",
            "builtin": True,
            "category": "idle",
            "location": "any",
            "joints": _sample_joints(),
            "joint_count": 2,
        },
        "idle_sit": {
            "name": "Idle Sitting",
            "builtin": True,
            "category": "idle",
            "location": "couch",
            "joints": _sample_joints(),
            "joint_count": 2,
        },
        "custom_wave": {
            "name": "Custom Wave",
            "builtin": False,
            "category": "emotive",
            "location": "any",
            "joints": _sample_joints(),
            "joint_count": 2,
        },
    }
    path = tmp_path / "poses.json"
    _write_json(path, data)
    return path


@pytest.fixture
def pose_lib(pose_file: Path) -> PoseLibrary:
    """PoseLibrary loaded from the temporary poses.json file."""
    return PoseLibrary(str(pose_file))


CATALOG_YAML = {
    "catalog": {
        "girl_a": {
            "file": "girl_a.glb",
            "source_dir": "/models/characters",
            "size_mb": 45.2,
            "type": "character",
            "gender": "female",
            "description": "Main character model A",
            "tags": ["rigged", "female", "main_cast"],
            "has_skeleton": True,
            "has_animations": True,
            "poly_estimate": "50k",
            "thumbnail": None,
        },
        "chair_01": {
            "file": "chair_01.glb",
            "source_dir": "/models/props",
            "size_mb": 2.1,
            "type": "prop",
            "gender": "unknown",
            "description": "Office swivel chair",
            "tags": ["furniture", "seating"],
            "has_skeleton": False,
            "has_animations": False,
            "poly_estimate": "5k",
            "thumbnail": None,
        },
    },
    "bone_mapping": {
        "mixamorig:Hips": "hips",
        "mixamorig:Spine": "spine",
        "mixamorig:Head": "head",
    },
    "source_directories": [
        {"path": "/models/characters", "label": "Characters", "auto_scan": True},
    ],
    "import": {
        "default_scale": 1.0,
        "auto_center": True,
    },
}


@pytest.fixture
def catalog_file(tmp_path: Path) -> Path:
    """Create a model catalog YAML file."""
    path = tmp_path / "model_catalog.yaml"
    _write_yaml(path, CATALOG_YAML)
    return path


@pytest.fixture
def catalog(catalog_file: Path) -> ModelCatalog:
    """ModelCatalog loaded from the temporary catalog file."""
    return ModelCatalog(str(catalog_file))


# ═══════════════════════════════════════════════════════════════════════
#  AnimationConfig Tests
# ═══════════════════════════════════════════════════════════════════════

class TestAnimationConfigLoading:
    """YAML loading and initialization."""

    def test_loads_all_yaml_files(self, anim_config: AnimationConfig):
        """All five config sections should be present after loading."""
        data = anim_config.as_dict()
        assert "animations" in data
        assert "interactions" in data
        assert "characters" in data
        assert "outfits" in data
        assert "scene" in data

    def test_missing_config_dir_yields_empty(self, tmp_path: Path):
        """Loading from a non-existent directory produces empty configs."""
        cfg = AnimationConfig(str(tmp_path / "nope"))
        data = cfg.as_dict()
        for section in ("animations", "interactions", "characters", "outfits", "scene"):
            assert data[section] == {}

    def test_partial_directory_loads_available_files(self, tmp_path: Path):
        """If only some YAML files exist, the rest are empty."""
        cfg_dir = tmp_path / "partial"
        cfg_dir.mkdir()
        _write_yaml(cfg_dir / "scene.yaml", {"name": "test"})
        cfg = AnimationConfig(str(cfg_dir))
        assert cfg.get("scene.name") == "test"
        assert cfg.get("animations") == {}

    def test_reload_picks_up_changes(self, config_dir: Path, anim_config: AnimationConfig):
        """Reload reads updated YAML from disk."""
        assert anim_config.get("scene.name") == "penthouse"
        _write_yaml(config_dir / "scene.yaml", {"name": "studio"})
        anim_config.reload()
        assert anim_config.get("scene.name") == "studio"

    def test_corrupt_yaml_returns_empty(self, tmp_path: Path):
        """Malformed YAML doesn't crash — returns empty dict."""
        cfg_dir = tmp_path / "bad"
        cfg_dir.mkdir()
        (cfg_dir / "animations.yaml").write_text("{{bad yaml!!", encoding="utf-8")
        cfg = AnimationConfig(str(cfg_dir))
        assert cfg.get("animations") == {}


class TestAnimationConfigGet:
    """Dot-notation path accessor."""

    def test_single_level_key(self, anim_config: AnimationConfig):
        """Top-level section access."""
        scene = anim_config.get("scene")
        assert isinstance(scene, dict)
        assert scene["name"] == "penthouse"

    def test_multi_level_dotpath(self, anim_config: AnimationConfig):
        """Deep dot-path access returns nested values."""
        assert anim_config.get("scene.name") == "penthouse"
        assert anim_config.get("scene.max_characters") == 4

    def test_deep_nested_dotpath(self, anim_config: AnimationConfig):
        """Three-level dot-path access."""
        assert anim_config.get("animations.expressions.happy.mouth_smile") == 0.8

    def test_missing_path_returns_default(self, anim_config: AnimationConfig):
        """Missing paths return the default value."""
        assert anim_config.get("nonexistent.key") is None
        assert anim_config.get("nonexistent.key", "fallback") == "fallback"

    def test_partial_path_returns_dict(self, anim_config: AnimationConfig):
        """A partial path stops at the last valid node and returns its subtree."""
        cats = anim_config.get("animations.state_categories")
        assert isinstance(cats, dict)
        assert "idle" in cats
        assert "emotive" in cats


class TestAnimationConfigStateMachine:
    """State category, priority, and blend helpers."""

    def test_get_state_category_known(self, anim_config: AnimationConfig):
        """Known states return their category."""
        assert anim_config.get_state_category("idle") == "idle"
        assert anim_config.get_state_category("laugh") == "emotive"
        assert anim_config.get_state_category("cuddle") == "intimate"

    def test_get_state_category_unknown(self, anim_config: AnimationConfig):
        """Unknown states return None."""
        assert anim_config.get_state_category("moonwalk") is None

    def test_get_state_priority(self, anim_config: AnimationConfig):
        """Priority values match the YAML config."""
        assert anim_config.get_state_priority("idle") == 0
        assert anim_config.get_state_priority("laugh") == 1
        assert anim_config.get_state_priority("kiss") == 2

    def test_get_state_priority_unknown_returns_zero(self, anim_config: AnimationConfig):
        """Unknown states fall back to priority 0."""
        assert anim_config.get_state_priority("backflip") == 0

    def test_blend_duration_exact_match(self, anim_config: AnimationConfig):
        """Exact from→to override is returned."""
        assert anim_config.get_blend_duration("idle", "laugh") == 0.3

    def test_blend_duration_any_to_target(self, anim_config: AnimationConfig):
        """'any → target' override is used when no exact match exists."""
        assert anim_config.get_blend_duration("wave", "kiss") == 0.8

    def test_blend_duration_source_to_any(self, anim_config: AnimationConfig):
        """'source → any' override is used when no exact or any→target exists."""
        assert anim_config.get_blend_duration("cuddle", "idle") == 0.5

    def test_blend_duration_default_fallback(self, anim_config: AnimationConfig):
        """Falls back to the default blend duration."""
        assert anim_config.get_blend_duration("wave", "cry") == 0.6


class TestAnimationConfigInteractions:
    """Location interaction lookups and chains."""

    def test_get_location_interactions(self, anim_config: AnimationConfig):
        """Returns all interactions for a known location."""
        bed = anim_config.get_location_interactions("bed")
        assert "sleep" in bed
        assert "cuddle" in bed
        assert "read" in bed

    def test_get_location_interactions_unknown(self, anim_config: AnimationConfig):
        """Unknown location returns empty dict."""
        assert anim_config.get_location_interactions("moon_base") == {}

    def test_get_location_default_state(self, anim_config: AnimationConfig):
        """Returns the default state for a location."""
        assert anim_config.get_location_default_state("bed") == "idle_sit"
        assert anim_config.get_location_default_state("couch") == "idle_sit"

    def test_get_location_default_state_unknown(self, anim_config: AnimationConfig):
        """Unknown location defaults to 'idle'."""
        assert anim_config.get_location_default_state("void") == "idle"

    def test_get_interaction_state_known(self, anim_config: AnimationConfig):
        """Returns (state, expression) for a known location+action."""
        state, expr = anim_config.get_interaction_state("bed", "sleep")
        assert state == "sleeping"
        assert expr == "neutral"

    def test_get_interaction_state_happy_expression(self, anim_config: AnimationConfig):
        """Cuddle interaction returns happy expression."""
        state, expr = anim_config.get_interaction_state("bed", "cuddle")
        assert state == "cuddle"
        assert expr == "happy"

    def test_get_interaction_state_falls_through_to_universal(self, anim_config: AnimationConfig):
        """Actions not in a location fall through to universal interactions."""
        state, expr = anim_config.get_interaction_state("bed", "wave")
        assert state == "wave"
        assert expr == "happy"

    def test_get_interaction_state_unknown_action(self, anim_config: AnimationConfig):
        """Completely unknown action returns location default state + neutral."""
        state, expr = anim_config.get_interaction_state("bed", "juggle")
        assert state == "idle_sit"
        assert expr == "neutral"

    def test_is_paired_interaction_true(self, anim_config: AnimationConfig):
        """Paired interaction is correctly identified."""
        assert anim_config.is_paired_interaction("bed", "cuddle") is True

    def test_is_paired_interaction_false(self, anim_config: AnimationConfig):
        """Non-paired interaction returns False."""
        assert anim_config.is_paired_interaction("bed", "sleep") is False

    def test_is_paired_interaction_universal(self, anim_config: AnimationConfig):
        """Paired flag is checked in universal interactions too."""
        assert anim_config.is_paired_interaction("couch", "dance") is True

    def test_is_paired_interaction_unknown(self, anim_config: AnimationConfig):
        """Unknown actions return False."""
        assert anim_config.is_paired_interaction("bed", "teleport") is False

    def test_get_interaction_chain(self, anim_config: AnimationConfig):
        """Returns the ordered steps of a named chain."""
        steps = anim_config.get_interaction_chain("morning_routine")
        assert len(steps) == 3
        assert steps[0]["action"] == "wake_up"
        assert steps[1]["duration"] == 3.0
        assert steps[2]["action"] == "stand_up"

    def test_get_interaction_chain_unknown(self, anim_config: AnimationConfig):
        """Unknown chain name returns empty list."""
        assert anim_config.get_interaction_chain("teleport_sequence") == []


class TestAnimationConfigExpressions:
    """Expression morph value lookups."""

    def test_get_expression_known(self, anim_config: AnimationConfig):
        """Returns morph values for a known expression."""
        happy = anim_config.get_expression("happy")
        assert happy["mouth_smile"] == 0.8
        assert happy["eye_squint"] == 0.3

    def test_get_expression_unknown(self, anim_config: AnimationConfig):
        """Unknown expression returns empty dict."""
        assert anim_config.get_expression("disgusted") == {}

    def test_get_all_expressions(self, anim_config: AnimationConfig):
        """Returns all expression definitions."""
        exprs = anim_config.get_all_expressions()
        assert "happy" in exprs
        assert "sad" in exprs
        assert "neutral" in exprs


class TestAnimationConfigAsDict:
    """Full config export."""

    def test_as_dict_returns_all_sections(self, anim_config: AnimationConfig):
        """as_dict() includes every loaded section."""
        d = anim_config.as_dict()
        assert isinstance(d, dict)
        assert len(d) == 5
        assert d["scene"]["name"] == "penthouse"

    def test_as_dict_is_copy(self, anim_config: AnimationConfig):
        """Mutating as_dict() output does not affect internal cache."""
        d = anim_config.as_dict()
        d["scene"] = "HACKED"
        assert anim_config.get("scene.name") == "penthouse"


# ═══════════════════════════════════════════════════════════════════════
#  PoseLibrary Tests
# ═══════════════════════════════════════════════════════════════════════

class TestPoseLibraryLoading:
    """JSON loading and initialization."""

    def test_loads_from_json(self, pose_lib: PoseLibrary):
        """Library loads all poses from the JSON file."""
        assert pose_lib.count() == 3

    def test_missing_file_starts_empty(self, tmp_path: Path):
        """Library starts empty when JSON file doesn't exist."""
        lib = PoseLibrary(str(tmp_path / "nope.json"))
        assert lib.count() == 0

    def test_corrupt_json_starts_empty(self, tmp_path: Path):
        """Corrupt JSON doesn't crash — library starts empty."""
        bad = tmp_path / "bad.json"
        bad.write_text("{{{not json!!!", encoding="utf-8")
        lib = PoseLibrary(str(bad))
        assert lib.count() == 0

    def test_reload_picks_up_changes(self, pose_file: Path, pose_lib: PoseLibrary):
        """Reload reads updated JSON from disk."""
        assert pose_lib.count() == 3
        data = json.loads(pose_file.read_text(encoding="utf-8"))
        data["new_pose"] = {
            "name": "New",
            "builtin": False,
            "category": "custom",
            "location": "any",
            "joints": _sample_joints(),
            "joint_count": 2,
        }
        pose_file.write_text(json.dumps(data), encoding="utf-8")
        pose_lib.reload()
        assert pose_lib.count() == 4


class TestPoseLibraryQuery:
    """Read-only queries over the pose collection."""

    def test_count(self, pose_lib: PoseLibrary):
        """Count returns total number of poses."""
        assert pose_lib.count() == 3

    def test_get_existing(self, pose_lib: PoseLibrary):
        """Get returns a pose by ID."""
        pose = pose_lib.get("idle_stand")
        assert pose is not None
        assert pose["name"] == "Idle Standing"
        assert pose["builtin"] is True

    def test_get_missing(self, pose_lib: PoseLibrary):
        """Get returns None for unknown IDs."""
        assert pose_lib.get("nonexistent") is None

    def test_get_all_returns_copy(self, pose_lib: PoseLibrary):
        """get_all returns a dict copy — mutations don't affect internal state."""
        all_poses = pose_lib.get_all()
        assert len(all_poses) == 3
        all_poses.pop("idle_stand")
        assert pose_lib.count() == 3

    def test_list_categories(self, pose_lib: PoseLibrary):
        """Returns sorted unique categories."""
        cats = pose_lib.list_categories()
        assert cats == ["emotive", "idle"]

    def test_get_by_category(self, pose_lib: PoseLibrary):
        """Filters poses by category."""
        idle_poses = pose_lib.get_by_category("idle")
        assert len(idle_poses) == 2
        assert "idle_stand" in idle_poses
        assert "idle_sit" in idle_poses

    def test_get_by_category_empty(self, pose_lib: PoseLibrary):
        """Unknown category returns empty dict."""
        assert pose_lib.get_by_category("combat") == {}

    def test_get_builtin(self, pose_lib: PoseLibrary):
        """Returns only builtin poses."""
        builtin = pose_lib.get_builtin()
        assert len(builtin) == 2
        for pose in builtin.values():
            assert pose["builtin"] is True

    def test_get_custom(self, pose_lib: PoseLibrary):
        """Returns only custom (non-builtin) poses."""
        custom = pose_lib.get_custom()
        assert len(custom) == 1
        assert "custom_wave" in custom

    def test_search_by_name(self, pose_lib: PoseLibrary):
        """Search matches against pose name."""
        results = pose_lib.search("Standing")
        assert "idle_stand" in results

    def test_search_by_id(self, pose_lib: PoseLibrary):
        """Search matches against pose ID."""
        results = pose_lib.search("custom_wave")
        assert "custom_wave" in results

    def test_search_by_category(self, pose_lib: PoseLibrary):
        """Search matches against category."""
        results = pose_lib.search("emotive")
        assert "custom_wave" in results

    def test_search_case_insensitive(self, pose_lib: PoseLibrary):
        """Search is case-insensitive."""
        results = pose_lib.search("IDLE")
        assert len(results) >= 2

    def test_search_no_match(self, pose_lib: PoseLibrary):
        """Search returns empty dict when nothing matches."""
        assert pose_lib.search("zzz_nonexistent") == {}


class TestPoseLibraryMutation:
    """Add, update, and delete operations."""

    def test_add_creates_pose(self, pose_lib: PoseLibrary):
        """Add creates a new pose with all fields set."""
        joints = _sample_joints()
        ok = pose_lib.add("sit_cross", "Cross-legged Sit", joints, category="sitting")
        assert ok is True
        pose = pose_lib.get("sit_cross")
        assert pose["name"] == "Cross-legged Sit"
        assert pose["category"] == "sitting"
        assert pose["location"] == "any"
        assert pose["joint_count"] == len(joints)
        assert "created_at" in pose

    def test_add_rejects_duplicate_id(self, pose_lib: PoseLibrary):
        """Adding a pose with an existing ID fails."""
        ok = pose_lib.add("idle_stand", "Duplicate", _sample_joints())
        assert ok is False
        assert pose_lib.count() == 3  # unchanged

    def test_add_rejects_invalid_joints(self, pose_lib: PoseLibrary):
        """Invalid joint data (missing axis) is rejected."""
        bad_joints = {"head": {"x": 0.0, "y": 0.0}}  # missing z
        ok = pose_lib.add("broken", "Broken", bad_joints)
        assert ok is False

    def test_add_rejects_non_dict_joints(self, pose_lib: PoseLibrary):
        """Non-dict joint data is rejected."""
        ok = pose_lib.add("bad", "Bad", {"head": "not_a_dict"})
        assert ok is False

    def test_add_persists_to_disk(self, pose_file: Path, pose_lib: PoseLibrary):
        """Add with auto_save=True writes to disk."""
        pose_lib.add("saved_pose", "Saved", _sample_joints())
        raw = json.loads(pose_file.read_text(encoding="utf-8"))
        assert "saved_pose" in raw

    def test_update_modifies_name(self, pose_lib: PoseLibrary):
        """Update changes the name of an existing pose."""
        ok = pose_lib.update("custom_wave", name="Super Wave")
        assert ok is True
        assert pose_lib.get("custom_wave")["name"] == "Super Wave"

    def test_update_modifies_category(self, pose_lib: PoseLibrary):
        """Update changes the category of an existing pose."""
        ok = pose_lib.update("custom_wave", category="greeting")
        assert ok is True
        assert pose_lib.get("custom_wave")["category"] == "greeting"

    def test_update_modifies_joints(self, pose_lib: PoseLibrary):
        """Update replaces joint data and updates joint_count."""
        new_joints = {
            "head": {"x": 5.0, "y": 5.0, "z": 5.0},
            "torso": {"x": 1.0, "y": 1.0, "z": 1.0},
            "arm_l": {"x": 0.0, "y": 90.0, "z": 0.0},
        }
        ok = pose_lib.update("custom_wave", joints=new_joints)
        assert ok is True
        pose = pose_lib.get("custom_wave")
        assert pose["joint_count"] == 3
        assert pose["joints"]["arm_l"]["y"] == 90.0

    def test_update_nonexistent_fails(self, pose_lib: PoseLibrary):
        """Update returns False for unknown pose IDs."""
        ok = pose_lib.update("ghost", name="Phantom")
        assert ok is False

    def test_delete_custom_pose(self, pose_lib: PoseLibrary):
        """Custom poses can be deleted."""
        assert pose_lib.count() == 3
        ok = pose_lib.delete("custom_wave")
        assert ok is True
        assert pose_lib.count() == 2
        assert pose_lib.get("custom_wave") is None

    def test_delete_builtin_refused(self, pose_lib: PoseLibrary):
        """Built-in poses cannot be deleted."""
        ok = pose_lib.delete("idle_stand")
        assert ok is False
        assert pose_lib.get("idle_stand") is not None

    def test_delete_nonexistent_returns_false(self, pose_lib: PoseLibrary):
        """Deleting an unknown ID returns False."""
        assert pose_lib.delete("phantom") is False


class TestPoseLibraryBulk:
    """Import and export operations."""

    def test_import_adds_new_poses(self, pose_lib: PoseLibrary):
        """Import adds new poses from a dict."""
        import_data = {
            "imported_a": {"name": "Imported A", "category": "imported"},
            "imported_b": {"name": "Imported B", "category": "imported"},
        }
        count = pose_lib.import_poses(import_data)
        assert count == 2
        assert pose_lib.count() == 5

    def test_import_skips_existing_without_overwrite(self, pose_lib: PoseLibrary):
        """Import skips IDs that already exist when overwrite=False."""
        import_data = {
            "idle_stand": {"name": "Overwritten Stand", "category": "idle"},
        }
        count = pose_lib.import_poses(import_data, overwrite=False)
        assert count == 0
        assert pose_lib.get("idle_stand")["name"] == "Idle Standing"

    def test_import_overwrites_with_flag(self, pose_lib: PoseLibrary):
        """Import overwrites existing poses when overwrite=True."""
        import_data = {
            "custom_wave": {"name": "Replaced Wave", "category": "replaced"},
        }
        count = pose_lib.import_poses(import_data, overwrite=True)
        assert count == 1
        assert pose_lib.get("custom_wave")["name"] == "Replaced Wave"


class TestPoseLibraryStats:
    """Statistics computation."""

    def test_stats_counts(self, pose_lib: PoseLibrary):
        """Stats returns correct total, builtin, and custom counts."""
        s = pose_lib.stats()
        assert s["total"] == 3
        assert s["builtin"] == 2
        assert s["custom"] == 1

    def test_stats_categories(self, pose_lib: PoseLibrary):
        """Stats returns per-category counts."""
        s = pose_lib.stats()
        assert s["categories"]["idle"] == 2
        assert s["categories"]["emotive"] == 1

    def test_stats_after_mutation(self, pose_lib: PoseLibrary):
        """Stats reflect add/delete operations."""
        pose_lib.add("new_pose", "New", _sample_joints(), category="new_cat")
        s = pose_lib.stats()
        assert s["total"] == 4
        assert s["custom"] == 2
        assert "new_cat" in s["categories"]


# ═══════════════════════════════════════════════════════════════════════
#  ModelCatalog Tests
# ═══════════════════════════════════════════════════════════════════════

class TestModelCatalogLoading:
    """YAML loading and initialization."""

    def test_loads_from_yaml(self, catalog: ModelCatalog):
        """Catalog loads entries from YAML file."""
        assert catalog.count() == 2

    def test_missing_file_starts_empty(self, tmp_path: Path):
        """Catalog starts empty when YAML file doesn't exist."""
        cat = ModelCatalog(str(tmp_path / "nope.yaml"))
        assert cat.count() == 0

    def test_corrupt_yaml_starts_empty(self, tmp_path: Path):
        """Corrupt YAML doesn't crash — catalog starts empty."""
        bad = tmp_path / "bad.yaml"
        bad.write_text("{{bad yaml!!", encoding="utf-8")
        cat = ModelCatalog(str(bad))
        assert cat.count() == 0

    def test_reload_picks_up_changes(self, catalog_file: Path, catalog: ModelCatalog):
        """Reload reads updated YAML from disk."""
        assert catalog.count() == 2
        data = yaml.safe_load(catalog_file.read_text(encoding="utf-8"))
        data["catalog"]["new_model"] = {
            "file": "new.glb",
            "source_dir": "/tmp",
            "type": "prop",
            "tags": [],
        }
        _write_yaml(catalog_file, data)
        catalog.reload()
        assert catalog.count() == 3


class TestModelCatalogQuery:
    """Read-only queries."""

    def test_get_existing(self, catalog: ModelCatalog):
        """Get returns a model entry by ID."""
        entry = catalog.get("girl_a")
        assert entry is not None
        assert entry["type"] == "character"
        assert entry["size_mb"] == 45.2

    def test_get_missing(self, catalog: ModelCatalog):
        """Get returns None for unknown IDs."""
        assert catalog.get("nonexistent") is None

    def test_count(self, catalog: ModelCatalog):
        """Count returns total number of models."""
        assert catalog.count() == 2

    def test_get_all(self, catalog: ModelCatalog):
        """get_all returns all entries as a dict copy."""
        all_models = catalog.get_all()
        assert len(all_models) == 2
        assert "girl_a" in all_models
        assert "chair_01" in all_models

    def test_get_by_type(self, catalog: ModelCatalog):
        """Filters models by type."""
        chars = catalog.get_by_type("character")
        assert len(chars) == 1
        assert "girl_a" in chars

    def test_get_by_type_no_match(self, catalog: ModelCatalog):
        """Unknown type returns empty dict."""
        assert catalog.get_by_type("vehicle") == {}

    def test_get_by_tag(self, catalog: ModelCatalog):
        """Filters models by tag."""
        rigged = catalog.get_by_tag("rigged")
        assert len(rigged) == 1
        assert "girl_a" in rigged

    def test_get_by_tag_shared(self, catalog: ModelCatalog):
        """Tag that doesn't exist returns empty dict."""
        assert catalog.get_by_tag("animated") == {}

    def test_search_by_id(self, catalog: ModelCatalog):
        """Search matches against model ID."""
        results = catalog.search("girl")
        assert "girl_a" in results

    def test_search_by_description(self, catalog: ModelCatalog):
        """Search matches against description."""
        results = catalog.search("swivel")
        assert "chair_01" in results

    def test_search_by_tag(self, catalog: ModelCatalog):
        """Search matches against tags."""
        results = catalog.search("furniture")
        assert "chair_01" in results

    def test_search_case_insensitive(self, catalog: ModelCatalog):
        """Search is case-insensitive."""
        results = catalog.search("GIRL")
        assert "girl_a" in results

    def test_search_no_match(self, catalog: ModelCatalog):
        """Search returns empty dict when nothing matches."""
        assert catalog.search("zzz_nonexistent") == {}


class TestModelCatalogMutation:
    """Add, update, and remove operations."""

    def test_add_creates_entry(self, catalog: ModelCatalog, tmp_path: Path):
        """Add creates a new catalog entry."""
        ok = catalog.add(
            model_id="desk_01",
            file="desk_01.glb",
            source_dir=str(tmp_path),
            model_type="prop",
            description="Standing desk",
            tags=["furniture", "office"],
        )
        assert ok is True
        assert catalog.count() == 3
        entry = catalog.get("desk_01")
        assert entry["type"] == "prop"
        assert entry["description"] == "Standing desk"
        assert "furniture" in entry["tags"]

    def test_add_rejects_duplicate_id(self, catalog: ModelCatalog, tmp_path: Path):
        """Adding a model with an existing ID fails."""
        ok = catalog.add("girl_a", "dup.glb", str(tmp_path))
        assert ok is False
        assert catalog.count() == 2

    def test_add_computes_size_for_real_file(self, catalog: ModelCatalog, tmp_path: Path):
        """Add calculates file size when the file exists."""
        model_file = tmp_path / "real_model.glb"
        model_file.write_bytes(b"\x00" * 2048)  # 2KB
        ok = catalog.add("real_model", "real_model.glb", str(tmp_path))
        assert ok is True
        entry = catalog.get("real_model")
        assert entry["size_mb"] >= 0  # computed from file

    def test_update_modifies_metadata(self, catalog: ModelCatalog):
        """Update changes metadata fields."""
        ok = catalog.update("chair_01", description="Ergonomic chair", type="furniture")
        assert ok is True
        entry = catalog.get("chair_01")
        assert entry["description"] == "Ergonomic chair"
        assert entry["type"] == "furniture"

    def test_update_nonexistent_fails(self, catalog: ModelCatalog):
        """Update returns False for unknown model IDs."""
        ok = catalog.update("ghost", description="Phantom model")
        assert ok is False

    def test_remove_deletes_entry(self, catalog: ModelCatalog):
        """Remove deletes a catalog entry."""
        assert catalog.count() == 2
        ok = catalog.remove("chair_01")
        assert ok is True
        assert catalog.count() == 1
        assert catalog.get("chair_01") is None

    def test_remove_nonexistent_returns_false(self, catalog: ModelCatalog):
        """Removing an unknown ID returns False."""
        assert catalog.remove("phantom") is False

    def test_add_persists_to_disk(self, catalog_file: Path, catalog: ModelCatalog, tmp_path: Path):
        """Add writes changes to the YAML file."""
        catalog.add("persisted", "p.glb", str(tmp_path), description="Persisted model")
        raw = yaml.safe_load(catalog_file.read_text(encoding="utf-8"))
        assert "persisted" in raw["catalog"]


class TestModelCatalogScan:
    """Directory scanning for model files."""

    def test_scan_finds_glb_files(self, catalog: ModelCatalog, tmp_path: Path):
        """scan_directory discovers new .glb files."""
        scan_dir = tmp_path / "models"
        scan_dir.mkdir()
        (scan_dir / "hero.glb").write_bytes(b"\x00" * 1024)
        (scan_dir / "villain.glb").write_bytes(b"\x00" * 2048)

        count = catalog.scan_directory(str(scan_dir))
        assert count == 2
        assert catalog.get("hero") is not None
        assert catalog.get("villain") is not None

    def test_scan_ignores_non_model_files(self, catalog: ModelCatalog, tmp_path: Path):
        """scan_directory skips unsupported extensions."""
        scan_dir = tmp_path / "mixed"
        scan_dir.mkdir()
        (scan_dir / "texture.png").write_bytes(b"\x00")
        (scan_dir / "readme.txt").write_text("hi", encoding="utf-8")
        (scan_dir / "actual_model.glb").write_bytes(b"\x00" * 512)

        count = catalog.scan_directory(str(scan_dir))
        assert count == 1

    def test_scan_skips_already_cataloged(self, catalog: ModelCatalog, tmp_path: Path):
        """scan_directory skips files that are already in the catalog."""
        scan_dir = tmp_path / "rescan"
        scan_dir.mkdir()
        (scan_dir / "girl_a.glb").write_bytes(b"\x00" * 1024)  # same filename as existing

        count = catalog.scan_directory(str(scan_dir))
        assert count == 0  # already in catalog by filename

    def test_scan_nonexistent_directory(self, catalog: ModelCatalog):
        """Scanning a non-existent directory returns 0."""
        count = catalog.scan_directory("/nonexistent/path")
        assert count == 0

    def test_scan_handles_vrm_and_gltf(self, catalog: ModelCatalog, tmp_path: Path):
        """scan_directory finds .vrm and .gltf files too."""
        scan_dir = tmp_path / "multi"
        scan_dir.mkdir()
        (scan_dir / "avatar.vrm").write_bytes(b"\x00" * 512)
        (scan_dir / "scene.gltf").write_bytes(b"\x00" * 256)

        count = catalog.scan_directory(str(scan_dir))
        assert count == 2

    def test_scan_normalizes_model_id(self, catalog: ModelCatalog, tmp_path: Path):
        """Model IDs derived from filenames are normalized."""
        scan_dir = tmp_path / "names"
        scan_dir.mkdir()
        (scan_dir / "My Model (v2).glb").write_bytes(b"\x00" * 100)

        catalog.scan_directory(str(scan_dir))
        # Spaces→underscores, parens removed, lowercased
        entry = catalog.get("my_model_v2")
        assert entry is not None
        assert entry["file"] == "My Model (v2).glb"


class TestModelCatalogBoneMapping:
    """Skeleton bone name mapping."""

    def test_get_bone_mapping(self, catalog: ModelCatalog):
        """Returns the full bone mapping dict."""
        mapping = catalog.get_bone_mapping()
        assert mapping["mixamorig:Hips"] == "hips"
        assert mapping["mixamorig:Head"] == "head"

    def test_get_bone_mapping_is_copy(self, catalog: ModelCatalog):
        """Mutating the returned mapping doesn't affect internal state."""
        mapping = catalog.get_bone_mapping()
        mapping["mixamorig:Hips"] = "HACKED"
        assert catalog.get_bone_mapping()["mixamorig:Hips"] == "hips"

    def test_map_bone_name_known(self, catalog: ModelCatalog):
        """map_bone_name translates known external names."""
        assert catalog.map_bone_name("mixamorig:Spine") == "spine"

    def test_map_bone_name_unknown_passthrough(self, catalog: ModelCatalog):
        """Unknown bone names pass through unchanged."""
        assert catalog.map_bone_name("custom_bone") == "custom_bone"

    def test_bone_mapping_empty_catalog(self, tmp_path: Path):
        """Empty catalog returns empty bone mapping."""
        cat = ModelCatalog(str(tmp_path / "nope.yaml"))
        assert cat.get_bone_mapping() == {}


class TestModelCatalogStats:
    """Statistics computation."""

    def test_stats_counts(self, catalog: ModelCatalog):
        """Stats returns correct total and type breakdown."""
        s = catalog.stats()
        assert s["total"] == 2
        assert s["types"]["character"] == 1
        assert s["types"]["prop"] == 1

    def test_stats_total_size(self, catalog: ModelCatalog):
        """Stats computes total size in MB."""
        s = catalog.stats()
        assert s["total_size_mb"] == pytest.approx(47.3, abs=0.1)

    def test_stats_source_directories(self, catalog: ModelCatalog):
        """Stats counts source directories."""
        s = catalog.stats()
        assert s["source_directories"] == 1

    def test_stats_after_add(self, catalog: ModelCatalog, tmp_path: Path):
        """Stats reflect newly added models."""
        catalog.add("new_prop", "new.glb", str(tmp_path), model_type="prop")
        s = catalog.stats()
        assert s["total"] == 3
        assert s["types"]["prop"] == 2

    def test_stats_empty_catalog(self, tmp_path: Path):
        """Stats for empty catalog returns zeroes."""
        cat = ModelCatalog(str(tmp_path / "empty.yaml"))
        s = cat.stats()
        assert s["total"] == 0
        assert s["types"] == {}
        assert s["total_size_mb"] == 0.0
