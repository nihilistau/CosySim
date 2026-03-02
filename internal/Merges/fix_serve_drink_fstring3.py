with open('engine/mcp/tools/lounge_tools.py', 'r', encoding='utf-8') as f:
    lines = f.readlines()

new_lines = []
skip = False
for line in lines:
    if line.startswith("    return ServeLoungeDrinkResponse("):
        new_lines.append(line)
    elif line.startswith("        ok=True,"):
        new_lines.append(line)
    elif line.startswith("        drink=cocktail[\"name\"],"):
        new_lines.append(line)
    elif line.startswith("        narrative=f\"Viktor serves '"):
        new_lines.append("        narrative=f\"Viktor serves '{cocktail['name']}'. {cocktail.get('note', '')}\nEffects queued (fires next turn): {effects_str}\nScene: {viktor_line}\"\n    )\n")
        skip = True
    elif skip and (line.startswith("Effects queued") or line.startswith("Scene:") or line.strip() == ")"):
        continue
    else:
        new_lines.append(line)

with open('engine/mcp/tools/lounge_tools.py', 'w', encoding='utf-8') as f:
    f.writelines(new_lines)
