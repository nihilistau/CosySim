with open('engine/mcp/cosysim_server.py', 'r', encoding='utf-8') as f:
    lines = f.readlines()

new_lines = []
in_func = False
skip_try = False

for line in lines:
    if line.startswith("def get_all_tools_for_scene("):
        in_func = True
        new_lines.append(line)
    elif in_func and line.strip() == "try:":
        skip_try = True
        new_lines.append("    from engine.mcp.tools.scene_tools import get_all_tools_for_scene_impl\n")
        new_lines.append("    return get_all_tools_for_scene_impl(scene_id).model_dump_json(indent=2)\n")
    elif in_func and skip_try:
        if line.strip() == "return f\"Error fetching tools: {e}\"":
            in_func = False
            skip_try = False
    else:
        new_lines.append(line)

with open('engine/mcp/cosysim_server.py', 'w', encoding='utf-8') as f:
    f.writelines(new_lines)
