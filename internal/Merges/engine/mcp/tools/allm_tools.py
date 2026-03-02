import json
import logging
from typing import Optional, Any

logger = logging.getLogger(__name__)


def allm_connect_impl(instance: str = "") -> str:
    """Connect to AnythingLLM instance(s). Leave empty for all."""
    try:
        from engine.integrations.anythingllm import get_anythingllm_client

        client = get_anythingllm_client()
        if instance:
            return json.dumps(client.connect(instance=instance), default=str)
        return json.dumps(client.connect_all(), default=str)
    except Exception as exc:
        return json.dumps({"error": str(exc)})


def allm_status_impl() -> str:
    """Get status of all AnythingLLM instances."""
    try:
        from engine.integrations.anythingllm import get_anythingllm_client

        return json.dumps(get_anythingllm_client().status(), default=str)
    except Exception as exc:
        return json.dumps({"error": str(exc)})


def allm_list_workspaces_impl(instance: str = "") -> str:
    """List workspaces on an AnythingLLM instance."""
    try:
        from engine.integrations.anythingllm import get_anythingllm_client

        return json.dumps(
            get_anythingllm_client().list_workspaces(instance=instance or None),
            default=str,
        )
    except Exception as exc:
        return json.dumps({"error": str(exc)})


def allm_chat_impl(
    workspace: str, message: str, mode: str = "chat", instance: str = ""
) -> str:
    """Chat with an AnythingLLM workspace."""
    try:
        from engine.integrations.anythingllm import get_anythingllm_client

        result = get_anythingllm_client().chat(
            workspace, message, mode=mode, instance=instance or None
        )
        return json.dumps(result, default=str)
    except Exception as exc:
        return json.dumps({"error": str(exc)})


def allm_sync_to_nexus_impl(workspace: str, instance: str = "") -> str:
    """Sync AnythingLLM workspace Q&A pairs to Nexus."""
    try:
        from engine.integrations.anythingllm import get_anythingllm_client

        return json.dumps(
            get_anythingllm_client().sync_to_nexus(
                workspace, instance=instance or None
            ),
            default=str,
        )
    except Exception as exc:
        return json.dumps({"error": str(exc)})


def allm_sync_from_nexus_impl(
    workspace: str, query: str = "*", limit: int = 50, instance: str = ""
) -> str:
    """Push Nexus knowledge into an AnythingLLM workspace for RAG."""
    try:
        from engine.integrations.anythingllm import get_anythingllm_client

        return json.dumps(
            get_anythingllm_client().sync_from_nexus(
                workspace, query=query, limit=limit, instance=instance or None
            ),
            default=str,
        )
    except Exception as exc:
        return json.dumps({"error": str(exc)})
