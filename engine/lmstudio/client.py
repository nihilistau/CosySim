"""
LMStudioManager — CosySim integration layer for LMStudio

Provides a clean, config-aware interface to the LMStudio Python SDK
and CLI tool.  All VRAM estimation and model lifecycle methods are
hardware-aware (defaults tuned for RTX 2060 12 GB / 32 GB RAM / i9).

Usage::

    from engine.lmstudio import get_lmstudio_manager
    mgr = get_lmstudio_manager()

    if mgr.is_server_running():
        loaded = mgr.list_loaded_models()
        mgr.load_model("llama-3-8b-instruct")

Design notes
------------
- All CLI calls use ``subprocess`` with ``lms <cmd> --json`` so output is
  always machine-parseable.
- The SDK path (``lmstudio`` package) is used for chat / actor calls; the
  CLI is used for model management operations that are not yet in the SDK.
- ``estimate_vram_needed()`` uses ``lms load --estimate-only`` which prints
  a VRAM estimate without actually loading the model.
- The global singleton is retrieved via ``get_lmstudio_manager()`` so that
  callers never need to manage config themselves.
"""
from __future__ import annotations

import json
import logging
import subprocess
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

# ──────────────────────────────────────────────── hardware defaults ──
# RTX 2060 12 GB — override via config or COSYSIM_* env vars.
_DEFAULT_GPU       = 0.9       # fraction of model layers on GPU
_DEFAULT_TTL       = 3600      # seconds before auto-unload (0 = never)
_DEFAULT_CTX       = 4096      # context window
_VRAM_CAP_MB       = 11_500    # keep below this many MB

# ─────────────────────────────────────────────────────────────────────


class LMStudioManager:
    """
    Thin, config-driven wrapper around the LMStudio SDK and CLI.

    Parameters
    ----------
    config : ConfigManager
        Optional config manager instance.  If omitted the global
        ``get_config()`` singleton is used.

    Attributes
    ----------
    host : str
        LMStudio server host (default ``"127.0.0.1"``).
    port : int
        LMStudio server port (default ``1234``).
    cli : str
        Name / path of the ``lms`` CLI binary (default ``"lms"``).
    vram_cap_mb : int
        Hard VRAM cap in MB.  ``load_model()`` will refuse to load if the
        estimated usage would exceed this value.
    """

    def __init__(self, config=None) -> None:
        if config is None:
            from engine.config import get_config
            config = get_config()

        self.host:       str = config.get("lmstudio.host", "127.0.0.1")
        self.port:       int = int(config.get("lmstudio.port", 1234))
        self.cli:        str = config.get("lmstudio.cli",  "lms")
        self.vram_cap_mb: int = int(config.get("lmstudio.vram_cap_mb", _VRAM_CAP_MB))

        # Default model-load options from config, fall back to hardware defaults
        _opts = config.get("lmstudio.default_load_opts") or {}
        self.default_gpu:  float = float(_opts.get("gpu",  _DEFAULT_GPU))
        self.default_ttl:  int   = int  (_opts.get("ttl",  _DEFAULT_TTL))
        self.default_ctx:  int   = int  (_opts.get("context_length", _DEFAULT_CTX))

        self._base_url = f"http://{self.host}:{self.port}/v1"

    # ─────────────────────────────────────────────── server status ──

    def is_server_running(self) -> bool:
        """
        Return True if the LMStudio server is reachable.

        Uses ``lms server status --json`` and falls back to a plain HTTP
        probe if the CLI is not available.
        """
        try:
            result = self._cli_run(["server", "status", "--json"], timeout=5)
            data   = json.loads(result)
            return bool(data.get("running") or data.get("status") == "running")
        except (LMStudioCLIError, json.JSONDecodeError):
            logger.debug("Suppressed exception", exc_info=True)

        # Fallback: direct HTTP probe
        try:
            import urllib.request
            urllib.request.urlopen(f"{self._base_url}/models", timeout=3)
            return True
        except Exception:
            return False

    def get_server_info(self) -> Dict[str, Any]:
        """
        Return server info dict from ``lms server status --json``.

        Returns an empty dict if the server is not running or the CLI
        is unavailable.
        """
        try:
            raw  = self._cli_run(["server", "status", "--json"], timeout=5)
            return json.loads(raw)
        except Exception as exc:
            logger.debug("get_server_info failed: %s", exc)
            return {}

    # ──────────────────────────────────────────── loaded-model list ──

    def list_loaded_models(self) -> List[Dict[str, Any]]:
        """
        Return list of currently loaded model dicts from ``lms ps --json``.

        Each dict contains at least ``model_key`` and ``status`` keys.
        Returns an empty list on any error.
        """
        try:
            raw  = self._cli_run(["ps", "--json"], timeout=8)
            data = json.loads(raw)
            return data if isinstance(data, list) else data.get("models", [])
        except (LMStudioCLIError, json.JSONDecodeError) as exc:
            logger.debug("list_loaded_models failed: %s", exc)
            return []

    def get_available_models(self) -> List[Dict[str, Any]]:
        """
        Return all models available to load (from ``lms ls --json``).

        Returns an empty list on any error.
        """
        try:
            raw  = self._cli_run(["ls", "--json"], timeout=10)
            data = json.loads(raw)
            return data if isinstance(data, list) else data.get("models", [])
        except (LMStudioCLIError, json.JSONDecodeError) as exc:
            logger.debug("get_available_models failed: %s", exc)
            return []

    # ────────────────────────────────────────────── model lifecycle ──

    def load_model(
        self,
        model_key: str,
        *,
        gpu:            Optional[float] = None,
        ttl:            Optional[int]   = None,
        context_length: Optional[int]   = None,
        force:          bool            = False,
    ) -> bool:
        """
        Load a model into LMStudio via ``lms load``.

        Performs a VRAM estimate first — refuses to load if the model would
        push usage over ``vram_cap_mb``.  Pass ``force=True`` to bypass.

        Args:
            model_key:      Model identifier (e.g. ``"llama-3-8b-instruct"``).
            gpu:            GPU offload fraction (default: ``self.default_gpu``).
            ttl:            Time-to-live in seconds (default: ``self.default_ttl``).
            context_length: Context length (default: ``self.default_ctx``).
            force:          If True, skip the VRAM guard check.

        Returns:
            True on success, False on failure.
        """
        gpu = gpu if gpu is not None else self.default_gpu
        ttl = ttl if ttl is not None else self.default_ttl
        ctx = context_length if context_length is not None else self.default_ctx

        # Guard: estimate VRAM usage before loading
        if not force:
            est = self.estimate_vram_needed(model_key, gpu=gpu, context_length=ctx)
            if est is not None and est > self.vram_cap_mb:
                logger.warning(
                    "Refusing to load %s — estimated %d MB VRAM > cap %d MB",
                    model_key, est, self.vram_cap_mb,
                )
                return False

        cmd = [
            "load", model_key,
            f"--gpu={gpu}",
            f"--ttl={ttl}",
            f"--context-length={ctx}",
        ]
        try:
            self._cli_run(cmd, timeout=120)
            logger.info("Model loaded: %s (gpu=%.1f, ttl=%ds)", model_key, gpu, ttl)
            return True
        except LMStudioCLIError as exc:
            logger.error("Failed to load model %s: %s", model_key, exc)
            return False

    def unload_model(self, model_key: str) -> bool:
        """
        Unload a model via ``lms unload <model_key>``.

        Args:
            model_key: Model identifier to unload.

        Returns:
            True on success, False on failure.
        """
        try:
            self._cli_run(["unload", model_key], timeout=30)
            logger.info("Model unloaded: %s", model_key)
            return True
        except LMStudioCLIError as exc:
            logger.error("Failed to unload model %s: %s", model_key, exc)
            return False

    # ──────────────────────────────────────────────── VRAM estimate ──

    def estimate_vram_needed(
        self,
        model_key: str,
        *,
        gpu:            Optional[float] = None,
        context_length: Optional[int]   = None,
    ) -> Optional[int]:
        """
        Estimate VRAM (MB) needed to load a model via ``lms load --estimate-only``.

        Args:
            model_key:      Model identifier.
            gpu:            GPU fraction (default: ``self.default_gpu``).
            context_length: Context length (default: ``self.default_ctx``).

        Returns:
            Estimated VRAM in MB, or None if the estimate is unavailable.
        """
        gpu = gpu if gpu is not None else self.default_gpu
        ctx = context_length if context_length is not None else self.default_ctx
        cmd = [
            "load", model_key,
            "--estimate-only",
            f"--gpu={gpu}",
            f"--context-length={ctx}",
        ]
        try:
            raw  = self._cli_run(cmd, timeout=30)
            data = json.loads(raw)
            # LMStudio returns {"vram_mb": <int>} or similar
            vram = data.get("vram_mb") or data.get("gpuMemoryMb") or data.get("gpu_mb")
            return int(vram) if vram is not None else None
        except (LMStudioCLIError, json.JSONDecodeError, ValueError) as exc:
            logger.debug("estimate_vram_needed failed for %s: %s", model_key, exc)
            return None

    # ──────────────────────────────────────────── SDK chat helpers ──

    def get_client(self):
        """
        Return a ``lmstudio.LMStudio`` SDK client instance.

        The SDK client is lazy-imported so that the rest of the codebase
        does not require the ``lmstudio`` package at import time.

        Raises:
            ImportError if the ``lmstudio`` package is not installed.
        """
        try:
            import lmstudio as lms
        except ImportError as exc:
            raise ImportError(
                "lmstudio package not installed.  "
                "Run: pip install lmstudio"
            ) from exc
        return lms.LMStudio(base_url=self._base_url)

    def get_llm(self, model: Optional[str] = None):
        """
        Return an ``lmstudio.llm`` handle for the given model.

        Args:
            model: Model key.  If omitted, uses the first loaded model.

        Returns:
            An ``lmstudio.LLM`` object ready for ``.complete()`` / ``.act()`` calls.
        """
        import lmstudio as lms

        if model:
            return lms.llm(model)

        loaded = self.list_loaded_models()
        if loaded:
            return lms.llm(loaded[0].get("model_key", ""))
        return lms.llm()  # Let the server pick

    # ───────────────────────────────────────────────── CLI helper ──

    def _cli_run(self, args: List[str], *, timeout: int = 30) -> str:
        """
        Run ``lms <args>`` and return stdout.

        Raises:
            LMStudioCLIError on non-zero exit code or subprocess failure.
        """
        cmd = [self.cli] + args
        try:
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=timeout,
            )
        except FileNotFoundError as exc:
            raise LMStudioCLIError(
                f"lms CLI not found (is it on PATH?): {self.cli}"
            ) from exc
        except subprocess.TimeoutExpired as exc:
            raise LMStudioCLIError(f"lms CLI timed out after {timeout}s: {cmd}") from exc

        if result.returncode != 0:
            err = (result.stderr or result.stdout or "").strip()
            raise LMStudioCLIError(f"lms {' '.join(args)} exited {result.returncode}: {err}")

        return result.stdout.strip()


# ─────────────────────────────────────────────── custom exception ──

class LMStudioCLIError(RuntimeError):
    """Raised when the ``lms`` CLI returns a non-zero exit code."""


# ──────────────────────────────────────────────────── singleton ──

_manager_instance: Optional[LMStudioManager] = None


def get_lmstudio_manager() -> LMStudioManager:
    """
    Return the global ``LMStudioManager`` singleton.

    Creates the instance on first call using the global config.
    Thread-safe for read access; the first call should happen at
    startup before concurrent code runs.
    """
    global _manager_instance
    if _manager_instance is None:
        _manager_instance = LMStudioManager()
    return _manager_instance
