"""MCP tool domain: training.

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

# ──── TRAINING TOOLS ─────────────────────────────────────────────────────


@mcp_tool
def capture_training_data(user_message: str, agent_response: str,
                          dataset_type: str = "conversation",
                          quality_score: float = 0.7,
                          character_id: str = "") -> str:
    """Capture an LLM interaction as training data for fine-tuning."""
    try:
        from engine.nexus.training_pipeline import get_training_pipeline
        tp = get_training_pipeline()
        entry_id = tp.capture_interaction(
            user_message, agent_response,
            dataset_type=dataset_type,
            quality_score=quality_score,
            character_id=character_id or None,
        )
        return json.dumps({"status": "ok", "entry_id": entry_id, "type": dataset_type})
    except Exception as e:
        return json.dumps({"error": str(e)})


@mcp_tool
def generate_content(character_id: str, content_type: str = "greetings") -> str:
    """Generate pre-built content for a character. Types: greetings, reactions."""
    try:
        from engine.nexus.workflows import ContentWorkflow
        cw = ContentWorkflow()
        if content_type == "greetings":
            ids = cw.generate_greetings(character_id)
        elif content_type == "reactions":
            ids = cw.generate_reactions(character_id)
        else:
            return json.dumps({"error": f"Unknown type '{content_type}'. Use: greetings, reactions"})
        return json.dumps({"status": "ok", "entries_created": len(ids), "ids": ids[:5]})
    except Exception as e:
        return json.dumps({"error": str(e)})


@mcp_tool
def training_stats() -> str:
    """Get training data flywheel statistics — example counts by source,
    total examples, export history, and quality distribution."""
    try:
        from engine.nexus.training_flywheel import get_training_flywheel
        return json.dumps(get_training_flywheel().stats(), indent=2, default=str)
    except Exception as e:
        return json.dumps({"error": str(e)})


@mcp_tool
def training_export(format: str = "jsonl", min_quality: float = 0.5) -> str:
    """Export training data for model fine-tuning. format: 'jsonl' (instruction),
    'sharegpt' (conversation), or 'dpo' (preference). Returns export path and count."""
    try:
        from engine.nexus.training_flywheel import get_training_flywheel
        fw = get_training_flywheel()
        if format == "sharegpt":
            return json.dumps(fw.export_sharegpt(min_quality=min_quality), indent=2, default=str)
        elif format == "dpo":
            return json.dumps(fw.export_dpo(), indent=2, default=str)
        else:
            return json.dumps(fw.export_jsonl(min_quality=min_quality), indent=2, default=str)
    except Exception as e:
        return json.dumps({"error": str(e)})


@mcp_tool
def training_sync_nexus() -> str:
    """Sync all Nexus Q&A pairs into the training flywheel for fine-tuning.
    Deduplicates against existing examples."""
    try:
        from engine.nexus.training_flywheel import get_training_flywheel
        return json.dumps(get_training_flywheel().sync_from_nexus(), indent=2, default=str)
    except Exception as e:
        return json.dumps({"error": str(e)})


@mcp_tool
async def finetune_submit(model_type: str, base_model: str = "") -> str:
    """Submit a new fine-tuning job for a micro-model type.

    Args:
        model_type: qa_evaluator | conversation_analyzer | syntax_fixer | router_v2 | knowledge_synthesizer
        base_model: HuggingFace model ID or alias (qwen-270m, qwen-1.7b, llama-3b). Default: auto.
    """
    from training.finetune_orchestrator import get_finetune_orchestrator
    orch = get_finetune_orchestrator()
    kwargs: dict = {"model_type": model_type}
    if base_model:
        kwargs["base_model"] = base_model
    try:
        job = orch.submit(**kwargs)
        return json.dumps(job.to_dict(), indent=2)
    except FileNotFoundError as exc:
        return f"ERROR: {exc}\nRun finetune_build_dataset first."


@mcp_tool
async def finetune_run_next() -> str:
    """Run the next pending fine-tuning job. Blocks until complete."""
    from training.finetune_orchestrator import get_finetune_orchestrator
    orch = get_finetune_orchestrator()
    job = orch.run_next()
    if job is None:
        return "No pending fine-tuning jobs."
    return json.dumps(job.to_dict(), indent=2)


@mcp_tool
async def finetune_list_jobs(status: str = "") -> str:
    """List all fine-tuning jobs.

    Args:
        status: Filter by status (pending|running|done|failed). Empty = all.
    """
    from training.finetune_orchestrator import get_finetune_orchestrator
    orch = get_finetune_orchestrator()
    jobs = orch.list_jobs(status=status or None)
    lines = ["=== Fine-tune Jobs ===", f"Queue: {orch.queue_status()}", ""]
    for j in jobs[:20]:
        lines.append(
            f"[{j['status']}] {j['job_id']} {j['model_type']} ({j['base_model']}) "
            f"progress={j['progress']:.0%}"
        )
    return "\n".join(lines)


@mcp_tool
async def finetune_build_dataset(model_type: str, count: int = 500) -> str:
    """Build training dataset for a micro-model type using NLM teacher.

    Args:
        model_type: Target model type.
        count: Number of examples to generate.
    """
    from training.micro_datasets import MicroDatasetManager
    mgr = MicroDatasetManager()
    stats = mgr.build(model_type, count=count)
    return json.dumps(stats.to_dict(), indent=2)


@mcp_tool
async def finetune_dataset_status() -> str:
    """Show dataset sizes for all micro-model types."""
    from training.micro_datasets import MicroDatasetManager
    mgr = MicroDatasetManager()
    status = mgr.status()
    lines = ["=== Dataset Status ==="]
    for model_type, info in status.items():
        ready = "✓" if info["ready"] else "✗"
        lines.append(f"  {ready} {model_type}: train={info['train']} val={info['val']} test={info['test']}")
    return "\n".join(lines)


@mcp_tool
async def model_registry_list(model_type: str = "") -> str:
    """List registered fine-tuned models.

    Args:
        model_type: Filter by type. Empty = all.
    """
    from training.model_registry import get_model_registry
    registry = get_model_registry()
    models = registry.list_models(model_type=model_type or None)
    lines = ["=== Model Registry ==="]
    for m in models:
        active = "★ ACTIVE" if m["active"] else "  "
        score = f"score={m['benchmark_score']:.3f}" if m["benchmark_score"] else "score=?"
        lines.append(f"  {active} [{m['model_id']}] {m['model_type']} {score} base={m['base_model']}")
    lines.append(f"\nSummary: {json.dumps(registry.summary(), indent=2)}")
    return "\n".join(lines)


@mcp_tool
async def model_benchmark_run(model_type: str = "") -> str:
    """Run benchmarks on fine-tuned models.

    Args:
        model_type: Type to benchmark. Empty = run all.
    """
    from training.benchmark_runner import get_benchmark_runner
    runner = get_benchmark_runner()
    if model_type:
        result = runner.run(model_type)
        return result.summary()
    else:
        results = runner.run_all()
        return "\n".join(r.summary() for r in results)


@mcp_tool
async def model_benchmark_leaderboard() -> str:
    """Show the best benchmark score per micro-model type."""
    from training.benchmark_runner import get_benchmark_runner
    board = get_benchmark_runner().get_leaderboard()
    lines = ["=== Model Leaderboard ==="]
    for model_type, info in board.items():
        score = f"{info['best_score']:.3f}" if info["best_score"] is not None else "no data"
        lines.append(f"  {model_type}: {score} (id={info['model_id']})")
    return "\n".join(lines)


@mcp_tool
async def model_promote(model_id: str, model_type: str) -> str:
    """Manually promote a fine-tuned model as the active one for its type.

    Args:
        model_id: Registry model ID (8-char).
        model_type: Model type (qa_evaluator, router_v2, etc.).
    """
    from training.model_registry import get_model_registry
    registry = get_model_registry()
    registry.promote(model_type, model_id)
    return f"Promoted model {model_id} as active {model_type}."


@mcp_tool
async def teacher_generate_dataset(model_type: str, count: int = 300) -> str:
    """Generate a training dataset via NLM teacher pipeline (Gemini 3.0).

    Args:
        model_type: Target micro-model type.
        count: Number of examples to generate.
    """
    from engine.nexus.teacher_pipeline import get_teacher_pipeline
    pipeline = get_teacher_pipeline()
    result = pipeline.generate_dataset(model_type, count=count)
    return json.dumps(result.to_dict(), indent=2)


@mcp_tool
async def finetuned_router_status() -> str:
    """Show which fine-tuned models are currently active in the router."""
    from engine.lmstudio.finetuned_router import get_finetuned_router
    router = get_finetuned_router()
    active = router.get_active_models()
    lines = ["=== Fine-tuned Router ==="]
    if not active:
        lines.append("  No fine-tuned models loaded.")
        lines.append("  Run: finetuned_router_load_registry")
    else:
        for task_type, path in active.items():
            lines.append(f"  {task_type}: {path}")
    return "\n".join(lines)


@mcp_tool
async def finetuned_router_load_registry() -> str:
    """Load all active fine-tuned models from the model registry into the router."""
    from engine.lmstudio.finetuned_router import get_finetuned_router
    router = get_finetuned_router()
    count = router.load_from_registry()
    return f"Loaded {count} fine-tuned models from registry."
