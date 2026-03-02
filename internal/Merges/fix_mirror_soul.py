import re

with open('engine/mcp/cosysim_server.py', 'r', encoding='utf-8') as f:
    code = f.read()

pattern = r'    """\n    try:\n\n        duration_turns = max\(1, min\(6, duration_turns\)\)(.*?)\n    except Exception as exc:\n        return json\.dumps\(\{"ok": False, "error": str\(exc\)\}\)'

replacement = r'''    """
    from engine.mcp.tools.interaction_tools import mirror_soul_impl
    
    return mirror_soul_impl(
        character_id,
        target_id,
        duration_turns=duration_turns,
        scene_id=scene_id,
        registry=get_character_registry(),
        dialog_system=get_dialog_system(),
        scene_state_manager=get_scene_state_manager(),
        framework=get_framework()
    ).model_dump_json(indent=2)'''

new_code = re.sub(pattern, replacement, code, flags=re.DOTALL)

with open('engine/mcp/cosysim_server.py', 'w', encoding='utf-8') as f:
    f.write(new_code)

print("Replaced mirror_soul." if new_code != code else "Failed to replace mirror_soul.")
