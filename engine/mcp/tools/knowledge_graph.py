"""MCP tool domain: knowledge_graph.

Thin wrappers that delegate to *_tools.py implementations.
Apply @mcp_tool for unified error handling and serialisation.
"""
from __future__ import annotations

import json
import logging
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional

from engine.paths import ROOT as _root
if str(_root) not in sys.path:
    sys.path.insert(0, str(_root))

from engine.mcp.decorators import mcp_tool
from engine.mcp._lazy import _get_db, _get_rag, _get_config

logger = logging.getLogger(__name__)

# ──── KNOWLEDGE_GRAPH TOOLS ──────────────────────────────────────────────


@mcp_tool
def knowledge_graph_build() -> str:
    """Build the knowledge graph from Nexus entries — extracts topics, edges, gaps, clusters."""
    try:
        from engine.nexus.knowledge_graph import get_knowledge_graph
        from dataclasses import asdict
        snap = get_knowledge_graph().build()
        return json.dumps({
            "topic_count": snap.topic_count,
            "edge_count": snap.edge_count,
            "gap_count": snap.gap_count,
            "top_topics": snap.top_topics[:15],
            "gaps": snap.gaps[:10],
            "clusters": snap.clusters[:5],
        }, default=str)
    except Exception as e:
        return json.dumps({"error": str(e)})


@mcp_tool
def knowledge_graph_gaps() -> str:
    """Detect knowledge gaps — topics with few entries that neighbor strong topics."""
    try:
        from engine.nexus.knowledge_graph import get_knowledge_graph
        from dataclasses import asdict
        gaps = get_knowledge_graph().detect_gaps()
        return json.dumps([asdict(g) for g in gaps], default=str)
    except Exception as e:
        return json.dumps({"error": str(e)})


@mcp_tool
def knowledge_graph_clusters() -> str:
    """Get topic clusters from the knowledge graph."""
    try:
        from engine.nexus.knowledge_graph import get_knowledge_graph
        return json.dumps(get_knowledge_graph().cluster_topics(), default=str)
    except Exception as e:
        return json.dumps({"error": str(e)})


@mcp_tool
def knowledge_graph_search(query: str) -> str:
    """Search topics in the knowledge graph by name."""
    try:
        from engine.nexus.knowledge_graph import get_knowledge_graph
        return json.dumps(get_knowledge_graph().search_topics(query), default=str)
    except Exception as e:
        return json.dumps({"error": str(e)})


@mcp_tool
def knowledge_graph_research_tasks() -> str:
    """Auto-create research tasks for knowledge gaps."""
    try:
        from engine.nexus.knowledge_graph import get_knowledge_graph
        return json.dumps(get_knowledge_graph().create_research_tasks(), default=str)
    except Exception as e:
        return json.dumps({"error": str(e)})
