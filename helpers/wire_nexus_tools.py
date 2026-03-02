import re
import os

filepath = "engine/mcp/devtools_server.py"

with open(filepath, "r", encoding="utf-8") as f:
    code = f.read()

# Add imports for nexus tools if not present
if "from engine.mcp.tools.nexus_tools import" not in code:
    imports = """from engine.mcp.tools.nexus_tools import (
    nexus_search_impl, nexus_ask_impl, nexus_add_impl, nexus_add_qa_impl,
    nexus_get_rules_impl, nexus_store_prompt_impl, nexus_get_prompts_impl,
    nexus_research_impl, nexus_converse_impl, nexus_finish_research_impl,
    nexus_import_youtube_impl, nexus_log_session_impl, nexus_status_impl,
    nexus_list_plugins_impl, nexus_remember_impl, nexus_recall_impl,
    nexus_memory_context_impl, nexus_distill_impl, nexus_export_session_impl,
    nexus_maintain_impl, nexus_smart_query_impl, nexus_router_stats_impl,
    nexus_quality_report_impl
)
"""
    # Insert after fastmcp import
    code = re.sub(r"(from fastmcp import FastMCP\n)", r"\1" + imports, code)

# Define replacements
replacements = {
    r"(def nexus_search\(query: str, limit: int = 10\) -> str:).*?(?=\n@mcp\.tool|\n# |\Z)": r"\1\n    return nexus_search_impl(query=query, limit=limit, nexus_getter=_get_nexus)\n",
    r'(def nexus_ask\(question: str, depth: str = "auto", category: str = ""\) -> str:).*?(?=\n@mcp\.tool|\n# |\Z)': r"\1\n    return nexus_ask_impl(question=question, depth=depth, category=category, nexus_getter=_get_nexus)\n",
    r'(def nexus_add\(title: str, content: str, content_type: str = "note",\s+category: str = "", tags: str = ""\) -> str:).*?(?=\n@mcp\.tool|\n# |\Z)': r"\1\n    return nexus_add_impl(title=title, content=content, content_type=content_type, category=category, tags=tags, nexus_getter=_get_nexus)\n",
    r'(def nexus_add_qa\(question: str, answer: str, category: str = "",\s+tags: str = ""\) -> str:).*?(?=\n@mcp\.tool|\n# |\Z)': r"\1\n    return nexus_add_qa_impl(question=question, answer=answer, category=category, tags=tags, nexus_getter=_get_nexus)\n",
    r'(def nexus_get_rules\(scope: str = "", rule_type: str = ""\) -> str:).*?(?=\n@mcp\.tool|\n# |\Z)': r"\1\n    return nexus_get_rules_impl(scope=scope, rule_type=rule_type, nexus_getter=_get_nexus)\n",
    r'(def nexus_store_prompt\(name: str, content: str, category: str = "",\s+version: str = ""\) -> str:).*?(?=\n@mcp\.tool|\n# |\Z)': r"\1\n    return nexus_store_prompt_impl(name=name, content=content, category=category, version=version, nexus_getter=_get_nexus)\n",
    r'(def nexus_get_prompts\(category: str = "", name: str = ""\) -> str:).*?(?=\n@mcp\.tool|\n# |\Z)': r"\1\n    return nexus_get_prompts_impl(category=category, name=name, nexus_getter=_get_nexus)\n",
    r"(def nexus_research\(question: str\) -> str:).*?(?=\n@mcp\.tool|\n# |\Z)": r"\1\n    return nexus_research_impl(question=question, nexus_getter=_get_nexus)\n",
    r"(def nexus_converse\(research_id: str, message: str\) -> str:).*?(?=\n@mcp\.tool|\n# |\Z)": r"\1\n    return nexus_converse_impl(research_id=research_id, message=message, nexus_getter=_get_nexus)\n",
    r"(def nexus_finish_research\(research_id: str\) -> str:).*?(?=\n@mcp\.tool|\n# |\Z)": r"\1\n    return nexus_finish_research_impl(research_id=research_id, nexus_getter=_get_nexus)\n",
    r'(def nexus_import_youtube\(url: str, category: str = "", tags: str = ""\) -> str:).*?(?=\n@mcp\.tool|\n# |\Z)': r"\1\n    return nexus_import_youtube_impl(url=url, category=category, tags=tags, nexus_getter=_get_nexus)\n",
    r'(def nexus_log_session\(project: str = "CosySim", repo: str = "",\s+branch: str = ""\) -> str:).*?(?=\n@mcp\.tool|\n# |\Z)': r"\1\n    return nexus_log_session_impl(project=project, repo=repo, branch=branch, nexus_getter=_get_nexus)\n",
    r"(def nexus_status\(\) -> str:).*?(?=\n@mcp\.tool|\n# |\Z)": r"\1\n    return nexus_status_impl(nexus_getter=_get_nexus)\n",
    r'(def nexus_list_plugins\(scope: str = ""\) -> str:).*?(?=\n@mcp\.tool|\n# |\Z)': r"\1\n    return nexus_list_plugins_impl(scope=scope, nexus_getter=_get_nexus)\n",
    r'(def nexus_remember\(content: str, agent_id: str = "copilot",\s+memory_type: str = "observation", importance: float = 0\.5\) -> str:).*?(?=\n@mcp\.tool|\n# |\Z)': r"\1\n    return nexus_remember_impl(content=content, agent_id=agent_id, memory_type=memory_type, importance=importance)\n",
    r'(def nexus_recall\(query: str, agent_id: str = "copilot", limit: int = 5\) -> str:).*?(?=\n@mcp\.tool|\n# |\Z)': r"\1\n    return nexus_recall_impl(query=query, agent_id=agent_id, limit=limit)\n",
    r'(def nexus_memory_context\(agent_id: str = "copilot", max_tokens: int = 500\) -> str:).*?(?=\n@mcp\.tool|\n# |\Z)': r"\1\n    return nexus_memory_context_impl(agent_id=agent_id, max_tokens=max_tokens)\n",
    r'(def nexus_distill\(action: str = "stats"\) -> str:).*?(?=\n@mcp\.tool|\n# |\Z)': r"\1\n    return nexus_distill_impl(action=action)\n",
    r"(def nexus_export_session\(\) -> str:).*?(?=\n@mcp\.tool|\n# |\Z)": r"\1\n    return nexus_export_session_impl()\n",
    r'(def nexus_maintain\(action: str = "health"\) -> str:).*?(?=\n@mcp\.tool|\n# |\Z)': r"\1\n    return nexus_maintain_impl(action=action)\n",
    r'(def nexus_smart_query\(question: str, min_confidence: float = 0\.3,\s+use_llm: bool = True, category: str = ""\) -> str:).*?(?=\n@mcp\.tool|\n# |\Z)': r"\1\n    return nexus_smart_query_impl(question=question, min_confidence=min_confidence, use_llm=use_llm, category=category)\n",
    r"(def nexus_router_stats\(\) -> str:).*?(?=\n@mcp\.tool|\n# |\Z)": r"\1\n    return nexus_router_stats_impl()\n",
    r"(def nexus_quality_report\(\) -> str:).*?(?=\n@mcp\.tool|\n# |\Z)": r"\1\n    return nexus_quality_report_impl()\n",
}

for pattern, replacement in replacements.items():
    code = re.sub(pattern, replacement, code, flags=re.DOTALL)

with open(filepath, "w", encoding="utf-8") as f:
    f.write(code)

print("Rewrote devtools_server.py nexus functions")
