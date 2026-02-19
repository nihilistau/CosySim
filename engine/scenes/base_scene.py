"""
BaseScene - Abstract base class for all scenes
Provides common functionality: character loading, asset management, save/load
"""
from abc import ABC, abstractmethod
from typing import Dict, List, Optional, Any
from pathlib import Path
import json
from datetime import datetime

import sys
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from engine.assets import AssetManager, CharacterAsset, SceneAsset


class BaseScene(ABC):
    """
    Abstract base class for all scenes
    
    Provides:
    - Asset management integration
    - Character loading from assets
    - Scene save/load functionality
    - Common scene lifecycle methods
    """
    
    def __init__(self, scene_name: str, host: str = "0.0.0.0", port: int = 5000):
        """
        Initialize base scene
        
        Args:
            scene_name: Unique name for this scene
            host: Host to bind to
            port: Port to listen on
        """
        self.scene_name = scene_name
        self.host = host
        self.port = port
        
        # Asset manager for all assets
        self.asset_manager = AssetManager()
        
        # Active characters in this scene
        self.active_characters: Dict[str, CharacterAsset] = {}
        
        # Scene configuration
        self.scene_config: Dict[str, Any] = {
            'name': scene_name,
            'created_at': datetime.now().isoformat(),
            'characters': [],
            'settings': {}
        }
        
        # Scene asset ID (if loaded from asset)
        self.scene_asset_id: Optional[str] = None
    
    def load_character(self, character_id: str) -> CharacterAsset:
        """
        Load a character from assets
        
        Args:
            character_id: Character asset ID
            
        Returns:
            CharacterAsset instance
        """
        character = self.asset_manager.load('character', character_id)
        self.active_characters[character_id] = character
        
        # Update scene config
        if character_id not in self.scene_config['characters']:
            self.scene_config['characters'].append(character_id)
        
        return character
    
    def unload_character(self, character_id: str) -> None:
        """Remove character from scene"""
        if character_id in self.active_characters:
            del self.active_characters[character_id]
            self.scene_config['characters'].remove(character_id)
    
    def get_character(self, character_id: str) -> Optional[CharacterAsset]:
        """Get active character by ID"""
        return self.active_characters.get(character_id)
    
    def list_characters(self) -> List[CharacterAsset]:
        """Get all active characters"""
        return list(self.active_characters.values())
    
    def save_scene(self, name: Optional[str] = None) -> str:
        """
        Save current scene state as an asset
        
        Args:
            name: Optional scene name (defaults to scene_name)
            
        Returns:
            Scene asset ID
        """
        scene_name = name or self.scene_name
        
        # Create scene asset
        scene_data = {
            'name': scene_name,
            'type': self.__class__.__name__,
            'host': self.host,
            'port': self.port,
            'characters': list(self.active_characters.keys()),
            'config': self.scene_config.get('settings', {}),
            'template': None,
            'dependencies': list(self.active_characters.keys())
        }
        
        # Create or update scene asset
        scene_asset = SceneAsset(**scene_data)
        scene_asset_id = self.asset_manager.save(scene_asset)
        
        self.scene_asset_id = scene_asset_id
        return scene_asset_id
    
    def load_scene(self, scene_id: str) -> None:
        """
        Load scene from asset
        
        Args:
            scene_id: Scene asset ID
        """
        scene_asset = self.asset_manager.load('scene', scene_id)
        
        # Load all characters
        for char_id in scene_asset.characters:
            try:
                self.load_character(char_id)
            except Exception as e:
                print(f"Warning: Could not load character {char_id}: {e}")
        
        # Apply scene configuration
        self.scene_config['settings'] = scene_asset.config
        self.scene_asset_id = scene_id
        
        # Call scene-specific load logic
        self.on_scene_loaded(scene_asset)
    
    def export_scene(self, export_path: Path) -> None:
        """
        Export scene and all dependencies
        
        Args:
            export_path: Directory to export to
        """
        if not self.scene_asset_id:
            self.save_scene()
        
        export_path = Path(export_path)
        export_path.mkdir(parents=True, exist_ok=True)
        
        # Export scene asset
        scene_data = self.asset_manager.export_asset(self.scene_asset_id)
        with open(export_path / f"{self.scene_name}_scene.json", 'w') as f:
            json.dump(scene_data, f, indent=2)
        
        # Export all character assets
        for char_id in self.active_characters:
            char_data = self.asset_manager.export_asset(char_id)
            with open(export_path / f"character_{char_id[:8]}.json", 'w') as f:
                json.dump(char_data, f, indent=2)
    
    def import_scene(self, import_path: Path) -> str:
        """
        Import scene from export
        
        Args:
            import_path: Path to scene JSON file
            
        Returns:
            Imported scene asset ID
        """
        with open(import_path, 'r') as f:
            scene_data = json.load(f)
        
        scene_id = self.asset_manager.import_asset(scene_data)
        self.load_scene(scene_id)
        return scene_id
    
    # ============= ABSTRACT METHODS =============
    
    @abstractmethod
    def start(self) -> None:
        """Start the scene (Flask app, Streamlit, etc.)"""
        pass
    
    @abstractmethod
    def stop(self) -> None:
        """Stop the scene and cleanup"""
        pass
    
    # ============= LIFECYCLE HOOKS =============
    
    def on_scene_loaded(self, scene_asset: SceneAsset) -> None:
        """Called after scene is loaded from asset"""
        pass
    
    def on_character_added(self, character: CharacterAsset) -> None:
        """Called when character is added to scene"""
        pass
    
    def on_character_removed(self, character_id: str) -> None:
        """Called when character is removed from scene"""
        pass
