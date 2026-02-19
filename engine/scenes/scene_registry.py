"""
Scene Registry — auto-discovers and validates scenes in ``content/scenes/``.

Usage::

    from engine.scenes.scene_registry import SceneRegistry
    registry = SceneRegistry()
    registry.discover()            # scan content/scenes/*/
    scenes = registry.get_all()    # list of SceneInfo dicts
"""
from __future__ import annotations

import importlib
import inspect
import logging
from pathlib import Path
from typing import Any, Dict, List, Optional, Type

logger = logging.getLogger(__name__)


class SceneInfo:
    """Metadata about a discovered scene."""

    def __init__(self, name: str, cls: Type, module_path: str, plugin_info: Dict[str, Any]):
        self.name = name
        self.cls = cls
        self.module_path = module_path
        self.plugin_info = plugin_info

    @property
    def port(self) -> int:
        return self.plugin_info.get("port", 0)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "name": self.name,
            "module": self.module_path,
            "port": self.port,
            **self.plugin_info,
        }


class SceneRegistry:
    """Discovers and validates BaseScene subclasses in ``content/scenes/``."""

    def __init__(self, scenes_dir: Optional[Path] = None):
        if scenes_dir is None:
            scenes_dir = Path(__file__).parent.parent.parent / "content" / "scenes"
        self.scenes_dir = scenes_dir
        self._scenes: Dict[str, SceneInfo] = {}

    def discover(self) -> List[SceneInfo]:
        """Scan each subdirectory in scenes_dir for BaseScene subclasses."""
        if not self.scenes_dir.exists():
            logger.warning("Scenes directory does not exist: %s", self.scenes_dir)
            return []

        from engine.scenes.base_scene import BaseScene

        for scene_dir in sorted(self.scenes_dir.iterdir()):
            if not scene_dir.is_dir() or scene_dir.name.startswith(("_", ".")):
                continue
            # Look for *_scene.py files
            for py_file in scene_dir.glob("*_scene.py"):
                self._try_load(py_file, BaseScene)

        # Validate ports
        self._validate_ports()

        logger.info("Discovered %d scenes: %s",
                     len(self._scenes),
                     ", ".join(f"{s.name}:{s.port}" for s in self._scenes.values()))
        return list(self._scenes.values())

    def _try_load(self, py_file: Path, base_cls: Type) -> None:
        """Attempt to import a file and find BaseScene subclasses."""
        # Build module path: content.scenes.{dir}.{file_stem}
        rel = py_file.relative_to(self.scenes_dir.parent.parent)
        module_path = str(rel.with_suffix("")).replace("\\", ".").replace("/", ".")

        try:
            mod = importlib.import_module(module_path)
        except Exception as e:
            logger.debug("Could not import %s: %s", module_path, e)
            return

        for attr_name in dir(mod):
            obj = getattr(mod, attr_name)
            if (inspect.isclass(obj)
                    and issubclass(obj, base_cls)
                    and obj is not base_cls
                    and not inspect.isabstract(obj)):
                try:
                    info = obj.__dict__.get("get_plugin_info")
                    # We can't call get_plugin_info without an instance, so
                    # try instantiation with defaults or inspect class
                    plugin_info = self._extract_plugin_info(obj)
                    name = plugin_info.get("name", attr_name)
                    scene_info = SceneInfo(
                        name=name, cls=obj,
                        module_path=module_path,
                        plugin_info=plugin_info,
                    )
                    self._scenes[name] = scene_info
                except Exception as e:
                    logger.debug("Could not extract info from %s: %s", attr_name, e)

    def _extract_plugin_info(self, cls: Type) -> Dict[str, Any]:
        """Try to get plugin_info without full init (may fail for complex scenes)."""
        # First try: instantiate with no args
        try:
            instance = cls.__new__(cls)
            if hasattr(instance, 'get_plugin_info'):
                return instance.get_plugin_info()
        except Exception:
            pass
        # Fallback: look for class-level metadata
        return {
            "name": cls.__name__.replace("Scene", ""),
            "description": cls.__doc__ or "",
            "port": 0,
        }

    def _validate_ports(self) -> None:
        """Check for port conflicts."""
        seen: Dict[int, str] = {}
        for scene in self._scenes.values():
            port = scene.port
            if port == 0:
                continue
            if port in seen:
                logger.warning("Port conflict: '%s' and '%s' both use port %d",
                               scene.name, seen[port], port)
            seen[port] = scene.name

    # ── Query ───────────────────────────────────────────────────────────
    def get_all(self) -> List[SceneInfo]:
        return list(self._scenes.values())

    def get_by_name(self, name: str) -> Optional[SceneInfo]:
        return self._scenes.get(name)

    def get_by_port(self, port: int) -> Optional[SceneInfo]:
        for s in self._scenes.values():
            if s.port == port:
                return s
        return None

    @property
    def names(self) -> List[str]:
        return list(self._scenes.keys())
