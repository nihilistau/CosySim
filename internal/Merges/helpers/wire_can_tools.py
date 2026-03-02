import re
import os

filepath = "engine/mcp/devtools_server.py"

with open(filepath, "r", encoding="utf-8") as f:
    code = f.read()

# Add imports for newly extracted tools
if "from engine.mcp.tools.copilot_tools import" not in code:
    imports = """from engine.mcp.tools.copilot_tools import (
    copilot_store_snippet_impl, copilot_store_discovery_impl, copilot_log_progress_impl,
    copilot_context_primer_impl, copilot_local_model_guide_impl, copilot_sync_config_impl,
    copilot_config_status_impl, copilot_list_instructions_impl, copilot_list_agents_impl
)
from engine.mcp.tools.agent_tools import (
    agent_create_task_impl, agent_update_task_impl, agent_complete_task_impl, agent_list_tasks_impl
)
from engine.mcp.tools.notebook_tools import (
    nlm_notebook_list_impl, nlm_notebook_seed_impl, nlm_notebook_rotate_impl
)
"""
    # Insert after fastmcp import
    code = re.sub(r"(from fastmcp import FastMCP\n)", r"\1" + imports, code)

# Define replacements
replacements = {
    # Copilot
    r'(def copilot_store_snippet\(title: str, code: str, language: str = "python",\s+tags: str = ""\) -> str:).*?(?=\n@mcp\.tool|\n# |\Z)': r"\1\n    return copilot_store_snippet_impl(title=title, code=code, language=language, tags=tags)\n",
    r'(def copilot_store_discovery\(title: str, finding: str,\s+category: str = "debugging"\) -> str:).*?(?=\n@mcp\.tool|\n# |\Z)': r"\1\n    return copilot_store_discovery_impl(title=title, finding=finding, category=category)\n",
    r'(def copilot_log_progress\(task: str, status: str = "completed", details: str = "",\s+tests_passed: int = 0, commit_sha: str = ""\) -> str:).*?(?=\n@mcp\.tool|\n# |\Z)': r"\1\n    return copilot_log_progress_impl(task=task, status=status, details=details, tests_passed=tests_passed, commit_sha=commit_sha)\n",
    r'(def copilot_context_primer\(project: str = "CosySim"\) -> str:).*?(?=\n@mcp\.tool|\n# |\Z)': r"\1\n    return copilot_context_primer_impl(project=project)\n",
    r'(def copilot_local_model_guide\(task_type: str = "general"\) -> str:).*?(?=\n@mcp\.tool|\n# |\Z)': r"\1\n    return copilot_local_model_guide_impl(task_type=task_type)\n",
    r"(def copilot_sync_config\(\) -> str:).*?(?=\n@mcp\.tool|\n# |\Z)": r"\1\n    return copilot_sync_config_impl()\n",
    r"(def copilot_config_status\(\) -> str:).*?(?=\n@mcp\.tool|\n# |\Z)": r"\1\n    return copilot_config_status_impl()\n",
    r"(def copilot_list_instructions\(\) -> str:).*?(?=\n@mcp\.tool|\n# |\Z)": r"\1\n    return copilot_list_instructions_impl()\n",
    r"(def copilot_list_agents\(\) -> str:).*?(?=\n@mcp\.tool|\n# |\Z)": r"\1\n    return copilot_list_agents_impl()\n",
    # Agent
    r'(def agent_create_task\(title: str, description: str = "", agent: str = "copilot",\s+priority: str = "normal", tags: str = ""\) -> str:).*?(?=\n@mcp\.tool|\n# |\Z)': r"\1\n    return agent_create_task_impl(title=title, description=description, agent=agent, priority=priority, tags=tags)\n",
    r"(def agent_update_task\(task_id: str, status: str\) -> str:).*?(?=\n@mcp\.tool|\n# |\Z)": r"\1\n    return agent_update_task_impl(task_id=task_id, status=status)\n",
    r'(def agent_complete_task\(task_id: str, summary: str = ""\) -> str:).*?(?=\n@mcp\.tool|\n# |\Z)': r"\1\n    return agent_complete_task_impl(task_id=task_id, summary=summary)\n",
    r'(def agent_list_tasks\(status: str = "", agent: str = "", limit: int = 20\) -> str:).*?(?=\n@mcp\.tool|\n# |\Z)': r"\1\n    return agent_list_tasks_impl(status=status, agent=agent, limit=limit)\n",
    # Notebook
    r"(def nlm_notebook_list\(\) -> str:).*?(?=\n@mcp\.tool|\n# |\Z)": r"\1\n    return nlm_notebook_list_impl()\n",
    r'(def nlm_notebook_seed\(slot_name: str = "cosysim-architecture", source_type: str = "docs"\) -> str:).*?(?=\n@mcp\.tool|\n# |\Z)': r"\1\n    return nlm_notebook_seed_impl(slot_name=slot_name, source_type=source_type)\n",
    r"(def nlm_notebook_rotate\(slot_name: str\) -> str:).*?(?=\n@mcp\.tool|\n# |\Z)": r"\1\n    return nlm_notebook_rotate_impl(slot_name=slot_name)\n",
}

for pattern, replacement in replacements.items():
    code = re.sub(pattern, replacement, code, flags=re.DOTALL)

with open(filepath, "w", encoding="utf-8") as f:
    f.write(code)

print("Rewrote devtools_server.py copilot/agent/notebook functions")
