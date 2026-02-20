"""engine.lmstudio — LMStudio integration layer

Primary API
-----------
``LMStudioClient`` / ``get_lmstudio_client``
    REST v1 client (``/v1/chat/completions``).  This is the primary path
    for all LLM inference — use it directly or via CharacterAgent/SceneAgent.
    Supports MCP ``integrations``, streaming, token counting, and auto
    model-resolution (picks the first loaded model if none is configured).

``LMStudioManager`` / ``get_lmstudio_manager``
    CLI-based model lifecycle (load, unload, VRAM estimation).  Used for
    model management in the admin panel, not for inference.

``MCP``
    Factory helpers for MCP integration payloads::

        MCP.plugin("mcp/cosysim")                      # registered plugin
        MCP.ephemeral("http://localhost:8600/mcp/sse") # ephemeral URL

Quick start::

    from engine.lmstudio import get_lmstudio_client, MCP

    client = get_lmstudio_client()
    reply = client.quick_reply("Hello!")

    # With CosySim MCP tools:
    from engine.config import get_config
    mcp_url = get_config().get("lmstudio.cosysim_mcp_url", "")
    reply = client.quick_reply("Search my memories for 'beach'",
                               integrations=[MCP.ephemeral(mcp_url)])
"""
from .client    import LMStudioManager, get_lmstudio_manager
from .client_v2 import LMStudioClient, get_lmstudio_client, MCP

__all__ = [
    # REST v1 (primary inference path)
    "LMStudioClient",
    "get_lmstudio_client",
    "MCP",
    # CLI lifecycle management
    "LMStudioManager",
    "get_lmstudio_manager",
]
