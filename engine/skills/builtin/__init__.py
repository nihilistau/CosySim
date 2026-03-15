"""engine.skills.builtin — Built-in skill packs"""
# Import all packs so their @skill decorators fire at import time
from . import comfyui_skills, memory_skills, character_skills, voice_skills, tts_skills, social_skills
from . import training_skills, notebooklm_skills
from . import board_skills, coding_skills, nexus_skills
from . import experiment_skills, agent_state_skills
from . import autonomy_skills
from . import homeassistant_skills
from . import anythingllm_skills, codespace_skills, inference_skills
from . import nlm_forge_skills, prompts_chat_skills
from . import profile_skills
from . import relationship_skills
from . import reputation_skills
from . import art_skills
from . import player_profile_skills
from . import npc_skills
from . import news_skills
from . import coder_skills
from . import cdp_skills
from . import google_account_skills
from . import debugger_skills
from . import recovery_skills
from . import lifecycle_skills
from . import workspace_skills
from . import orchestration_skills
from . import resilience_skills

__all__ = [
    "comfyui_skills", "memory_skills", "character_skills", "voice_skills",
    "tts_skills", "social_skills", "training_skills", "notebooklm_skills",
    "board_skills", "coding_skills", "nexus_skills",
    "experiment_skills", "agent_state_skills",
    "autonomy_skills",
    "homeassistant_skills",
    "anythingllm_skills", "codespace_skills", "inference_skills",
    "nlm_forge_skills", "prompts_chat_skills",
    "profile_skills",
    "relationship_skills",
    "reputation_skills",
    "art_skills",
    "player_profile_skills",
    "npc_skills",
    "news_skills",
    "coder_skills",
    "cdp_skills",
    "google_account_skills",
    "debugger_skills",
    "recovery_skills",
    "lifecycle_skills",
    "workspace_skills",
    "orchestration_skills",
    "resilience_skills",
]
