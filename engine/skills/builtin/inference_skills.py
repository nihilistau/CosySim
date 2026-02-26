"""
Inference Leaderboard Skills — MCP skills for benchmarking and comparing
model performance across methods, tiers, and configurations.

Skills:
    - benchmark_model: Run a benchmark against a loaded model
    - store_benchmark: Store benchmark results in Nexus
    - get_leaderboard: Retrieve and compare benchmark results
    - check_lmstudio: Check LMStudio status and loaded models
    - delegate_task: Delegate a task to local LMStudio model
"""
from __future__ import annotations

import logging
import time
from typing import Any

from engine.skills.skill import skill

logger = logging.getLogger(__name__)


@skill(
    pack="inference",
    description="Run a quick benchmark against a loaded LMStudio model",
    category="SYSTEM",
    cooldown=10.0,
    cost=2.0,
    tags=["benchmark", "performance", "lmstudio"],
)
def benchmark_model(
    prompt: str = "Explain quantum computing in 3 sentences.",
    model: str = "",
    iterations: int = 3,
    max_tokens: int = 256,
) -> str:
    """Run a quick benchmark and return performance metrics."""
    from engine.nexus.lms_task_bridge import LMSTaskBridge

    bridge = LMSTaskBridge()

    # Check LMStudio first
    status = bridge.check_lmstudio()
    if status["status"] != "online":
        return f"LMStudio is offline: {status.get('error', 'unknown')}"
    if not status["model_ids"]:
        return "No models loaded in LMStudio. Load a model first."

    results = []
    for i in range(iterations):
        result = bridge.run_prompt(
            prompt,
            model=model,
            max_tokens=max_tokens,
            priority="background",
        )
        results.append(result)

    completed = [r for r in results if r.ok]
    if not completed:
        errors = [r.error for r in results if r.error]
        return f"All {iterations} runs failed. Errors: {'; '.join(errors[:3])}"

    avg_latency = sum(r.latency_ms for r in completed) / len(completed)
    avg_tps = sum(r.tps for r in completed) / len(completed)
    avg_tokens = sum(r.tokens_generated for r in completed) / len(completed)
    used_model = completed[0].model

    return (
        f"Benchmark: {used_model}\n"
        f"Runs: {len(completed)}/{iterations} succeeded\n"
        f"Avg latency: {avg_latency:.0f}ms\n"
        f"Avg TPS: {avg_tps:.1f}\n"
        f"Avg tokens: {avg_tokens:.0f}\n"
        f"Prompt: {prompt[:60]}..."
    )


@skill(
    pack="inference",
    description="Store benchmark results in Nexus for the inference leaderboard",
    category="SYSTEM",
    cooldown=2.0,
    cost=1.0,
    tags=["benchmark", "nexus", "leaderboard"],
)
def store_benchmark(
    model: str,
    method: str,
    tps: float = 0.0,
    latency_ms: float = 0.0,
    ttft_ms: float = 0.0,
    memory_mb: float = 0.0,
    context_length: int = 0,
    concurrency: int = 1,
    notes: str = "",
) -> str:
    """Store benchmark metrics in Nexus leaderboard."""
    from engine.nexus.client import get_nexus_client

    client = get_nexus_client()
    entry_id = client.store_benchmark(
        model=model,
        method=method,
        metrics={
            "tps": tps,
            "latency_ms": latency_ms,
            "ttft_ms": ttft_ms,
            "memory_mb": memory_mb,
            "context_length": context_length,
            "concurrency": concurrency,
            "notes": notes,
        },
    )
    if entry_id:
        return f"Stored benchmark for {model} [{method}] → Nexus ID: {entry_id}"
    return f"Failed to store benchmark for {model}"


@skill(
    pack="inference",
    description="Get the inference performance leaderboard from Nexus",
    category="SYSTEM",
    cooldown=2.0,
    cost=0.5,
    tags=["benchmark", "leaderboard", "comparison"],
)
def get_leaderboard(method: str = "", limit: int = 10) -> str:
    """Retrieve benchmark leaderboard, optionally filtered by method."""
    from engine.nexus.client import get_nexus_client

    client = get_nexus_client()
    entries = client.get_leaderboard(method=method, limit=limit)

    if not entries:
        return "No benchmark entries found. Run benchmark_model first."

    lines = [f"Inference Leaderboard ({len(entries)} entries):"]
    lines.append("-" * 50)
    for i, entry in enumerate(entries, 1):
        title = entry.get("title", "Unknown")
        content = entry.get("content", "")
        lines.append(f"{i}. {title}")
        # Extract key metrics from content
        for metric_line in content.split("\n"):
            if any(k in metric_line for k in ["Tokens/sec", "Latency", "Memory"]):
                lines.append(f"   {metric_line.strip()}")
        lines.append("")

    return "\n".join(lines)


@skill(
    pack="inference",
    description="Check LMStudio server status and loaded models",
    category="SYSTEM",
    cooldown=5.0,
    cost=0.5,
    tags=["lmstudio", "health", "status"],
)
def check_lmstudio_status() -> str:
    """Check if LMStudio is running and what models are loaded."""
    from engine.nexus.lms_task_bridge import LMSTaskBridge

    bridge = LMSTaskBridge()
    status = bridge.check_lmstudio()

    if status["status"] == "online":
        models = status.get("model_ids", [])
        if models:
            model_list = "\n".join(f"  - {m}" for m in models)
            return f"LMStudio: ONLINE\nModels loaded ({len(models)}):\n{model_list}"
        return "LMStudio: ONLINE (no models loaded)"
    return f"LMStudio: OFFLINE — {status.get('error', 'unknown error')}"


@skill(
    pack="inference",
    description="Delegate a task to local LMStudio model for execution",
    category="SYSTEM",
    cooldown=5.0,
    cost=2.0,
    tags=["delegation", "lmstudio", "task"],
)
def delegate_task(
    task_type: str,
    prompt: str,
    model: str = "",
    store_result: bool = True,
) -> str:
    """Delegate a structured task to LMStudio.

    Task types: evaluate, summarize, generate, classify, compare
    """
    from engine.nexus.lms_task_bridge import LMSTaskBridge

    bridge = LMSTaskBridge()

    # Quick health check
    status = bridge.check_lmstudio()
    if status["status"] != "online":
        return f"Cannot delegate — LMStudio offline: {status.get('error')}"

    result = bridge.run_task(
        task_type=task_type,
        prompt=prompt,
        model=model,
        store_result=store_result,
    )

    if result.ok:
        return (
            f"Task {result.task_id} completed ({result.latency_ms:.0f}ms, "
            f"{result.tps:.1f} TPS):\n{result.output[:2000]}"
        )
    return f"Task {result.task_id} failed: {result.error}"
