import re
import json


def process_file():
    with open("engine/mcp/cosysim_server.py", "r", encoding="utf-8") as f:
        content = f.read()

    # resolve_random_scene_event
    pattern = r'@mcp\.tool\(\)\ndef resolve_random_scene_event[\s\S]*?return json\.dumps\(\{"error": str\(e\)\}\)'
    new_rre = '''@mcp.tool()
def resolve_random_scene_event(scene_id: str = "bedroom") -> str:
    """
    Generate a random scene event to keep things fresh and unpredictable.
    Call this when the scene feels stale or to inject spontaneity.

    Returns an event description and any stat effects — ready to use.
    """
    from engine.mcp.tools.scene_tools import resolve_random_scene_event_impl
    return resolve_random_scene_event_impl(scene_id, get_scene_state_manager())'''
    content = re.sub(pattern, new_rre, content)

    with open("engine/mcp/cosysim_server.py", "w", encoding="utf-8") as f:
        f.write(content)


process_file()
