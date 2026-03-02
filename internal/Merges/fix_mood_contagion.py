import re

with open('engine/mcp/cosysim_server.py', 'r', encoding='utf-8') as f:
    code = f.read()

pattern = r'    """\n    try:\n\n        target_ids: List\[str\] = \((.*?)\n    except Exception as exc:\n        return json\.dumps\(\{"ok": False, "error": str\(exc\)\}\)'

replacement = r'''    """
    from engine.mcp.tools.interaction_tools import trigger_mood_contagion_impl
    
    # We serialize the Pydantic model returned by trigger_mood_contagion_impl
    return trigger_mood_contagion_impl(
        scene_id,
        initiator_id,
        emotion,
        intensity=intensity,
        target_ids_json=target_ids_json,
        affinity_factor=affinity_factor,
        framework=get_framework(),
        registry=get_character_registry(),
        scene_state_manager=get_scene_state_manager()
    ).model_dump_json(indent=2)'''

new_code = re.sub(pattern, replacement, code, flags=re.DOTALL)

with open('engine/mcp/cosysim_server.py', 'w', encoding='utf-8') as f:
    f.write(new_code)

print("Replaced mood_contagion." if new_code != code else "Failed to replace mood_contagion.")
