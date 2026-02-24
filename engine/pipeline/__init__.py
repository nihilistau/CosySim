"""
CosySim Pipeline — Parallel stream architecture for real-time LLM orchestration.

The pipeline replaces the sequential request→response flow with parallel
processing: while the primary LLM generates tokens, a watcher model analyzes
them in real time for intent classification, quality gating (kill switch),
and tool pre-warming (token-ahead routing).

Usage::

    from engine.pipeline import VirtualPipeline, PipelineConfig

    pipeline = VirtualPipeline(vam, sdk_client, watcher)
    result = pipeline.execute(request)      # PipelineResult
    # or streaming:
    for token in pipeline.execute_stream(request, on_delta=print):
        ...
"""

from engine.pipeline.pipeline_result import (
    PipelineConfig,
    PipelineResult,
    PreWarmResult,
    WatcherAnalysis,
    WatcherSignal,
)
from engine.pipeline.kill_switch import KillSwitch
from engine.pipeline.stream_watcher import StreamWatcher
from engine.pipeline.token_router import TokenAheadRouter
from engine.pipeline.virtual_pipeline import VirtualPipeline

__all__ = [
    "KillSwitch",
    "PipelineConfig",
    "PipelineResult",
    "PreWarmResult",
    "StreamWatcher",
    "TokenAheadRouter",
    "VirtualPipeline",
    "WatcherAnalysis",
    "WatcherSignal",
]
