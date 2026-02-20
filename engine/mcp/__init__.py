"""CosySim MCP package — exposes framework capabilities to LMStudio via MCP."""

# ─── Framework (root singleton + scene/character nodes + mixin) ───────────────
from engine.mcp.framework import (
    get_framework,
    MCPFramework,
    MCPSceneMixin,
    MCPSceneNode,
    MCPCharacterNode,
    MCPTimer,
    ScheduledConsequence,
    CrossSceneMessage,
)

# ─── Character Registry ────────────────────────────────────────────────────────
from engine.mcp.character_registry import (
    get_character_registry,
    CharacterRegistry,
    apply_default_skills,
)

# ─── Dialog System ─────────────────────────────────────────────────────────────
from engine.mcp.dialog_system import (
    get_dialog_system,
    DialogSystem,
    SpeechStyle,
    ResponseDirective,
    ConversationState,
)

# ─── Scene Rules Engine ────────────────────────────────────────────────────────
from engine.mcp.scene_rules_engine import (
    get_rules_engine,
    SceneRulesEngine,
)

# ─── Scene State Manager ──────────────────────────────────────────────────────
from engine.mcp.scene_state import (
    get_scene_state_manager,
    SceneStateManager,
)

# ─── Communications & Governance Framework ────────────────────────────────────
from engine.mcp.comms_framework import (
    # Governor factory + class
    get_governor,
    AgentGovernor,
    # Interceptor base + pipeline
    InterceptorBase,
    InterceptorPipeline,
    # Policy, context, manifest
    InteractionPolicy,
    ResponseContext,
    SkillManifest,
    SceneManifest,
    SkillEntry,
    # Trigger type constants
    TRIGGER_AUTO,
    TRIGGER_OPTIONAL,
    TRIGGER_REQUIRED,
    # Game state
    get_game_state,
    GameState,
    # Agent router
    get_router,
    AgentRouter,
    # Skill manifest singleton
    get_skill_manifest,
)

__all__ = [
    # Framework
    "get_framework",
    "MCPFramework",
    "MCPSceneMixin",
    "MCPSceneNode",
    "MCPCharacterNode",
    "MCPTimer",
    "ScheduledConsequence",
    "CrossSceneMessage",
    # Character Registry
    "get_character_registry",
    "CharacterRegistry",
    "apply_default_skills",
    # Dialog System
    "get_dialog_system",
    "DialogSystem",
    "SpeechStyle",
    "ResponseDirective",
    "ConversationState",
    # Rules Engine
    "get_rules_engine",
    "SceneRulesEngine",
    # Scene State
    "get_scene_state_manager",
    "SceneStateManager",
    # Comms / Governance
    "get_governor",
    "AgentGovernor",
    "InterceptorBase",
    "InterceptorPipeline",
    "InteractionPolicy",
    "ResponseContext",
    "SkillManifest",
    "SceneManifest",
    "SkillEntry",
    "TRIGGER_AUTO",
    "TRIGGER_OPTIONAL",
    "TRIGGER_REQUIRED",
    "get_game_state",
    "GameState",
    "get_router",
    "AgentRouter",
    "get_skill_manifest",
]
