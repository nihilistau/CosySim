import re

with open("engine/mcp/cosysim_server.py", "r", encoding="utf-8") as f:
    content = f.read()

# Add import at the top
import_block = """from engine.mcp.tools.interaction_tools import (
    perform_interaction_impl,
    list_available_interactions_impl,
    get_interaction_details_impl,
    start_timed_action_impl,
    poll_timed_action_impl,
    abort_timed_action_impl,
    list_active_timed_actions_impl,
)
"""

if "from engine.mcp.tools.interaction_tools import" not in content:
    content = content.replace(
        "from engine.mcp.tools.scene_tools import (",
        import_block + "from engine.mcp.tools.scene_tools import ("
    )

replacement_block = """@mcp.tool()
def perform_interaction(
    interaction_type: str,
    initiator_id: str,
    target_id: str,
    scene_id: str = "bedroom",
    subtype: str = "",
    intensity: int = 0,
) -> str:
    \"\"\"
    Perform one of the 6 core interaction types between two characters.

    BEDROOM interaction_types:
      cuddle    — physical closeness (subtypes: embrace, spoon, lap_sit, entangled)
      kiss      — kissing (subtypes: soft, neck, deep, trail, urgent)
      caress    — tactile touch (subtypes: hair, back, face, body)
      striptease — undressing performance (subtypes: tease_outer, slow_reveal, dance_strip, interactive_strip)
      intimate  — sexual encounter (subtypes: foreplay, oral, passionate, directed, afterglow)
      deep_talk — intimate conversation (subtypes: pillow_talk, dirty_talk, whisper, confession, fantasy_share)

    PHONE interaction_types:
      flirt_text | sext | voice_call | video_call | send_media | roleplay_text

    intensity: 0=auto-select based on stats, 1-5=force min intimacy level
    subtype: override auto-selection with a specific subtype id

    Returns the interaction result, narrative fragments, stat effects applied,
    and a timed action token if the interaction takes time.
    \"\"\"
    return perform_interaction_impl(
        interaction_type, initiator_id, target_id, scene_id, subtype, intensity
    )


@mcp.tool()
def list_available_interactions(character_id: str, scene_id: str = "bedroom") -> str:
    \"\"\"
    List all interaction types and their accessible subtypes for a character
    based on their current stats.  Use this before calling perform_interaction
    to know what's available without guessing.

    Returns a filtered list — only shows subtypes whose stat requirements are met.
    \"\"\"
    return list_available_interactions_impl(character_id, scene_id)


@mcp.tool()
def get_interaction_details(
    interaction_type: str,
    subtype: str = "",
    scene_id: str = "bedroom",
) -> str:
    \"\"\"
    Get detailed information about a specific interaction type/subtype —
    description, phases, sample narrative fragments, stat effects, requirements.

    Call this to understand what an interaction involves before using it,
    or to pick the right fragments for your narration.
    \"\"\"
    return get_interaction_details_impl(interaction_type, subtype, scene_id)


# ── TIMED ACTIONS ─────────────────────────────────────────────────────


@mcp.tool()
def start_timed_action(
    character_id: str,
    action_type: str,
    duration_secs: float = 30.0,
    description: str = "",
    phases: str = "",
) -> str:
    \"\"\"
    Start a long-form action that plays out over real time.
    Returns a token you can use to poll progress.

    Use for anything that should feel like it takes time:
    striptease, massage, sex, bath scene, dance, etc.

    phases: comma-separated phase labels e.g. 'beginning,building,peak,afterglow'
    duration_secs: how long the action takes (15-120 typical)
    \"\"\"
    return start_timed_action_impl(
        character_id, action_type, duration_secs, description, phases
    )


@mcp.tool()
def poll_timed_action(token: str) -> str:
    \"\"\"
    Check the progress of a running timed action.
    Returns phase name, progress (0.0-1.0), elapsed time, and completion status.

    Check this periodically to narrate an unfolding scene.  When complete=true
    the action has finished — emit the afterglow narrative.
    \"\"\"
    return poll_timed_action_impl(token)


@mcp.tool()
def abort_timed_action(token: str) -> str:
    \"\"\"Stop a timed action early (e.g. interrupted by Director or refused by character).\"\"\"
    return abort_timed_action_impl(token)


@mcp.tool()
def list_active_timed_actions(character_id: str = "") -> str:
    \"\"\"
    List all currently running timed actions.
    Pass character_id to filter to a specific character, or leave blank for all.
    \"\"\"
    return list_active_timed_actions_impl(character_id)"""


import re
# Matches from @mcp.tool() before perform_interaction down to the end of list_active_timed_actions
pattern = re.compile(r'@mcp\.tool\(\)\ndef perform_interaction\(.*?def list_active_timed_actions\(character_id: str = ""\) -> str:.*?return json\.dumps\(\{"error": str\(e\)\}\)', re.DOTALL | re.MULTILINE)

content = pattern.sub(replacement_block, content)

with open("engine/mcp/cosysim_server.py", "w", encoding="utf-8") as f:
    f.write(content)

