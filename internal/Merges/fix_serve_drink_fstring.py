with open('engine/mcp/tools/lounge_tools.py', 'r', encoding='utf-8') as f:
    lines = f.readlines()

new_lines = []
for line in lines:
    if line.startswith("    narrative=f\"Viktor serves"):
        new_lines.append("    narrative=f\"Viktor serves '{cocktail['name']}'. {cocktail.get('note', '')}\nEffects queued (fires next turn): {effects_str}\nScene: {viktor_line}\"\n")
    elif "Effects queued" in line and "Scene: {viktor_line}" in line:
        pass # Skip these broken lines
    else:
        new_lines.append(line)

with open('engine/mcp/tools/lounge_tools.py', 'w', encoding='utf-8') as f:
    f.writelines(new_lines)
