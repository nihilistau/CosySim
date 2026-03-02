with open('engine/mcp/tools/lounge_tools.py', 'r', encoding='utf-8') as f:
    code = f.read()

bad = """    return ServeLoungeDrinkResponse(
        ok=True,
        drink=cocktail["name"],
        narrative=f"Viktor serves '{cocktail['name']}'. {cocktail.get('note', '')}
Effects queued (fires next turn): {effects_str}
Scene: {viktor_line}"
    )"""

good = """    return ServeLoungeDrinkResponse(
        ok=True,
        drink=cocktail["name"],
        narrative=f"Viktor serves '{cocktail['name']}'. {cocktail.get('note', '')}\nEffects queued (fires next turn): {effects_str}\nScene: {viktor_line}"
    )"""

new_code = code.replace(bad, good)

with open('engine/mcp/tools/lounge_tools.py', 'w', encoding='utf-8') as f:
    f.write(new_code)
