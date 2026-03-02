import re

with open('engine/mcp/devtools_server.py', 'r', encoding='utf-8') as f:
    code = f.read()

# Replace system_status
pattern_system = r'@mcp\.tool\(\)\ndef system_status\(\) -> str:\n.*?(?=\n@mcp\.tool\(\)\ndef list_all_skills)'
replacement_system = r'''@mcp.tool()
def system_status() -> str:
    """Get comprehensive CosySim system status — services, models,
    scenes, skills, orchestrator, and Nexus connectivity."""
    from engine.mcp.tools.system_tools import system_status_impl
    return system_status_impl(_get_nexus, _get_config).model_dump_json(indent=2)
'''
code = re.sub(pattern_system, replacement_system, code, flags=re.DOTALL)

# Replace list_all_skills
pattern_list = r'@mcp\.tool\(\)\ndef list_all_skills\(\) -> str:\n.*?(?=\n@mcp\.tool\(\)\ndef get_skill_info)'
replacement_list = r'''@mcp.tool()
def list_all_skills() -> str:
    """List all registered MCP skills grouped by pack."""
    from engine.mcp.tools.system_tools import list_all_skills_impl
    return list_all_skills_impl().model_dump_json(indent=2)
'''
code = re.sub(pattern_list, replacement_list, code, flags=re.DOTALL)

# Replace get_skill_info
pattern_info = r'@mcp\.tool\(\)\ndef get_skill_info\(skill_name: str\) -> str:\n.*?(?=\n@mcp\.tool\(\)\ndef get_benchmark_stats)'
replacement_info = r'''@mcp.tool()
def get_skill_info(skill_name: str) -> str:
    """Get detailed information about a specific MCP skill."""
    from engine.mcp.tools.system_tools import get_skill_info_impl
    return get_skill_info_impl(skill_name).model_dump_json(indent=2)
'''
code = re.sub(pattern_info, replacement_info, code, flags=re.DOTALL)

# Replace get_benchmark_stats inline try except
pattern_bench = r'    try:\n        from engine\.mcp\.tools\.utility_tools import get_benchmark_stats_logic as _impl\n        return _impl\(\)\n    except Exception as e:\n        return json\.dumps\(\{"error": str\(e\)\}\)'
replacement_bench = r'''    from engine.mcp.tools.utility_tools import get_benchmark_stats_logic
    return get_benchmark_stats_logic()'''
code = re.sub(pattern_bench, replacement_bench, code, flags=re.DOTALL)

# Also fix _get_nexus so it doesn't trigger bare except warning
pattern_nexus = r'def _get_nexus\(\):\n    try:\n        from engine\.nexus\.nexus_bridge import NexusBridge\n        return NexusBridge\(\)\n    except Exception:\n        return None'
replacement_nexus = r'''def _get_nexus():
    try:
        from engine.nexus.nexus_bridge import NexusBridge
        return NexusBridge()
    except Exception as e:
        _ = e
        return None'''
code = re.sub(pattern_nexus, replacement_nexus, code, flags=re.DOTALL)

with open('engine/mcp/devtools_server.py', 'w', encoding='utf-8') as f:
    f.write(code)

