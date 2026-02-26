"""
InferenceBenchmark — Automated benchmarking framework for LMStudio models.

Measures tokens/sec, time-to-first-token, latency, and VRAM usage across
configurable test matrices. Stores results in Nexus.

Usage::

    from engine.lmstudio.benchmark import InferenceBenchmark

    bench = InferenceBenchmark()
    results = bench.run_quick("qwen3-8b", runs=10)
    bench.run_matrix("qwen3-8b", temperatures=[0.0, 0.5, 0.7, 1.0])
    bench.compare_models(["qwen3-8b", "phi-4"], runs=5)
"""
from __future__ import annotations

import logging
import statistics
import time
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

import requests

from engine.config import get_config

logger = logging.getLogger(__name__)

# ── Benchmark prompts by category ───────────────────────────────────────

BENCHMARK_PROMPTS = {
    "short": "What is the capital of France? Answer in one sentence.",
    "medium": (
        "Explain the concept of gradient descent in machine learning. "
        "Include its variants and when to use each one."
    ),
    "long": (
        "Write a detailed analysis of the trade-offs between microservices "
        "and monolithic architectures. Cover performance, scalability, "
        "development velocity, operational complexity, and testing strategies. "
        "Provide concrete examples for each point."
    ),
    "code": (
        "Write a Python function that implements a priority queue using a "
        "binary heap. Include type hints, docstrings, and handle edge cases."
    ),
    "roleplay": (
        "You are a mysterious tavern keeper in a fantasy world. A weary "
        "traveler walks in and asks about rumors of a dragon in the mountains. "
        "Respond in character with atmosphere and personality."
    ),
    "routing": "classify: What tool should I use to check the weather?",
}


@dataclass
class BenchmarkResult:
    """Result of a single benchmark run."""

    model: str
    prompt_type: str
    temperature: float
    max_tokens: int
    context_length: int
    n_parallel: int

    # Timing
    total_latency_ms: float = 0.0
    time_to_first_token_ms: float = 0.0
    generation_time_ms: float = 0.0

    # Throughput
    prompt_tokens: int = 0
    completion_tokens: int = 0
    tokens_per_second: float = 0.0

    # Status
    success: bool = True
    error: str = ""

    def to_dict(self) -> Dict[str, Any]:
        """Serialize for storage."""
        return {
            "model": self.model,
            "prompt_type": self.prompt_type,
            "temperature": self.temperature,
            "max_tokens": self.max_tokens,
            "context_length": self.context_length,
            "n_parallel": self.n_parallel,
            "total_latency_ms": round(self.total_latency_ms, 1),
            "ttft_ms": round(self.time_to_first_token_ms, 1),
            "generation_ms": round(self.generation_time_ms, 1),
            "prompt_tokens": self.prompt_tokens,
            "completion_tokens": self.completion_tokens,
            "tps": round(self.tokens_per_second, 1),
            "success": self.success,
            "error": self.error,
        }


@dataclass
class BenchmarkSummary:
    """Aggregate statistics from multiple benchmark runs."""

    model: str
    config_label: str
    runs: int = 0
    results: List[BenchmarkResult] = field(default_factory=list)

    @property
    def successful(self) -> List[BenchmarkResult]:
        return [r for r in self.results if r.success]

    @property
    def success_rate(self) -> float:
        return len(self.successful) / len(self.results) if self.results else 0.0

    def _stat(self, values: List[float]) -> Dict[str, float]:
        """Compute mean, median, p95, p99, min, max."""
        if not values:
            return {"mean": 0, "median": 0, "p95": 0, "p99": 0, "min": 0, "max": 0}
        sv = sorted(values)
        n = len(sv)
        return {
            "mean": round(statistics.mean(sv), 1),
            "median": round(statistics.median(sv), 1),
            "p95": round(sv[int(n * 0.95)] if n > 1 else sv[0], 1),
            "p99": round(sv[int(n * 0.99)] if n > 1 else sv[0], 1),
            "min": round(sv[0], 1),
            "max": round(sv[-1], 1),
        }

    @property
    def latency_stats(self) -> Dict[str, float]:
        return self._stat([r.total_latency_ms for r in self.successful])

    @property
    def tps_stats(self) -> Dict[str, float]:
        return self._stat([r.tokens_per_second for r in self.successful])

    @property
    def ttft_stats(self) -> Dict[str, float]:
        return self._stat([r.time_to_first_token_ms for r in self.successful])

    def to_markdown(self) -> str:
        """Format as markdown report."""
        lat = self.latency_stats
        tps = self.tps_stats
        ttft = self.ttft_stats
        lines = [
            f"## Benchmark: {self.model}",
            f"Config: {self.config_label}",
            f"Runs: {len(self.successful)}/{self.runs} successful "
            f"({self.success_rate:.0%})",
            "",
            "| Metric | Mean | Median | P95 | P99 | Min | Max |",
            "|--------|------|--------|-----|-----|-----|-----|",
            f"| Latency (ms) | {lat['mean']} | {lat['median']} | "
            f"{lat['p95']} | {lat['p99']} | {lat['min']} | {lat['max']} |",
            f"| TPS | {tps['mean']} | {tps['median']} | "
            f"{tps['p95']} | {tps['p99']} | {tps['min']} | {tps['max']} |",
            f"| TTFT (ms) | {ttft['mean']} | {ttft['median']} | "
            f"{ttft['p95']} | {ttft['p99']} | {ttft['min']} | {ttft['max']} |",
        ]
        return "\n".join(lines)


class InferenceBenchmark:
    """Automated benchmarking framework for LMStudio inference."""

    def __init__(self, config: Optional[Any] = None) -> None:
        self._config = config or get_config()
        self._host = self._config.get("lmstudio.host", "localhost")
        self._port = self._config.get("lmstudio.port", 1234)
        self._base_url = f"http://{self._host}:{self._port}"
        self._nexus_url = self._config.get("nexus.url", "http://localhost:8700/api")
        self._summaries: List[BenchmarkSummary] = []

    # ── Single run ──────────────────────────────────────────────────

    def _run_single(
        self,
        model: str,
        prompt: str,
        temperature: float = 0.7,
        max_tokens: int = 256,
        prompt_type: str = "medium",
    ) -> BenchmarkResult:
        """Execute a single inference call and measure metrics."""
        result = BenchmarkResult(
            model=model,
            prompt_type=prompt_type,
            temperature=temperature,
            max_tokens=max_tokens,
            context_length=0,
            n_parallel=0,
        )

        payload = {
            "model": model,
            "messages": [{"role": "user", "content": prompt}],
            "temperature": temperature,
            "max_tokens": max_tokens,
            "stream": True,
        }

        try:
            t0 = time.monotonic()
            ttft_recorded = False

            resp = requests.post(
                f"{self._base_url}/v1/chat/completions",
                json=payload,
                stream=True,
                timeout=120,
            )
            resp.raise_for_status()

            completion_tokens = 0
            for line in resp.iter_lines(decode_unicode=True):
                if not line or not line.startswith("data: "):
                    continue
                data_str = line[6:]
                if data_str.strip() == "[DONE]":
                    break

                if not ttft_recorded:
                    result.time_to_first_token_ms = (
                        time.monotonic() - t0
                    ) * 1000
                    ttft_recorded = True
                completion_tokens += 1

            elapsed = (time.monotonic() - t0) * 1000
            result.total_latency_ms = elapsed
            result.generation_time_ms = elapsed - result.time_to_first_token_ms
            result.completion_tokens = completion_tokens
            if result.generation_time_ms > 0:
                result.tokens_per_second = (
                    completion_tokens / (result.generation_time_ms / 1000)
                )

        except Exception as e:
            result.success = False
            result.error = str(e)
            logger.warning("Benchmark run failed: %s", e)

        return result

    # ── Quick benchmark ─────────────────────────────────────────────

    def run_quick(
        self,
        model: str,
        runs: int = 10,
        prompt_type: str = "medium",
        temperature: float = 0.7,
        max_tokens: int = 256,
    ) -> BenchmarkSummary:
        """Run a quick benchmark with fixed settings."""
        prompt = BENCHMARK_PROMPTS.get(prompt_type, BENCHMARK_PROMPTS["medium"])
        config_label = f"temp={temperature}, max_tokens={max_tokens}, type={prompt_type}"

        summary = BenchmarkSummary(
            model=model,
            config_label=config_label,
            runs=runs,
        )

        logger.info(
            "Starting quick benchmark: %s, %d runs, %s",
            model, runs, config_label,
        )

        for i in range(runs):
            result = self._run_single(
                model=model,
                prompt=prompt,
                temperature=temperature,
                max_tokens=max_tokens,
                prompt_type=prompt_type,
            )
            summary.results.append(result)
            if result.success:
                logger.debug(
                    "Run %d/%d: %.0fms, %.1f TPS",
                    i + 1, runs, result.total_latency_ms, result.tokens_per_second,
                )
            else:
                logger.warning("Run %d/%d failed: %s", i + 1, runs, result.error)

        self._summaries.append(summary)
        logger.info(
            "Benchmark complete: %s — avg %.0fms, %.1f TPS, %.0f%% success",
            model,
            summary.latency_stats["mean"],
            summary.tps_stats["mean"],
            summary.success_rate * 100,
        )
        return summary

    # ── Config matrix ───────────────────────────────────────────────

    def run_matrix(
        self,
        model: str,
        temperatures: Optional[List[float]] = None,
        max_tokens_list: Optional[List[int]] = None,
        prompt_types: Optional[List[str]] = None,
        runs_per_config: int = 5,
    ) -> List[BenchmarkSummary]:
        """Run benchmarks across a configuration matrix."""
        temps = temperatures or [0.0, 0.3, 0.7, 1.0]
        tokens = max_tokens_list or [128, 256, 512]
        prompts = prompt_types or ["short", "medium", "long"]

        results: List[BenchmarkSummary] = []

        total = len(temps) * len(tokens) * len(prompts)
        logger.info("Starting matrix benchmark: %d configurations", total)

        for temp in temps:
            for max_tok in tokens:
                for pt in prompts:
                    summary = self.run_quick(
                        model=model,
                        runs=runs_per_config,
                        prompt_type=pt,
                        temperature=temp,
                        max_tokens=max_tok,
                    )
                    results.append(summary)

        self._summaries.extend(results)
        return results

    # ── Model comparison ────────────────────────────────────────────

    def compare_models(
        self,
        models: List[str],
        runs: int = 5,
        prompt_type: str = "medium",
    ) -> List[BenchmarkSummary]:
        """Compare multiple models on the same prompts."""
        results: List[BenchmarkSummary] = []
        for model in models:
            summary = self.run_quick(
                model=model, runs=runs, prompt_type=prompt_type,
            )
            results.append(summary)
        return results

    # ── Nexus storage ───────────────────────────────────────────────

    def store_results(self, summary: BenchmarkSummary) -> Optional[str]:
        """Store benchmark results in Nexus."""
        try:
            content = summary.to_markdown()
            timestamp = time.strftime("%Y-%m-%d %H:%M")
            resp = requests.post(
                f"{self._nexus_url}/entries",
                json={
                    "title": f"Benchmark: {summary.model} — {timestamp}",
                    "content": content,
                    "content_type": "audit",
                    "category": "performance",
                    "tags": ["benchmark", "auto-generated", summary.model],
                },
                timeout=10,
            )
            if resp.ok:
                entry_id = resp.json().get("id", "?")
                logger.info("Stored benchmark in Nexus: %s", entry_id)
                return entry_id
            logger.warning("Nexus store failed: %s", resp.text[:200])
        except Exception as e:
            logger.warning("Cannot store to Nexus: %s", e)
        return None

    def store_all(self) -> List[str]:
        """Store all accumulated summaries in Nexus."""
        ids = []
        for summary in self._summaries:
            entry_id = self.store_results(summary)
            if entry_id:
                ids.append(entry_id)
        return ids

    # ── Report generation ───────────────────────────────────────────

    def generate_report(self) -> str:
        """Generate a markdown report of all accumulated benchmarks."""
        lines = [
            "# Inference Benchmark Report",
            f"Generated: {time.strftime('%Y-%m-%d %H:%M')}",
            f"Total configurations tested: {len(self._summaries)}",
            "",
        ]
        for summary in self._summaries:
            lines.append(summary.to_markdown())
            lines.append("")
        return "\n".join(lines)
