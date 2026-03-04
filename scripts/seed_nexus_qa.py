"""seed_nexus_qa.py — Seed core Q&A pairs into the Nexus knowledge base.

These are the architectural and operational questions that agents ask repeatedly.
Seeding them ensures the Q&A cache (Tier 1 of the NLM-first pipeline) has
immediate hits, saving LLM compute on every future lookup.

Usage:
    python scripts/seed_nexus_qa.py
    python scripts/seed_nexus_qa.py --dry-run   # preview without writing
    python scripts/seed_nexus_qa.py --force     # re-write even if already present
"""
from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path
from typing import List, Tuple

PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

# ──── Q&A corpus ─────────────────────────────────────────────────────────────
# (question, answer, category)
QA_PAIRS: List[Tuple[str, str, str]] = [

    # ── Architecture ──────────────────────────────────────────────────────────
    (
        "What is CosySim?",
        "CosySim is a multi-scene AI simulation framework (v0.85b) built on a custom MCP pipeline "
        "with LMStudio v1 API integration and Nexus knowledge system. It orchestrates virtual agents "
        "across 16 interactive scenes, each a self-contained Flask+Socket.IO web app with its own "
        "LLM agents, MCP skill packs, game logic, and real-time state. The engine includes 214+ MCP "
        "tools, 25+ @skill packs, 26-interceptor governance with auto-registry, and a local LMStudio "
        "GPU backend (localhost:1234).",
        "architecture",
    ),
    (
        "What is the MCPFramework?",
        "MCPFramework is the root singleton (get_framework()) that holds the entire MCP state tree. "
        "It contains MCPSceneNode (per-scene state), MCPCharacterNode (per-character state: stats, "
        "inventory, relationships), MCPTimer (scheduled events), and is auto-persisted if "
        "framework.state_persistence is enabled. All mutable game state must be synced to this tree — "
        "never stored in local Python variables.",
        "architecture",
    ),
    (
        "How does the interceptor pipeline work?",
        "The InterceptorPipeline is a chain of 26 interceptors (auto-discovered via @register_interceptor) "
        "that wrap every LLM call. pre_call() methods run before the LLM (inject system prompts, modify "
        "request). post_call() methods run after (strip artifacts, extract tags, modify response). "
        "Interceptors are in engine/agents/interceptors/ as individual modules. Priority controls order. "
        "INTERCEPTOR_CACHE singleton holds the built pipeline. AgentGovernor enforces governance context "
        "through the chain.",
        "architecture",
    ),
    (
        "What is Nexus?",
        "Nexus (at localhost:8700) is CosySim's central knowledge management system. It has 3 layers: "
        "1) Q&A Cache — instant lookup of previously answered questions. "
        "2) FTS5 full-text search — searches across all knowledge entries. "
        "3) NLM (NotebookLM) research — deep Gemini-powered research for unknown questions. "
        "Accessed via get_nexus_client() in Python, or python -m engine.nexus.bridge CLI, or 214 MCP tools. "
        "Contains entries, rules, Q&A pairs, prompts, sessions, memories.",
        "architecture",
    ),
    (
        "What is the NLM-first workflow?",
        "Every question goes through a 4-tier pipeline before hitting the local GPU: "
        "Tier 1: Nexus Q&A Cache (instant, free) — cached prior answers. "
        "Tier 2: Nexus FTS5 Search (fast, free) — synthesise from knowledge entries. "
        "Tier 3: NotebookLM (free Gemini compute) — notebook-backed research, auto-stored. "
        "Tier 4: LMStudio LLM (local GPU) — last resort only. "
        "Use nexus_smart_query() as the primary entry point. Every LLM answer is auto-cached for Tier 1.",
        "architecture",
    ),
    (
        "How are skills defined and used?",
        "Skills use the @skill decorator from engine/skills/skill.py: "
        "@skill(pack='scene_name', description='LLM-facing description', category='game', cooldown=5.0). "
        "Skills are the only way LLM agents call tools. They return strings for LLM consumption. "
        "Access the running scene via BaseScene.get_active_scene('name'). "
        "Register skills by importing the skills module in the scene's __init__.py. "
        "21 builtin skill packs (188+ skills) are in engine/skills/builtin/.",
        "architecture",
    ),
    (
        "What is the scheduler daemon?",
        "SchedulerDaemon (engine/nexus/scheduler_daemon.py) manages 50 recurring background tasks. "
        "Schedules: 'daily' (24h), 'weekly' (7d), 'every_Nh' (N hours), 'every_Nm' (N minutes). "
        "Tasks include: news fetch, Q&A mining, model training, cookie health check (daily), "
        "cookie auto-refresh (every 72h via CDP), test suite benchmark (weekly). "
        "Adding a task requires updating 6 test files that assert count==50.",
        "system",
    ),
    (
        "How does the Google cookie/auth system work?",
        "Google auth cookies for NLM, Colab, and GitHub Copilot are stored in data/accounts/pool.json "
        "via GoogleAccountPool. har_capture.py extracts fresh cookies: CDP mode connects to running Chrome "
        "port 9222 and calls Network.getCookies() silently in ~1s. Scheduler task #49 (cookie-auto-refresh) "
        "runs this every 72h automatically. Task #48 (cookie-health-check) alerts Nexus if cookies go stale. "
        "Drop a .har file into data/hars/ and har_watchfolder.py auto-imports it within 30s.",
        "system",
    ),

    # ── Development conventions ───────────────────────────────────────────────
    (
        "What are the Python coding conventions for CosySim?",
        "Absolute imports only (from engine.config import get_config — never relative). "
        "Type hints required on all function signatures. Google-style docstrings. "
        "4 spaces, double quotes, f-strings. Logging via logger = logging.getLogger(__name__) — never print(). "
        "Config via get_config().get('dot.path', default) — never hardcode ports/paths/model names. "
        "All mutable state must sync to MCPFramework tree. @skill for any LLM-callable function.",
        "conventions",
    ),
    (
        "How do I run the test suite?",
        "Full suite: python -m pytest tests/ -v --tb=short --ignore=tests/test_agent_loop.py --ignore=tests/live_wire_test.py\n"
        "Fast subset: python -m pytest tests/test_scheduler_daemon.py tests/test_autonomy_skills.py -q\n"
        "Time it: python scripts/test_timer.py run\n"
        "Compare runs: python scripts/test_timer.py compare\n"
        "The suite has 8,811+ tests across 176+ files. Typically ~17 minutes full run.",
        "testing",
    ),
    (
        "How do I add a new scheduler task?",
        "1. Write the callback: def _my_task_callback() -> Dict[str, Any]: ...\n"
        "2. Register in _register_builtin_tasks(): daemon.register('my-task', 'Description', 'daily', _my_task_callback)\n"
        "3. Update count assertion in 6 test files (currently 50): test_scheduler_daemon.py, "
        "test_autonomy_skills.py (×2), test_master_notebook_builder.py, test_qa_expander.py, "
        "test_router_finetune_cycle.py, test_faction_politics.py\n"
        "Schedules: 'daily', 'weekly', 'every_Nh', 'every_Nm'",
        "conventions",
    ),
    (
        "What git commit conventions does CosySim use?",
        "Conventional commits: feat:, fix:, docs:, test:, chore:, refactor:. "
        "Always include: Co-authored-by: Copilot <223556219+Copilot@users.noreply.github.com>. "
        "Always use git --no-pager. Examples: "
        "'feat: add CDP cookie capture', 'fix(nexus/client): handle JSON-string tags field'",
        "conventions",
    ),

    # ── Key singletons ────────────────────────────────────────────────────────
    (
        "What are the key singletons in CosySim?",
        "get_framework() → MCPFramework (root state tree)\n"
        "get_character_registry() → CharacterRegistry\n"
        "get_dialog_system() → DialogSystem\n"
        "get_rules_engine() → SceneRulesEngine\n"
        "get_scene_state_manager() → SceneStateManager\n"
        "get_governor() → AgentGovernor\n"
        "get_router() → AgentRouter\n"
        "get_nexus_client() → NexusClient\n"
        "get_orchestrator() → InferenceOrchestrator (multi-model routing)\n"
        "get_account_pool() → GoogleAccountPool",
        "architecture",
    ),
    (
        "What external services does CosySim use and on what ports?",
        "LMStudio: localhost:1234 (LLM inference, v1 API, always running)\n"
        "ComfyUI: localhost:8188 (image/video generation)\n"
        "Nexus KMS: localhost:8700 (knowledge management)\n"
        "TTS Server: localhost:8600 (Qwen3 TTS)\n"
        "Web Bridge: localhost:8601 (Socket.IO real-time)\n"
        "Hub: localhost:8500 (scene hub + navigation)\n"
        "Nexus Panel: localhost:5570 (dashboard + Librarian)\n"
        "Chrome CDP: localhost:9222 (remote debugging for cookie capture)",
        "system",
    ),

    # ── Nexus usage ───────────────────────────────────────────────────────────
    (
        "How do I search Nexus from the CLI?",
        "python -m engine.nexus.bridge search 'interceptor pipeline'\n"
        "python -m engine.nexus.bridge ask 'How does state management work?'\n"
        "python -m engine.nexus.bridge health\n"
        "python -m engine.nexus.bridge store 'Title' 'Content' --type note --category dev\n"
        "python -m engine.nexus.bridge qa 'Question?' 'Answer.'\n"
        "python -m engine.nexus.bridge rules global\n"
        "Nexus must be running at localhost:8700.",
        "system",
    ),
    (
        "What Nexus content types exist?",
        "note: general knowledge, observations\n"
        "code: code snippets, patterns, templates\n"
        "prompt: system/agent prompts (versioned)\n"
        "document: design docs, specs, guides\n"
        "transcript: YouTube/video transcripts\n"
        "research: research session artifacts\n"
        "memory: agent memories/observations\n"
        "history: session histories, changelogs\n"
        "plan: implementation plans\n"
        "decision: architecture decisions",
        "conventions",
    ),
    (
        "How does NotebookLM integration work?",
        "NLM is accessed via the NLM direct client (engine/integrations/nlm_direct_client.py) using "
        "Google auth cookies from the pool. It posts to notebooklm.google.com/_/LabsTailwindUi/data/... "
        "with f.req=url_encoded_json. Responses are chunked wrb.fr JSON. "
        "We have unlimited free access: create/delete notebooks, upload sources, converse with Gemini. "
        "Used for: agent Q&A (free Gemini compute), knowledge distillation, onboarding source. "
        "Scheduler runs NLM tasks via the cdp-mine and news-distill-nlm tasks.",
        "architecture",
    ),
    (
        "What is PROJECT_JOURNAL.md?",
        "docs/PROJECT_JOURNAL.md is a 5,000+ word project narrative covering the full arc from v0.51b "
        "to v0.84b across 17 chapters. It documents: the founding architecture, every major breakthrough "
        "(NLM discovery, Colab bypass, GitHub Copilot API, training flywheel), the philosophy, and "
        "current state. It is the primary agent onboarding/alignment source. Also stored in Nexus "
        "(id: 13a12912e5cc4a3a). Designed to be uploaded to NotebookLM as a knowledge source.",
        "system",
    ),

    # ── Training ──────────────────────────────────────────────────────────────
    (
        "What is the training flywheel?",
        "The training flywheel collects data passively from every live interaction via DataCollector, "
        "stores it in training/datasets/collected/ as .jsonl files, and uses scheduler tasks to "
        "periodically trigger fine-tune jobs. ModelZoo defines 14+ trainable model types. "
        "DataCollector.collect_tool_call(), collect_conversation(), collect_grammar_error(), etc. "
        "are wired into VirtualAgent and the interceptor pipeline. Training uses Llama-3.2-3B LoRA "
        "(coder), Qwen3 LoRA (TTS), Orpheus LoRA (voice). Results benchmarked and stored in Nexus.",
        "training",
    ),
    (
        "What is the router model?",
        "The router model (Qwen 270M) classifies every incoming agent request to route it to the "
        "appropriate LMStudio model profile (big/small/draft) or upstream service. "
        "Trained on router_data collected by RouterDataCollector. v3 dataset has 2,080 examples, "
        "16 classes. The finetune cycle runs via 'router-finetune-cycle' scheduler task. "
        "The router saves significant VRAM by avoiding loading the 70B model for simple requests.",
        "training",
    ),
]


# ──── Main ─────────────────────────────────────────────────────────────────────

def main() -> None:
    parser = argparse.ArgumentParser(description="Seed core Q&A pairs into Nexus")
    parser.add_argument("--dry-run", action="store_true", help="Preview without writing")
    parser.add_argument("--force", action="store_true", help="Re-write even if pair exists")
    args = parser.parse_args()

    from engine.nexus.client import get_nexus_client
    client = get_nexus_client()

    # Check existing Q&A to skip duplicates (unless --force)
    existing: set = set()
    if not args.force:
        try:
            pairs = client.find_qa("", limit=500)
            for p in pairs:
                q = getattr(p, "question", None) or (p.get("question") if isinstance(p, dict) else None)
                if q:
                    existing.add(q.strip().lower())
        except Exception:
            pass

    stored = 0
    skipped = 0
    failed = 0

    print(f"\n-- Nexus Q&A Seeder -------------------------------------------")
    print(f"  Pairs to seed : {len(QA_PAIRS)}")
    print(f"  Existing      : {len(existing)}")
    print(f"  Dry run       : {args.dry_run}")
    print()

    for question, answer, category in QA_PAIRS:
        key = question.strip().lower()
        if key in existing and not args.force:
            print(f"  SKIP  {question[:60]}")
            skipped += 1
            continue

        if args.dry_run:
            print(f"  DRY   [{category}] {question[:70]}")
            stored += 1
            continue

        try:
            client.add_qa(question=question, answer=answer, category=category)
            print(f"  ✓     [{category}] {question[:70]}")
            stored += 1
            time.sleep(0.1)  # gentle rate limiting
        except Exception as exc:
            print(f"  ✗     {question[:60]} — {exc}")
            failed += 1

    print(f"\n  Stored : {stored}")
    print(f"  Skipped: {skipped}")
    print(f"  Failed : {failed}")

    if not args.dry_run and stored > 0:
        # Store a record in Nexus
        try:
            client.add_entry(
                f"Q&A Seed Run — {stored} pairs stored",
                f"seed_nexus_qa.py ran at {time.strftime('%Y-%m-%d %H:%M:%S')}.\n"
                f"Stored: {stored}, Skipped: {skipped}, Failed: {failed}\n"
                f"Categories: architecture, conventions, testing, system, training",
                content_type="note",
                category="system",
                tags=["qa-seed", "nexus-setup"],
            )
        except Exception:
            pass

        print(f"\n  Nexus Q&A cache now has {stored + len(existing)} pairs.")
        print(f"  Tier 1 lookup (instant) is operational.\n")


if __name__ == "__main__":
    main()
