"""
Interceptor Registry
====================

Auto-registry for all InterceptorBase subclasses in the agent pipeline.
Import this module and call ``get_all_interceptors()`` to get a list of all
registered interceptor classes, sorted by priority.  ``comms_framework.py``
uses this instead of maintaining a hardcoded list.

Version: v1.54.0 [2026-03-26]
Author:  CosySim Team

Change Log:
    v1.62.0 [2026-06-15] — Registered CommsLoggerInterceptor (CB-T2): every
                            governed agent reply flows into GlobalCommsLog
    v1.54.0 [2026-03-26] — Registered 6 missing interceptors, sorted registry by priority
    v1.51.1 [2026-03-25] — Added FactionContext + HeatAwareness interceptors
    v1.51.0 [2026-03-25] — Added SpectatorBroadcast + NarrativeMod interceptors
    v1.49.1 [2026-03-22] — Switched to real RelationshipContextInterceptor

Usage::

    from engine.agents.interceptors import get_all_interceptors

    pipeline = InterceptorPipeline()
    for cls in get_all_interceptors():
        pipeline.add(cls())
"""
from __future__ import annotations

from typing import Type

from engine.agents.interceptors.cache import INTERCEPTOR_CACHE, _InterceptorCache  # noqa: F401

from engine.agents.interceptors.router_message import RouterMessageInjector
from engine.agents.interceptors.auto_result import AutoResultInjector
from engine.agents.interceptors.skill_awareness import SkillAwarenessInterceptor
from engine.agents.interceptors.game import GameInterceptor
from engine.agents.interceptors.personality_guard import PersonalityGuardInterceptor
from engine.agents.interceptors.conversation_variety import ConversationVarietyInterceptor
from engine.agents.interceptors.policy_enforcer import PolicyEnforcerInterceptor
from engine.agents.interceptors.memory_enhancer import MemoryEnhancerInterceptor
from engine.agents.interceptors.response_shaper import ResponseShaperInterceptor
from engine.agents.interceptors.activity_logger import ActivityLoggerInterceptor
# v1.62.0 [2026-06-15] — CB-T2: write every governed agent reply into GlobalCommsLog
from engine.agents.interceptors.comms_logger import CommsLoggerInterceptor
from engine.agents.interceptors.penthouse_scene import PenthouseSceneInterceptor
from engine.agents.interceptors.phone_scene import PhoneSceneInterceptor
from engine.agents.interceptors.lounge_scene import LoungeSceneInterceptor
from engine.agents.interceptors.gallery_scene import GallerySceneInterceptor
from engine.agents.interceptors.universal_scene import UniversalSceneInterceptor
from engine.agents.interceptors.ambient_event import AmbientEventInterceptor
from engine.agents.interceptors.character_registry import CharacterRegistryInterceptor
from engine.agents.interceptors.dialog_directive import DialogDirectiveInterceptor
from engine.agents.interceptors.tts_style import TTSStyleInterceptor
from engine.agents.interceptors.mood_sync import MoodSyncInterceptor
from engine.agents.interceptors.stat_sync import StatSyncInterceptor
from engine.agents.interceptors.stimulus_detect import StimulusDetectInterceptor
from engine.agents.interceptors.natural_mood_drift import NaturalMoodDriftInterceptor
from engine.agents.interceptors.conversation_recap import ConversationRecapInterceptor
from engine.agents.interceptors.relationship_event import RelationshipEventInterceptor
from engine.agents.interceptors.nexus_prompt import NexusPromptInterceptor
# v1.51.0 [2026-03-25] — Spectator/danmaku broadcast interceptor
from engine.agents.interceptors.spectator_broadcast import SpectatorBroadcastInterceptor
# v1.51.0 [2026-03-25] — Narrative mod stage injection interceptor
from engine.agents.interceptors.narrative_mod import NarrativeModInterceptor
# v1.51.1 [2026-03-25] — Faction standing context injection
from engine.agents.interceptors.faction_context import FactionContextInterceptor
# v1.51.1 [2026-03-25] — Heat/wanted level awareness
from engine.agents.interceptors.heat_awareness import HeatAwarenessInterceptor
from engine.characters.neurochemistry import NeurochemistryInterceptor
# v1.49.1 [2026-03-22] — Use the real RelationshipContextInterceptor (not the split stub)
from engine.agents.relationship_interceptor import RelationshipContextInterceptor  # noqa: F401
from engine.agents.dialogue_gate import DialogueGateInterceptor
# v1.54.0 [2026-03-26] — Registered missing interceptors from engine subsystems
from engine.content.content_gate import ContentIntensityInterceptor
from engine.characters.memory import CharacterMemoryInterceptor
from engine.world.world_state import WorldStateInterceptor
from engine.characters.reputation import ReputationInterceptor
from engine.agents.grammar_scanner_interceptor import GrammarScannerInterceptor
# Backward-compat aliases — GameInterceptor merged GameSession + GameRules in v3.1
GameSessionInterceptor = GameInterceptor
GameRulesInterceptor = GameInterceptor

# v1.54.0 [2026-03-26] — Sorted by priority, registered 6 missing interceptors
_REGISTRY: list[Type] = [
    ContentIntensityInterceptor,    # pri  1 — content profile injection (NEW)
    NeurochemistryInterceptor,      # pri  4 — neurochemistry mood tagging
    NaturalMoodDriftInterceptor,    # pri  5 — natural stat drift + inner thoughts
    NexusPromptInterceptor,         # pri  6 — Nexus context hydration
    ConversationRecapInterceptor,   # pri  7 — short-term conversation memory
    CharacterMemoryInterceptor,     # pri  7 — RAG character memory injection (NEW)
    CharacterRegistryInterceptor,   # pri  8 — character identity injection
    RouterMessageInjector,          # pri 10 — agent-router inbox messages
    DialogDirectiveInterceptor,     # pri 12 — must_include / style_lock directives
    NarrativeModInterceptor,        # pri 15 — stage context injection
    PenthouseSceneInterceptor,      # pri 15 — penthouse scene context
    PhoneSceneInterceptor,          # pri 15 — phone scene context
    LoungeSceneInterceptor,         # pri 15 — lounge scene context
    GallerySceneInterceptor,        # pri 15 — gallery scene context
    WorldStateInterceptor,          # pri 15 — world time/weather/events (NEW)
    UniversalSceneInterceptor,      # pri 16 — universal scene fallback
    AmbientEventInterceptor,        # pri 17 — random ambient micro-events
    AutoResultInjector,             # pri 20 — auto-skill result injection
    ReputationInterceptor,          # pri 22 — reputation context block (NEW)
    SkillAwarenessInterceptor,      # pri 30 — skill manifest awareness
    GameInterceptor,                # pri 35 — game session/rules
    FactionContextInterceptor,      # pri 40 — faction standing context
    DialogueGateInterceptor,        # pri 45 — reputation-based dialogue gating (NEW)
    RelationshipContextInterceptor, # pri 46 — relationship context
    PersonalityGuardInterceptor,    # pri 50 — personality consistency guard
    ConversationVarietyInterceptor, # pri 55 — anti-repetition + expressiveness
    PolicyEnforcerInterceptor,      # pri 60 — policy enforcement
    MemoryEnhancerInterceptor,      # pri 70 — deep RAG memory recall
    HeatAwarenessInterceptor,       # pri 75 — heat/wanted level awareness
    ResponseShaperInterceptor,      # pri 80 — response formatting/shaping
    TTSStyleInterceptor,            # pri 85 — TTS voice style tags
    StimulusDetectInterceptor,      # pri 88 — NLP stimulus detection → neurochemistry
    ActivityLoggerInterceptor,      # pri 90 — EventChain + training logging
    CommsLoggerInterceptor,         # pri 90 — write agent reply → GlobalCommsLog (CB-T2)
    StatSyncInterceptor,            # pri 91 — apply [STAT:x±y] tags to game state
    MoodSyncInterceptor,            # pri 92 — mood sync to CharacterRegistry
    SpectatorBroadcastInterceptor,  # pri 92 — danmaku spectator broadcast
    RelationshipEventInterceptor,   # pri 93 — relationship buff detection
    GrammarScannerInterceptor,      # pri 95 — output quality flagging (NEW)
]


def get_all_interceptors() -> list[Type]:
    """Return the ordered list of all registered interceptor classes."""
    return list(_REGISTRY)


def register_interceptor(cls: Type) -> Type:
    """Class decorator that registers an interceptor in the global registry.

    Usage::

        @register_interceptor
        class MyCustomInterceptor(InterceptorBase):
            ...
    """
    if cls not in _REGISTRY:
        _REGISTRY.append(cls)
    return cls


__all__ = [
    "get_all_interceptors",
    "register_interceptor",
    "INTERCEPTOR_CACHE",
    "_InterceptorCache",
    "ContentIntensityInterceptor",
    "NeurochemistryInterceptor",
    "NaturalMoodDriftInterceptor",
    "NexusPromptInterceptor",
    "ConversationRecapInterceptor",
    "CharacterMemoryInterceptor",
    "CharacterRegistryInterceptor",
    "RouterMessageInjector",
    "DialogDirectiveInterceptor",
    "NarrativeModInterceptor",
    "PenthouseSceneInterceptor",
    "PhoneSceneInterceptor",
    "LoungeSceneInterceptor",
    "GallerySceneInterceptor",
    "WorldStateInterceptor",
    "UniversalSceneInterceptor",
    "AmbientEventInterceptor",
    "AutoResultInjector",
    "ReputationInterceptor",
    "SkillAwarenessInterceptor",
    "GameInterceptor",
    "GameSessionInterceptor",
    "GameRulesInterceptor",
    "FactionContextInterceptor",
    "DialogueGateInterceptor",
    "RelationshipContextInterceptor",
    "PersonalityGuardInterceptor",
    "ConversationVarietyInterceptor",
    "PolicyEnforcerInterceptor",
    "MemoryEnhancerInterceptor",
    "HeatAwarenessInterceptor",
    "ResponseShaperInterceptor",
    "TTSStyleInterceptor",
    "StimulusDetectInterceptor",
    "ActivityLoggerInterceptor",
    "CommsLoggerInterceptor",
    "MoodSyncInterceptor",
    "SpectatorBroadcastInterceptor",
    "RelationshipEventInterceptor",
    "GrammarScannerInterceptor",
]


# v1.54.0 [2026-03-26] — Log interceptor registration count at import time
import logging as _logging
_logger = _logging.getLogger(__name__)
_logger.info(
    "[interceptors] Registered %d interceptors (operation=init)",
    len(_REGISTRY),
)
