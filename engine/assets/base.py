"""
Base Asset System for CosyVoice

All content (audio, video, images, characters, messages, scenes) is managed as assets
with a unified interface for validation, versioning, import/export, and lifecycle management.

Core Concepts:
- BaseAsset: Universal interface for all asset types
- AssetManager: Unified CRUD operations for all assets
- AssetRegistry: Central catalog and indexing
- Versioning: Track changes and enable rollback
- Dependencies: Track relationships between assets

Example:
    from engine.assets import AudioAsset, AssetManager
    
    # Create audio asset
    audio = AudioAsset.create(
        filepath="voice.wav",
        metadata={"character_id": "char1", "emotion": "happy"}
    )
    
    # Save via manager
    manager = AssetManager()
    manager.save(audio)
    
    # Load later
    loaded = manager.load("audio", audio.id)
"""

import json
import uuid
import hashlib
from pathlib import Path
from datetime import datetime
from typing import Any, Dict, List, Optional, Type
from abc import ABC, abstractmethod
import logging

logger = logging.getLogger(__name__)


class AssetMetadata:
    """Asset metadata container."""
    
    def __init__(
        self,
        asset_id: str,
        asset_type: str,
        created_at: str,
        updated_at: str,
        version: int = 1,
        tags: Optional[List[str]] = None,
        custom: Optional[Dict[str, Any]] = None
    ):
        self.asset_id = asset_id
        self.asset_type = asset_type
        self.created_at = created_at
        self.updated_at = updated_at
        self.version = version
        self.tags = tags or []
        self.custom = custom or {}
    
    def to_dict(self) -> Dict[str, Any]:
        """Export metadata to dictionary."""
        return {
            "asset_id": self.asset_id,
            "asset_type": self.asset_type,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "version": self.version,
            "tags": self.tags,
            "custom": self.custom
        }
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'AssetMetadata':
        """Import metadata from dictionary."""
        return cls(
            asset_id=data["asset_id"],
            asset_type=data["asset_type"],
            created_at=data["created_at"],
            updated_at=data["updated_at"],
            version=data.get("version", 1),
            tags=data.get("tags", []),
            custom=data.get("custom", {})
        )


class BaseAsset(ABC):
    """
    Base class for all assets.
    
    All asset types must inherit from this class and implement:
    - validate(): Check if asset is valid
    - export(): Export asset to dictionary
    - import_data(): Create asset from dictionary
    """
    
    ASSET_TYPE: str = "base"  # Override in subclasses
    
    def __init__(
        self,
        asset_id: Optional[str] = None,
        metadata: Optional[AssetMetadata] = None
    ):
        """
        Initialize asset.
        
        Args:
            asset_id: Unique asset ID (generated if None)
            metadata: Asset metadata
        """
        self.id = asset_id or str(uuid.uuid4())
        
        if metadata is None:
            now = datetime.now().isoformat()
            metadata = AssetMetadata(
                asset_id=self.id,
                asset_type=self.ASSET_TYPE,
                created_at=now,
                updated_at=now
            )
        
        self.metadata = metadata
    
    @abstractmethod
    def validate(self) -> bool:
        """
        Validate asset integrity.
        
        Returns:
            True if valid, False otherwise
        
        Raises:
            ValueError: If validation fails with specific error
        """
        pass
    
    @abstractmethod
    def export(self) -> Dict[str, Any]:
        """
        Export asset to dictionary.
        
        Returns:
            Dictionary representation of asset
        """
        pass
    
    @classmethod
    @abstractmethod
    def import_data(cls, data: Dict[str, Any]) -> 'BaseAsset':
        """
        Import asset from dictionary.
        
        Args:
            data: Dictionary representation
        
        Returns:
            Asset instance
        """
        pass
    
    def get_checksum(self) -> str:
        """
        Calculate asset checksum for integrity verification.
        
        Returns:
            SHA256 checksum
        """
        data = json.dumps(self.export(), sort_keys=True)
        return hashlib.sha256(data.encode()).hexdigest()
    
    def add_tag(self, tag: str) -> None:
        """Add tag to asset."""
        if tag not in self.metadata.tags:
            self.metadata.tags.append(tag)
            self._touch()
    
    def remove_tag(self, tag: str) -> None:
        """Remove tag from asset."""
        if tag in self.metadata.tags:
            self.metadata.tags.remove(tag)
            self._touch()
    
    def has_tag(self, tag: str) -> bool:
        """Check if asset has tag."""
        return tag in self.metadata.tags
    
    def _touch(self) -> None:
        """Update the updated_at timestamp."""
        self.metadata.updated_at = datetime.now().isoformat()
    
    def __repr__(self) -> str:
        return f"<{self.__class__.__name__} id={self.id}>"


class AssetDependency:
    """Represents a dependency between assets."""
    
    def __init__(
        self,
        source_id: str,
        target_id: str,
        dependency_type: str = "requires"
    ):
        """
        Initialize dependency.
        
        Args:
            source_id: Source asset ID
            target_id: Target asset ID  
            dependency_type: Type of dependency (requires, references, includes)
        """
        self.source_id = source_id
        self.target_id = target_id
        self.dependency_type = dependency_type
    
    def to_dict(self) -> Dict[str, str]:
        """Export to dictionary."""
        return {
            "source_id": self.source_id,
            "target_id": self.target_id,
            "dependency_type": self.dependency_type
        }
    
    @classmethod
    def from_dict(cls, data: Dict[str, str]) -> 'AssetDependency':
        """Import from dictionary."""
        return cls(
            source_id=data["source_id"],
            target_id=data["target_id"],
            dependency_type=data.get("dependency_type", "requires")
        )


class AssetValidationError(Exception):
    """Raised when asset validation fails."""
    pass


class AssetNotFoundError(Exception):
    """Raised when asset is not found."""
    pass


# Asset type registry
ASSET_REGISTRY: Dict[str, Type[BaseAsset]] = {}


def register_asset_type(asset_type: str):
    """
    Decorator to register asset type.
    
    Usage:
        @register_asset_type("audio")
        class AudioAsset(BaseAsset):
            ASSET_TYPE = "audio"
            ...
    """
    def decorator(cls: Type[BaseAsset]):
        ASSET_REGISTRY[asset_type] = cls
        return cls
    return decorator


def get_asset_class(asset_type: str) -> Type[BaseAsset]:
    """
    Get asset class by type.
    
    Args:
        asset_type: Asset type name
    
    Returns:
        Asset class
    
    Raises:
        KeyError: If asset type not registered
    """
    if asset_type not in ASSET_REGISTRY:
        raise KeyError(f"Asset type not registered: {asset_type}")
    return ASSET_REGISTRY[asset_type]
