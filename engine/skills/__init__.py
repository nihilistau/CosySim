"""
engine.skills — CosySim Skill System

A skill is a plain Python function decorated with ``@skill`` that can be
passed directly to ``lmstudio.llm().act()`` as a tool, or wired into an
``engine.agents.CharacterAgent``.

Quick start::

    from engine.skills import skill, SKILL_REGISTRY

    @skill(pack="comfyui", description="Generate an image from a text prompt")
    def generate_image(prompt: str, style: str = "realistic") -> str:
        ...

    # Get all tools in a pack
    tools = SKILL_REGISTRY.get_pack_tools("comfyui")

    # Use with LMStudio
    from engine.lmstudio import get_lmstudio_manager
    llm   = get_lmstudio_manager().get_llm()
    reply = llm.act("Draw a sunset", tools)
"""
from .skill    import skill, SkillMeta, SkillPack
from .registry import SKILL_REGISTRY, get_skills, get_pack_tools, mcp_skill_pack

__all__ = [
    "skill",
    "SkillMeta",
    "SkillPack",
    "SKILL_REGISTRY",
    "get_skills",
    "get_pack_tools",
    "mcp_skill_pack",
]
