"""
CosySim Engine — reusable AI agent simulation framework.

Public API::

    from engine import get_config, BaseScene, CharacterAgent, AgentLoop
    from engine import skill, get_pack_tools
    from engine import Location, SceneMap
    from engine import MediaConfig, get_media_config
    from engine import install_logger, timed, get_system_monitor
    from engine import SceneRegistry
    from engine.paths import paths, ROOT
"""

# Paths (must be first — other modules may import during their init)
from engine.paths import paths, ROOT  # noqa: F401

# Config
from engine.config import get_config  # noqa: F401

# Scenes
from engine.scenes.base_scene import BaseScene  # noqa: F401
from engine.scenes.scene_registry import SceneRegistry  # noqa: F401

# Agents
from engine.agents.character_agent import CharacterAgent  # noqa: F401
from engine.agents.agent_loop import AgentLoop  # noqa: F401

# Skills
from engine.skills.skill import skill  # noqa: F401
from engine.skills.registry import get_pack_tools  # noqa: F401

# Spatial
from engine.spatial.location import Location  # noqa: F401
from engine.spatial.scene_map import SceneMap  # noqa: F401

# Media
from engine.media.media_config import MediaConfig, get_media_config  # noqa: F401

# Logging / benchmarking / monitoring
from engine.logging import install_logger, timed, get_system_monitor  # noqa: F401

__all__ = [
    "paths", "ROOT",
    "get_config",
    "BaseScene", "SceneRegistry",
    "CharacterAgent", "AgentLoop",
    "skill", "get_pack_tools",
    "Location", "SceneMap",
    "MediaConfig", "get_media_config",
    "install_logger", "timed", "get_system_monitor",
]