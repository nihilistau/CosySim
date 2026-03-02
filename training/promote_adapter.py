"""training/promote_adapter.py — Register and promote a Colab-trained adapter.

After downloading the adapter zip from Colab:
1. Extract it to training/models/router_v3_final/
2. Run: python training/promote_adapter.py --adapter training/models/router_v3_final
                                            --model-type router_v3
                                            --base-model Qwen/Qwen2.5-0.5B-Instruct
                                            --promote

This registers the adapter in ModelRegistry, stores metrics in Nexus, and
optionally promotes it as the active router_v3 model.
"""
from __future__ import annotations

import argparse
import json
import logging
import sys
from pathlib import Path

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
logger = logging.getLogger(__name__)


def _load_metrics(adapter_dir: Path) -> dict:
    """Load metrics.json from adapter directory if present."""
    metrics_path = adapter_dir / "metrics.json"
    if metrics_path.exists():
        with open(metrics_path) as f:
            return json.load(f)
    return {}


def _store_in_nexus(model_id: str, model_type: str, metrics: dict) -> None:
    """Store training results in Nexus."""
    try:
        import sys
        sys.path.insert(0, str(Path(__file__).parent.parent))
        from engine.nexus.client import get_nexus_client

        client = get_nexus_client()
        accuracy = metrics.get("val_accuracy", "?")
        train_loss = metrics.get("train_loss", "?")

        content = (
            f"Model type: {model_type}\n"
            f"Model ID: {model_id}\n"
            f"Base model: {metrics.get('model', 'Qwen2.5-0.5B-Instruct')}\n"
            f"Dataset: {metrics.get('dataset', 'router_v3')}\n"
            f"Train examples: {metrics.get('train_examples', '?')}\n"
            f"Val accuracy: {accuracy}%\n"
            f"Train loss: {train_loss}\n"
            f"Val correct: {metrics.get('val_correct', '?')}/{metrics.get('val_total', '?')}\n"
        )

        client.add_entry(
            title=f"Fine-tune result: {model_type} ({model_id})",
            content=content,
            content_type="note",
            category="training",
        )
        client.add_qa(
            question=f"What is the accuracy of the trained {model_type} router?",
            answer=f"Val accuracy: {accuracy}% (model_id={model_id}, loss={train_loss})",
            category="training",
        )
        logger.info("Results stored in Nexus")
    except Exception as exc:
        logger.warning("Could not store in Nexus: %s", exc)


def promote(
    adapter_path: str,
    model_type: str = "router_v3",
    base_model: str = "Qwen/Qwen2.5-0.5B-Instruct",
    merged_path: str | None = None,
    do_promote: bool = False,
) -> None:
    """Register adapter and optionally promote it.

    Args:
        adapter_path: Path to the LoRA adapter directory.
        model_type: Registry model type key.
        base_model: HuggingFace base model ID.
        merged_path: Path to merged 16-bit model if available.
        do_promote: If True, promote as active model for this type.
    """
    import sys
    sys.path.insert(0, str(Path(__file__).parent.parent))
    from training.model_registry import get_model_registry

    adapter_dir = Path(adapter_path).resolve()
    if not adapter_dir.exists():
        logger.error("Adapter directory not found: %s", adapter_dir)
        sys.exit(1)

    metrics = _load_metrics(adapter_dir)
    logger.info("Adapter: %s", adapter_dir)
    logger.info("Metrics: %s", metrics)

    registry = get_model_registry()

    # Register
    model = registry.register(
        model_type=model_type,
        adapter_path=str(adapter_dir),
        base_model=base_model,
        merged_path=merged_path,
        notes=f"Colab-trained. val_accuracy={metrics.get('val_accuracy', '?')}%",
    )
    logger.info("Registered as model_id: %s", model.model_id)

    # Update benchmark score from val_accuracy
    if "val_accuracy" in metrics:
        score = float(metrics["val_accuracy"]) / 100.0
        registry.update_benchmark(model.model_id, score=score, details=metrics)
        logger.info("Benchmark score: %.3f", score)

    # Store in Nexus
    _store_in_nexus(model.model_id, model_type, metrics)

    # Promote if requested
    if do_promote:
        registry.promote(model_type, model.model_id)
        logger.info("Promoted %s as active %s model", model.model_id, model_type)
    else:
        # Auto-promote if this is the best
        promoted = registry.auto_promote(model_type)
        if promoted and promoted.model_id == model.model_id:
            logger.info("Auto-promoted %s (best score)", model.model_id)
        else:
            logger.info("Not promoted (another model has higher score). Use --promote to force.")

    print(f"\n✓ Model registered: {model.model_id}")
    print(f"  Type:     {model_type}")
    print(f"  Adapter:  {adapter_dir}")
    print(f"  Score:    {metrics.get('val_accuracy', '?')}% val accuracy")
    print(f"  Active:   {registry._models[model.model_id].active}")


def main() -> None:
    """CLI entry point."""
    parser = argparse.ArgumentParser(description="Promote Colab-trained adapter to ModelRegistry")
    parser.add_argument("--adapter", required=True, help="Path to adapter directory")
    parser.add_argument("--model-type", default="router_v3", help="Model type key")
    parser.add_argument("--base-model", default="Qwen/Qwen2.5-0.5B-Instruct",
                        help="HuggingFace base model ID")
    parser.add_argument("--merged", default=None,
                        help="Path to merged 16-bit model directory (optional)")
    parser.add_argument("--promote", action="store_true",
                        help="Force promote as active model (auto-promotes if best)")
    args = parser.parse_args()

    promote(
        adapter_path=args.adapter,
        model_type=args.model_type,
        base_model=args.base_model,
        merged_path=args.merged,
        do_promote=args.promote,
    )


if __name__ == "__main__":
    main()
