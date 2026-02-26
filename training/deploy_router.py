"""Auto-deploy a trained router GGUF to LMStudio.

Usage:
    python -m training.deploy_router path/to/model.gguf [--model-key cosysim-router-v1]
"""
from __future__ import annotations

import argparse
import logging
import os
import shutil
import sys
from pathlib import Path

logger = logging.getLogger(__name__)


def find_lmstudio_models_dir() -> Path:
    """Find the LMStudio models directory.

    Returns:
        Path to the LMStudio models directory.
    """
    candidates = [
        Path.home() / ".cache" / "lm-studio" / "models",
        Path.home() / ".lmstudio" / "models",
        Path(os.environ.get("LMSTUDIO_MODELS_DIR", "")),
    ]
    for p in candidates:
        if p.exists():
            return p
    return Path.home() / ".cache" / "lm-studio" / "models"


def deploy(gguf_path: str, model_key: str = "cosysim-router-v1") -> dict:
    """Deploy a GGUF model to LMStudio models directory.

    Args:
        gguf_path: Path to the GGUF file.
        model_key: Model identifier for config.

    Returns:
        Deployment result dict.
    """
    src = Path(gguf_path)
    if not src.exists():
        return {"success": False, "error": f"File not found: {gguf_path}"}

    models_dir = find_lmstudio_models_dir()
    dest_dir = models_dir / model_key
    dest_dir.mkdir(parents=True, exist_ok=True)
    dest = dest_dir / src.name

    logger.info("Deploying %s → %s", src, dest)
    shutil.copy2(str(src), str(dest))

    # Update config
    try:
        from engine.config import get_config
        cfg = get_config()
        cfg.set("lmstudio.models.router.key", model_key)
        cfg.set("lmstudio.models.router.enabled", True)
        logger.info("Config updated: router.key = %s", model_key)
    except Exception as e:
        logger.warning("Config update skipped: %s", e)

    result = {
        "success": True,
        "source": str(src),
        "destination": str(dest),
        "model_key": model_key,
        "file_size_mb": round(src.stat().st_size / (1024 * 1024), 1),
    }
    logger.info("Router deployed: %s", result)
    return result


def main() -> None:
    """CLI entry point."""
    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")

    parser = argparse.ArgumentParser(
        description="Deploy trained router GGUF to LMStudio"
    )
    parser.add_argument("gguf_path", help="Path to the GGUF model file")
    parser.add_argument(
        "--model-key",
        default="cosysim-router-v1",
        help="Model key for config (default: cosysim-router-v1)",
    )
    args = parser.parse_args()

    result = deploy(args.gguf_path, args.model_key)
    if result["success"]:
        logger.info(
            "Deployed %.1fMB -> %s (key: %s)",
            result["file_size_mb"],
            result["destination"],
            result["model_key"],
        )
    else:
        logger.error("%s", result["error"])
        sys.exit(1)


if __name__ == "__main__":
    main()
