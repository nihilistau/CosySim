from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional, Set

logger = logging.getLogger(__name__)

TRIGGER_AUTO     = "auto"       # run before LLM call; inject result into context
TRIGGER_OPTIONAL = "optional"   # model may choose to call it
TRIGGER_REQUIRED = "required"   # model MUST call it (enforced via system prompt)

@dataclass
class SkillEntry:
    """One skill definition within a manifest."""
    name:           str
    trigger:        str   = TRIGGER_OPTIONAL
    description:    str   = ""
    when:           str   = "always"
    args_template:  Dict  = field(default_factory=dict)

@dataclass
class InteractionPolicy:
    """Per-character/scene safety constraints and rules."""
    max_length:         int  = 500
    forbidden_topics:   List[str] = field(default_factory=list)
    required_tone:      Optional[str] = None
    response_format:    Optional[str] = None

class ResponseContext(dict):
    """
    Mutable context object for a single LLM generation cycle.
    Passed through the InterceptorPipeline.
    """
    def __getattr__(self, name):
        try:
            return self[name]
        except KeyError:
            raise AttributeError(name)

    def __setattr__(self, name, value):
        self[name] = value

class InterceptorBase:
    """
    Base class for all governance interceptors.
    """
    name: str = "Base"
    priority: int = 50
    applicable_scenes: Optional[Set[str]] = None

    def pre_call(self, ctx: ResponseContext) -> None:
        pass

    def post_call(self, ctx: ResponseContext) -> None:
        pass

class InterceptorPipeline:
    """
    Ordered execution of interceptors around the LLM call.
    """
    def __init__(self):
        self.interceptors: List[InterceptorBase] = []

    def add(self, interceptor: InterceptorBase) -> None:
        self.interceptors.append(interceptor)
        self.interceptors.sort(key=lambda x: x.priority)

    def run_pre(self, ctx: ResponseContext) -> None:
        scene = ctx.get("scene", "unknown")
        for inc in self.interceptors:
            if ctx.get("abort", False):
                break
            if inc.applicable_scenes and scene not in inc.applicable_scenes:
                continue
            try:
                inc.pre_call(ctx)
            except Exception as e:
                logger.error(f"Interceptor {inc.name} pre_call failed: {e}")

    def run_post(self, ctx: ResponseContext) -> None:
        scene = ctx.get("scene", "unknown")
        for inc in self.interceptors:
            if inc.applicable_scenes and scene not in inc.applicable_scenes:
                continue
            try:
                inc.post_call(ctx)
            except Exception as e:
                logger.error(f"Interceptor {inc.name} post_call failed: {e}")

