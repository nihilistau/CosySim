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
"""
from __future__ import annotations

import functools
from dataclasses import dataclass, field
from typing import Callable, List, Optional, Any


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
    """
    func:        Callable
    name:        str
    pack:        str
    description: str
    tags:        List[str] = field(default_factory=list)

    def __repr__(self) -> str:
        return f"<SkillMeta {self.pack}.{self.name}>"


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
        # Import here to avoid a circular import at module level
        from engine.skills.registry import SKILL_REGISTRY
        return SKILL_REGISTRY.get_pack_tools(self.name)

    def __repr__(self) -> str:
        return f"<SkillPack {self.name!r} ({len(self.tools)} tools)>"


# ────────────────────────────────────────────── decorator factory ──

def skill(
    func:        Optional[Callable] = None,
    *,
    name:        Optional[str]  = None,
    description: str            = "",
    pack:        str            = "default",
    tags:        List[str]      = None,
) -> Any:
    """
    Decorator that registers a function as a CosySim skill.

    Can be used with or without arguments::

        # No-arg form — pack defaults to 'default'
        @skill
        def my_tool(x: int) -> str: ...

        # With arguments
        @skill(pack="comfyui", description="Generate an image")
        def generate_image(prompt: str) -> str: ...

    The decorated function is returned **unchanged** so it can be called
    directly in tests without any special handling.

    Parameters
    ----------
    name : str, optional
        Registry key.  Defaults to ``func.__name__``.
    description : str
        Tool description shown to the LLM.  Falls back to the function's
        docstring first line if not provided.
    pack : str
        Pack name; skills can be retrieved together by pack.
    tags : list[str]
        Optional tags for filtering / discovery.
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
        )
        # Lazy import to avoid circular dependency
        from engine.skills.registry import SKILL_REGISTRY
        SKILL_REGISTRY.register(meta)
        return fn

    if func is not None:
        # Used as @skill without parentheses
        return _register(func)

    # Used as @skill(...) with keyword arguments
    return _register
