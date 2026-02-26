"""
Local fine-tuning script for Gemma 270M router model.

Uses Unsloth + QLoRA for efficient training on consumer GPUs (>=6GB VRAM).
Can also run on CPU (slower but works for small datasets).

Usage:
    python -m training.finetune_local --dataset tag_extraction --epochs 3
    python -m training.finetune_local --dataset all --lr 2e-4
"""

from __future__ import annotations

import json
import logging
import os
from pathlib import Path
from typing import Optional

log = logging.getLogger(__name__)

TRAINING_DIR = Path(__file__).parent
DATASETS_DIR = TRAINING_DIR / "datasets"
OUTPUT_DIR = TRAINING_DIR / "output"

DEFAULT_BASE_MODEL = "google/gemma-3-270m-it"
ALL_DATASETS = [
    "tag_extraction",
    "tool_routing",
    "priority_classify",
    "decision_classify",
    "response_validate",
]


def _load_dataset(dataset_name: str) -> list[dict]:
    """Load training data from JSONL files (combined > train > live)."""
    candidates = [
        DATASETS_DIR / f"{dataset_name}_combined.jsonl",
        DATASETS_DIR / f"{dataset_name}_train.jsonl",
        DATASETS_DIR / f"{dataset_name}_live.jsonl",
    ]

    examples = []
    seen_files = set()
    for path in candidates:
        if path.exists() and str(path) not in seen_files:
            seen_files.add(str(path))
            with open(path, "r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if line:
                        try:
                            examples.append(json.loads(line))
                        except json.JSONDecodeError:
                            continue

    log.info("Loaded %d examples for '%s'", len(examples), dataset_name)
    return examples


def _format_prompt(example: dict) -> str:
    """Format example into chat template for Gemma."""
    instruction = example.get("instruction", "")
    output = example.get("output", "")
    return (
        f"<start_of_turn>user\n{instruction}<end_of_turn>\n"
        f"<start_of_turn>model\n{output}<end_of_turn>"
    )


def check_dependencies() -> dict[str, bool]:
    """Check which training dependencies are available."""
    deps = {}
    for pkg in ["unsloth", "transformers", "peft", "trl", "torch", "datasets"]:
        try:
            __import__(pkg)
            deps[pkg] = True
        except (ImportError, Exception):
            deps[pkg] = False
    return deps


def _has_unsloth() -> bool:
    """Check if Unsloth is importable (fails on Windows due to Triton)."""
    try:
        from unsloth import FastLanguageModel  # noqa: F401
        return True
    except Exception:
        return False


# ── Run counter persistence ──────────────────────────────────────

_RUN_COUNTER_FILE = TRAINING_DIR / ".run_counter"


def _next_run_number() -> int:
    """Get and increment the persistent run counter."""
    n = 1
    if _RUN_COUNTER_FILE.exists():
        try:
            n = int(_RUN_COUNTER_FILE.read_text().strip()) + 1
        except (ValueError, OSError):
            n = 1
    _RUN_COUNTER_FILE.write_text(str(n))
    return n


def _collect_system_snapshot() -> dict:
    """Gather system, inference, and resource metrics from all subsystems.

    Returns:
        Dict with keys: system, inference, resources, benchmarks, pipeline.
        Each key may be empty if that subsystem isn't available.
    """
    snapshot: dict = {}

    # 1. System metrics (CPU, RAM, GPU)
    try:
        from engine.observability.metrics_db import get_metrics_db
        db = get_metrics_db()
        sys_history = db.get_system_history(seconds=60)
        if sys_history:
            latest = sys_history[-1]
            snapshot["system"] = {
                "cpu_pct": latest.get("cpu_pct", 0),
                "ram_pct": latest.get("ram_pct", 0),
                "gpu_vram_pct": latest.get("gpu_vram_pct", 0),
                "gpu_temp_c": latest.get("gpu_temp_c", 0),
                "lmstudio_ok": bool(latest.get("lmstudio_ok", 0)),
            }
        # Pipeline summary (latency, tps, ttft, kills)
        pipeline = db.get_pipeline_summary(seconds=300)
        if pipeline and pipeline.get("total", 0) > 0:
            snapshot["pipeline"] = {
                "total_requests": pipeline.get("total", 0),
                "avg_latency_ms": round(pipeline.get("avg_latency") or 0, 1),
                "avg_tps": round(pipeline.get("avg_tps") or 0, 1),
                "avg_ttft_ms": round(pipeline.get("avg_ttft") or 0, 1),
                "total_kills": int(pipeline.get("total_kills") or 0),
                "avg_tokens_in": round(pipeline.get("avg_tokens_in") or 0, 1),
                "avg_tokens_out": round(pipeline.get("avg_tokens_out") or 0, 1),
            }
    except Exception:
        pass

    # 2. Inference monitor (per-model TPS, latency, error rate)
    try:
        from engine.lmstudio.inference_monitor import InferenceMonitor
        monitor = InferenceMonitor()
        status = monitor.get_status()
        snapshot["inference"] = {
            "uptime_seconds": status.get("uptime_seconds", 0),
            "total_requests": status.get("total_requests", 0),
            "total_errors": status.get("total_errors", 0),
            "error_rate": status.get("error_rate", 0),
            "requests_per_minute": status.get("requests_per_minute", 0),
            "models": status.get("models", {}),
            "tiers": status.get("tiers", {}),
        }
    except Exception:
        pass

    # 3. Resource manager (VRAM, strategy, slots)
    try:
        from engine.lmstudio.resource_manager import get_resource_manager
        rm = get_resource_manager()
        rm_status = rm.get_status()
        snapshot["resources"] = {
            "strategy": rm_status.get("strategy", "unknown"),
            "vram_cap_mb": rm_status.get("vram_cap_mb", 0),
            "vram_used_mb": rm_status.get("vram_used_mb", 0),
            "vram_free_mb": rm_status.get("vram_free_mb", 0),
            "concurrent_slots": rm_status.get("concurrent_slots", 0),
            "active_slots": len(rm_status.get("slots", {})),
            "bg_queue_size": rm_status.get("bg_queue_size", 0),
        }
    except Exception:
        pass

    # 4. LLM KPIs (token speed, latency percentiles)
    try:
        from engine.logging.benchmark import get_benchmarks, get_llm_kpis
        benchmarks = get_benchmarks()
        llm_kpis = get_llm_kpis()
        snapshot["benchmarks"] = {
            "operations": benchmarks,
            "llm_kpis": {
                "count": llm_kpis.get("count", 0),
                "avg_tokens_per_sec": llm_kpis.get("avg_tokens_per_sec", 0),
                "p95_tokens_per_sec": llm_kpis.get("p95_tokens_per_sec", 0),
                "avg_latency_ms": llm_kpis.get("avg_latency_ms", 0),
                "p95_latency_ms": llm_kpis.get("p95_latency_ms", 0),
                "total_tokens_in": llm_kpis.get("total_tokens_in", 0),
                "total_tokens_out": llm_kpis.get("total_tokens_out", 0),
                "avg_first_token_ms": llm_kpis.get("avg_first_token_ms", 0),
                "models": llm_kpis.get("models", []),
            },
        }
    except Exception:
        pass

    return snapshot


def store_run_metrics(result: dict) -> Optional[str]:
    """Package training run metrics with full system context and store in Nexus.

    Collects scene metrics, token speed, resource management, inference
    performance, and pipeline stats alongside training results.

    Args:
        result: Training result dict from finetune().

    Returns:
        Nexus entry ID or None.
    """
    run_num = _next_run_number()
    title = result.get("run_title", f"Training Run #{run_num}")
    if f"#{run_num}" not in title:
        title = f"{title} (Run #{run_num})"

    description = result.get("run_description", "")

    # Collect system-wide metrics at time of training completion
    sys_snapshot = _collect_system_snapshot()

    content_lines = [
        f"# {title}",
        f"",
        f"**Run:** #{run_num}",
        f"**Dataset:** {result.get('dataset', 'unknown')}",
        f"**Backend:** {result.get('backend', 'auto')}",
        f"**Base Model:** {result.get('base_model', DEFAULT_BASE_MODEL)}",
        f"",
        f"## Hyperparameters",
        f"- Epochs: {result.get('epochs', '?')}",
        f"- Learning Rate: {result.get('learning_rate', '?')}",
        f"- Batch Size: {result.get('batch_size', '?')}",
        f"- LoRA Rank: {result.get('lora_r', '?')}",
        f"- LoRA Alpha: {result.get('lora_alpha', '?')}",
        f"- Max Seq Length: {result.get('max_seq_length', '?')}",
        f"- Gradient Accumulation: {result.get('gradient_accumulation', '?')}",
        f"",
        f"## Training Results",
        f"- Examples: {result.get('examples', '?')}",
        f"- Final Loss: {result.get('final_loss', '?')}",
        f"- Adapter Path: {result.get('adapter_path', 'n/a')}",
        f"- GGUF Path: {result.get('gguf_path', 'n/a')}",
    ]

    if result.get("accuracy") is not None:
        content_lines.extend([
            f"",
            f"## Evaluation",
            f"- Accuracy: {result['accuracy']:.1%}",
            f"- Correct: {result.get('correct', '?')}/{result.get('total', '?')}",
        ])

    # System metrics at training time
    if sys_snapshot.get("system"):
        s = sys_snapshot["system"]
        content_lines.extend([
            f"",
            f"## System State at Training",
            f"- CPU: {s['cpu_pct']:.1f}%",
            f"- RAM: {s['ram_pct']:.1f}%",
            f"- GPU VRAM: {s['gpu_vram_pct']:.1f}%",
            f"- GPU Temp: {s['gpu_temp_c']:.0f}°C",
            f"- LMStudio: {'online' if s['lmstudio_ok'] else 'offline'}",
        ])

    # Resource management
    if sys_snapshot.get("resources"):
        r = sys_snapshot["resources"]
        content_lines.extend([
            f"",
            f"## Resource Management",
            f"- Strategy: {r['strategy']}",
            f"- VRAM Cap: {r['vram_cap_mb']} MB",
            f"- VRAM Used: {r['vram_used_mb']} MB",
            f"- VRAM Free: {r['vram_free_mb']} MB",
            f"- Concurrent Slots: {r['concurrent_slots']}",
            f"- Active Model Slots: {r['active_slots']}",
            f"- Background Queue: {r['bg_queue_size']}",
        ])

    # Token speed / inference performance
    if sys_snapshot.get("benchmarks", {}).get("llm_kpis", {}).get("count", 0) > 0:
        k = sys_snapshot["benchmarks"]["llm_kpis"]
        content_lines.extend([
            f"",
            f"## Token Speed & Inference Performance",
            f"- Inference Calls: {k['count']}",
            f"- Avg Tokens/sec: {k['avg_tokens_per_sec']}",
            f"- P95 Tokens/sec: {k['p95_tokens_per_sec']}",
            f"- Avg Latency: {k['avg_latency_ms']}ms",
            f"- P95 Latency: {k['p95_latency_ms']}ms",
            f"- Avg First Token: {k['avg_first_token_ms']}ms",
            f"- Total Tokens In: {k['total_tokens_in']}",
            f"- Total Tokens Out: {k['total_tokens_out']}",
            f"- Models Used: {', '.join(k['models']) if k['models'] else 'n/a'}",
        ])

    # Pipeline summary
    if sys_snapshot.get("pipeline"):
        p = sys_snapshot["pipeline"]
        content_lines.extend([
            f"",
            f"## Pipeline Performance (last 5 min)",
            f"- Requests: {p['total_requests']}",
            f"- Avg Latency: {p['avg_latency_ms']}ms",
            f"- Avg TPS: {p['avg_tps']}",
            f"- Avg TTFT: {p['avg_ttft_ms']}ms",
            f"- Kill Switch Fires: {p['total_kills']}",
            f"- Avg Tokens In: {p['avg_tokens_in']}",
            f"- Avg Tokens Out: {p['avg_tokens_out']}",
        ])

    # Per-model inference breakdown
    if sys_snapshot.get("inference", {}).get("models"):
        content_lines.extend([
            f"",
            f"## Per-Model Inference Stats",
            f"| Model | Requests | Avg Latency | Avg TPS | Error Rate |",
            f"|-------|----------|-------------|---------|------------|",
        ])
        for name, m in sys_snapshot["inference"]["models"].items():
            content_lines.append(
                f"| {name} | {m.get('requests', 0)} | "
                f"{m.get('avg_latency_ms', 0):.0f}ms | "
                f"{m.get('avg_tps', 0):.1f} | "
                f"{m.get('error_rate', 0):.1%} |"
            )

    if description:
        content_lines.extend([f"", f"## Description", description])

    if result.get("gguf_error"):
        content_lines.extend([f"", f"## Warnings", f"- GGUF export failed: {result['gguf_error']}"])

    content = "\n".join(content_lines)

    # Full raw JSON with both training result and system snapshot
    full_metrics = {
        "training": result,
        "system_snapshot": sys_snapshot,
        "run_number": run_num,
    }
    metrics_json = json.dumps(full_metrics, indent=2, default=str)
    content += f"\n\n## Raw Metrics\n```json\n{metrics_json}\n```"

    try:
        from engine.nexus.client import get_nexus_client
        client = get_nexus_client()
        entry_id = client.add_entry(
            title=title,
            content=content,
            content_type="document",
            category="training",
            tags=["training", "finetune", result.get("dataset", ""), f"run-{run_num}"],
        )
        log.info("Run #%d metrics stored in Nexus: %s", run_num, entry_id)
        return entry_id
    except Exception as exc:
        log.warning("Failed to store run metrics in Nexus: %s", exc)
        metrics_path = Path(result.get("output_dir", ".")) / f"run_{run_num}_metrics.json"
        try:
            metrics_path.write_text(metrics_json, encoding="utf-8")
            log.info("Run metrics saved locally: %s", metrics_path)
        except Exception:
            pass
        return None


def finetune(
    dataset_name: str,
    base_model: str = DEFAULT_BASE_MODEL,
    output_dir: Optional[str] = None,
    epochs: int = 3,
    lr: float = 2e-4,
    lora_r: int = 16,
    lora_alpha: int = 16,
    batch_size: int = 4,
    max_seq_length: int = 512,
    gradient_accumulation: int = 4,
    export_gguf: bool = True,
    backend: str = "auto",
    run_title: str = "",
    run_description: str = "",
    store_in_nexus: bool = True,
) -> dict:
    """
    Train QLoRA adapter on CosySim dataset.

    Args:
        dataset_name: Dataset to train on (or 'all' for combined).
        base_model: HuggingFace model ID.
        output_dir: Where to save adapter + GGUF.
        epochs: Training epochs.
        lr: Learning rate.
        lora_r: LoRA rank.
        lora_alpha: LoRA alpha.
        batch_size: Per-device batch size.
        max_seq_length: Max token length.
        gradient_accumulation: Gradient accumulation steps.
        export_gguf: Whether to export GGUF after training.
        backend: "unsloth", "hf", or "auto" (tries unsloth first).

    Returns:
        Dict with training results (loss, path, etc.).
    """
    if output_dir is None:
        output_dir = str(OUTPUT_DIR / f"cosysim-{dataset_name}")
    os.makedirs(output_dir, exist_ok=True)

    # Load data
    if dataset_name == "all":
        examples = []
        for ds in ALL_DATASETS:
            examples.extend(_load_dataset(ds))
    else:
        examples = _load_dataset(dataset_name)

    if not examples:
        raise ValueError(f"No training data found for '{dataset_name}'")

    # Select backend
    use_unsloth = False
    if backend == "auto":
        use_unsloth = _has_unsloth()
    elif backend == "unsloth":
        use_unsloth = True

    if use_unsloth:
        result = _finetune_unsloth(
            examples, base_model, output_dir, epochs, lr,
            lora_r, lora_alpha, batch_size, max_seq_length,
            gradient_accumulation, export_gguf, dataset_name,
        )
    else:
        result = _finetune_hf(
            examples, base_model, output_dir, epochs, lr,
            lora_r, lora_alpha, batch_size, max_seq_length,
            gradient_accumulation, dataset_name,
        )

    # Store run metrics in Nexus
    if store_in_nexus:
        result["run_title"] = run_title or f"Finetune: {dataset_name}"
        result["run_description"] = run_description
        result["base_model"] = base_model
        result["lora_r"] = lora_r
        result["lora_alpha"] = lora_alpha
        result["learning_rate"] = lr
        result["batch_size"] = batch_size
        result["max_seq_length"] = max_seq_length
        result["gradient_accumulation"] = gradient_accumulation
        store_run_metrics(result)

    return result


def _finetune_unsloth(
    examples: list, base_model: str, output_dir: str,
    epochs: int, lr: float, lora_r: int, lora_alpha: int,
    batch_size: int, max_seq_length: int, gradient_accumulation: int,
    export_gguf: bool, dataset_name: str,
) -> dict:
    """Train using Unsloth (Linux/Colab, 4-bit QLoRA)."""
    from unsloth import FastLanguageModel
    from trl import SFTTrainer, SFTConfig
    import torch

    log.info("Loading base model: %s", base_model)
    model, tokenizer = FastLanguageModel.from_pretrained(
        model_name=base_model,
        max_seq_length=max_seq_length,
        dtype=None,  # auto-detect
        load_in_4bit=True,
    )

    log.info("Applying LoRA adapters (r=%d, alpha=%d)", lora_r, lora_alpha)
    model = FastLanguageModel.get_peft_model(
        model,
        r=lora_r,
        lora_alpha=lora_alpha,
        target_modules=["q_proj", "k_proj", "v_proj", "o_proj",
                        "gate_proj", "up_proj", "down_proj"],
        lora_dropout=0,
        bias="none",
        use_gradient_checkpointing="unsloth",
    )

    # Format examples
    formatted = [_format_prompt(ex) for ex in examples]
    log.info("Formatted %d training examples", len(formatted))

    # Create HF dataset
    from datasets import Dataset
    train_dataset = Dataset.from_dict({"text": formatted})

    # Configure trainer
    training_args = SFTConfig(
        output_dir=output_dir,
        num_train_epochs=epochs,
        per_device_train_batch_size=batch_size,
        gradient_accumulation_steps=gradient_accumulation,
        learning_rate=lr,
        weight_decay=0.01,
        warmup_steps=5,
        logging_steps=10,
        save_strategy="epoch",
        bf16=torch.cuda.is_available(),
        fp16=False,
        max_seq_length=max_seq_length,
        dataset_text_field="text",
        packing=False,
    )

    trainer = SFTTrainer(
        model=model,
        tokenizer=tokenizer,
        train_dataset=train_dataset,
        args=training_args,
    )

    log.info("Starting training: %d examples, %d epochs", len(examples), epochs)
    train_result = trainer.train()

    # Save adapter
    adapter_path = os.path.join(output_dir, "adapter")
    model.save_pretrained(adapter_path)
    tokenizer.save_pretrained(adapter_path)
    log.info("Adapter saved to %s", adapter_path)

    result = {
        "dataset": dataset_name,
        "examples": len(examples),
        "epochs": epochs,
        "final_loss": train_result.training_loss,
        "adapter_path": adapter_path,
        "output_dir": output_dir,
    }

    # Export GGUF
    if export_gguf:
        try:
            gguf_path = os.path.join(output_dir, "gguf")
            model.save_pretrained_gguf(
                gguf_path,
                tokenizer,
                quantization_method="q4_k_m",
            )
            result["gguf_path"] = gguf_path
            log.info("GGUF exported to %s", gguf_path)
        except Exception as exc:
            log.warning("GGUF export failed: %s", exc)
            result["gguf_error"] = str(exc)

    return result


def _finetune_hf(
    examples: list, base_model: str, output_dir: str,
    epochs: int, lr: float, lora_r: int, lora_alpha: int,
    batch_size: int, max_seq_length: int, gradient_accumulation: int,
    dataset_name: str,
) -> dict:
    """Train using HuggingFace Transformers + PEFT (Windows-compatible, no Triton)."""
    from transformers import AutoModelForCausalLM, AutoTokenizer
    from peft import LoraConfig, get_peft_model, TaskType
    from trl import SFTTrainer, SFTConfig
    from datasets import Dataset
    import torch

    log.info("[HF backend] Loading base model: %s", base_model)
    tokenizer = AutoTokenizer.from_pretrained(base_model)
    if tokenizer.pad_token is None:
        tokenizer.pad_token = tokenizer.eos_token

    model = AutoModelForCausalLM.from_pretrained(
        base_model,
        torch_dtype=torch.float16 if torch.cuda.is_available() else torch.float32,
        device_map="auto" if torch.cuda.is_available() else None,
    )

    lora_config = LoraConfig(
        task_type=TaskType.CAUSAL_LM,
        r=lora_r,
        lora_alpha=lora_alpha,
        target_modules=["q_proj", "k_proj", "v_proj", "o_proj",
                        "gate_proj", "up_proj", "down_proj"],
        lora_dropout=0.05,
        bias="none",
    )
    model = get_peft_model(model, lora_config)
    log.info("[HF backend] LoRA applied (r=%d, alpha=%d), trainable params: %d",
             lora_r, lora_alpha, model.num_parameters(only_trainable=True))

    formatted = [_format_prompt(ex) for ex in examples]
    train_dataset = Dataset.from_dict({"text": formatted})

    training_args = SFTConfig(
        output_dir=output_dir,
        num_train_epochs=epochs,
        per_device_train_batch_size=batch_size,
        gradient_accumulation_steps=gradient_accumulation,
        learning_rate=lr,
        weight_decay=0.01,
        warmup_steps=5,
        logging_steps=10,
        save_strategy="epoch",
        bf16=False,
        fp16=torch.cuda.is_available(),
        max_seq_length=max_seq_length,
        dataset_text_field="text",
        packing=False,
    )

    trainer = SFTTrainer(
        model=model,
        tokenizer=tokenizer,
        train_dataset=train_dataset,
        args=training_args,
    )

    log.info("[HF backend] Training: %d examples, %d epochs", len(examples), epochs)
    train_result = trainer.train()

    adapter_path = os.path.join(output_dir, "adapter")
    model.save_pretrained(adapter_path)
    tokenizer.save_pretrained(adapter_path)
    log.info("[HF backend] Adapter saved to %s", adapter_path)

    return {
        "backend": "hf",
        "dataset": dataset_name,
        "examples": len(examples),
        "epochs": epochs,
        "final_loss": train_result.training_loss,
        "adapter_path": adapter_path,
        "output_dir": output_dir,
    }


def evaluate_model(
    adapter_path: str,
    dataset_name: str,
    base_model: str = DEFAULT_BASE_MODEL,
    max_samples: int = 50,
) -> dict:
    """
    Evaluate a fine-tuned adapter on validation data.

    Returns accuracy metrics.
    """
    val_path = DATASETS_DIR / f"{dataset_name}_val.jsonl"
    if not val_path.exists():
        raise FileNotFoundError(f"No validation set: {val_path}")

    examples = []
    with open(val_path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                try:
                    examples.append(json.loads(line))
                except json.JSONDecodeError:
                    continue

    if not examples:
        raise ValueError(f"Empty validation set for '{dataset_name}'")

    examples = examples[:max_samples]

    deps = check_dependencies()
    if not deps.get("unsloth"):
        raise ImportError("Unsloth required for evaluation")

    from unsloth import FastLanguageModel

    model, tokenizer = FastLanguageModel.from_pretrained(
        model_name=base_model,
        max_seq_length=512,
        load_in_4bit=True,
    )
    model = FastLanguageModel.get_peft_model(model, r=16)
    # Load adapter weights
    model.load_adapter(adapter_path)
    FastLanguageModel.for_inference(model)

    correct = 0
    total = 0
    for ex in examples:
        prompt = f"<start_of_turn>user\n{ex['instruction']}<end_of_turn>\n<start_of_turn>model\n"
        inputs = tokenizer(prompt, return_tensors="pt").to(model.device)
        outputs = model.generate(**inputs, max_new_tokens=256)
        generated = tokenizer.decode(outputs[0], skip_special_tokens=True)

        # Simple exact match (could be more sophisticated)
        expected = ex.get("output", "")
        if expected.strip() in generated:
            correct += 1
        total += 1

    return {
        "dataset": dataset_name,
        "total": total,
        "correct": correct,
        "accuracy": correct / total if total > 0 else 0.0,
        "adapter_path": adapter_path,
    }


if __name__ == "__main__":
    import argparse

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s")

    parser = argparse.ArgumentParser(description="Local fine-tuning for Gemma 270M router")
    sub = parser.add_subparsers(dest="command", help="Command")

    # Train command
    train_p = sub.add_parser("train", help="Train a LoRA adapter")
    train_p.add_argument("--dataset", type=str, default="tag_extraction")
    train_p.add_argument("--base-model", type=str, default=DEFAULT_BASE_MODEL)
    train_p.add_argument("--epochs", type=int, default=3)
    train_p.add_argument("--lr", type=float, default=2e-4)
    train_p.add_argument("--lora-r", type=int, default=16)
    train_p.add_argument("--batch-size", type=int, default=4)
    train_p.add_argument("--output-dir", type=str, default=None)
    train_p.add_argument("--no-gguf", action="store_true")
    train_p.add_argument("--backend", type=str, default="auto",
                         choices=["auto", "unsloth", "hf"],
                         help="Training backend (default: auto)")
    train_p.add_argument("--run-title", type=str, default="",
                         help="Title for this run (stored in Nexus)")
    train_p.add_argument("--run-description", type=str, default="",
                         help="Description of experiment goals/changes")
    train_p.add_argument("--no-nexus", action="store_true",
                         help="Skip storing metrics in Nexus")

    # Evaluate command
    eval_p = sub.add_parser("eval", help="Evaluate adapter on validation set")
    eval_p.add_argument("--adapter", type=str, required=True)
    eval_p.add_argument("--dataset", type=str, default="tag_extraction")
    eval_p.add_argument("--max-samples", type=int, default=50)

    # Check command
    sub.add_parser("check", help="Check training dependencies")

    # Data stats command
    sub.add_parser("stats", help="Show dataset statistics")

    args = parser.parse_args()

    if args.command == "check":
        deps = check_dependencies()
        for pkg, ok in deps.items():
            status = "✓" if ok else "✗"
            print(f"  {status} {pkg}")
    elif args.command == "stats":
        from training.prepare_from_live import get_dataset_stats
        for name, counts in get_dataset_stats().items():
            total = sum(counts.values())
            print(f"  {name}: {counts} (total: {total})")
    elif args.command == "eval":
        result = evaluate_model(args.adapter, args.dataset, max_samples=args.max_samples)
        print(f"Accuracy: {result['accuracy']:.1%} ({result['correct']}/{result['total']})")
    elif args.command == "train":
        result = finetune(
            dataset_name=args.dataset,
            base_model=args.base_model,
            output_dir=args.output_dir,
            epochs=args.epochs,
            lr=args.lr,
            lora_r=args.lora_r,
            batch_size=args.batch_size,
            export_gguf=not args.no_gguf,
            backend=args.backend,
            run_title=args.run_title,
            run_description=args.run_description,
            store_in_nexus=not args.no_nexus,
        )
        print(f"Training complete: {result}")
    else:
        parser.print_help()
