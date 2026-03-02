import json
from typing import Optional


def capture_training_data_impl(
    user_message: str,
    agent_response: str,
    dataset_type: str = "conversation",
    quality_score: float = 0.7,
    character_id: str = "",
) -> str:
    try:
        from engine.nexus.training_pipeline import get_training_pipeline

        tp = get_training_pipeline()
        entry_id = tp.capture_interaction(
            user_message,
            agent_response,
            dataset_type=dataset_type,
            quality_score=quality_score,
            character_id=character_id or None,
        )
        return json.dumps({"status": "ok", "entry_id": entry_id, "type": dataset_type})
    except Exception as e:
        return json.dumps({"error": str(e)})


def generate_content_impl(character_id: str, content_type: str = "greetings") -> str:
    try:
        from engine.nexus.workflows import ContentWorkflow

        cw = ContentWorkflow()
        if content_type == "greetings":
            ids = cw.generate_greetings(character_id)
        elif content_type == "reactions":
            ids = cw.generate_reactions(character_id)
        else:
            return json.dumps(
                {"error": f"Unknown type '{content_type}'. Use: greetings, reactions"}
            )
        return json.dumps({"status": "ok", "entries_created": len(ids), "ids": ids[:5]})
    except Exception as e:
        return json.dumps({"error": str(e)})


def training_stats_impl() -> str:
    try:
        from engine.nexus.training_flywheel import get_training_flywheel

        return json.dumps(get_training_flywheel().stats(), indent=2, default=str)
    except Exception as e:
        return json.dumps({"error": str(e)})


def training_export_impl(format: str = "jsonl", min_quality: float = 0.5) -> str:
    try:
        from engine.nexus.training_flywheel import get_training_flywheel

        fw = get_training_flywheel()
        if format == "sharegpt":
            return json.dumps(
                fw.export_sharegpt(min_quality=min_quality), indent=2, default=str
            )
        elif format == "dpo":
            return json.dumps(fw.export_dpo(), indent=2, default=str)
        else:
            return json.dumps(
                fw.export_jsonl(min_quality=min_quality), indent=2, default=str
            )
    except Exception as e:
        return json.dumps({"error": str(e)})


def training_sync_nexus_impl() -> str:
    try:
        from engine.nexus.training_flywheel import get_training_flywheel

        return json.dumps(
            get_training_flywheel().sync_from_nexus(), indent=2, default=str
        )
    except Exception as e:
        return json.dumps({"error": str(e)})


def finetune_submit_impl(model_type: str, base_model: str = "") -> str:
    from training.finetune_orchestrator import get_finetune_orchestrator

    try:
        orch = get_finetune_orchestrator()
        kwargs = {"model_type": model_type}
        if base_model:
            kwargs["base_model"] = base_model
        job = orch.submit(**kwargs)
        return json.dumps(job.to_dict(), indent=2)
    except FileNotFoundError as exc:
        return f"ERROR: {exc}\nRun finetune_build_dataset first."
    except Exception as exc:
        return json.dumps({"error": str(exc)})


def finetune_run_next_impl() -> str:
    from training.finetune_orchestrator import get_finetune_orchestrator

    try:
        orch = get_finetune_orchestrator()
        job = orch.run_next()
        if job is None:
            return "No pending fine-tuning jobs."
        return json.dumps(job.to_dict(), indent=2)
    except Exception as exc:
        return json.dumps({"error": str(exc)})


def finetune_list_jobs_impl(status: str = "") -> str:
    from training.finetune_orchestrator import get_finetune_orchestrator

    try:
        orch = get_finetune_orchestrator()
        jobs = orch.list_jobs(status=status or None)
        lines = ["=== Fine-tune Jobs ===", f"Queue: {orch.queue_status()}", ""]
        for j in jobs[:20]:
            lines.append(
                f"[{j['status']}] {j['job_id']} {j['model_type']} ({j['base_model']}) "
                f"progress={j['progress']:.0%}"
            )
        return "\n".join(lines)
    except Exception as exc:
        return json.dumps({"error": str(exc)})


def finetune_build_dataset_impl(model_type: str, count: int = 500) -> str:
    from training.micro_datasets import MicroDatasetManager

    try:
        mgr = MicroDatasetManager()
        stats = mgr.build(model_type, count=count)
        return json.dumps(stats.to_dict(), indent=2)
    except Exception as exc:
        return json.dumps({"error": str(exc)})


def finetune_dataset_status_impl() -> str:
    from training.micro_datasets import MicroDatasetManager

    try:
        mgr = MicroDatasetManager()
        status = mgr.status()
        lines = ["=== Dataset Status ==="]
        for model_type, info in status.items():
            ready = "✓" if info["ready"] else "✗"
            lines.append(
                f"  {ready} {model_type}: train={info['train']} val={info['val']} test={info['test']}"
            )
        return "\n".join(lines)
    except Exception as exc:
        return json.dumps({"error": str(exc)})


def model_registry_list_impl(model_type: str = "") -> str:
    from training.model_registry import get_model_registry

    try:
        registry = get_model_registry()
        models = registry.list_models(model_type=model_type or None)
        lines = ["=== Model Registry ==="]
        for m in models:
            active = "★ ACTIVE" if m["active"] else "  "
            score = (
                f"score={m['benchmark_score']:.3f}"
                if m["benchmark_score"]
                else "score=?"
            )
            lines.append(
                f"  {active} [{m['model_id']}] {m['model_type']} {score} base={m['base_model']}"
            )
        lines.append(f"\nSummary: {json.dumps(registry.summary(), indent=2)}")
        return "\n".join(lines)
    except Exception as exc:
        return json.dumps({"error": str(exc)})


def model_benchmark_run_impl(model_type: str = "") -> str:
    from training.benchmark_runner import get_benchmark_runner

    try:
        runner = get_benchmark_runner()
        if model_type:
            result = runner.run(model_type)
            return result.summary()
        else:
            results = runner.run_all()
            return "\n".join(r.summary() for r in results)
    except Exception as exc:
        return json.dumps({"error": str(exc)})


def model_benchmark_leaderboard_impl() -> str:
    from training.benchmark_runner import get_benchmark_runner

    try:
        board = get_benchmark_runner().get_leaderboard()
        lines = ["=== Model Leaderboard ==="]
        for model_type, info in board.items():
            score = (
                f"{info['best_score']:.3f}"
                if info["best_score"] is not None
                else "no data"
            )
            lines.append(f"  {model_type}: {score} (id={info['model_id']})")
        return "\n".join(lines)
    except Exception as exc:
        return json.dumps({"error": str(exc)})


def model_promote_impl(model_id: str, model_type: str) -> str:
    from training.model_registry import get_model_registry

    try:
        registry = get_model_registry()
        registry.promote(model_type, model_id)
        return f"Promoted model {model_id} as active {model_type}."
    except Exception as exc:
        return json.dumps({"error": str(exc)})


def teacher_generate_dataset_impl(model_type: str, count: int = 300) -> str:
    from engine.nexus.teacher_pipeline import get_teacher_pipeline

    try:
        pipeline = get_teacher_pipeline()
        result = pipeline.generate_dataset(model_type, count=count)
        return json.dumps(result.to_dict(), indent=2)
    except Exception as exc:
        return json.dumps({"error": str(exc)})


def finetuned_router_status_impl() -> str:
    from engine.lmstudio.finetuned_router import get_finetuned_router

    try:
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
    except Exception as exc:
        return json.dumps({"error": str(exc)})


def finetuned_router_load_registry_impl() -> str:
    from engine.lmstudio.finetuned_router import get_finetuned_router

    try:
        router = get_finetuned_router()
        count = router.load_from_registry()
        return f"Loaded {count} fine-tuned models from registry."
    except Exception as exc:
        return json.dumps({"error": str(exc)})
