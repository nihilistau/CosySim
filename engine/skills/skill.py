"""
skill.py — Core skill decorator, metadata, and pack definitions

A **Skill** is a plain Python function annotated with type hints so that:

1. The LMStudio SDK can auto-generate a JSON schema for it (``lmstudio.act()``).
2. The CosySim skill registry can discover, group, and describe all skills.

The ``@skill`` decorator is the only thing a skill author needs::

    from engine.skills.skill import skill

    @skill(pack="comfyui", description="Generate an image and return its URL")
    def generate_image(prompt: str, width: int = 512, height: int = 512) -> str:
        \"\"\"Generate an image matching *prompt* and return the file URL.\"\"\"
        ...

Details
-------
* The decorator does **not** modify the function — it remains callable as-is.
* Registration happens at import time via the global ``SKILL_REGISTRY``.
* ``SkillPack`` is a lightweight grouping object: give it a pack name and it
  exposes ``.tools`` (list of callables) ready for ``lmstudio.llm().act()``.
* Skills can have categories, cooldowns, prerequisites, and costs for
  governance-aware execution.
"""
from __future__ import annotations

import functools
import time
import threading
from dataclasses import dataclass, field
from typing import Callable, Dict, List, Optional, Any


# ══════════════════════════════════════════════════════════════════════
#  SKILL CATEGORIES
# ══════════════════════════════════════════════════════════════════════

class SkillCategory:
    """Predefined skill categories for organization and filtering."""
    COMMUNICATION = "communication"     # messaging, voice, cross-scene
    MEMORY        = "memory"            # search, store, recall
    MEDIA         = "media"             # images, voice, video generation
    GAME          = "game"              # game state, dice, scoring
    SOCIAL        = "social"            # mood, relationship, contagion
    ENVIRONMENT   = "environment"       # lighting, props, scene changes
    SYSTEM        = "system"            # config, status, admin
    NARRATIVE     = "narrative"         # story beats, dialog, narration


@dataclass
class SkillMeta:
    """
    Metadata for a single registered skill.

    Attributes
    ----------
    func : Callable
        The original unwrapped function reference.
    name : str
        Canonical skill name (used in logs and registry keys).
    pack : str
        Pack this skill belongs to (e.g. ``"comfyui"``, ``"memory"``).
    description : str
        Human-readable description surfaced to the LLM as the tool description.
    tags : list[str]
        Optional free-form tags for filtering.
    category : str
        Skill category from SkillCategory constants.
    cooldown_secs : float
        Minimum seconds between invocations (0 = no cooldown).
    prerequisites : list[str]
        Skill names that must have been called first in the same session.
    cost : float
        Abstract cost for budget tracking (higher = more expensive).
    """
    func:           Callable
    name:           str
    pack:           str
    description:    str
    tags:           List[str]    = field(default_factory=list)
    category:       str          = ""
    cooldown_secs:  float        = 0.0
    prerequisites:  List[str]    = field(default_factory=list)
    cost:           float        = 1.0

    def __repr__(self) -> str:
        return f"<SkillMeta {self.pack}.{self.name}>"


# ══════════════════════════════════════════════════════════════════════
#  COOLDOWN TRACKER
# ══════════════════════════════════════════════════════════════════════

class CooldownTracker:
    """Thread-safe skill cooldown enforcement."""

    def __init__(self) -> None:
        self._last_used: Dict[str, float] = {}
        self._lock = threading.Lock()

    def can_use(self, skill_name: str, cooldown_secs: float) -> bool:
        if cooldown_secs <= 0:
            return True
        with self._lock:
            last = self._last_used.get(skill_name, 0.0)
            return (time.time() - last) >= cooldown_secs

    def mark_used(self, skill_name: str) -> None:
        with self._lock:
            self._last_used[skill_name] = time.time()

    def get_remaining(self, skill_name: str, cooldown_secs: float) -> float:
        with self._lock:
            last = self._last_used.get(skill_name, 0.0)
            remaining = cooldown_secs - (time.time() - last)
            return max(0.0, remaining)

    def reset(self, skill_name: str = "") -> None:
        with self._lock:
            if skill_name:
                self._last_used.pop(skill_name, None)
            else:
                self._last_used.clear()


# Global cooldown tracker
COOLDOWN_TRACKER = CooldownTracker()


@dataclass
class SkillPack:
    """
    A named collection of related skills.

    ``tools`` returns the list of callables ready for ``lmstudio.llm().act()``.

    Example::

        from engine.skills import SKILL_REGISTRY

        comfy = SkillPack("comfyui")
        result = llm.act("Draw a sunset", comfy.tools)
    """
    name:        str
    description: str = ""

    @property
    def tools(self) -> List[Callable]:
        """Return all skill callables registered under this pack."""
        from engine.skills.registry import SKILL_REGISTRY
        return SKILL_REGISTRY.get_pack_tools(self.name)

    @property
    def skill_metas(self) -> List[SkillMeta]:
        """Return all SkillMeta objects for this pack."""
        from engine.skills.registry import SKILL_REGISTRY
        return SKILL_REGISTRY.get_pack_metas(self.name)

    def __repr__(self) -> str:
        return f"<SkillPack {self.name!r} ({len(self.tools)} tools)>"


# ────────────────────────────────────────────── decorator factory ──

def skill(
    func:          Optional[Callable] = None,
    *,
    name:          Optional[str]  = None,
    description:   str            = "",
    pack:          str            = "default",
    tags:          List[str]      = None,
    category:      str            = "",
    cooldown:      float          = 0.0,
    prerequisites: List[str]      = None,
    cost:          float          = 1.0,
) -> Any:
    """
    Decorator that registers a function as a CosySim skill.

    Can be used with or without arguments::

        # No-arg form — pack defaults to 'default'
        @skill
        def my_tool(x: int) -> str: ...

        # With arguments
        @skill(pack="comfyui", description="Generate an image", category="media")
        def generate_image(prompt: str) -> str: ...

    The decorated function is returned **unchanged** so it can be called
    directly in tests without any special handling.

    Parameters
    ----------
    name : str, optional
        Registry key.  Defaults to ``func.__name__``.
    description : str
        Tool description shown to the LLM.
    pack : str
        Pack name; skills can be retrieved together by pack.
    tags : list[str]
        Optional tags for filtering / discovery.
    category : str
        Skill category (SkillCategory constant).
    cooldown : float
        Minimum seconds between invocations.
    prerequisites : list[str]
        Skill names that must be called first.
    cost : float
        Abstract cost for budget tracking.
    """
    def _register(fn: Callable) -> Callable:
        _name = name or fn.__name__
        _desc = description or (fn.__doc__ or "").split("\n")[0].strip()
        meta  = SkillMeta(
            func=fn,
            name=_name,
            pack=pack,
            description=_desc,
            tags=list(tags or []),
            category=category,
            cooldown_secs=cooldown,
            prerequisites=list(prerequisites or []),
            cost=cost,
        )
        from engine.skills.registry import SKILL_REGISTRY
        SKILL_REGISTRY.register(meta)
        return fn

    if func is not None:
        return _register(func)
    return _register
