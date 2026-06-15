"""Game pillar skill packs — world, city, boards, missions, NPCs, etc.

These skill files live in ``engine/skills/builtin/`` (parent directory) and
are re-exported here for pillar-aware imports.  Direct imports from the
parent continue to work unchanged.
"""
# Re-export game-pillar skill modules from the parent package.
# This allows ``from engine.skills.builtin.game import world_skills``.
from engine.skills.builtin import (
    art_skills,
    board_skills,
    character_skills,
    city_skills,
    comfyui_skills,
    crew_skills,
    hacking_skills,
    inventory_skills,
    living_world_skills,
    memory_skills,
    mission_skills,
    multiplayer_skills,
    neurochemistry_skills,
    npc_backstory_skills,
    npc_skills,
    onboarding_skills,
    oracle_skills,
    player_profile_skills,
    progression_skills,
    relationship_skills,
    reputation_skills,
    social_skills,
    story_skills,
    territory_skills,
    voice_skills,
    world_skills,
)

PILLAR = "game"
