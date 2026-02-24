"""
TrainingCapture — Auto-captures training data candidates from pipeline events.

Hooks into the pipeline to extract training examples for Gemma 270M fine-tuning.
Each pipeline execution may produce multiple training candidates across datasets:

- **tag_extraction** — LLM output with tags → structured tag routing
- **tool_routing** — context → tool call decision
- **priority_classify** — request metadata → priority/tier
- **response_validate** — bad output → validation result

Candidates are stored in MetricsDB and can be reviewed/exported via the
Command Center or ``training/prepare_from_live.py``.
"""

from __future__ import annotations

import json
import logging
from typing import Any, Dict, List, Optional

from engine.observability.metrics_db import MetricsDB, get_metrics_db

logger = logging.getLogger(__name__)


class TrainingCapture:
    """
    Listens to pipeline events and captures training data candidates.

    Usage::

        capture = TrainingCapture()

        # After each pipeline execution:
        capture.on_pipeline_complete(request, result)

        # Query stats:
        capture.get_stats()
    """

    def __init__(
        self,
        db: Optional[MetricsDB] = None,
        min_quality: float = 0.5,
        enabled: bool = True,
    ):
        self._db = db or get_metrics_db()
        self._min_quality = min_quality
        self._enabled = enabled
        self._capture_count = 0

    @property
    def enabled(self) -> bool:
        return self._enabled

    @enabled.setter
    def enabled(self, value: bool) -> None:
        self._enabled = value

    @property
    def capture_count(self) -> int:
        return self._capture_count

    def on_pipeline_complete(self, request: Any, result: Any) -> int:
        """
        Extract training candidates from a completed pipeline execution.

        Returns the number of candidates captured.
        """
        if not self._enabled:
            return 0

        count = 0
        try:
            count += self._capture_tag_extraction(result)
            count += self._capture_tool_routing(request, result)
            count += self._capture_priority(request, result)
            count += self._capture_validation(request, result)
        except Exception as exc:
            logger.debug("Training capture failed: %s", exc)

        self._capture_count += count
        return count

    def get_stats(self) -> Dict[str, Any]:
        """Get training data statistics."""
        return self._db.get_training_stats()

    # ── Dataset-specific capture ────────────────────────────────────

    def _capture_tag_extraction(self, result: Any) -> int:
        """Capture tag extraction examples from results with tags."""
        raw = getattr(result, "raw_text", "")
        mood_tags = getattr(result, "mood_tags", [])
        image_requests = getattr(result, "image_requests", [])
        action_tags = getattr(result, "action_tags", [])
        voice = getattr(result, "voice_style", "")
        clean = getattr(result, "clean_text", "")

        if not (mood_tags or image_requests or action_tags):
            return 0

        # Build structured output
        output = {"clean_text": clean}
        if mood_tags:
            output["mood"] = mood_tags[0] if len(mood_tags) == 1 else mood_tags
        if image_requests:
            output["image"] = image_requests[0] if len(image_requests) == 1 else image_requests
        if action_tags:
            output["action"] = action_tags[0] if len(action_tags) == 1 else action_tags
        if voice:
            output["voice"] = voice

        # Format as tool call for Gemma training
        output_text = (
            f'<tool_call>{{"name":"route_tags","arguments":'
            f'{json.dumps(output)}}}</tool_call>'
        )

        quality = self._estimate_quality(result)
        if quality >= self._min_quality:
            self._db.store_training_candidate(
                source="pipeline",
                dataset="tag_extraction",
                input_text=raw,
                output_text=output_text,
                quality_score=quality,
            )
            return 1
        return 0

    def _capture_tool_routing(self, request: Any, result: Any) -> int:
        """Capture tool call routing examples."""
        tool_calls = getattr(result, "tool_calls", [])
        if not tool_calls:
            return 0

        count = 0
        for tc in tool_calls:
            name = getattr(tc, "name", "") or (tc.get("name", "") if isinstance(tc, dict) else "")
            args = getattr(tc, "arguments", {}) or (tc.get("arguments", {}) if isinstance(tc, dict) else {})
            success = getattr(tc, "success", True)

            if not name:
                continue

            context = self._describe_request(request)
            output_text = (
                f'<tool_call>{{"name":"{name}","arguments":'
                f'{json.dumps(args)}}}</tool_call>'
            )

            quality = 1.0 if success else 0.3
            if quality >= self._min_quality:
                self._db.store_training_candidate(
                    source="pipeline",
                    dataset="tool_routing",
                    input_text=context,
                    output_text=output_text,
                    quality_score=quality,
                )
                count += 1

        return count

    def _capture_priority(self, request: Any, result: Any) -> int:
        """Capture priority classification examples."""
        scene = getattr(request, "scene", "") if request else ""
        agent = getattr(request, "agent_id", "") if request else ""
        priority = getattr(request, "priority", "") if request else ""
        tier = getattr(result, "tier", "")

        if not (scene or agent):
            return 0

        input_text = f"{scene}:{agent}:{priority}"
        output_text = json.dumps({"tier": tier, "priority": str(priority)})

        self._db.store_training_candidate(
            source="pipeline",
            dataset="priority_classify",
            input_text=input_text,
            output_text=output_text,
            quality_score=1.0,
        )
        return 1

    def _capture_validation(self, request: Any, result: Any) -> int:
        """Capture response validation examples from killed generations."""
        killed = getattr(result, "generation_killed", False)
        killed_content = getattr(result, "killed_content", "")

        if not killed or not killed_content:
            return 0

        expected = "dialogue"
        if request and hasattr(request, "metadata"):
            meta = getattr(request, "metadata", {}) or {}
            expected = meta.get("expected_format", "dialogue")

        input_text = f"Expected: {expected}. Got: {killed_content[:200]}"
        analysis = getattr(result, "watcher_analysis", None)
        kill_reason = getattr(analysis, "kill_reason", "quality_gate") if analysis else "quality_gate"

        output_text = json.dumps({
            "valid": False,
            "reason": kill_reason,
            "suggested_action": "retry_with_constraint",
        })

        self._db.store_training_candidate(
            source="pipeline",
            dataset="response_validate",
            input_text=input_text,
            output_text=output_text,
            quality_score=1.0,
            notes="Auto-captured from kill switch",
        )
        return 1

    # ── Helpers ──────────────────────────────────────────────────────

    def _estimate_quality(self, result: Any) -> float:
        """Estimate quality score for a result."""
        analysis = getattr(result, "watcher_analysis", None)
        if analysis:
            accept = getattr(analysis, "acceptability", 0.5)
            return accept

        # If no watcher, check if it was accepted (not killed)
        if getattr(result, "generation_killed", False):
            return 0.2
        return 0.7

    def _describe_request(self, request: Any) -> str:
        """Describe a request for training context."""
        if request is None:
            return "unknown request"
        parts = []
        for attr in ("scene", "agent_id", "priority"):
            val = getattr(request, attr, None)
            if val:
                parts.append(f"{attr}={val}")
        meta = getattr(request, "metadata", {}) or {}
        if meta.get("character_name"):
            parts.append(f"character={meta['character_name']}")
        return ", ".join(parts) if parts else "unknown request"
