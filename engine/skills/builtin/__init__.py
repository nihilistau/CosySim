"""engine.skills.builtin — Built-in skill packs"""
# Import all packs so their @skill decorators fire at import time
from . import comfyui_skills, memory_skills, character_skills, voice_skills, tts_skills, social_skills
from . import training_skills, notebooklm_skills

__all__ = [
    "comfyui_skills", "memory_skills", "character_skills", "voice_skills",
    "tts_skills", "social_skills", "training_skills", "notebooklm_skills",
]
