"""NLM archive operations — download, export, document generation, and user account."""
from __future__ import annotations

import json
import logging
import os
import re
import time
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from engine.mcp.nlm_rpc_constants import (
    RPC_GENERATE_DOC, RPC_GET_THREAD_IDS, RPC_LIST_NOTEBOOKS,
    RPC_LIST_SOURCES, RPC_MIND_MAP, RPC_NOTEBOOK_CONTENT,
    RPC_READ_THREAD, RPC_SAVE_REPORT, RPC_USER_PLAN, RPC_USER_QUOTA,
    RESP_LEN_DEFAULT, RESP_LEN_LONGER, RESP_LEN_SHORTER,
    DOC_TYPE_BRIEF, DOC_TYPE_NOTE, _WRITE_CONFIG,
)
from engine.mcp.nlm_auth import _load_cookies, _cookies_header, _sapisid_hash
from engine.mcp.nlm_transport import (
    _batchexecute, _build_headers, _extract_strings, _dedup, _extract_sources,
)
from engine.mcp.nlm_operations import read_source

logger = logging.getLogger(__name__)

_PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent


# ════════════════════════════════════════════════════════════════════════════
# DOWNLOAD & ARCHIVE OPERATIONS
#
# High-level operations that combine multiple RPCs to produce complete exports.
#
#   download_all_sources()   — fetch full text of all sources (tr032e loop)
#   export_notebook()        — full notebook archive (summary + sources + notes
#                              + threads + mindmap) in a single structured dict
#   export_all_notebooks()   — export every notebook for the authenticated user
#
# These are the primary integration points for Nexus ingestion and offline
# analysis.  Source content reading is rate-limited per the global limiter.
# ════════════════════════════════════════════════════════════════════════════

def download_all_sources(
    notebook_id: str,
    cookies: Dict[str, str],
    source_ids: Optional[List[str]] = None,
) -> List[Dict[str, Any]]:
    """Download the full text content of all sources in a notebook (tr032e RPC).

    Workflow:
      1. If ``source_ids`` is None, fetch the source list via wXbhsf to get
         all source UUIDs and their metadata (title, url, source_type).
      2. Call ``read_source()`` (tr032e) for each source UUID individually.
         Each call respects the rate limiter (1.5s default gap).
      3. Return a combined list with both metadata and full text content.

    Use this to extract all NLM source content into Nexus or local storage
    for offline analysis, fine-tuning data collection, or archival.

    Performance note: Large notebooks with many sources will be slow due to
    the rate limiter.  A 20-source notebook takes ~30s minimum at 1.5s/call.

    Args:
        notebook_id: UUID of the target notebook.
        cookies:     Google auth cookies.
        source_ids:  Optional list of specific source UUIDs to read. If None,
                     reads ALL sources in the notebook.

    Returns:
        List of dicts: [{source_id, title, url, source_type, word_count, content, error}, ...]
        where ``content`` is the full markdown text of the source.
        ``error`` is present (and non-None) only if tr032e failed for that source.
    """
    if source_ids is None:
        args = json.dumps([None, 1, None, [2]])
        _, data = _batchexecute(RPC_LIST_SOURCES, args, cookies, notebook_id)
        _, sources = _extract_sources(data) if data and not isinstance(data, dict) else ("", [])
        source_ids = [s["id"] for s in sources if s.get("id")]
        source_meta = {s["id"]: s for s in sources if s.get("id")}
    else:
        source_meta = {}

    results = []
    for sid in source_ids:
        meta = source_meta.get(sid, {"id": sid, "title": "", "url": ""})
        content_result = read_source(sid, cookies)
        results.append({
            "source_id": sid,
            "title": meta.get("title", ""),
            "url": meta.get("url", ""),
            "source_type": meta.get("source_type"),
            "word_count": content_result.get("word_count", 0),
            "content": content_result.get("content", ""),
            "error": content_result.get("error"),
        })
    return results


def export_notebook(
    notebook_id: str,
    cookies: Dict[str, str],
    include_source_content: bool = True,
    include_threads: bool = True,
) -> Dict[str, Any]:
    """Export a complete notebook archive with all available data.

    Makes the following RPC calls in sequence (each rate-limited):
      1. VfAZjd  (AI_SUMMARY)     — notebook summary text
      2. wXbhsf  (LIST_SOURCES)   — source metadata list
      3. tr032e  (READ_SOURCE)    — full text per source (if include_source_content)
      4. gArtLc  (LIST_ARTIFACTS) — notes and saved artifacts
      5. hPTbtc  (GET_THREAD_IDS) — conversation thread UUIDs (if include_threads)
      6. khqZz   (READ_THREAD)    — messages per thread (if include_threads)
      7. cFji9   (MIND_MAP)       — D3 mind map JSON structure

    The resulting archive dict is self-contained and suitable for:
      - Storage in Nexus as a knowledge entry
      - Offline analysis without NLM access
      - Comparison between notebook versions
      - Fine-tuning dataset construction

    Performance: With include_source_content=True, this makes (2 + N + 3 + T)
    API calls where N = source count and T = thread count.  At 1.5s/call, a
    notebook with 10 sources and 5 threads takes ~30s minimum.

    Args:
        notebook_id:           UUID of the target notebook.
        cookies:               Google auth cookies.
        include_source_content: If True, read full text of each source via
                               tr032e (slow but complete). False = metadata only.
        include_threads:       If True, fetch and read all conversation threads.

    Returns:
        Dict with keys: notebook_id, notebook_name, summary, sources,
        notes, threads, mindmap, stats (counts + total_source_words), exported_at.
    """
    import datetime
    archive: Dict[str, Any] = {
        "notebook_id": notebook_id,
        "exported_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
    }

    # Summary
    _, data = _batchexecute(RPC_NOTEBOOK_CONTENT, json.dumps([notebook_id, [2]]), cookies, notebook_id)
    archive["summary"] = "\n\n".join(_extract_strings(data, 50)) if data and not isinstance(data, dict) else ""

    # Sources with optional full content
    _, data = _batchexecute(RPC_LIST_SOURCES, json.dumps([None, 1, None, [2]]), cookies, notebook_id)
    notebook_name, sources = _extract_sources(data) if data and not isinstance(data, dict) else ("", [])
    archive["notebook_name"] = notebook_name

    if include_source_content:
        sources_with_content = []
        for src in sources:
            if src.get("id"):
                content_result = read_source(src["id"], cookies)
                src["content"] = content_result.get("content", "")
                src["content_word_count"] = content_result.get("word_count", 0)
            sources_with_content.append(src)
        archive["sources"] = sources_with_content
    else:
        archive["sources"] = sources

    # Notes / artifacts
    _, data = _batchexecute(
        "gArtLc",
        json.dumps([[2], notebook_id, "NOT artifact.status = \"ARTIFACT_STATUS_SUGGESTED\""]),
        cookies, notebook_id,
    )
    notes = _dedup(_extract_strings(data, 80)) if data and not isinstance(data, dict) else []
    archive["notes"] = [n for n in notes if len(n) > 50]

    # Conversation threads
    if include_threads:
        t_args = json.dumps([[], None, notebook_id, 50])
        _, t_data = _batchexecute(RPC_GET_THREAD_IDS, t_args, cookies, notebook_id)
        thread_ids: List[str] = []
        try:
            if isinstance(t_data, list) and t_data:
                for item in t_data[0]:
                    if isinstance(item, list) and item and isinstance(item[0], str):
                        thread_ids.append(item[0])
        except (IndexError, TypeError):
            pass

        threads = []
        for tid in thread_ids:
            m_args = json.dumps([[], None, None, tid, 50])
            _, m_data = _batchexecute(RPC_READ_THREAD, m_args, cookies, notebook_id)
            messages = [s for s in _extract_strings(m_data or [], min_len=10) if len(s) > 20]
            threads.append({"thread_id": tid, "messages": messages, "message_count": len(messages)})
        archive["threads"] = threads
    else:
        archive["threads"] = []

    # Mind map
    _, data = _batchexecute(RPC_MIND_MAP, json.dumps([notebook_id, None, None, [2]]), cookies, notebook_id)
    mindmap_raw = ""
    try:
        mindmap_raw = _extract_strings(data, min_len=5)[0] if data and _extract_strings(data, min_len=5) else ""
    except (IndexError, TypeError):
        pass
    try:
        archive["mindmap"] = json.loads(mindmap_raw)
    except (json.JSONDecodeError, TypeError):
        archive["mindmap"] = mindmap_raw or None

    archive["stats"] = {
        "sources": len(archive["sources"]),
        "notes": len(archive["notes"]),
        "threads": len(archive["threads"]),
        "total_source_words": sum(s.get("content_word_count", s.get("word_count", 0)) for s in archive["sources"]),
    }
    return archive


def export_all_notebooks(
    cookies: Dict[str, str],
    include_source_content: bool = False,
    include_threads: bool = True,
) -> Dict[str, Any]:
    """Export all notebooks for the authenticated user as a complete archive.

    Workflow:
      1. Call ub2Bae (LIST_NOTEBOOKS) to get all notebook UUIDs + names.
      2. Call export_notebook() for each notebook in sequence.
      3. Return a combined result dict.

    Source content is disabled by default for full-account exports because
    reading all sources across all notebooks can take many minutes.
    Set include_source_content=True only when you explicitly need all text
    (e.g., for full Nexus ingestion or training data collection).

    Error handling: Failed notebooks are included in the result with an
    "error" key instead of crashing the entire export.

    Args:
        cookies:                Google auth cookies.
        include_source_content: Read full source text per source per notebook.
                               Disabled by default for large accounts.
        include_threads:        Read conversation threads for each notebook.

    Returns:
        Dict with: count (total notebooks), notebooks (list of archives), exported_at.
        Each archive follows the export_notebook() return structure.
    """
    import datetime
    _, data = _batchexecute(RPC_LIST_NOTEBOOKS, "[[2]]", cookies)
    notebook_ids: List[Dict[str, str]] = []
    try:
        for nb in (data[0] if isinstance(data, list) and data else []):
            if isinstance(nb, list):
                nid = None
                for part in nb:
                    if isinstance(part, str) and re.match(r"[a-f0-9-]{36}", part):
                        nid = part
                        break
                texts = _extract_strings(nb, min_len=5)
                if nid:
                    notebook_ids.append({"id": nid, "name": texts[0] if texts else "Unknown"})
    except (IndexError, TypeError) as exc:
        logger.warning("export_all_notebooks: list parse error: %s", exc)

    notebooks = []
    for nb_meta in notebook_ids:
        try:
            archive = export_notebook(
                nb_meta["id"], cookies,
                include_source_content=include_source_content,
                include_threads=include_threads,
            )
            archive["notebook_name"] = archive.get("notebook_name") or nb_meta["name"]
            notebooks.append(archive)
        except Exception as exc:
            logger.error("export_all_notebooks: failed for %s: %s", nb_meta["id"], exc)
            notebooks.append({
                "notebook_id": nb_meta["id"],
                "notebook_name": nb_meta["name"],
                "error": str(exc),
            })

    return {
        "count": len(notebooks),
        "notebooks": notebooks,
        "exported_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
    }


def get_user_quota(cookies: Dict[str, str]) -> Dict[str, Any]:
    """Fetch user account info and storage quota (ozz5Z RPC).

    Returns quota usage, plan type, and account metadata.

    Args:
        cookies: Google auth cookies.

    Returns:
        Dict with: raw_data (nested structure), extracted_text.
    """
    args = json.dumps([[[[None, "1", 627],
                         [None, None, None, None, None, None, None,
                          None, None, [None, None, 4]],
                         1]]])
    _, data = _batchexecute(RPC_USER_QUOTA, args, cookies)
    if data is None or (isinstance(data, dict) and "error" in data):
        return data or {"error": "no_data"}
    texts = _extract_strings(data, min_len=5)
    return {"quota_data": data, "extracted": texts[:10]}


def get_user_plan(cookies: Dict[str, str]) -> Dict[str, Any]:
    """Fetch user plan/tier and quota limits (ZwVcOc RPC).

    Returns current plan name, daily query allowance, and remaining queries.

    Args:
        cookies: Google auth cookies.

    Returns:
        Dict with: plan_name, daily_limit, queries_remaining, raw_data.
    """
    args = json.dumps([None, [2]])
    _, data = _batchexecute(RPC_USER_PLAN, args, cookies)
    if data is None or (isinstance(data, dict) and "error" in data):
        return data or {"error": "no_data"}

    result: Dict[str, Any] = {"raw_data": data}
    try:
        texts = _extract_strings(data, min_len=3)
        ints = [x for x in _walk_ints(data)]

        # Heuristic: plan name is the first string of length > 3
        if texts:
            result["plan_name"] = texts[0]

        # daily_limit and queries_remaining are typically integers in the payload
        if len(ints) >= 2:
            result["daily_limit"] = ints[0]
            result["queries_remaining"] = ints[1]
        elif len(ints) == 1:
            result["queries_remaining"] = ints[0]
    except Exception as e:
        logger.debug("[NLMArchive] Quota parse failed (operation=parse_quota): %s", e)

    return result


def _walk_ints(obj: Any) -> List[int]:
    """Recursively extract all integers from a nested structure."""
    results: List[int] = []
    if isinstance(obj, int) and not isinstance(obj, bool):
        results.append(obj)
    elif isinstance(obj, list):
        for item in obj:
            results.extend(_walk_ints(item))
    return results


def generate_document(
    notebook_id: str,
    source_ids: List[str],
    cookies: Dict[str, str],
    doc_type: int = 2,
) -> Dict[str, Any]:
    """Generate a document/report from selected sources (ciyUvf RPC).

    Args:
        notebook_id: UUID of the target notebook.
        source_ids:  List of source UUIDs to include in the document.
        cookies:     Google auth cookies.
        doc_type:    Document type integer (2=standard, 9=deep research).

    Returns:
        Dict with: title, description, source_ids.
    """
    source_array = [[sid] for sid in source_ids]
    args = json.dumps([_WRITE_CONFIG, notebook_id, source_array])
    _, data = _batchexecute(RPC_GENERATE_DOC, args, cookies, notebook_id)
    return _parse_generate_response(data, source_ids)


def _parse_generate_response(data: Any, source_ids: List[str]) -> Dict[str, Any]:
    """Parse a ciyUvf response."""
    if data is None:
        return {"title": "", "description": "", "source_ids": source_ids, "error": "no_data"}
    if isinstance(data, dict) and "error" in data:
        return {"title": "", "description": "", "source_ids": source_ids, **data}
    try:
        # ciyUvf returns [[title, description, null, [[source_id], ...]], ...]
        if isinstance(data, list) and data:
            first = data[0]
            if isinstance(first, list):
                title = first[0] if isinstance(first[0], str) else ""
                description = first[1] if len(first) > 1 and isinstance(first[1], str) else ""
                return {"title": title, "description": description, "source_ids": source_ids}
    except (IndexError, TypeError) as exc:
        logger.warning("parse generate: %s", exc)
    return {"title": "", "description": "", "source_ids": source_ids}


def save_note_report(
    notebook_id: str,
    source_ids: List[str],
    cookies: Dict[str, str],
    note_type: int = 2,
) -> Dict[str, Any]:
    """Create/save a note artifact in a notebook (R7cb6c RPC).

    Args:
        notebook_id: UUID of the target notebook.
        source_ids:  List of source UUIDs to associate with the note.
        cookies:     Google auth cookies.
        note_type:   Note type (2=standard note, 9=deep research).

    Returns:
        Dict with: note_id, title, note_type.
    """
    # Build nested source array as observed in HAR: [[[src_id]], [[src_id]], ...]
    source_array = [[sid] for sid in source_ids]
    note_body = [None, None, note_type, source_array]
    args = json.dumps([_WRITE_CONFIG, notebook_id, note_body])
    _, data = _batchexecute(RPC_SAVE_REPORT, args, cookies, notebook_id)
    return _parse_save_note_response(data)


def _parse_save_note_response(data: Any) -> Dict[str, Any]:
    """Parse an R7cb6c response."""
    if data is None:
        return {"note_id": None, "title": "", "note_type": 2, "error": "no_data"}
    if isinstance(data, dict) and "error" in data:
        return {"note_id": None, "title": "", "note_type": 2, **data}
    try:
        # R7cb6c returns [[note_id, title, type_int, [[source_ids]]], ...]
        if isinstance(data, list) and data:
            first = data[0]
            if isinstance(first, list) and len(first) >= 3:
                note_id = first[0] if isinstance(first[0], str) else None
                title = first[1] if isinstance(first[1], str) else ""
                note_type = first[2] if isinstance(first[2], int) else 2
                return {"note_id": note_id, "title": title, "note_type": note_type}
    except (IndexError, TypeError) as exc:
        logger.warning("parse save_note: %s", exc)
    return {"note_id": None, "title": "", "note_type": 2}
