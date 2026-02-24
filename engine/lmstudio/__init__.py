"""engine.lmstudio — LMStudio integration layer (v2 framework — v1 native API only)

Primary API
-----------
``LMSClient`` / ``get_lms_client``
    **Native v1 REST client** (``/api/v1/chat``, ``/api/v1/models/*``).
    The **only** inference path — no OpenAI-compatible fallback.
    Supports stateful chats, ephemeral MCP, structured output,
    speculative decoding, image input, full params.

``ConversationManager`` / ``get_conversation_manager``
    Client-side conversation state mirror.  Tracks all messages,
    handles ``previous_response_id`` for stateful chats, transparent
    replay on model unload, edit/fork conversation history.

``LMStudioClient`` / ``get_lmstudio_client``
    **Deprecated** — thin compatibility wrapper that redirects to
    ``LMSClient``.  Use ``get_lms_client()`` directly.

``InferenceConfig`` / ``LoadConfig``
    Typed dataclasses for all inference and model-load parameters.
    Factories: ``from_agent_profile()``, ``from_yaml()``, ``merge()``.

``ResourceManager`` / ``get_resource_manager``
    Intelligent model lifecycle with 6 strategies (SINGLE_BIG, CONCURRENT,
    MULTI_SMALL, JIT_SWAP, SPECULATIVE, HYBRID).  GPU budget tracking,
    background task queue, TTL-based eviction.

``LMStudioManager`` / ``get_lmstudio_manager``
    CLI-based model lifecycle (load, unload, VRAM estimation).

``MCP``
    Factory helpers for MCP integration payloads::

        MCP.plugin("mcp/cosysim")
        MCP.ephemeral("http://localhost:8600/mcp/sse")

``ModelManager`` / ``get_model_manager``
    Three-mode model lifecycle controller (CONCURRENT / JIT / JIT_TTL).

``ConcurrentExecutor`` / ``get_executor``
    Thread-pool fan-out for parallel LMStudio requests.

``ToolFactory`` / ``tool`` / ``from_callable`` / ``run_with_tools``
    Ephemeral in-process function-calling tools.

Quick start::

    from engine.lmstudio import get_lms_client, InferenceConfig

    client = get_lms_client()
    reply = client.quick_reply("Hello!")

    # With full config control:
    cfg = InferenceConfig(temperature=0.3, max_output_tokens=1000)
    resp = client.chat(messages, config=cfg)

    # Structured output:
    resp = client.chat_structured(messages, {"type": "object", ...})

    # Stateful chat:
    resp = client.chat_stateful("Hello!", system="You are helpful.")
    resp2 = client.chat_stateful("What did I say?", previous_response_id=resp.response_id)

    # Conversation manager (recommended for scenes):
    from engine.lmstudio import get_conversation_manager
    conv = get_conversation_manager().create("aria_chat", system="You are Aria.")
    resp = conv.send("Hello!")
"""
# Native v1 client (primary — the only inference path)
from .lms_client       import (
    LMSClient, get_lms_client, LMSResponse, LMSStreamEvent, LMSModelInfo,
    LMSModel, LMSModelInstance, LMSQuantization, LMSCapabilities,
    LMSLoadResult, LMSDownloadJob, LMSDownloadStatus, MCP,
)
# Conversation state management
from .conversation     import ConversationManager, get_conversation_manager, Conversation
# Config dataclasses
from .inference_config import InferenceConfig, LoadConfig, json_schema_format, json_object_format
# Resource manager
from .resource_manager import ResourceManager, get_resource_manager, Strategy
# CLI lifecycle management
from .client           import LMStudioManager, get_lmstudio_manager
# Model lifecycle modes
from .model_manager    import ModelManager, get_model_manager, LoadMode
# Concurrency
from .concurrency      import ConcurrentExecutor, get_executor, ConcurrentResult
# Ephemeral tools / function-calling
from .tool_factory     import ToolSpec, tool, from_callable, run_with_tools
# SDK client (WebSocket-based, optional)
from .sdk_client       import SDKClient, get_sdk_client, SDK_AVAILABLE
# Inference router (three-tier priority queue)
from .router           import InferenceRouter, Priority, Tier, Channel
# Tool registry (MCP ↔ SDK bridge)
from .tool_registry    import (
    ToolRegistry as SDKToolRegistry, ToolScope,
    get_tool_registry, reset_tool_registry,
)

__all__ = [
    # Native v1 (the only inference path)
    "LMSClient", "get_lms_client", "LMSResponse", "LMSStreamEvent", "LMSModelInfo",
    "LMSModel", "LMSModelInstance", "LMSQuantization", "LMSCapabilities",
    "LMSLoadResult", "LMSDownloadJob", "LMSDownloadStatus", "MCP",
    # Conversation state
    "ConversationManager", "get_conversation_manager", "Conversation",
    # Config
    "InferenceConfig", "LoadConfig", "json_schema_format", "json_object_format",
    # Resource manager
    "ResourceManager", "get_resource_manager", "Strategy",
    # CLI lifecycle
    "LMStudioManager", "get_lmstudio_manager",
    # Model lifecycle modes
    "ModelManager", "get_model_manager", "LoadMode",
    # Concurrency
    "ConcurrentExecutor", "get_executor", "ConcurrentResult",
    # Ephemeral tools
    "ToolSpec", "tool", "from_callable", "run_with_tools",
    # SDK client (WebSocket)
    "SDKClient", "get_sdk_client", "SDK_AVAILABLE",
    # Inference router
    "InferenceRouter", "Priority", "Tier", "Channel",
    # Tool registry
    "SDKToolRegistry", "ToolScope", "get_tool_registry", "reset_tool_registry",
]
