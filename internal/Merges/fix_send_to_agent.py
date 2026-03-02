import re

with open('engine/mcp/cosysim_server.py', 'r', encoding='utf-8') as f:
    code = f.read()

pattern = r'    """\n    try:\n\n        get_router\(\)\.send\(recipient_id, message, sender_id=sender_id\)\n        return f"Message sent to \{recipient_id\}\."\n    except Exception as e:\n        return f"Failed to send: \{e\}"'

replacement = r'''    """
    from engine.mcp.tools.conversation_tools import send_to_agent_impl
    return send_to_agent_impl(recipient_id, message, get_router(), sender_id=sender_id).model_dump_json()'''

new_code = re.sub(pattern, replacement, code, flags=re.DOTALL)

with open('engine/mcp/cosysim_server.py', 'w', encoding='utf-8') as f:
    f.write(new_code)
