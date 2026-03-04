"""ARGUS rpcid detector — compares live traffic rpcids against the known baseline.

Emits discovery events for any rpcid that is NOT in config.py.
Also tracks which known rpcids have NEVER been seen (coverage gaps).
"""
from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from typing import Callable, Dict, List, Optional, Set

from scripts.argus.config import GEMINI_RPCIDS, NLM_RPCIDS
from scripts.argus.discovery.endpoint_registry import get_registry
from scripts.argus.network_monitor import CapturedRequest

logger = logging.getLogger(__name__)

# rpcid is 4–8 mixed-case alphanumeric chars
_RPCID_RE = re.compile(r'\b([A-Za-z][A-Za-z0-9]{3,7})\b')

# Known good rpcids that produce false positives (common words, JS tokens, etc.)
_IGNORE: Set[str] = {
    "true", "false", "null", "undefined", "function", "return",
    "class", "const", "let", "var", "async", "await", "import",
    "export", "default", "this", "super", "extends", "static",
    "catch", "throw", "from", "void", "type",
}


@dataclass
class RpcidEvent:
    """A newly discovered rpcid."""
    rpcid: str
    source: str  # "batchexecute" | "heap" | "bundle"
    context: str  # surrounding text for identification
    target: str   # "nlm" | "gemini" | "aistudio" | "unknown"
    url: str = ""

    def to_nexus_entry(self) -> Dict[str, str]:
        return {
            "title": f"New rpcid discovered: {self.rpcid}",
            "content": (
                f"Source: {self.source}\n"
                f"Target: {self.target}\n"
                f"URL: {self.url}\n"
                f"Context: {self.context[:300]}"
            ),
            "content_type": "note",
            "category": "argus",
        }


@dataclass
class RpcidDetector:
    """Stateful detector: accumulates seen rpcids and fires callbacks on discoveries."""

    _seen_nlm: Set[str] = field(default_factory=set)
    _seen_gemini: Set[str] = field(default_factory=set)
    _on_discovery: List[Callable[[RpcidEvent], None]] = field(default_factory=list)

    def on_discovery(self, callback: Callable[[RpcidEvent], None]) -> None:
        """Register a callback invoked whenever a new rpcid is found."""
        self._on_discovery.append(callback)

    # ──── Main analysis entry points ────

    def analyse_request(self, req: CapturedRequest) -> List[RpcidEvent]:
        """Analyse a single captured request for rpcids."""
        events: List[RpcidEvent] = []
        target = _classify_target(req.url)

        if req.is_batchexecute:
            events.extend(self._scan_batchexecute(req, target))

        if req.is_grpc_web:
            events.extend(self._scan_grpc(req, target))

        return events

    def analyse_heap_strings(
        self, strings: List[str], target: str = "unknown"
    ) -> List[RpcidEvent]:
        """Scan a list of raw heap strings for new rpcids."""
        events: List[RpcidEvent] = []
        baseline = NLM_RPCIDS if target == "nlm" else GEMINI_RPCIDS
        for s in strings:
            found = _RPCID_RE.findall(s)
            for rpcid in found:
                if self._is_candidate(rpcid, baseline):
                    ev = RpcidEvent(
                        rpcid=rpcid,
                        source="heap",
                        context=s[:200],
                        target=target,
                    )
                    events.append(ev)
                    self._fire(ev)
        return events

    def analyse_bundle(
        self, bundle_text: str, target: str = "unknown"
    ) -> List[RpcidEvent]:
        """Scan a JS bundle for embedded rpcid literals."""
        events: List[RpcidEvent] = []
        baseline = NLM_RPCIDS if target == "nlm" else GEMINI_RPCIDS

        # Look for patterns like: rpcid: "XyzAbc", 'rpcid','XyzAbc', etc.
        patterns = [
            re.compile(r'"rpcid"\s*,\s*"([A-Za-z][A-Za-z0-9]{3,7})"'),
            re.compile(r"'rpcid'\s*,\s*'([A-Za-z][A-Za-z0-9]{3,7})'"),
            re.compile(r'rpcid:\s*"([A-Za-z][A-Za-z0-9]{3,7})"'),
        ]
        for pat in patterns:
            for m in pat.finditer(bundle_text):
                rpcid = m.group(1)
                if self._is_candidate(rpcid, baseline):
                    ctx = bundle_text[max(0, m.start() - 80): m.end() + 80]
                    ev = RpcidEvent(
                        rpcid=rpcid,
                        source="bundle",
                        context=ctx,
                        target=target,
                    )
                    events.append(ev)
                    self._fire(ev)
        return events

    # ──── Coverage reporting ────

    def coverage_report(self) -> Dict[str, object]:
        """Return coverage stats for known rpcids."""
        seen_nlm = self._seen_nlm & set(NLM_RPCIDS.keys())
        seen_gemini = self._seen_gemini & set(GEMINI_RPCIDS.keys())

        unseen_nlm = set(NLM_RPCIDS.keys()) - seen_nlm
        unseen_gemini = set(GEMINI_RPCIDS.keys()) - seen_gemini

        new_nlm = self._seen_nlm - set(NLM_RPCIDS.keys())
        new_gemini = self._seen_gemini - set(GEMINI_RPCIDS.keys())

        return {
            "nlm": {
                "total": len(NLM_RPCIDS),
                "seen": len(seen_nlm),
                "unseen": sorted(unseen_nlm),
                "new_discoveries": sorted(new_nlm),
                "coverage_pct": round(100 * len(seen_nlm) / max(len(NLM_RPCIDS), 1)),
            },
            "gemini": {
                "total": len(GEMINI_RPCIDS),
                "seen": len(seen_gemini),
                "unseen": sorted(unseen_gemini),
                "new_discoveries": sorted(new_gemini),
                "coverage_pct": round(100 * len(seen_gemini) / max(len(GEMINI_RPCIDS), 1)),
            },
        }

    # ──── Internal helpers ────

    def _scan_batchexecute(
        self, req: CapturedRequest, target: str
    ) -> List[RpcidEvent]:
        events: List[RpcidEvent] = []
        payload = req.post_data or ""
        baseline = NLM_RPCIDS if "notebooklm" in req.url else GEMINI_RPCIDS

        # Extract rpcid from f.req=[[["rpcid","data",null,"generic"]]]
        rpcid_matches = re.findall(r'\[\["([A-Za-z][A-Za-z0-9]{3,7})"', payload)
        for rpcid in rpcid_matches:
            if self._is_candidate(rpcid, baseline):
                target_key = "nlm" if "notebooklm" in req.url else "gemini"
                if target_key == "nlm":
                    self._seen_nlm.add(rpcid)
                else:
                    self._seen_gemini.add(rpcid)

                ev = RpcidEvent(
                    rpcid=rpcid,
                    source="batchexecute",
                    context=payload[:200],
                    target=target_key,
                    url=req.url,
                )
                events.append(ev)
                self._fire(ev)
                # Also register in endpoint registry
                if target_key == "nlm":
                    get_registry().register_nlm_rpcid(rpcid)
                else:
                    get_registry().register_gemini_rpcid(rpcid)

        return events

    def _scan_grpc(
        self, req: CapturedRequest, target: str
    ) -> List[RpcidEvent]:
        """Extract AI Studio method from gRPC-web URL."""
        events: List[RpcidEvent] = []
        # URL: .../MakerSuiteService/MethodName
        m = re.search(r'/([A-Za-z][A-Za-z0-9]+(?:Service|Rpc|Api))\/([A-Za-z][A-Za-z0-9]+)$',
                      req.url)
        if m:
            method = m.group(2)
            get_registry().register_aistudio_method(method, m.group(1))

        return events

    def _is_candidate(self, rpcid: str, baseline: Dict[str, str]) -> bool:
        """True if rpcid looks like a real rpcid and is NOT in the ignore list."""
        if rpcid.lower() in _IGNORE:
            return False
        if rpcid in baseline:
            return False  # Known — not a new discovery
        if len(rpcid) < 4 or len(rpcid) > 8:
            return False
        if rpcid.islower() or rpcid.isupper():
            return False  # real rpcids are mixed case
        return True

    def _fire(self, event: RpcidEvent) -> None:
        """Invoke all registered discovery callbacks."""
        for cb in self._on_discovery:
            try:
                cb(event)
            except Exception as exc:
                logger.error("RpcidDetector: callback error: %s", exc)


def _classify_target(url: str) -> str:
    if "notebooklm" in url:
        return "nlm"
    if "gemini.google" in url:
        return "gemini"
    if "aistudio" in url or "alkalimakersuite" in url:
        return "aistudio"
    return "unknown"


# ──── Module-level singleton ────

_detector: Optional[RpcidDetector] = None


def get_detector() -> RpcidDetector:
    """Return the shared RpcidDetector singleton."""
    global _detector
    if _detector is None:
        _detector = RpcidDetector()
    return _detector
