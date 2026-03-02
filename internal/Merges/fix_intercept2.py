import re

with open('engine/mcp/cosysim_server.py', 'r', encoding='utf-8') as f:
    code = f.read()

pattern = r'    try:\n\n        mgr = get_virtual_agent_manager\(\)\n        request = InferenceRequest\(.*?    except Exception as e:\n        return f"Enhancement failed: \{e\}"'

replacement = r'''    from engine.mcp.tools.dialog_tools import intercept_and_enhance_impl
    return intercept_and_enhance_impl(original_message, instruction, get_virtual_agent_manager()).model_dump_json(indent=2)'''

new_code = re.sub(pattern, replacement, code, flags=re.DOTALL)

with open('engine/mcp/cosysim_server.py', 'w', encoding='utf-8') as f:
    f.write(new_code)
