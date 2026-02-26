"""LlmsterManager — CLI wrapper for the ``lms`` (llmster) daemon.

Provides programmatic control over the LMStudio daemon process,
model loading with continuous batching (n_parallel), server management,
and runtime updates.  All operations go through the ``lms`` CLI.

Usage::

    from engine.lmstudio.llmster_manager import get_llmster_manager

    mgr = get_llmster_manager()
    print(mgr.daemon_status())
    mgr.load_model("qwen/qwen3-8b", n_parallel=4)
"""
from __future__ import annotations

import json
import logging
import shutil
import subprocess
import threading
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from engine.config import get_config

logger = logging.getLogger(__name__)


# ── Data Models ────────────────────────────────────────────────────────

@dataclass
class LlmsterStatus:
    """Status snapshot of the llmster daemon and server."""

    daemon_running: bool = False
    server_running: bool = False
    server_port: int = 0
    loaded_models: List[Dict[str, Any]] = field(default_factory=list)
    cli_version: str = ""
    error: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return {
            "daemon_running": self.daemon_running,
            "server_running": self.server_running,
            "server_port": self.server_port,
            "loaded_models": self.loaded_models,
            "cli_version": self.cli_version,
            "error": self.error,
        }


@dataclass
class ModelLoadResult:
    """Result of a model load operation."""

    success: bool = False
    model_id: str = ""
    instance_id: str = ""
    n_parallel: int = 1
    context_length: int = 0
    error: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return {
            "success": self.success,
            "model_id": self.model_id,
            "instance_id": self.instance_id,
            "n_parallel": self.n_parallel,
            "context_length": self.context_length,
            "error": self.error,
        }


# ── LlmsterManager ────────────────────────────────────────────────────

class LlmsterManager:
    """Wraps the ``lms`` CLI for daemon, server, and model management.

    Args:
        lms_path: Explicit path to the ``lms`` binary.  If None,
            resolved from config or ``shutil.which``.
    """

    def __init__(self, lms_path: Optional[str] = None) -> None:
        cfg = get_config()
        self._lms = (
            lms_path
            or cfg.get("lmstudio.llmster.lms_path", "")
            or shutil.which("lms")
            or "lms"
        )
        self._default_n_parallel: int = cfg.get(
            "lmstudio.llmster.default_n_parallel", 4
        )
        self._unified_kv: bool = cfg.get(
            "lmstudio.llmster.unified_kv_cache", True
        )
        self._lock = threading.Lock()

    # ── CLI helpers ─────────────────────────────────────────────────

    def _run(
        self,
        args: List[str],
        timeout: int = 30,
        check: bool = False,
    ) -> subprocess.CompletedProcess:
        """Run an ``lms`` sub-command and return the result."""
        cmd = [self._lms] + args
        logger.debug("llmster cmd: %s", " ".join(cmd))
        try:
            return subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=timeout,
                check=check,
            )
        except FileNotFoundError:
            logger.error("lms binary not found at %s", self._lms)
            raise
        except subprocess.TimeoutExpired:
            logger.warning("lms command timed out: %s", " ".join(cmd))
            raise

    def _run_json(self, args: List[str], timeout: int = 30) -> Any:
        """Run ``lms`` and parse JSON output."""
        result = self._run(args + ["--json"], timeout=timeout)
        if result.returncode != 0:
            logger.warning("lms returned %d: %s", result.returncode, result.stderr)
            return None
        try:
            return json.loads(result.stdout)
        except (json.JSONDecodeError, ValueError):
            return result.stdout.strip()

    # ── Daemon Control ─────────────────────────────────────────────

    def daemon_status(self) -> LlmsterStatus:
        """Check daemon and server status."""
        status = LlmsterStatus()
        try:
            result = self._run(["status"], timeout=10)
            output = result.stdout + result.stderr
            status.daemon_running = result.returncode == 0
            if "port" in output.lower():
                for word in output.split():
                    if word.isdigit():
                        port = int(word)
                        if 1000 <= port <= 65535:
                            status.server_port = port
                            status.server_running = True
                            break

            # Try to get version
            ver = self._run(["version"], timeout=5)
            if ver.returncode == 0:
                status.cli_version = ver.stdout.strip()

            # Get loaded models
            status.loaded_models = self.list_loaded()

        except FileNotFoundError:
            status.error = f"lms binary not found at {self._lms}"
        except Exception as exc:
            status.error = str(exc)

        return status

    def daemon_up(self) -> bool:
        """Start the llmster daemon."""
        with self._lock:
            try:
                result = self._run(["daemon", "up"], timeout=30)
                success = result.returncode == 0
                if success:
                    logger.info("Llmster daemon started")
                else:
                    logger.warning("Daemon start failed: %s", result.stderr)
                return success
            except Exception as exc:
                logger.error("Failed to start daemon: %s", exc)
                return False

    def daemon_down(self) -> bool:
        """Stop the llmster daemon."""
        with self._lock:
            try:
                result = self._run(["daemon", "down"], timeout=15)
                success = result.returncode == 0
                if success:
                    logger.info("Llmster daemon stopped")
                return success
            except Exception as exc:
                logger.error("Failed to stop daemon: %s", exc)
                return False

    # ── Server Control ─────────────────────────────────────────────

    def server_start(self, port: int = 1234) -> bool:
        """Start the LMStudio server."""
        try:
            result = self._run(["server", "start", "--port", str(port)], timeout=15)
            return result.returncode == 0
        except Exception as exc:
            logger.error("Server start failed: %s", exc)
            return False

    def server_stop(self) -> bool:
        """Stop the LMStudio server."""
        try:
            result = self._run(["server", "stop"], timeout=15)
            return result.returncode == 0
        except Exception as exc:
            logger.error("Server stop failed: %s", exc)
            return False

    # ── Model Operations ───────────────────────────────────────────

    def load_model(
        self,
        model_id: str,
        n_parallel: Optional[int] = None,
        gpu_offload: Optional[float] = None,
        context_length: Optional[int] = None,
    ) -> ModelLoadResult:
        """Load a model with optional continuous batching configuration.

        Args:
            model_id: Model identifier (e.g. "qwen/qwen3-8b").
            n_parallel: Number of concurrent inference slots (continuous batching).
            gpu_offload: GPU offload ratio (0.0 to 1.0).
            context_length: Context window size.

        Returns:
            ModelLoadResult with load outcome.
        """
        n_par = n_parallel if n_parallel is not None else self._default_n_parallel
        args = ["load", model_id]

        if n_par > 1:
            args.extend(["--n-parallel", str(n_par)])
        if gpu_offload is not None:
            args.extend(["--gpu-offload", str(gpu_offload)])
        if context_length is not None:
            args.extend(["--context-length", str(context_length)])

        result_obj = ModelLoadResult(model_id=model_id, n_parallel=n_par)

        try:
            result = self._run(args, timeout=120)
            if result.returncode == 0:
                result_obj.success = True
                logger.info(
                    "Loaded %s with n_parallel=%d", model_id, n_par
                )
                # Try to extract instance_id from output
                for line in result.stdout.split("\n"):
                    if "instance" in line.lower():
                        parts = line.split()
                        for p in parts:
                            if len(p) > 8 and not p.startswith("-"):
                                result_obj.instance_id = p
                                break
            else:
                result_obj.error = result.stderr.strip() or result.stdout.strip()
                logger.warning("Load failed for %s: %s", model_id, result_obj.error)
        except Exception as exc:
            result_obj.error = str(exc)
            logger.error("Load exception for %s: %s", model_id, exc)

        return result_obj

    def unload_model(self, model_id: str) -> bool:
        """Unload a model from memory."""
        try:
            result = self._run(["unload", model_id], timeout=30)
            if result.returncode == 0:
                logger.info("Unloaded %s", model_id)
            return result.returncode == 0
        except Exception as exc:
            logger.error("Unload failed for %s: %s", model_id, exc)
            return False

    def list_models(self) -> List[Dict[str, Any]]:
        """List models available on disk."""
        try:
            result = self._run(["ls"], timeout=15)
            if result.returncode != 0:
                return []
            models = []
            for line in result.stdout.strip().split("\n"):
                line = line.strip()
                if line and not line.startswith(("-", "=", "MODEL", "model")):
                    models.append({"id": line.split()[0] if line.split() else line})
            return models
        except Exception as exc:
            logger.error("List models failed: %s", exc)
            return []

    def list_loaded(self) -> List[Dict[str, Any]]:
        """List currently loaded models."""
        try:
            result = self._run(["ps"], timeout=10)
            if result.returncode != 0:
                return []
            models = []
            for line in result.stdout.strip().split("\n"):
                line = line.strip()
                if line and not line.startswith(("-", "=", "MODEL", "model", "TYPE")):
                    parts = line.split()
                    if parts:
                        models.append({
                            "id": parts[0],
                            "type": parts[1] if len(parts) > 1 else "llm",
                        })
            return models
        except Exception as exc:
            logger.error("List loaded failed: %s", exc)
            return []

    def download_model(self, model_id: str) -> bool:
        """Download a model from the catalog."""
        try:
            result = self._run(["get", model_id], timeout=600)
            if result.returncode == 0:
                logger.info("Downloaded %s", model_id)
            return result.returncode == 0
        except Exception as exc:
            logger.error("Download failed for %s: %s", model_id, exc)
            return False

    def runtime_update(self, backend: str = "llama.cpp") -> bool:
        """Update the inference runtime."""
        try:
            result = self._run(["runtime", "update", backend], timeout=120)
            return result.returncode == 0
        except Exception as exc:
            logger.error("Runtime update failed: %s", exc)
            return False

    def get_server_info(self) -> Dict[str, Any]:
        """Get comprehensive server info."""
        status = self.daemon_status()
        return {
            **status.to_dict(),
            "lms_path": self._lms,
            "default_n_parallel": self._default_n_parallel,
            "unified_kv_cache": self._unified_kv,
        }


# ── Singleton ──────────────────────────────────────────────────────────

_manager: Optional[LlmsterManager] = None
_manager_lock = threading.Lock()


def get_llmster_manager() -> LlmsterManager:
    """Get the singleton LlmsterManager instance."""
    global _manager
    if _manager is None:
        with _manager_lock:
            if _manager is None:
                _manager = LlmsterManager()
    return _manager
