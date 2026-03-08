"""MCP skills for LMStudio server-side control.

Exposes the ServerController, LMLinkManager, and TaskQueue to agents
via the ``@skill`` decorator so they can manage model lifecycle,
configure inference, route tasks, and monitor health.

Skill pack: ``lmstudio_server``
"""
from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

from engine.skills import skill

logger = logging.getLogger(__name__)


# ── Model lifecycle ──────────────────────────────────────────────────────

@skill(
    pack="lmstudio_server",
    description="Load a model on the LMStudio server with optional context length and GPU offload",
    category="SYSTEM",
    cooldown=10.0,
    cost=3.0,
    tags=["lmstudio", "model", "server"],
)
def lms_load_model(
    model_key: str,
    context_length: int = 4096,
    gpu_offload: float = 0.9,
    stop_strings: str = "",
) -> str:
    """Load a model on LMStudio with the given configuration."""
    from engine.lmstudio.server_controller import get_server_controller

    ctrl = get_server_controller()
    stops = [s.strip() for s in stop_strings.split(",") if s.strip()] if stop_strings else []

    try:
        instance = ctrl.load_model(
            model_key,
            context_length=context_length,
            gpu_offload=gpu_offload,
            stop_strings=stops,
        )
        return (
            f"Model '{model_key}' loaded: ctx={instance.context_length}, "
            f"gpu={instance.gpu_offload}, stop_strings={instance.stop_strings}"
        )
    except Exception as e:
        return f"Failed to load model '{model_key}': {e}"


@skill(
    pack="lmstudio_server",
    description="Unload a model from the LMStudio server to free VRAM",
    category="SYSTEM",
    cooldown=5.0,
    cost=1.0,
    tags=["lmstudio", "model", "server"],
)
def lms_unload_model(model_key: str) -> str:
    """Unload a model from LMStudio."""
    from engine.lmstudio.server_controller import get_server_controller

    ctrl = get_server_controller()
    success = ctrl.unload_model(model_key)
    return f"Model '{model_key}' unloaded: {'success' if success else 'failed'}"


@skill(
    pack="lmstudio_server",
    description="List all loaded and downloaded models on LMStudio",
    category="SYSTEM",
    cooldown=2.0,
    cost=0.5,
    tags=["lmstudio", "model", "status"],
)
def lms_list_models() -> str:
    """List loaded and available models."""
    from engine.lmstudio.server_controller import get_server_controller
    import json

    ctrl = get_server_controller()
    models = ctrl.list_models()
    return json.dumps(models, indent=2, default=str)


# ── Server health ────────────────────────────────────────────────────────

@skill(
    pack="lmstudio_server",
    description="Get LMStudio server health status including VRAM and loaded models",
    category="SYSTEM",
    cooldown=5.0,
    cost=0.5,
    tags=["lmstudio", "health", "status"],
)
def lms_server_health() -> str:
    """Get comprehensive server health status."""
    from engine.lmstudio.server_controller import get_server_controller
    import json

    ctrl = get_server_controller()
    status = ctrl.get_full_status()
    return json.dumps(status, indent=2, default=str)


# ── Inference configuration ──────────────────────────────────────────────

@skill(
    pack="lmstudio_server",
    description="Configure server-side inference defaults for a model (stop strings, temperature, etc.)",
    category="SYSTEM",
    cooldown=2.0,
    cost=1.0,
    tags=["lmstudio", "config", "inference"],
)
def lms_configure_model(
    model_key: str,
    stop_strings: str = "",
    temperature: float = -1.0,
    max_tokens: int = -1,
) -> str:
    """Configure inference parameters for a loaded model."""
    from engine.lmstudio.server_controller import get_server_controller

    ctrl = get_server_controller()
    stops = [s.strip() for s in stop_strings.split(",") if s.strip()] if stop_strings else None
    temp = temperature if temperature >= 0 else None
    tokens = max_tokens if max_tokens >= 0 else None

    instance = ctrl.configure_inference(
        model_key,
        stop_strings=stops,
        temperature=temp,
        max_tokens=tokens,
    )
    return (
        f"Model '{model_key}' configured: "
        f"stop_strings={instance.stop_strings}, "
        f"temperature={instance.temperature}, "
        f"max_tokens={instance.max_tokens}"
    )


# ── Agent instance isolation ─────────────────────────────────────────────

@skill(
    pack="lmstudio_server",
    description="Create an isolated model instance for a specific agent with separate KV cache",
    category="SYSTEM",
    cooldown=10.0,
    cost=5.0,
    tags=["lmstudio", "agent", "instance"],
)
def lms_create_agent_instance(
    agent_id: str,
    model_key: str,
    context_length: int = 8192,
) -> str:
    """Create a dedicated model instance for an agent."""
    from engine.lmstudio.server_controller import get_server_controller

    ctrl = get_server_controller()
    try:
        instance = ctrl.create_agent_instance(
            agent_id=agent_id,
            model_key=model_key,
            context_length=context_length,
        )
        return (
            f"Agent instance created: agent={agent_id}, "
            f"model={model_key}, id={instance.instance_id}, "
            f"ctx={instance.context_length}"
        )
    except Exception as e:
        return f"Failed to create agent instance: {e}"


@skill(
    pack="lmstudio_server",
    description="Release an agent's dedicated model instance",
    category="SYSTEM",
    cooldown=5.0,
    cost=1.0,
    tags=["lmstudio", "agent", "instance"],
)
def lms_release_agent_instance(agent_id: str) -> str:
    """Release a dedicated model instance for an agent."""
    from engine.lmstudio.server_controller import get_server_controller

    ctrl = get_server_controller()
    success = ctrl.release_agent_instance(agent_id)
    return f"Agent '{agent_id}' instance release: {'success' if success else 'no instance found'}"


@skill(
    pack="lmstudio_server",
    description="List all agent-to-model instance bindings",
    category="SYSTEM",
    cooldown=2.0,
    cost=0.5,
    tags=["lmstudio", "agent", "status"],
)
def lms_list_agent_instances() -> str:
    """List all active agent instance bindings."""
    from engine.lmstudio.server_controller import get_server_controller
    import json

    ctrl = get_server_controller()
    instances = ctrl.list_agent_instances()
    if not instances:
        return "No agent instances active"
    return json.dumps(instances, indent=2, default=str)


# ── LMLink federation ───────────────────────────────────────────────────

@skill(
    pack="lmstudio_server",
    description="Get LMLink multi-instance federation status and peer health",
    category="SYSTEM",
    cooldown=5.0,
    cost=0.5,
    tags=["lmstudio", "lmlink", "federation"],
)
def lms_lmlink_status() -> str:
    """Get LMLink federation status."""
    from engine.lmstudio.lmlink_manager import get_lmlink_manager
    import json

    mgr = get_lmlink_manager()
    return json.dumps(mgr.get_status(), indent=2, default=str)


@skill(
    pack="lmstudio_server",
    description="Route a model request through LMLink to find the best peer",
    category="SYSTEM",
    cooldown=2.0,
    cost=1.0,
    tags=["lmstudio", "lmlink", "routing"],
)
def lms_lmlink_route(model_key: str) -> str:
    """Resolve the best LMLink peer for a model."""
    from engine.lmstudio.lmlink_manager import get_lmlink_manager
    import json

    mgr = get_lmlink_manager()
    decision = mgr.resolve_with_failover(model_key)
    if decision is None:
        return f"No peer available for model '{model_key}'"
    return json.dumps(decision.to_dict(), indent=2, default=str)


# ── Task queue ───────────────────────────────────────────────────────────

@skill(
    pack="lmstudio_server",
    description="Submit a task to the inference queue with type-based model affinity routing",
    category="SYSTEM",
    cooldown=1.0,
    cost=2.0,
    tags=["lmstudio", "queue", "task"],
)
def lms_submit_task(
    prompt: str,
    task_type: str = "chat",
    model_hint: str = "",
    priority: str = "NORMAL",
    system_prompt: str = "",
    max_tokens: int = 2048,
) -> str:
    """Submit a task to the inference queue."""
    from engine.lmstudio.task_queue import (
        get_task_queue, TaskType, TaskPriority,
    )
    import json

    ttype = TaskType(task_type.lower()) if task_type.lower() in TaskType.__members__.values() else TaskType.CHAT

    try:
        pri = TaskPriority[priority.upper()]
    except KeyError:
        pri = TaskPriority.NORMAL

    queue = get_task_queue()
    task = queue.submit(
        task_type=ttype,
        prompt=prompt,
        system_prompt=system_prompt,
        model_hint=model_hint,
        priority=pri,
        max_tokens=max_tokens,
    )
    return json.dumps(task.to_dict(), indent=2, default=str)


@skill(
    pack="lmstudio_server",
    description="Get task queue status including depth, workers, and metrics",
    category="SYSTEM",
    cooldown=2.0,
    cost=0.5,
    tags=["lmstudio", "queue", "status"],
)
def lms_queue_status() -> str:
    """Get task queue status and metrics."""
    from engine.lmstudio.task_queue import get_task_queue
    import json

    queue = get_task_queue()
    return json.dumps(queue.get_status(), indent=2, default=str)


# ── Token counting ───────────────────────────────────────────────────────

@skill(
    pack="lmstudio_server",
    description="Count tokens in text using the model's tokenizer",
    category="SYSTEM",
    cooldown=1.0,
    cost=0.5,
    tags=["lmstudio", "tokens", "utility"],
)
def lms_count_tokens(text: str, model_key: str = "") -> str:
    """Count tokens in text."""
    from engine.lmstudio.server_controller import get_server_controller

    ctrl = get_server_controller()
    count = ctrl.count_tokens(text, model_key=model_key or None)
    return f"Token count: {count} (text length: {len(text)} chars)"
