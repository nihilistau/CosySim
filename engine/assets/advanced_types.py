"""
Advanced Asset Types

Character, Scene, Personality, Role, and Message assets for the virtual companion system.
"""

import json
from pathlib import Path
from typing import Dict, Any, List, Optional
from datetime import datetime

from .base import BaseAsset, register_asset_type, AssetValidationError


@register_asset_type("character")
class CharacterAsset(BaseAsset):
    """Character asset with personality and role references."""
    
    ASSET_TYPE = "character"
    
    def __init__(self, **kwargs):
        super().__init__()
        self.name: str = kwargs.get("name", "")
        self.description: str = kwargs.get("description", "")
        self.personality_id: Optional[str] = kwargs.get("personality_id")
        self.role_id: Optional[str] = kwargs.get("role_id")
        self.avatar_id: Optional[str] = kwargs.get("avatar_id")  # Reference to ImageAsset
        self.voice_profile: Dict[str, Any] = kwargs.get("voice_profile", {})
        self.attributes: Dict[str, Any] = kwargs.get("attributes", {})
        self.relationships: Dict[str, float] = kwargs.get("relationships", {})  # user_id -> affinity
        
        # Physical attributes
        self.age: Optional[int] = kwargs.get("age")
        self.gender: Optional[str] = kwargs.get("gender")
        self.ethnicity: Optional[str] = kwargs.get("ethnicity")
        self.hair_color: Optional[str] = kwargs.get("hair_color")
        self.eye_color: Optional[str] = kwargs.get("eye_color")
        self.height: Optional[str] = kwargs.get("height")
        self.build: Optional[str] = kwargs.get("build")
        
        # Behavior settings
        self.messaging_frequency: str = kwargs.get("messaging_frequency", "medium")  # low/medium/high
        self.autonomy_level: float = kwargs.get("autonomy_level", 0.5)  # 0.0-1.0
        self.nsfw_enabled: bool = kwargs.get("nsfw_enabled", False)
    
    def validate(self) -> bool:
        """Validate character data."""
        if not self.name:
            raise AssetValidationError("Character must have a name")
        
        if self.autonomy_level < 0.0 or self.autonomy_level > 1.0:
            raise AssetValidationError("Autonomy level must be between 0.0 and 1.0")
        
        if self.messaging_frequency not in ["low", "medium", "high"]:
            raise AssetValidationError("Messaging frequency must be low, medium, or high")
        
        return True
    
    def export(self) -> Dict[str, Any]:
        """Export character to dict."""
        return {
            "type": "character",
            "id": self.id,
            "name": self.name,
            "description": self.description,
            "personality_id": self.personality_id,
            "role_id": self.role_id,
            "avatar_id": self.avatar_id,
            "voice_profile": self.voice_profile,
            "attributes": self.attributes,
            "relationships": self.relationships,
            "age": self.age,
            "gender": self.gender,
            "ethnicity": self.ethnicity,
            "hair_color": self.hair_color,
            "eye_color": self.eye_color,
            "height": self.height,
            "build": self.build,
            "messaging_frequency": self.messaging_frequency,
            "autonomy_level": self.autonomy_level,
            "nsfw_enabled": self.nsfw_enabled,
            "metadata": self.metadata.to_dict()
        }
    
    @classmethod
    def import_data(cls, data: Dict[str, Any]) -> "CharacterAsset":
        """Import character from dict."""
        char = cls(
            name=data["name"],
            description=data.get("description", ""),
            personality_id=data.get("personality_id"),
            role_id=data.get("role_id"),
            avatar_id=data.get("avatar_id"),
            voice_profile=data.get("voice_profile", {}),
            attributes=data.get("attributes", {}),
            relationships=data.get("relationships", {}),
            age=data.get("age"),
            gender=data.get("gender"),
            ethnicity=data.get("ethnicity"),
            hair_color=data.get("hair_color"),
            eye_color=data.get("eye_color"),
            height=data.get("height"),
            build=data.get("build"),
            messaging_frequency=data.get("messaging_frequency", "medium"),
            autonomy_level=data.get("autonomy_level", 0.5),
            nsfw_enabled=data.get("nsfw_enabled", False)
        )
        char.id = data["id"]
        char.metadata.from_dict(data.get("metadata", {}))
        return char
    
    @classmethod
    def create(cls, name: str, **kwargs) -> "CharacterAsset":
        """Factory method to create a character."""
        return cls(name=name, **kwargs)


@register_asset_type("personality")
class PersonalityAsset(BaseAsset):
    """Personality configuration asset."""
    
    ASSET_TYPE = "personality"
    
    def __init__(self, **kwargs):
        super().__init__()
        self.name: str = kwargs.get("name", "")
        self.description: str = kwargs.get("description", "")
        self.personality_type: str = kwargs.get("personality_type", "friendly")
        self.system_prompt: str = kwargs.get("system_prompt", "")
        self.traits: List[str] = kwargs.get("traits", [])
        self.speaking_style: Dict[str, Any] = kwargs.get("speaking_style", {})
        self.example_dialogues: List[Dict[str, str]] = kwargs.get("example_dialogues", [])
        
        # Personality parameters
        self.warmth: float = kwargs.get("warmth", 0.7)  # 0.0-1.0
        self.formality: float = kwargs.get("formality", 0.3)  # 0.0-1.0
        self.humor: float = kwargs.get("humor", 0.5)  # 0.0-1.0
        self.flirtiness: float = kwargs.get("flirtiness", 0.5)  # 0.0-1.0
        self.intelligence: float = kwargs.get("intelligence", 0.7)  # 0.0-1.0
        self.creativity: float = kwargs.get("creativity", 0.6)  # 0.0-1.0
    
    def validate(self) -> bool:
        """Validate personality data."""
        if not self.name:
            raise AssetValidationError("Personality must have a name")
        
        # Validate parameter ranges
        for param in ["warmth", "formality", "humor", "flirtiness", "intelligence", "creativity"]:
            value = getattr(self, param)
            if value < 0.0 or value > 1.0:
                raise AssetValidationError(f"{param} must be between 0.0 and 1.0")
        
        return True
    
    def export(self) -> Dict[str, Any]:
        """Export personality to dict."""
        return {
            "type": "personality",
            "id": self.id,
            "name": self.name,
            "description": self.description,
            "personality_type": self.personality_type,
            "system_prompt": self.system_prompt,
            "traits": self.traits,
            "speaking_style": self.speaking_style,
            "example_dialogues": self.example_dialogues,
            "warmth": self.warmth,
            "formality": self.formality,
            "humor": self.humor,
            "flirtiness": self.flirtiness,
            "intelligence": self.intelligence,
            "creativity": self.creativity,
            "metadata": self.metadata.to_dict()
        }
    
    @classmethod
    def import_data(cls, data: Dict[str, Any]) -> "PersonalityAsset":
        """Import personality from dict."""
        personality = cls(
            name=data["name"],
            description=data.get("description", ""),
            personality_type=data.get("personality_type", "friendly"),
            system_prompt=data.get("system_prompt", ""),
            traits=data.get("traits", []),
            speaking_style=data.get("speaking_style", {}),
            example_dialogues=data.get("example_dialogues", []),
            warmth=data.get("warmth", 0.7),
            formality=data.get("formality", 0.3),
            humor=data.get("humor", 0.5),
            flirtiness=data.get("flirtiness", 0.5),
            intelligence=data.get("intelligence", 0.7),
            creativity=data.get("creativity", 0.6)
        )
        personality.id = data["id"]
        personality.metadata.from_dict(data.get("metadata", {}))
        return personality
    
    @classmethod
    def create(cls, name: str, **kwargs) -> "PersonalityAsset":
        """Factory method to create a personality."""
        return cls(name=name, **kwargs)


@register_asset_type("role")
class RoleAsset(BaseAsset):
    """Role definition asset."""
    
    ASSET_TYPE = "role"
    
    def __init__(self, **kwargs):
        super().__init__()
        self.name: str = kwargs.get("name", "")
        self.description: str = kwargs.get("description", "")
        self.role_type: str = kwargs.get("role_type", "companion")  # companion/assistant/narrator/etc
        self.context: str = kwargs.get("context", "")
        self.goals: List[str] = kwargs.get("goals", [])
        self.constraints: List[str] = kwargs.get("constraints", [])
        self.permissions: Dict[str, bool] = kwargs.get("permissions", {})
        self.capabilities: List[str] = kwargs.get("capabilities", [])
    
    def validate(self) -> bool:
        """Validate role data."""
        if not self.name:
            raise AssetValidationError("Role must have a name")
        
        return True
    
    def export(self) -> Dict[str, Any]:
        """Export role to dict."""
        return {
            "type": "role",
            "id": self.id,
            "name": self.name,
            "description": self.description,
            "role_type": self.role_type,
            "context": self.context,
            "goals": self.goals,
            "constraints": self.constraints,
            "permissions": self.permissions,
            "capabilities": self.capabilities,
            "metadata": self.metadata.to_dict()
        }
    
    @classmethod
    def import_data(cls, data: Dict[str, Any]) -> "RoleAsset":
        """Import role from dict."""
        role = cls(
            name=data["name"],
            description=data.get("description", ""),
            role_type=data.get("role_type", "companion"),
            context=data.get("context", ""),
            goals=data.get("goals", []),
            constraints=data.get("constraints", []),
            permissions=data.get("permissions", {}),
            capabilities=data.get("capabilities", [])
        )
        role.id = data["id"]
        role.metadata.from_dict(data.get("metadata", {}))
        return role
    
    @classmethod
    def create(cls, name: str, **kwargs) -> "RoleAsset":
        """Factory method to create a role."""
        return cls(name=name, **kwargs)


@register_asset_type("scene")
class SceneAsset(BaseAsset):
    """Scene definition asset."""
    
    ASSET_TYPE = "scene"
    
    def __init__(self, **kwargs):
        super().__init__()
        self.name: str = kwargs.get("name", "")
        self.description: str = kwargs.get("description", "")
        self.scene_type: str = kwargs.get("scene_type", "phone")  # phone/dashboard/bedroom/custom
        self.config: Dict[str, Any] = kwargs.get("config", {})
        self.characters: List[str] = kwargs.get("characters", [])  # Character IDs
        self.assets: Dict[str, str] = kwargs.get("assets", {})  # asset_type -> asset_id
        self.server_config: Dict[str, Any] = kwargs.get("server_config", {})
        self.ui_config: Dict[str, Any] = kwargs.get("ui_config", {})
    
    def validate(self) -> bool:
        """Validate scene data."""
        if not self.name:
            raise AssetValidationError("Scene must have a name")
        
        return True
    
    def export(self) -> Dict[str, Any]:
        """Export scene to dict."""
        return {
            "type": "scene",
            "id": self.id,
            "name": self.name,
            "description": self.description,
            "scene_type": self.scene_type,
            "config": self.config,
            "characters": self.characters,
            "assets": self.assets,
            "server_config": self.server_config,
            "ui_config": self.ui_config,
            "metadata": self.metadata.to_dict()
        }
    
    @classmethod
    def import_data(cls, data: Dict[str, Any]) -> "SceneAsset":
        """Import scene from dict."""
        scene = cls(
            name=data["name"],
            description=data.get("description", ""),
            scene_type=data.get("scene_type", "phone"),
            config=data.get("config", {}),
            characters=data.get("characters", []),
            assets=data.get("assets", {}),
            server_config=data.get("server_config", {}),
            ui_config=data.get("ui_config", {})
        )
        scene.id = data["id"]
        scene.metadata.from_dict(data.get("metadata", {}))
        return scene
    
    @classmethod
    def create(cls, name: str, **kwargs) -> "SceneAsset":
        """Factory method to create a scene."""
        return cls(name=name, **kwargs)


@register_asset_type("message")
class MessageAsset(BaseAsset):
    """Message/conversation history asset."""
    
    ASSET_TYPE = "message"
    
    def __init__(self, **kwargs):
        super().__init__()
        self.conversation_id: str = kwargs.get("conversation_id", "")
        self.character_id: str = kwargs.get("character_id", "")
        self.sender: str = kwargs.get("sender", "")  # 'user' or 'character'
        self.content: str = kwargs.get("content", "")
        self.message_type: str = kwargs.get("message_type", "text")  # text/image/video/audio
        self.media_id: Optional[str] = kwargs.get("media_id")  # Reference to media asset
        self.timestamp: str = kwargs.get("timestamp", datetime.now().isoformat())
        self.metadata_extra: Dict[str, Any] = kwargs.get("metadata_extra", {})
    
    def validate(self) -> bool:
        """Validate message data."""
        if not self.conversation_id:
            raise AssetValidationError("Message must have a conversation_id")
        
        if not self.sender:
            raise AssetValidationError("Message must have a sender")
        
        if self.sender not in ["user", "character"]:
            raise AssetValidationError("Sender must be 'user' or 'character'")
        
        return True
    
    def export(self) -> Dict[str, Any]:
        """Export message to dict."""
        return {
            "type": "message",
            "id": self.id,
            "conversation_id": self.conversation_id,
            "character_id": self.character_id,
            "sender": self.sender,
            "content": self.content,
            "message_type": self.message_type,
            "media_id": self.media_id,
            "timestamp": self.timestamp,
            "metadata_extra": self.metadata_extra,
            "metadata": self.metadata.to_dict()
        }
    
    @classmethod
    def import_data(cls, data: Dict[str, Any]) -> "MessageAsset":
        """Import message from dict."""
        message = cls(
            conversation_id=data["conversation_id"],
            character_id=data.get("character_id", ""),
            sender=data["sender"],
            content=data.get("content", ""),
            message_type=data.get("message_type", "text"),
            media_id=data.get("media_id"),
            timestamp=data.get("timestamp", datetime.now().isoformat()),
            metadata_extra=data.get("metadata_extra", {})
        )
        message.id = data["id"]
        message.metadata.from_dict(data.get("metadata", {}))
        return message
    
    @classmethod
    def create(cls, conversation_id: str, sender: str, content: str, **kwargs) -> "MessageAsset":
        """Factory method to create a message."""
        return cls(conversation_id=conversation_id, sender=sender, content=content, **kwargs)
