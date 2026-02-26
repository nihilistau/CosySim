"""
Nexus → GitHub Knowledge Exporter

Exports key Nexus knowledge entries to markdown files in a GitHub repo,
which can then be added to a Copilot Space as sources. This bridges
local Nexus knowledge to GitHub's cloud context system.

Usage:
    python engine/nexus/space_exporter.py                    # export to knowledge-pipeline repo
    python engine/nexus/space_exporter.py --output /path     # export to custom dir
    python engine/nexus/space_exporter.py --categories architecture,api
    python engine/nexus/space_exporter.py --push             # auto commit+push
"""
from __future__ import annotations

import json
import logging
import subprocess
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

NEXUS_URL = "http://localhost:8700"
DEFAULT_OUTPUT = Path("C:/Files/knowledge-pipeline/knowledge/nexus-export")


def _fetch_nexus(path: str) -> dict:
    """Fetch from Nexus API."""
    try:
        req = urllib.request.Request(
            f"{NEXUS_URL}{path}",
            headers={"Accept": "application/json"},
        )
        with urllib.request.urlopen(req, timeout=10) as resp:
            return json.loads(resp.read())
    except Exception as e:
        logger.error("Nexus fetch failed: %s", e)
        return {}


def _entry_to_markdown(entry: dict) -> str:
    """Convert a Nexus entry to structured markdown."""
    title = entry.get("title", "Untitled")
    content = entry.get("content", "")
    content_type = entry.get("content_type", "note")
    category = entry.get("category", "general")
    tags = entry.get("tags", "")
    created = entry.get("created_at", "")

    lines = [
        f"# {title}",
        "",
        f"> Type: {content_type}",
        f"> Category: {category}",
        f"> Tags: {tags}",
        f"> Exported: {datetime.now(timezone.utc).isoformat()}",
        "",
        content,
    ]
    return "\n".join(lines)


def export_knowledge(
    output_dir: Optional[Path] = None,
    categories: Optional[list[str]] = None,
    min_length: int = 100,
    limit: int = 50,
) -> dict:
    """Export Nexus knowledge entries to markdown files.

    Args:
        output_dir: Directory to write markdown files to.
        categories: Filter by categories (None = all).
        min_length: Minimum content length to export.
        limit: Maximum entries to export.

    Returns:
        dict with export counts.
    """
    output = output_dir or DEFAULT_OUTPUT
    output.mkdir(parents=True, exist_ok=True)

    counts = {"exported": 0, "skipped": 0, "errors": 0}

    # Fetch entries from Nexus
    # Search for high-value entries
    queries = categories or ["architecture", "api", "system", "knowledge", "sessions"]

    seen_ids = set()
    all_entries = []

    for query in queries:
        data = _fetch_nexus(f"/api/search?q={query}&limit={limit}")
        raw = data.get("data", [])
        results = raw if isinstance(raw, list) else raw.get("results", [])
        for entry in results:
            eid = entry.get("id", "")
            if eid not in seen_ids:
                seen_ids.add(eid)
                all_entries.append(entry)

    # Also fetch Q&A entries
    qa_data = _fetch_nexus("/api/qa?limit=30")
    qa_raw = qa_data.get("data", [])
    qa_entries = qa_raw if isinstance(qa_raw, list) else qa_raw.get("entries", [])

    # Export regular entries
    for entry in all_entries[:limit]:
        content = entry.get("content", "")
        if len(content) < min_length:
            counts["skipped"] += 1
            continue

        title = entry.get("title", "untitled")
        slug = title.lower()
        for char in " /\\:*?\"<>|":
            slug = slug.replace(char, "-")
        slug = slug[:60].strip("-")

        try:
            md_content = _entry_to_markdown(entry)
            filepath = output / f"{slug}.md"
            filepath.write_text(md_content, encoding="utf-8")
            counts["exported"] += 1
        except Exception as e:
            logger.error("Failed to export %s: %s", title, e)
            counts["errors"] += 1

    # Export Q&A as a single compiled file
    if qa_entries:
        qa_lines = ["# Nexus Q&A Knowledge Base", "", f"> Exported: {datetime.now(timezone.utc).isoformat()}", ""]
        for qa in qa_entries:
            question = qa.get("question", "")
            answer = qa.get("answer", "")
            if question and answer:
                qa_lines.extend([
                    f"## Q: {question}",
                    "",
                    answer,
                    "",
                    "---",
                    "",
                ])

        qa_file = output / "nexus-qa-compiled.md"
        qa_file.write_text("\n".join(qa_lines), encoding="utf-8")
        counts["exported"] += 1

    # Write index
    index_lines = [
        "# Nexus Knowledge Export",
        "",
        f"Exported {counts['exported']} entries from Nexus KMS.",
        f"Last export: {datetime.now(timezone.utc).isoformat()}",
        "",
        "## Files",
        "",
    ]
    for f in sorted(output.glob("*.md")):
        if f.name != "index.md":
            index_lines.append(f"- [{f.stem}]({f.name})")

    (output / "index.md").write_text("\n".join(index_lines), encoding="utf-8")

    logger.info(
        "Export complete: %d exported, %d skipped, %d errors",
        counts["exported"], counts["skipped"], counts["errors"],
    )
    return counts


def push_export(output_dir: Optional[Path] = None) -> bool:
    """Commit and push exported knowledge to GitHub."""
    repo_root = (output_dir or DEFAULT_OUTPUT).parent.parent
    try:
        subprocess.run(["git", "add", "-A"], cwd=repo_root, check=True, capture_output=True)
        subprocess.run(
            ["git", "commit", "-m", f"knowledge: Nexus export {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M')}"],
            cwd=repo_root, check=True, capture_output=True,
        )
        subprocess.run(["git", "push"], cwd=repo_root, check=True, capture_output=True)
        logger.info("Pushed export to GitHub")
        return True
    except subprocess.CalledProcessError as e:
        logger.error("Git push failed: %s", e.stderr.decode() if e.stderr else str(e))
        return False


def main() -> None:
    import argparse
    import sys

    logging.basicConfig(level=logging.INFO, format="%(message)s")

    parser = argparse.ArgumentParser(description="Export Nexus knowledge for Copilot Spaces")
    parser.add_argument("--output", type=Path, help="Output directory")
    parser.add_argument("--categories", help="Comma-separated categories to export")
    parser.add_argument("--limit", type=int, default=50, help="Max entries")
    parser.add_argument("--push", action="store_true", help="Auto commit and push")
    args = parser.parse_args()

    categories = args.categories.split(",") if args.categories else None
    counts = export_knowledge(
        output_dir=args.output,
        categories=categories,
        limit=args.limit,
    )

    print(f"Exported: {counts['exported']}, Skipped: {counts['skipped']}, Errors: {counts['errors']}")

    if args.push:
        push_export(args.output)


if __name__ == "__main__":
    main()
