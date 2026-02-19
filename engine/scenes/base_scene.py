"""
BaseScene — Abstract base for all CosySim scenes.
==================================================

Provides a standard contract every scene inherits:

* **Character management** — load / unload / list from asset system
* **Scene persistence** — save_scene / load_scene
* **Discovery** — get_plugin_info(), get_health(), get_skill_packs()
* **Lifecycle hooks** — on_scene_loaded, on_character_added, on_character_removed

Concrete scenes must implement ``start()``, ``stop()``, and
``get_plugin_info()`` at minimum.

Usage::

    class MyScene(BaseScene):
        def start(self):   ...
        def stop(self):    ...
        def get_plugin_info(self): return {...}
"""
from abc import ABC, abstractmethod
from typing import TYPE_CHECKING, Dict, List, Optional, Any
from pathlib import Path
import json
from datetime import datetime

if TYPE_CHECKING:
    from content.simulation.character_system.character import Character

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
        Load a character from assets and fire on_character_added hook.
        """
        character = self.asset_manager.load('character', character_id)
        self.active_characters[character_id] = character
        
        if character_id not in self.scene_config['characters']:
            self.scene_config['characters'].append(character_id)
        
        # Fire lifecycle hook
        self.on_character_added(character)
        return character
    
    def unload_character(self, character_id: str) -> None:
        """Remove character from scene and fire on_character_removed hook."""
        if character_id in self.active_characters:
            del self.active_characters[character_id]
            if character_id in self.scene_config['characters']:
                self.scene_config['characters'].remove(character_id)
            self.on_character_removed(character_id)
    
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
        raise NotImplementedError(
            "Scene export is not yet implemented. "
            "AssetManager needs export_asset() method — see plan Phase 1.8."
        )
    
    def import_scene(self, import_path: Path) -> str:
        """
        Import scene from export
        
        Args:
            import_path: Path to scene JSON file
            
        Returns:
            Imported scene asset ID
        """
        raise NotImplementedError(
            "Scene import is not yet implemented. "
            "AssetManager needs import_asset() method — see plan Phase 1.8."
        )

    def _asset_to_character(self, char_asset: CharacterAsset) -> 'Character':
        """
        Convert a CharacterAsset to a Character DB object.

        Uses the CharacterAsset.to_character() bridge (Phase 3) which:
        - Tries to load an existing DB row by asset ID
        - Creates a new row seeded from asset attributes if none found
        - Returns the loaded Character instance

        Requires the scene to have a ``self.db`` attribute (Database instance).
        Falls back gracefully if db is not yet available.

        Args:
            char_asset: CharacterAsset to convert

        Returns:
            Character instance ready for services / LLM calls
        """
        db = getattr(self, 'db', None)
        return char_asset.to_character(db)

    # ============= ABSTRACT METHODS =============

    @abstractmethod
    def start(self) -> None:
        """Start the scene (Flask app, Streamlit, etc.)"""
        pass

    @abstractmethod
    def stop(self) -> None:
        """Stop the scene and cleanup"""
        pass

    @abstractmethod
    def get_plugin_info(self) -> Dict[str, Any]:
        """
        Return scene metadata consumed by the admin panel and launcher.

        Every concrete scene **must** implement this to be discoverable.

        Returns a dict with at minimum::

            {
                "name":        str,          # human-readable scene name
                "description": str,          # one-line description
                "version":     str,          # semver string, e.g. "1.0.0"
                "author":      str,
                "port":        int,          # HTTP port this scene binds to
                "tags":        List[str],    # e.g. ["phone", "character", "chat"]
                "skill_packs": List[str],    # skill pack names the scene uses
                "routes":      List[Dict],   # [{"path": "/api/...", "methods": [...], "description": "..."}]
            }

        The admin panel calls ``get_plugin_info()`` on each loaded scene to
        populate the scene registry and skill-pack cross-reference table.
        """
        pass

    # ============= PLUGIN HOOKS =============

    def get_skill_packs(self) -> List[str]:
        """
        Return the list of skill pack names this scene exposes.

        Override in subclass to advertise skills.  Defaults to empty list
        (scene uses no tools).  The base implementation reads
        ``get_plugin_info()["skill_packs"]`` when available.

        Returns:
            List of pack name strings understood by SKILL_REGISTRY.
        """
        try:
            return self.get_plugin_info().get("skill_packs", [])
        except NotImplementedError:
            return []

    def get_health(self) -> Dict[str, Any]:
        """
        Return a simple health-check dict for the admin panel.

        Subclasses can override to add service-level checks.

        Returns:
            dict with keys ``ok`` (bool), ``scene`` (str), ``port`` (int),
            and optional ``details`` string.
        """
        return {
            "ok": True,
            "scene": self.scene_name,
            "port": self.port,
        }
    
    # ============= LIFECYCLE HOOKS =============
    # Override these in subclasses to react to scene events.
    
    def on_scene_loaded(self, scene_asset: SceneAsset) -> None:
        """Called after a saved scene is restored from an asset.
        Override to apply scene-specific configuration from the asset."""
        pass
    
    def on_character_added(self, character: CharacterAsset) -> None:
        """Called after a character is loaded into the scene.
        Override to initialise character-specific resources (e.g. 3D model, SocketIO room)."""
        pass
    
    def on_character_removed(self, character_id: str) -> None:
        """Called after a character is removed from the scene.
        Override to clean up character-specific resources."""
        pass
