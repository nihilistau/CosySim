"""engine.agents — CosySim AI agent layer

Public API::

    from engine.agents import CharacterAgent, AgentLoop, SceneAgent
    from engine.agents import AgentGovernor, get_governor
    from engine.agents import VirtualAgent, VirtualAgentManager, get_virtual_agent_manager
    from engine.agents.protocols import IAgent, AgentCapability
"""
from .character_agent import CharacterAgent
from .scene_agent      import SceneAgent, get_scene_agent
from .agent_loop       import AgentLoop
from .protocols        import IAgent, IInterceptor, AgentCapability
from .virtual_agent    import VirtualAgent, InferenceRequest, InferenceResponse
from .virtual_agent_manager import VirtualAgentManager, get_virtual_agent_manager

# Governor re-exported for convenience — avoids deep imports in scenes
from engine.mcp.comms_framework import AgentGovernor, get_governor

__all__ = [
    "CharacterAgent",
    "SceneAgent",
    "get_scene_agent",
    "AgentLoop",
    "IAgent",
    "IInterceptor",
    "AgentCapability",
    "AgentGovernor",
    "get_governor",
    "VirtualAgent",
    "VirtualAgentManager",
    "get_virtual_agent_manager",
    "InferenceRequest",
    "InferenceResponse",
]
