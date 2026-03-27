#!/usr/bin/env python3
"""
Nexus CLI - CosySim Knowledge Management
==========================================

Full CLI for the Nexus Knowledge Management System. Search, ask, add
knowledge, manage sessions, run maintenance, and interact with NLM.

Version: v1.57.2 [2026-03-27]
Author:  CosySim Team

Change Log:
    v1.57.2 [2026-03-27] - Initial standalone CLI

Usage:
    python apps/nexus.py search "interceptor pipeline"
    python apps/nexus.py ask "How does state persistence work?"
    python apps/nexus.py add "Title" "Content" --type decision
    python apps/nexus.py status
    python apps/nexus.py prompts --category system
    python apps/nexus.py rules --scope coding
    python apps/nexus.py nlm ask "How does MCP work?"
    python apps/nexus.py nlm batch-ask questions.txt
    python apps/nexus.py nlm stats
    python apps/nexus.py seed                    # Seed core Q&A pairs
    python apps/nexus.py sessions                # List recent sessions
    python apps/nexus.py embed "text to embed"   # Get embeddings
"""
from __future__ import annotations

import sys
from pathlib import Path

# Bootstrap
sys.path.insert(0, str(Path(__file__).resolve().parent))
from _bootstrap import bootstrap, run, run_module, ROOT, SCRIPTS
bootstrap()

import argparse


def main() -> int:
    parser = argparse.ArgumentParser(
        prog="nexus",
        description="Nexus KMS - CosySim Knowledge Management System",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Command Groups:
  search <query>        Search the knowledge base
  ask <question>        Ask a question (uses query router)
  add <title> <body>    Add knowledge entry (--type, --namespace)
  status                Show Nexus health and statistics
  prompts               List prompt templates (--category)
  rules                 List governance rules (--scope)
  nlm <subcmd>          NotebookLM operations (ask, batch-ask, distill, stats)
  seed                  Seed core Q&A pairs into Nexus
  sessions              List/sync sessions
  embed <text>          Generate embeddings for text
  maintenance           Run maintenance tasks (cleanup, dedup, reindex)
  youtube <url>         Ingest YouTube transcript into knowledge base

Examples:
  nexus search "how does the interceptor pipeline work"
  nexus ask "What are the three pillars?"
  nexus add "RPC Discovery" "Found 60 gRPC methods" --type discovery
  nexus nlm ask "Summarize the architecture"
  nexus status
        """,
    )
    parser.add_argument("command", nargs="?", help="Command to run")
    parser.add_argument("args", nargs=argparse.REMAINDER, help="Command arguments")

    parsed = parser.parse_args()

    if not parsed.command:
        parser.print_help()
        return 0

    cmd = parsed.command
    rest = parsed.args

    if cmd == "nlm":
        # Delegate to NLM CLI
        return run_module("engine.nexus.nlm_cli", rest)

    elif cmd == "seed":
        return run(SCRIPTS / "seed_nexus_qa.py", rest)

    elif cmd == "sessions":
        return run_module("engine.nexus.sync_sessions_to_nexus", rest)

    elif cmd == "maintenance":
        return run_module("engine.nexus.self_maintenance", rest)

    elif cmd == "embed":
        # Quick embedding test
        if not rest:
            print("Usage: nexus embed <text>")
            return 1
        try:
            from engine.nexus.embedding_service import get_embedding_service
            svc = get_embedding_service()
            text = " ".join(rest)
            result = svc.embed(text)
            print(f"Embedding for: {text[:60]}...")
            print(f"Dimensions: {len(result)}")
            print(f"First 10: {result[:10]}")
            return 0
        except Exception as e:
            print(f"ERROR: {e}")
            return 1

    else:
        # Everything else delegates to the main Nexus CLI
        return run_module("engine.nexus.cli", [cmd] + rest)


if __name__ == "__main__":
    sys.exit(main())
