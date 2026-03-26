"""
Runtime Data Collection Hooks
=============================

Collects training examples from the live system at runtime.
Writes to training/datasets/collected/{model_type}_live.jsonl.
Non-blocking append-only file writes.

Version: v1.55.0 [2026-03-26]
Author:  CosySim Team

Change Log:
    v1.55.0 [2026-03-26] — Add collect_agent_decision() and collect_agent_outcome()
                            for self-improvement training loop
    v1.0.0  [2026-03-01] — Initial data collection hooks
"""
from __future__ import annotations

import json
import logging
import threading
import time
import uuid
from pathlib import Path
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

_COLLECTED_DIR = Path("training/datasets/collected")
_instance: Optional["DataCollector"] = None
_lock = threading.Lock()


class DataCollector:
    """Collects training examples from the live system at runtime.

    Writes to training/datasets/collected/{model_type}_live.jsonl.
    Non-blocking append-only file writes.
    """

    def __init__(self, base_dir: Optional[Path] = None) -> None:
        """Initialize DataCollector.

        Args:
            base_dir: Base directory for collected data. Defaults to training/datasets/collected.
        """
        self._base_dir = base_dir or _COLLECTED_DIR
        self._base_dir.mkdir(parents=True, exist_ok=True)
        self._write_lock = threading.Lock()
        self._stats: Dict[str, int] = {}

    def _live_path(self, model_type: str) -> Path:
        """Get path to live collection file for a model type."""
        return self._base_dir / f"{model_type}_live.jsonl"

    def _append(self, model_type: str, record: Dict[str, Any]) -> None:
        """Append a record to the live collection file."""
        path = self._live_path(model_type)
        record.setdefault("id", str(uuid.uuid4()))
        record.setdefault("collected_at", time.time())
        with self._write_lock:
            with path.open("a", encoding="utf-8") as f:
                f.write(json.dumps(record) + "\n")
            self._stats[model_type] = self._stats.get(model_type, 0) + 1

    def collect(
        self,
        model_type: str,
        input_text: str,
        output_text: str,
        quality: float = 1.0,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> None:
        """Collect a generic training example.

        Args:
            model_type: Target model type (must be in MODEL_ZOO).
            input_text: The input/instruction text.
            output_text: The expected output/response.
            quality: Quality score 0.0-1.0.
            metadata: Optional additional metadata.
        """
        try:
            record = {
                "model_type": model_type,
                "input": input_text,
                "output": output_text,
                "quality": quality,
                "metadata": metadata or {},
                "source": "runtime",
            }
            self._append(model_type, record)
        except Exception as e:
            logger.error(f"DataCollector.collect failed for {model_type}: {e}")

    def collect_tool_call(
        self,
        user_input: str,
        tool_name: str,
        params: Dict[str, Any],
        success: bool = True,
    ) -> None:
        """Collect a tool/skill call for tool_dispatch training.

        Args:
            user_input: The natural language user input.
            tool_name: The tool/skill that was called.
            params: The parameters passed to the tool.
            success: Whether the tool call succeeded.
        """
        try:
            output = json.dumps({"tool": tool_name, "args": params})
            quality = 1.0 if success else 0.3
            record = {
                "model_type": "tool_dispatch",
                "input": user_input,
                "output": output,
                "quality": quality,
                "metadata": {"tool_name": tool_name, "success": success},
                "source": "runtime",
            }
            self._append("tool_dispatch", record)
        except Exception as e:
            logger.error(f"DataCollector.collect_tool_call failed: {e}")

    def collect_grammar_error(
        self,
        bad_text: str,
        fixed_text: str,
        error_type: str = "syntax",
    ) -> None:
        """Collect a grammar error correction for grammar_scanner training.

        Args:
            bad_text: Text with errors.
            fixed_text: Corrected text.
            error_type: Type of error (syntax, json, yaml, python, etc.).
        """
        try:
            record = {
                "model_type": "grammar_scanner",
                "input": bad_text,
                "output": fixed_text,
                "quality": 1.0,
                "metadata": {"error_type": error_type},
                "source": "runtime",
            }
            self._append("grammar_scanner", record)
        except Exception as e:
            logger.error(f"DataCollector.collect_grammar_error failed: {e}")

    def collect_output_rating(
        self,
        output: str,
        rating: int,
        context: str = "",
        source: str = "feed",
    ) -> None:
        """Collect an LLM output quality rating for output_evaluator training.

        Args:
            output: The LLM output text.
            rating: Quality rating 1-5.
            context: Optional context for the output.
            source: Source of the rating (feed, user, auto, etc.).
        """
        try:
            rating = max(1, min(5, int(rating)))
            formatted_output = f"SCORE: {rating}\nREASON: Collected from {source}"
            record = {
                "model_type": "output_evaluator",
                "input": output if not context else f"Context: {context}\n\nOutput: {output}",
                "output": formatted_output,
                "quality": rating / 5.0,
                "metadata": {"rating": rating, "source": source},
                "source": "runtime",
            }
            self._append("output_evaluator", record)
        except Exception as e:
            logger.error(f"DataCollector.collect_output_rating failed: {e}")

    def collect_conversation(
        self,
        system_prompt: str,
        history: List[Dict[str, str]],
        response: str,
        character_id: Optional[str] = None,
        rating: Optional[float] = None,
    ) -> None:
        """Collect a conversation exchange for conversational model training.

        Args:
            system_prompt: Character system prompt.
            history: List of prior turns [{"role": "user/assistant", "content": str}].
            response: The assistant response to learn from.
            character_id: Optional character identifier.
            rating: Optional quality rating 0.0-1.0.
        """
        try:
            turns_text = "\n".join(
                f"{t['role'].upper()}: {t['content']}" for t in history
            )
            input_text = f"System: {system_prompt}\n\n{turns_text}"
            quality = rating if rating is not None else 1.0
            record = {
                "model_type": "conversational",
                "input": input_text,
                "output": response,
                "quality": quality,
                "metadata": {
                    "character_id": character_id,
                    "system_prompt": system_prompt,
                    "history": history,
                },
                "source": "runtime",
            }
            self._append("conversational", record)
        except Exception as e:
            logger.error(f"DataCollector.collect_conversation failed: {e}")

    def collect_code(
        self,
        prompt: str,
        code: str,
        language: str = "python",
        source: str = "session",
    ) -> None:
        """Collect a code generation example for coder model training.

        Args:
            prompt: The coding instruction/prompt.
            code: The generated/expected code.
            language: Programming language.
            source: Source of the example (session, nexus, codebase, etc.).
        """
        try:
            record = {
                "model_type": "coder",
                "input": prompt,
                "output": code,
                "quality": 1.0,
                "metadata": {"language": language, "source": source},
                "source": "runtime",
            }
            self._append("coder", record)
        except Exception as e:
            logger.error(f"DataCollector.collect_code failed: {e}")

    def collect_voice_sample(
        self,
        character_id: str,
        text: str,
        audio_path: str,
        quality_rating: float,
        backend: str,
    ) -> None:
        """Collect a voice audio sample for voice model training.

        Args:
            character_id: Character identifier.
            text: The text that was spoken.
            audio_path: Path to the WAV audio file.
            quality_rating: Quality rating 0.0-1.0.
            backend: TTS backend (piper, qwen3, orpheus).
        """
        try:
            model_type = f"voice_{backend}"
            record = {
                "model_type": model_type,
                "input": text,
                "output": audio_path,
                "quality": quality_rating,
                "metadata": {
                    "character_id": character_id,
                    "audio_path": audio_path,
                    "backend": backend,
                },
                "source": "runtime",
            }
            self._append(model_type, record)
        except Exception as e:
            logger.error(f"DataCollector.collect_voice_sample failed: {e}")

    # ── Agent Decision Training ─────────────────────────────────────────

    # v1.55.0 [2026-03-26] — Agent decision logging for self-improvement loop
    def collect_agent_decision(
        self,
        situation: str,
        action: str,
        character_id: str = "",
        scene: str = "",
        quality: float = 1.0,
        model: str = "",
    ) -> None:
        """Log an agent decision for routing/planning training data.

        Captures the situation→action mapping so the self-improvement pipeline
        can learn which decisions lead to good outcomes.

        Args:
            situation: The perceived context that led to the decision.
            action: The action taken (e.g. "speak: Hello there").
            character_id: Character who made the decision.
            scene: Scene where the decision was made.
            quality: Quality score 0.0–1.0 (1.0 = success, 0.3 = failure).
            model: LLM model used for the decision (if known).
        """
        try:
            record = {
                "model_type": "agent_decision",
                "input": situation,
                "output": action,
                "quality": quality,
                "metadata": {
                    "character_id": character_id,
                    "scene": scene,
                    "model": model,
                },
                "source": "runtime",
            }
            self._append("agent_decision", record)
            logger.debug(
                "[DataCollector] Agent decision collected "
                "(operation=collect_agent_decision, character=%s, scene=%s, quality=%.1f)",
                character_id, scene, quality,
            )
        except Exception as e:
            logger.error(
                "[DataCollector] collect_agent_decision failed "
                "(operation=collect_agent_decision, character=%s): %s",
                character_id, e,
            )

    # v1.55.0 [2026-03-26] — Agent outcome feedback for reinforcement signal
    def collect_agent_outcome(
        self,
        decision_summary: str,
        outcome: str,
        quality_rating: float = 1.0,
    ) -> None:
        """Feedback on whether an agent action succeeded.

        Provides a reinforcement signal that pairs with collect_agent_decision
        records, allowing the training pipeline to weight decisions by outcome.

        Args:
            decision_summary: Brief description of what was decided.
            outcome: Result category — "success", "partial", or "failure".
            quality_rating: Numeric quality 0.0–1.0.
        """
        try:
            # Map outcome string to a quality floor so the training pipeline
            # can filter by minimum quality reliably
            outcome_quality = {
                "success": max(quality_rating, 0.8),
                "partial": min(max(quality_rating, 0.3), 0.7),
                "failure": min(quality_rating, 0.3),
            }
            effective_quality = outcome_quality.get(outcome, quality_rating)

            record = {
                "model_type": "agent_decision",
                "input": f"[OUTCOME] {decision_summary}",
                "output": f"outcome={outcome}",
                "quality": effective_quality,
                "metadata": {
                    "outcome": outcome,
                    "original_rating": quality_rating,
                    "record_type": "outcome_feedback",
                },
                "source": "runtime",
            }
            self._append("agent_decision", record)
            logger.debug(
                "[DataCollector] Agent outcome collected "
                "(operation=collect_agent_outcome, outcome=%s, quality=%.2f)",
                outcome, effective_quality,
            )
        except Exception as e:
            logger.error(
                "[DataCollector] collect_agent_outcome failed "
                "(operation=collect_agent_outcome): %s", e,
            )

    # ── Debug Session Training ───────────────────────────────────────────

    def collect_debug_session(
        self,
        errors_before: List[Dict[str, Any]],
        file_changed: str,
        errors_after: Optional[List[Dict[str, Any]]] = None,
        marker_note: str = "",
    ) -> None:
        """Collect a browser debugging session for browser_debugger + error_classifier training.

        Called automatically by the CDP data miner, but can also be called manually
        after a fix cycle to record the session immediately.

        Args:
            errors_before: List of CDP error dicts before the fix (each has 'msg', 'scene', 'level').
            file_changed: Relative path of the file that was modified as the fix.
            errors_after: Errors remaining after the fix. If None, treated as unknown.
            marker_note: Optional human note describing what was changed.
        """
        try:
            from scripts.cdp_data_miner import (
                _make_browser_debugger_examples,
                _make_error_classifier_examples,
                _append_examples,
                classify_error,
            )
            import time as _time

            window = {
                "marker":        {"msg": f"file_change: {file_changed}", "ts": ""},
                "file_changed":  file_changed,
                "errors_before": errors_before,
                "errors_after":  errors_after or [],
                "ts_mark":       "",
            }
            debugger_examples   = _make_browser_debugger_examples([window])
            classifier_examples = _make_error_classifier_examples(errors_before)

            added_d = _append_examples("browser_debugger", debugger_examples)
            added_c = _append_examples("error_classifier", classifier_examples)
            logger.info(
                "DataCollector.collect_debug_session: +%d debugger, +%d classifier examples",
                added_d, added_c,
            )
        except Exception as e:
            logger.error(f"DataCollector.collect_debug_session failed: {e}")

    def flush(self, model_type: str) -> int:
        """Merge live data into training set.

        Reads the live JSONL file, converts to training format, and appends
        to the main training dataset. Clears the live file after merging.

        Args:
            model_type: Model type to flush.

        Returns:
            Number of records flushed.
        """
        live_path = self._live_path(model_type)
        if not live_path.exists():
            return 0

        try:
            records = []
            with live_path.open("r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if line:
                        try:
                            records.append(json.loads(line))
                        except json.JSONDecodeError:
                            continue

            if not records:
                return 0

            # Write to training dataset
            train_dir = Path("training/datasets")
            train_dir.mkdir(parents=True, exist_ok=True)
            train_path = train_dir / f"{model_type}_train.jsonl"

            with self._write_lock:
                with train_path.open("a", encoding="utf-8") as f:
                    for record in records:
                        alpaca = {
                            "instruction": record.get("input", ""),
                            "output": record.get("output", ""),
                            "input": "",
                            "metadata": record.get("metadata", {}),
                        }
                        f.write(json.dumps(alpaca) + "\n")

                # Clear live file
                live_path.write_text("", encoding="utf-8")
                self._stats[model_type] = 0

            count = len(records)
            logger.info(f"Flushed {count} records for {model_type} to {train_path}")

            # Store stats in Nexus
            try:
                from engine.nexus.client import get_nexus_client
                client = get_nexus_client()
                client.add_entry(
                    f"DataCollector flush: {model_type}",
                    f"Flushed {count} records into {train_path}",
                    content_type="note",
                    category="training",
                )
            except Exception:
                pass

            return count
        except Exception as e:
            logger.error(f"DataCollector.flush failed for {model_type}: {e}")
            return 0

    def flush_all(self) -> Dict[str, int]:
        """Flush all model type buffers.

        Returns:
            Dict mapping model_type to number of records flushed.
        """
        results: Dict[str, int] = {}
        try:
            if self._base_dir.exists():
                for path in self._base_dir.glob("*_live.jsonl"):
                    model_type = path.stem.replace("_live", "")
                    count = self.flush(model_type)
                    if count > 0:
                        results[model_type] = count
        except Exception as e:
            logger.error(f"DataCollector.flush_all failed: {e}")
        return results

    def stats(self) -> Dict[str, int]:
        """Get per-type buffer sizes (lines in live files).

        Returns:
            Dict mapping model_type to current line count in live file.
        """
        result: Dict[str, int] = {}
        try:
            if self._base_dir.exists():
                for path in self._base_dir.glob("*_live.jsonl"):
                    model_type = path.stem.replace("_live", "")
                    try:
                        count = sum(1 for line in path.open("r", encoding="utf-8") if line.strip())
                        result[model_type] = count
                    except Exception:
                        result[model_type] = 0
        except Exception as e:
            logger.error(f"DataCollector.stats failed: {e}")
        return result

    def get_collected(self, model_type: str, limit: int = 1000) -> List[Dict[str, Any]]:
        """Get collected records for a model type.

        Args:
            model_type: Model type to retrieve.
            limit: Maximum number of records to return.

        Returns:
            List of collected record dicts.
        """
        records: List[Dict[str, Any]] = []
        live_path = self._live_path(model_type)
        if not live_path.exists():
            return records
        try:
            with live_path.open("r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if line:
                        try:
                            records.append(json.loads(line))
                        except json.JSONDecodeError:
                            continue
                        if len(records) >= limit:
                            break
        except Exception as e:
            logger.error(f"DataCollector.get_collected failed for {model_type}: {e}")
        return records

    def get_stats(self) -> Dict[str, Any]:
        """Get comprehensive training stats for all model types.

        Returns:
            Dict with live buffer counts, total training examples, and last flush times.
        """
        result: Dict[str, Any] = {}
        try:
            # Live buffer counts
            live_counts = self.stats()
            for model_type, count in live_counts.items():
                result[f"{model_type}_live"] = count

            # Training dataset sizes
            train_dir = self._base_dir.parent
            if train_dir.exists():
                for path in sorted(train_dir.glob("*_train.jsonl")):
                    model_type = path.stem.replace("_train", "")
                    try:
                        count = sum(1 for line in path.open("r", encoding="utf-8") if line.strip())
                        result[f"{model_type}_train"] = count
                    except Exception:
                        result[f"{model_type}_train"] = 0

            result["total_live"] = sum(live_counts.values())
            result["model_types"] = len(live_counts)
        except Exception as e:
            logger.error(f"DataCollector.get_stats failed: {e}")
        return result

    def prune_low_quality(self, min_quality: float = 0.3) -> int:
        """Remove low-quality records from all live buffers.

        Args:
            min_quality: Minimum quality threshold (records below are removed).

        Returns:
            Number of records pruned.
        """
        pruned = 0
        try:
            if not self._base_dir.exists():
                return 0
            for live_path in self._base_dir.glob("*_live.jsonl"):
                kept: List[str] = []
                removed = 0
                try:
                    with live_path.open("r", encoding="utf-8") as f:
                        for line in f:
                            line = line.strip()
                            if not line:
                                continue
                            try:
                                rec = json.loads(line)
                                if rec.get("quality", 1.0) >= min_quality:
                                    kept.append(line)
                                else:
                                    removed += 1
                            except json.JSONDecodeError:
                                kept.append(line)
                    if removed > 0:
                        with self._write_lock:
                            live_path.write_text("\n".join(kept) + ("\n" if kept else ""), encoding="utf-8")
                        pruned += removed
                except Exception as exc:
                    logger.debug("prune_low_quality skip %s: %s", live_path, exc)
        except Exception as e:
            logger.error(f"DataCollector.prune_low_quality failed: {e}")
        return pruned


def get_data_collector() -> DataCollector:
    """Get the DataCollector singleton.

    Returns:
        The global DataCollector instance.
    """
    global _instance
    if _instance is None:
        with _lock:
            if _instance is None:
                _instance = DataCollector()
    return _instance
