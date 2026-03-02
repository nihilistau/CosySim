with open('engine/mcp/cosysim_server.py', 'r', encoding='utf-8') as f:
    lines = f.readlines()

new_lines = []
in_func = False
skip_try = False

for line in lines:
    if line.startswith("def intercept_and_enhance("):
        in_func = True
        new_lines.append(line)
    elif in_func and line.strip() == "try:":
        skip_try = True
        new_lines.append("    from engine.mcp.tools.dialog_tools import intercept_and_enhance_impl\n")
        new_lines.append("    return intercept_and_enhance_impl(original_message, instruction, get_virtual_agent_manager()).model_dump_json(indent=2)\n")
    elif in_func and skip_try:
        if "return f\"Enhancement failed" in line:
            in_func = False
            skip_try = False
    else:
        new_lines.append(line)

with open('engine/mcp/cosysim_server.py', 'w', encoding='utf-8') as f:
    f.writelines(new_lines)
