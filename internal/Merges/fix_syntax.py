with open('engine/mcp/cosysim_server.py', 'r', encoding='utf-8') as f:
    code = f.read()

import re

# Find the broken try block inside character_remove_restriction
pattern = r'@mcp\.tool\(\)\ndef character_remove_restriction.*?except Exception as e:\n        return json\.dumps\(\{"error": str\(e\)\}\)'

replacement = """@mcp.tool()
def character_remove_restriction(character_id: str, restriction: str) -> str:
    \"\"\"
    Remove a named restriction from a character.

    Args:
        character_id: e.g. "aria"
        restriction:  Name of the restriction to remove
    \"\"\"
    from engine.mcp.tools.character_tools import character_remove_restriction_impl
    return character_remove_restriction_impl(character_id, restriction)"""

new_code = re.sub(pattern, replacement, code, flags=re.DOTALL)

with open('engine/mcp/cosysim_server.py', 'w', encoding='utf-8') as f:
    f.write(new_code)
