"""
Pipeline data structures — types shared across all pipeline components.

These are pure data classes with no dependencies on engine internals,
making them safe to import from anywhere without circular imports.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional


# ── Watcher signals ─────────────────────────────────────────────────────

class WatcherSignal(Enum):
    """Signal emitted by the StreamWatcher during token analysis."""
    CONTINUE = "continue"     # generation is acceptable, keep going
    KILL = "kill"             # abort generation, retry with modified prompt
    PRE_WARM = "pre_warm"     # start tool call in background
    ROUTE = "route"           # tag detected, route immediately


# ── Watcher analysis ────────────────────────────────────────────────────

@dataclass
class WatcherAnalysis:
    """Summary of the StreamWatcher's analysis over one generation."""
    intent: str = ""                         # classified intent (e.g. "image_gen", "tool_call")
    acceptability: float = 1.0               # 0.0–1.0 quality score
    signals: List[WatcherSignal] = field(default_factory=list)
    tokens_analyzed: int = 0                 # how many tokens the watcher saw
    latency_ms: float = 0.0                  # total watcher classification time
    kill_reason: str = ""                    # why kill was triggered (if any)
    predicted_tools: List[str] = field(default_factory=list)  # tools watcher expected


# ── Pipeline configuration ──────────────────────────────────────────────

@dataclass
class PipelineConfig:
    """Configuration for the VirtualPipeline."""

    # Watcher
    watcher_enabled: bool = True             # use StreamWatcher (degrades gracefully)
    watcher_model_key: str = ""              # model key for Gemma 270M watcher
    watcher_trigger_tokens: int = 8          # tokens before first classification
    watcher_batch_size: int = 16             # tokens per subsequent batch

    # Kill switch
    kill_switch_enabled: bool = True         # can kill generation mid-stream
    kill_threshold: float = 0.3              # acceptability below this → kill
    max_retries: int = 2                     # retries after kill before accepting best
    repetition_limit: int = 3                # same phrase N times → kill
    retry_temperature_decay: float = 0.15    # reduce temp by this on each retry

    # Token-ahead routing
    pre_warm_enabled: bool = True            # pre-warm tools on intent detection
    pre_warm_timeout: float = 5.0            # seconds to wait for pre-warmed results

    # Conversation management
    max_branches: int = 10                   # max active branches per conversation
    branch_ttl: int = 300                    # seconds before pruning unused branches

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> "PipelineConfig":
        """Create from a config dict (e.g. from YAML)."""
        cfg = cls()
        watcher = d.get("watcher", {})
        kill = d.get("kill_switch", {})
        token = d.get("token_ahead", {})
        conv = d.get("conversation", {})

        cfg.watcher_enabled = d.get("enabled", cfg.watcher_enabled)
        cfg.watcher_model_key = watcher.get("model_key", cfg.watcher_model_key)
        cfg.watcher_trigger_tokens = watcher.get("trigger_tokens", cfg.watcher_trigger_tokens)
        cfg.watcher_batch_size = watcher.get("batch_size", cfg.watcher_batch_size)

        cfg.kill_switch_enabled = kill.get("enabled", cfg.kill_switch_enabled)
        cfg.kill_threshold = kill.get("threshold", cfg.kill_threshold)
        cfg.max_retries = kill.get("max_retries", cfg.max_retries)
        cfg.repetition_limit = kill.get("repetition_limit", cfg.repetition_limit)

        cfg.pre_warm_enabled = token.get("enabled", cfg.pre_warm_enabled)
        cfg.pre_warm_timeout = token.get("pre_warm_timeout", cfg.pre_warm_timeout)

        cfg.max_branches = conv.get("max_branches", cfg.max_branches)
        cfg.branch_ttl = conv.get("branch_ttl", cfg.branch_ttl)

        return cfg


# ── Pre-warm result ─────────────────────────────────────────────────────

@dataclass
class PreWarmResult:
    """Result of a tool that was pre-warmed during generation."""
    tool_name: str = ""
    arguments: Dict[str, Any] = field(default_factory=dict)
    result: Any = None
    success: bool = True
    latency_ms: float = 0.0
    was_used: bool = False       # True if the tag actually appeared


# ── Pipeline result ─────────────────────────────────────────────────────

@dataclass
class PipelineResult:
    """
    Superset of ProcessedResponse with pipeline orchestration metadata.

    Contains everything StreamProcessor produces (clean_text, tags, tool_calls)
    plus pipeline-specific data (watcher analysis, pre-warmed results, kill info).
    """

    # ── Content (from StreamProcessor) ──
    raw_text: str = ""                       # accumulated text including tags
    clean_text: str = ""                     # text with inline tags stripped
    reasoning_content: str = ""              # thinking/chain-of-thought

    # ── Extracted tags (from StreamProcessor) ──
    mood_tags: List[str] = field(default_factory=list)
    image_requests: List[str] = field(default_factory=list)
    action_tags: List[str] = field(default_factory=list)
    stat_deltas: List[Any] = field(default_factory=list)    # List[StatDelta]
    voice_style: str = ""

    # ── Tool calls (from StreamProcessor / LLM tool_call events) ──
    tool_calls: List[Any] = field(default_factory=list)     # List[ToolCallRecord]

    # ── LLM stats ──
    model: str = ""
    input_tokens: int = 0
    output_tokens: int = 0
    reasoning_tokens: int = 0
    server_tps: float = 0.0
    time_to_first_token_s: float = 0.0

    # ── Pipeline metadata ──
    response_id: str = ""                    # SSE UID for KV cache reuse
    branch_id: str = ""                      # conversation branch point
    tier: str = ""                           # which tier served this (gpu/cpu/router)

    # ── Watcher ──
    watcher_analysis: WatcherAnalysis = field(default_factory=WatcherAnalysis)

    # ── Token-ahead results ──
    pre_warmed_results: List[PreWarmResult] = field(default_factory=list)

    # ── Kill switch ──
    generation_killed: bool = False          # True if kill switch fired
    retry_count: int = 0                     # how many retries before final result
    killed_content: str = ""                 # content from killed generation(s)

    # ── Timing ──
    pipeline_latency_ms: float = 0.0        # total pipeline time (incl. retries)
    generation_latency_ms: float = 0.0      # pure LLM generation time
    pipeline_started: float = field(default_factory=time.time)
    pipeline_ended: float = 0.0

    # ── Spec decode ──
    draft_accepted: int = 0
    draft_rejected: int = 0

    # ── Convenience properties ──

    @property
    def has_images(self) -> bool:
        return bool(self.image_requests)

    @property
    def has_tool_calls(self) -> bool:
        return bool(self.tool_calls)

    @property
    def has_mood(self) -> bool:
        return bool(self.mood_tags)

    @property
    def primary_mood(self) -> str:
        return self.mood_tags[0] if self.mood_tags else ""

    @property
    def is_stateful(self) -> bool:
        return bool(self.response_id and self.response_id.startswith("resp_"))

    @property
    def pre_warm_hit_rate(self) -> float:
        """Fraction of pre-warmed tools that were actually used."""
        if not self.pre_warmed_results:
            return 0.0
        used = sum(1 for r in self.pre_warmed_results if r.was_used)
        return used / len(self.pre_warmed_results)

    @property
    def watcher_active(self) -> bool:
        return self.watcher_analysis.tokens_analyzed > 0

    @property
    def draft_acceptance_ratio(self) -> float:
        total = self.draft_accepted + self.draft_rejected
        return self.draft_accepted / total if total > 0 else 0.0

    @classmethod
    def from_processed_response(cls, pr: Any) -> "PipelineResult":
        """Create from an existing ProcessedResponse (bridge for existing code)."""
        result = cls()
        for attr in (
            "raw_text", "clean_text", "reasoning_content",
            "mood_tags", "image_requests", "action_tags",
            "stat_deltas", "voice_style", "tool_calls",
            "response_id", "model", "input_tokens", "output_tokens",
            "reasoning_tokens", "server_tps", "time_to_first_token_s",
            "latency_ms",
        ):
            val = getattr(pr, attr, None)
            if val is not None:
                target = "generation_latency_ms" if attr == "latency_ms" else attr
                setattr(result, target, val)
        return result

    def to_inference_response_kwargs(self) -> Dict[str, Any]:
        """Convert to kwargs for InferenceResponse construction."""
        return {
            "content": self.clean_text,
            "reasoning_content": self.reasoning_content,
            "model": self.model,
            "response_id": self.response_id,
            "input_tokens": self.input_tokens,
            "output_tokens": self.output_tokens,
            "reasoning_tokens": self.reasoning_tokens,
            "latency_ms": self.pipeline_latency_ms,
            "tool_calls": [
                {"tool": tc.name, "arguments": tc.arguments, "output": tc.output}
                if hasattr(tc, "name") else tc
                for tc in self.tool_calls
            ],
            "server_tps": self.server_tps,
            "time_to_first_token_s": self.time_to_first_token_s,
            "mood_tags": list(self.mood_tags),
            "image_requests": list(self.image_requests),
            "action_tags": list(self.action_tags),
        }
