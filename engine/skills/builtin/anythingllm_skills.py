"""
AnythingLLM Skills — @skill-decorated functions for agent interaction
with AnythingLLM instances (phone + laptop).

Agents can manage workspaces, chat, sync knowledge with Nexus,
and upload documents via these skills.
"""
from __future__ import annotations

import json
import logging
from typing import Optional

from engine.skills.skill import skill

logger = logging.getLogger(__name__)


def _allm() -> "AnythingLLMClient":
    """Lazy import to avoid circular dependencies."""
    from engine.integrations.anythingllm import get_anythingllm_client
    return get_anythingllm_client()


# ── Connection ──────────────────────────────────────────────────────────


@skill(
    pack="anythingllm",
    description="Connect to all AnythingLLM instances and verify connectivity",
    category="system",
    tags=["anythingllm", "connect"],
)
def allm_connect(instance: str = "") -> str:
    """Connect to AnythingLLM instance(s). Leave instance empty to connect all."""
    if instance:
        result = _allm().connect(instance=instance)
    else:
        result = _allm().connect_all()
    return json.dumps(result)


@skill(
    pack="anythingllm",
    description="Get status of all AnythingLLM instances",
    category="system",
    tags=["anythingllm", "status"],
)
def allm_status() -> str:
    """Check status and stats of all AnythingLLM instances."""
    return json.dumps(_allm().status())


@skill(
    pack="anythingllm",
    description="List all configured AnythingLLM instances",
    category="system",
    tags=["anythingllm", "instances"],
)
def allm_list_instances() -> str:
    """List configured AnythingLLM instances with connection status."""
    return json.dumps(_allm().list_instances())


# ── Workspaces ──────────────────────────────────────────────────────────


@skill(
    pack="anythingllm",
    description="List workspaces on an AnythingLLM instance",
    category="system",
    tags=["anythingllm", "workspace"],
)
def allm_list_workspaces(instance: str = "") -> str:
    """List all workspaces. Specify instance name or use default."""
    inst = instance or None
    workspaces = _allm().list_workspaces(instance=inst)
    return json.dumps(workspaces)


@skill(
    pack="anythingllm",
    description="Create a new workspace on an AnythingLLM instance",
    category="system",
    tags=["anythingllm", "workspace", "create"],
)
def allm_create_workspace(name: str, instance: str = "") -> str:
    """Create a workspace with the given name."""
    inst = instance or None
    result = _allm().create_workspace(name, instance=inst)
    return json.dumps(result)


# ── Chat ────────────────────────────────────────────────────────────────


@skill(
    pack="anythingllm",
    description="Chat with an AnythingLLM workspace (RAG-enhanced)",
    category="communication",
    tags=["anythingllm", "chat", "rag"],
)
def allm_chat(workspace: str, message: str, mode: str = "chat", instance: str = "") -> str:
    """Send a message to an AnythingLLM workspace. Mode: 'chat' or 'query'."""
    inst = instance or None
    result = _allm().chat(workspace, message, mode=mode, instance=inst)
    text = result.get("textResponse", result.get("text", json.dumps(result)))
    return text if isinstance(text, str) else json.dumps(text)


@skill(
    pack="anythingllm",
    description="Get chat history from an AnythingLLM workspace",
    category="memory",
    tags=["anythingllm", "history"],
)
def allm_chat_history(workspace: str, instance: str = "") -> str:
    """Retrieve chat history for a workspace."""
    inst = instance or None
    history = _allm().get_chat_history(workspace, instance=inst)
    return json.dumps(history[:20])  # Last 20 messages


# ── Knowledge Sync ──────────────────────────────────────────────────────


@skill(
    pack="anythingllm",
    description="Sync AnythingLLM workspace chat history TO Nexus as Q&A pairs",
    category="memory",
    tags=["anythingllm", "nexus", "sync"],
)
def allm_sync_to_nexus(workspace: str, instance: str = "") -> str:
    """Export workspace Q&A pairs to Nexus knowledge base."""
    inst = instance or None
    result = _allm().sync_to_nexus(workspace, instance=inst)
    return json.dumps(result)


@skill(
    pack="anythingllm",
    description="Push Nexus knowledge INTO an AnythingLLM workspace for RAG",
    category="memory",
    tags=["anythingllm", "nexus", "sync"],
)
def allm_sync_from_nexus(
    workspace: str, query: str = "*", limit: int = 50, instance: str = "",
) -> str:
    """Upload Nexus entries as documents to an AnythingLLM workspace."""
    inst = instance or None
    result = _allm().sync_from_nexus(workspace, query=query, limit=limit, instance=inst)
    return json.dumps(result)


# ── Documents ───────────────────────────────────────────────────────────


@skill(
    pack="anythingllm",
    description="Upload text content to an AnythingLLM workspace",
    category="memory",
    tags=["anythingllm", "document", "upload"],
)
def allm_upload_document(
    workspace: str, title: str, content: str, instance: str = "",
) -> str:
    """Upload text as a document to an AnythingLLM workspace."""
    inst = instance or None
    result = _allm().upload_document(workspace, title, content, instance=inst)
    return json.dumps(result)
