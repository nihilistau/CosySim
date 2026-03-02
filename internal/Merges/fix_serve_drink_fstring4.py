import re
with open('engine/mcp/tools/lounge_tools.py', 'r', encoding='utf-8') as f:
    code = f.read()

pattern = r'narrative=f"Viktor serves \'.*?\n.*?\n.*?"\n    \)'
# wait, if it's actual newlines...
code = re.sub(r'narrative=f"Viktor serves \'.*?Scene: \{viktor_line\}"\n    \)', r'narrative=f"Viktor serves \'{cocktail[\'name\']}\'. {cocktail.get(\'note\', \'\')}\nEffects queued (fires next turn): {effects_str}\nScene: {viktor_line}"\n    )', code, flags=re.DOTALL)

with open('engine/mcp/tools/lounge_tools.py', 'w', encoding='utf-8') as f:
    f.write(code)
