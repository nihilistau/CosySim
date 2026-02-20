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

``ModelManager`` / ``get_model_manager``
    Three-mode model lifecycle controller (CONCURRENT / JIT / JIT_TTL).
    Handles automated load/unload via ``lms`` CLI with optional TTL reaping.

``ConcurrentExecutor`` / ``get_executor``
    Thread-pool fan-out for parallel LMStudio requests.
    Use ``scatter()`` for same prompt → N models, or ``parallel_tasks()``
    for different prompts in parallel (e.g. multi-agent ticks).

``ToolFactory`` / ``tool`` / ``from_callable`` / ``run_with_tools``
    Ephemeral in-process function-calling tools.  Convert any Python
    callable into an OpenAI function spec and run the full tool-call loop.

Quick start::

    from engine.lmstudio import get_lmstudio_client, MCP

    client = get_lmstudio_client()
    reply = client.quick_reply("Hello!")

    # With CosySim MCP tools:
    from engine.config import get_config
    mcp_url = get_config().get("lmstudio.cosysim_mcp_url", "")
    reply = client.quick_reply("Search my memories for 'beach'",
                               integrations=[MCP.ephemeral(mcp_url)])

    # Ephemeral tools:
    from engine.lmstudio import tool, run_with_tools

    @tool
    def mood_score(character: str) -> str:
        \"\"\"Return mood score for a character.\"\"\"
        return "happy (8/10)"

    reply = run_with_tools(messages, tools=[mood_score])
"""
from .client      import LMStudioManager, get_lmstudio_manager
from .client_v2   import LMStudioClient, get_lmstudio_client, MCP
from .model_manager import ModelManager, get_model_manager, LoadMode
from .concurrency   import ConcurrentExecutor, get_executor, ConcurrentResult
from .tool_factory  import ToolSpec, tool, from_callable, run_with_tools

__all__ = [
    # REST v1 (primary inference path)
    "LMStudioClient",
    "get_lmstudio_client",
    "MCP",
    # CLI lifecycle management
    "LMStudioManager",
    "get_lmstudio_manager",
    # Model lifecycle modes
    "ModelManager",
    "get_model_manager",
    "LoadMode",
    # Concurrency
    "ConcurrentExecutor",
    "get_executor",
    "ConcurrentResult",
    # Ephemeral tools / function-calling
    "ToolSpec",
    "tool",
    "from_callable",
    "run_with_tools",
]
