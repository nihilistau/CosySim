"""
VirtualPipeline — Parallel stream orchestrator for CosySim.

Replaces sequential request→response with parallel processing:

1. Starts primary LLM generation (streaming)
2. Feeds tokens to StreamProcessor (tag extraction, UI callbacks)
3. Feeds tokens to StreamWatcher (quality gating, intent detection)
4. Pre-warms MCP tools on intent detection (token-ahead routing)
5. Kill switch cancels bad generations mid-stream
6. Assembles PipelineResult from all parallel results

Usage::

    pipeline = VirtualPipeline(vam, config=PipelineConfig())
    result = pipeline.execute(request)      # blocking
    # or streaming:
    for token in pipeline.execute_stream(request, on_delta=print):
        ...
    result = pipeline.get_last_result()
"""

from __future__ import annotations

import logging
import time
from typing import Any, Callable, Dict, Generator, List, Optional

from engine.pipeline.kill_switch import KillSwitch
from engine.pipeline.pipeline_result import (
    PipelineConfig,
    PipelineResult,
    WatcherAnalysis,
    WatcherSignal,
)
from engine.pipeline.stream_watcher import StreamWatcher, WatchContext
from engine.pipeline.token_router import TokenAheadRouter

logger = logging.getLogger(__name__)


class VirtualPipeline:
    """
    Parallel stream orchestrator.

    The pipeline is an optional execution path within VirtualAgentManager.
    If the watcher model isn't loaded, it still works — just without parallel
    watching (degrades to enhanced streaming with better result typing).
    """

    def __init__(
        self,
        vam: Any = None,
        config: PipelineConfig = PipelineConfig(),
        sdk_client: Any = None,
        tool_executor: Optional[Callable] = None,
        on_metrics: Optional[Callable] = None,
    ):
        self._vam = vam
        self._config = config
        self._sdk = sdk_client

        # Sub-components
        self._watcher = StreamWatcher(config=config, sdk_client=sdk_client)
        self._kill_switch = KillSwitch(config=config)
        self._token_router = TokenAheadRouter(
            tool_executor=tool_executor,
            timeout=config.pre_warm_timeout,
        )

        # Metrics callback
        self._on_metrics = on_metrics

        # Last result for streaming mode
        self._last_result: Optional[PipelineResult] = None

    @property
    def config(self) -> PipelineConfig:
        return self._config

    @property
    def watcher(self) -> StreamWatcher:
        return self._watcher

    def execute(
        self,
        request: Any,
        *,
        stream_fn: Optional[Callable] = None,
        on_delta: Optional[Callable] = None,
        context: Optional[WatchContext] = None,
    ) -> PipelineResult:
        """
        Execute the full pipeline: generate + watch + pre-warm + assemble.

        Args:
            request: InferenceRequest or compatible dict
            stream_fn: Callable that yields token strings (overrides VAM streaming)
            on_delta: Callback for each token (UI streaming)
            context: WatchContext for the watcher

        Returns:
            PipelineResult with all processed data
        """
        t0 = time.perf_counter()
        self._kill_switch.reset()
        self._token_router.reset()

        # Build watch context
        watch_ctx = context or self._build_watch_context(request)

        # Try generation (with retries on kill)
        result = self._run_generation(
            request,
            stream_fn=stream_fn,
            on_delta=on_delta,
            watch_ctx=watch_ctx,
        )

        result.pipeline_latency_ms = (time.perf_counter() - t0) * 1000
        result.pipeline_ended = time.time()
        result.retry_count = self._kill_switch.retry_count

        self._last_result = result

        # Emit metrics
        if self._on_metrics:
            try:
                self._on_metrics(result)
            except Exception:
                logger.debug("Suppressed exception", exc_info=True)

        return result

    def execute_stream(
        self,
        request: Any,
        *,
        stream_fn: Optional[Callable] = None,
        on_delta: Optional[Callable] = None,
        context: Optional[WatchContext] = None,
    ) -> Generator[str, None, PipelineResult]:
        """
        Streaming pipeline — yields tokens while running watcher in parallel.

        The generator's return value (via StopIteration) is the PipelineResult.
        Use ``get_last_result()`` to retrieve it after exhausting the generator.
        """
        t0 = time.perf_counter()
        self._kill_switch.reset()
        self._token_router.reset()

        watch_ctx = context or self._build_watch_context(request)
        self._watcher.start_session(watch_ctx)

        # Get the token stream
        stream = stream_fn() if stream_fn else self._get_stream(request)

        accumulated = []
        killed = False

        for token in stream:
            accumulated.append(token)

            # Feed watcher
            signal = self._watcher.feed(token)

            # Handle watcher signals
            if signal == WatcherSignal.KILL and self._kill_switch.enabled:
                analysis = self._watcher.get_analysis()
                decision = self._kill_switch.evaluate(
                    analysis, "".join(accumulated), len(accumulated)
                )
                if decision.should_kill:
                    self._kill_switch.on_kill("".join(accumulated))
                    killed = True
                    break

            if signal == WatcherSignal.PRE_WARM and self._config.pre_warm_enabled:
                analysis = self._watcher.get_analysis()
                for tool in analysis.predicted_tools:
                    self._token_router.on_intent_detected(tool)

            if signal == WatcherSignal.ROUTE:
                for tag_type, values in self._watcher.tags_detected.items():
                    for val in values:
                        self._token_router.on_tag_detected(tag_type, val)

            # Yield to caller
            yield token
            if on_delta:
                try:
                    on_delta(token)
                except Exception:
                    logger.debug("Suppressed exception", exc_info=True)

        # Build result
        raw_text = "".join(accumulated)
        result = self._build_result(raw_text, killed=killed)
        result.pipeline_latency_ms = (time.perf_counter() - t0) * 1000
        result.pipeline_ended = time.time()

        self._last_result = result
        return result

    def get_last_result(self) -> Optional[PipelineResult]:
        """Get the result from the last execute/execute_stream call."""
        return self._last_result

    # ── Internal methods ────────────────────────────────────────────

    def _run_generation(
        self,
        request: Any,
        *,
        stream_fn: Optional[Callable],
        on_delta: Optional[Callable],
        watch_ctx: WatchContext,
    ) -> PipelineResult:
        """Run generation with kill switch retries."""
        attempt = 0
        max_attempts = self._config.max_retries + 1
        best_result: Optional[PipelineResult] = None

        while attempt < max_attempts:
            self._watcher.start_session(watch_ctx)

            stream = stream_fn() if stream_fn else self._get_stream(request)

            accumulated: List[str] = []
            killed = False
            t_gen = time.perf_counter()

            for token in stream:
                accumulated.append(token)

                # Feed watcher
                signal = self._watcher.feed(token)

                # Check kill switch
                if signal == WatcherSignal.KILL and self._kill_switch.enabled:
                    analysis = self._watcher.get_analysis()
                    decision = self._kill_switch.evaluate(
                        analysis, "".join(accumulated), len(accumulated)
                    )
                    if decision.should_kill and decision.retry_allowed:
                        self._kill_switch.on_kill("".join(accumulated))
                        killed = True
                        break

                # Token-ahead routing
                if signal == WatcherSignal.PRE_WARM and self._config.pre_warm_enabled:
                    analysis = self._watcher.get_analysis()
                    for tool in analysis.predicted_tools:
                        self._token_router.on_intent_detected(tool)

                if signal == WatcherSignal.ROUTE:
                    for tag_type, values in self._watcher.tags_detected.items():
                        for val in values:
                            self._token_router.on_tag_detected(tag_type, val)

                # UI callback
                if on_delta:
                    try:
                        on_delta(token)
                    except Exception:
                        logger.debug("Suppressed exception", exc_info=True)

            raw_text = "".join(accumulated)
            gen_time = (time.perf_counter() - t_gen) * 1000

            result = self._build_result(raw_text, killed=killed)
            result.generation_latency_ms = gen_time

            if not killed:
                return result

            # Track best result
            if best_result is None or len(raw_text) > len(best_result.raw_text):
                best_result = result

            attempt += 1

            # Modify request for retry if possible
            if hasattr(request, "messages"):
                retry_mods = self._kill_switch.modify_for_retry(
                    request.messages,
                    getattr(request, "temperature", None),
                    self._watcher.kill_reason,
                )
                request.messages = retry_mods["messages"]
                request.temperature = retry_mods["temperature"]

        # Exhausted retries — return best attempt
        if best_result:
            best_result.generation_killed = True
            best_result.retry_count = self._kill_switch.retry_count
            return best_result

        return PipelineResult(generation_killed=True)

    def _get_stream(self, request: Any) -> Generator[str, None, None]:
        """Get a token stream from VAM."""
        if self._vam and hasattr(self._vam, "infer_stream"):
            yield from self._vam.infer_stream(request)
        else:
            yield ""

    def _build_result(self, raw_text: str, killed: bool = False) -> PipelineResult:
        """Build PipelineResult from accumulated text and watcher analysis."""
        from engine.agents.stream_processor import StreamProcessor

        # Use StreamProcessor for tag extraction — feed via on_event-compatible path
        proc = StreamProcessor()
        # Directly populate content parts and trigger tag scanning
        proc._content_parts.append(raw_text)
        proc._scan_for_tags(raw_text)
        processed = proc.result()

        # Collect pre-warmed results
        pre_warmed = self._token_router.collect_results() if self._token_router.active_count > 0 or self._token_router.completed_count > 0 else []

        # Mark which pre-warmed tools were actually used
        for pw in pre_warmed:
            tags = self._watcher.tags_detected
            if pw.tool_name == "generate_image_request" and tags.get("image"):
                pw.was_used = True
            elif pw.tool_name == "update_mood" and tags.get("mood"):
                pw.was_used = True

        return PipelineResult(
            raw_text=processed.raw_text,
            clean_text=processed.clean_text,
            reasoning_content=processed.reasoning_content,
            mood_tags=list(processed.mood_tags),
            image_requests=list(processed.image_requests),
            action_tags=list(processed.action_tags),
            stat_deltas=list(processed.stat_deltas),
            voice_style=processed.voice_style,
            tool_calls=list(processed.tool_calls),
            model=processed.model,
            input_tokens=processed.input_tokens,
            output_tokens=processed.output_tokens,
            reasoning_tokens=processed.reasoning_tokens,
            server_tps=processed.server_tps,
            time_to_first_token_s=processed.time_to_first_token_s,
            response_id=processed.response_id,
            watcher_analysis=self._watcher.get_analysis(),
            pre_warmed_results=pre_warmed,
            generation_killed=killed,
            killed_content="".join(self._kill_switch.killed_contents),
            pipeline_started=time.time(),
        )

    def _build_watch_context(self, request: Any) -> WatchContext:
        """Build WatchContext from an InferenceRequest."""
        ctx = WatchContext()
        if hasattr(request, "agent_id"):
            ctx.agent_id = request.agent_id
        if hasattr(request, "scene"):
            ctx.scene_id = request.scene
        if hasattr(request, "metadata"):
            meta = request.metadata or {}
            ctx.character_name = meta.get("character_name", "")
            ctx.scene_rules = meta.get("scene_rules", [])
            ctx.expected_format = meta.get("expected_format", "dialogue")
            ctx.forbidden_patterns = meta.get("forbidden_patterns", [])
        if hasattr(request, "max_output_tokens"):
            ctx.max_tokens = request.max_output_tokens
        return ctx
