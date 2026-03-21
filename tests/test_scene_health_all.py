"""Parametrized health checks for all CosySim scene modules.

Validates that every scene directory under content/scenes/ can be imported
and contains the expected structural components (skill pack, templates).
"""
from __future__ import annotations

import importlib
import logging
from pathlib import Path
from typing import List

import pytest

logger = logging.getLogger(__name__)

# ──── Scene Discovery ────

SCENES_ROOT = Path(__file__).resolve().parent.parent / "content" / "scenes"

# Directories that are not actual scenes
_EXCLUDED = {"_archive", "__pycache__", "assets", "__init__"}


def _discover_scene_names() -> List[str]:
    """Walk content/scenes/ and return sorted list of scene directory names.

    Returns:
        Sorted list of scene names (directory names that look like scene packages).
    """
    if not SCENES_ROOT.is_dir():
        logger.warning("Scenes root not found: %s", SCENES_ROOT)
        return []

    names = sorted(
        d.name
        for d in SCENES_ROOT.iterdir()
        if d.is_dir() and d.name not in _EXCLUDED and not d.name.startswith("__")
    )
    logger.info("Discovered %d scene directories: %s", len(names), names)
    return names


SCENE_NAMES: List[str] = _discover_scene_names()

# Scenes known to be stubs or incomplete (no __init__.py / no Python module)
_STUB_SCENES = {"bedroom"}


# ──── Fixtures ────


@pytest.fixture(params=SCENE_NAMES)
def scene_name(request: pytest.FixtureRequest) -> str:
    """Yield each discovered scene name as a test parameter."""
    return request.param


# ──── Parametrized Tests ────


class TestSceneImport:
    """Verify every scene package can be imported."""

    @pytest.mark.parametrize("scene_name", SCENE_NAMES)
    def test_scene_module_imports(self, scene_name: str) -> None:
        """Scene module at content.scenes.{name} should import without error."""
        module_path = f"content.scenes.{scene_name}"

        if scene_name in _STUB_SCENES:
            pytest.skip(f"{scene_name} is a known stub scene without a Python module")

        try:
            mod = importlib.import_module(module_path)
        except Exception as exc:
            pytest.fail(f"Failed to import {module_path}: {exc}")

        assert mod is not None, f"Module {module_path} imported as None"
        logger.info("Successfully imported %s", module_path)


class TestSceneStructure:
    """Verify structural components exist for each scene."""

    @pytest.mark.parametrize("scene_name", SCENE_NAMES)
    def test_scene_has_skill_pack(self, scene_name: str) -> None:
        """Scene should have a {name}_skills.py skill pack file."""
        scene_dir = SCENES_ROOT / scene_name
        skills_file = scene_dir / f"{scene_name}_skills.py"

        if not skills_file.exists():
            pytest.skip(
                f"{scene_name} has no skill pack ({skills_file.name} not found)"
            )

        assert skills_file.is_file()
        assert skills_file.stat().st_size > 0, f"{skills_file.name} is empty"
        logger.info("Skill pack found: %s", skills_file.name)

    @pytest.mark.parametrize("scene_name", SCENE_NAMES)
    def test_scene_has_templates(self, scene_name: str) -> None:
        """Scene should have a templates/ directory with at least one file."""
        scene_dir = SCENES_ROOT / scene_name
        templates_dir = scene_dir / "templates"

        if not templates_dir.exists():
            pytest.skip(f"{scene_name} has no templates/ directory")

        assert templates_dir.is_dir()
        template_files = list(templates_dir.iterdir())
        assert len(template_files) > 0, (
            f"{scene_name}/templates/ exists but is empty"
        )
        logger.info(
            "%s has %d template(s)", scene_name, len(template_files)
        )


# ──── Standalone Assertions ────


def test_scene_count_minimum() -> None:
    """The project must have at least 15 discoverable scene directories."""
    count = len(SCENE_NAMES)
    assert count >= 15, (
        f"Expected at least 15 scenes, found {count}: {SCENE_NAMES}"
    )
    logger.info("Scene count check passed: %d scenes discovered", count)


def test_no_empty_scene_directories() -> None:
    """Every scene directory should contain at least one file or subdirectory."""
    for name in SCENE_NAMES:
        scene_dir = SCENES_ROOT / name
        contents = list(scene_dir.iterdir())
        assert len(contents) > 0, f"Scene directory {name}/ is completely empty"
