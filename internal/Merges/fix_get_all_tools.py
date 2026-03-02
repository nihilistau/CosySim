import re

with open('engine/mcp/cosysim_server.py', 'r', encoding='utf-8') as f:
    code = f.read()

pattern = r'    try:\n        bedroom_tools = \[(.*?)\n    except Exception as e:\n        return f"Error fetching tools: \{e\}"'

replacement = r'''    from engine.mcp.tools.scene_tools import get_all_tools_for_scene_impl
    return get_all_tools_for_scene_impl(scene_id).model_dump_json(indent=2)'''

new_code = re.sub(pattern, replacement, code, flags=re.DOTALL)

with open('engine/mcp/cosysim_server.py', 'w', encoding='utf-8') as f:
    f.write(new_code)
