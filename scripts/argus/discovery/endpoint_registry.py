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
    DATA_DIR,
    GEMINI_RPCIDS,
    NLM_RPCIDS,
)

logger = logging.getLogger(__name__)

REGISTRY_PATH = DATA_DIR / "registry.json"
SCHEMA_VERSION = "1.0"


class EndpointRegistry:
    """Versioned registry of all discovered endpoints and rpcids.

    Structure::

        {
          "schema": "1.0",
          "nlm_rpcids":        { "rpcid": {"name": ..., "seen": N, "last": "ts"}, ...},
          "gemini_rpcids":     { ... },
          "aistudio_methods":  { "method": {"service": ..., "seen": N, "last": "ts"}, ...},
          "unknown_endpoints": { "url": {"method": ..., "seen": N, "first": "ts"}, ...},
          "runs":              [{"ts": ..., "new_rpcids": [...], "new_methods": [...]}]
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
        methods = self._data["aistudio_methods"]
        ts = _now()
        if method in methods:
            methods[method]["seen"] = methods[method].get("seen", 0) + 1
            methods[method]["last"] = ts
            return False
        # New method!
        methods[method] = {"service": service or "Unknown", "seen": 1, "first": ts, "last": ts}
        logger.info("EndpointRegistry: NEW AI Studio method: %s", method)
        return True

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
        # New!
        store[rpcid] = {"name": name or rpcid, "seen": 1, "first": ts, "last": ts}
        logger.info("EndpointRegistry: NEW rpcid: %s (%s)", rpcid, name)
        return True

    # ──── Diff vs baseline ────

    def diff_vs_baseline(self) -> Dict[str, List[str]]:
        """Compare seen rpcids/methods vs config.py baselines.

        Returns::

            {
              "new_nlm_rpcids":    [...],
              "new_gemini_rpcids": [...],
              "new_ais_methods":   [...],
              "new_endpoints":     [...],
              "unseen_nlm_rpcids": [...],
            }
        """
        nlm = self._data["nlm_rpcids"]
        gemini = self._data["gemini_rpcids"]
        ais = self._data["aistudio_methods"]

        new_nlm = [r for r, d in nlm.items() if d.get("seen", 0) > 0 and r not in NLM_RPCIDS]
        new_gemini = [r for r, d in gemini.items() if d.get("seen", 0) > 0 and r not in GEMINI_RPCIDS]
        new_ais = [m for m, d in ais.items() if d.get("seen", 0) > 0 and m not in AISTUDIO_METHODS]
        new_eps = list(self._data["unknown_endpoints"].keys())
        unseen_nlm = [r for r, d in nlm.items() if d.get("seen", 0) == 0 and r in NLM_RPCIDS]

        return {
            "new_nlm_rpcids": new_nlm,
            "new_gemini_rpcids": new_gemini,
            "new_ais_methods": new_ais,
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
        return {
            "nlm_rpcids_total": len(self._data["nlm_rpcids"]),
            "nlm_rpcids_seen": sum(
                1 for d in self._data["nlm_rpcids"].values() if d.get("seen", 0) > 0
            ),
            "gemini_rpcids_total": len(self._data["gemini_rpcids"]),
            "gemini_rpcids_seen": sum(
                1 for d in self._data["gemini_rpcids"].values() if d.get("seen", 0) > 0
            ),
            "aistudio_methods_total": len(self._data["aistudio_methods"]),
            "aistudio_methods_seen": sum(
                1 for d in self._data["aistudio_methods"].values() if d.get("seen", 0) > 0
            ),
            "unknown_endpoints": len(self._data["unknown_endpoints"]),
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
                - ``type``: "nlm_rpcid" | "gemini_rpcid" | "aistudio_method" | "endpoint"
                - ``value``: the rpcid/method/url string
                - ``name``: (optional) human-readable name
                - ``service``: (optional) gRPC service name

        Returns:
            Dict with ``new_nlm``, ``new_gemini``, ``new_ais``, ``new_endpoints`` lists.
        """
        new_nlm: List[str] = []
        new_gemini: List[str] = []
        new_ais: List[str] = []
        new_eps: List[str] = []

        for result in crawl_results:
            kind = result.get("type", "")
            value = result.get("value", "")
            if not value:
                continue

            if kind == "nlm_rpcid":
                if self.register_nlm_rpcid(value, result.get("name")):
                    new_nlm.append(value)
            elif kind == "gemini_rpcid":
                if self.register_gemini_rpcid(value, result.get("name")):
                    new_gemini.append(value)
            elif kind == "aistudio_method":
                if self.register_aistudio_method(value, result.get("service")):
                    new_ais.append(value)
            elif kind == "endpoint":
                if self.register_unknown_endpoint(value, result.get("method", "POST")):
                    new_eps.append(value)

        return {
            "new_nlm": new_nlm,
            "new_gemini": new_gemini,
            "new_ais": new_ais,
            "new_endpoints": new_eps,
        }


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
