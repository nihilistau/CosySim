import re

with open('engine/mcp/cosysim_server.py', 'r', encoding='utf-8') as f:
    code = f.read()

pattern = r'    """\n    try:\n\n        params = _json\.loads\(params_json\)(.*?)\n    except Exception as exc:\n        return json\.dumps\(\{"ok": False, "error": str\(exc\)\}\)'

replacement = r'''    """
    from engine.mcp.tools.interaction_tools import schedule_consequence_impl
    
    return schedule_consequence_impl(
        scene_id,
        character_id,
        consequence_type,
        params_json,
        trigger_after_turns=trigger_after_turns,
        description=description,
        created_by=created_by,
        framework=get_framework()
    ).model_dump_json(indent=2)'''

new_code = re.sub(pattern, replacement, code, flags=re.DOTALL)

with open('engine/mcp/cosysim_server.py', 'w', encoding='utf-8') as f:
    f.write(new_code)

print("Replaced schedule_consequence." if new_code != code else "Failed to replace schedule_consequence.")
