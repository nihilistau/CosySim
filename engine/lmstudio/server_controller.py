"""
ServerController — Bidirectional LMStudio server management

CosySim is both client AND server for LMStudio. The ServerController
provides server-side control: model lifecycle, inference config, instance
isolation per agent, health monitoring, and metrics collection.

Channels used:
- SDK (WebSocket) for persistent model management + response control
- CLI (subprocess) for server start/stop/status + VRAM estimation
- REST (v1 API) for inference (handled by lms_client.py)

The ServerController is wired into the InferenceOrchestrator and exposed
via MCP skills so agents can self-manage their model instances.

Version: v1.56.0 [2026-03-26]
Author:  CosySim Team

Change Log:
    v1.56.0 [2026-03-26] — Per-model health metrics via get_model_health()
    v1.50.1 [2026-03-22] — Auto-unload idle agent instances
    v1.49.3 [2026-03-22] — Initial ServerController with SDK/CLI channels

Usage::

    from engine.lmstudio.server_controller import get_server_controller

    ctrl = get_server_controller()
    status = ctrl.get_server_status()
    ctrl.load_model("qwen3-0.6b", context_length=4096, gpu_offload=0.8)
    ctrl.configure_inference("qwen3-0.6b", stop_strings=["<|endoftext|>"])
    ctrl.create_agent_instance("aria", "qwen3-0.6b", context_length=8192)
"""
from __future__ import annotations

import logging
import threading
import time
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


# ── Model instance descriptor ──────────────────────────────────────────

@dataclass
class ModelInstance:
    """Tracks a loaded model instance with its configuration."""

    model_key: str
    instance_id: str = ""
    agent_id: str = ""
    context_length: int = 4096
    gpu_offload: float = 0.9
    stop_strings: List[str] = field(default_factory=list)
    temperature: float = 0.7
    max_tokens: int = 2048
    loaded_at: float = field(default_factory=time.monotonic)
    last_used_at: float = field(default_factory=time.monotonic)
    request_count: int = 0
    total_tokens: int = 0

    def touch(self, tokens: int = 0) -> None:
        """Mark the instance as used and accumulate token count."""
        self.last_used_at = time.monotonic()
        self.request_count += 1
        self.total_tokens += tokens

    @property
    def idle_seconds(self) -> float:
        return time.monotonic() - self.last_used_at

    @property
    def uptime_seconds(self) -> float:
        return time.monotonic() - self.loaded_at

    def to_dict(self) -> Dict[str, Any]:
        return {
            "model_key": self.model_key,
            "instance_id": self.instance_id,
            "agent_id": self.agent_id,
            "context_length": self.context_length,
            "gpu_offload": self.gpu_offload,
            "stop_strings": self.stop_strings,
            "temperature": self.temperature,
            "max_tokens": self.max_tokens,
            "idle_seconds": round(self.idle_seconds, 1),
            "uptime_seconds": round(self.uptime_seconds, 1),
            "request_count": self.request_count,
            "total_tokens": self.total_tokens,
        }


# ── Server health snapshot ─────────────────────────────────────────────

@dataclass
class ServerHealth:
    """Snapshot of LMStudio server health."""

    reachable: bool = False
    server_version: str = ""
    loaded_models: int = 0
    model_names: List[str] = field(default_factory=list)
    vram_used_mb: float = 0.0
    vram_total_mb: float = 0.0
    cpu_usage_pct: float = 0.0
    uptime_seconds: float = 0.0
    pending_requests: int = 0
    checked_at: float = field(default_factory=time.time)
    error: str = ""

    @property
    def vram_usage_pct(self) -> float:
        if self.vram_total_mb > 0:
            return round((self.vram_used_mb / self.vram_total_mb) * 100, 1)
        return 0.0

    @property
    def healthy(self) -> bool:
        return self.reachable and not self.error

    def to_dict(self) -> Dict[str, Any]:
        return {
            "reachable": self.reachable,
            "healthy": self.healthy,
            "server_version": self.server_version,
            "loaded_models": self.loaded_models,
            "model_names": self.model_names,
            "vram_used_mb": round(self.vram_used_mb, 1),
            "vram_total_mb": round(self.vram_total_mb, 1),
            "vram_usage_pct": self.vram_usage_pct,
            "uptime_seconds": round(self.uptime_seconds, 1),
            "pending_requests": self.pending_requests,
            "checked_at": self.checked_at,
            "error": self.error,
        }


# ── Server Controller ──────────────────────────────────────────────────

class ServerController:
    """
    Server-side controller for LMStudio — controls model lifecycle,
    inference configuration, and agent instance isolation.

    Uses SDK (WebSocket) for model management and CLI for server
    operations. Integrates with LMLinkManager for multi-instance routing.
    """

    def __init__(self, config: Any = None) -> None:
        if config is None:
            from engine.config import get_config
            config = get_config()

        self._config = config
        self._lock = threading.Lock()

        # Instance tracking {instance_id_or_model_key → ModelInstance}
        self._instances: Dict[str, ModelInstance] = {}

        # Agent-to-instance mapping {agent_id → instance_id}
        self._agent_instances: Dict[str, str] = {}

        # Health monitoring
        self._last_health: Optional[ServerHealth] = None
        self._health_check_interval: float = float(
            config.get("lmstudio.health.check_interval_seconds", 30)
        )
        self._health_thread: Optional[threading.Thread] = None
        self._health_stop = threading.Event()

        # Metrics
        self._metrics: Dict[str, Any] = {
            "total_loads": 0,
            "total_unloads": 0,
            "total_config_changes": 0,
            "total_instance_creates": 0,
            "health_checks": 0,
            "errors": 0,
        }

        # Lazy SDK/CLI references
        self._sdk_client = None
        self._cli_manager = None
        self._lmlink_manager = None

        # v1.49.3 [2026-03-22] — Structured logging context
        logger.info("[ServerController] Initialized (operation=init)")

    # ── Lazy component access ────────────────────────────────────────

    @property
    def sdk(self):
        """Return the SDK client singleton (lazy)."""
        if self._sdk_client is None:
            from engine.lmstudio.sdk_client import get_sdk_client
            self._sdk_client = get_sdk_client()
        return self._sdk_client

    @property
    def cli(self):
        """Return the CLI manager singleton (lazy)."""
        if self._cli_manager is None:
            from engine.lmstudio.client import get_lmstudio_manager
            self._cli_manager = get_lmstudio_manager()
        return self._cli_manager

    @property
    def lmlink(self):
        """Return the LMLink manager (lazy, may be None if disabled)."""
        if self._lmlink_manager is None:
            try:
                from engine.lmstudio.lmlink_manager import get_lmlink_manager
                self._lmlink_manager = get_lmlink_manager()
            except Exception:
                logger.debug("LMLink manager unavailable")
        return self._lmlink_manager

    # ── Server lifecycle ─────────────────────────────────────────────

    def is_server_running(self) -> bool:
        """Check if the LMStudio server is reachable."""
        try:
            return self.cli.is_server_running()
        except Exception:
            return False

    def get_server_status(self) -> ServerHealth:
        """Get comprehensive server health status."""
        health = ServerHealth()

        try:
            # Check reachability via CLI
            health.reachable = self.cli.is_server_running()

            if not health.reachable:
                health.error = "Server not reachable"
                self._last_health = health
                return health

            # Get loaded models via SDK (preferred) or CLI
            sdk = self.sdk
            if sdk is not None:
                try:
                    loaded = sdk.list_loaded()
                    health.loaded_models = len(loaded)
                    health.model_names = [m.get("model_key", "") for m in loaded]
                except Exception as e:
                    logger.debug("SDK list_loaded failed, trying CLI: %s", e)
                    loaded = self.cli.list_loaded_models()
                    health.loaded_models = len(loaded)
                    health.model_names = [
                        m.get("path", m.get("id", "")) for m in loaded
                    ]
            else:
                loaded = self.cli.list_loaded_models()
                health.loaded_models = len(loaded)
                health.model_names = [
                    m.get("path", m.get("id", "")) for m in loaded
                ]

            # VRAM info from config (actual runtime VRAM query requires nvidia-smi)
            health.vram_total_mb = float(
                self._config.get("lmstudio.vram_cap_mb", 12288)
            )

            # Estimate VRAM usage from loaded models
            gpu_frac = float(self._config.get("lmstudio.default_load_opts.gpu", 0.9))
            health.vram_used_mb = health.loaded_models * 4000 * gpu_frac

        except Exception as e:
            health.reachable = False
            health.error = str(e)
            self._metrics["errors"] += 1

        self._last_health = health
        self._metrics["health_checks"] += 1
        return health

    # v1.56.0 [2026-03-26] — Per-model health metrics for monitoring
    # CONNECTS: get_server_status(), SDK/CLI model listing
    # CALLED BY: Oracle diagnostics, /api/oracle/health, admin overlay
    # EMITS: structured dict with per-model VRAM/context/loaded status
    def get_model_health(self) -> Dict[str, Any]:
        """Return health metrics for all loaded models.

        Queries the server for loaded models and returns per-model details
        including VRAM usage estimates and context lengths, plus aggregate
        totals.  Falls back gracefully if the server is unreachable.

        Returns:
            Dict with ``models`` list, ``total_vram_mb``, ``model_count``,
            and ``server_reachable`` flag.
        """
        try:
            status = self.get_server_status()
            models: List[Dict[str, Any]] = []

            # Build per-model entries from loaded model names + instance data
            for model_name in status.model_names:
                instance = self._instances.get(model_name)
                vram_estimate = 0.0
                ctx = 0
                if instance:
                    # Use actual instance config if available
                    gpu_frac = instance.gpu_offload
                    vram_estimate = 4000 * gpu_frac  # ~4GB base per model * GPU fraction
                    ctx = instance.context_length
                else:
                    # Estimate from config defaults
                    gpu_frac = float(
                        self._config.get("lmstudio.default_load_opts.gpu", 0.9)
                    )
                    vram_estimate = 4000 * gpu_frac
                    ctx = int(
                        self._config.get("lmstudio.default_load_opts.context_length", 4096)
                    )

                models.append({
                    "id": model_name,
                    "loaded": True,
                    "vram_mb": round(vram_estimate, 1),
                    "context_length": ctx,
                    "request_count": instance.request_count if instance else 0,
                    "total_tokens": instance.total_tokens if instance else 0,
                    "idle_seconds": round(instance.idle_seconds, 1) if instance else 0,
                })

            total_vram = sum(m["vram_mb"] for m in models)
            logger.debug(
                "[ServerController] Model health check (operation=get_model_health, "
                "model_count=%d, total_vram_mb=%.1f)",
                len(models), total_vram,
            )

            return {
                "models": models,
                "total_vram_mb": round(total_vram, 1),
                "model_count": len(models),
                "server_reachable": True,
            }
        except Exception as exc:
            logger.warning(
                "[ServerController] Model health check failed (operation=get_model_health): %s",
                exc,
            )
            return {"server_reachable": False, "error": str(exc), "models": []}

    # ── Model lifecycle ──────────────────────────────────────────────

    def load_model(
        self,
        model_key: str,
        *,
        context_length: Optional[int] = None,
        gpu_offload: Optional[float] = None,
        flash_attention: Optional[bool] = None,
        eval_batch_size: Optional[int] = None,
        ttl: Optional[int] = None,
        stop_strings: Optional[List[str]] = None,
    ) -> ModelInstance:
        """
        Load a model on the LMStudio server.

        Uses the SDK for load control, falling back to CLI.

        Parameters
        ----------
        model_key : str
            Model identifier (e.g., "qwen3-0.6b" or full path).
        context_length : int, optional
            Maximum context window size.
        gpu_offload : float, optional
            Fraction of layers to offload to GPU (0.0-1.0).
        flash_attention : bool, optional
            Enable flash attention.
        eval_batch_size : int, optional
            Evaluation batch size.
        ttl : int, optional
            Time-to-live in seconds (0 = never expire).
        stop_strings : list[str], optional
            Default stop strings for this model.

        Returns
        -------
        ModelInstance
            Descriptor of the loaded model instance.
        """
        ctx = context_length or int(
            self._config.get("lmstudio.default_load_opts.context_length", 4096)
        )
        gpu = gpu_offload if gpu_offload is not None else float(
            self._config.get("lmstudio.default_load_opts.gpu", 0.9)
        )

        sdk = self.sdk
        if sdk is not None:
            try:
                sdk.load_instance(
                    model_key,
                    context_length=ctx,
                    gpu_offload=gpu,
                    flash_attention=flash_attention,
                    eval_batch_size=eval_batch_size,
                    ttl=ttl,
                )
                logger.info("[ServerController] Loaded model via SDK (operation=load_model, model=%s, ctx=%d, gpu=%.1f)", model_key, ctx, gpu)
            except Exception as e:
                logger.warning("[ServerController] SDK load failed, trying CLI (operation=load_model, model=%s): %s", model_key, e)
                self.cli.load_model(
                    model_key,
                    gpu=gpu,
                    context_length=ctx,
                    ttl=ttl or int(self._config.get("lmstudio.default_load_opts.ttl", 3600)),
                )
        else:
            self.cli.load_model(
                model_key,
                gpu=gpu,
                context_length=ctx,
                ttl=ttl or int(self._config.get("lmstudio.default_load_opts.ttl", 3600)),
            )

        instance = ModelInstance(
            model_key=model_key,
            instance_id=model_key,
            context_length=ctx,
            gpu_offload=gpu,
            stop_strings=stop_strings or [],
        )

        with self._lock:
            self._instances[model_key] = instance
            self._metrics["total_loads"] += 1

        return instance

    def unload_model(self, model_key: str) -> bool:
        """
        Unload a model from the LMStudio server.

        Returns True if the model was unloaded successfully.
        """
        sdk = self.sdk
        try:
            if sdk is not None:
                sdk.unload_model(model_key)
            else:
                self.cli.unload_model(model_key)

            with self._lock:
                self._instances.pop(model_key, None)
                # Remove any agent bindings to this model
                agents_to_remove = [
                    aid for aid, iid in self._agent_instances.items()
                    if iid == model_key
                ]
                for aid in agents_to_remove:
                    del self._agent_instances[aid]
                self._metrics["total_unloads"] += 1

            logger.info("[ServerController] Unloaded model (operation=unload_model, model=%s)", model_key)
            return True

        except Exception as e:
            logger.error("[ServerController] Failed to unload model (operation=unload_model, model=%s): %s", model_key, e)
            self._metrics["errors"] += 1
            return False

    def list_models(self) -> Dict[str, Any]:
        """
        List all models — loaded and downloaded.

        Returns
        -------
        dict
            Keys: "loaded" (list), "downloaded" (list), "instances" (dict)
        """
        result: Dict[str, Any] = {
            "loaded": [],
            "downloaded": [],
            "instances": {},
        }

        sdk = self.sdk
        if sdk is not None:
            try:
                result["loaded"] = sdk.list_loaded()
            except Exception:
                result["loaded"] = self.cli.list_loaded_models()
            try:
                result["downloaded"] = sdk.list_downloaded()
            except Exception:
                logger.debug("list_downloaded failed", exc_info=True)
        else:
            result["loaded"] = self.cli.list_loaded_models()

        with self._lock:
            result["instances"] = {
                k: v.to_dict() for k, v in self._instances.items()
            }

        return result

    # ── Inference configuration ──────────────────────────────────────

    def configure_inference(
        self,
        model_key: str,
        *,
        stop_strings: Optional[List[str]] = None,
        temperature: Optional[float] = None,
        max_tokens: Optional[int] = None,
        top_p: Optional[float] = None,
        top_k: Optional[int] = None,
        repeat_penalty: Optional[float] = None,
    ) -> ModelInstance:
        """
        Configure server-side inference parameters for a model instance.

        These become the defaults for all requests to this model.

        Parameters
        ----------
        model_key : str
            Model to configure.
        stop_strings : list[str], optional
            Server-side stop sequences.
        temperature : float, optional
            Sampling temperature.
        max_tokens : int, optional
            Maximum output tokens.
        top_p, top_k, repeat_penalty : optional
            Additional sampling parameters.

        Returns
        -------
        ModelInstance
            Updated instance descriptor.
        """
        with self._lock:
            instance = self._instances.get(model_key)
            if instance is None:
                instance = ModelInstance(model_key=model_key, instance_id=model_key)
                self._instances[model_key] = instance

            if stop_strings is not None:
                instance.stop_strings = stop_strings
            if temperature is not None:
                instance.temperature = temperature
            if max_tokens is not None:
                instance.max_tokens = max_tokens

            self._metrics["total_config_changes"] += 1

        logger.info(
            "[ServerController] Configured inference (operation=configure, model=%s, stop_strings=%s, temp=%s, max_tokens=%s)",
            model_key,
            stop_strings,
            temperature,
            max_tokens,
        )
        return instance

    def get_instance_config(self, model_key: str) -> Optional[Dict[str, Any]]:
        """Get the current inference config for a model instance."""
        with self._lock:
            instance = self._instances.get(model_key)
            return instance.to_dict() if instance else None

    # ── Agent instance isolation ─────────────────────────────────────

    def create_agent_instance(
        self,
        agent_id: str,
        model_key: str,
        *,
        context_length: int = 8192,
        gpu_offload: float = 0.9,
        stop_strings: Optional[List[str]] = None,
        ttl: int = 3600,
    ) -> ModelInstance:
        """
        Create an isolated model instance for an agent.

        Uses SDK's ``load_new_instance()`` to create a separate KV cache
        per agent, preventing context contamination between agents.

        Parameters
        ----------
        agent_id : str
            Unique agent identifier.
        model_key : str
            Base model to instantiate.
        context_length : int
            Context window for this instance.
        gpu_offload : float
            GPU layer fraction.
        stop_strings : list[str], optional
            Agent-specific stop strings.
        ttl : int
            Time-to-live in seconds.

        Returns
        -------
        ModelInstance
            The agent's dedicated model instance.
        """
        instance_id = f"{agent_id}_{model_key}"

        sdk = self.sdk
        if sdk is not None:
            try:
                sdk.load_instance(
                    model_key,
                    instance_id=instance_id,
                    context_length=context_length,
                    gpu_offload=gpu_offload,
                    ttl=ttl,
                )
            except Exception as e:
                logger.warning(
                    "[ServerController] SDK instance isolation failed (operation=create_instance, agent_id=%s): %s — "
                    "falling back to shared model",
                    agent_id, e,
                )
                instance_id = model_key
        else:
            logger.info(
                "[ServerController] SDK unavailable — agent will share model (operation=create_instance, agent_id=%s, model=%s)",
                agent_id, model_key,
            )
            instance_id = model_key

        instance = ModelInstance(
            model_key=model_key,
            instance_id=instance_id,
            agent_id=agent_id,
            context_length=context_length,
            gpu_offload=gpu_offload,
            stop_strings=stop_strings or [],
        )

        with self._lock:
            self._instances[instance_id] = instance
            self._agent_instances[agent_id] = instance_id
            self._metrics["total_instance_creates"] += 1

        logger.info(
            "[ServerController] Created agent instance (operation=create_instance, agent_id=%s, model=%s, instance_id=%s, ctx=%d)",
            agent_id, model_key, instance_id, context_length,
        )
        return instance

    def get_agent_instance(self, agent_id: str) -> Optional[ModelInstance]:
        """Get the model instance assigned to an agent."""
        with self._lock:
            instance_id = self._agent_instances.get(agent_id)
            if instance_id:
                return self._instances.get(instance_id)
        return None

    def release_agent_instance(self, agent_id: str) -> bool:
        """
        Release an agent's dedicated model instance.

        Unloads the instance if it was an isolated instance (not shared).
        """
        with self._lock:
            instance_id = self._agent_instances.pop(agent_id, None)
            if not instance_id:
                return False

            instance = self._instances.get(instance_id)
            if instance is None:
                return False

            # Only unload if this was an isolated instance (not the base model)
            is_isolated = instance_id != instance.model_key

        if is_isolated:
            return self.unload_model(instance_id)

        logger.info("[ServerController] Released shared instance (operation=release_instance, agent_id=%s)", agent_id)
        return True

    def list_agent_instances(self) -> Dict[str, Dict[str, Any]]:
        """Return all agent-to-instance mappings with instance details."""
        with self._lock:
            result = {}
            for agent_id, instance_id in self._agent_instances.items():
                instance = self._instances.get(instance_id)
                result[agent_id] = instance.to_dict() if instance else {
                    "instance_id": instance_id,
                    "status": "missing",
                }
            return result

    # ── Health monitoring ────────────────────────────────────────────

    def start_health_monitoring(self) -> None:
        """Start background health check thread."""
        if self._health_thread is not None and self._health_thread.is_alive():
            logger.debug("Health monitoring already running")
            return

        self._health_stop.clear()
        self._health_thread = threading.Thread(
            target=self._health_loop,
            name="lmstudio-health-monitor",
            daemon=True,
        )
        self._health_thread.start()
        logger.info(
            "[ServerController] Started health monitoring (operation=start_health, interval=%ds)",
            self._health_check_interval,
        )

    def stop_health_monitoring(self) -> None:
        """Stop background health check thread."""
        self._health_stop.set()
        if self._health_thread is not None:
            self._health_thread.join(timeout=5)
            self._health_thread = None
        logger.info("[ServerController] Stopped health monitoring (operation=stop_health)")

    def _health_loop(self) -> None:
        """Background health check loop."""
        while not self._health_stop.is_set():
            try:
                self.get_server_status()
            except Exception:
                logger.debug("Health check error", exc_info=True)

            # v1.50.1 [2026-03-22] — Auto-unload idle agent instances
            try:
                self._reap_idle_instances()
            except Exception:
                logger.debug("Idle reaper error", exc_info=True)

            self._health_stop.wait(self._health_check_interval)

    def _reap_idle_instances(self) -> None:
        """Unload agent instances that have been idle longer than jit_ttl_seconds."""
        ttl = float(self._config.get("lmstudio.jit_ttl_seconds", 300))
        if ttl <= 0:
            return
        with self._lock:
            idle_keys = [
                key for key, inst in self._instances.items()
                if inst.agent_id and inst.idle_seconds > ttl
            ]
        for key in idle_keys:
            inst = self._instances.get(key)
            if not inst:
                continue
            logger.info("[ServerController] Reaping idle instance: %s (agent=%s, idle=%.0fs, ttl=%.0fs) (operation=reap_idle)",
                        key, inst.agent_id, inst.idle_seconds, ttl)
            try:
                self.release_agent_instance(inst.agent_id)
            except Exception as exc:
                logger.warning("[ServerController] Failed to reap %s (operation=reap_idle): %s", key, exc)

    @property
    def last_health(self) -> Optional[ServerHealth]:
        """Return the most recent health check result."""
        return self._last_health

    # ── Token counting ───────────────────────────────────────────────

    def count_tokens(self, text: str, model_key: Optional[str] = None) -> int:
        """
        Count tokens in text using the model's tokenizer.

        Falls back to a rough estimate if SDK is unavailable.
        """
        sdk = self.sdk
        if sdk is not None:
            try:
                return sdk.count_tokens(text, model_key=model_key)
            except Exception:
                pass

        # Rough estimate: ~4 chars per token for English
        return max(1, len(text) // 4)

    # ── VRAM estimation ──────────────────────────────────────────────

    def estimate_vram(self, model_key: str) -> Optional[float]:
        """
        Estimate VRAM needed for a model (in MB).

        Uses CLI ``lms load --estimate-only`` when available.
        """
        try:
            return self.cli.estimate_vram_needed(model_key)
        except Exception:
            logger.debug("VRAM estimation failed for '%s'", model_key)
            return None

    # ── Metrics and status ───────────────────────────────────────────

    def get_metrics(self) -> Dict[str, Any]:
        """Return controller metrics."""
        with self._lock:
            return {
                **self._metrics.copy(),
                "active_instances": len(self._instances),
                "agent_bindings": len(self._agent_instances),
                "last_health": self._last_health.to_dict() if self._last_health else None,
            }

    def get_full_status(self) -> Dict[str, Any]:
        """
        Get comprehensive status including server health, instances,
        agents, metrics, and LMLink status.
        """
        status: Dict[str, Any] = {
            "server": self.get_server_status().to_dict(),
            "instances": {k: v.to_dict() for k, v in self._instances.items()},
            "agent_instances": self.list_agent_instances(),
            "metrics": self.get_metrics(),
        }

        # Add LMLink status if available
        lmlink = self.lmlink
        if lmlink is not None:
            try:
                status["lmlink"] = lmlink.get_status()
            except Exception:
                status["lmlink"] = {"error": "unavailable"}

        return status

    # ── Convenience: build inference config for a model ──────────────

    def build_request_config(
        self,
        model_key: str,
        *,
        override_stop_strings: Optional[List[str]] = None,
        override_temperature: Optional[float] = None,
        override_max_tokens: Optional[int] = None,
    ) -> Dict[str, Any]:
        """
        Build an inference config dict from the model instance's
        server-side defaults, with optional per-request overrides.

        This is the key "server-side" feature — the controller
        maintains default configs that apply to every request unless
        explicitly overridden.

        Returns
        -------
        dict
            Config dict compatible with InferenceConfig or lms_client.chat().
        """
        with self._lock:
            instance = self._instances.get(model_key)

        config: Dict[str, Any] = {}

        if instance:
            if instance.stop_strings:
                config["stop_strings"] = instance.stop_strings
            if instance.temperature != 0.7:
                config["temperature"] = instance.temperature
            if instance.max_tokens != 2048:
                config["max_tokens"] = instance.max_tokens

        # Apply overrides
        if override_stop_strings is not None:
            config["stop_strings"] = override_stop_strings
        if override_temperature is not None:
            config["temperature"] = override_temperature
        if override_max_tokens is not None:
            config["max_tokens"] = override_max_tokens

        return config

    # ── Shutdown ─────────────────────────────────────────────────────

    def shutdown(self) -> None:
        """Clean shutdown: stop health monitoring, clear state."""
        self.stop_health_monitoring()

        with self._lock:
            self._instances.clear()
            self._agent_instances.clear()

        logger.info("[ServerController] Shut down (operation=shutdown)")


# ── Singleton ────────────────────────────────────────────────────────────

_instance: Optional[ServerController] = None
_instance_lock = threading.Lock()


def get_server_controller(config: Any = None) -> ServerController:
    """Return the global ServerController singleton."""
    global _instance
    if _instance is not None:
        return _instance

    with _instance_lock:
        if _instance is not None:
            return _instance
        _instance = ServerController(config=config)
        return _instance
