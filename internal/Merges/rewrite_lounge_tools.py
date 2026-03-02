import re

with open("engine/mcp/cosysim_server.py", "r", encoding="utf-8") as f:
    content = f.read()

# Add import at the top
import_block = """from engine.mcp.tools.lounge_tools import (
    start_lounge_performance_impl,
    get_lounge_menu_impl,
    get_lounge_state_impl,
    reveal_lounge_secret_impl,
    trigger_lounge_event_impl,
    lounge_heat_tick_impl,
)
"""

if "from engine.mcp.tools.lounge_tools import" not in content:
    content = content.replace(
        "from engine.mcp.tools.interaction_tools import (",
        import_block + "from engine.mcp.tools.interaction_tools import ("
    )

replacement_block = """@mcp.tool()
def start_lounge_performance(
    song_id: str = "",
    lola_mood: int = 0,
    scene_id: str = "lounge",
) -> str:
    \"\"\"
    Start a Lola Voss stage performance.

    If song_id is blank, picks the best song for the current mood score.
    Starts an MCPTimer for the song duration, sets Lola's directive, and
    fires mood_contagion to the guest when the song finishes.

    Returns: song name + duration + mood directive set.
    \"\"\"
    return start_lounge_performance_impl(song_id, lola_mood, scene_id)


@mcp.tool()
def get_lounge_menu(
    trust_level: int = 0,
    scene_id: str = "lounge",
) -> str:
    \"\"\"
    Return the cocktail menu available at the given trust level.

    Locked items are shown greyed out to preserve immersion.

    Returns: JSON list of available cocktails with trust requirements.
    \"\"\"
    return get_lounge_menu_impl(trust_level, scene_id)


@mcp.tool()
def get_lounge_state(scene_id: str = "lounge") -> str:
    \"\"\"
    Return the full Velvet Lounge MCP state as JSON.

    Includes: trust, heat, active song, atmosphere, active rules,
    narrative entries, character moods, and pending consequences.

    Returns: JSON state snapshot.
    \"\"\"
    return get_lounge_state_impl(scene_id)


@mcp.tool()
def reveal_lounge_secret(
    character_id: str,
    secret_id: str = "",
    trust_level: int = 0,
    scene_id: str = "lounge",
) -> str:
    \"\"\"
    Reveal the next (or specified) lounge secret for a character.

    Gates on trust_level. If secret_id is blank, the next un-revealed
    secret for the character is chosen.  Applies effect stats as
    consequences and injects the secret into the character's next reply.

    Returns: secret title + content + effects applied.
    \"\"\"
    return reveal_lounge_secret_impl(character_id, secret_id, trust_level, scene_id)


@mcp.tool()
def trigger_lounge_event(
    event_id: str = "",
    scene_id: str = "lounge",
) -> str:
    \"\"\"
    Fire a named lounge random event, or pick one at random if event_id is blank.

    Applies any associated stat effects, Viktor→Lola cross-scene message,
    and adds narrative entry.

    Returns: event text + effects applied.
    \"\"\"
    return trigger_lounge_event_impl(event_id, scene_id)


@mcp.tool()
def lounge_heat_tick(
    delta: int = 5,
    scene_id: str = "lounge",
) -> str:
    \"\"\"
    Advance (or reduce if delta < 0) the lounge heat meter.

    Heat affects: available actions, character directives, back-room access,
    and triggers warning/critical rules at thresholds 65 and 85.

    Returns: new heat level + any rules fired.
    \"\"\"
    return lounge_heat_tick_impl(delta, scene_id)"""


import re
# Matches from start_lounge_performance down to lounge_heat_tick end
pattern = re.compile(r'@mcp\.tool\(\)\ndef start_lounge_performance\(.*?def lounge_heat_tick\(.*?return json\.dumps\(\{"error": str\(e\)\}\)\n\n    except Exception as exc:\n        return f"lounge_heat_tick failed: \{exc\}"', re.DOTALL | re.MULTILINE)
# The actual exception in heat_tick is "lounge_heat_tick failed: {exc}"
pattern = re.compile(r'@mcp\.tool\(\)\ndef start_lounge_performance\(.*?def lounge_heat_tick\(.*?return f"lounge_heat_tick failed: \{exc\}"', re.DOTALL | re.MULTILINE)


content = pattern.sub(replacement_block, content)

with open("engine/mcp/cosysim_server.py", "w", encoding="utf-8") as f:
    f.write(content)

