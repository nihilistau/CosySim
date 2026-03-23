"""Agent workflow orchestrator for CosySim.

Provides 5 configurable agent workflow patterns for knowledge distillation,
dataset creation, research, metrics extraction, and quality auditing.
Each workflow can be run via CLI, MCP skill, or programmatic API.

Workflows:
  1. knowledge_distill  — Extract knowledge from Nexus → structured datasets
  2. dataset_curate     — Multi-source dataset curation with quality scoring
  3. research_pipeline  — Automated research with source synthesis
  4. metrics_extract    — Extract metrics from test runs, benchmarks, system data
  5. quality_audit      — Comprehensive codebase quality assessment

Usage::

    python -m engine.workflows.agent_workflows distill --topic "interceptors"
    python -m engine.workflows.agent_workflows curate --output training/datasets/custom/
    python -m engine.workflows.agent_workflows research --question "best MCP patterns"
    python -m engine.workflows.agent_workflows metrics --scope tests
    python -m engine.workflows.agent_workflows audit --scope scenes
"""
from __future__ import annotations

import argparse
import json
import logging
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


# ── Data Structures ──────────────────────────────────────────────

@dataclass
class WorkflowResult:
    """Result from running a workflow."""

    workflow: str
    status: str = "pending"  # "success", "partial", "failed", "pending"
    duration_seconds: float = 0.0
    items_processed: int = 0
    items_output: int = 0
    output_path: Optional[str] = None
    details: Dict[str, Any] = field(default_factory=dict)
    errors: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "workflow": self.workflow,
            "status": self.status,
            "duration_seconds": round(self.duration_seconds, 2),
            "items_processed": self.items_processed,
            "items_output": self.items_output,
            "output_path": self.output_path,
            "details": self.details,
            "errors": self.errors,
        }

    def summary(self) -> str:
        status_icon = {"success": "✅", "partial": "⚠️", "failed": "❌"}.get(self.status, "❓")
        lines = [
            f"{status_icon} {self.workflow}: {self.status}",
            f"   Processed: {self.items_processed}, Output: {self.items_output}",
            f"   Duration: {self.duration_seconds:.1f}s",
        ]
        if self.output_path:
            lines.append(f"   Output: {self.output_path}")
        for error in self.errors[:3]:
            lines.append(f"   ❌ {error}")
        return "\n".join(lines)


# ── Workflow 1: Knowledge Distillation ───────────────────────────

def knowledge_distill(
    topic: str = "",
    categories: Optional[List[str]] = None,
    output_path: str = "training/datasets/custom/distilled.jsonl",
    nexus_url: str = "",
    max_items: int = 500,
) -> WorkflowResult:
    """Extract knowledge from Nexus and distill into training-ready format.

    Pipeline: Nexus search → filter → score relevance → format → deduplicate → write

    Args:
        topic: Focus topic for knowledge extraction (empty = all).
        categories: Filter by these Nexus categories.
        output_path: Where to write the distilled JSONL.
        nexus_url: Nexus API URL.
        max_items: Maximum items to process.

    Returns:
        WorkflowResult with distillation stats.
    """
    if not nexus_url:
        from engine.port_registry import get_service_url
        nexus_url = get_service_url("nexus")
    start = time.time()
    result = WorkflowResult(workflow="knowledge_distill")

    try:
        import requests

        items: List[Dict[str, Any]] = []

        # Fetch Q&A pairs
        try:
            from engine.nexus.client import get_nexus_client
            qa_data = get_nexus_client().find_qa("", limit=max_items)
            items.extend([{"type": "qa", **qa} for qa in qa_data])
        except Exception as e:
            result.errors.append(f"Q&A fetch: {e}")

        # Fetch entries by topic
        if topic:
            try:
                resp = requests.get(
                    f"{nexus_url}/api/search",
                    params={"q": topic, "limit": max_items},
                    timeout=10,
                )
                if resp.ok:
                    search_data = resp.json()
                    entries = search_data if isinstance(search_data, list) else search_data.get("results", [])
                    items.extend([{"type": "entry", **e} for e in entries])
            except Exception as e:
                result.errors.append(f"Search fetch: {e}")

        result.items_processed = len(items)

        # Filter by category
        if categories:
            items = [i for i in items if i.get("category") in categories]

        # Score and sort by relevance
        def _score(item: Dict[str, Any]) -> float:
            score = 0.0
            content = item.get("answer", "") or item.get("content", "")
            score += min(len(content) / 200, 3.0)
            if topic and topic.lower() in content.lower():
                score += 2.0
            if item.get("category") in ("architecture", "api", "system"):
                score += 1.0
            return score

        items.sort(key=_score, reverse=True)
        items = items[:max_items]

        # Format as instruction examples
        formatted: List[Dict[str, str]] = []
        seen: set = set()
        for item in items:
            if item["type"] == "qa":
                q = item.get("question", "").strip()
                a = item.get("answer", "").strip()
                if not q or not a:
                    continue
                key = q.lower()
                if key in seen:
                    continue
                seen.add(key)
                formatted.append({
                    "instruction": "Answer the following question about CosySim.",
                    "input": q,
                    "output": a,
                })
            else:
                title = item.get("title", "").strip()
                content = item.get("content", "").strip()
                if not title or not content or len(content) < 20:
                    continue
                key = title.lower()
                if key in seen:
                    continue
                seen.add(key)
                formatted.append({
                    "instruction": f"Explain the following CosySim concept: {title}",
                    "input": title,
                    "output": content,
                })

        # Write output
        Path(output_path).parent.mkdir(parents=True, exist_ok=True)
        with open(output_path, "w", encoding="utf-8") as f:
            for item in formatted:
                f.write(json.dumps(item, ensure_ascii=False) + "\n")

        result.items_output = len(formatted)
        result.output_path = output_path
        result.status = "success" if formatted else "partial"

    except Exception as e:
        result.status = "failed"
        result.errors.append(str(e))

    result.duration_seconds = time.time() - start
    return result


# ── Workflow 2: Dataset Curation ─────────────────────────────────

def dataset_curate(
    sources: Optional[List[str]] = None,
    output_dir: str = "training/datasets/custom",
    fmt: str = "instruction",
    nexus_url: str = "",
    min_quality: float = 0.5,
) -> WorkflowResult:
    """Multi-source dataset curation with quality scoring.

    Args:
        sources: Which sources to include (default: all available).
        output_dir: Directory for output files.
        fmt: Output format (instruction, chat_ml, sharegpt).
        nexus_url: Nexus API URL.
        min_quality: Minimum quality score (0-1) to include.

    Returns:
        WorkflowResult with curation stats.
    """
    if not nexus_url:
        from engine.port_registry import get_service_url
        nexus_url = get_service_url("nexus")
    start = time.time()
    result = WorkflowResult(workflow="dataset_curate")

    if sources is None:
        sources = ["nexus_qa", "nexus_entries"]

    try:
        from engine.nexus.dataset_curator import DatasetCurator, QualityFilter

        curator = DatasetCurator(nexus_url=nexus_url)
        Path(output_dir).mkdir(parents=True, exist_ok=True)
        total_exported = 0

        if "nexus_qa" in sources:
            qa_path = str(Path(output_dir) / "curated_qa.jsonl")
            try:
                qf = QualityFilter(
                    min_answer_length=int(min_quality * 40),
                    min_question_length=int(min_quality * 10),
                )
                stats = curator.export_qa_dataset(qa_path, fmt=fmt, quality_filter=qf)
                total_exported += stats.exported
                result.details["qa"] = stats.to_dict()
            except Exception as e:
                result.errors.append(f"Q&A curation: {e}")

        if "nexus_entries" in sources:
            entry_path = str(Path(output_dir) / "curated_entries.jsonl")
            try:
                qf = QualityFilter(min_content_length=int(min_quality * 50))
                stats = curator.export_instruction_dataset(entry_path, fmt=fmt, quality_filter=qf)
                total_exported += stats.exported
                result.details["entries"] = stats.to_dict()
            except Exception as e:
                result.errors.append(f"Entry curation: {e}")

        result.items_output = total_exported
        result.output_path = output_dir
        result.status = "success" if total_exported > 0 else "partial"

    except ImportError:
        result.status = "failed"
        result.errors.append("DatasetCurator not available")
    except Exception as e:
        result.status = "failed"
        result.errors.append(str(e))

    result.duration_seconds = time.time() - start
    return result


# ── Workflow 3: Research Pipeline ────────────────────────────────

def research_pipeline(
    question: str,
    depth: str = "shallow",
    output_path: Optional[str] = None,
    nexus_url: str = "",
) -> WorkflowResult:
    """Automated research with source synthesis.

    Pipeline: Nexus Q&A cache → FTS search → synthesize → store results

    Args:
        question: The research question.
        depth: "shallow" (cache + FTS) or "deep" (include NLM).
        output_path: Optional file to write results.
        nexus_url: Nexus API URL.

    Returns:
        WorkflowResult with research findings.
    """
    if not nexus_url:
        from engine.port_registry import get_service_url
        nexus_url = get_service_url("nexus")
    start = time.time()
    result = WorkflowResult(workflow="research_pipeline")

    try:
        import requests

        findings: List[Dict[str, Any]] = []

        # Check Q&A cache
        try:
            resp = requests.get(
                f"{nexus_url}/api/qa/ask",
                params={"question": question},
                timeout=10,
            )
            if resp.ok:
                answer = resp.json()
                if answer.get("answer"):
                    findings.append({
                        "source": "qa_cache",
                        "content": answer["answer"],
                        "confidence": answer.get("confidence", 0.5),
                    })
        except Exception as e:
            result.errors.append(f"Q&A lookup: {e}")

        # FTS search
        try:
            resp = requests.get(
                f"{nexus_url}/api/search",
                params={"q": question, "limit": 10},
                timeout=10,
            )
            if resp.ok:
                results_data = resp.json()
                entries = results_data if isinstance(results_data, list) else results_data.get("results", [])
                for entry in entries:
                    findings.append({
                        "source": "fts_search",
                        "title": entry.get("title", ""),
                        "content": entry.get("content", "")[:500],
                        "confidence": 0.6,
                    })
        except Exception as e:
            result.errors.append(f"FTS search: {e}")

        result.items_processed = len(findings)

        synthesis = {
            "question": question,
            "findings_count": len(findings),
            "sources": [f["source"] for f in findings],
            "top_answer": findings[0]["content"][:500] if findings else "No findings",
            "all_findings": findings,
        }

        # Store result as Q&A
        if findings:
            try:
                requests.post(
                    f"{nexus_url}/api/qa",
                    json={
                        "question": question,
                        "answer": synthesis["top_answer"],
                        "category": "research",
                    },
                    timeout=10,
                )
            except Exception:
                logger.debug("Failed to store research Q&A result in Nexus", exc_info=True)

        if output_path:
            Path(output_path).parent.mkdir(parents=True, exist_ok=True)
            with open(output_path, "w", encoding="utf-8") as f:
                json.dump(synthesis, f, indent=2, ensure_ascii=False)
            result.output_path = output_path

        result.items_output = len(findings)
        result.details = synthesis
        result.status = "success" if findings else "partial"

    except Exception as e:
        result.status = "failed"
        result.errors.append(str(e))

    result.duration_seconds = time.time() - start
    return result


# ── Workflow 4: Metrics Extraction ───────────────────────────────

def metrics_extract(
    scope: str = "all",
    output_path: str = "data/metrics_report.json",
) -> WorkflowResult:
    """Extract metrics from test runs, benchmarks, and system data.

    Args:
        scope: What to measure (tests, benchmarks, codebase, training, all).
        output_path: Where to write the metrics report.

    Returns:
        WorkflowResult with extracted metrics.
    """
    start = time.time()
    result = WorkflowResult(workflow="metrics_extract")
    metrics: Dict[str, Any] = {}

    try:
        if scope in ("tests", "all"):
            test_metrics = _extract_test_metrics()
            metrics["tests"] = test_metrics
            result.items_processed += test_metrics.get("total_tests", 0)

        if scope in ("codebase", "all"):
            code_metrics = _extract_codebase_metrics()
            metrics["codebase"] = code_metrics
            result.items_processed += code_metrics.get("total_files", 0)

        if scope in ("training", "all"):
            training_metrics = _extract_training_metrics()
            metrics["training"] = training_metrics
            result.items_processed += training_metrics.get("total_examples", 0)

        Path(output_path).parent.mkdir(parents=True, exist_ok=True)
        with open(output_path, "w", encoding="utf-8") as f:
            json.dump(metrics, f, indent=2)

        result.output_path = output_path
        result.items_output = len(metrics)
        result.details = metrics
        result.status = "success"

    except Exception as e:
        result.status = "failed"
        result.errors.append(str(e))

    result.duration_seconds = time.time() - start
    return result


def _extract_test_metrics() -> Dict[str, Any]:
    """Extract test suite metrics."""
    test_dir = Path("tests")
    if not test_dir.exists():
        return {"error": "tests/ not found"}

    test_files = list(test_dir.glob("test_*.py"))
    total_tests = 0
    for tf in test_files:
        content = tf.read_text(encoding="utf-8", errors="ignore")
        total_tests += content.count("def test_")

    return {
        "test_files": len(test_files),
        "total_tests": total_tests,
        "avg_tests_per_file": round(total_tests / max(len(test_files), 1), 1),
    }


def _extract_codebase_metrics() -> Dict[str, Any]:
    """Extract codebase size and structure metrics."""
    metrics: Dict[str, Any] = {"total_files": 0, "total_lines": 0, "by_directory": {}}

    for subdir in ["engine", "content", "training"]:
        dir_path = Path(subdir)
        if not dir_path.exists():
            continue
        files = list(dir_path.rglob("*.py"))
        lines = 0
        for f in files:
            try:
                lines += len(f.read_text(encoding="utf-8", errors="ignore").splitlines())
            except Exception:
                logger.debug(f"Failed to read file for metrics: {f}", exc_info=True)
        metrics["by_directory"][subdir] = {"files": len(files), "lines": lines}
        metrics["total_files"] += len(files)
        metrics["total_lines"] += lines

    return metrics


def _extract_training_metrics() -> Dict[str, Any]:
    """Extract training dataset metrics."""
    dataset_dir = Path("training/datasets")
    if not dataset_dir.exists():
        return {"error": "training/datasets/ not found"}

    datasets: Dict[str, int] = {}
    total = 0
    for jsonl in dataset_dir.glob("*.jsonl"):
        count = sum(1 for _ in open(jsonl, encoding="utf-8"))
        datasets[jsonl.stem] = count
        total += count

    return {"datasets": datasets, "total_examples": total}


# ── Workflow 5: Quality Audit ────────────────────────────────────

def quality_audit(
    scope: str = "all",
    output_path: str = "data/audit_report.json",
) -> WorkflowResult:
    """Comprehensive codebase quality assessment.

    Args:
        scope: What to audit (engine, scenes, skills, all).
        output_path: Where to write the audit report.

    Returns:
        WorkflowResult with audit findings.
    """
    start = time.time()
    result = WorkflowResult(workflow="quality_audit")
    audit: Dict[str, Any] = {}

    try:
        dirs_to_audit = []
        if scope in ("engine", "all"):
            dirs_to_audit.append(Path("engine"))
        if scope in ("scenes", "all"):
            dirs_to_audit.append(Path("content/scenes"))
        if scope in ("skills", "all"):
            dirs_to_audit.append(Path("engine/skills"))

        total_functions = 0
        documented = 0
        typed = 0
        files_audited = 0

        for audit_dir in dirs_to_audit:
            if not audit_dir.exists():
                continue
            for py_file in audit_dir.rglob("*.py"):
                if py_file.name.startswith("__"):
                    continue
                files_audited += 1
                try:
                    content = py_file.read_text(encoding="utf-8", errors="ignore")
                    lines = content.splitlines()

                    for i, line in enumerate(lines):
                        stripped = line.strip()
                        if stripped.startswith("def ") or stripped.startswith("async def "):
                            total_functions += 1
                            if i + 1 < len(lines) and '"""' in lines[i + 1]:
                                documented += 1
                            if "->" in stripped:
                                typed += 1
                except Exception:
                    logger.debug(f"Failed to audit file: {py_file}", exc_info=True)

        audit["functions"] = {
            "total": total_functions,
            "documented": documented,
            "typed": typed,
            "docstring_coverage": round(100 * documented / max(total_functions, 1), 1),
            "type_hint_coverage": round(100 * typed / max(total_functions, 1), 1),
        }
        audit["files_audited"] = files_audited

        # Check for anti-patterns
        antipatterns: List[str] = []
        for audit_dir in dirs_to_audit:
            if not audit_dir.exists():
                continue
            for py_file in audit_dir.rglob("*.py"):
                try:
                    content = py_file.read_text(encoding="utf-8", errors="ignore")
                    rel_path = str(py_file)
                    if "print(" in content and "logger" not in content:
                        antipatterns.append(f"{rel_path}: uses print() without logger")
                    if "from ." in content:
                        antipatterns.append(f"{rel_path}: uses relative imports")
                    if "except:" in content and "except Exception" not in content:
                        antipatterns.append(f"{rel_path}: bare except clause")
                except Exception:
                    logger.debug(f"Failed to scan file for antipatterns: {py_file}", exc_info=True)
        audit["antipatterns"] = antipatterns[:20]
        audit["antipattern_count"] = len(antipatterns)

        Path(output_path).parent.mkdir(parents=True, exist_ok=True)
        with open(output_path, "w", encoding="utf-8") as f:
            json.dump(audit, f, indent=2)

        result.items_processed = files_audited
        result.items_output = total_functions
        result.output_path = output_path
        result.details = audit
        result.status = "success"

    except Exception as e:
        result.status = "failed"
        result.errors.append(str(e))

    result.duration_seconds = time.time() - start
    return result


# ── Workflow Registry ────────────────────────────────────────────

WORKFLOWS = {
    "distill": knowledge_distill,
    "curate": dataset_curate,
    "research": research_pipeline,
    "metrics": metrics_extract,
    "audit": quality_audit,
}


def run_all(
    nexus_url: str = "",
    output_base: str = "data/workflow_results",
) -> List[WorkflowResult]:
    """Run all workflows and collect results."""
    if not nexus_url:
        from engine.port_registry import get_service_url
        nexus_url = get_service_url("nexus")
    results = []
    Path(output_base).mkdir(parents=True, exist_ok=True)

    results.append(knowledge_distill(
        output_path=f"{output_base}/distilled.jsonl",
        nexus_url=nexus_url,
    ))
    results.append(dataset_curate(
        output_dir=f"{output_base}/curated",
        nexus_url=nexus_url,
    ))
    results.append(research_pipeline(
        question="What are the key architectural patterns in CosySim?",
        output_path=f"{output_base}/research.json",
        nexus_url=nexus_url,
    ))
    results.append(metrics_extract(
        output_path=f"{output_base}/metrics.json",
    ))
    results.append(quality_audit(
        output_path=f"{output_base}/audit.json",
    ))

    return results


# ── CLI ──────────────────────────────────────────────────────────

def main() -> None:
    parser = argparse.ArgumentParser(description="CosySim Agent Workflows")
    sub = parser.add_subparsers(dest="workflow", help="Workflow to run")

    p_distill = sub.add_parser("distill", help="Knowledge distillation from Nexus")
    p_distill.add_argument("--topic", default="", help="Focus topic")
    p_distill.add_argument("--output", default="training/datasets/custom/distilled.jsonl")
    p_distill.add_argument("--nexus-url", default="")

    p_curate = sub.add_parser("curate", help="Dataset curation")
    p_curate.add_argument("--output", default="training/datasets/custom")
    p_curate.add_argument("--format", default="instruction", choices=["instruction", "chat_ml", "sharegpt"])
    p_curate.add_argument("--nexus-url", default="")

    p_research = sub.add_parser("research", help="Research pipeline")
    p_research.add_argument("--question", required=True, help="Research question")
    p_research.add_argument("--output", default=None)
    p_research.add_argument("--nexus-url", default="")

    p_metrics = sub.add_parser("metrics", help="Metrics extraction")
    p_metrics.add_argument("--scope", default="all", choices=["tests", "codebase", "training", "all"])
    p_metrics.add_argument("--output", default="data/metrics_report.json")

    p_audit = sub.add_parser("audit", help="Quality audit")
    p_audit.add_argument("--scope", default="all", choices=["engine", "scenes", "skills", "all"])
    p_audit.add_argument("--output", default="data/audit_report.json")

    sub.add_parser("all", help="Run all workflows")

    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(message)s")

    if args.workflow == "distill":
        r = knowledge_distill(topic=args.topic, output_path=args.output, nexus_url=args.nexus_url)
        print(r.summary())
    elif args.workflow == "curate":
        r = dataset_curate(output_dir=args.output, fmt=args.format, nexus_url=args.nexus_url)
        print(r.summary())
    elif args.workflow == "research":
        r = research_pipeline(question=args.question, output_path=args.output, nexus_url=args.nexus_url)
        print(r.summary())
    elif args.workflow == "metrics":
        r = metrics_extract(scope=args.scope, output_path=args.output)
        print(r.summary())
    elif args.workflow == "audit":
        r = quality_audit(scope=args.scope, output_path=args.output)
        print(r.summary())
    elif args.workflow == "all":
        results = run_all()
        for r in results:
            print(r.summary())
            print()
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
