"""engine.skills.builtin — Built-in skill packs"""
# Import all packs so their @skill decorators fire at import time
from . import comfyui_skills, memory_skills, character_skills, voice_skills, tts_skills, social_skills
from . import training_skills, notebooklm_skills
from . import board_skills, coding_skills, nexus_skills
from . import experiment_skills, agent_state_skills

__all__ = [
    "comfyui_skills", "memory_skills", "character_skills", "voice_skills",
    "tts_skills", "social_skills", "training_skills", "notebooklm_skills",
    "board_skills", "coding_skills", "nexus_skills",
    "experiment_skills", "agent_state_skills",
]
