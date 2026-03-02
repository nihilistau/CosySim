from __future__ import annotations

import json
from typing import Any, Dict, List, Optional
from pydantic import BaseModel, Field

from engine.mcp.decorators import mcp_tool, ToolExecutionError


@mcp_tool
def knowledge_graph_build_impl() -> Dict[str, Any]:
    """Build the knowledge graph from Nexus entries — extracts topics, edges, gaps, clusters."""
    try:
        from engine.nexus.knowledge_graph import get_knowledge_graph

        snap = get_knowledge_graph().build()
        return {
            "topic_count": snap.topic_count,
            "edge_count": snap.edge_count,
            "gap_count": snap.gap_count,
            "top_topics": snap.top_topics[:15],
            "gaps": snap.gaps[:10],
            "clusters": snap.clusters[:5],
        }
    except ImportError:
        raise ToolExecutionError("Knowledge Graph module not available.")


@mcp_tool
def knowledge_graph_gaps_impl() -> List[Dict[str, Any]]:
    """Detect knowledge gaps — topics with few entries that neighbor strong topics."""
    try:
        from engine.nexus.knowledge_graph import get_knowledge_graph
        from dataclasses import asdict

        gaps = get_knowledge_graph().detect_gaps()
        return [asdict(g) for g in gaps]
    except ImportError:
        raise ToolExecutionError("Knowledge Graph module not available.")


@mcp_tool
def knowledge_graph_clusters_impl() -> List[Any]:
    """Get topic clusters from the knowledge graph."""
    try:
        from engine.nexus.knowledge_graph import get_knowledge_graph

        return get_knowledge_graph().cluster_topics()
    except ImportError:
        raise ToolExecutionError("Knowledge Graph module not available.")


@mcp_tool
def knowledge_graph_search_impl(query: str) -> List[Any]:
    """Search topics in the knowledge graph by name."""
    try:
        from engine.nexus.knowledge_graph import get_knowledge_graph

        return get_knowledge_graph().search_topics(query)
    except ImportError:
        raise ToolExecutionError("Knowledge Graph module not available.")


@mcp_tool
def knowledge_graph_research_tasks_impl() -> List[Dict[str, Any]]:
    """Auto-create research tasks for knowledge gaps."""
    try:
        from engine.nexus.knowledge_graph import get_knowledge_graph

        return get_knowledge_graph().create_research_tasks()
    except ImportError:
        raise ToolExecutionError("Knowledge Graph module not available.")
