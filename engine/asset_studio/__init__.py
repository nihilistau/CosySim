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

__all__ = ["AssetStudioCore", "get_studio_core"]
