"""engine/agents/interceptors/__init__.py — Auto-registry for all interceptors.

Import this module and call get_all_interceptors() to get a list of all
registered interceptor classes. comms_framework.py uses this instead of
maintaining a hardcoded list.

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
from engine.agents.interceptors.natural_mood_drift import NaturalMoodDriftInterceptor
from engine.agents.interceptors.conversation_recap import ConversationRecapInterceptor
from engine.agents.interceptors.relationship_event import RelationshipEventInterceptor
from engine.agents.interceptors.nexus_prompt import NexusPromptInterceptor
# v1.51.0 [2026-03-25] — Spectator/danmaku broadcast interceptor
from engine.agents.interceptors.spectator_broadcast import SpectatorBroadcastInterceptor
# v1.51.0 [2026-03-25] — Narrative mod stage injection interceptor
from engine.agents.interceptors.narrative_mod import NarrativeModInterceptor
from engine.characters.neurochemistry import NeurochemistryInterceptor
# v1.49.1 [2026-03-22] — Use the real RelationshipContextInterceptor (not the split stub)
from engine.agents.relationship_interceptor import RelationshipContextInterceptor  # noqa: F401
from engine.agents.dialogue_gate import DialogueGateInterceptor  # noqa: F401
# Backward-compat aliases — GameInterceptor merged GameSession + GameRules in v3.1
GameSessionInterceptor = GameInterceptor
GameRulesInterceptor = GameInterceptor

_REGISTRY: list[Type] = [
    NeurochemistryInterceptor,
    RouterMessageInjector,
    AutoResultInjector,
    SkillAwarenessInterceptor,
    GameInterceptor,
    PersonalityGuardInterceptor,
    ConversationVarietyInterceptor,
    PolicyEnforcerInterceptor,
    MemoryEnhancerInterceptor,
    ResponseShaperInterceptor,
    ActivityLoggerInterceptor,
    PenthouseSceneInterceptor,
    PhoneSceneInterceptor,
    LoungeSceneInterceptor,
    GallerySceneInterceptor,
    UniversalSceneInterceptor,
    AmbientEventInterceptor,
    CharacterRegistryInterceptor,
    DialogDirectiveInterceptor,
    TTSStyleInterceptor,
    MoodSyncInterceptor,
    NaturalMoodDriftInterceptor,
    ConversationRecapInterceptor,
    RelationshipEventInterceptor,
    RelationshipContextInterceptor,
    NexusPromptInterceptor,
    NarrativeModInterceptor,        # v1.51.0 — stage context injection (pri 15)
    SpectatorBroadcastInterceptor,  # v1.51.0 — danmaku spectator broadcast (pri 92)
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
    "RouterMessageInjector",
    "AutoResultInjector",
    "SkillAwarenessInterceptor",
    "GameInterceptor",
    "GameSessionInterceptor",
    "GameRulesInterceptor",
    "DialogueGateInterceptor",
    "PersonalityGuardInterceptor",
    "ConversationVarietyInterceptor",
    "PolicyEnforcerInterceptor",
    "MemoryEnhancerInterceptor",
    "ResponseShaperInterceptor",
    "ActivityLoggerInterceptor",
    "PenthouseSceneInterceptor",
    "PhoneSceneInterceptor",
    "LoungeSceneInterceptor",
    "GallerySceneInterceptor",
    "UniversalSceneInterceptor",
    "AmbientEventInterceptor",
    "CharacterRegistryInterceptor",
    "DialogDirectiveInterceptor",
    "TTSStyleInterceptor",
    "MoodSyncInterceptor",
    "NaturalMoodDriftInterceptor",
    "ConversationRecapInterceptor",
    "RelationshipEventInterceptor",
    "RelationshipContextInterceptor",
    "NexusPromptInterceptor",
    "SpectatorBroadcastInterceptor",
]
