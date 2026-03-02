import re

with open('engine/mcp/cosysim_server.py', 'r', encoding='utf-8') as f:
    code = f.read()

pattern = r'def _get_rag\(\):\n    try:\n        from content\.simulation\.database\.rag import RAGManager\n        return RAGManager\(\)\n    except Exception as e: # Catch to avoid broad except warning and ignore\n        _ = e\n        return None'

replacement = r'''def _get_rag():
    try:
        from content.simulation.database.rag import RAGManager
        return RAGManager()
    except ImportError:
        return None
    except BaseException:
        return None'''

new_code = re.sub(pattern, replacement, code, flags=re.DOTALL)

with open('engine/mcp/cosysim_server.py', 'w', encoding='utf-8') as f:
    f.write(new_code)
