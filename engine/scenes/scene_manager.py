"""SceneManager - Manages scene lifecycle and instances"""
import logging
from typing import Dict, Optional, Type
from pathlib import Path

import sys
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from engine.scenes.base_scene import BaseScene
from engine.assets import AssetManager

logger = logging.getLogger(__name__)


class SceneManager:
    """
    Manages multiple scene instances
    Handles scene registration, creation, and lifecycle
    """
    
    def __init__(self):
        self.asset_manager = AssetManager()
        self.active_scenes: Dict[str, BaseScene] = {}
        self.scene_registry: Dict[str, Type[BaseScene]] = {}
    
    def register_scene_type(self, name: str, scene_class: Type[BaseScene]) -> None:
        """Register a scene type"""
        self.scene_registry[name] = scene_class

    def seed_default_scenes(self) -> int:
        """Auto-register all known Flask scenes from the launcher catalogue.

        Returns the number of scenes registered.
        """
        KNOWN_SCENES = {
            "phone":   {"cls": "content.scenes.phone.phone_scene_v2.PhoneSceneV2",   "port": 5555, "label": "CosyPhone OS"},
            "bedroom": {"cls": "content.scenes.bedroom.bedroom_scene.BedroomScene",   "port": 5556, "label": "The Bedroom"},
            "lounge":  {"cls": "content.scenes.lounge.lounge_scene.LoungeScene",       "port": 5557, "label": "The Velvet Lounge"},
            "casino":  {"cls": "content.scenes.casino.casino_scene.CasinoScene",       "port": 5559, "label": "Midnight Casino"},
            "gallery": {"cls": "content.scenes.gallery.gallery_scene.GalleryScene",    "port": 5560, "label": "The Gallery"},
            "warzone": {"cls": "content.scenes.warzone.warzone_scene.WarzoneScene",    "port": 5561, "label": "Global Strike"},
            "realm":   {"cls": "content.scenes.realm.realm_scene.RealmScene",          "port": 5562, "label": "The Realm"},
            "neoncity": {"cls": "content.scenes.neoncity.neoncity_scene.NeonCityScene", "port": 5563, "label": "NeonCity"},
            "coders":  {"cls": "content.scenes.coders.coders_scene.CodersRoomScene",   "port": 5564, "label": "The Coders Room"},
        }
        count = 0
        for name, info in KNOWN_SCENES.items():
            if name in self.scene_registry:
                continue
            try:
                mod_path, cls_name = info["cls"].rsplit(".", 1)
                import importlib
                mod = importlib.import_module(mod_path)
                cls = getattr(mod, cls_name)
                self.scene_registry[name] = cls
                count += 1
                logger.debug("SceneManager: auto-registered '%s'", name)
            except Exception as exc:
                logger.debug("SceneManager: failed to register '%s': %s", name, exc)
        return count
    
    def create_scene(self, scene_type: str, scene_name: str, **kwargs) -> BaseScene:
        """
        Create a new scene instance
        
        Args:
            scene_type: Type of scene (must be registered)
            scene_name: Unique name for this instance
            **kwargs: Additional arguments for scene constructor
            
        Returns:
            Scene instance
        """
        if scene_type not in self.scene_registry:
            raise ValueError(f"Scene type '{scene_type}' not registered")
        
        scene_class = self.scene_registry[scene_type]
        scene = scene_class(scene_name=scene_name, **kwargs)
        self.active_scenes[scene_name] = scene

        # Register with MCPFramework
        try:
            from engine.mcp.framework import get_framework
            get_framework().get_scene(scene_name)
            logger.debug("SceneManager: MCPFramework registered scene '%s'", scene_name)
        except Exception as _exc:
            logger.debug("SceneManager create_scene MCP sync failed: %s", _exc)

        return scene
    
    def load_scene(self, scene_id: str) -> BaseScene:
        """
        Load scene from asset
        
        Args:
            scene_id: Scene asset ID
            
        Returns:
            Loaded scene instance
        """
        scene_asset = self.asset_manager.load('scene', scene_id)
        
        # Get scene type from asset
        scene_type = scene_asset.type
        
        if scene_type not in self.scene_registry:
            raise ValueError(f"Scene type '{scene_type}' not registered")
        
        # Create scene instance
        scene_class = self.scene_registry[scene_type]
        scene = scene_class(
            scene_name=scene_asset.name,
            host=scene_asset.host,
            port=scene_asset.port
        )
        
        # Load scene state
        scene.load_scene(scene_id)
        
        self.active_scenes[scene_asset.name] = scene
        return scene
    
    def get_scene(self, scene_name: str) -> Optional[BaseScene]:
        """Get active scene by name"""
        return self.active_scenes.get(scene_name)
    
    def stop_scene(self, scene_name: str) -> None:
        """Stop and remove a scene."""
        if scene_name in self.active_scenes:
            scene = self.active_scenes[scene_name]
            scene.stop()
            # Notify MCP
            try:
                scene._mcp_deregister_scene()
            except Exception:
                pass
            del self.active_scenes[scene_name]
            logger.info("SceneManager: stopped scene '%s'", scene_name)
    
    def stop_all(self) -> None:
        """Stop all active scenes"""
        for scene_name in list(self.active_scenes.keys()):
            self.stop_scene(scene_name)
    
    def list_active_scenes(self) -> list:
        """List all active scenes"""
        return list(self.active_scenes.keys())
    
    def list_scene_types(self) -> list:
        """List all registered scene types"""
        return list(self.scene_registry.keys())
