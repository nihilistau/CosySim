#!/usr/bin/env python3
"""
NLM CLI - NotebookLM Operations
==================================

Query, ingest documents, create notebooks, bulk-seed Q&A, run prompt
chains, generate flashcards, and reverse-engineer the NLM API.

Version: v1.57.2 [2026-03-27]
Author:  CosySim Team

Change Log:
    v1.57.2 [2026-03-27] - Initial standalone CLI with upload file-type handling

Usage:
    python apps/nlm.py ask "question"                     # Query via CDP
    python apps/nlm.py ingest --file docs/ARCH.md         # Ingest into notebook
    python apps/nlm.py create [--name NAME]               # Create new notebook
    python apps/nlm.py seed questions.txt                  # Bulk-ask Q&A pairs
    python apps/nlm.py chain pipeline.yaml                 # Run prompt chain
    python apps/nlm.py flashcards                          # Generate flashcards
    python apps/nlm.py protocol                            # Reverse-engineer NLM API
    python apps/nlm.py upload <file> [--notebook-url URL]  # Upload file (auto-renames .py)
    python apps/nlm.py cli ...                             # Full NLM CLI
"""
from __future__ import annotations

import os
import shutil
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _bootstrap import bootstrap, run, run_module, ROOT, SCRIPTS
bootstrap()

# File extensions NLM doesn't accept directly - need renaming
NLM_BLOCKED_EXTENSIONS = {
    ".py", ".js", ".ts", ".tsx", ".jsx", ".css", ".scss",
    ".java", ".go", ".rs", ".c", ".cpp", ".h", ".hpp",
    ".rb", ".php", ".sh", ".bash", ".ps1", ".bat",
    ".yaml", ".yml", ".toml", ".ini", ".cfg", ".conf",
    ".sql", ".graphql", ".proto",
}

# Extension to add for NLM-compatible upload
NLM_RENAME_SUFFIX = ".txt"


def _prepare_file_for_nlm(filepath: str) -> tuple[str, bool]:
    """Copy and rename file if NLM won't accept its extension.

    Args:
        filepath: Original file path.

    Returns:
        Tuple of (path_to_upload, needs_cleanup).
        If renamed, returns a temp copy; caller must clean up.
    """
    p = Path(filepath)
    ext = p.suffix.lower()

    if ext not in NLM_BLOCKED_EXTENSIONS:
        return filepath, False

    # Create temp copy with .txt suffix
    tmp_dir = Path(tempfile.mkdtemp(prefix="nlm_upload_"))
    new_name = p.name + NLM_RENAME_SUFFIX
    dest = tmp_dir / new_name
    shutil.copy2(filepath, dest)
    print(f"  Renamed for NLM: {p.name} -> {new_name}")
    return str(dest), True


def main() -> int:
    if not sys.argv[1:] or sys.argv[1] in ("-h", "--help"):
        print("""
  NLM - NotebookLM Operations v1.57.2
  =====================================

  Usage: python apps/nlm.py <command> [args...]

  Query:
    ask "question"                    Query NLM via CDP browser
    cli ask "question"                Query via NLM CLI (HTTP)

  Content:
    ingest --file FILE                Ingest file into NLM notebook
    upload <file> [--notebook-url U]  Upload file (auto-renames .py/.js/.ts)
    create [--name NAME]              Create new NLM notebook

  Knowledge:
    seed <file>                       Bulk-ask Q&A pairs, store in Nexus
    flashcards                        Generate flashcards via Gemini
    chain <pipeline>                  Run prompt chain pipeline

  Analysis:
    protocol                          Reverse-engineer NLM API from HAR
    debug-chunks                      Debug NLM response chunks

  Full CLI:
    cli <subcmd>                      Full NLM CLI (ask, batch-ask, distill, stats)

  Note: .py, .js, .ts, .yaml etc. files are auto-renamed to .py.txt
  for NLM upload compatibility.
""")
        return 0

    cmd = sys.argv[1]
    rest = sys.argv[2:]

    # Upload with auto-rename
    if cmd == "upload":
        return _cmd_upload(rest)

    # Script dispatch
    dispatch = {
        "ask":          SCRIPTS / "nlm_ask.py",
        "ingest":       SCRIPTS / "nlm_ingest.py",
        "create":       SCRIPTS / "nlm_create_notebook.py",
        "seed":         SCRIPTS / "nlm_bulk_seeder.py",
        "chain":        SCRIPTS / "nlm_prompt_chain.py",
        "flashcards":   SCRIPTS / "nlm_flashcard_builder.py",
        "protocol":     SCRIPTS / "nlm_protocol_mapper.py",
        "debug-chunks": SCRIPTS / "nlm_debug_chunks.py",
    }

    if cmd in dispatch:
        return run(dispatch[cmd], rest)

    if cmd == "cli":
        return run_module("engine.nexus.nlm_cli", rest)

    print(f"Unknown command: {cmd}")
    return 1


def _cmd_upload(args: list[str]) -> int:
    """Upload file(s) to NLM with automatic renaming for blocked extensions."""
    import argparse

    parser = argparse.ArgumentParser(prog="nlm upload")
    parser.add_argument("files", nargs="+", help="Files to upload")
    parser.add_argument("--notebook-url", "-u", help="Target notebook URL")
    parser.add_argument("--name", "-n", help="Source name in NLM")
    parsed = parser.parse_args(args)

    cleanup_dirs: list[Path] = []

    try:
        for filepath in parsed.files:
            if not os.path.exists(filepath):
                # Try relative to project root
                abs_path = str(ROOT / filepath)
                if not os.path.exists(abs_path):
                    print(f"ERROR: File not found: {filepath}")
                    continue
                filepath = abs_path

            upload_path, needs_cleanup = _prepare_file_for_nlm(filepath)

            if needs_cleanup:
                cleanup_dirs.append(Path(upload_path).parent)

            # Build ingest args
            ingest_args = ["--file", upload_path]
            if parsed.name:
                ingest_args += ["--name", parsed.name]
            elif needs_cleanup:
                # Use original filename as the source name
                ingest_args += ["--name", Path(filepath).name]
            if parsed.notebook_url:
                ingest_args += ["--notebook-url", parsed.notebook_url]

            print(f"  Uploading: {Path(filepath).name}")
            result = run(SCRIPTS / "nlm_ingest.py", ingest_args)
            if result != 0:
                print(f"  WARNING: Upload may have failed for {filepath}")

    finally:
        # Clean up temp directories
        for d in cleanup_dirs:
            try:
                shutil.rmtree(d)
            except OSError:
                pass

    return 0


if __name__ == "__main__":
    sys.exit(main())
