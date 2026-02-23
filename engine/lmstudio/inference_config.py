"""
InferenceConfig / LoadConfig — Typed configuration for LMStudio inference and model loading

These dataclasses centralise every parameter that can be passed to LMStudio's
native v1 REST API or Python SDK.  They flow through the entire stack:

    YAML config → AgentProfile → InferenceConfig → LMSClient → /api/v1/chat

Usage::

    from engine.lmstudio.inference_config import InferenceConfig, LoadConfig

    # From agent profile
    cfg = InferenceConfig.from_agent_profile("big")

    # Manual override
    cfg = InferenceConfig(temperature=0.3, max_output_tokens=2000)

    # Merge: base + overrides
    final = InferenceConfig.merge(base_cfg, override_cfg)
"""
from __future__ import annotations

import copy
import logging
from dataclasses import dataclass, field, asdict
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


# ── Inference parameters ────────────────────────────────────────────────

@dataclass
class InferenceConfig:
    """All parameters for an LMStudio inference request.

    Maps 1:1 to LMStudio native v1 fields where possible.
    """

    # Sampling
    temperature: Optional[float] = None
    top_p: Optional[float] = None
    top_k: Optional[int] = None
    min_p: Optional[float] = None
    repeat_penalty: Optional[float] = None

    # Output limits
    max_output_tokens: Optional[int] = None

    # Reasoning — native v1 accepts: "off" | "low" | "medium" | "high" | "on"
    # Also accepts bool for convenience (True → "on", False → "off")
    reasoning: Optional[Any] = None

    # Stop sequences
    stop_strings: Optional[List[str]] = None

    # Structured output: {"type": "json_schema", "json_schema": {...}}
    response_format: Optional[Dict[str, Any]] = None

    # Speculative decoding: draft model identifier
    draft_model: Optional[str] = None

    # MCP integrations: [{"type": "ephemeral_mcp", "server_url": "..."}, ...]
    integrations: Optional[List[Dict[str, Any]]] = None

    # Stateful chat: chain responses without resending full history
    previous_response_id: Optional[str] = None

    # Whether to store the chat for stateful continuations (default True)
    store: Optional[bool] = None

    # Context length override for this request
    context_length: Optional[int] = None

    # Image input for VLMs: list of base64 data URIs or URLs
    images: Optional[List[str]] = None

    # Model override (empty = use default/loaded)
    model: Optional[str] = None

    # ── Factories ───────────────────────────────────────────────────

    @classmethod
    def from_agent_profile(cls, role: str = "big") -> "InferenceConfig":
        """Build config from an MCPFramework AgentProfile."""
        try:
            from engine.mcp.framework import get_framework
            profile = get_framework().get_agent_profile(role)
        except Exception:
            return cls()

        return cls(
            temperature=profile.temperature,
            top_p=profile.top_p,
            max_output_tokens=profile.max_tokens,
            model=profile.model or None,
        )

    @classmethod
    def from_yaml(cls, section: str = "lmstudio.inference_defaults") -> "InferenceConfig":
        """Build config from a YAML config section."""
        try:
            from engine.config import get_config
            cfg = get_config()
        except Exception:
            return cls()

        return cls(
            temperature=_opt_float(cfg, f"{section}.temperature"),
            top_p=_opt_float(cfg, f"{section}.top_p"),
            top_k=_opt_int(cfg, f"{section}.top_k"),
            min_p=_opt_float(cfg, f"{section}.min_p"),
            repeat_penalty=_opt_float(cfg, f"{section}.repeat_penalty"),
            max_output_tokens=_opt_int(cfg, f"{section}.max_output_tokens"),
            reasoning=_opt_bool(cfg, f"{section}.reasoning"),
            stop_strings=cfg.get(f"{section}.stop_strings", None),
            draft_model=cfg.get(f"{section}.draft_model", None) or None,
        )

    @classmethod
    def merge(cls, base: "InferenceConfig", override: "InferenceConfig") -> "InferenceConfig":
        """Return a new config: *base* with any non-None fields from *override*."""
        base_d = asdict(base)
        over_d = asdict(override)
        merged = {k: (over_d[k] if over_d[k] is not None else base_d[k]) for k in base_d}
        return cls(**merged)

    # ── Conversion to API payloads ──────────────────────────────────

    def to_native_v1(self) -> Dict[str, Any]:
        """Build the fields dict for LMStudio native ``/api/v1/chat``.

        Note: ``model``, ``input``, ``system_prompt``, and ``stream`` are
        set by the caller (LMSClient) — this only returns optional params.
        """
        d: Dict[str, Any] = {}
        if self.temperature is not None:
            d["temperature"] = self.temperature
        if self.top_p is not None:
            d["top_p"] = self.top_p
        if self.top_k is not None:
            d["top_k"] = self.top_k
        if self.min_p is not None:
            d["min_p"] = self.min_p
        if self.repeat_penalty is not None:
            d["repeat_penalty"] = self.repeat_penalty
        if self.max_output_tokens is not None:
            d["max_output_tokens"] = self.max_output_tokens
        if self.reasoning is not None:
            # Convert bool → string enum for native v1
            if isinstance(self.reasoning, bool):
                d["reasoning"] = "on" if self.reasoning else "off"
            else:
                d["reasoning"] = str(self.reasoning)
        if self.stop_strings:
            d["stop"] = self.stop_strings
        if self.response_format:
            d["response_format"] = self.response_format
        if self.integrations:
            d["integrations"] = self.integrations
        if self.previous_response_id:
            d["previous_response_id"] = self.previous_response_id
        if self.store is not None:
            d["store"] = self.store
        if self.context_length is not None:
            d["context_length"] = self.context_length
        if self.draft_model:
            d["draft_model"] = self.draft_model
        return d

    def to_openai_compat(self) -> Dict[str, Any]:
        """Build the fields dict for OpenAI-compatible ``/v1/chat/completions``."""
        d: Dict[str, Any] = {}
        if self.temperature is not None:
            d["temperature"] = self.temperature
        if self.top_p is not None:
            d["top_p"] = self.top_p
        if self.max_output_tokens is not None:
            d["max_tokens"] = self.max_output_tokens
        if self.stop_strings:
            d["stop"] = self.stop_strings
        if self.response_format:
            d["response_format"] = self.response_format
        if self.integrations:
            d["integrations"] = self.integrations
        return d

    def to_dict(self) -> Dict[str, Any]:
        """Full serialisation (for admin panels / persistence)."""
        return {k: v for k, v in asdict(self).items() if v is not None}


# ── Load parameters ─────────────────────────────────────────────────────

@dataclass
class LoadConfig:
    """Parameters for loading a model into LMStudio.

    Maps to ``/api/v1/models/load`` body and ``lms load`` CLI flags.
    """

    # Context window size
    context_length: Optional[int] = None

    # GPU offload: fraction (0.0–1.0) or "max" or "off"
    gpu_offload: Optional[Any] = None

    # Flash attention
    flash_attention: Optional[bool] = None

    # Evaluation batch size
    eval_batch_size: Optional[int] = None

    # Keep KV cache on GPU (reduces RAM usage, uses more VRAM)
    keep_kv_cache_on_gpu: Optional[bool] = None

    # MoE: number of experts to use (for mixture-of-experts models)
    num_experts: Optional[int] = None

    # Time-to-live in seconds (0 = never auto-unload)
    ttl: Optional[int] = None

    # Speculative decoding draft model
    draft_model: Optional[str] = None

    @classmethod
    def from_yaml(cls, section: str = "lmstudio.load_defaults") -> "LoadConfig":
        """Build from YAML config section."""
        try:
            from engine.config import get_config
            cfg = get_config()
        except Exception:
            return cls()

        return cls(
            context_length=_opt_int(cfg, f"{section}.context_length"),
            gpu_offload=cfg.get(f"{section}.gpu_offload", None),
            flash_attention=_opt_bool(cfg, f"{section}.flash_attention"),
            eval_batch_size=_opt_int(cfg, f"{section}.eval_batch_size"),
            keep_kv_cache_on_gpu=_opt_bool(cfg, f"{section}.keep_kv_cache_on_gpu"),
            num_experts=_opt_int(cfg, f"{section}.num_experts"),
            ttl=_opt_int(cfg, f"{section}.ttl"),
            draft_model=cfg.get(f"{section}.draft_model", None) or None,
        )

    def to_rest_body(self) -> Dict[str, Any]:
        """Build the JSON body for ``POST /api/v1/models/load``.

        Field names match the LMStudio v1 API spec exactly.
        """
        d: Dict[str, Any] = {}
        if self.context_length is not None:
            d["context_length"] = self.context_length
        if self.gpu_offload is not None:
            d["gpu_offload"] = self.gpu_offload
        if self.flash_attention is not None:
            d["flash_attention"] = self.flash_attention
        if self.eval_batch_size is not None:
            d["eval_batch_size"] = self.eval_batch_size
        if self.keep_kv_cache_on_gpu is not None:
            d["offload_kv_cache_to_gpu"] = self.keep_kv_cache_on_gpu
        if self.num_experts is not None:
            d["num_experts"] = self.num_experts
        return d

    def to_cli_flags(self) -> List[str]:
        """Build CLI flags list for ``lms load``."""
        flags: List[str] = []
        if self.context_length is not None:
            flags.extend(["--context-length", str(self.context_length)])
        if self.gpu_offload is not None:
            flags.extend(["--gpu", str(self.gpu_offload)])
        if self.ttl is not None:
            flags.extend(["--ttl", str(self.ttl)])
        return flags

    def to_dict(self) -> Dict[str, Any]:
        return {k: v for k, v in asdict(self).items() if v is not None}


# ── Structured output helpers ───────────────────────────────────────────

def json_schema_format(schema: Dict[str, Any], name: str = "response") -> Dict[str, Any]:
    """Build a ``response_format`` dict for JSON schema enforcement.

    Usage::

        cfg = InferenceConfig(
            response_format=json_schema_format({
                "type": "object",
                "properties": {"action": {"type": "string"}, "target": {"type": "string"}},
                "required": ["action"],
            })
        )
    """
    return {
        "type": "json_schema",
        "json_schema": {
            "name": name,
            "strict": True,
            "schema": schema,
        },
    }


def json_object_format() -> Dict[str, Any]:
    """Simple ``response_format`` that asks for any valid JSON object."""
    return {"type": "json_object"}


# ── Internal helpers ────────────────────────────────────────────────────

def _opt_float(cfg, key: str) -> Optional[float]:
    v = cfg.get(key, None)
    return float(v) if v is not None else None

def _opt_int(cfg, key: str) -> Optional[int]:
    v = cfg.get(key, None)
    return int(v) if v is not None else None

def _opt_bool(cfg, key: str) -> Optional[bool]:
    v = cfg.get(key, None)
    return bool(v) if v is not None else None
