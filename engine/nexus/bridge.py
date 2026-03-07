"""
bridge.py — Standalone Nexus CLI bridge for Copilot CLI agents.

Provides direct Nexus access without requiring the MCP server to be running.
Each command outputs JSON for easy parsing by Copilot CLI or other tools.

Usage:
    python -m engine.nexus.bridge search "interceptor pipeline"
    python -m engine.nexus.bridge ask "How does state management work?"
    python -m engine.nexus.bridge store "Title" "Content" --type note --category dev
    python -m engine.nexus.bridge qa "Question?" "Answer."
    python -m engine.nexus.bridge backfill "Question?" "Answer." --source docs
    python -m engine.nexus.bridge inventory --store
    python -m engine.nexus.bridge rules [scope]
    python -m engine.nexus.bridge health
    python -m engine.nexus.bridge seed [docs|qa|rules|prompts|conventions|all]
    python -m engine.nexus.bridge maintain [health|dedup|cleanup]
"""
from __future__ import annotations

import argparse
import json
import logging
import sys
from typing import Any

from engine.nexus.client import get_nexus_client
from engine.nexus.knowledge_capture import capture_external_discovery
from engine.system_registry import (
    build_system_inventory,
    render_system_inventory_text,
    store_system_inventory_snapshot,
)

logger = logging.getLogger(__name__)


def _output(data: Any) -> None:
    """Print JSON output to stdout for CLI consumers."""
    print(json.dumps(data, indent=2, default=str))


def cmd_search(args: argparse.Namespace) -> None:
    """Search Nexus knowledge base."""
    client = get_nexus_client()
    results = client.search(args.query, limit=args.limit)
    _output({"query": args.query, "results": results, "count": len(results)})


def cmd_ask(args: argparse.Namespace) -> None:
    """Ask Nexus a question (Q&A cache → FTS → NLM)."""
    client = get_nexus_client()
    answer = client.ask(args.question, depth=args.depth)
    _output(answer)


def cmd_store(args: argparse.Namespace) -> None:
    """Store a knowledge entry in Nexus."""
    client = get_nexus_client()
    result = client.add_entry(
        title=args.title,
        content=args.content,
        content_type=args.type,
        category=args.category,
        tags=args.tags.split(",") if args.tags else [],
    )
    _output({"status": "stored", "result": result})


def cmd_qa(args: argparse.Namespace) -> None:
    """Store a Q&A pair in Nexus."""
    client = get_nexus_client()
    result = client.add_qa(
        question=args.question,
        answer=args.answer,
        category=args.category,
    )
    _output({"status": "stored", "result": result})


def cmd_backfill(args: argparse.Namespace) -> None:
    """Backfill externally discovered knowledge into Nexus as note + Q&A."""
    result = capture_external_discovery(
        question=args.question,
        answer=args.answer,
        source=args.source,
        title=args.title,
        category=args.category,
        tags=args.tags.split(",") if args.tags else [],
        details=args.details,
    )
    _output(result.to_dict())


def cmd_inventory(args: argparse.Namespace) -> None:
    """Render or store the canonical CosySim system inventory."""
    if args.store:
        result = store_system_inventory_snapshot(title=args.title)
        if args.format == "text":
            print(render_system_inventory_text(include_catalog=args.include_catalog))
            print("")
            print(f"Stored entry_id={result['entry_id']} qa_id={result['qa_id']}")
            return
        _output(result)
        return

    if args.format == "text":
        print(render_system_inventory_text(include_catalog=args.include_catalog))
        return

    _output(build_system_inventory(include_catalog=args.include_catalog))


def cmd_rules(args: argparse.Namespace) -> None:
    """Get governance rules from Nexus."""
    client = get_nexus_client()
    rules = client.get_rules(scope=args.scope or "")
    _output({"scope": args.scope, "rules": rules, "count": len(rules)})


def cmd_health(args: argparse.Namespace) -> None:
    """Check Nexus health and knowledge stats."""
    from collections import Counter
    try:
        client = get_nexus_client()
        entries = client.list_entries(limit=500)
        # find_qa requires a non-empty query — use broad common term for count
        qa_list = client.find_qa("cosysim", limit=500) or client.find_qa("what", limit=500)
        rules_list = client.get_rules()
        types = dict(Counter(e.content_type for e in entries))
        cats = dict(Counter(e.category for e in entries))
        _output({
            "status": "healthy",
            "entries": len(entries),
            "qa_pairs": len(qa_list),
            "rules": len(rules_list),
            "by_type": types,
            "by_category": cats,
        })
    except Exception as e:
        _output({"status": "error", "error": str(e)})


def cmd_seed(args: argparse.Namespace) -> None:
    """Run the Nexus knowledge seeder."""
    import engine.nexus.nexus_seeder as seeder_mod
    source = getattr(args, "source", "all")
    fn_map = {
        "docs": seeder_mod.seed_docs,
        "qa": seeder_mod.seed_qa,
        "rules": seeder_mod.seed_rules,
        "prompts": seeder_mod.seed_prompts,
        "conventions": seeder_mod.seed_conventions,
        "all": seeder_mod.seed_all,
    }
    fn = fn_map.get(source, seeder_mod.seed_all)
    counts = fn()
    _output({"status": "ok", "source": source, "created": counts})


def cmd_maintain(args: argparse.Namespace) -> None:
    """Run Nexus maintenance actions."""
    if args.action == "health":
        cmd_health(args)
        return

    if args.action == "dedup":
        client = get_nexus_client()
        entries = client.list_entries(limit=500)
        seen: dict = {}
        duplicates = []
        for e in entries:
            title = e.title.strip().lower()
            if title in seen:
                duplicates.append({"id": e.id, "title": e.title})
            else:
                seen[title] = e.id
        removed = 0
        for dup in duplicates:
            if client.delete_entry(dup["id"]):
                removed += 1
        _output({"found": len(duplicates), "removed": removed, "duplicates": duplicates})
        return

    if args.action == "cleanup":
        client = get_nexus_client()
        entries = client.list_entries(limit=500)
        low = [e for e in entries if len(e.content) < 10]
        removed = 0
        for e in low:
            if client.delete_entry(e.id):
                removed += 1
        _output({"low_quality": len(low), "removed": removed})
        return

    _output({"error": f"Unknown action: {args.action}"})


def main() -> None:
    """CLI entry point."""
    parser = argparse.ArgumentParser(
        description="Nexus Knowledge Bridge — Direct CLI access to Nexus KMS",
        prog="python -m engine.nexus.bridge",
    )
    subs = parser.add_subparsers(dest="command", required=True)

    # search
    p = subs.add_parser("search", help="Search knowledge base")
    p.add_argument("query", help="Search query")
    p.add_argument("--limit", type=int, default=10, help="Max results")
    p.set_defaults(func=cmd_search)

    # ask
    p = subs.add_parser("ask", help="Ask a question (Q&A → FTS → NLM)")
    p.add_argument("question", help="Question to ask")
    p.add_argument("--depth", default="auto", choices=["shallow", "auto", "deep"])
    p.set_defaults(func=cmd_ask)

    # store
    p = subs.add_parser("store", help="Store knowledge entry")
    p.add_argument("title", help="Entry title")
    p.add_argument("content", help="Entry content")
    p.add_argument("--type", default="note", help="Content type")
    p.add_argument("--category", default="development", help="Category")
    p.add_argument("--tags", default="", help="Comma-separated tags")
    p.set_defaults(func=cmd_store)

    # qa
    p = subs.add_parser("qa", help="Store a Q&A pair")
    p.add_argument("question", help="Question")
    p.add_argument("answer", help="Answer")
    p.add_argument("--category", default="development", help="Category")
    p.set_defaults(func=cmd_qa)

    # backfill
    p = subs.add_parser("backfill", help="Backfill external discovery into Nexus")
    p.add_argument("question", help="Question or retrieval key")
    p.add_argument("answer", help="Discovered answer")
    p.add_argument("--source", required=True, help="Where the information was found")
    p.add_argument("--title", default="", help="Optional knowledge entry title")
    p.add_argument("--category", default="research", help="Category")
    p.add_argument("--tags", default="", help="Comma-separated tags")
    p.add_argument("--details", default="", help="Optional extra details/context")
    p.set_defaults(func=cmd_backfill)

    # inventory
    p = subs.add_parser("inventory", help="Show or store the canonical system inventory")
    p.add_argument("--store", action="store_true", help="Store the inventory snapshot in Nexus")
    p.add_argument("--title", default="System inventory snapshot", help="Stored entry title")
    p.add_argument("--format", default="json", choices=["json", "text"], help="Output format")
    p.add_argument("--include-catalog", action="store_true", help="Include full service and scene catalogues")
    p.set_defaults(func=cmd_inventory)

    # rules
    p = subs.add_parser("rules", help="Get governance rules")
    p.add_argument("scope", nargs="?", default="", help="Rule scope filter")
    p.set_defaults(func=cmd_rules)

    # health
    p = subs.add_parser("health", help="Check Nexus health and stats")
    p.set_defaults(func=cmd_health)

    # seed
    p = subs.add_parser("seed", help="Seed Nexus with project knowledge")
    p.add_argument("source", nargs="?", default="all",
                   choices=["docs", "qa", "rules", "prompts", "conventions", "all"])
    p.set_defaults(func=cmd_seed)

    # maintain
    p = subs.add_parser("maintain", help="Maintenance actions")
    p.add_argument("action", nargs="?", default="health",
                   choices=["health", "dedup", "cleanup"])
    p.set_defaults(func=cmd_maintain)

    args = parser.parse_args()
    try:
        args.func(args)
    except Exception as e:
        _output({"error": str(e)})
        sys.exit(1)


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    main()
