"""NotebookLM HAR Extractor — Extract notebook content from HAR files.

Ported from docs/NOTEBOOKLM_HAR_SDK.md into a proper module.
Extracts notebook metadata, sources, documents, notes, conversations,
and auth cookies from browser-captured HAR files.

Usage:
    from engine.nexus.har_extractor import HARExtractor
    extractor = HARExtractor()
    notebooks = extractor.extract("capture.har")
    extractor.ingest_to_nexus(notebooks[0], client)
"""
from __future__ import annotations

import base64
import json
import logging
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Set

logger = logging.getLogger(__name__)


# ──── Data Models ────

@dataclass
class NotebookData:
    """Extracted content from a single NotebookLM notebook."""

    notebook_id: str = ""
    notebook_name: str = ""
    summary: str = ""
    sources: List[Dict[str, Any]] = field(default_factory=list)
    documents: List[str] = field(default_factory=list)
    notes: List[str] = field(default_factory=list)
    conversations: List[str] = field(default_factory=list)
    cookies: Dict[str, str] = field(default_factory=dict)

    @property
    def stats(self) -> Dict[str, int]:
        """Compute extraction statistics."""
        return {
            "sources": len(self.sources),
            "documents": len(self.documents),
            "notes": len(self.notes),
            "conversations": len(self.conversations),
            "total_chars": (
                len(self.summary)
                + sum(len(d) for d in self.documents)
                + sum(len(n) for n in self.notes)
                + sum(len(c) for c in self.conversations)
            ),
        }

    def to_dict(self) -> Dict[str, Any]:
        """Serialize to dict for JSON export."""
        return {
            "notebook_id": self.notebook_id,
            "notebook_name": self.notebook_name,
            "name": self.notebook_name,
            "id": self.notebook_id,
            "summary": self.summary,
            "sources": self.sources,
            "documents": self.documents,
            "notes": self.notes,
            "conversations": self.conversations,
            "content": {
                "documents": self.documents,
                "notes": self.notes,
                "conversations": self.conversations,
            },
            "stats": self.stats,
        }


@dataclass
class IngestResult:
    """Result of ingesting notebook data into Nexus."""

    notebook_id: str
    entries_created: int = 0
    qa_pairs_created: int = 0
    errors: List[str] = field(default_factory=list)
    entry_ids: List[str] = field(default_factory=list)


# ──── Core Decode Functions ────

def _get_response_text(entry: Dict[str, Any]) -> str:
    """Decode HAR entry response, handling base64 encoding.

    Args:
        entry: A single HAR log entry.

    Returns:
        Decoded response text.
    """
    content = entry.get("response", {}).get("content", {})
    text = content.get("text", "")
    if content.get("encoding") == "base64" and text:
        try:
            text = base64.b64decode(text).decode("utf-8", errors="replace")
        except Exception:
            logger.debug("Failed to base64-decode entry", exc_info=True)
    return text


def _parse_batchexecute(raw: str) -> tuple[Optional[str], Any]:
    """Parse Google batchexecute response through all encoding layers.

    Handles: XSSI prefix -> length-prefixed chunks -> wrb.fr envelope -> inner JSON.

    Args:
        raw: Decoded response text.

    Returns:
        Tuple of (rpc_id, parsed_data) or (None, None) on failure.
    """
    body = raw.lstrip(")]}'\n")
    for line in body.split("\n"):
        line = line.strip()
        if line.startswith('[["wrb.fr"'):
            try:
                outer = json.loads(line)
                rpc_id = outer[0][1]
                inner_str = outer[0][2]
                inner = json.loads(inner_str) if isinstance(inner_str, str) else inner_str
                return rpc_id, inner
            except (json.JSONDecodeError, IndexError, TypeError):
                continue
    return None, None


def _unwrap(entry: Dict[str, Any]) -> tuple[Optional[str], Any]:
    """Full HAR entry -> (rpc_id, data) pipeline.

    Args:
        entry: HAR log entry dict.

    Returns:
        Tuple of (rpc_id, parsed_inner_data).
    """
    return _parse_batchexecute(_get_response_text(entry))


# ──── Content Extraction Helpers ────

def _extract_strings(obj: Any, min_len: int = 80) -> List[str]:
    """Recursively extract meaningful text strings from nested data.

    Args:
        obj: Nested list/dict/str structure from parsed response.
        min_len: Minimum string length to include.

    Returns:
        List of extracted text strings.
    """
    results: List[str] = []
    if isinstance(obj, str):
        s = obj.strip()
        if len(s) >= min_len and not re.match(r"^[a-f0-9-]{30,}$", s):
            results.append(s)
    elif isinstance(obj, list):
        for item in obj:
            results.extend(_extract_strings(item, min_len))
    elif isinstance(obj, dict):
        for v in obj.values():
            results.extend(_extract_strings(v, min_len))
    return results


def _dedup(texts: List[str], key_len: int = 120) -> List[str]:
    """Deduplicate text blocks by prefix.

    Args:
        texts: List of text strings.
        key_len: Number of prefix characters to use as dedup key.

    Returns:
        Deduplicated list preserving order.
    """
    seen: Set[str] = set()
    result: List[str] = []
    for t in texts:
        key = t[:key_len]
        if key not in seen:
            seen.add(key)
            result.append(t)
    return result


def _extract_sources(data: Any) -> tuple[str, List[Dict[str, Any]]]:
    """Extract source listing from wXbhsf response.

    Args:
        data: Parsed inner data from wXbhsf RPC.

    Returns:
        Tuple of (notebook_name, list_of_source_dicts).
    """
    notebook_name = ""
    sources: List[Dict[str, Any]] = []

    try:
        nb_core = data[0][0]
        notebook_name = nb_core[0] if isinstance(nb_core[0], str) else ""
        src_list = nb_core[1] if len(nb_core) > 1 and isinstance(nb_core[1], list) else []

        for src in src_list:
            if not isinstance(src, list) or len(src) < 2:
                continue
            try:
                uuid = src[0][0] if isinstance(src[0], list) and src[0] else ""
                title = src[1] if isinstance(src[1], str) else ""
                url = ""
                word_count = 0
                source_type = None

                if len(src) > 2 and isinstance(src[2], list):
                    meta = src[2]
                    word_count = meta[1] if len(meta) > 1 and isinstance(meta[1], int) else 0
                    source_type = meta[6] if len(meta) > 6 else None
                    if len(meta) > 7 and isinstance(meta[7], list) and meta[7]:
                        url = meta[7][0] if isinstance(meta[7][0], str) else ""

                sources.append({
                    "id": uuid,
                    "title": title,
                    "url": url,
                    "word_count": word_count,
                    "source_type": source_type,
                })
            except (IndexError, TypeError):
                logger.debug("Failed to parse source entry", exc_info=True)
                continue
    except (IndexError, TypeError) as e:
        logger.warning("Failed to parse sources: %s", e)

    return notebook_name, sources


# ──── Cookie Extraction ────

_NLM_COOKIE_NAMES = {
    "SID", "HSID", "SSID", "APISID", "SAPISID",
    "__Secure-1PSID", "__Secure-3PSID",
    "__Secure-1PAPISID", "__Secure-3PAPISID",
    "NID", "CONSENT",
}


def _extract_cookies_from_entries(entries: List[Dict[str, Any]]) -> Dict[str, str]:
    """Extract Google auth cookies from HAR entries.

    Args:
        entries: HAR log entries list.

    Returns:
        Dict of cookie_name -> cookie_value for NLM-relevant cookies.
    """
    cookies: Dict[str, str] = {}
    for entry in entries:
        url = entry.get("request", {}).get("url", "")
        if "notebooklm.google.com" not in url and "google.com" not in url:
            continue

        for cookie in entry.get("request", {}).get("cookies", []):
            name = cookie.get("name", "")
            value = cookie.get("value", "")
            if name in _NLM_COOKIE_NAMES and value and len(value) > 10:
                cookies[name] = value

        for header in entry.get("request", {}).get("headers", []):
            if header.get("name", "").lower() == "cookie":
                for part in header.get("value", "").split(";"):
                    part = part.strip()
                    if "=" in part:
                        k, v = part.split("=", 1)
                        if k.strip() in _NLM_COOKIE_NAMES and len(v.strip()) > 10:
                            cookies[k.strip()] = v.strip()
    return cookies


# ──── Main Extractor Class ────

class HARExtractor:
    """Extracts NotebookLM content from browser HAR files.

    Usage:
        extractor = HARExtractor()
        notebooks = extractor.extract("path/to/capture.har")
        for nb in notebooks:
            print(nb.notebook_name, nb.stats)
    """

    def extract(self, har_path: str) -> List[NotebookData]:
        """Extract all notebook data from a HAR file.

        Args:
            har_path: Path to the .har file.

        Returns:
            List of NotebookData objects (one per notebook found).
        """
        path = Path(har_path)
        if not path.exists():
            raise FileNotFoundError(f"HAR file not found: {har_path}")

        with open(path, "r", encoding="utf-8", errors="replace") as f:
            har = json.load(f)

        entries = har.get("log", {}).get("entries", [])
        if not entries:
            logger.warning("No entries found in HAR file")
            return []

        cookies = _extract_cookies_from_entries(entries)

        # Index batchexecute entries by RPC ID
        rpc_entries: Dict[str, List[int]] = {}
        for i, e in enumerate(entries):
            url = e.get("request", {}).get("url", "")
            if "batchexecute" not in url and "GenerateFreeForm" not in url:
                continue

            rpc_id, _ = _unwrap(e)
            if rpc_id:
                rpc_entries.setdefault(rpc_id, []).append(i)
            elif "GenerateFreeForm" in url:
                rpc_entries.setdefault("GenerateFreeForm", []).append(i)

        logger.info("Found RPC endpoints: %s", {k: len(v) for k, v in rpc_entries.items()})

        nb = NotebookData(cookies=cookies)

        # Extract notebook ID from page URL
        for e in entries:
            match = re.search(r"/notebook/([a-f0-9-]{36})", e.get("request", {}).get("url", ""))
            if match:
                nb.notebook_id = match.group(1)
                break

        # Sources (wXbhsf)
        if "wXbhsf" in rpc_entries:
            _, data = _unwrap(entries[rpc_entries["wXbhsf"][0]])
            if data:
                nb.notebook_name, nb.sources = _extract_sources(data)

        # Summary (VfAZjd)
        if "VfAZjd" in rpc_entries:
            _, data = _unwrap(entries[rpc_entries["VfAZjd"][0]])
            if data:
                nb.summary = "\n\n".join(_extract_strings(data, 50))

        # Full source content (e3bVqc)
        if "e3bVqc" in rpc_entries:
            _, data = _unwrap(entries[rpc_entries["e3bVqc"][0]])
            if data:
                docs = _dedup(_extract_strings(data, 100))
                nb.documents = [d for d in docs if len(d) > 200]

        # Notes (gArtLc)
        if "gArtLc" in rpc_entries:
            for idx in rpc_entries["gArtLc"]:
                _, data = _unwrap(entries[idx])
                if data:
                    notes = _dedup(_extract_strings(data, 80))
                    nb.notes.extend([n for n in notes if len(n) > 100])

        # Conversations (cFji9 + khqZz)
        for rpc in ["cFji9", "khqZz"]:
            if rpc in rpc_entries:
                for idx in rpc_entries[rpc]:
                    _, data = _unwrap(entries[idx])
                    if data:
                        convos = _extract_strings(data, 80)
                        nb.conversations.extend([c for c in convos if len(c) > 100])
        nb.conversations = _dedup(nb.conversations)

        # Streaming reports (GenerateFreeForm)
        if "GenerateFreeForm" in rpc_entries:
            for idx in rpc_entries["GenerateFreeForm"]:
                text = _get_response_text(entries[idx])
                body = text.lstrip(")]}'\n")
                for line in body.split("\n"):
                    line = line.strip()
                    if line.startswith('[["wrb.fr"'):
                        try:
                            outer = json.loads(line)
                            inner_str = outer[0][2]
                            if inner_str:
                                inner = json.loads(inner_str)
                                for s in _extract_strings(inner, 100):
                                    nb.documents.append(s)
                        except (json.JSONDecodeError, IndexError, TypeError):
                            logger.debug("Failed to parse GenerateFreeForm entry", exc_info=True)
            nb.documents = _dedup(nb.documents)

        logger.info(
            "Extracted '%s': %d sources, %d docs, %d notes, %d conversations (%s chars)",
            nb.notebook_name, nb.stats["sources"], nb.stats["documents"],
            nb.stats["notes"], nb.stats["conversations"],
            f"{nb.stats['total_chars']:,}",
        )

        return [nb]

    def extract_cookies(self, har_path: str) -> Dict[str, str]:
        """Extract only auth cookies from a HAR file (fast, no content parsing).

        Args:
            har_path: Path to the .har file.

        Returns:
            Dict of cookie_name -> cookie_value.
        """
        path = Path(har_path)
        if not path.exists():
            raise FileNotFoundError(f"HAR file not found: {har_path}")

        with open(path, "r", encoding="utf-8", errors="replace") as f:
            har = json.load(f)

        entries = har.get("log", {}).get("entries", [])
        return _extract_cookies_from_entries(entries)

    def preview(self, har_path: str) -> Dict[str, Any]:
        """Quick preview of HAR contents without full extraction.

        Args:
            har_path: Path to the .har file.

        Returns:
            Dict with summary info: notebook_id, rpc_endpoints found, entry count.
        """
        path = Path(har_path)
        if not path.exists():
            raise FileNotFoundError(f"HAR file not found: {har_path}")

        with open(path, "r", encoding="utf-8", errors="replace") as f:
            har = json.load(f)

        entries = har.get("log", {}).get("entries", [])
        notebook_ids: Set[str] = set()
        rpc_counts: Dict[str, int] = {}

        for e in entries:
            url = e.get("request", {}).get("url", "")
            match = re.search(r"/notebook/([a-f0-9-]{36})", url)
            if match:
                notebook_ids.add(match.group(1))

            if "batchexecute" in url or "GenerateFreeForm" in url:
                rpc_id, _ = _unwrap(e)
                if rpc_id:
                    rpc_counts[rpc_id] = rpc_counts.get(rpc_id, 0) + 1
                elif "GenerateFreeForm" in url:
                    rpc_counts["GenerateFreeForm"] = rpc_counts.get("GenerateFreeForm", 0) + 1

        has_cookies = bool(_extract_cookies_from_entries(entries))

        return {
            "har_file": str(path.name),
            "total_entries": len(entries),
            "notebook_ids": list(notebook_ids),
            "rpc_endpoints": rpc_counts,
            "has_auth_cookies": has_cookies,
            "can_extract": bool(rpc_counts),
        }

    def save_notebook(self, data: NotebookData, output_dir: str = ".") -> str:
        """Save extracted notebook data to JSON file.

        Args:
            data: Extracted NotebookData.
            output_dir: Directory for output file.

        Returns:
            Path to the saved JSON file.
        """
        out_dir = Path(output_dir)
        out_dir.mkdir(parents=True, exist_ok=True)

        safe_name = re.sub(r"[^\w\s-]", "", data.notebook_name or "notebook").strip()
        safe_name = re.sub(r"\s+", "_", safe_name).lower() or "notebook"
        filename = f"{safe_name}_{data.notebook_id[:8]}.json" if data.notebook_id else f"{safe_name}.json"
        out_path = out_dir / filename

        with open(out_path, "w", encoding="utf-8") as f:
            json.dump(data.to_dict(), f, indent=2, ensure_ascii=False)

        logger.info("Saved notebook to %s", out_path)
        return str(out_path)

    def ingest_to_nexus(
        self,
        data: NotebookData,
        client: Any,
        items: Optional[List[str]] = None,
    ) -> IngestResult:
        """Ingest extracted notebook content into Nexus KMS.

        Args:
            data: Extracted NotebookData to ingest.
            client: NexusClient instance.
            items: Optional list of item types to ingest.
                   Defaults to all: ["sources", "documents", "notes", "conversations"].

        Returns:
            IngestResult with counts and any errors.
        """
        items = items or ["sources", "documents", "notes", "conversations"]
        result = IngestResult(notebook_id=data.notebook_id)
        nb_tag = data.notebook_name or data.notebook_id[:8]

        # Sources index
        if "sources" in items and data.sources:
            try:
                content = "\n".join(
                    f"- {s.get('title', 'Untitled')} ({s.get('word_count', 0)} words)"
                    + (f" — {s['url']}" if s.get("url") else "")
                    for s in data.sources
                )
                entry_id = client.add_entry(
                    title=f"NLM Sources: {nb_tag}",
                    content=content,
                    content_type="document",
                    category="nlm",
                    tags=["notebooklm", "sources", nb_tag],
                )
                if entry_id:
                    result.entries_created += 1
                    result.entry_ids.append(entry_id)
            except Exception as e:
                result.errors.append(f"sources: {e}")

        # Documents
        if "documents" in items:
            for i, doc in enumerate(data.documents):
                try:
                    entry_id = client.add_entry(
                        title=f"NLM Doc {i + 1}/{len(data.documents)}: {nb_tag}",
                        content=doc,
                        content_type="document",
                        category="nlm",
                        tags=["notebooklm", "document", nb_tag],
                    )
                    if entry_id:
                        result.entries_created += 1
                        result.entry_ids.append(entry_id)
                except Exception as e:
                    result.errors.append(f"doc {i}: {e}")

        # Notes
        if "notes" in items:
            for i, note in enumerate(data.notes):
                try:
                    entry_id = client.add_entry(
                        title=f"NLM Note {i + 1}/{len(data.notes)}: {nb_tag}",
                        content=note,
                        content_type="note",
                        category="nlm",
                        tags=["notebooklm", "note", nb_tag],
                    )
                    if entry_id:
                        result.entries_created += 1
                        result.entry_ids.append(entry_id)
                except Exception as e:
                    result.errors.append(f"note {i}: {e}")

        # Conversations as Q&A pairs
        if "conversations" in items:
            for i, convo in enumerate(data.conversations):
                try:
                    entry_id = client.add_entry(
                        title=f"NLM Conversation {i + 1}/{len(data.conversations)}: {nb_tag}",
                        content=convo,
                        content_type="note",
                        category="nlm",
                        tags=["notebooklm", "conversation", nb_tag],
                    )
                    if entry_id:
                        result.entries_created += 1
                        result.entry_ids.append(entry_id)
                except Exception as e:
                    result.errors.append(f"convo {i}: {e}")

        logger.info(
            "Ingested '%s': %d entries, %d errors",
            nb_tag, result.entries_created, len(result.errors),
        )
        return result
