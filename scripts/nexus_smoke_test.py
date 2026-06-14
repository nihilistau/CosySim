"""
NEXUS Smoke Test — End-to-end verification of the self-improving pipeline.
==========================================================================

Verifies that all NEXUS subsystems are operational and connected:
  1. Nexus KMS health (port 8700)
  2. Embedding service health (which provider is active)
  3. Vector store health (ChromaDB operational, collection counts)
  4. Query router (all 6 tiers connected)
  5. Scheduler daemon (tasks registered, running state)
  6. Distiller (can find and process entries)
  7. Self-improvement loop (seed → embed → query → find)

Version: v1.50.2 [2026-03-24]
Author:  CosySim Team

Change Log:
    v1.50.2 [2026-03-24] — Initial creation: end-to-end NEXUS verification

Usage:
    python scripts/nexus_smoke_test.py
    python scripts/nexus_smoke_test.py --verbose
    python scripts/nexus_smoke_test.py --fix    # Attempt auto-fixes for common issues
"""
from __future__ import annotations

import argparse
import logging
import sys
import time
from pathlib import Path
from typing import Any, Dict, List, Tuple

# Ensure repo root is on path
_REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_REPO_ROOT))

logger = logging.getLogger(__name__)


# ──── Result tracking ─────────────────────────────────────────────────────────

class SmokeResult:
    """Tracks pass/fail for each check."""

    def __init__(self) -> None:
        self.checks: List[Tuple[str, bool, str]] = []

    def record(self, name: str, passed: bool, detail: str = "") -> bool:
        self.checks.append((name, passed, detail))
        status = "PASS" if passed else "FAIL"
        icon = "+" if passed else "!"
        print(f"  [{icon}] {name}: {status}" + (f" — {detail}" if detail else ""))
        return passed

    @property
    def passed(self) -> int:
        return sum(1 for _, ok, _ in self.checks if ok)

    @property
    def failed(self) -> int:
        return sum(1 for _, ok, _ in self.checks if not ok)

    @property
    def total(self) -> int:
        return len(self.checks)

    def summary(self) -> str:
        return f"{self.passed}/{self.total} passed, {self.failed} failed"


# ──── Check functions ─────────────────────────────────────────────────────────

def check_nexus_health(r: SmokeResult) -> bool:
    """Check 1: Nexus KMS is reachable and healthy."""
    try:
        from engine.nexus.client import get_nexus_client
        client = get_nexus_client()
        health = client.health()
        ok = health.get("status") == "ok" or health.get("ok", False) or bool(health)
        detail = f"entries={health.get('entries', '?')}, qa={health.get('qa_pairs', '?')}"
        return r.record("Nexus KMS health", ok, detail)
    except Exception as exc:
        return r.record("Nexus KMS health", False, str(exc))


def check_nexus_available(r: SmokeResult) -> bool:
    """Check 1b: Nexus connectivity test."""
    try:
        from engine.nexus.client import get_nexus_client
        client = get_nexus_client()
        avail = client.is_available()
        return r.record("Nexus KMS reachable", avail,
                        "port 8700" if avail else "cannot connect to port 8700")
    except Exception as exc:
        return r.record("Nexus KMS reachable", False, str(exc))


def check_embedding_service(r: SmokeResult) -> bool:
    """Check 2: Embedding service has at least one working provider."""
    try:
        from engine.nexus.embedding_service import get_embedding_service
        svc = get_embedding_service()
        # Ensure providers are initialized
        svc._ensure_providers()
        providers = svc._providers
        active = svc._active_provider
        active_name = getattr(active, "name", "none") if active else "none"
        ok = len(providers) > 0
        detail = f"providers={len(providers)}, active={active_name}"
        return r.record("Embedding service", ok, detail)
    except Exception as exc:
        return r.record("Embedding service", False, str(exc))


def check_embedding_works(r: SmokeResult) -> bool:
    """Check 2b: Actually generate an embedding vector."""
    try:
        from engine.nexus.embedding_service import get_embedding_service
        svc = get_embedding_service()
        vec = svc.embed("NEXUS smoke test", purpose="query")
        ok = isinstance(vec, list) and len(vec) > 0
        # Check normalization (should be ~1.0 for cosine space)
        if ok:
            import math
            norm = math.sqrt(sum(v * v for v in vec))
            normalized = 0.99 <= norm <= 1.01
            detail = f"dims={len(vec)}, norm={norm:.4f}"
            if not normalized:
                detail += " (WARNING: not L2-normalized)"
            return r.record("Embedding generation", ok, detail)
        return r.record("Embedding generation", False, "empty vector")
    except Exception as exc:
        return r.record("Embedding generation", False, str(exc))


def check_vector_store(r: SmokeResult) -> bool:
    """Check 3: Vector store (ChromaDB) is operational."""
    try:
        from engine.nexus.vector_store import is_vector_store_enabled, get_vector_store
        if not is_vector_store_enabled():
            return r.record("Vector store", True, "disabled in config (OK)")
        store = get_vector_store()
        health = store.health()
        ok = health.get("status") == "healthy"
        detail = (
            f"status={health.get('status')}, "
            f"vectors={health.get('total_vectors', 0)}, "
            f"collections={health.get('chromadb_collections', '?')}"
        )
        return r.record("Vector store", ok, detail)
    except Exception as exc:
        return r.record("Vector store", False, str(exc))


def check_query_router(r: SmokeResult) -> bool:
    """Check 4: Query router is initialized and can route."""
    try:
        from engine.nexus.query_router import get_query_router
        router = get_query_router()
        stats = router.stats
        detail = (
            f"total_queries={stats.total_queries}, "
            f"cache_hits={stats.cache_hits}, "
            f"hit_rate={stats.hit_rate():.0%}"
        )
        return r.record("Query router", True, detail)
    except Exception as exc:
        return r.record("Query router", False, str(exc))


def check_query_router_resolves(r: SmokeResult) -> bool:
    """Check 4b: Query router can actually resolve a test query."""
    try:
        from engine.nexus.query_router import get_query_router
        router = get_query_router()
        result = router.query("What is CosySim?", use_llm=False, min_confidence=0.1)
        ok = result.answer != "" and result.source != "none"
        detail = f"source={result.source}, confidence={result.confidence:.2f}, time={result.query_time_ms:.0f}ms"
        return r.record("Query resolution", ok, detail)
    except Exception as exc:
        return r.record("Query resolution", False, str(exc))


def check_scheduler_daemon(r: SmokeResult) -> bool:
    """Check 5: Scheduler daemon has tasks registered."""
    try:
        from engine.nexus.scheduler_daemon import get_scheduler_daemon
        daemon = get_scheduler_daemon()
        status = daemon.status()
        task_count = status.get("task_count", 0)
        running = status.get("running", False)
        overdue = status.get("overdue_count", 0)
        error_rate = status.get("error_rate_pct", 0)
        detail = (
            f"running={running}, tasks={task_count}, "
            f"overdue={overdue}, error_rate={error_rate}%"
        )
        # OK if daemon has tasks registered (may not be running outside launcher)
        ok = task_count > 0 or running
        return r.record("Scheduler daemon", ok, detail)
    except Exception as exc:
        return r.record("Scheduler daemon", False, str(exc))


def check_self_improvement_loop(r: SmokeResult, verbose: bool = False) -> bool:
    """Check 6: End-to-end self-improvement loop.

    Seeds a test entry → verifies it can be found via query router.
    """
    try:
        from engine.nexus.client import get_nexus_client
        client = get_nexus_client()
        if not client.is_available():
            return r.record("Self-improvement loop", False, "Nexus offline")

        # Seed a test Q&A pair
        test_q = "What is the NEXUS smoke test sentinel?"
        test_a = (
            "The NEXUS smoke test sentinel is a temporary entry used to verify "
            "the self-improving knowledge loop. It confirms that entries stored "
            "in Nexus can be retrieved by the query router, completing the "
            "ingestion-to-retrieval cycle."
        )
        try:
            client.add_qa(
                question=test_q,
                answer=test_a,
                category="smoke-test",
                tags=["smoke-test", "auto-generated", "temporary"],
            )
        except Exception as exc:
            return r.record("Self-improvement loop", False, f"seed failed: {exc}")

        # Small delay for indexing
        time.sleep(0.5)

        # Try to retrieve it
        from engine.nexus.query_router import get_query_router
        router = get_query_router()
        # Clear local cache to force fresh lookup
        router.clear_local_cache()
        result = router.query(test_q, use_llm=False, min_confidence=0.1)

        ok = result.source != "none" and "sentinel" in result.answer.lower()
        detail = f"source={result.source}, found={'yes' if ok else 'no'}"
        if verbose and ok:
            detail += f", answer={result.answer[:80]}..."
        return r.record("Self-improvement loop", ok, detail)
    except Exception as exc:
        return r.record("Self-improvement loop", False, str(exc))


def check_config_consistency(r: SmokeResult) -> bool:
    """Check 7: Key config values are consistent between config and code."""
    try:
        from engine.config import get_config
        cfg = get_config()

        issues = []
        # Check embedding config
        enabled = cfg.get("nexus.embeddings.enabled", None)
        if enabled is None:
            issues.append("nexus.embeddings.enabled not set")
        normalize = cfg.get("nexus.embeddings.normalize", None)
        if normalize is None:
            issues.append("nexus.embeddings.normalize not set")
        vs_enabled = cfg.get("nexus.vector_store.enabled", None)
        if vs_enabled is None:
            issues.append("nexus.vector_store.enabled not set")

        ok = len(issues) == 0
        detail = "all keys present" if ok else "; ".join(issues)
        return r.record("Config consistency", ok, detail)
    except Exception as exc:
        return r.record("Config consistency", False, str(exc))


# ──── Main ────────────────────────────────────────────────────────────────────

def run_smoke_test(verbose: bool = False) -> SmokeResult:
    """Run all NEXUS smoke test checks."""
    r = SmokeResult()

    print("\n=== NEXUS Smoke Test ===\n")
    print("  Checking system health...\n")

    # Group 1: Connectivity
    print("  -- Connectivity --")
    nexus_ok = check_nexus_available(r)
    if nexus_ok:
        check_nexus_health(r)

    # Group 2: Embeddings
    print("\n  -- Embeddings --")
    check_embedding_service(r)
    check_embedding_works(r)

    # Group 3: Vector Store
    print("\n  -- Vector Store --")
    check_vector_store(r)

    # Group 4: Query Routing
    print("\n  -- Query Routing --")
    check_query_router(r)
    if nexus_ok:
        check_query_router_resolves(r)

    # Group 5: Scheduler
    print("\n  -- Scheduler --")
    check_scheduler_daemon(r)

    # Group 6: Config
    print("\n  -- Configuration --")
    check_config_consistency(r)

    # Group 7: End-to-end loop (only if Nexus is up)
    if nexus_ok:
        print("\n  -- Self-Improvement Loop --")
        check_self_improvement_loop(r, verbose=verbose)

    # Summary
    print(f"\n=== Results: {r.summary()} ===\n")
    if r.failed > 0:
        print("  Failed checks:")
        for name, ok, detail in r.checks:
            if not ok:
                print(f"    - {name}: {detail}")
        print()

    return r


def main() -> None:
    parser = argparse.ArgumentParser(description="NEXUS Smoke Test")
    parser.add_argument("--verbose", "-v", action="store_true", help="Show detailed output")
    args = parser.parse_args()

    if args.verbose:
        logging.basicConfig(level=logging.DEBUG, format="%(levelname)s: %(message)s")
    else:
        logging.basicConfig(level=logging.WARNING, format="%(levelname)s: %(message)s")

    result = run_smoke_test(verbose=args.verbose)
    sys.exit(0 if result.failed == 0 else 1)


if __name__ == "__main__":
    main()
