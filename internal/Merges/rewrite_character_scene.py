import re

with open("engine/mcp/cosysim_server.py", "r", encoding="utf-8") as f:
    content = f.read()

import_block = """from engine.mcp.tools.character_tools import (
    get_character_scene_stats_impl,
    update_character_scene_stats_impl,
    set_character_scene_stat_impl,
    reset_character_scene_stats_impl,
    check_character_consent_impl,
    get_character_agency_summary_impl,
)
"""

if "get_character_scene_stats_impl," not in content:
    content = content.replace(
        "from engine.mcp.tools.character_tools import (",
        import_block + "from engine.mcp.tools.character_tools import ("
    )

replacement_block = """@mcp.tool()
def get_character_scene_stats(character_id: str) -> str:
    \"\"\"
    Get the full extended emotional/physical stat vector for a character in the
    current scene.

    Stats (all 0-100): arousal, horniness, pleasure, happiness, anger, fear,
    drunkenness, tiredness, explicitness, openness, affection, dominance.

    Also returns 'emotional_state' — a human-readable description of how the
    character is feeling right now.  USE THIS to inform how they should behave.
    \"\"\"
    return get_character_scene_stats_impl(character_id)


@mcp.tool()
def update_character_scene_stats(character_id: str, stat_changes: str) -> str:
    \"\"\"
    Adjust a character's scene stats by delta values.  Pass a JSON string like:
    '{"arousal": 15, "happiness": -10, "openness": 5}'

    Stats clamp at 0-100.  Use positive values to increase, negative to decrease.
    Call this after interactions, events, emotional moments.
    \"\"\"
    return update_character_scene_stats_impl(character_id, stat_changes)


@mcp.tool()
def set_character_scene_stat(character_id: str, stat: str, value: float) -> str:
    \"\"\"
    Set a specific stat to an exact value (0-100).  Use when you need precision
    rather than a delta — e.g. resetting a stat at scene start.

    stat: arousal | horniness | pleasure | happiness | anger | fear |
          drunkenness | tiredness | explicitness | openness | affection | dominance
    \"\"\"
    return set_character_scene_stat_impl(character_id, stat, value)


@mcp.tool()
def reset_character_scene_stats(character_id: str) -> str:
    \"\"\"Reset all scene stats for a character back to defaults (scene reset / new character).\"\"\"
    return reset_character_scene_stats_impl(character_id)"""

content = re.sub(
    r'@mcp\.tool\(\)\ndef get_character_scene_stats\(.*?def reset_character_scene_stats\(character_id: str\) -> str:.*?return json\.dumps\(\{"error": str\(e\)\}\)',
    replacement_block,
    content,
    flags=re.DOTALL | re.MULTILINE
)


replacement_block_2 = """@mcp.tool()
def check_character_consent(character_id: str, action_type: str) -> str:
    \"\"\"
    Check whether a character would willingly perform or receive an action
    based on their current stats.

    Returns a WILL/RELUCTANT/REFUSE decision and the reasoning.
    Characters CAN and SHOULD refuse sometimes — it creates drama.
    They might also take initiative and suggest something the Director didn't.

    action_type examples: 'striptease', 'kiss', 'sex', 'oral', 'cuddle',
                          'dirty_talk', 'remove_top', 'remove_all'
    \"\"\"
    return check_character_consent_impl(character_id, action_type)


@mcp.tool()
def get_character_agency_summary(character_id: str) -> str:
    \"\"\"
    Get a full picture of a character's current agency — who they are RIGHT NOW.
    Includes emotional state, compliance level, what they most want, what they'd
    resist, and what they might spontaneously initiate.

    Use this to write authentic agent responses that feel real rather than always-compliant.
    \"\"\"
    return get_character_agency_summary_impl(character_id)"""

content = re.sub(
    r'@mcp\.tool\(\)\ndef check_character_consent\(.*?def get_character_agency_summary\(character_id: str\) -> str:.*?return json\.dumps\(\{"error": str\(e\)\}\)',
    replacement_block_2,
    content,
    flags=re.DOTALL | re.MULTILINE
)

with open("engine/mcp/cosysim_server.py", "w", encoding="utf-8") as f:
    f.write(content)

