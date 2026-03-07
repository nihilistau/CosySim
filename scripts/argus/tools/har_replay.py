"""ARGUS HAR Replay — parse captured .har files without a live browser.

Feeds all batchexecute + gRPC-web requests from a HAR file through the
ARGUS decoders and discovery pipeline, exactly as if they were captured
live. Useful for analysing large offline HAR files (e.g. the 39MB
script.google.com capture from nihilistcod).

Usage:
    # CLI
    python -m scripts.argus.tools.har_replay --har artifacts/argus/har/nihilistcod/script.google.com.har
    python -m scripts.argus.tools.har_replay --har artifacts/argus/har/nihilistcod/script.google.com.har --target apps_script --report

    # Python
    from scripts.argus.tools.har_replay import HARReplayer
    replayer = HARReplayer("artifacts/argus/har/nihilistcod/script.google.com.har")
    results = replayer.run()
    print(results.summary())
"""
from __future__ import annotations

import argparse
import json
import logging
import time
import urllib.parse
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional

from scripts.argus import config as cfg
from scripts.argus.decoders.batchexecute import BatchExecuteDecoder, BatchRequest, BatchFrame
from scripts.argus.decoders.grpc_web import GrpcWebDecoder as GRPCWebDecoder
from scripts.argus.discovery.endpoint_registry import EndpointRegistry
from scripts.argus.discovery.rpcid_detector import RpcidDetector
from scripts.argus.nexus_sink import ArgusNexusSink as NexusSink

logger = logging.getLogger(__name__)

# ──── Data structures ────────────────────────────────────────────────────────

@dataclass
class HAREntry:
    """A single request/response pair from a HAR file."""

    url: str
    method: str
    request_body: str
    response_body: str
    status: int
    mime_type: str
    time_ms: float
    started_at: str


@dataclass
class ReplayResult:
    """Aggregated results from a HAR replay run."""

    har_path: str
    target_name: str
    total_entries: int = 0
    batchexecute_entries: int = 0
    grpc_entries: int = 0
    skipped_entries: int = 0

    new_rpcids: List[str] = field(default_factory=list)
    known_rpcids: List[str] = field(default_factory=list)
    all_requests: List[BatchRequest] = field(default_factory=list)
    all_frames: List[BatchFrame] = field(default_factory=list)
    endpoints: List[str] = field(default_factory=list)
    heap_fields: List[str] = field(default_factory=list)    # extracted from JS/JSON responses

    errors: List[str] = field(default_factory=list)

    def summary(self) -> str:
        """Return a human-readable summary string."""
        lines = [
            f"HAR Replay: {self.har_path}",
            f"  Target:      {self.target_name}",
            f"  Entries:     {self.total_entries} total / {self.batchexecute_entries} batchexecute / {self.grpc_entries} gRPC",
            f"  rpcids:      {len(self.known_rpcids)} known + {len(self.new_rpcids)} NEW",
            f"  Endpoints:   {len(self.endpoints)}",
        ]
        if self.new_rpcids:
            lines.append(f"  NEW rpcids:  {', '.join(self.new_rpcids)}")
        if self.errors:
            lines.append(f"  Errors:      {len(self.errors)}")
        return "\n".join(lines)


# ──── Replayer ───────────────────────────────────────────────────────────────

class HARReplayer:
    """Parse a .har file and feed all requests through ARGUS decoders.

    Args:
        har_path: Path to the .har file.
        target_name: Name of the ARGUS target (e.g. "apps_script", "notebooklm").
        store_nexus: Whether to store discoveries in Nexus.
    """

    def __init__(
        self,
        har_path: str | Path,
        target_name: str = "unknown",
        store_nexus: bool = True,
    ) -> None:
        self._har_path = Path(har_path)
        self._target_name = target_name
        self._store_nexus = store_nexus

        self._batch_decoder = BatchExecuteDecoder()
        self._grpc_decoder = GRPCWebDecoder()
        self._registry = EndpointRegistry()
        self._detector = RpcidDetector()
        self._nexus = NexusSink() if store_nexus else None

    # ──── Public ─────────────────────────────────────────────────────────────

    def run(self) -> ReplayResult:
        """Parse the HAR file and return aggregated ReplayResult.

        Returns:
            ReplayResult with all decoded requests, new rpcids, endpoints.
        """
        logger.info("Starting HAR replay: %s", self._har_path)
        result = ReplayResult(
            har_path=str(self._har_path),
            target_name=self._target_name,
        )

        entries = self._load_har_entries()
        result.total_entries = len(entries)
        logger.info("Loaded %d HAR entries", len(entries))

        for entry in entries:
            try:
                self._process_entry(entry, result)
            except Exception as exc:
                logger.debug("Error processing entry %s: %s", entry.url, exc)
                result.errors.append(f"{entry.url}: {exc}")

        # Detect new rpcids
        known = set(cfg.NLM_RPCIDS) | set(cfg.GEMINI_RPCIDS) | set(cfg.GAS_RPCIDS)
        for req in result.all_requests:
            if req.rpcid in known:
                if req.rpcid not in result.known_rpcids:
                    result.known_rpcids.append(req.rpcid)
            else:
                if req.rpcid not in result.new_rpcids:
                    result.new_rpcids.append(req.rpcid)

        # Collect unique endpoints
        result.endpoints = list({req.url for req in result.all_requests})

        # Store to Nexus
        if self._nexus and (result.new_rpcids or result.all_requests):
            self._store_to_nexus(result)

        logger.info("HAR replay complete. %s", result.summary())
        return result

    def extract_override_candidates(self, result: Optional[ReplayResult] = None) -> Dict[str, Any]:
        """Extract client-side override candidates from replay results.

        Looks for model field, quota fields, and feature flag fields in
        all decoded payloads. Returns dict of field_name → [example_values].

        Args:
            result: Prior ReplayResult or None to run a fresh replay.

        Returns:
            Dict mapping field name to list of observed values.
        """
        if result is None:
            result = self.run()

        candidates: Dict[str, List[Any]] = {}
        override_keys = {
            "model", "modelVersion", "backendModel", "generationConfig",
            "remainingQueries", "queryLimit", "dailyQuota", "queryCount",
            "notebookCount", "notebookLimit", "maxNotebooks",
            "featureFlags", "enabledFlags", "tier", "subscription",
        }

        def _walk(obj: Any, path: str = "") -> None:
            if isinstance(obj, dict):
                for k, v in obj.items():
                    full_key = f"{path}.{k}" if path else k
                    if k in override_keys:
                        candidates.setdefault(k, [])
                        if v not in candidates[k]:
                            candidates[k].append(v)
                    _walk(v, full_key)
            elif isinstance(obj, list):
                for item in obj:
                    _walk(item, path)

        for req in result.all_requests:
            if req.payload:
                _walk(req.payload)
        for frame in result.all_frames:
            if frame.data:
                _walk(frame.data)

        return candidates

    # ──── Private ────────────────────────────────────────────────────────────

    def _load_har_entries(self) -> List[HAREntry]:
        """Load and parse entries from the .har file.

        Returns:
            List of HAREntry objects.
        """
        with self._har_path.open(encoding="utf-8", errors="replace") as fh:
            har = json.load(fh)

        raw_entries = har.get("log", {}).get("entries", [])
        entries: List[HAREntry] = []

        for raw in raw_entries:
            try:
                req = raw.get("request", {})
                resp = raw.get("response", {})

                req_body = ""
                post_data = req.get("postData", {})
                if post_data:
                    req_body = post_data.get("text", "")

                resp_body = ""
                resp_content = resp.get("content", {})
                if resp_content:
                    resp_body = resp_content.get("text", "")

                entries.append(HAREntry(
                    url=req.get("url", ""),
                    method=req.get("method", "GET"),
                    request_body=req_body,
                    response_body=resp_body,
                    status=resp.get("status", 0),
                    mime_type=resp_content.get("mimeType", ""),
                    time_ms=raw.get("time", 0),
                    started_at=raw.get("startedDateTime", ""),
                ))
            except Exception as exc:
                logger.debug("Could not parse HAR entry: %s", exc)

        return entries

    def _process_entry(self, entry: HAREntry, result: ReplayResult) -> None:
        """Classify and decode a single HAR entry.

        Args:
            entry: The HAR entry to process.
            result: ReplayResult to update in place.
        """
        url = entry.url

        # batchexecute
        if "batchexecute" in url or "data/batchexecute" in url:
            self._decode_batchexecute(entry, result)
            result.batchexecute_entries += 1
            return

        # gRPC-web ($rpc/ prefix)
        if "/$rpc/" in url or "/grpc/" in url:
            self._decode_grpc(entry, result)
            result.grpc_entries += 1
            return

        # Other (fetch API, xhr, static assets)
        result.skipped_entries += 1

    def _decode_batchexecute(self, entry: HAREntry, result: ReplayResult) -> None:
        """Decode a batchexecute request/response pair."""
        body = entry.request_body

        # URL-decode f.req
        req_str = body
        if "f.req=" in body:
            try:
                req_str = urllib.parse.unquote(body.split("f.req=", 1)[1].split("&", 1)[0])
            except Exception:
                pass

        # Decode request frames
        requests = self._batch_decoder.decode_request(req_str)
        for req_obj in requests:
            req_obj.url = entry.url
            result.all_requests.append(req_obj)

        # Decode response frames
        if entry.response_body:
            frames = self._batch_decoder.decode_response(entry.response_body)
            result.all_frames.extend(frames)

    def _decode_grpc(self, entry: HAREntry, result: ReplayResult) -> None:
        """Decode a gRPC-web request/response pair."""
        method = entry.url.rsplit("/", 1)[-1] if "/" in entry.url else entry.url
        payload = {}

        if entry.request_body:
            try:
                payload = json.loads(entry.request_body)
            except json.JSONDecodeError:
                pass

        # Register as a synthetic BatchRequest for uniform handling
        req_obj = BatchRequest(
            rpcid=method,
            payload_raw=entry.request_body or "",
            payload=payload,
            service="grpc-web",
            url=entry.url,
        )
        result.all_requests.append(req_obj)

    def _store_to_nexus(self, result: ReplayResult) -> None:
        """Store replay discoveries to Nexus.

        Args:
            result: Completed ReplayResult.
        """
        if not self._nexus:
            return
        try:
            self._nexus.store_har_replay(
                target=self._target_name,
                har_path=str(self._har_path),
                new_rpcids=result.new_rpcids,
                known_rpcids=result.known_rpcids,
                endpoint_count=len(result.endpoints),
                summary=result.summary(),
            )
        except Exception as exc:
            logger.warning("Could not store replay to Nexus: %s", exc)


# ──── CLI ────────────────────────────────────────────────────────────────────

def _build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="ARGUS HAR Replay — parse captured HAR files offline")
    p.add_argument("--har", required=True, help="Path to .har file")
    p.add_argument("--target", default="unknown", help="ARGUS target name (e.g. apps_script)")
    p.add_argument("--report", action="store_true", help="Print full report after replay")
    p.add_argument("--overrides", action="store_true", help="Extract client-side override candidates")
    p.add_argument("--no-nexus", action="store_true", help="Skip Nexus storage")
    return p


def main() -> None:
    """CLI entry point."""
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    args = _build_parser().parse_args()

    replayer = HARReplayer(
        har_path=args.har,
        target_name=args.target,
        store_nexus=not args.no_nexus,
    )

    result = replayer.run()
    print(result.summary())

    if args.report:
        print("\n-- New rpcids --")
        for rpcid in result.new_rpcids:
            matching = [r for r in result.all_requests if r.rpcid == rpcid]
            print(f"  {rpcid}  ({len(matching)} calls)")
            if matching and matching[0].payload:
                preview = str(matching[0].payload)[:120]
                print(f"    payload: {preview}")

        print("\n-- Known rpcids seen --")
        for rpcid in result.known_rpcids:
            count = sum(1 for r in result.all_requests if r.rpcid == rpcid)
            print(f"  {rpcid}  ({count} calls)")

        print("\n-- Endpoints --")
        for ep in sorted(result.endpoints):
            print(f"  {ep}")

    if args.overrides:
        print("\n-- Client-side override candidates --")
        candidates = replayer.extract_override_candidates(result)
        for field_name, values in sorted(candidates.items()):
            print(f"  {field_name}: {values}")


if __name__ == "__main__":
    main()
