"""
Merge multiple LoRA adapters into a single model and export to GGUF.

Sequentially applies adapters to the base model, merging each before
loading the next. Useful for combining task-specific adapters (e.g.
tag_extraction + tool_routing) into one deployable model.

Usage:
    python -m training.merge_adapters --adapters path/a path/b --output merged
    python -m training.merge_adapters --adapters path/a --output merged --no-gguf
"""

from __future__ import annotations

import logging
import os
from pathlib import Path
from typing import List, Optional

log = logging.getLogger(__name__)

TRAINING_DIR = Path(__file__).parent
OUTPUT_DIR = TRAINING_DIR / "output"

DEFAULT_BASE_MODEL = "google/gemma-3-270m-it"


def check_dependencies() -> dict[str, bool]:
    """Check which merge dependencies are available."""
    deps = {}
    for pkg in ["unsloth", "transformers", "peft", "torch"]:
        try:
            __import__(pkg)
            deps[pkg] = True
        except (ImportError, Exception):
            deps[pkg] = False
    return deps


def merge_adapters(
    adapter_paths: List[str],
    base_model: str = DEFAULT_BASE_MODEL,
    output_dir: Optional[str] = None,
    export_gguf: bool = True,
    max_seq_length: int = 512,
) -> dict:
    """
    Merge multiple LoRA adapters sequentially into one model.

    Loads the base model, then for each adapter: loads it, calls
    ``merge_and_unload``, and repeats. The fully-merged model is saved
    and optionally exported to GGUF.

    Args:
        adapter_paths: Ordered list of adapter directories to merge.
        base_model: HuggingFace model ID for the base model.
        output_dir: Where to save the merged model and GGUF.
        export_gguf: Whether to export GGUF after merging.
        max_seq_length: Max sequence length for model loading.

    Returns:
        Dict with ``merged_path``, ``adapter_count``, and ``gguf_path``.
    """
    if not adapter_paths:
        raise ValueError("At least one adapter path is required")

    for p in adapter_paths:
        if not Path(p).exists():
            raise FileNotFoundError(f"Adapter not found: {p}")

    if output_dir is None:
        output_dir = str(OUTPUT_DIR / "merged")
    os.makedirs(output_dir, exist_ok=True)

    # Check deps
    deps = check_dependencies()
    missing = [k for k, v in deps.items() if not v]
    if missing:
        raise ImportError(
            f"Missing dependencies: {', '.join(missing)}. "
            f"Install with: pip install unsloth transformers peft torch"
        )

    from unsloth import FastLanguageModel
    from peft import PeftModel

    # Load base model
    log.info("Loading base model: %s", base_model)
    model, tokenizer = FastLanguageModel.from_pretrained(
        model_name=base_model,
        max_seq_length=max_seq_length,
        dtype=None,
        load_in_4bit=False,
    )

    # Sequential merge
    for i, adapter_path in enumerate(adapter_paths):
        log.info("Merging adapter %d/%d: %s", i + 1, len(adapter_paths), adapter_path)
        model = PeftModel.from_pretrained(model, adapter_path)
        model = model.merge_and_unload()

    # Save merged model
    merged_path = os.path.join(output_dir, "merged_model")
    model.save_pretrained(merged_path)
    tokenizer.save_pretrained(merged_path)
    log.info("Merged model saved to %s", merged_path)

    result = {
        "merged_path": merged_path,
        "adapter_count": len(adapter_paths),
        "gguf_path": None,
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


if __name__ == "__main__":
    import argparse

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s")

    parser = argparse.ArgumentParser(
        description="Merge multiple LoRA adapters into one model"
    )
    parser.add_argument(
        "--adapters", nargs="+", required=True,
        help="Paths to adapter directories (merged in order)",
    )
    parser.add_argument("--base-model", type=str, default=DEFAULT_BASE_MODEL)
    parser.add_argument("--output", type=str, default=None, dest="output_dir")
    parser.add_argument("--no-gguf", action="store_true")
    parser.add_argument("--max-seq-length", type=int, default=512)

    args = parser.parse_args()

    result = merge_adapters(
        adapter_paths=args.adapters,
        base_model=args.base_model,
        output_dir=args.output_dir,
        export_gguf=not args.no_gguf,
        max_seq_length=args.max_seq_length,
    )
    print(f"Merge complete: {result}")
