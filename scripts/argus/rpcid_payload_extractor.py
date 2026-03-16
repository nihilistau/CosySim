"""ARGUS rpcid Payload Extractor — extracts f.req POST bodies from HAR files.

Parses batchexecute POST data to decode rpcid operation semantics by
extracting URL-encoded f.req parameters, source-path context, and
response previews. Includes heuristic operation inference.

Example usage::

    from scripts.argus.rpcid_payload_extractor import PayloadExtractor

    extractor = PayloadExtractor()
    results = extractor.extract_file(Path("capture.har"), ["DYBcR", "ozz5Z"])
"""
from __future__ import annotations

import json
import logging
import re
import urllib.parse
from collections import defaultdict
from pathlib import Path
from typing import Any, Dict, List, Optional, Set

logger = logging.getLogger(__name__)

__all__ = [
    "PayloadExtractor",
    "extract_postdata",
    "infer_operation",
]

GOLDMINE = Path(r"artifacts\argus\har\users_dump_folder\GoldMine")


class PayloadExtractor:
    """High-level interface for extracting rpcid payloads from HAR files.

    Wraps the streaming extraction functions into a file/directory-scanning
    API suitable for MCP skill consumption.
    """

    def __init__(self, chunk_size: int = 100 * 1024 * 1024) -> None:
        self.chunk_size = chunk_size

    def extract_file(
        self, har_path: Path, target_rpcids: Optional[List[str]] = None
    ) -> Dict[str, Any]:
        """Extract payloads from a single HAR file.

        Args:
            har_path: Path to the HAR file.
            target_rpcids: Optional list of rpcids to extract. None means all.

        Returns:
            Dict with rpcid_postdata and inferences.
        """
        results = extract_postdata(
            har_path, target_rpcids=target_rpcids, chunk_size=self.chunk_size
        )
        inferences = {}
        for rpcid, entries in results.items():
            inferences[rpcid] = infer_operation(rpcid, entries)

        return {
            "rpcid_postdata": results,
            "inferences": inferences,
            "files_scanned": 1,
        }

    def extract_directory(
        self,
        directory: Path,
        target_rpcids: Optional[List[str]] = None,
        pattern: str = "*.har",
    ) -> Dict[str, Any]:
        """Extract payloads across all HAR files in a directory.

        Args:
            directory: Directory containing HAR files.
            target_rpcids: Optional list of rpcids to extract. None means all.
            pattern: Glob pattern for HAR files.

        Returns:
            Combined postdata and inferences across all files.
        """
        directory = Path(directory)
        if not directory.exists():
            logger.warning("HAR directory does not exist: %s", directory)
            return {"rpcid_postdata": {}, "inferences": {}, "files_scanned": 0}

        combined_postdata: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
        files_scanned = 0

        for har_path in sorted(directory.rglob(pattern)):
            logger.info("Extracting payloads from %s", har_path.name)
            try:
                results = extract_postdata(
                    har_path, target_rpcids=target_rpcids, chunk_size=self.chunk_size
                )
                for rpcid, entries in results.items():
                    combined_postdata[rpcid].extend(entries)
                files_scanned += 1
            except Exception:
                logger.exception("Failed to extract payloads from %s", har_path)

        inferences = {}
        for rpcid, entries in combined_postdata.items():
            inferences[rpcid] = infer_operation(rpcid, entries)

        return {
            "rpcid_postdata": dict(combined_postdata),
            "inferences": inferences,
            "files_scanned": files_scanned,
        }


def extract_postdata(
    har_path: Path,
    target_rpcids: Optional[List[str]] = None,
    chunk_size: int = 100 * 1024 * 1024,
) -> Dict[str, List[Dict[str, Any]]]:
    """Parse HAR entries to find POST bodies for batchexecute requests.

    Args:
        har_path: Path to the HAR file.
        target_rpcids: Optional list of rpcids to extract. None means all.
        chunk_size: Size of each read chunk in bytes.

    Returns:
        Dict mapping rpcid -> list of extracted postdata entries.
    """
    results: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
    target_set = set(target_rpcids) if target_rpcids else None
    file_size = har_path.stat().st_size
    overlap = 200000

    entry_url_pat = re.compile(
        r'"url"\s*:\s*"(https://[^"]*batchexecute\?rpcids=([A-Za-z0-9_]+)[^"]*)"'
    )
    freq_content_pat = re.compile(r'f\.req=([^&"]{10,8000})')
    source_path_pat = re.compile(r'source-path=([^&"]+)')

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

            for m in entry_url_pat.finditer(data):
                url = m.group(1)
                rpcid = m.group(2)

                if target_set and rpcid not in target_set:
                    continue

                if len(results[rpcid]) >= 2:
                    continue

                sp_match = source_path_pat.search(url)
                source_path = urllib.parse.unquote(sp_match.group(1)) if sp_match else "unknown"

                pos = m.start()
                context_start = max(0, pos - 50000)
                context_end = min(len(data), pos + 50000)
                context = data[context_start:context_end]

                freq_match = freq_content_pat.search(context)
                freq_raw = ""
                freq_decoded = ""
                if freq_match:
                    freq_raw = freq_match.group(1)[:3000]
                    try:
                        freq_decoded = urllib.parse.unquote(freq_raw[:3000])
                    except Exception:
                        freq_decoded = freq_raw[:1000]

                resp_start = context.find('"response"', pos - context_start)
                resp_content = ""
                if resp_start > 0:
                    resp_text_match = re.search(
                        r'"text"\s*:\s*"([^"]{10,2000})"',
                        context[resp_start:resp_start + 5000],
                    )
                    if resp_text_match:
                        resp_content = resp_text_match.group(1)[:500]

                results[rpcid].append({
                    "source_path": source_path,
                    "freq_raw_len": len(freq_raw),
                    "freq_decoded": freq_decoded[:1000],
                    "response_preview": resp_content[:300],
                })

            pct = int(processed / file_size * 100)
            if pct % 25 == 0:
                logger.debug("%s: %d%% (%d MB)...", har_path.name, pct, processed // (1024 * 1024))

    return dict(results)


def infer_operation(rpcid: str, entries: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Infer what operation the rpcid performs from context clues.

    Args:
        rpcid: The rpcid identifier.
        entries: List of postdata entries with source_path and freq_decoded.

    Returns:
        Dict with rpcid, source_paths, categories, payload_hints,
        and sample_count.
    """
    source_paths: Set[str] = set()
    for e in entries:
        source_paths.add(e["source_path"])

    category_map = {
        "/app": "core_chat",
        "/gems/view": "gems_listing",
        "/gem/storybook": "gem_storybook",
        "/mystuff": "user_content",
        "/saved-info": "saved_info",
        "/_gemini": "gemini_integration",
    }

    categories: Set[str] = set()
    for sp in source_paths:
        for pattern, cat in category_map.items():
            if pattern in sp:
                categories.add(cat)

    payload_hints: List[str] = []
    for e in entries:
        decoded = e.get("freq_decoded", "")
        if decoded:
            if "null" in decoded[:100]:
                payload_hints.append("standard_batchexecute")
            if "conversation" in decoded.lower():
                payload_hints.append("conversation_related")
            if "model" in decoded.lower():
                payload_hints.append("model_related")
            if "gem" in decoded.lower():
                payload_hints.append("gem_related")

    return {
        "rpcid": rpcid,
        "source_paths": sorted(source_paths),
        "categories": sorted(categories),
        "payload_hints": list(set(payload_hints)),
        "sample_count": len(entries),
    }


def main() -> None:
    """Extract POST data for rpcids from the default goldmine HAR file."""
    har_file = GOLDMINE / "gemini.google.com-NEWEST.har"
    if not har_file.exists():
        logger.error("HAR file not found: %s", har_file)
        return

    results = extract_postdata(har_file)

    inferences = {}
    for rpcid in sorted(results.keys()):
        entries = results[rpcid]
        inferences[rpcid] = infer_operation(rpcid, entries)

    output = {
        "rpcid_postdata": results,
        "inferences": inferences,
    }

    print(json.dumps(inferences, indent=2))

    out_path = GOLDMINE / "rpcid_operations.json"
    with open(out_path, "w") as f:
        json.dump(output, f, indent=2, default=str)
    logger.info("Detailed results saved to %s", out_path)


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    main()
