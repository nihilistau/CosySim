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
        except ImportError:
            deps[pkg] = False
    return deps


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

    Returns:
        Dict with training results (loss, path, etc.).
    """
    # Resolve output directory
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

    # Check deps
    deps = check_dependencies()
    missing = [k for k, v in deps.items() if not v]
    if missing:
        raise ImportError(
            f"Missing training dependencies: {', '.join(missing)}. "
            f"Install with: pip install unsloth transformers peft trl datasets"
        )

    # Dynamic imports (only if deps available)
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
        )
        print(f"Training complete: {result}")
    else:
        parser.print_help()
