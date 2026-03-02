import re

with open('engine/mcp/cosysim_server.py', 'r', encoding='utf-8') as f:
    code = f.read()

pattern = r'    """\n    try:\n\n        duration_turns = max\(1, min\(5, duration_turns\)\)(.*?)\n    except Exception as exc:\n        return json\.dumps\(\{"ok": False, "error": str\(exc\)\}\)'

replacement = r'''    """
    from engine.mcp.tools.interaction_tools import mood_whisper_impl
    
    return mood_whisper_impl(
        from_character_id,
        to_character_id,
        whisper_content,
        duration_turns=duration_turns,
        scene_id=scene_id,
        framework=get_framework(),
        dialog_system=get_dialog_system(),
        scene_state_manager=get_scene_state_manager()
    ).model_dump_json(indent=2)'''

new_code = re.sub(pattern, replacement, code, flags=re.DOTALL)

with open('engine/mcp/cosysim_server.py', 'w', encoding='utf-8') as f:
    f.write(new_code)

print("Replaced dream_whisper." if new_code != code else "Failed to replace dream_whisper.")
