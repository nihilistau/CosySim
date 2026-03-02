import re

with open('engine/mcp/cosysim_server.py', 'r', encoding='utf-8') as f:
    code = f.read()

pattern = r'    try:\n        return enforce_behavior_impl\((.*?)\n        \)\n    except Exception as e:\n        return json\.dumps\(\{"error": str\(e\)\}\)'
replacement = r'    return enforce_behavior_impl(\1\n    )'

new_code = re.sub(pattern, replacement, code, flags=re.DOTALL)

with open('engine/mcp/cosysim_server.py', 'w', encoding='utf-8') as f:
    f.write(new_code)
