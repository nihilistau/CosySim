import re

with open('engine/mcp/cosysim_server.py', 'r', encoding='utf-8') as f:
    code = f.read()

pattern = r'    """\n    try:\n\n        manifest = get_skill_manifest\(\).get\(scene\)(.*?)\n    except Exception as e:\n        return f"Failed to get skills: \{e\}"'

replacement = r'''    """
    from engine.mcp.tools.scene_tools import get_my_skills_impl
    return get_my_skills_impl(scene, get_skill_manifest())'''

new_code = re.sub(pattern, replacement, code, flags=re.DOTALL)

with open('engine/mcp/cosysim_server.py', 'w', encoding='utf-8') as f:
    f.write(new_code)
