"""
Animation Framework — Reusable animation system for CosySim scenes.

Provides:
- AnimationConfig: YAML-driven animation/pose/interaction config loader
- PoseLibrary: CRUD for pose presets with category management
- ModelCatalog: External model scanning, cataloging, and import
- InteractionManager: Interaction chain sequencing and paired animation support

Usage:
    from engine.animation import AnimationConfig, PoseLibrary, ModelCatalog

    config = AnimationConfig("config/penthouse")
    poses = PoseLibrary("data/penthouse/animations/poses.json")
    catalog = ModelCatalog("config/penthouse/models/catalog.yaml")
"""
from __future__ import annotations

from engine.animation.animation_config import AnimationConfig
from engine.animation.pose_library import PoseLibrary
from engine.animation.model_catalog import ModelCatalog

__all__ = ["AnimationConfig", "PoseLibrary", "ModelCatalog"]
