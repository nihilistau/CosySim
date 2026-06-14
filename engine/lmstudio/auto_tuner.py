"""
AutoTuner — Iterative settings optimizer for LMStudio inference
================================================================

Runs benchmark matrices, adjusts settings toward best performance,
and stores optimal configs per model in Nexus.

Version: v1.44.0 [2026-03-21]
Author:  CosySim Team

Change Log:
    v1.44.0 [2026-03-21] — Replaced direct Nexus HTTP with NexusClient
    v1.43.0 [2026-03-21] — Initial auto-tuner

Usage::

    from engine.lmstudio.auto_tuner import AutoTuner

    tuner = AutoTuner()
    optimal = tuner.find_optimal("qwen3-8b", task_type="roleplay")
    tuner.test_hypothesis("cpu_overflow")
"""
from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from engine.config import get_config
from engine.lmstudio.benchmark import BenchmarkSummary, InferenceBenchmark

logger = logging.getLogger(__name__)


@dataclass
class TuningConfig:
    """A configuration to test."""

    temperature: float = 0.7
    max_tokens: int = 256
    n_parallel: int = 1
    context_length: int = 8192
    gpu_offload: float = 1.0
    label: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return {
            "temperature": self.temperature,
            "max_tokens": self.max_tokens,
            "n_parallel": self.n_parallel,
            "context_length": self.context_length,
            "gpu_offload": self.gpu_offload,
            "label": self.label,
        }


@dataclass
class TuningResult:
    """Result of a tuning exploration."""

    model: str
    task_type: str
    configs_tested: int = 0
    best_config: Optional[TuningConfig] = None
    best_tps: float = 0.0
    best_latency: float = 0.0
    all_results: List[Dict[str, Any]] = field(default_factory=list)

    def to_markdown(self) -> str:
        lines = [
            f"## Tuning Result: {self.model} ({self.task_type})",
            f"Configs tested: {self.configs_tested}",
            "",
        ]
        if self.best_config:
            lines.extend([
                f"### Best Config",
                f"- Temperature: {self.best_config.temperature}",
                f"- Max Tokens: {self.best_config.max_tokens}",
                f"- Best TPS: {self.best_tps:.1f}",
                f"- Best Latency: {self.best_latency:.0f}ms",
                "",
            ])

        if self.all_results:
            lines.extend([
                "### All Results",
                "| Config | TPS | Latency (ms) | Success % |",
                "|--------|-----|-------------|-----------|",
            ])
            for r in sorted(self.all_results, key=lambda x: x.get("tps", 0), reverse=True):
                lines.append(
                    f"| {r.get('label', '?')} | {r.get('tps', 0):.1f} | "
                    f"{r.get('latency', 0):.0f} | {r.get('success_rate', 0):.0%} |"
                )
        return "\n".join(lines)


# ── Task type defaults ──────────────────────────────────────────────────

TASK_TYPE_CONFIGS: Dict[str, List[TuningConfig]] = {
    "roleplay": [
        TuningConfig(temperature=0.6, max_tokens=512, label="roleplay-conservative"),
        TuningConfig(temperature=0.7, max_tokens=512, label="roleplay-balanced"),
        TuningConfig(temperature=0.8, max_tokens=512, label="roleplay-creative"),
        TuningConfig(temperature=0.9, max_tokens=768, label="roleplay-wild"),
    ],
    "code": [
        TuningConfig(temperature=0.0, max_tokens=512, label="code-deterministic"),
        TuningConfig(temperature=0.1, max_tokens=512, label="code-low"),
        TuningConfig(temperature=0.2, max_tokens=512, label="code-slight"),
        TuningConfig(temperature=0.3, max_tokens=768, label="code-moderate"),
    ],
    "routing": [
        TuningConfig(temperature=0.0, max_tokens=64, label="route-zero"),
        TuningConfig(temperature=0.1, max_tokens=64, label="route-low"),
        TuningConfig(temperature=0.0, max_tokens=128, label="route-zero-long"),
    ],
    "chat": [
        TuningConfig(temperature=0.5, max_tokens=256, label="chat-focused"),
        TuningConfig(temperature=0.7, max_tokens=256, label="chat-balanced"),
        TuningConfig(temperature=0.7, max_tokens=512, label="chat-long"),
        TuningConfig(temperature=0.8, max_tokens=256, label="chat-casual"),
    ],
    "narration": [
        TuningConfig(temperature=0.6, max_tokens=512, label="narr-measured"),
        TuningConfig(temperature=0.7, max_tokens=768, label="narr-balanced"),
        TuningConfig(temperature=0.8, max_tokens=768, label="narr-creative"),
    ],
}


class AutoTuner:
    """Iterative settings optimizer for LMStudio models."""

    def __init__(self, config: Optional[Any] = None) -> None:
        self._config = config or get_config()
        self._benchmark = InferenceBenchmark(self._config)
        self._results: List[TuningResult] = []

    def find_optimal(
        self,
        model: str,
        task_type: str = "chat",
        runs_per_config: int = 5,
        custom_configs: Optional[List[TuningConfig]] = None,
    ) -> TuningResult:
        """Find the optimal configuration for a model + task type."""
        configs = custom_configs or TASK_TYPE_CONFIGS.get(task_type, TASK_TYPE_CONFIGS["chat"])

        prompt_type_map = {
            "roleplay": "roleplay",
            "code": "code",
            "routing": "routing",
            "chat": "medium",
            "narration": "long",
        }
        prompt_type = prompt_type_map.get(task_type, "medium")

        result = TuningResult(
            model=model,
            task_type=task_type,
            configs_tested=len(configs),
        )

        logger.info(
            "Starting auto-tune: %s for %s (%d configs, %d runs each)",
            model, task_type, len(configs), runs_per_config,
        )

        for cfg in configs:
            summary = self._benchmark.run_quick(
                model=model,
                runs=runs_per_config,
                prompt_type=prompt_type,
                temperature=cfg.temperature,
                max_tokens=cfg.max_tokens,
            )

            avg_tps = summary.tps_stats["mean"]
            avg_lat = summary.latency_stats["mean"]

            result.all_results.append({
                "label": cfg.label,
                "tps": avg_tps,
                "latency": avg_lat,
                "success_rate": summary.success_rate,
                "config": cfg.to_dict(),
            })

            if avg_tps > result.best_tps:
                result.best_tps = avg_tps
                result.best_latency = avg_lat
                result.best_config = cfg

        self._results.append(result)
        logger.info(
            "Auto-tune complete: %s — best=%s (%.1f TPS, %.0fms)",
            model,
            result.best_config.label if result.best_config else "none",
            result.best_tps,
            result.best_latency,
        )
        return result

    def test_hypothesis(
        self,
        hypothesis: str,
        runs: int = 10,
    ) -> Dict[str, Any]:
        """Test a specific optimization hypothesis.

        Supported hypotheses:
        - "cpu_overflow": Compare GPU-only vs GPU+CPU routing for mixed workloads
        - "speculative": Test if speculative decoding improves throughput
        - "context_reduction": Compare short vs long context windows
        """
        logger.info("Testing hypothesis: %s", hypothesis)

        if hypothesis == "cpu_overflow":
            return self._test_cpu_overflow(runs)
        elif hypothesis == "speculative":
            return self._test_speculative(runs)
        elif hypothesis == "context_reduction":
            return self._test_context_reduction(runs)
        else:
            logger.warning("Unknown hypothesis: %s", hypothesis)
            return {"error": f"Unknown hypothesis: {hypothesis}"}

    def _test_cpu_overflow(self, runs: int) -> Dict[str, Any]:
        """Test whether routing simple tasks to CPU model improves throughput."""
        gpu_model = self._config.get("lmstudio.models.primary", "qwen3-8b")
        cpu_model = self._config.get("lmstudio.models.cpu_utility", "qwen3-4b-thinking")

        # Baseline: all tasks on GPU model
        gpu_results = self._benchmark.run_quick(
            model=gpu_model, runs=runs, prompt_type="short",
        )

        # Hypothesis: simple tasks on CPU model
        cpu_results = self._benchmark.run_quick(
            model=cpu_model, runs=runs, prompt_type="short",
        )

        result = {
            "hypothesis": "cpu_overflow",
            "gpu_model": gpu_model,
            "cpu_model": cpu_model,
            "gpu_tps": gpu_results.tps_stats["mean"],
            "cpu_tps": cpu_results.tps_stats["mean"],
            "gpu_latency": gpu_results.latency_stats["mean"],
            "cpu_latency": cpu_results.latency_stats["mean"],
            "verdict": "",
        }

        if cpu_results.tps_stats["mean"] > 0:
            tps_ratio = gpu_results.tps_stats["mean"] / max(cpu_results.tps_stats["mean"], 0.1)
            result["tps_ratio_gpu_to_cpu"] = round(tps_ratio, 2)

            if tps_ratio < 2.0:
                result["verdict"] = (
                    "CPU model is viable for simple tasks. "
                    "TPS difference is small enough to justify CPU offloading."
                )
            else:
                result["verdict"] = (
                    f"GPU is {tps_ratio:.1f}x faster. CPU overflow only useful "
                    f"when GPU is at capacity."
                )

        return result

    # v1.44.0 [2026-03-21] — Implemented speculative decoding benchmark
    def _test_speculative(self, runs: int) -> Dict[str, Any]:
        """Test if speculative decoding improves throughput.

        Loads main + draft model, benchmarks with spec decode active,
        then unloads draft and benchmarks without. Compares TPS and latency.
        """
        from engine.lmstudio.lms_client import get_lms_client

        client = get_lms_client()
        main_model = self._config.get("lmstudio.speculative.main_model", "")
        draft_model = self._config.get("lmstudio.speculative.draft_model", "")

        if not draft_model:
            return {
                "hypothesis": "speculative",
                "status": "skipped",
                "note": "No draft_model configured in lmstudio.speculative.draft_model",
            }

        if not main_model:
            main_model = client.resolve_model()
        if not main_model:
            return {
                "hypothesis": "speculative",
                "status": "skipped",
                "note": "No main model available",
            }

        # Phase 1: Benchmark WITH speculative decoding
        try:
            client.enable_speculative(main_model, draft_model)
        except Exception as exc:
            return {
                "hypothesis": "speculative",
                "status": "error",
                "note": f"Failed to enable speculative decoding: {exc}",
            }

        with_spec = self._benchmark.run_quick(
            model=main_model, runs=runs, prompt_type="medium",
        )

        # Phase 2: Benchmark WITHOUT speculative decoding
        try:
            client.disable_speculative(draft_model)
        except Exception:
            logger.debug("Failed to disable speculative for comparison", exc_info=True)

        without_spec = self._benchmark.run_quick(
            model=main_model, runs=runs, prompt_type="medium",
        )

        speedup = round(
            with_spec.tps_stats["mean"] / max(without_spec.tps_stats["mean"], 0.1), 2
        )

        return {
            "hypothesis": "speculative",
            "status": "completed",
            "main_model": main_model,
            "draft_model": draft_model,
            "with_spec_tps": with_spec.tps_stats["mean"],
            "without_spec_tps": without_spec.tps_stats["mean"],
            "with_spec_latency": with_spec.latency_stats["mean"],
            "without_spec_latency": without_spec.latency_stats["mean"],
            "speedup_factor": speedup,
            "recommendation": "enable" if speedup > 1.1 else "disable",
        }

    def _test_context_reduction(self, runs: int) -> Dict[str, Any]:
        """Test if shorter context improves throughput."""
        model = self._config.get("lmstudio.models.primary", "qwen3-8b")

        short = self._benchmark.run_quick(
            model=model, runs=runs, prompt_type="short", max_tokens=128,
        )
        long = self._benchmark.run_quick(
            model=model, runs=runs, prompt_type="long", max_tokens=512,
        )

        return {
            "hypothesis": "context_reduction",
            "short_tps": short.tps_stats["mean"],
            "long_tps": long.tps_stats["mean"],
            "short_latency": short.latency_stats["mean"],
            "long_latency": long.latency_stats["mean"],
            "speedup_factor": round(
                short.tps_stats["mean"] / max(long.tps_stats["mean"], 0.1), 2
            ),
        }

    # v1.44.0 [2026-03-21] — Uses NexusClient instead of raw HTTP
    def store_results(self, result: TuningResult) -> Optional[str]:
        """Store tuning results in Nexus via NexusClient."""
        try:
            from engine.nexus.client import get_nexus_client

            client = get_nexus_client()
            content = result.to_markdown()
            timestamp = time.strftime("%Y-%m-%d %H:%M")
            entry_id = client.add_entry(
                title=f"Tuning: {result.model} ({result.task_type}) — {timestamp}",
                content=content,
                content_type="audit",
                category="performance",
                tags=["tuning", "auto-generated", result.model, result.task_type],
            )
            if entry_id:
                logger.info("Stored tuning result in Nexus: %s", entry_id)
                return entry_id
        except Exception as e:
            logger.warning("Cannot store to Nexus: %s", e)
        return None
