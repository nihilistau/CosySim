"""
Concrete Asset Types

Implementations of specific asset types:
- AudioAsset: Voice messages, music, sound effects
- ImageAsset: Photos, avatars, backgrounds
- VideoAsset: Video messages, clips
"""

import os
import imghdr
from pathlib import Path
from typing import Any, Dict, Optional
import logging

from .base import BaseAsset, AssetMetadata, AssetValidationError, register_asset_type

logger = logging.getLogger(__name__)


@register_asset_type("audio")
class AudioAsset(BaseAsset):
    """Audio asset (voice messages, music, sound effects)."""
    
    ASSET_TYPE = "audio"
    ALLOWED_FORMATS = {".wav", ".mp3", ".ogg", ".flac", ".m4a"}
    
    def __init__(
        self,
        filepath: str,
        duration: Optional[float] = None,
        sample_rate: Optional[int] = None,
        channels: Optional[int] = None,
        format: Optional[str] = None,
        asset_id: Optional[str] = None,
        metadata: Optional[AssetMetadata] = None
    ):
        """
        Initialize audio asset.
        
        Args:
            filepath: Path to audio file
            duration: Duration in seconds
            sample_rate: Sample rate in Hz
            channels: Number of channels (1=mono, 2=stereo)
            format: Audio format (wav, mp3, etc.)
            asset_id: Asset ID
            metadata: Asset metadata
        """
        super().__init__(asset_id, metadata)
        
        self.filepath = filepath
        self.duration = duration
        self.sample_rate = sample_rate
        self.channels = channels
        self.format = format or Path(filepath).suffix.lstrip('.')
    
    def validate(self) -> bool:
        """Validate audio asset."""
        # Check file exists
        if not os.path.exists(self.filepath):
            raise AssetValidationError(f"Audio file not found: {self.filepath}")
        
        # Check format
        file_ext = Path(self.filepath).suffix.lower()
        if file_ext not in self.ALLOWED_FORMATS:
            raise AssetValidationError(
                f"Unsupported audio format: {file_ext}. "
                f"Allowed: {self.ALLOWED_FORMATS}"
            )
        
        # Check file is not empty
        if os.path.getsize(self.filepath) == 0:
            raise AssetValidationError(f"Audio file is empty: {self.filepath}")
        
        return True
    
    def export(self) -> Dict[str, Any]:
        """Export audio asset to dictionary."""
        return {
            "id": self.id,
            "type": self.ASSET_TYPE,
            "filepath": self.filepath,
            "duration": self.duration,
            "sample_rate": self.sample_rate,
            "channels": self.channels,
            "format": self.format,
            "metadata": self.metadata.to_dict()
        }
    
    @classmethod
    def import_data(cls, data: Dict[str, Any]) -> 'AudioAsset':
        """Import audio asset from dictionary."""
        metadata = AssetMetadata.from_dict(data["metadata"])
        return cls(
            filepath=data["filepath"],
            duration=data.get("duration"),
            sample_rate=data.get("sample_rate"),
            channels=data.get("channels"),
            format=data.get("format"),
            asset_id=data["id"],
            metadata=metadata
        )
    
    @classmethod
    def create(
        cls,
        filepath: str,
        duration: Optional[float] = None,
        sample_rate: int = 22050,
        channels: int = 1,
        tags: Optional[list] = None
    ) -> 'AudioAsset':
        """
        Create audio asset with defaults.
        
        Args:
            filepath: Path to audio file
            duration: Duration in seconds
            sample_rate: Sample rate in Hz
            channels: Number of channels
            tags: Tags to apply
        
        Returns:
            AudioAsset instance
        """
        asset = cls(filepath, duration, sample_rate, channels)
        if tags:
            asset.metadata.tags = tags
        return asset


@register_asset_type("image")
class ImageAsset(BaseAsset):
    """Image asset (photos, avatars, backgrounds)."""
    
    ASSET_TYPE = "image"
    ALLOWED_FORMATS = {".jpg", ".jpeg", ".png", ".gif", ".webp", ".bmp"}
    
    def __init__(
        self,
        filepath: str,
        width: Optional[int] = None,
        height: Optional[int] = None,
        format: Optional[str] = None,
        asset_id: Optional[str] = None,
        metadata: Optional[AssetMetadata] = None
    ):
        """
        Initialize image asset.
        
        Args:
            filepath: Path to image file
            width: Image width in pixels
            height: Image height in pixels
            format: Image format (jpg, png, etc.)
            asset_id: Asset ID
            metadata: Asset metadata
        """
        super().__init__(asset_id, metadata)
        
        self.filepath = filepath
        self.width = width
        self.height = height
        self.format = format or Path(filepath).suffix.lstrip('.')
    
    def validate(self) -> bool:
        """Validate image asset."""
        # Check file exists
        if not os.path.exists(self.filepath):
            raise AssetValidationError(f"Image file not found: {self.filepath}")
        
        # Check format via extension
        file_ext = Path(self.filepath).suffix.lower()
        if file_ext not in self.ALLOWED_FORMATS:
            raise AssetValidationError(
                f"Unsupported image format: {file_ext}. "
                f"Allowed: {self.ALLOWED_FORMATS}"
            )
        
        # Check file is not empty
        if os.path.getsize(self.filepath) == 0:
            raise AssetValidationError(f"Image file is empty: {self.filepath}")
        
        # Verify actual image format matches extension
        actual_format = imghdr.what(self.filepath)
        if actual_format is None:
            raise AssetValidationError(f"File is not a valid image: {self.filepath}")
        
        return True
    
    def export(self) -> Dict[str, Any]:
        """Export image asset to dictionary."""
        return {
            "id": self.id,
            "type": self.ASSET_TYPE,
            "filepath": self.filepath,
            "width": self.width,
            "height": self.height,
            "format": self.format,
            "metadata": self.metadata.to_dict()
        }
    
    @classmethod
    def import_data(cls, data: Dict[str, Any]) -> 'ImageAsset':
        """Import image asset from dictionary."""
        metadata = AssetMetadata.from_dict(data["metadata"])
        return cls(
            filepath=data["filepath"],
            width=data.get("width"),
            height=data.get("height"),
            format=data.get("format"),
            asset_id=data["id"],
            metadata=metadata
        )
    
    @classmethod
    def create(
        cls,
        filepath: str,
        width: Optional[int] = None,
        height: Optional[int] = None,
        tags: Optional[list] = None
    ) -> 'ImageAsset':
        """
        Create image asset with defaults.
        
        Args:
            filepath: Path to image file
            width: Image width
            height: Image height
            tags: Tags to apply
        
        Returns:
            ImageAsset instance
        """
        asset = cls(filepath, width, height)
        if tags:
            asset.metadata.tags = tags
        return asset


@register_asset_type("video")
class VideoAsset(BaseAsset):
    """Video asset (video messages, clips)."""
    
    ASSET_TYPE = "video"
    ALLOWED_FORMATS = {".mp4", ".avi", ".mov", ".mkv", ".webm"}
    
    def __init__(
        self,
        filepath: str,
        duration: Optional[float] = None,
        width: Optional[int] = None,
        height: Optional[int] = None,
        fps: Optional[float] = None,
        format: Optional[str] = None,
        has_audio: bool = True,
        asset_id: Optional[str] = None,
        metadata: Optional[AssetMetadata] = None
    ):
        """
        Initialize video asset.
        
        Args:
            filepath: Path to video file
            duration: Duration in seconds
            width: Video width in pixels
            height: Video height in pixels
            fps: Frames per second
            format: Video format (mp4, avi, etc.)
            has_audio: Whether video has audio track
            asset_id: Asset ID
            metadata: Asset metadata
        """
        super().__init__(asset_id, metadata)
        
        self.filepath = filepath
        self.duration = duration
        self.width = width
        self.height = height
        self.fps = fps
        self.format = format or Path(filepath).suffix.lstrip('.')
        self.has_audio = has_audio
    
    def validate(self) -> bool:
        """Validate video asset."""
        # Check file exists
        if not os.path.exists(self.filepath):
            raise AssetValidationError(f"Video file not found: {self.filepath}")
        
        # Check format
        file_ext = Path(self.filepath).suffix.lower()
        if file_ext not in self.ALLOWED_FORMATS:
            raise AssetValidationError(
                f"Unsupported video format: {file_ext}. "
                f"Allowed: {self.ALLOWED_FORMATS}"
            )
        
        # Check file is not empty
        if os.path.getsize(self.filepath) == 0:
            raise AssetValidationError(f"Video file is empty: {self.filepath}")
        
        return True
    
    def export(self) -> Dict[str, Any]:
        """Export video asset to dictionary."""
        return {
            "id": self.id,
            "type": self.ASSET_TYPE,
            "filepath": self.filepath,
            "duration": self.duration,
            "width": self.width,
            "height": self.height,
            "fps": self.fps,
            "format": self.format,
            "has_audio": self.has_audio,
            "metadata": self.metadata.to_dict()
        }
    
    @classmethod
    def import_data(cls, data: Dict[str, Any]) -> 'VideoAsset':
        """Import video asset from dictionary."""
        metadata = AssetMetadata.from_dict(data["metadata"])
        return cls(
            filepath=data["filepath"],
            duration=data.get("duration"),
            width=data.get("width"),
            height=data.get("height"),
            fps=data.get("fps"),
            format=data.get("format"),
            has_audio=data.get("has_audio", True),
            asset_id=data["id"],
            metadata=metadata
        )
    
    @classmethod
    def create(
        cls,
        filepath: str,
        duration: Optional[float] = None,
        width: int = 512,
        height: int = 512,
        fps: float = 15.0,
        has_audio: bool = True,
        tags: Optional[list] = None
    ) -> 'VideoAsset':
        """
        Create video asset with defaults.
        
        Args:
            filepath: Path to video file
            duration: Duration in seconds
            width: Video width
            height: Video height
            fps: Frames per second
            has_audio: Whether video has audio
            tags: Tags to apply
        
        Returns:
            VideoAsset instance
        """
        asset = cls(filepath, duration, width, height, fps, has_audio=has_audio)
        if tags:
            asset.metadata.tags = tags
        return asset
