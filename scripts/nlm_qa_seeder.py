"""NLM Q&A Seeder — batch-ask curated questions to NotebookLM and store answers in Nexus.

Attaches to the running Chrome instance (port 9222) via ARGUS BaseCrawler,
finds the open NLM tab, submits each question from a curated list, waits for
the stable answer, and stores every Q&A pair in Nexus Q&A cache.

This seeds the first lookup tier of the Nexus smart query pipeline, so future
agent questions get instant cache hits instead of burning LMStudio tokens.

Usage:
    python scripts/nlm_qa_seeder.py                    # all questions
    python scripts/nlm_qa_seeder.py --limit 10         # first 10 only
    python scripts/nlm_qa_seeder.py --resume           # skip already-in-Nexus Q&As
    python scripts/nlm_qa_seeder.py --list             # print questions and exit
    python scripts/nlm_qa_seeder.py --category arch    # one category only
    python scripts/nlm_qa_seeder.py --timeout 90       # longer per-question timeout
"""
from __future__ import annotations

import argparse
import asyncio
import json
import logging
import sys
import time
from pathlib import Path
from typing import Optional

PROJECT_ROOT = Path(__file__).parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger(__name__)


# ──── Curated Question Corpus ─────────────────────────────────────────────────
#
# 60 questions across 6 categories. Every answer stored in Nexus becomes an
# instant lookup for future Copilot / local agent queries.

QUESTIONS: list[dict] = [
    # ── Architecture & Core ──────────────────────────────────────────────────
    {"category": "arch", "q": "What is CosySim and what is its core purpose?"},
    {"category": "arch", "q": "How does the MCPFramework work and what is its role as the root singleton?"},
    {"category": "arch", "q": "What are the main components of the CosySim engine and how do they relate?"},
    {"category": "arch", "q": "How does the InterceptorPipeline work and when does it execute?"},
    {"category": "arch", "q": "What is the MCPSceneNode and how does per-scene state work?"},
    {"category": "arch", "q": "What is the MCPCharacterNode and what state does it hold?"},
    {"category": "arch", "q": "How does the EventChain audit logging system work?"},
    {"category": "arch", "q": "What is the AgentGovernor and how does it enforce governance on agent calls?"},
    {"category": "arch", "q": "How does the SceneStateManager differ from the MCPFramework tree?"},
    {"category": "arch", "q": "What is the DialogSystem and how does it thread conversations?"},

    # ── Scenes & Skills ──────────────────────────────────────────────────────
    {"category": "scenes", "q": "How do you create a new CosySim scene from scratch?"},
    {"category": "scenes", "q": "What must every BaseScene subclass override and why?"},
    {"category": "scenes", "q": "How do you register a new skill pack for a scene?"},
    {"category": "scenes", "q": "What does the @skill decorator do and what parameters does it accept?"},
    {"category": "scenes", "q": "How do scene skills access the running scene instance?"},
    {"category": "scenes", "q": "What is the character lifecycle in a scene (on_character_added / on_character_removed)?"},
    {"category": "scenes", "q": "How does the BaseScene.register_health_route() work?"},
    {"category": "scenes", "q": "What are the 15 active CosySim scenes and what does each one do?"},
    {"category": "scenes", "q": "How does the SceneRegistry track and launch scenes?"},
    {"category": "scenes", "q": "What is the PlayerState system and how does it persist across sessions?"},

    # ── LMStudio & Inference ─────────────────────────────────────────────────
    {"category": "lmstudio", "q": "How does the LMStudio v1 API differ from the OpenAI API format?"},
    {"category": "lmstudio", "q": "What is the correct input format for LMStudio v1 API chat requests?"},
    {"category": "lmstudio", "q": "How does stateful conversation threading work with store=true and previous_response_id?"},
    {"category": "lmstudio", "q": "How does the InferenceOrchestrator route requests to different model profiles?"},
    {"category": "lmstudio", "q": "What are the four model profile types (big, small, router, draft)?"},
    {"category": "lmstudio", "q": "How does SSE streaming work in LMStudio v1 (event types, parsing)?"},
    {"category": "lmstudio", "q": "What is the RouterDataCollector and how does it capture training data?"},
    {"category": "lmstudio", "q": "How does infer_processed() capture a streaming generator's return value?"},
    {"category": "lmstudio", "q": "What is the StreamProcessor and what tags does it extract ([MOOD], [IMAGE], etc.)?"},
    {"category": "lmstudio", "q": "How does the AgentRouter classify and route incoming requests?"},

    # ── Nexus & Knowledge ────────────────────────────────────────────────────
    {"category": "nexus", "q": "What are the three layers of the Nexus knowledge database?"},
    {"category": "nexus", "q": "How does the Nexus smart query router work (4-tier pipeline)?"},
    {"category": "nexus", "q": "What is the NLM Forge and how does it use NotebookLM for knowledge distillation?"},
    {"category": "nexus", "q": "How do you store a Q&A pair in Nexus and retrieve it later?"},
    {"category": "nexus", "q": "What is the Nexus scheduler daemon and what are the main task categories?"},
    {"category": "nexus", "q": "How does the Nexus Q&A cache work and why is cache hit rate important?"},
    {"category": "nexus", "q": "What is the NexusClient Python API and its main methods?"},
    {"category": "nexus", "q": "How does the Nexus governance rules engine work?"},
    {"category": "nexus", "q": "What is the deep storage layer in Nexus and what does it archive?"},
    {"category": "nexus", "q": "How does nexus_smart_query differ from nexus_ask?"},

    # ── Agent System & ARGUS ─────────────────────────────────────────────────
    {"category": "agents", "q": "What is ARGUS and what problem does it solve?"},
    {"category": "agents", "q": "How does the ARGUS BaseCrawler attach to a running Chrome instance?"},
    {"category": "agents", "q": "What is the ARGUS network monitor and how does it capture batchexecute calls?"},
    {"category": "agents", "q": "How does the ARGUS eval command work and what JS helpers are available?"},
    {"category": "agents", "q": "How does the ARGUS ask command submit questions to NotebookLM?"},
    {"category": "agents", "q": "What is the VirtualAgent and how does it use the InterceptorPipeline?"},
    {"category": "agents", "q": "What is the CharacterRegistry and how are characters loaded?"},
    {"category": "agents", "q": "How does the governance system enforce rules on agent operations?"},
    {"category": "agents", "q": "What are the seeded characters (lola, viktor, aria, frankie, mira) and their roles?"},
    {"category": "agents", "q": "How does the phone assistant cascade work (4-tier routing)?"},

    # ── Deployment & Integration ─────────────────────────────────────────────
    {"category": "deploy", "q": "What is the correct service start order for CosySim?"},
    {"category": "deploy", "q": "What ports does each CosySim service run on?"},
    {"category": "deploy", "q": "How do you add a new scheduler task and what test files need updating?"},
    {"category": "deploy", "q": "What is the AnythingLLM integration and how is it wired?"},
    {"category": "deploy", "q": "How does the Google account pool manage cookies and when do they expire?"},
    {"category": "deploy", "q": "What is the LMStudio llmster daemon and how does it manage model loading?"},
    {"category": "deploy", "q": "How does the training data flywheel work (collect → evaluate → finetune)?"},
    {"category": "deploy", "q": "What are the ComfyUI integration points and what does each skill do?"},
    {"category": "deploy", "q": "How does the TTS system work (Piper, Orpheus, Qwen3 models)?"},
    {"category": "deploy", "q": "What is the NLM direct client and how does it bypass the browser?"},
]


# ──── Progress tracking ───────────────────────────────────────────────────────

PROGRESS_FILE = PROJECT_ROOT / "data" / "argus" / "qa_seeder_progress.json"


def _load_progress() -> dict:
    if PROGRESS_FILE.exists():
        try:
            return json.loads(PROGRESS_FILE.read_text(encoding="utf-8"))
        except Exception:
            pass
    return {"answered": [], "failed": [], "total_stored": 0}


def _save_progress(progress: dict) -> None:
    PROGRESS_FILE.parent.mkdir(parents=True, exist_ok=True)
    PROGRESS_FILE.write_text(json.dumps(progress, indent=2), encoding="utf-8")


# ──── Nexus helpers ───────────────────────────────────────────────────────────

def _is_in_nexus(question: str) -> bool:
    """Check if this question is already cached in Nexus."""
    try:
        from engine.nexus.client import get_nexus_client
        client = get_nexus_client()
        results = client.search(question[:80])
        # If there are results that look like this Q was already answered, skip
        return any(question[:40].lower() in (r.get("title", "") + r.get("content", "")).lower()
                   for r in (results or []))
    except Exception:
        return False


def _store_in_nexus(question: str, answer: str) -> bool:
    """Store Q&A pair directly in Nexus."""
    try:
        from engine.nexus.client import get_nexus_client
        client = get_nexus_client()
        client.add_qa(question, answer, category="cosysim_knowledge")
        return True
    except Exception as exc:
        logger.warning("Nexus store failed: %s", exc)
        return False


# ──── Core seeder ─────────────────────────────────────────────────────────────

async def run_seeder(
    questions: list[dict],
    timeout: int,
    resume: bool,
    dry_run: bool,
    inter_delay: float,
) -> dict:
    """Attach to Chrome, loop through questions, store answers in Nexus."""
    from scripts.argus.crawlers.base_crawler import BaseCrawler
    from scripts.argus.network_monitor import NetworkMonitor
    from scripts.argus.tools.__main__ import cmd_ask

    progress = _load_progress()
    already_answered = set(progress.get("answered", []))

    stats = {"asked": 0, "answered": 0, "stored": 0, "skipped": 0, "failed": 0}

    monitor = NetworkMonitor()
    crawler = BaseCrawler(monitor=monitor)

    async with crawler:
        ctx = crawler.context
        if ctx is None:
            logger.error("No browser context — is Chrome running on port 9222?")
            return stats

        print(f"\n{'═'*70}")
        print(f"  NLM Q&A Seeder — {len(questions)} questions queued")
        print(f"  Resume: {resume}  |  Timeout: {timeout}s/q  |  Delay: {inter_delay}s between")
        print(f"{'═'*70}\n")

        for i, item in enumerate(questions, 1):
            q = item["q"]
            cat = item["category"]
            q_key = q[:60]

            print(f"[{i:02d}/{len(questions):02d}] [{cat}] {q}")

            # Resume mode: skip if already answered this session
            if resume and q_key in already_answered:
                print(f"  ↳ Skipped (already in progress log)\n")
                stats["skipped"] += 1
                continue

            if dry_run:
                print(f"  ↳ [DRY RUN] Would submit to NLM\n")
                stats["skipped"] += 1
                continue

            stats["asked"] += 1

            answer = await cmd_ask(
                ctx, q, "notebooklm", timeout, raw=False, store=False
            )

            if answer:
                stats["answered"] += 1

                # Store in Nexus
                stored = _store_in_nexus(q, answer)
                if stored:
                    stats["stored"] += 1
                    print(f"  ↳ ✓ Stored in Nexus ({len(answer)} chars)\n")
                else:
                    print(f"  ↳ ⚠ Nexus store failed\n")

                progress["answered"].append(q_key)
                if stored:
                    progress["total_stored"] = progress.get("total_stored", 0) + 1
            else:
                stats["failed"] += 1
                progress["failed"].append(q_key)
                print(f"  ↳ ✗ Timeout or no response\n")

            _save_progress(progress)

            # Pause between questions so NLM has time to settle
            if i < len(questions):
                await asyncio.sleep(inter_delay)

    print(f"\n{'═'*70}")
    print(f"  Done: {stats['answered']}/{stats['asked']} answered, "
          f"{stats['stored']} stored in Nexus, "
          f"{stats['failed']} failed, {stats['skipped']} skipped")
    print(f"  Progress saved: {PROGRESS_FILE}")
    print(f"{'═'*70}\n")

    return stats


# ──── CLI ─────────────────────────────────────────────────────────────────────

def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description="Batch-ask NLM and seed Nexus Q&A cache",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    p.add_argument("--limit",    type=int,   default=0,      help="Max questions (0=all)")
    p.add_argument("--category", type=str,   default="",     help="Filter by category: arch|scenes|lmstudio|nexus|agents|deploy")
    p.add_argument("--timeout",  type=int,   default=60,     help="Per-question NLM timeout in seconds (default 60)")
    p.add_argument("--delay",    type=float, default=3.0,    help="Seconds between questions (default 3)")
    p.add_argument("--resume",   action="store_true",        help="Skip questions already in progress log")
    p.add_argument("--dry-run",  action="store_true",        help="Print questions without submitting")
    p.add_argument("--list",     action="store_true",        help="Print all questions and exit")
    p.add_argument("--reset",    action="store_true",        help="Clear progress log and start fresh")
    return p.parse_args()


def main() -> None:
    args = parse_args()

    if args.reset:
        if PROGRESS_FILE.exists():
            PROGRESS_FILE.unlink()
            print("Progress log cleared.")

    questions = list(QUESTIONS)

    if args.category:
        questions = [q for q in questions if q["category"] == args.category]
        if not questions:
            print(f"ERROR: No questions in category '{args.category}'.")
            print(f"Available: {sorted(set(q['category'] for q in QUESTIONS))}")
            sys.exit(1)

    if args.list:
        cats = sorted(set(q["category"] for q in questions))
        for cat in cats:
            print(f"\n── {cat} ──")
            for i, item in enumerate([q for q in questions if q["category"] == cat], 1):
                print(f"  {i:2d}. {item['q']}")
        print(f"\nTotal: {len(questions)} questions")
        return

    if args.limit:
        questions = questions[: args.limit]

    asyncio.run(run_seeder(
        questions=questions,
        timeout=args.timeout,
        resume=args.resume,
        dry_run=args.dry_run,
        inter_delay=args.delay,
    ))


if __name__ == "__main__":
    main()
