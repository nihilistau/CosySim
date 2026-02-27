"""
Nexus CLI — Command-line interface to the Nexus Knowledge System.

Usage:
    python -m engine.nexus.cli search "interceptor pipeline"
    python -m engine.nexus.cli ask "How does state persistence work?"
    python -m engine.nexus.cli add "Title" "Content" --type decision --category arch
    python -m engine.nexus.cli status
    python -m engine.nexus.cli prompts --category system
    python -m engine.nexus.cli rules --scope coding
    python -m engine.nexus.cli youtube "https://youtube.com/watch?v=..."
"""
import argparse
import json
import logging
import sys
import textwrap
from typing import List

from engine.nexus.client import get_nexus_client

logger = logging.getLogger(__name__)


def _print_json(data, indent: int = 2):
    """Pretty-print JSON data."""
    logger.info(json.dumps(data, indent=indent, default=str))


def _print_entries(entries: List[dict], fields=("title", "content_type", "category")):
    """Print a list of entries in a readable table format."""
    if not entries:
        logger.info("No results found.")
        return
    for i, entry in enumerate(entries, 1):
        title = entry.get("title", "Untitled")
        ctype = entry.get("content_type", "")
        cat = entry.get("category", "")
        suffix = " (%s)" % cat if cat else ""
        logger.info("  %d. [%s] %s%s", i, ctype, title, suffix)
        content = entry.get("content", "")
        if content:
            preview = textwrap.shorten(content, width=120, placeholder="...")
            logger.info("     %s", preview)
    logger.info("\n  %d result(s)", len(entries))


def cmd_search(args):
    """Search the Nexus knowledge base."""
    client = get_nexus_client()
    results = client.search(args.query, limit=args.limit)
    if args.json:
        _print_json(results)
    else:
        logger.info("Search: \"%s\"\n", args.query)
        _print_entries(results)


def cmd_ask(args):
    """Smart Q&A — checks cache, then FTS, then NLM."""
    client = get_nexus_client()
    answer = client.ask(args.question, depth=args.depth, category=args.category)
    if args.json:
        _print_json(answer)
    else:
        logger.info("Q: %s\n", args.question)
        if answer.get("answer"):
            logger.info("A: %s", answer["answer"])
            if answer.get("source"):
                logger.info("\n  Source: %s", answer["source"])
            if answer.get("confidence"):
                logger.info("  Confidence: %s", answer["confidence"])
        else:
            logger.info("No answer found.")


def cmd_add(args):
    """Store a knowledge entry in Nexus."""
    client = get_nexus_client()
    tags = [t.strip() for t in args.tags.split(",")] if args.tags else []
    entry_id = client.add_entry(
        title=args.title,
        content=args.content,
        content_type=args.type,
        category=args.category,
        tags=tags,
    )
    if entry_id:
        logger.info("Stored: %s", entry_id)
    else:
        logger.error("Failed to store entry.")
        sys.exit(1)


def cmd_status(args):
    """Check Nexus system health."""
    client = get_nexus_client()
    health = client.health()
    stats = client.stats()
    if args.json:
        _print_json({"health": health, "stats": stats})
    else:
        available = health.get("ok", False)
        status_str = "ONLINE" if available else "OFFLINE"
        logger.info("Nexus: %s", status_str)
        if stats.get("ok"):
            data = stats.get("data", stats)
            for key, val in data.items():
                if key != "ok":
                    logger.info("  %s: %s", key, val)


def cmd_prompts(args):
    """List stored prompts."""
    client = get_nexus_client()
    prompts = client.get_prompts(category=args.category, name=args.name)
    if args.json:
        _print_json(prompts)
    else:
        suffix = " (%s)" % args.category if args.category else ""
        logger.info("Prompts%s:\n", suffix)
        _print_entries(prompts)


def cmd_rules(args):
    """Get governance rules."""
    client = get_nexus_client()
    rules = client.get_rules(scope=args.scope, rule_type=args.type)
    if args.json:
        _print_json(rules)
    else:
        if not rules:
            logger.info("No rules found.")
            return
        for i, rule in enumerate(rules, 1):
            logger.info("  %d. [%s] %s", i, rule.get("scope", ""), rule.get("name", "Unnamed"))
            if rule.get("condition"):
                logger.info("     Condition: %s", json.dumps(rule["condition"]))
            if rule.get("action"):
                logger.info("     Action: %s", json.dumps(rule["action"]))
        logger.info("\n  %d rule(s)", len(rules))


def cmd_youtube(args):
    """Import a YouTube transcript."""
    client = get_nexus_client()
    tags = [t.strip() for t in args.tags.split(",")] if args.tags else []
    result = client.import_youtube(args.url, category=args.category, tags=tags)
    if result:
        logger.info("Imported: %s", result.get("title", "unknown"))
        if result.get("entry_id"):
            logger.info("  Entry ID: %s", result["entry_id"])
    else:
        logger.error("Import failed.")
        sys.exit(1)


def cmd_qa(args):
    """Store a Q&A pair."""
    client = get_nexus_client()
    qa_id = client.add_qa(args.question, args.answer, category=args.category)
    if qa_id:
        logger.info("Stored Q&A: %s", qa_id)
    else:
        logger.error("Failed to store Q&A.")
        sys.exit(1)


def main():
    parser = argparse.ArgumentParser(
        prog="nexus",
        description="Nexus Knowledge System — CLI interface",
    )
    parser.add_argument("--json", action="store_true", help="Output as JSON")
    sub = parser.add_subparsers(dest="command", help="Available commands")

    # search
    p = sub.add_parser("search", help="Search knowledge base")
    p.add_argument("query", help="Search query")
    p.add_argument("--limit", type=int, default=10, help="Max results")
    p.set_defaults(func=cmd_search)

    # ask
    p = sub.add_parser("ask", help="Smart Q&A")
    p.add_argument("question", help="Question to ask")
    p.add_argument("--depth", default="auto", choices=["shallow", "auto", "deep"])
    p.add_argument("--category", default="", help="Filter by category")
    p.set_defaults(func=cmd_ask)

    # add
    p = sub.add_parser("add", help="Store a knowledge entry")
    p.add_argument("title", help="Entry title")
    p.add_argument("content", help="Entry content")
    p.add_argument("--type", default="note", help="Content type (note, decision, document, snippet, bug)")
    p.add_argument("--category", default="", help="Category")
    p.add_argument("--tags", default="", help="Comma-separated tags")
    p.set_defaults(func=cmd_add)

    # qa
    p = sub.add_parser("qa", help="Store a Q&A pair")
    p.add_argument("question", help="Question")
    p.add_argument("answer", help="Answer")
    p.add_argument("--category", default="", help="Category")
    p.set_defaults(func=cmd_qa)

    # status
    p = sub.add_parser("status", help="Check Nexus health")
    p.set_defaults(func=cmd_status)

    # prompts
    p = sub.add_parser("prompts", help="List stored prompts")
    p.add_argument("--category", default="", help="Filter by category")
    p.add_argument("--name", default="", help="Filter by name")
    p.set_defaults(func=cmd_prompts)

    # rules
    p = sub.add_parser("rules", help="Get governance rules")
    p.add_argument("--scope", default="", help="Filter by scope")
    p.add_argument("--type", default="", help="Filter by rule type")
    p.set_defaults(func=cmd_rules)

    # youtube
    p = sub.add_parser("youtube", help="Import YouTube transcript")
    p.add_argument("url", help="YouTube video URL")
    p.add_argument("--category", default="youtube", help="Category")
    p.add_argument("--tags", default="", help="Comma-separated tags")
    p.set_defaults(func=cmd_youtube)

    args = parser.parse_args()
    if not args.command:
        parser.print_help()
        sys.exit(1)
    args.func(args)


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    main()
