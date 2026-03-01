"""NeonCity — Living World Hub v0.68 "Dark Renaissance".

The city breathes.  Six factions fight for control.  The night never ends.
"""
from .neoncity_scene import NeonCityScene, SCENE_METADATA  # noqa: F401
from . import neoncity_skills as _neoncity_skills           # noqa: F401 — register @skill decorators

__all__ = ["NeonCityScene", "SCENE_METADATA"]
