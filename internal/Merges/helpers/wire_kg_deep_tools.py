import re
import os

filepath = "engine/mcp/devtools_server.py"

with open(filepath, "r", encoding="utf-8") as f:
    code = f.read()

# Add imports for newly extracted tools
if "from engine.mcp.tools.kg_tools import" not in code:
    imports = """from engine.mcp.tools.kg_tools import (
    knowledge_graph_build_impl, knowledge_graph_gaps_impl, knowledge_graph_clusters_impl,
    knowledge_graph_search_impl, knowledge_graph_research_tasks_impl
)
from engine.mcp.tools.deep_storage_tools import (
    deep_storage_archive_impl, deep_storage_archive_all_impl, deep_storage_from_har_impl,
    deep_storage_retrieve_impl, deep_storage_list_impl, deep_storage_search_impl,
    deep_storage_chain_impl, deep_storage_stats_impl
)
"""
    # Insert after fastmcp import
    code = re.sub(r"(from fastmcp import FastMCP\n)", r"\1" + imports, code)

# Define replacements
replacements = {
    # Knowledge Graph
    r"(def knowledge_graph_build\(\) -> str:).*?(?=\n@mcp\.tool|\n# |\Z)": r"\1\n    return knowledge_graph_build_impl()\n",
    r"(def knowledge_graph_gaps\(\) -> str:).*?(?=\n@mcp\.tool|\n# |\Z)": r"\1\n    return knowledge_graph_gaps_impl()\n",
    r"(def knowledge_graph_clusters\(\) -> str:).*?(?=\n@mcp\.tool|\n# |\Z)": r"\1\n    return knowledge_graph_clusters_impl()\n",
    r"(def knowledge_graph_search\(query: str\) -> str:).*?(?=\n@mcp\.tool|\n# |\Z)": r"\1\n    return knowledge_graph_search_impl(query=query)\n",
    r"(def knowledge_graph_research_tasks\(\) -> str:).*?(?=\n@mcp\.tool|\n# |\Z)": r"\1\n    return knowledge_graph_research_tasks_impl()\n",
    # Deep Storage
    r"(def deep_storage_archive\(notebook_id: str\) -> str:).*?(?=\n@mcp\.tool|\n# |\Z)": r"\1\n    return deep_storage_archive_impl(notebook_id=notebook_id)\n",
    r"(def deep_storage_archive_all\(\) -> str:).*?(?=\n@mcp\.tool|\n# |\Z)": r"\1\n    return deep_storage_archive_all_impl()\n",
    r"(def deep_storage_from_har\(har_path: str\) -> str:).*?(?=\n@mcp\.tool|\n# |\Z)": r"\1\n    return deep_storage_from_har_impl(har_path=har_path)\n",
    r"(def deep_storage_retrieve\(notebook_id: str\) -> str:).*?(?=\n@mcp\.tool|\n# |\Z)": r"\1\n    return deep_storage_retrieve_impl(notebook_id=notebook_id)\n",
    r"(def deep_storage_list\(\) -> str:).*?(?=\n@mcp\.tool|\n# |\Z)": r"\1\n    return deep_storage_list_impl()\n",
    r"(def deep_storage_search\(query: str\) -> str:).*?(?=\n@mcp\.tool|\n# |\Z)": r"\1\n    return deep_storage_search_impl(query=query)\n",
    r"(def deep_storage_chain\(chain_id: str\) -> str:).*?(?=\n@mcp\.tool|\n# |\Z)": r"\1\n    return deep_storage_chain_impl(chain_id=chain_id)\n",
    r"(def deep_storage_stats\(\) -> str:).*?(?=\n@mcp\.tool|\n# |\Z)": r"\1\n    return deep_storage_stats_impl()\n",
}

for pattern, replacement in replacements.items():
    code = re.sub(pattern, replacement, code, flags=re.DOTALL)

with open(filepath, "w", encoding="utf-8") as f:
    f.write(code)

print("Rewrote devtools_server.py kg/deep_storage functions")
