"""NLM CLI — Command-line interface for NotebookLM operations.

Terminal interface for all NLM operations: Q&A, batch asking, notebooks,
document generation, distillation, decomposition, and HAR extraction.

Usage:
    python -m engine.nexus.nlm_cli ask "How does MCP work?"
    python -m engine.nexus.nlm_cli batch-ask questions.txt --notebook nb-123
    python -m engine.nexus.nlm_cli distill nb-123 --topic "MCP state" --count 20
    python -m engine.nexus.nlm_cli stats
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path
from typing import List, Optional

import logging

logger = logging.getLogger(__name__)


def _get_router():
    """Lazy-load NLMRouter."""
    from engine.nexus.nlm_router import get_nlm_router
    return get_nlm_router()


def _get_engine():
    """Lazy-load NLMEngine."""
    from engine.nexus.nlm_engine import get_nlm_engine
    return get_nlm_engine()


def _get_forge():
    """Lazy-load KnowledgeForge."""
    from engine.nexus.knowledge_forge import get_knowledge_forge
    return get_knowledge_forge()


def _get_extractor():
    """Lazy-load HARExtractor."""
    from engine.nexus.har_extractor import HARExtractor
    return HARExtractor()


def _progress_callback(current: int, total: int, question: str) -> None:
    """Print batch progress."""
    logger.info("  [%s/%s] %s", current, total, question[:70])


# ──── Commands ────

def cmd_ask(args: argparse.Namespace) -> None:
    """Ask a question via the NLM-first router."""
    router = _get_router()
    result = router.route(args.question, notebook_id=args.notebook or "")
    logger.info("\n[%s] (conf: %.0f%%, %.0fms)", result.source_tier, result.confidence * 100, result.query_time_ms)
    logger.info("\n%s\n", result.answer)
    if result.stored_in_nexus:
        logger.info("  → Stored in Nexus for future cache hits")


def cmd_batch_ask(args: argparse.Namespace) -> None:
    """Batch-ask questions from a file or stdin."""
    questions: List[str] = []
    if args.file:
        path = Path(args.file)
        if path.suffix == ".json":
            questions = json.loads(path.read_text(encoding="utf-8"))
        else:
            questions = [
                line.strip() for line in path.read_text(encoding="utf-8").splitlines()
                if line.strip() and not line.startswith("#")
            ]
    elif args.questions:
        questions = args.questions
    else:
        logger.info("Provide questions via --file or as arguments")
        return

    logger.info("\nBatch asking %s questions...\n", len(questions))
    router = _get_router()
    results = []
    for i, q in enumerate(questions):
        logger.info("  [%s/%s] %s", i + 1, len(questions), q[:70])
        result = router.route(q, notebook_id=args.notebook or "")
        results.append(result)
        logger.info("    → [%s] %s...", result.source_tier, result.answer[:80])

    # Summary
    tiers = {}
    for r in results:
        tiers[r.source_tier] = tiers.get(r.source_tier, 0) + 1
    logger.info("\n  Summary: %s answered", len(results))
    for tier, count in sorted(tiers.items()):
        logger.info("    %s: %s", tier, count)


def cmd_converse(args: argparse.Namespace) -> None:
    """Interactive conversation with NLM (teacher mode)."""
    engine = _get_engine()
    nb_id = args.notebook
    if not nb_id:
        logger.error("--notebook required for conversation mode")
        return

    logger.info("NLM Teacher Mode — Notebook: %s...", nb_id[:8])
    logger.info("Type 'quit' to exit.\n")

    while True:
        try:
            msg = input("You: ").strip()
        except (EOFError, KeyboardInterrupt):
            break
        if msg.lower() in ("quit", "exit", "q"):
            break
        if not msg:
            continue

        result = engine.ask(nb_id, msg)
        answer = result.get("answer", result.get("response", ""))
        if "error" in result:
            logger.error("%s", result['error'])
        else:
            logger.info("\nNLM: %s\n", answer)


def cmd_create(args: argparse.Namespace) -> None:
    """Create a new NLM notebook."""
    from engine.nexus.nlm_notebook_factory import get_notebook_factory

    category = getattr(args, "category", "general") or "general"
    factory = get_notebook_factory()
    nb_id = factory.get_or_create(args.name, category=category)
    if nb_id:
        logger.info("Created notebook: %s", nb_id)
        logger.info("  Name: %s", args.name)
        logger.info("  Category: %s", category)
    else:
        logger.error("Failed to create notebook: %s", args.name)


def cmd_list(args: argparse.Namespace) -> None:
    """List all notebooks."""
    engine = _get_engine()
    notebooks = engine.list_notebooks()
    if not notebooks:
        logger.info("No notebooks found (or backend unavailable)")
        return
    logger.info("\n%s notebook(s):\n", len(notebooks))
    for nb in notebooks:
        nb_id = nb.get("id", nb.get("notebook_id", "?"))
        name = nb.get("name", nb.get("title", "Untitled"))
        logger.info("  %s...  %s", nb_id[:12], name)


def cmd_add_source(args: argparse.Namespace) -> None:
    """Add a source to a notebook."""
    engine = _get_engine()
    result = engine.add_source(args.notebook, args.type, args.value)
    logger.info(json.dumps(result, indent=2, default=str))


def cmd_add_codebase(args: argparse.Namespace) -> None:
    """Add source files to a notebook."""
    engine = _get_engine()
    result = engine.create_from_files(args.files, args.name or f"Codebase: {args.notebook[:8]}")
    nb_id = result.get("notebook_id", "")
    added = result.get("sources_added", 0)
    logger.info("Notebook: %s", nb_id)
    logger.info("Sources added: %s/%s", added, len(args.files))


def cmd_generate(args: argparse.Namespace) -> None:
    """Generate a document from a notebook."""
    forge = _get_forge()
    result = forge.generate_doc(args.notebook, args.type, args.instructions or "")
    if result.documents:
        content = result.documents[0].get("content", "")
        logger.info("\n--- %s ---\n", args.type)
        logger.info("%s", content[:2000])
        if len(content) > 2000:
            logger.info("\n... (%s chars total)", len(content))
    else:
        logger.error("%s", result.errors)


def cmd_distill(args: argparse.Namespace) -> None:
    """Distill Q&A pairs from a notebook."""
    forge = _get_forge()
    topics = [args.topic] if args.topic else None
    logger.info("Distilling from notebook %s...", args.notebook[:8])
    result = forge.distill(
        args.notebook, topics=topics, count=args.count,
        delay=args.delay, on_progress=_progress_callback,
    )
    logger.info("\n  %s Q&A pairs generated", len(result.qa_pairs))
    logger.info("  %s stored in Nexus", len(result.nexus_ids))
    logger.info("  %s errors", len(result.errors))
    logger.info("  Duration: %ss", result.duration_seconds)

    if args.output:
        outpath = Path(args.output)
        outpath.parent.mkdir(parents=True, exist_ok=True)
        with open(outpath, "w", encoding="utf-8") as f:
            for pair in result.qa_pairs:
                f.write(json.dumps(pair.to_dict(), ensure_ascii=False) + "\n")
        logger.info("  Written to: %s", outpath)


def cmd_decompose(args: argparse.Namespace) -> None:
    """Decompose a plan into steps."""
    forge = _get_forge()
    plan_text = args.plan
    if Path(plan_text).exists():
        plan_text = Path(plan_text).read_text(encoding="utf-8")
    result = forge.decompose(plan_text, notebook_id=args.notebook or "")
    if result.steps:
        logger.info("\n%s steps:\n", len(result.steps))
        for step in result.steps:
            logger.info("  %s. %s", step['step'], step['instruction'][:100])
    else:
        logger.error("%s", result.errors)


def cmd_analyze(args: argparse.Namespace) -> None:
    """Analyze source files."""
    forge = _get_forge()
    logger.info("Analyzing %s files...", len(args.files))
    result = forge.analyze(args.files)
    logger.info("\n  %s insights generated", len(result.qa_pairs))
    for pair in result.qa_pairs[:5]:
        logger.info("\n  Q: %s", pair.question[:80])
        logger.info("  A: %s...", pair.answer[:120])


def cmd_solve(args: argparse.Namespace) -> None:
    """Solve a problem via NLM."""
    forge = _get_forge()
    result = forge.solve(
        args.question,
        context_files=args.files,
        notebook_id=args.notebook or "",
    )
    if result.qa_pairs:
        logger.info("\n%s\n", result.qa_pairs[0].answer)
    else:
        logger.error("%s", result.errors)


def cmd_extract(args: argparse.Namespace) -> None:
    """Extract notebooks from a HAR file."""
    extractor = _get_extractor()
    if args.preview:
        preview = extractor.preview(args.har_file)
        logger.info(json.dumps(preview, indent=2, default=str))
        return

    notebooks = extractor.extract(args.har_file)
    logger.info("\nExtracted %s notebook(s):\n", len(notebooks))
    for nb in notebooks:
        stats = nb.stats()
        logger.info("  %s... — %s", nb.id[:12], nb.name)
        logger.info("    Sources: %s, Docs: %s", stats['sources'], stats['documents'])
        logger.info("    Notes: %s, Conversations: %s", stats['notes'], stats['conversations'])

    if args.save:
        outdir = Path(args.save)
        for nb in notebooks:
            path = extractor.save_notebook(nb, outdir)
            logger.info("  Saved: %s", path)


def cmd_ingest(args: argparse.Namespace) -> None:
    """Ingest HAR content to Nexus."""
    from engine.nexus.client import get_nexus_client
    extractor = _get_extractor()
    client = get_nexus_client()
    notebooks = extractor.extract(args.har_file)
    for nb in notebooks:
        result = extractor.ingest_to_nexus(nb, client)
        logger.info("  %s: %s/%s entries, %s skipped", nb.name, result.stored, result.total, result.skipped)


def cmd_stats(args: argparse.Namespace) -> None:
    """Show NLM usage statistics."""
    engine = _get_engine()
    router = _get_router()

    logger.info("\n═══ NLM Engine Stats ═══")
    for k, v in engine.stats().items():
        logger.info("  %s: %s", k, v)

    logger.info("\n═══ Router Savings ═══")
    report = router.savings_report()
    for k, v in report.items():
        if isinstance(v, dict):
            logger.info("  %s:", k)
            for kk, vv in v.items():
                logger.info("    %s: %s", kk, vv)
        else:
            logger.info("  %s: %s", k, v)


def cmd_forge(args: argparse.Namespace) -> None:
    """Run end-to-end forge pipeline for a topic."""
    forge = _get_forge()
    logger.info("Building knowledge for: %s", args.topic)

    def on_progress(phase: str, current: int, total: int) -> None:
        logger.info("  [%s] %s/%s", phase, current, total)

    result = forge.build_topic(
        args.topic,
        sources=args.sources,
        question_count=args.count,
        on_progress=on_progress,
    )
    logger.info("\n  Notebook: %s", result.notebook_id)
    logger.info("  Q&A pairs: %s", len(result.qa_pairs))
    logger.info("  Stored in Nexus: %s", len(result.nexus_ids))
    logger.info("  Duration: %ss", result.duration_seconds)

    if args.export:
        outpath = Path(args.export)
        forge.export_training(
            result.notebook_id,
            format=args.format or "instruction",
            output_path=str(outpath),
        )
        logger.info("  Exported to: %s", outpath)


# ──── Parser ────

def build_parser() -> argparse.ArgumentParser:
    """Build the CLI argument parser."""
    parser = argparse.ArgumentParser(
        prog="nlm",
        description="NotebookLM CLI — NLM-first knowledge operations",
    )
    sub = parser.add_subparsers(dest="command", help="Command")

    # ask
    p = sub.add_parser("ask", help="Ask a question via NLM-first router")
    p.add_argument("question", help="Question to ask")
    p.add_argument("--notebook", "-n", help="NLM notebook ID")

    # batch-ask
    p = sub.add_parser("batch-ask", help="Batch-ask questions")
    p.add_argument("--file", "-f", help="File with questions (one per line or JSON array)")
    p.add_argument("--notebook", "-n", help="NLM notebook ID")
    p.add_argument("questions", nargs="*", help="Questions as arguments")

    # converse
    p = sub.add_parser("converse", help="Interactive NLM conversation (teacher mode)")
    p.add_argument("--notebook", "-n", required=True, help="NLM notebook ID")

    # create
    p = sub.add_parser("create", help="Create a new notebook")
    p.add_argument("name", help="Notebook name")
    p.add_argument("--sources", "-s", nargs="*", help="Source URLs to add")

    # list
    sub.add_parser("list", help="List all notebooks")

    # add-source
    p = sub.add_parser("add-source", help="Add a source to a notebook")
    p.add_argument("notebook", help="Notebook ID")
    p.add_argument("type", choices=["url", "text", "pdf", "youtube"], help="Source type")
    p.add_argument("value", help="Source value (URL or text)")

    # add-codebase
    p = sub.add_parser("add-codebase", help="Add source files to a notebook")
    p.add_argument("notebook", help="Notebook ID")
    p.add_argument("files", nargs="+", help="File paths")
    p.add_argument("--name", help="Notebook name")

    # generate
    p = sub.add_parser("generate", help="Generate a document from a notebook")
    p.add_argument("notebook", help="Notebook ID")
    p.add_argument("--type", "-t", default="study_guide",
                   choices=["study_guide", "faq", "briefing", "deep_dive", "timeline"],
                   help="Document type")
    p.add_argument("--instructions", "-i", help="Custom instructions")

    # distill
    p = sub.add_parser("distill", help="Distill Q&A pairs from a notebook")
    p.add_argument("notebook", help="Notebook ID")
    p.add_argument("--topic", "-t", help="Topic for question generation")
    p.add_argument("--count", "-c", type=int, default=20, help="Number of Q&A pairs")
    p.add_argument("--delay", "-d", type=float, default=1.5, help="Delay between questions")
    p.add_argument("--output", "-o", help="Output JSONL file")

    # decompose
    p = sub.add_parser("decompose", help="Decompose a plan into steps")
    p.add_argument("plan", help="Plan text or file path")
    p.add_argument("--notebook", "-n", help="Notebook with context")

    # analyze
    p = sub.add_parser("analyze", help="Analyze source files via NLM")
    p.add_argument("files", nargs="+", help="Source file paths")

    # solve
    p = sub.add_parser("solve", help="Solve a problem via NLM")
    p.add_argument("question", help="Problem to solve")
    p.add_argument("--files", "-f", nargs="*", help="Context files")
    p.add_argument("--notebook", "-n", help="Notebook with context")

    # extract
    p = sub.add_parser("extract", help="Extract notebooks from a HAR file")
    p.add_argument("har_file", help="Path to .har file")
    p.add_argument("--preview", "-p", action="store_true", help="Preview only")
    p.add_argument("--save", "-s", help="Save directory")

    # ingest
    p = sub.add_parser("ingest", help="Ingest HAR content to Nexus")
    p.add_argument("har_file", help="Path to .har file")

    # stats
    sub.add_parser("stats", help="Show NLM usage statistics")

    # forge
    p = sub.add_parser("forge", help="End-to-end knowledge building")
    p.add_argument("topic", help="Topic to build knowledge for")
    p.add_argument("--sources", "-s", nargs="*", help="Source URLs or file paths")
    p.add_argument("--count", "-c", type=int, default=30, help="Q&A pairs to generate")
    p.add_argument("--export", "-e", help="Export JSONL path")
    p.add_argument("--format", choices=["instruction", "chat_ml", "sharegpt"],
                   default="instruction", help="Export format")

    return parser


# ──── Entry Point ────

COMMAND_MAP = {
    "ask": cmd_ask,
    "batch-ask": cmd_batch_ask,
    "converse": cmd_converse,
    "create": cmd_create,
    "list": cmd_list,
    "add-source": cmd_add_source,
    "add-codebase": cmd_add_codebase,
    "generate": cmd_generate,
    "distill": cmd_distill,
    "decompose": cmd_decompose,
    "analyze": cmd_analyze,
    "solve": cmd_solve,
    "extract": cmd_extract,
    "ingest": cmd_ingest,
    "stats": cmd_stats,
    "forge": cmd_forge,
}


def main(argv: Optional[List[str]] = None) -> None:
    """CLI entry point."""
    parser = build_parser()
    args = parser.parse_args(argv)

    if not args.command:
        parser.print_help()
        return

    handler = COMMAND_MAP.get(args.command)
    if handler:
        handler(args)
    else:
        parser.print_help()


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    main()
