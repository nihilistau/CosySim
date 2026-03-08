"""ARGUS Explorer — Automated API surface testing and discovery system.

Systematic exploration of Google API endpoints discovered via ARGUS.
Tests rpcids with different parameter combinations, validates responses,
maps rpcids to service methods, and stores all findings in Nexus.

Architecture:
    Registry (YAML) → Explorer → CDP/Network → Validator → Nexus

Usage::

    # Full exploration run (automated)
    python -m scripts.argus.explorer --target nlm --mode auto

    # Test a single operation
    python -m scripts.argus.explorer --op list_notebooks --tier pro

    # Parameter sweep on an operation
    python -m scripts.argus.explorer --op create_note --sweep tier_marker

    # Discover unmapped rpcids via CDP traffic monitoring
    python -m scripts.argus.explorer --mode discover --duration 60

    # Export full API surface report
    python -m scripts.argus.explorer --report

    # Store API surface catalog in Nexus
    python -m scripts.argus.explorer --store-nexus
"""
from __future__ import annotations

import argparse
import asyncio
import json
import logging
import sys
import time
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple

import yaml

logger = logging.getLogger(__name__)

# ─── Data paths ──────────────────────────────────────────────────────────────

_PROJECT_ROOT = Path(__file__).resolve().parents[2]
_REGISTRY_YAML = _PROJECT_ROOT / "config" / "nlm_rpcids.yaml"
_RESULTS_DIR = _PROJECT_ROOT / "data" / "argus" / "explorer"
_RESULTS_DIR.mkdir(parents=True, exist_ok=True)

EXPLORATION_LOG = _RESULTS_DIR / "exploration_log.jsonl"
COVERAGE_REPORT = _RESULTS_DIR / "coverage_report.json"
PARAMETER_RESULTS = _RESULTS_DIR / "parameter_results.json"
DISCOVERY_LOG = _RESULTS_DIR / "discovery_log.jsonl"


# ─── Data classes ────────────────────────────────────────────────────────────

@dataclass
class ExplorationResult:
    """Result of testing a single rpcid/operation."""
    operation: str
    rpcid: str
    tier: str
    status_code: int
    success: bool
    response_size: int
    response_preview: str
    error: Optional[str]
    duration_ms: float
    parameters: Dict[str, Any]
    timestamp: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class ParameterSweepResult:
    """Result of testing an operation with different parameter values."""
    operation: str
    parameter: str
    results: List[Dict[str, Any]] = field(default_factory=list)
    best_value: Optional[Any] = None
    summary: str = ""


@dataclass
class DiscoveryEvent:
    """A newly discovered rpcid from live traffic monitoring."""
    rpcid: str
    source: str
    url: str
    method: str
    context: str
    is_new: bool
    timestamp: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())


@dataclass
class CoverageReport:
    """Overall API surface coverage statistics."""
    total_operations: int
    tested_operations: int
    confirmed_operations: int
    heap_only_operations: int
    unmapped_rpcids: int
    gemini_rpcids: int
    aistudio_methods: int
    colab_methods: int
    quota_events: int
    coverage_pct: float
    last_run: str
    per_category: Dict[str, Dict[str, int]] = field(default_factory=dict)
    parameter_coverage: Dict[str, int] = field(default_factory=dict)


# ─── Registry Loader ─────────────────────────────────────────────────────────

class RegistryLoader:
    """Loads and queries the YAML registry for exploration targets."""

    def __init__(self, yaml_path: Optional[Path] = None) -> None:
        path = yaml_path or _REGISTRY_YAML
        with open(path, encoding="utf-8") as f:
            self._data = yaml.safe_load(f)

    @property
    def operations(self) -> Dict[str, Dict[str, Any]]:
        """NLM batchexecute operations (dict entries only)."""
        ops = self._data.get("operations", {})
        return {k: v for k, v in ops.items() if isinstance(v, dict)}

    @property
    def parameters(self) -> Dict[str, Dict[str, Any]]:
        return self._data.get("parameters", {})

    @property
    def gemini_rpcids(self) -> Dict[str, Dict[str, Any]]:
        return self._data.get("gemini", {}).get("rpcids", {})

    @property
    def aistudio_methods(self) -> Dict[str, Dict[str, Any]]:
        return self._data.get("aistudio", {}).get("methods", {})

    @property
    def colab_methods(self) -> Dict[str, Dict[str, Any]]:
        return self._data.get("colab", {}).get("methods", {})

    @property
    def quota_events(self) -> Dict[str, Dict[str, Any]]:
        return self._data.get("quota_events", {})

    @property
    def nlm_identity(self) -> Dict[str, Any]:
        return self._data.get("nlm_identity", {})

    def get_testable_operations(self) -> Dict[str, Dict[str, Any]]:
        """Operations that have a known rpcid and can be tested."""
        return {k: v for k, v in self.operations.items()
                if v.get("rpcid") is not None}

    def get_heap_only_operations(self) -> Dict[str, Dict[str, Any]]:
        """Operations discovered via heap but missing rpcid — exploration targets."""
        return {k: v for k, v in self.operations.items()
                if v.get("source") == "argus_heap" and v.get("rpcid") is None}

    def get_operations_by_category(self, category: str) -> Dict[str, Dict[str, Any]]:
        return {k: v for k, v in self.operations.items()
                if v.get("category") == category}

    def get_parameter_options(self, param_name: str) -> Dict[str, Any]:
        """Get all option values for a parameter."""
        param = self.parameters.get(param_name, {})
        return param.get("options", {})

    def build_coverage_report(self) -> CoverageReport:
        """Build a coverage statistics report."""
        ops = self.operations
        testable = self.get_testable_operations()
        heap_only = self.get_heap_only_operations()

        per_cat: Dict[str, Dict[str, int]] = {}
        for name, op in ops.items():
            cat = op.get("category", "unknown")
            if cat not in per_cat:
                per_cat[cat] = {"total": 0, "has_rpcid": 0, "heap_only": 0}
            per_cat[cat]["total"] += 1
            if op.get("rpcid"):
                per_cat[cat]["has_rpcid"] += 1
            if op.get("source") == "argus_heap":
                per_cat[cat]["heap_only"] += 1

        param_cov: Dict[str, int] = {}
        for name, op in ops.items():
            for p in op.get("configurable", []):
                clean = p.split(" ")[0]
                param_cov[clean] = param_cov.get(clean, 0) + 1

        total = len(ops)
        tested = len(testable)
        coverage = (tested / total * 100) if total > 0 else 0.0

        return CoverageReport(
            total_operations=total,
            tested_operations=tested,
            confirmed_operations=sum(1 for v in testable.values() if v.get("confirmed")),
            heap_only_operations=len(heap_only),
            unmapped_rpcids=len(heap_only),
            gemini_rpcids=len(self.gemini_rpcids),
            aistudio_methods=len(self.aistudio_methods),
            colab_methods=len(self.colab_methods),
            quota_events=len(self.quota_events),
            coverage_pct=round(coverage, 1),
            last_run=datetime.now(timezone.utc).isoformat(),
            per_category=per_cat,
            parameter_coverage=param_cov,
        )


# ─── RPC Tester ──────────────────────────────────────────────────────────────

class RpcTester:
    """Tests NLM rpcids via batchexecute with configurable parameters.

    Uses NLMDirectClient for actual RPC calls, with CDP token refresh.
    """

    def __init__(self) -> None:
        self._client = None
        self._loader = RegistryLoader()

    def _ensure_client(self) -> Any:
        """Lazy-init the NLM client."""
        if self._client is None:
            try:
                from engine.integrations.nlm_direct_client import NLMDirectClient
                self._client = NLMDirectClient()
                logger.info("RpcTester: NLMDirectClient initialized")
            except Exception as exc:
                logger.error("RpcTester: failed to init client: %s", exc)
                raise
        return self._client

    def test_operation(
        self,
        operation: str,
        tier: str = "primary",
        notebook_id: Optional[str] = None,
        extra_params: Optional[Dict[str, Any]] = None,
    ) -> ExplorationResult:
        """Test a single operation by calling its rpcid.

        Args:
            operation: Operation name from the YAML registry.
            tier: "primary" or "fallback" rpcid to test.
            notebook_id: Required for operations with requires_notebook=true.
            extra_params: Override parameter values for this call.

        Returns:
            ExplorationResult with status, timing, and response info.
        """
        op = self._loader.operations.get(operation)
        if not op:
            return ExplorationResult(
                operation=operation, rpcid="?", tier=tier,
                status_code=0, success=False, response_size=0,
                response_preview="", error=f"Unknown operation: {operation}",
                duration_ms=0, parameters={},
            )

        rpcid_key = "rpcid" if tier == "primary" else "fallback_rpcid"
        rpcid = op.get(rpcid_key)
        if not rpcid:
            return ExplorationResult(
                operation=operation, rpcid="null", tier=tier,
                status_code=0, success=False, response_size=0,
                response_preview="", error=f"No {tier} rpcid for {operation}",
                duration_ms=0, parameters={},
            )

        if op.get("requires_notebook") and not notebook_id:
            return ExplorationResult(
                operation=operation, rpcid=rpcid, tier=tier,
                status_code=0, success=False, response_size=0,
                response_preview="", error="requires_notebook but no notebook_id provided",
                duration_ms=0, parameters=extra_params or {},
            )

        client = self._ensure_client()
        params = extra_params or {}
        start = time.monotonic()

        try:
            payload = self._build_test_payload(op, notebook_id, params)
            result = client._rpc_call(rpcid, payload, notebook_id=notebook_id)
            elapsed = (time.monotonic() - start) * 1000

            result_str = str(result)
            return ExplorationResult(
                operation=operation, rpcid=rpcid, tier=tier,
                status_code=200, success=True,
                response_size=len(result_str),
                response_preview=result_str[:500],
                error=None, duration_ms=round(elapsed, 1),
                parameters=params,
            )
        except Exception as exc:
            elapsed = (time.monotonic() - start) * 1000
            status = 0
            err_str = str(exc)
            if "400" in err_str:
                status = 400
            elif "401" in err_str or "403" in err_str:
                status = 403
            elif "429" in err_str:
                status = 429

            return ExplorationResult(
                operation=operation, rpcid=rpcid, tier=tier,
                status_code=status, success=False, response_size=0,
                response_preview="", error=err_str[:500],
                duration_ms=round(elapsed, 1), parameters=params,
            )

    def _build_test_payload(
        self,
        op: Dict[str, Any],
        notebook_id: Optional[str],
        params: Dict[str, Any],
    ) -> Any:
        """Build a minimal test payload for an operation."""
        payload_template = op.get("payload", [])
        if isinstance(payload_template, str):
            return []

        payload = []
        for item in payload_template:
            if isinstance(item, str) and item.startswith("$"):
                param_name = item[1:]
                if param_name == "notebook_id" and notebook_id:
                    payload.append(notebook_id)
                elif param_name == "tier_marker":
                    payload.append(params.get("tier_marker", [2]))
                elif param_name == "source_config":
                    payload.append([1, None, None, None, None, None, None, None, None, None, [1]])
                elif param_name == "write_config":
                    payload.append([2, None, None, [1, None, None, None, None, None, None, None, None, None, [1]], [[2, 1]]])
                elif param_name in params:
                    payload.append(params[param_name])
                else:
                    payload.append(None)
            else:
                payload.append(item)
        return payload

    def sweep_parameter(
        self,
        operation: str,
        parameter: str,
        notebook_id: Optional[str] = None,
    ) -> ParameterSweepResult:
        """Test an operation with all options of a parameter.

        Returns:
            ParameterSweepResult with per-value success/failure data.
        """
        options = self._loader.get_parameter_options(parameter)
        if not options:
            return ParameterSweepResult(
                operation=operation, parameter=parameter,
                summary=f"No options found for parameter '{parameter}'",
            )

        results = []
        for option_name, option_value in options.items():
            logger.info("Sweep %s.%s = %s (%s)", operation, parameter, option_name, option_value)
            result = self.test_operation(
                operation, extra_params={parameter: option_value},
                notebook_id=notebook_id,
            )
            results.append({
                "option": option_name,
                "value": option_value,
                "success": result.success,
                "status_code": result.status_code,
                "response_size": result.response_size,
                "duration_ms": result.duration_ms,
                "error": result.error,
            })
            time.sleep(1)

        best = None
        for r in results:
            if r["success"]:
                if best is None or r["response_size"] > best["response_size"]:
                    best = r

        return ParameterSweepResult(
            operation=operation,
            parameter=parameter,
            results=results,
            best_value=best["value"] if best else None,
            summary=f"{sum(1 for r in results if r['success'])}/{len(results)} succeeded",
        )


# ─── CDP Traffic Discovery ──────────────────────────────────────────────────

class CdpDiscovery:
    """Monitors live Chrome traffic via CDP to discover new rpcids."""

    CDP_URL = "http://localhost:9222"

    def __init__(self) -> None:
        self._loader = RegistryLoader()
        self._known_rpcids: Set[str] = set()
        for op in self._loader.operations.values():
            if isinstance(op, dict) and op.get("rpcid"):
                self._known_rpcids.add(op["rpcid"])
                if op.get("fallback_rpcid"):
                    self._known_rpcids.add(op["fallback_rpcid"])

    async def monitor(self, duration_seconds: int = 60) -> List[DiscoveryEvent]:
        """Monitor CDP traffic for batchexecute calls and extract rpcids.

        Args:
            duration_seconds: How long to monitor in seconds.

        Returns:
            List of DiscoveryEvent for each rpcid seen.
        """
        import re

        try:
            import websockets
        except ImportError:
            logger.error("websockets package required: pip install websockets")
            return []

        events: List[DiscoveryEvent] = []
        tabs = await self._get_tabs()

        nlm_tabs = [t for t in tabs if "notebooklm" in t.get("url", "").lower()]
        if not nlm_tabs:
            logger.warning("No NotebookLM tabs found in Chrome")
            return events

        rpcid_pattern = re.compile(r'\[\["([A-Za-z][A-Za-z0-9]{3,7})"')

        for tab in nlm_tabs:
            ws_url = tab.get("webSocketDebuggerUrl")
            if not ws_url:
                continue

            try:
                async with websockets.connect(ws_url, max_size=10 * 1024 * 1024) as ws:
                    await ws.send(json.dumps({
                        "id": 1, "method": "Network.enable", "params": {}
                    }))
                    await ws.recv()

                    end_time = time.monotonic() + duration_seconds
                    while time.monotonic() < end_time:
                        try:
                            msg = await asyncio.wait_for(ws.recv(), timeout=5)
                            data = json.loads(msg)

                            if data.get("method") == "Network.requestWillBeSent":
                                req = data.get("params", {}).get("request", {})
                                url = req.get("url", "")
                                post = req.get("postData", "")

                                if "batchexecute" in url and post:
                                    matches = rpcid_pattern.findall(post)
                                    for rpcid in matches:
                                        is_new = rpcid not in self._known_rpcids
                                        event = DiscoveryEvent(
                                            rpcid=rpcid,
                                            source="cdp_live",
                                            url=url,
                                            method="POST",
                                            context=post[:200],
                                            is_new=is_new,
                                        )
                                        events.append(event)
                                        if is_new:
                                            logger.warning(
                                                "NEW rpcid discovered: %s in %s",
                                                rpcid, url,
                                            )
                                            self._known_rpcids.add(rpcid)
                        except asyncio.TimeoutError:
                            continue
            except Exception as exc:
                logger.error("CDP monitor error on tab %s: %s", tab.get("title", "?"), exc)

        return events

    async def _get_tabs(self) -> List[Dict[str, Any]]:
        """Get Chrome debug tab list."""
        import urllib.request
        try:
            resp = urllib.request.urlopen(f"{self.CDP_URL}/json", timeout=5)
            return json.loads(resp.read())
        except Exception as exc:
            logger.error("Failed to get CDP tabs: %s", exc)
            return []


# ─── Nexus Catalog Store ─────────────────────────────────────────────────────

class NexusCatalogStore:
    """Stores the complete API surface catalog in Nexus."""

    def __init__(self) -> None:
        self._loader = RegistryLoader()
        self._sink = None
        try:
            from scripts.argus.nexus_sink import ArgusNexusSink
            self._sink = ArgusNexusSink()
        except Exception:
            logger.warning("NexusCatalogStore: ArgusNexusSink unavailable")

    def store_full_catalog(self) -> Dict[str, int]:
        """Store the complete API surface catalog in Nexus.

        Returns:
            Dict with counts of entries stored per section.
        """
        counts: Dict[str, int] = {}

        counts["nlm_operations"] = self._store_nlm_catalog()
        counts["gemini_rpcids"] = self._store_gemini_catalog()
        counts["aistudio_methods"] = self._store_aistudio_catalog()
        counts["colab_methods"] = self._store_colab_catalog()
        counts["nlm_identity"] = self._store_nlm_identity()
        counts["coverage_report"] = self._store_coverage_report()

        total = sum(counts.values())
        logger.info("NexusCatalogStore: stored %d total entries", total)
        return counts

    def _store_nlm_catalog(self) -> int:
        """Store NLM operations catalog as a single comprehensive entry."""
        ops = self._loader.operations
        lines = ["# NotebookLM batchexecute API Surface", ""]
        lines.append(f"Total operations: {len(ops)}")
        lines.append(f"Service: LabsTailwindOrchestrationService")
        lines.append(f"Protocol: batchexecute POST to /_/LabsTailwindUi/data/batchexecute")
        lines.append("")

        by_cat: Dict[str, List[str]] = {}
        for name, op in ops.items():
            cat = op.get("category", "unknown")
            if cat not in by_cat:
                by_cat[cat] = []
            rpcid = op.get("rpcid", "UNMAPPED")
            sm = op.get("service_method", "")
            desc = op.get("description", "")
            entry = f"- **{name}** (`{rpcid}`) — {desc}"
            if sm:
                entry += f"\n  Service method: `{sm}`"
            by_cat[cat].append(entry)

        for cat, entries in sorted(by_cat.items()):
            lines.append(f"\n## {cat.title()} ({len(entries)} operations)")
            lines.extend(entries)

        content = "\n".join(lines)
        return self._store("ARGUS: NLM API Surface Catalog", content) or 0

    def _store_gemini_catalog(self) -> int:
        rpcids = self._loader.gemini_rpcids
        if not rpcids:
            return 0
        lines = ["# Gemini batchexecute API Surface", ""]
        lines.append(f"Total rpcids: {len(rpcids)}")
        lines.append(f"Service: BardChatUi")
        lines.append(f"Protocol: batchexecute POST to /_/BardChatUi/data/batchexecute")
        lines.append("")
        for rpcid, info in sorted(rpcids.items()):
            desc = info.get("description", "Unknown")
            cat = info.get("category", "?")
            lines.append(f"- **{rpcid}** [{cat}] — {desc}")
        content = "\n".join(lines)
        return self._store("ARGUS: Gemini API Surface Catalog", content) or 0

    def _store_aistudio_catalog(self) -> int:
        methods = self._loader.aistudio_methods
        if not methods:
            return 0
        lines = ["# AI Studio gRPC API Surface", ""]
        meta = self._loader._data.get("aistudio", {}).get("meta", {})
        lines.append(f"Total methods: {len(methods)}")
        lines.append(f"Service: {meta.get('service_name', 'MakerSuiteService')}")
        lines.append(f"Protocol: gRPC-Web to {meta.get('grpc_host', '?')}")
        lines.append("")

        by_cat: Dict[str, List[str]] = {}
        for method, info in methods.items():
            cat = info.get("category", "unknown")
            if cat not in by_cat:
                by_cat[cat] = []
            streaming = " [streaming]" if info.get("streaming") else ""
            by_cat[cat].append(f"- **{method}**{streaming} — {info.get('description', '')}")

        for cat, entries in sorted(by_cat.items()):
            lines.append(f"\n## {cat.title()}")
            lines.extend(entries)

        content = "\n".join(lines)
        return self._store("ARGUS: AI Studio API Surface Catalog", content) or 0

    def _store_colab_catalog(self) -> int:
        methods = self._loader.colab_methods
        if not methods:
            return 0
        lines = ["# Google Colab gRPC API Surface", ""]
        lines.append(f"Total methods: {len(methods)}")
        lines.append("")
        for method, info in sorted(methods.items()):
            cat = info.get("category", "?")
            lines.append(f"- **{method}** [{cat}] — {info.get('description', '')}")
        content = "\n".join(lines)
        return self._store("ARGUS: Colab API Surface Catalog", content) or 0

    def _store_nlm_identity(self) -> int:
        identity = self._loader.nlm_identity
        if not identity:
            return 0
        content = json.dumps(identity, indent=2)
        return self._store("ARGUS: NLM Service Identity Metadata", content) or 0

    def _store_coverage_report(self) -> int:
        report = self._loader.build_coverage_report()
        content = json.dumps(asdict(report), indent=2)
        return self._store("ARGUS: API Surface Coverage Report", content) or 0

    def _store(self, title: str, content: str) -> Optional[int]:
        if not self._sink:
            logger.info("NexusCatalogStore: would store '%s' (%d chars)", title, len(content))
            return 1
        result = self._sink.store(title, content)
        return 1 if result else 0

    def store_exploration_results(self, results: List[ExplorationResult]) -> int:
        """Store exploration test results in Nexus."""
        if not results:
            return 0

        lines = ["# ARGUS Explorer Results", ""]
        lines.append(f"Run: {datetime.now(timezone.utc).isoformat()}")
        lines.append(f"Tests: {len(results)}")

        success = sum(1 for r in results if r.success)
        lines.append(f"Success: {success}/{len(results)}")
        lines.append("")

        for r in results:
            status = "OK" if r.success else f"FAIL({r.status_code})"
            lines.append(f"- {r.operation} [{r.rpcid}] {r.tier}: {status} ({r.duration_ms}ms)")
            if r.error:
                lines.append(f"  Error: {r.error[:200]}")

        content = "\n".join(lines)
        return self._store("ARGUS: Explorer Run Results", content) or 0


# ─── Result Persistence ──────────────────────────────────────────────────────

def append_result(result: ExplorationResult) -> None:
    """Append an exploration result to the JSONL log."""
    with open(EXPLORATION_LOG, "a", encoding="utf-8") as f:
        f.write(json.dumps(result.to_dict()) + "\n")


def append_discovery(event: DiscoveryEvent) -> None:
    """Append a discovery event to the JSONL log."""
    with open(DISCOVERY_LOG, "a", encoding="utf-8") as f:
        f.write(json.dumps(asdict(event)) + "\n")


def save_coverage_report(report: CoverageReport) -> None:
    """Save coverage report to JSON."""
    with open(COVERAGE_REPORT, "w", encoding="utf-8") as f:
        json.dump(asdict(report), f, indent=2)


# ─── Auto Exploration Mode ──────────────────────────────────────────────────

class AutoExplorer:
    """Automated exploration: test all operations, sweep parameters, store results."""

    def __init__(self) -> None:
        self._loader = RegistryLoader()
        self._tester = RpcTester()
        self._catalog = NexusCatalogStore()
        self._results: List[ExplorationResult] = []

    def run_full_exploration(
        self,
        notebook_id: Optional[str] = None,
        categories: Optional[List[str]] = None,
        skip_notebook_ops: bool = False,
    ) -> CoverageReport:
        """Run automated exploration of all testable operations.

        Args:
            notebook_id: Notebook ID for operations that require one.
            categories: Only test these categories (None = all).
            skip_notebook_ops: Skip operations requiring a notebook ID.

        Returns:
            CoverageReport with results.
        """
        ops = self._loader.get_testable_operations()
        if categories:
            ops = {k: v for k, v in ops.items() if v.get("category") in categories}

        logger.info("AutoExplorer: %d testable operations", len(ops))

        for name, op in sorted(ops.items()):
            if skip_notebook_ops and op.get("requires_notebook"):
                logger.info("Skipping %s (requires notebook)", name)
                continue

            nb = notebook_id if op.get("requires_notebook") else None
            if op.get("requires_notebook") and not nb:
                logger.info("Skipping %s (requires notebook, none provided)", name)
                continue

            logger.info("Testing %s (%s)...", name, op.get("rpcid", "?"))
            result = self._tester.test_operation(name, notebook_id=nb)
            self._results.append(result)
            append_result(result)

            if op.get("fallback_rpcid"):
                logger.info("Testing %s fallback (%s)...", name, op["fallback_rpcid"])
                fb_result = self._tester.test_operation(name, tier="fallback", notebook_id=nb)
                self._results.append(fb_result)
                append_result(fb_result)

            time.sleep(0.5)

        report = self._loader.build_coverage_report()
        save_coverage_report(report)
        self._catalog.store_exploration_results(self._results)

        logger.info(
            "AutoExplorer: %d/%d succeeded, coverage %.1f%%",
            sum(1 for r in self._results if r.success),
            len(self._results),
            report.coverage_pct,
        )
        return report

    def run_parameter_sweeps(
        self,
        operations: Optional[List[str]] = None,
        parameters: Optional[List[str]] = None,
        notebook_id: Optional[str] = None,
    ) -> List[ParameterSweepResult]:
        """Sweep parameter values across operations.

        Args:
            operations: Which operations to sweep (None = all with configurable params).
            parameters: Which parameters to sweep (None = all).
            notebook_id: For operations requiring a notebook.

        Returns:
            List of ParameterSweepResult.
        """
        ops = self._loader.operations
        if operations:
            ops = {k: v for k, v in ops.items() if k in operations}

        sweeps: List[ParameterSweepResult] = []
        for name, op in ops.items():
            configurable = op.get("configurable", [])
            if not configurable:
                continue

            for param_spec in configurable:
                param_name = param_spec.split(" ")[0]
                if parameters and param_name not in parameters:
                    continue
                if param_name not in self._loader.parameters:
                    continue

                nb = notebook_id if op.get("requires_notebook") else None
                if op.get("requires_notebook") and not nb:
                    continue

                logger.info("Sweeping %s.%s...", name, param_name)
                result = self._tester.sweep_parameter(name, param_name, nb)
                sweeps.append(result)

        if sweeps:
            sweep_data = [asdict(s) for s in sweeps]
            with open(PARAMETER_RESULTS, "w", encoding="utf-8") as f:
                json.dump(sweep_data, f, indent=2)

        return sweeps


# ─── CLI Entry Point ─────────────────────────────────────────────────────────

def main() -> None:
    """CLI entry point for ARGUS Explorer."""
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")

    parser = argparse.ArgumentParser(
        description="ARGUS Explorer — automated API surface testing and discovery",
    )
    parser.add_argument("--mode", choices=["auto", "discover", "sweep"],
                        default="auto", help="Exploration mode")
    parser.add_argument("--op", type=str, help="Test a specific operation by name")
    parser.add_argument("--tier", choices=["primary", "fallback"], default="primary")
    parser.add_argument("--sweep", type=str, help="Sweep a specific parameter")
    parser.add_argument("--notebook", type=str, help="Notebook ID for operations that need one")
    parser.add_argument("--category", type=str, help="Only test this category")
    parser.add_argument("--duration", type=int, default=60,
                        help="Discovery monitoring duration in seconds")
    parser.add_argument("--report", action="store_true",
                        help="Print coverage report and exit")
    parser.add_argument("--store-nexus", action="store_true",
                        help="Store full API catalog in Nexus")
    parser.add_argument("--skip-notebook-ops", action="store_true",
                        help="Skip operations requiring a notebook ID")

    args = parser.parse_args()

    if args.report:
        loader = RegistryLoader()
        report = loader.build_coverage_report()
        print(json.dumps(asdict(report), indent=2))
        return

    if args.store_nexus:
        store = NexusCatalogStore()
        counts = store.store_full_catalog()
        print(f"Stored in Nexus: {json.dumps(counts, indent=2)}")
        return

    if args.op:
        if args.sweep:
            tester = RpcTester()
            result = tester.sweep_parameter(args.op, args.sweep, args.notebook)
            print(json.dumps(asdict(result), indent=2))
        else:
            tester = RpcTester()
            result = tester.test_operation(args.op, tier=args.tier, notebook_id=args.notebook)
            print(json.dumps(result.to_dict(), indent=2))
            append_result(result)
        return

    if args.mode == "discover":
        discovery = CdpDiscovery()
        print(f"Monitoring CDP traffic for {args.duration}s...")
        events = asyncio.run(discovery.monitor(args.duration))
        new_events = [e for e in events if e.is_new]
        print(f"Captured {len(events)} rpcid events, {len(new_events)} NEW")
        for e in events:
            append_discovery(e)
            if e.is_new:
                print(f"  NEW: {e.rpcid} from {e.source}")
        return

    if args.mode == "sweep":
        explorer = AutoExplorer()
        categories = [args.category] if args.category else None
        ops = None
        if args.op:
            ops = [args.op]
        params = [args.sweep] if args.sweep else None
        results = explorer.run_parameter_sweeps(ops, params, args.notebook)
        print(f"Completed {len(results)} parameter sweeps")
        for r in results:
            print(f"  {r.operation}.{r.parameter}: {r.summary}")
        return

    # Default: auto exploration
    explorer = AutoExplorer()
    categories = [args.category] if args.category else None
    report = explorer.run_full_exploration(
        notebook_id=args.notebook,
        categories=categories,
        skip_notebook_ops=args.skip_notebook_ops,
    )
    print(f"\nCoverage: {report.coverage_pct}% ({report.tested_operations}/{report.total_operations})")
    print(f"Gemini: {report.gemini_rpcids} rpcids")
    print(f"AI Studio: {report.aistudio_methods} methods")
    print(f"Colab: {report.colab_methods} methods")
    print(f"Heap-only (unmapped): {report.heap_only_operations}")


if __name__ == "__main__":
    main()
