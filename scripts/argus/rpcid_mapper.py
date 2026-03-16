"""ARGUS rpcid Mapper — maps rpcids to batchexecute services from HAR context.

Scans HAR files for batchexecute URL entries to build a mapping of rpcid
identifiers to their parent Google service (BardChatUi, LabsTailwindUi,
AppsMakerFrontendUi, Opal, etc.), along with request/response context.

Example usage::

    from scripts.argus.rpcid_mapper import RpcidMapper

    mapper = RpcidMapper()
    mapping = mapper.map_directory(Path("artifacts/argus/har"))
"""
from __future__ import annotations

import json
import logging
import re
import sys
from collections import defaultdict
from pathlib import Path
from typing import Any, Dict, List, Optional, Set

logger = logging.getLogger(__name__)

__all__ = [
    "RpcidMapper",
    "extract_rpcid_context",
]

GOLDMINE = Path(r"artifacts\argus\har\users_dump_folder\GoldMine")

# Known batchexecute service identifiers
SERVICES: Dict[str, str] = {
    "BardChatUi": "gemini",
    "BardFrontendService": "gemini",
    "LabsTailwindUi": "notebooklm",
    "AppsMakerFrontendUi": "aistudio",
    "Opal": "opal",
}


class RpcidMapper:
    """High-level interface for mapping rpcids to batchexecute services.

    Wraps the streaming context extraction into a file/directory-scanning
    API suitable for MCP skill consumption.
    """

    def __init__(self, chunk_size: int = 100 * 1024 * 1024) -> None:
        self.chunk_size = chunk_size

    def map_file(self, har_path: Path) -> Dict[str, Any]:
        """Map rpcids in a single HAR file to their services.

        Args:
            har_path: Path to the HAR file.

        Returns:
            Dict mapping service names to lists of rpcids,
            plus per-rpcid context entries.
        """
        rpcid_data, service_rpcid_map = extract_rpcid_context(
            har_path, chunk_size=self.chunk_size
        )
        return {
            "service_rpcid_map": {k: sorted(v) for k, v in service_rpcid_map.items()},
            "rpcid_context": {k: v for k, v in rpcid_data.items()},
            "files_scanned": 1,
        }

    def map_directory(self, directory: Path, pattern: str = "*.har") -> Dict[str, Any]:
        """Map rpcids across all HAR files in a directory.

        Args:
            directory: Directory containing HAR files.
            pattern: Glob pattern for HAR files.

        Returns:
            Combined service-to-rpcid mapping across all files.
        """
        directory = Path(directory)
        if not directory.exists():
            logger.warning("HAR directory does not exist: %s", directory)
            return {"service_rpcid_map": {}, "rpcid_context": {}, "files_scanned": 0}

        combined_services: Dict[str, Set[str]] = defaultdict(set)
        combined_context: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
        files_scanned = 0

        for har_path in sorted(directory.rglob(pattern)):
            logger.info("Mapping rpcids in %s", har_path.name)
            try:
                rpcid_data, service_rpcid_map = extract_rpcid_context(
                    har_path, chunk_size=self.chunk_size
                )
                for svc, rpcids in service_rpcid_map.items():
                    combined_services[svc].update(rpcids)
                for rpcid, entries in rpcid_data.items():
                    combined_context[rpcid].extend(entries)
                files_scanned += 1
            except Exception:
                logger.exception("Failed to map rpcids in %s", har_path)

        return {
            "service_rpcid_map": {k: sorted(v) for k, v in combined_services.items()},
            "rpcid_context": dict(combined_context),
            "files_scanned": files_scanned,
        }


def extract_rpcid_context(
    har_path: Path,
    target_rpcids: Optional[Set[str]] = None,
    chunk_size: int = 100 * 1024 * 1024,
) -> tuple[Dict[str, List[Dict[str, Any]]], Dict[str, Set[str]]]:
    """Stream through HAR looking for batchexecute entries with rpcids.

    Args:
        har_path: Path to the HAR file.
        target_rpcids: Optional set of rpcids to collect context for.
            If None, collects context for all discovered rpcids.
        chunk_size: Size of each read chunk in bytes.

    Returns:
        Tuple of (rpcid_data, service_rpcid_map) where rpcid_data maps
        rpcid -> list of context dicts, and service_rpcid_map maps
        service -> set of rpcids.
    """
    rpcid_data: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
    service_rpcid_map: Dict[str, Set[str]] = defaultdict(set)

    file_size = har_path.stat().st_size
    logger.debug("Scanning %s (%d MB)...", har_path.name, file_size // (1024 * 1024))

    overlap = 50000

    url_pat = re.compile(r'"url"\s*:\s*"(https?://[^"]*rpcids=([A-Za-z0-9_,]+)[^"]*)"')
    service_pat = re.compile(r'/_/([A-Za-z]+)/data/batchexecute')
    freq_pat = re.compile(r'"f\.req"\s*:\s*"([^"]{0,2000})')
    text_pat = re.compile(r'"text"\s*:\s*"([^"]{0,5000})')

    processed = 0
    with open(har_path, "r", encoding="utf-8", errors="replace") as f:
        prev_tail = ""
        while True:
            chunk = f.read(chunk_size)
            if not chunk:
                break
            processed += len(chunk)

            data = prev_tail + chunk
            prev_tail = chunk[-overlap:] if len(chunk) > overlap else chunk

            for m in url_pat.finditer(data):
                url = m.group(1)
                rpcids_str = m.group(2)
                rpcids = rpcids_str.split(",") if "," in rpcids_str else [rpcids_str]

                svc_match = service_pat.search(url)
                service = svc_match.group(1) if svc_match else "unknown"

                for rpcid in rpcids:
                    rpcid = rpcid.strip()
                    service_rpcid_map[service].add(rpcid)

                    collect = target_rpcids is None or rpcid in target_rpcids
                    if collect and len(rpcid_data[rpcid]) < 3:
                        pos = m.start()
                        context_start = max(0, pos - 5000)
                        context_end = min(len(data), pos + 10000)
                        context = data[context_start:context_end]

                        freq_match = freq_pat.search(context)
                        freq_content = freq_match.group(1)[:500] if freq_match else ""

                        resp_matches = text_pat.findall(context)
                        resp_preview = resp_matches[0][:300] if resp_matches else ""

                        rpcid_data[rpcid].append({
                            "service": service,
                            "url": url[:200],
                            "freq_preview": freq_content[:300],
                            "response_preview": resp_preview[:300],
                        })

            pct = int(processed / file_size * 100)
            if pct % 20 == 0:
                logger.debug("%s: %d%% (%d MB)...", har_path.name, pct, processed // (1024 * 1024))

    return dict(rpcid_data), dict(service_rpcid_map)


def main() -> None:
    """Map rpcids from the default goldmine HAR file."""
    har_file = GOLDMINE / "gemini.google.com-NEWEST.har"
    if not har_file.exists():
        logger.error("HAR file not found: %s", har_file)
        return

    rpcid_data, service_rpcid_map = extract_rpcid_context(har_file)

    print(json.dumps({
        "service_rpcid_map": {k: sorted(v) for k, v in service_rpcid_map.items()},
        "rpcid_context_count": {k: len(v) for k, v in rpcid_data.items()},
    }, indent=2))

    out_path = GOLDMINE / "rpcid_mapping.json"
    output = {
        "service_rpcid_map": {k: sorted(v) for k, v in service_rpcid_map.items()},
        "rpcid_context": {k: v for k, v in rpcid_data.items()},
    }
    with open(out_path, "w") as f:
        json.dump(output, f, indent=2, default=str)
    logger.info("Full mapping saved to %s", out_path)


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    main()
