"""ARGUS endpoint registry — versioned storage of all discovered API endpoints.

Maintains a persistent JSON registry at data/argus/registry.json.
Diffs against the known baseline in config.py to surface new discoveries.
"""
from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Set

from scripts.argus.config import (
    AISTUDIO_METHODS,
    APPSCRIPT_RPCIDS,
    COLAB_METHODS,
    DATA_DIR,
    GEMINI_RPCIDS,
    HEAP_DISCOVERED_METHODS,
    NLM_GRPC_METHODS,
    NLM_RPCIDS,
    WORKSPACE_OPERATIONS,
)

logger = logging.getLogger(__name__)

REGISTRY_PATH = DATA_DIR / "registry.json"
SCHEMA_VERSION = "2.0"


class EndpointRegistry:
    """Versioned registry of all discovered endpoints and rpcids.

    Structure::

        {
          "schema": "2.0",
          "nlm_rpcids":           { "rpcid": {"name": ..., "seen": N, "last": "ts"}, ...},
          "gemini_rpcids":        { ... },
          "aistudio_methods":     { "method": {"service": ..., "seen": N, "last": "ts"}, ...},
          "colab_methods":        { ... },
          "appscript_rpcids":     { ... },
          "workspace_operations": { ... },
          "nlm_grpc_methods":     { ... },
          "heap_discovered":      { ... },
          "unknown_endpoints":    { "url": {"method": ..., "seen": N, "first": "ts"}, ...},
          "runs":                 [{"ts": ..., "new_rpcids": [...], "new_methods": [...]}]
        }
    """

    def __init__(self, path: Path = REGISTRY_PATH) -> None:
        self._path = path
        self._data: Dict[str, Any] = {}
        self._load()

    # ──── Persistence ────

    def _load(self) -> None:
        """Load existing registry or initialise empty."""
        if self._path.exists():
            try:
                self._data = json.loads(self._path.read_text(encoding="utf-8"))
                logger.debug("EndpointRegistry: loaded from %s", self._path)
                return
            except Exception as exc:
                logger.warning("EndpointRegistry: failed to load, starting fresh: %s", exc)
        self._data = self._empty_registry()

    def _empty_registry(self) -> Dict[str, Any]:
        return {
            "schema": SCHEMA_VERSION,
            "nlm_rpcids": {
                rid: {"name": name, "seen": 0, "last": None}
                for rid, name in NLM_RPCIDS.items()
            },
            "gemini_rpcids": {
                rid: {"name": name, "seen": 0, "last": None}
                for rid, name in GEMINI_RPCIDS.items()
            },
            "aistudio_methods": {
                method: {"service": "MakerSuiteService", "seen": 0, "last": None}
                for method in AISTUDIO_METHODS
            },
            "colab_methods": {
                method: {"service": svc, "seen": 0, "last": None}
                for method, svc in COLAB_METHODS.items()
            },
            "appscript_rpcids": {
                rid: {"name": name, "seen": 0, "last": None}
                for rid, name in APPSCRIPT_RPCIDS.items()
            },
            "workspace_operations": {
                name: {"section": sec, "seen": 0, "last": None}
                for name, sec in WORKSPACE_OPERATIONS.items()
            },
            "nlm_grpc_methods": {
                method: {"service": svc, "seen": 0, "last": None}
                for method, svc in NLM_GRPC_METHODS.items()
            },
            "heap_discovered": {
                method: {"service": svc, "seen": 0, "last": None}
                for method, svc in HEAP_DISCOVERED_METHODS.items()
            },
            "unknown_endpoints": {},
            "runs": [],
        }

    def save(self) -> None:
        """Persist registry to disk."""
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._path.write_text(
            json.dumps(self._data, indent=2, ensure_ascii=False),
            encoding="utf-8",
        )
        logger.debug("EndpointRegistry: saved to %s", self._path)

    # ──── Registration ────

    def register_nlm_rpcid(self, rpcid: str, name: Optional[str] = None) -> bool:
        """Record a seen NLM rpcid. Returns True if this is a new discovery."""
        return self._register_rpcid(self._data["nlm_rpcids"], rpcid, name)

    def register_gemini_rpcid(self, rpcid: str, name: Optional[str] = None) -> bool:
        """Record a seen Gemini rpcid. Returns True if new."""
        return self._register_rpcid(self._data["gemini_rpcids"], rpcid, name)

    def register_aistudio_method(self, method: str, service: Optional[str] = None) -> bool:
        """Record a seen AI Studio gRPC method. Returns True if new."""
        return self._register_method(self._data["aistudio_methods"], method, service or "MakerSuiteService")

    def register_colab_method(self, method: str, service: Optional[str] = None) -> bool:
        """Record a seen Colab gRPC method. Returns True if new."""
        return self._register_method(
            self._data.setdefault("colab_methods", {}), method, service or "ColabAIService"
        )

    def register_appscript_rpcid(self, rpcid: str, name: Optional[str] = None) -> bool:
        """Record a seen Apps Script rpcid. Returns True if new."""
        return self._register_rpcid(self._data.setdefault("appscript_rpcids", {}), rpcid, name)

    def register_workspace_op(self, name: str, section: Optional[str] = None) -> bool:
        """Record a seen Workspace operation. Returns True if new."""
        store = self._data.setdefault("workspace_operations", {})
        ts = _now()
        if name in store:
            store[name]["seen"] = store[name].get("seen", 0) + 1
            store[name]["last"] = ts
            return False
        store[name] = {"section": section or "unknown", "seen": 1, "first": ts, "last": ts}
        logger.info("EndpointRegistry: NEW workspace operation: %s", name)
        return True

    def register_grpc_method(self, method: str, service: Optional[str] = None) -> bool:
        """Record a seen NLM gRPC method. Returns True if new."""
        return self._register_method(
            self._data.setdefault("nlm_grpc_methods", {}), method, service or "Unknown"
        )

    def register_heap_method(self, method: str, service: Optional[str] = None) -> bool:
        """Record a seen heap-discovered method. Returns True if new."""
        return self._register_method(
            self._data.setdefault("heap_discovered", {}), method, service or "Unknown"
        )

    def register_unknown_endpoint(self, url: str, http_method: str = "POST") -> bool:
        """Record an unclassified Google API endpoint. Returns True if new."""
        unknown = self._data["unknown_endpoints"]
        ts = _now()
        if url in unknown:
            unknown[url]["seen"] += 1
            unknown[url]["last"] = ts
            return False
        unknown[url] = {"method": http_method, "seen": 1, "first": ts, "last": ts}
        logger.info("EndpointRegistry: NEW unknown endpoint: %s", url)
        return True

    def _register_rpcid(
        self, store: Dict[str, Any], rpcid: str, name: Optional[str] = None
    ) -> bool:
        ts = _now()
        if rpcid in store:
            store[rpcid]["seen"] = store[rpcid].get("seen", 0) + 1
            store[rpcid]["last"] = ts
            return False
        store[rpcid] = {"name": name or rpcid, "seen": 1, "first": ts, "last": ts}
        logger.info("EndpointRegistry: NEW rpcid: %s (%s)", rpcid, name)
        return True

    def _register_method(
        self, store: Dict[str, Any], method: str, service: str
    ) -> bool:
        """Register a gRPC-style method into a service store."""
        ts = _now()
        if method in store:
            store[method]["seen"] = store[method].get("seen", 0) + 1
            store[method]["last"] = ts
            return False
        store[method] = {"service": service, "seen": 1, "first": ts, "last": ts}
        logger.info("EndpointRegistry: NEW method: %s (%s)", method, service)
        return True

    # ──── Diff vs baseline ────

    def diff_vs_baseline(self) -> Dict[str, List[str]]:
        """Compare seen rpcids/methods vs config.py baselines.

        Returns::

            {
              "new_nlm_rpcids":      [...],
              "new_gemini_rpcids":   [...],
              "new_ais_methods":     [...],
              "new_colab_methods":   [...],
              "new_appscript_rpcids":[...],
              "new_workspace_ops":   [...],
              "new_grpc_methods":    [...],
              "new_heap_methods":    [...],
              "new_endpoints":       [...],
              "unseen_nlm_rpcids":   [...],
            }
        """
        nlm = self._data.get("nlm_rpcids", {})
        gemini = self._data.get("gemini_rpcids", {})
        ais = self._data.get("aistudio_methods", {})
        colab = self._data.get("colab_methods", {})
        appscript = self._data.get("appscript_rpcids", {})
        workspace = self._data.get("workspace_operations", {})
        grpc = self._data.get("nlm_grpc_methods", {})
        heap = self._data.get("heap_discovered", {})

        new_nlm = [r for r, d in nlm.items() if d.get("seen", 0) > 0 and r not in NLM_RPCIDS]
        new_gemini = [r for r, d in gemini.items() if d.get("seen", 0) > 0 and r not in GEMINI_RPCIDS]
        new_ais = [m for m, d in ais.items() if d.get("seen", 0) > 0 and m not in AISTUDIO_METHODS]
        new_colab = [m for m, d in colab.items() if d.get("seen", 0) > 0 and m not in COLAB_METHODS]
        new_appscript = [r for r, d in appscript.items() if d.get("seen", 0) > 0 and r not in APPSCRIPT_RPCIDS]
        new_workspace = [n for n, d in workspace.items() if d.get("seen", 0) > 0 and n not in WORKSPACE_OPERATIONS]
        new_grpc = [m for m, d in grpc.items() if d.get("seen", 0) > 0 and m not in NLM_GRPC_METHODS]
        new_heap = [m for m, d in heap.items() if d.get("seen", 0) > 0 and m not in HEAP_DISCOVERED_METHODS]
        new_eps = list(self._data.get("unknown_endpoints", {}).keys())
        unseen_nlm = [r for r, d in nlm.items() if d.get("seen", 0) == 0 and r in NLM_RPCIDS]

        return {
            "new_nlm_rpcids": new_nlm,
            "new_gemini_rpcids": new_gemini,
            "new_ais_methods": new_ais,
            "new_colab_methods": new_colab,
            "new_appscript_rpcids": new_appscript,
            "new_workspace_ops": new_workspace,
            "new_grpc_methods": new_grpc,
            "new_heap_methods": new_heap,
            "new_endpoints": new_eps,
            "unseen_nlm_rpcids": unseen_nlm,
        }

    # ──── Run logging ────

    def record_run(
        self,
        new_rpcids: Optional[List[str]] = None,
        new_methods: Optional[List[str]] = None,
        duration_s: float = 0.0,
    ) -> None:
        """Append a run record to the history."""
        run = {
            "ts": _now(),
            "new_rpcids": new_rpcids or [],
            "new_methods": new_methods or [],
            "duration_s": duration_s,
        }
        self._data.setdefault("runs", []).append(run)
        # Keep last 52 runs (~1 year weekly)
        self._data["runs"] = self._data["runs"][-52:]

    # ──── Read helpers ────

    def get_stats(self) -> Dict[str, Any]:
        """Return summary statistics."""
        def _count(section: str) -> tuple:
            store = self._data.get(section, {})
            total = len(store)
            seen = sum(1 for d in store.values() if d.get("seen", 0) > 0)
            return total, seen

        nlm_t, nlm_s = _count("nlm_rpcids")
        gem_t, gem_s = _count("gemini_rpcids")
        ais_t, ais_s = _count("aistudio_methods")
        col_t, col_s = _count("colab_methods")
        app_t, app_s = _count("appscript_rpcids")
        wks_t, wks_s = _count("workspace_operations")
        grpc_t, grpc_s = _count("nlm_grpc_methods")
        heap_t, heap_s = _count("heap_discovered")

        return {
            "nlm_rpcids_total": nlm_t,
            "nlm_rpcids_seen": nlm_s,
            "gemini_rpcids_total": gem_t,
            "gemini_rpcids_seen": gem_s,
            "aistudio_methods_total": ais_t,
            "aistudio_methods_seen": ais_s,
            "colab_methods_total": col_t,
            "colab_methods_seen": col_s,
            "appscript_rpcids_total": app_t,
            "appscript_rpcids_seen": app_s,
            "workspace_operations_total": wks_t,
            "workspace_operations_seen": wks_s,
            "nlm_grpc_methods_total": grpc_t,
            "nlm_grpc_methods_seen": grpc_s,
            "heap_discovered_total": heap_t,
            "heap_discovered_seen": heap_s,
            "unknown_endpoints": len(self._data.get("unknown_endpoints", {})),
            "runs": len(self._data.get("runs", [])),
        }

    def get_full_data(self) -> Dict[str, Any]:
        """Return the full registry dict (copy)."""
        return dict(self._data)

    # ──── Bulk registration from capture results ────

    def process_crawl_results(
        self, crawl_results: List[Dict[str, Any]]
    ) -> Dict[str, List[str]]:
        """Bulk-process decoded crawl results and return newly discovered items.

        Args:
            crawl_results: list of dicts from decoders with keys:
                - ``type``: "nlm_rpcid" | "gemini_rpcid" | "aistudio_method" |
                  "colab_method" | "appscript_rpcid" | "workspace_op" |
                  "grpc_method" | "heap_method" | "endpoint"
                - ``value``: the rpcid/method/url string
                - ``name``: (optional) human-readable name
                - ``service``: (optional) gRPC service name
                - ``section``: (optional) workspace section name

        Returns:
            Dict with lists for each service's new discoveries.
        """
        new: Dict[str, List[str]] = {
            "new_nlm": [], "new_gemini": [], "new_ais": [],
            "new_colab": [], "new_appscript": [], "new_workspace": [],
            "new_grpc": [], "new_heap": [], "new_endpoints": [],
        }

        dispatch = {
            "nlm_rpcid": ("new_nlm", lambda r: self.register_nlm_rpcid(r["value"], r.get("name"))),
            "gemini_rpcid": ("new_gemini", lambda r: self.register_gemini_rpcid(r["value"], r.get("name"))),
            "aistudio_method": ("new_ais", lambda r: self.register_aistudio_method(r["value"], r.get("service"))),
            "colab_method": ("new_colab", lambda r: self.register_colab_method(r["value"], r.get("service"))),
            "appscript_rpcid": ("new_appscript", lambda r: self.register_appscript_rpcid(r["value"], r.get("name"))),
            "workspace_op": ("new_workspace", lambda r: self.register_workspace_op(r["value"], r.get("section"))),
            "grpc_method": ("new_grpc", lambda r: self.register_grpc_method(r["value"], r.get("service"))),
            "heap_method": ("new_heap", lambda r: self.register_heap_method(r["value"], r.get("service"))),
            "endpoint": ("new_endpoints", lambda r: self.register_unknown_endpoint(r["value"], r.get("method", "POST"))),
        }

        for result in crawl_results:
            kind = result.get("type", "")
            value = result.get("value", "")
            if not value or kind not in dispatch:
                continue
            key, handler = dispatch[kind]
            if handler(result):
                new[key].append(value)

        return new


# ──── Module-level singleton ────

_registry: Optional[EndpointRegistry] = None


def get_registry() -> EndpointRegistry:
    """Return the shared EndpointRegistry singleton."""
    global _registry
    if _registry is None:
        _registry = EndpointRegistry()
    return _registry


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()
