"""Asset Studio engine — unified asset generation and library system.

Provides generators, presets, prompt building, and an SQLite-backed asset
catalogue for images, portraits, voice clips, video, game items, SVG, and
audio.

Quick start::

    from engine.asset_studio import get_studio_core
    core = get_studio_core()
    result = core.generate("image", {"prompt": "a dark tavern"})
"""

from engine.asset_studio.studio_core import AssetStudioCore, get_studio_core
from engine.asset_studio.workflow_builder import (
    build_video_wan_t2v,
    build_video_wan_i2v,
    WORKFLOW_REGISTRY,
)
from engine.asset_studio.workflow_manager import WorkflowManager, get_workflow_manager

__all__ = [
    "AssetStudioCore",
    "get_studio_core",
    "WorkflowManager",
    "get_workflow_manager",
    "build_video_wan_t2v",
    "build_video_wan_i2v",
    "WORKFLOW_REGISTRY",
]
