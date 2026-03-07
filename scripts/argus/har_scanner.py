"""ARGUS HAR batch processor — scan .har files to populate the endpoint registry.

Reads all .har files from artifacts/argus/har/ recursively, extracts every
batchexecute and gRPC-web request, decodes them with ARGUS decoders, and
populates the endpoint registry. First-seen request/response payloads per
rpcid are saved to artifacts/argus/payloads/ for SDK implementation reference.

CLI::

    python -m scripts.argus.har_scanner                      # scan all HARs
    python -m scripts.argus.har_scanner --dir path/to/hars   # specific dir
    python -m scripts.argus.har_scanner --report             # print report
"""
from __future__ import annotations

import argparse
import base64
import hashlib
import json
import logging
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Set

from scripts.argus.config import GAS_RPCIDS, GEMINI_RPCIDS, NLM_RPCIDS
from scripts.argus.decoders.batchexecute import BatchExecuteDecoder, BatchRequest, BatchResponse
from scripts.argus.decoders.grpc_web import GrpcWebDecoder
from scripts.argus.discovery.endpoint_registry import EndpointRegistry, get_registry
from scripts.argus.paths import HAR_DIR, HAR_SCAN_REPORT_PATH, PAYLOADS_DIR

logger = logging.getLogger(__name__)

# ──── Paths ────────────────────────────────────────────────────────────────────
REPORT_PATH = HAR_SCAN_REPORT_PATH


# ──── ScanStats ────────────────────────────────────────────────────────────────

@dataclass
class ScanStats:
    """Statistics from a single HAR scan run.

    Attributes:
        files_scanned: Number of .har files processed (after dedup).
        requests_total: Total HTTP entries examined.
        batchexecute_calls: Entries identified as batchexecute calls.
        grpc_calls: Entries identified as gRPC-web calls.
        rpcids_nlm: Unique NLM rpcids seen in this run.
        rpcids_gemini: Unique Gemini rpcids seen in this run.
        rpcids_gas: Unique GAS rpcids seen in this run.
        rpcids_unknown: Unique unknown rpcids not in any baseline.
        new_discoveries: rpcids/methods not in any known baseline.
        errors: Number of parsing or decoding errors encountered.
    """

    files_scanned: int = 0
    requests_total: int = 0
    batchexecute_calls: int = 0
    grpc_calls: int = 0
    rpcids_nlm: int = 0
    rpcids_gemini: int = 0
    rpcids_gas: int = 0
    rpcids_unknown: int = 0
    new_discoveries: int = 0
    errors: int = 0


# ──── HarScanner ───────────────────────────────────────────────────────────────

class HarScanner:
    """Batch HAR file processor for ARGUS endpoint discovery.

    Scans .har files, extracts batchexecute and gRPC-web requests, decodes
    them with existing ARGUS decoders, and populates the endpoint registry.
    Saves first-seen payload examples per rpcid for SDK implementation reference.

    Args:
        payloads_dir: Override directory for payload JSON files (default:
            artifacts/argus/payloads/).
        registry: Override EndpointRegistry instance (default: shared singleton).
    """

    def __init__(
        self,
        payloads_dir: Optional[Path] = None,
        registry: Optional[EndpointRegistry] = None,
    ) -> None:
        self._be_decoder = BatchExecuteDecoder()
        self._grpc_decoder = GrpcWebDecoder()
        self._registry = registry if registry is not None else get_registry()
        self._payloads_dir = payloads_dir or PAYLOADS_DIR
        self._payloads_dir.mkdir(parents=True, exist_ok=True)

        # Per-scanner accumulation across all scan calls
        self._seen_nlm: Set[str] = set()
        self._seen_gemini: Set[str] = set()
        self._seen_gas: Set[str] = set()
        self._seen_unknown: Set[str] = set()
        self._new_discoveries: Set[str] = set()

        # First-seen payload examples (in-memory, also written to disk)
        self._payload_examples: Dict[str, Dict[str, Any]] = {}

        # Deduplication: set of MD5 hashes of processed file contents
        self._processed_hashes: Set[str] = set()

        # Ordered list of scanned file paths (as strings) for the report
        self._files_scanned: List[str] = []

        # Last completed scan_directory stats (used by get_report)
        self._last_stats: ScanStats = ScanStats()

    # ──── Public API ───────────────────────────────────────────────────────────

    def scan_file(self, path: Path) -> ScanStats:
        """Scan one .har file and update the registry.

        Decodes all batchexecute and gRPC-web entries in the file.
        Updates the scanner's internal accumulation state.

        Args:
            path: Path to the .har file.

        Returns:
            ScanStats for this file only (rpcid counts = unique rpcids in
            this file, not cumulative).
        """
        stats = ScanStats(files_scanned=1)
        local_nlm: Set[str] = set()
        local_gemini: Set[str] = set()
        local_gas: Set[str] = set()
        local_unknown: Set[str] = set()
        local_new: Set[str] = set()

        try:
            raw = path.read_text(encoding="utf-8", errors="replace")
            har = json.loads(raw)
        except Exception as exc:
            logger.warning("Failed to parse HAR %s: %s", path.name, exc)
            stats.errors += 1
            return stats

        try:
            entries: List[Dict[str, Any]] = har.get("log", {}).get("entries", []) or []
        except (AttributeError, TypeError) as exc:
            logger.warning("Unexpected HAR structure in %s: %s", path.name, exc)
            stats.errors += 1
            return stats

        for entry in entries:
            stats.requests_total += 1
            try:
                self._process_entry(
                    entry, stats,
                    local_nlm, local_gemini, local_gas, local_unknown, local_new,
                )
            except Exception as exc:
                logger.debug("Entry processing error in %s: %s", path.name, exc)
                stats.errors += 1

        # Merge per-file sets into scanner-wide accumulation
        self._seen_nlm |= local_nlm
        self._seen_gemini |= local_gemini
        self._seen_gas |= local_gas
        self._seen_unknown |= local_unknown
        self._new_discoveries |= local_new

        # Fill per-file rpcid counts
        stats.rpcids_nlm = len(local_nlm)
        stats.rpcids_gemini = len(local_gemini)
        stats.rpcids_gas = len(local_gas)
        stats.rpcids_unknown = len(local_unknown)
        stats.new_discoveries = len(local_new)

        self._files_scanned.append(str(path))
        return stats

    def scan_directory(self, dir: Path = HAR_DIR) -> ScanStats:
        """Scan all .har files in a directory recursively.

        Files are deduplicated by MD5 content hash — identical files in
        different sub-folders are processed only once.

        Args:
            dir: Root directory to scan (default: artifacts/argus/har/).

        Returns:
            Aggregated ScanStats across all processed files.  rpcid counts
            reflect unique rpcids seen across the entire scan.
        """
        total = ScanStats()

        har_files = sorted(dir.rglob("*.har"))
        logger.info("HarScanner: found %d .har files under %s", len(har_files), dir)

        for har_path in har_files:
            try:
                content_hash = hashlib.md5(har_path.read_bytes()).hexdigest()
            except Exception as exc:
                logger.warning("Cannot read/hash %s: %s", har_path, exc)
                total.errors += 1
                continue

            if content_hash in self._processed_hashes:
                logger.debug("Skipping duplicate HAR: %s (%s)", har_path.name, content_hash)
                continue

            self._processed_hashes.add(content_hash)
            logger.info("Scanning %s ...", har_path.name)
            file_stats = self.scan_file(har_path)

            total.files_scanned += file_stats.files_scanned
            total.requests_total += file_stats.requests_total
            total.batchexecute_calls += file_stats.batchexecute_calls
            total.grpc_calls += file_stats.grpc_calls
            total.errors += file_stats.errors

        # rpcid counts are set from the scanner-wide (deduplicated) sets
        total.rpcids_nlm = len(self._seen_nlm)
        total.rpcids_gemini = len(self._seen_gemini)
        total.rpcids_gas = len(self._seen_gas)
        total.rpcids_unknown = len(self._seen_unknown)
        total.new_discoveries = len(self._new_discoveries)

        self._registry.save()
        self._last_stats = total

        logger.info(
            "HarScanner complete: %d files, %d requests, "
            "%d batchexecute, %d gRPC-web, %d new discoveries",
            total.files_scanned, total.requests_total,
            total.batchexecute_calls, total.grpc_calls, total.new_discoveries,
        )
        return total

    def get_report(self) -> Dict[str, Any]:
        """Build a full report of all accumulated scan results.

        Returns:
            Dict containing: generated_at timestamp, files_scanned, total
            requests, batchexecute/grpc counts, rpcids grouped by service,
            new discoveries, per-rpcid details including payload file status,
            and errors count.
        """
        rpcid_names: Dict[str, str] = {}
        rpcid_names.update(NLM_RPCIDS)
        rpcid_names.update(GEMINI_RPCIDS)
        rpcid_names.update(GAS_RPCIDS)

        # Build a flat rpcid → service map
        all_seen: Dict[str, str] = {}
        all_seen.update({r: "nlm" for r in self._seen_nlm})
        all_seen.update({r: "gemini" for r in self._seen_gemini})
        all_seen.update({r: "gas" for r in self._seen_gas})
        all_seen.update({r: "unknown" for r in self._seen_unknown})

        rpcid_details: Dict[str, Dict[str, Any]] = {
            rpcid: {
                "service": service,
                "name": rpcid_names.get(rpcid, "UNKNOWN"),
                "has_payload": (self._payloads_dir / f"{rpcid}_request.json").exists(),
                "has_response": (self._payloads_dir / f"{rpcid}_response.json").exists(),
            }
            for rpcid, service in all_seen.items()
        }

        s = self._last_stats
        return {
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "files_scanned": len(self._files_scanned),
            "files": self._files_scanned,
            "requests_total": s.requests_total,
            "batchexecute_calls": s.batchexecute_calls,
            "grpc_calls": s.grpc_calls,
            "rpcids_by_service": {
                "nlm": sorted(self._seen_nlm),
                "gemini": sorted(self._seen_gemini),
                "gas": sorted(self._seen_gas),
                "unknown": sorted(self._seen_unknown),
            },
            "rpcid_counts": {
                "nlm": len(self._seen_nlm),
                "gemini": len(self._seen_gemini),
                "gas": len(self._seen_gas),
                "unknown": len(self._seen_unknown),
            },
            "new_discoveries": sorted(self._new_discoveries),
            "new_discovery_count": len(self._new_discoveries),
            "rpcid_details": rpcid_details,
            "errors": s.errors,
            "payloads_dir": str(self._payloads_dir),
        }

    def save_report(self, path: Path = REPORT_PATH) -> None:
        """Serialise the scan report to a JSON file.

        Args:
            path: Destination path (default: data/argus/har_scan_report.json).
        """
        report = self.get_report()
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            json.dumps(report, indent=2, ensure_ascii=False),
            encoding="utf-8",
        )
        logger.info("HarScanner: report saved to %s", path)

    # ──── Internal: entry routing ──────────────────────────────────────────────

    def _process_entry(
        self,
        entry: Dict[str, Any],
        stats: ScanStats,
        local_nlm: Set[str],
        local_gemini: Set[str],
        local_gas: Set[str],
        local_unknown: Set[str],
        local_new: Set[str],
    ) -> None:
        """Route a single HAR entry to the appropriate decoder.

        Args:
            entry: HAR log entry dict.
            stats: Mutable ScanStats for the current file.
            local_nlm: Per-file NLM rpcid accumulator.
            local_gemini: Per-file Gemini rpcid accumulator.
            local_gas: Per-file GAS rpcid accumulator.
            local_unknown: Per-file unknown rpcid accumulator.
            local_new: Per-file new-discovery accumulator.
        """
        request: Dict[str, Any] = entry.get("request", {}) or {}
        response: Dict[str, Any] = entry.get("response", {}) or {}

        url: str = request.get("url", "") or ""
        method: str = request.get("method", "") or ""

        if method != "POST":
            return

        post_data: Dict[str, Any] = request.get("postData", {}) or {}
        post_text: str = post_data.get("text", "") or ""

        resp_content: Dict[str, Any] = response.get("content", {}) or {}
        resp_text: str = resp_content.get("text", "") or ""
        resp_encoding: str = resp_content.get("encoding", "") or ""

        if resp_encoding == "base64" and resp_text:
            try:
                resp_text = base64.b64decode(resp_text).decode("utf-8", errors="replace")
            except Exception:
                resp_text = ""

        is_batch = "batchexecute" in url
        is_grpc = not is_batch and ("$rpc/" in url or "clients6.google.com" in url)

        if is_batch:
            stats.batchexecute_calls += 1
            self._process_batchexecute(
                url, post_text, resp_text,
                local_nlm, local_gemini, local_gas, local_unknown, local_new,
            )
        elif is_grpc:
            stats.grpc_calls += 1
            self._process_grpc(url, local_new)

    # ──── Internal: batchexecute ───────────────────────────────────────────────

    def _process_batchexecute(
        self,
        url: str,
        post_text: str,
        resp_text: str,
        local_nlm: Set[str],
        local_gemini: Set[str],
        local_gas: Set[str],
        local_unknown: Set[str],
        local_new: Set[str],
    ) -> None:
        """Decode a batchexecute request/response pair and register rpcids.

        Args:
            url: Request URL (used to classify service).
            post_text: POST body (URL-encoded f.req=...).
            resp_text: Response body (may start with )]}').
            local_nlm: Per-file NLM rpcid accumulator.
            local_gemini: Per-file Gemini rpcid accumulator.
            local_gas: Per-file GAS rpcid accumulator.
            local_unknown: Per-file unknown rpcid accumulator.
            local_new: Per-file new-discovery accumulator.
        """
        reqs = self._be_decoder.decode_request(post_text, url)
        if not reqs:
            return

        resp: Optional[BatchResponse] = None
        if resp_text:
            try:
                resp = self._be_decoder.decode_response(resp_text)
            except Exception as exc:
                logger.debug("batchexecute response decode error: %s", exc)

        is_gas = "script.google.com" in url
        is_nlm = "notebooklm" in url
        is_gemini = "gemini.google.com" in url

        for req in reqs:
            rpcid = req.rpcid
            if not rpcid:
                continue

            if is_gas:
                local_gas.add(rpcid)
                if rpcid not in GAS_RPCIDS:
                    local_new.add(rpcid)
                # Register in registry under unknown_endpoints with a gas: prefix
                self._registry.register_unknown_endpoint(
                    f"gas:batchexecute:{rpcid}", "POST"
                )

            elif is_nlm:
                local_nlm.add(rpcid)
                name = NLM_RPCIDS.get(rpcid)
                is_new = self._registry.register_nlm_rpcid(rpcid, name)
                if is_new and rpcid not in NLM_RPCIDS:
                    local_new.add(rpcid)

            elif is_gemini:
                local_gemini.add(rpcid)
                name = GEMINI_RPCIDS.get(rpcid)
                is_new = self._registry.register_gemini_rpcid(rpcid, name)
                if is_new and rpcid not in GEMINI_RPCIDS:
                    local_new.add(rpcid)

            else:
                local_unknown.add(rpcid)
                self._registry.register_unknown_endpoint(
                    f"unknown:batchexecute:{rpcid}", "POST"
                )

            self._save_payload_example(rpcid, req, resp)

    # ──── Internal: gRPC-web ───────────────────────────────────────────────────

    def _process_grpc(self, url: str, local_new: Set[str]) -> None:
        """Extract the gRPC method name from a gRPC-web URL and register it.

        Args:
            url: The full gRPC-web request URL.
            local_new: Per-file new-discovery accumulator.
        """
        try:
            service, method = self._grpc_decoder.parse_url(url)
            if method and method != "unknown":
                is_new = self._registry.register_aistudio_method(method, service)
                if is_new:
                    local_new.add(f"{service}/{method}")
        except Exception as exc:
            logger.debug("gRPC URL parse error for %s: %s", url, exc)

    # ──── Internal: payload persistence ───────────────────────────────────────

    def _save_payload_example(
        self,
        rpcid: str,
        req: BatchRequest,
        resp: Optional[BatchResponse],
    ) -> None:
        """Persist the first-seen request/response payload for an rpcid.

        Does nothing if a payload for this rpcid has already been saved.

        Args:
            rpcid: The rpcid string.
            req: Decoded BatchRequest object.
            resp: Decoded BatchResponse (may be None).
        """
        if rpcid in self._payload_examples:
            return

        req_data: Dict[str, Any] = {
            "rpcid": rpcid,
            "service": req.service,
            "url": req.url,
            "payload_raw": req.payload_raw,
            "payload": req.payload,
        }

        resp_data: Optional[Dict[str, Any]] = None
        if resp is not None and resp.frames:
            frame = resp.frame_for(rpcid)
            if frame is not None:
                resp_data = {
                    "rpcid": frame.rpcid,
                    "data_raw": frame.data_raw,
                    "data": frame.data,
                    "sequence": frame.sequence,
                }

        self._payload_examples[rpcid] = {
            "request": req_data,
            **({"response": resp_data} if resp_data else {}),
        }

        try:
            req_path = self._payloads_dir / f"{rpcid}_request.json"
            req_path.write_text(
                json.dumps(req_data, indent=2, ensure_ascii=False, default=str),
                encoding="utf-8",
            )
            if resp_data is not None:
                resp_path = self._payloads_dir / f"{rpcid}_response.json"
                resp_path.write_text(
                    json.dumps(resp_data, indent=2, ensure_ascii=False, default=str),
                    encoding="utf-8",
                )
                logger.debug("Saved payload+response for rpcid %s", rpcid)
            else:
                logger.debug("Saved payload for rpcid %s (no response frame)", rpcid)
        except Exception as exc:
            logger.debug("Failed to write payload file for %s: %s", rpcid, exc)


# ──── CLI ──────────────────────────────────────────────────────────────────────

def _cli() -> None:
    """Entry point for ``python -m scripts.argus.har_scanner``."""
    logging.basicConfig(level=logging.INFO, format="%(levelname)-8s %(message)s")

    parser = argparse.ArgumentParser(
        description="ARGUS HAR scanner — populate endpoint registry from .har files",
    )
    parser.add_argument(
        "--dir",
        type=Path,
        default=HAR_DIR,
        help=f"Directory to scan (default: {HAR_DIR})",
    )
    parser.add_argument(
        "--report",
        action="store_true",
        help="Print the existing report without re-scanning",
    )
    args = parser.parse_args()

    scanner = HarScanner()

    if args.report:
        if REPORT_PATH.exists():
            data = json.loads(REPORT_PATH.read_text(encoding="utf-8"))
            print(json.dumps(data, indent=2))
        else:
            print("No report found at", REPORT_PATH)
            print("Run without --report to perform a scan first.")
        return

    stats = scanner.scan_directory(args.dir)
    scanner.save_report()

    print("\n=== HAR Scan Report ===")
    print(f"Files scanned      : {stats.files_scanned}")
    print(f"Total requests     : {stats.requests_total}")
    print(f"BatchExecute calls : {stats.batchexecute_calls}")
    print(f"gRPC-web calls     : {stats.grpc_calls}")
    print(f"NLM rpcids         : {stats.rpcids_nlm}")
    print(f"Gemini rpcids      : {stats.rpcids_gemini}")
    print(f"GAS rpcids         : {stats.rpcids_gas}")
    print(f"Unknown rpcids     : {stats.rpcids_unknown}")
    print(f"New discoveries    : {stats.new_discoveries}")
    print(f"Errors             : {stats.errors}")

    report = scanner.get_report()
    if report["new_discoveries"]:
        print(f"\nNew discoveries: {', '.join(report['new_discoveries'])}")

    print(f"\nReport saved to: {REPORT_PATH}")
    print(f"Payloads dir   : {PAYLOADS_DIR}")


if __name__ == "__main__":
    _cli()
