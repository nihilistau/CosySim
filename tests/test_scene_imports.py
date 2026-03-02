"""Scene import health tests.

Verifies that all 18 CosySim scene modules can be imported without errors.
Run after any engine change to catch broken wiring early.
"""
from __future__ import annotations

import importlib

import pytest

SCENES = [
    "content.scenes.bedroom",
    "content.scenes.tavern",
    "content.scenes.games",
    "content.scenes.realm",
    "content.scenes.neoncity",
    "content.scenes.intel_hub",
    "content.scenes.phone",
    "content.scenes.command_center",
    "content.scenes.gallery",
    "content.scenes.hub",
    "content.scenes.lounge",
    "content.scenes.coders",
    "content.scenes.heist",
    "content.scenes.casino",
    "content.scenes.nexus_panel",
    "content.scenes.admin",
    "content.scenes.system_control",
]


@pytest.mark.parametrize("module_path", SCENES)
def test_scene_imports_cleanly(module_path: str) -> None:
    """Each scene module must be importable without raising any exception."""
    mod = importlib.import_module(module_path)
    assert mod is not None


def test_all_scenes_count() -> None:
    """Exactly 17 scenes are registered — update when a scene is added/removed."""
    assert len(SCENES) == 17
