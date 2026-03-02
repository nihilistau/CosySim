import re

with open('engine/mcp/cosysim_server.py', 'r', encoding='utf-8') as f:
    code = f.read()

pattern = r'    """\n    try:\n\n        ds = get_dialog_system\(\)(.*?)\n    except Exception as exc:\n        return json\.dumps\(\{"ok": False, "error": str\(exc\)\}\)'

replacement = r'''    """
    from engine.mcp.tools.memory_tools import time_echo as time_echo_impl
    
    return time_echo_impl(
        character_id,
        echo_query,
        rag=_get_rag(),
        dialog_system=get_dialog_system(),
        ssm=get_scene_state_manager(),
        fw=get_framework(),
        emotional_tone=emotional_tone,
        scene_id=scene_id
    ).model_dump_json(indent=2)'''

new_code = re.sub(pattern, replacement, code, flags=re.DOTALL)

with open('engine/mcp/cosysim_server.py', 'w', encoding='utf-8') as f:
    f.write(new_code)

print("Replaced time_echo." if new_code != code else "Failed to replace time_echo.")
