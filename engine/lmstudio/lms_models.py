"""LMStudio response dataclasses and model metadata.

Extracted from ``lms_client.py`` to reduce file size.
All names are re-exported from the parent module for backward compatibility.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional


# ── Response dataclasses ────────────────────────────────────────────────

@dataclass
class LMSResponse:
    """Result of a native v1 chat call."""
    content: str = ""
    model: str = ""
    finish_reason: str = ""
    input_tokens: int = 0
    output_tokens: int = 0
    total_tokens: int = 0
    latency_ms: float = 0.0
    request_id: str = ""
    response_id: str = ""          # for stateful chats (starts with "resp_")
    reasoning_content: str = ""    # thinking model CoT
    reasoning_tokens: int = 0      # tokens spent on reasoning
    tool_calls: List[Dict] = field(default_factory=list)
    # Native v1 stats (from chat.end or non-streaming response)
    server_tps: float = 0.0               # tokens_per_second from server
    time_to_first_token_s: float = 0.0    # time_to_first_token_seconds
    model_load_time_s: float = 0.0        # model_load_time_seconds (0 if already loaded)
    # Extra metadata (spec decode stats, etc.)
    metadata: Dict = field(default_factory=dict)

    @property
    def tokens_per_second(self) -> float:
        """Use server-reported TPS if available, else estimate from latency."""
        if self.server_tps > 0:
            return self.server_tps
        if self.latency_ms > 0 and self.output_tokens > 0:
            return self.output_tokens / (self.latency_ms / 1000.0)
        return 0.0

    @property
    def has_tool_calls(self) -> bool:
        return len(self.tool_calls) > 0

    @property
    def is_stateful(self) -> bool:
        """Whether this response has a response_id for continuations."""
        return bool(self.response_id and self.response_id.startswith("resp_"))

    def _apply_v1_stats(self, stats: Dict) -> None:
        """Apply native v1 stats dict to this response."""
        self.input_tokens = stats.get("input_tokens", self.input_tokens)
        self.output_tokens = stats.get("total_output_tokens", self.output_tokens)
        self.reasoning_tokens = stats.get("reasoning_output_tokens", self.reasoning_tokens)
        self.total_tokens = self.input_tokens + self.output_tokens
        self.server_tps = stats.get("tokens_per_second", 0.0)
        self.time_to_first_token_s = stats.get("time_to_first_token_seconds", 0.0)
        self.model_load_time_s = stats.get("model_load_time_seconds", 0.0) or 0.0


@dataclass
class LMSStreamEvent:
    """A single typed event from the native v1 SSE stream.

    LMStudio v1 streaming sends ``event: <type>\\ndata: <json>`` pairs.
    Event types (in order they may appear):

    - chat.start, chat.end
    - model_load.start, model_load.progress, model_load.end
    - prompt_processing.start, prompt_processing.progress, prompt_processing.end
    - reasoning.start, reasoning.delta, reasoning.end
    - tool_call.start, tool_call.arguments, tool_call.success, tool_call.failure
    - message.start, message.delta, message.end
    - error
    """
    event_type: str = ""
    # Content deltas (message.delta, reasoning.delta)
    content: str = ""
    # Progress (model_load.progress, prompt_processing.progress) — 0.0 to 1.0
    progress: float = 0.0
    # Model info (chat.start, model_load.*)
    model_instance_id: str = ""
    load_time_seconds: float = 0.0  # model_load.end
    # Tool call fields
    tool_name: str = ""
    tool_arguments: Optional[Dict] = None
    tool_output: str = ""
    tool_provider: Optional[Dict] = None
    # Error fields
    error: Optional[Dict] = None
    # chat.end aggregated result
    stats: Optional[Dict] = None
    result: Optional[Dict] = None
    response_id: str = ""
    # Terminal flag
    is_done: bool = False


@dataclass
class LMSModelInfo:
    """Information about a loaded model."""
    model_id: str = ""
    architecture: str = ""
    parameters: str = ""
    context_length: int = 0
    max_context_length: int = 0
    supports_vision: bool = False
    supports_tool_use: bool = False
    quantization: str = ""


@dataclass
class LMSModelInstance:
    """A loaded instance of a model (from ``loaded_instances[]``)."""
    id: str = ""
    config: Dict[str, Any] = field(default_factory=dict)

    @property
    def context_length(self) -> int:
        return self.config.get("context_length", 0)

    @property
    def eval_batch_size(self) -> Optional[int]:
        return self.config.get("eval_batch_size")

    @property
    def flash_attention(self) -> Optional[bool]:
        return self.config.get("flash_attention")

    @property
    def num_experts(self) -> Optional[int]:
        return self.config.get("num_experts")

    @property
    def offload_kv_cache_to_gpu(self) -> Optional[bool]:
        return self.config.get("offload_kv_cache_to_gpu")


@dataclass
class LMSQuantization:
    """Quantization info for a model."""
    name: Optional[str] = None
    bits_per_weight: Optional[float] = None


@dataclass
class LMSCapabilities:
    """Model capabilities."""
    vision: bool = False
    trained_for_tool_use: bool = False


@dataclass
class LMSModel:
    """Full model metadata from ``GET /api/v1/models``.

    Maps every field from the LMStudio v1 response schema.
    """
    type: str = "llm"
    publisher: str = ""
    key: str = ""
    display_name: str = ""
    architecture: Optional[str] = None
    quantization: Optional[LMSQuantization] = None
    size_bytes: int = 0
    params_string: Optional[str] = None
    loaded_instances: List[LMSModelInstance] = field(default_factory=list)
    max_context_length: int = 0
    format: Optional[str] = None
    capabilities: Optional[LMSCapabilities] = None
    description: Optional[str] = None

    @property
    def is_loaded(self) -> bool:
        return len(self.loaded_instances) > 0

    @property
    def instance_id(self) -> str:
        """The ID to use for ``/api/v1/chat`` model field."""
        if self.loaded_instances:
            return self.loaded_instances[0].id
        return self.key

    @classmethod
    def from_api(cls, data: Dict[str, Any]) -> "LMSModel":
        """Parse from a single model entry in ``GET /api/v1/models`` response."""
        quant_data = data.get("quantization")
        quant = None
        if quant_data and isinstance(quant_data, dict):
            quant = LMSQuantization(
                name=quant_data.get("name"),
                bits_per_weight=quant_data.get("bits_per_weight"),
            )
        cap_data = data.get("capabilities")
        caps = None
        if cap_data and isinstance(cap_data, dict):
            caps = LMSCapabilities(
                vision=cap_data.get("vision", False),
                trained_for_tool_use=cap_data.get("trained_for_tool_use", False),
            )
        instances = [
            LMSModelInstance(id=inst.get("id", ""), config=inst.get("config", {}))
            for inst in data.get("loaded_instances", [])
        ]
        return cls(
            type=data.get("type", "llm"),
            publisher=data.get("publisher", ""),
            key=data.get("key", ""),
            display_name=data.get("display_name", data.get("key", "")),
            architecture=data.get("architecture"),
            quantization=quant,
            size_bytes=data.get("size_bytes", 0),
            params_string=data.get("params_string"),
            loaded_instances=instances,
            max_context_length=data.get("max_context_length", 0),
            format=data.get("format"),
            capabilities=caps,
            description=data.get("description"),
        )


@dataclass
class LMSLoadResult:
    """Response from ``POST /api/v1/models/load``."""
    type: str = "llm"
    instance_id: str = ""
    load_time_seconds: float = 0.0
    status: str = ""
    load_config: Optional[Dict[str, Any]] = None


@dataclass
class LMSDownloadJob:
    """Response from ``POST /api/v1/models/download``."""
    job_id: Optional[str] = None
    status: str = ""
    total_size_bytes: Optional[int] = None
    started_at: Optional[str] = None
    completed_at: Optional[str] = None


@dataclass
class LMSDownloadStatus:
    """Response from ``GET /api/v1/models/download/status/:job_id``."""
    job_id: str = ""
    status: str = ""
    bytes_per_second: Optional[float] = None
    estimated_completion: Optional[str] = None
    completed_at: Optional[str] = None
    total_size_bytes: Optional[int] = None
    downloaded_bytes: Optional[int] = None
    started_at: Optional[str] = None

    @property
    def progress(self) -> float:
        """Download progress as 0.0–1.0."""
        if self.total_size_bytes and self.downloaded_bytes:
            return self.downloaded_bytes / self.total_size_bytes
        return 0.0 if self.status == "downloading" else 1.0
