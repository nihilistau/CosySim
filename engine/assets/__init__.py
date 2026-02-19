"""
Engine Assets Module

Unified asset management system for all content types.

Example Usage:
    from engine.assets import AssetManager, AudioAsset, ImageAsset
    
    # Create manager
    manager = AssetManager()
    
    # Create and save audio asset
    audio = AudioAsset.create(
        filepath="voice.wav",
        duration=5.0,
        tags=["character1", "happy"]
    )
    manager.save(audio)
    
    # Load asset
    loaded = manager.load("audio", audio.id)
    
    # Search assets
    results = manager.search(asset_type="audio", tags=["character1"])
    
    # Get statistics
    stats = manager.get_stats()
    print(f"Total assets: {stats['total_assets']}")
"""

from .base import (
    BaseAsset,
    AssetMetadata,
    AssetDependency,
    AssetValidationError,
    AssetNotFoundError,
    register_asset_type,
    get_asset_class,
    ASSET_REGISTRY
)

from .manager import AssetManager

from .types import (
    AudioAsset,
    ImageAsset,
    VideoAsset
)

from .advanced_types import (
    CharacterAsset,
    PersonalityAsset,
    RoleAsset,
    SceneAsset,
    MessageAsset
)

__all__ = [
    # Base classes
    "BaseAsset",
    "AssetMetadata",
    "AssetDependency",
    
    # Exceptions
    "AssetValidationError",
    "AssetNotFoundError",
    
    # Registry
    "register_asset_type",
    "get_asset_class",
    "ASSET_REGISTRY",
    
    # Manager
    "AssetManager",
    
    # Asset types
    "AudioAsset",
    "ImageAsset",
    "VideoAsset",
    
    # Advanced types
    "CharacterAsset",
    "PersonalityAsset",
    "RoleAsset",
    "SceneAsset",
    "MessageAsset",
]
