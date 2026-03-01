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

v0.68 modules::

    from engine import get_economy_manager, EconomyManager
    from engine import get_character_memory, CharacterMemoryInterceptor
    from engine import get_reputation_manager, ReputationInterceptor
    from engine import get_scene_director, SceneDirector
    from engine import get_world_state, WorldStateInterceptor
    from engine import get_world_sim, WorldSim
    from engine import get_content_engine, ContentEngine
    from engine import get_content_gate, ContentIntensityInterceptor
    from engine import get_consequence_store, ConsequenceStore
    from engine import get_investigation_board, InvestigationBoard
    from engine import get_event_bus, EventBus
    from engine import get_arena_engine, ArenaEngine
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


# ──── v0.68 Engine Modules ────
from engine.economy.economy import EconomyManager, get_economy_manager  # noqa: F401
from engine.characters.memory import CharacterMemoryInterceptor, get_character_memory  # noqa: F401
from engine.characters.reputation import ReputationInterceptor, get_reputation_manager  # noqa: F401
from engine.director.scene_director import SceneDirector, get_scene_director  # noqa: F401
from engine.director.scene_director import DirectorBeat, BeatType  # noqa: F401
from engine.world.world_state import WorldStateInterceptor, get_world_state  # noqa: F401
from engine.world.world_sim import WorldSim, get_world_sim  # noqa: F401
from engine.content.content_engine import ContentEngine, get_content_engine  # noqa: F401
from engine.content.content_gate import ContentIntensityInterceptor, get_content_gate  # noqa: F401
from engine.mechanics.consequences import ConsequenceStore, get_consequence_store  # noqa: F401
from engine.mechanics.investigation import InvestigationBoard, get_investigation_board  # noqa: F401
from engine.events.event_bus import EventBus, get_event_bus  # noqa: F401
from engine.arena.arena_engine import ArenaEngine, get_arena_engine  # noqa: F401

__all__ = [
    "paths", "ROOT",
    "get_config",
    "BaseScene", "SceneRegistry",
    "CharacterAgent", "AgentLoop",
    "skill", "get_pack_tools",
    "Location", "SceneMap",
    "MediaConfig", "get_media_config",
    "install_logger", "timed", "get_system_monitor",
    # v0.68
    "EconomyManager", "get_economy_manager",
    "CharacterMemoryInterceptor", "get_character_memory",
    "ReputationInterceptor", "get_reputation_manager",
    "SceneDirector", "get_scene_director", "DirectorBeat", "BeatType",
    "WorldStateInterceptor", "get_world_state",
    "WorldSim", "get_world_sim",
    "ContentEngine", "get_content_engine",
    "ContentIntensityInterceptor", "get_content_gate",
    "ConsequenceStore", "get_consequence_store",
    "InvestigationBoard", "get_investigation_board",
    "EventBus", "get_event_bus",
    "ArenaEngine", "get_arena_engine",
]