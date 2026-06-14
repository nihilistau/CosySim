"""
bootstrap_notebooks.py — Creates and seeds purpose-built NLM notebooks for the
CosySim + Copilot system.

Notebooks created:
  1. cosysim-architecture  — README, docs/, engine/ structure overview
  2. copilot-instructions  — all .github rules, agents, instructions
  3. copilot-session-history — recent session checkpoints from Nexus
  4. cosysim-codebase      — engine/ Python source (chunked)

These notebooks become the knowledge backbone for:
  - Copilot planning (ask architecture/design questions before coding)
  - Local agent instructions (retrieve rules via NLM)
  - Session history distillation (extract Q&A from past work)
  - Code analysis (understand patterns, detect issues)

Usage:
    python engine/nexus/bootstrap_notebooks.py                    # bootstrap all
    python engine/nexus/bootstrap_notebooks.py --notebook arch    # single notebook
    python engine/nexus/bootstrap_notebooks.py --refresh          # update stale sources
    python engine/nexus/bootstrap_notebooks.py --distill          # distill Q&A from notebooks

Called by:
  - scheduler_daemon "notebook-bootstrap" task (weekly)
  - Manual CLI bootstrap
  - Post-deploy hook
"""
from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import os
import sys
import time
import urllib.parse
import urllib.request
import urllib.error
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Optional

logger = logging.getLogger(__name__)

# ── Configuration ─────────────────────────────────────────────────────────────

def _get_nexus_url() -> str:
    env = os.environ.get("NEXUS_URL")
    if env:
        return env
    from engine.port_registry import get_service_url
    return get_service_url("nexus")


def _get_nlm_proxy_url() -> str:
    env = os.environ.get("NLM_PROXY_URL")
    if env:
        return env
    from engine.port_registry import get_service_url
    return get_service_url("nlm_proxy")
REPO_ROOT = Path(__file__).resolve().parent.parent.parent
HOME = Path.home()

# Track bootstrap state
STATE_FILE = REPO_ROOT / ".github" / "hooks" / "logs" / "notebook_bootstrap.json"

# Max chars per source text upload
MAX_SOURCE_CHARS = 50_000
BROWSER_BUNDLE_MAX_CHARS = 500_000
SCHEDULED_DISTILL_INTERVAL_HOURS = 24 * 7
SOURCE_WAIT_TIMEOUT_SECONDS = 90
SOURCE_WAIT_POLL_SECONDS = 3
ARGUS_ASK_TIMEOUT_SECONDS = 180

# Standard distillation questions asked for each notebook after seeding
ARCHITECTURE_QUESTIONS = [
    "What are the core components of the CosySim architecture and how do they interact?",
    "How does the MCPFramework state tree work and what are the key node types?",
    "What is the InterceptorPipeline and how does it govern agent behavior?",
    "How does the Nexus knowledge system store and retrieve information?",
    "What are the 4 tiers of the LibrarianService routing pipeline?",
    "How does LMStudio integrate with CosySim for inference?",
    "What is the @skill decorator pattern and how do skills get registered?",
    "How does the DialogSystem manage conversation threading?",
    "What are the 21 skill packs and their purposes?",
    "How does the KnowledgeCoverageEvaluator measure and improve knowledge completeness?",
    "What scheduled tasks run in the daemon and what do they do?",
    "How should local agents interact with the MCP tools?",
    "What is the NLM integration flow from question to stored Q&A?",
    "What are the key testing patterns and mock strategies used?",
    "How does the governance system enforce rules and prevent violations?",
]

COPILOT_QUESTIONS = [
    "What are the core rules Copilot must follow when working on CosySim?",
    "How should Copilot use Nexus before and after any task?",
    "What is the NLM-first workflow and its 4-tier pipeline?",
    "How does Copilot use NotebookLM to plan and decompose tasks?",
    "What are the Python coding conventions for CosySim?",
    "How should tests be written and what mocking patterns are required?",
    "What are the available custom agents and when should each be used?",
    "How does Copilot handle session compaction and context preservation?",
    "What are the git commit conventions and required trailers?",
    "How should Copilot set up the system so local agents can run autonomously?",
    "What is the correct way to add a new skill pack?",
    "How should new scenes be structured and what overrides are required?",
    "What are the configuration conventions and how should ports/paths be handled?",
    "What are the consensus gates and when must they be checked?",
    "How should Copilot store revelations and architecture decisions?",
]

HISTORY_QUESTIONS = [
    "What are the most important architectural decisions made recently?",
    "What patterns of work have been most productive?",
    "What issues keep recurring that should be addressed systematically?",
    "What features have been built and what is their current status?",
    "What were the key insights from NLM integration work?",
    "What testing gaps or failures have been identified?",
    "What are the next logical steps based on recent work?",
    "What performance or reliability issues have been discovered?",
    "What Nexus improvements have had the most impact?",
    "What should local agents know about the system's current state?",
]

CONTROL_QUESTIONS = [
    "What hook, checkpoint, and compaction surfaces must stay healthy for the Copilot control plane to work continuously?",
    "What immediate context packet should Copilot reload on startup so work can continue without re-deriving the whole session?",
    "How should Nexus, NotebookLM, and the hook/runtime layers cooperate to store goals, rules, changelogs, todos, settings, and version context?",
    "What are the highest-priority integration tasks across NLM, Colab, Nexus, Copilot, ARGUS, training, LMStudio, auth, UI, scenes, launcher, and CLI?",
    "What smart chain-prompting or double-prompting workflow should drive this control notebook and its downstream Nexus artifacts?",
    "What action plan should local agents follow to keep this control plane healthy and compounding?",
]


# ── NLM API Helpers ───────────────────────────────────────────────────────────

def _nlm_post(path: str, data: dict, timeout: int = 30) -> Optional[dict]:
    """POST to NLM proxy."""
    try:
        body = json.dumps(data).encode()
        req = urllib.request.Request(
            f"{_get_nlm_proxy_url()}{path}", data=body, method="POST",
            headers={"Content-Type": "application/json"},
        )
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return json.loads(resp.read())
    except Exception as e:
        logger.warning("NLM POST %s failed: %s", path, e)
        return None


def _nlm_get(path: str, timeout: int = 10) -> Optional[dict]:
    """GET from NLM proxy."""
    try:
        req = urllib.request.Request(
            f"{_get_nlm_proxy_url()}{path}",
            headers={"Accept": "application/json"},
        )
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return json.loads(resp.read())
    except Exception as e:
        logger.warning("NLM GET %s failed: %s", path, e)
        return None


def _nlm_delete(path: str, timeout: int = 30) -> Optional[dict]:
    """DELETE against the NLM proxy."""
    try:
        req = urllib.request.Request(
            f"{_get_nlm_proxy_url()}{path}",
            method="DELETE",
            headers={"Accept": "application/json"},
        )
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return json.loads(resp.read())
    except Exception as e:
        logger.warning("NLM DELETE %s failed: %s", path, e)
        return None


def _nexus_post(path: str, data: dict) -> Optional[dict]:
    """POST to Nexus API."""
    try:
        body = json.dumps(data).encode()
        req = urllib.request.Request(
            f"{_get_nexus_url()}{path}", data=body, method="POST",
            headers={"Content-Type": "application/json"},
        )
        with urllib.request.urlopen(req, timeout=10) as resp:
            return json.loads(resp.read())
    except Exception as e:
        logger.warning("Nexus POST %s failed: %s", path, e)
        return None


def _nexus_search(query: str, category: str = "", limit: int = 20) -> list[dict]:
    """Search Nexus for entries."""
    try:
        params = urllib.parse.urlencode({
            "q": query,
            "limit": limit,
            **({"category": category} if category else {}),
        })
        req = urllib.request.Request(
            f"{_get_nexus_url()}/api/search?{params}",
            headers={"Accept": "application/json"},
        )
        with urllib.request.urlopen(req, timeout=10) as resp:
            data = json.loads(resp.read())
        if isinstance(data, dict):
            return data.get("results", data.get("data", [])) or []
        return data or []
    except Exception:
        return []


# ── State Management ──────────────────────────────────────────────────────────

def _load_state() -> dict:
    if STATE_FILE.exists():
        try:
            return json.loads(STATE_FILE.read_text())
        except Exception:
            pass
    return {"notebooks": {}}


def _save_state(state: dict) -> None:
    STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
    state["last_bootstrap"] = datetime.now(timezone.utc).isoformat()
    STATE_FILE.write_text(json.dumps(state, indent=2))


# ── Source Assembly ───────────────────────────────────────────────────────────

def _collect_architecture_sources() -> list[dict]:
    """Collect documents for the architecture notebook."""
    sources = []

    files = [
        (REPO_ROOT / "README.md", "CosySim README"),
        (REPO_ROOT / "docs" / "ARCHITECTURE.md", "CosySim Architecture"),
        (REPO_ROOT / "docs" / "SYSTEM_AUDIT.md", "System Audit v0.59b"),
        (REPO_ROOT / "docs" / "NEXUS.md", "Nexus KMS Guide"),
        (REPO_ROOT / "docs" / "SKILLS.md", "Skills Reference"),
        (REPO_ROOT / "docs" / "AGENT_ONBOARDING.md", "Agent Onboarding"),
        (REPO_ROOT / "docs" / "MCP.md", "MCP Framework Guide"),
        (REPO_ROOT / "ROADMAP.md", "CosySim Roadmap"),
        (REPO_ROOT / "CHANGELOG.md", "CHANGELOG (recent)"),
    ]

    for path, title in files:
        if path.exists():
            content = path.read_text(encoding="utf-8", errors="replace")
            # For CHANGELOG, take the last 8000 chars (most recent)
            if "CHANGELOG" in title:
                content = content[:8000]
            else:
                content = content[:MAX_SOURCE_CHARS]
            sources.append({"title": title, "content": content, "type": "text"})

    # Add engine structure overview (generated)
    engine_overview = _generate_engine_overview()
    if engine_overview:
        sources.append({
            "title": "Engine Module Overview",
            "content": engine_overview,
            "type": "text",
        })

    return sources


def _collect_copilot_instruction_sources() -> list[dict]:
    """Collect all Copilot instructions and agent definitions."""
    sources = []

    # Global instructions
    global_inst = HOME / ".copilot" / "copilot-instructions.md"
    if global_inst.exists():
        sources.append({
            "title": "Global Copilot Instructions",
            "content": global_inst.read_text(encoding="utf-8", errors="replace")[:MAX_SOURCE_CHARS],
            "type": "text",
        })

    # Project instructions
    project_inst = REPO_ROOT / ".github" / "copilot-instructions.md"
    if project_inst.exists():
        sources.append({
            "title": "CosySim Project Instructions",
            "content": project_inst.read_text(encoding="utf-8", errors="replace")[:MAX_SOURCE_CHARS],
            "type": "text",
        })

    # Path-specific instructions (merged into one document for efficiency)
    instructions_dir = REPO_ROOT / ".github" / "instructions"
    if instructions_dir.exists():
        merged = ["# CosySim Path-Specific Instructions\n"]
        for f in sorted(instructions_dir.glob("*.md")):
            merged.append(f"\n---\n## {f.stem}\n")
            merged.append(f.read_text(encoding="utf-8", errors="replace"))
        if len(merged) > 1:
            sources.append({
                "title": "CosySim Path-Specific Instructions",
                "content": "\n".join(merged)[:MAX_SOURCE_CHARS],
                "type": "text",
            })

    # Agent definitions (merged)
    agents_dir = REPO_ROOT / ".github" / "agents"
    if agents_dir.exists():
        merged = ["# CosySim Custom Agents\n"]
        for f in sorted(agents_dir.glob("*.md")):
            merged.append(f"\n---\n## {f.stem}\n")
            merged.append(f.read_text(encoding="utf-8", errors="replace"))
        if len(merged) > 1:
            sources.append({
                "title": "CosySim Custom Agent Definitions",
                "content": "\n".join(merged)[:MAX_SOURCE_CHARS],
                "type": "text",
            })

    return sources


def _collect_session_history_sources() -> list[dict]:
    """Collect recent session history from the synced copilot-history corpus."""
    sources = []

    # Pull from the same synced history corpus used by session_distillation.
    entries = _nexus_search("session", category="copilot-history", limit=50)
    entries += _nexus_search("checkpoint", category="copilot-history", limit=50)

    if entries:
        merged = ["# Recent Copilot Session History\n"]
        seen = set()
        for e in entries[:30]:  # cap at 30 to avoid source size limits
            if e.get("id") in seen:
                continue
            seen.add(e.get("id"))
            merged.append(f"\n## {e.get('title', 'Untitled')}\n")
            merged.append(e.get("content", "")[:3000])
        sources.append({
            "title": "Recent Session History (from Nexus)",
            "content": "\n".join(merged)[:MAX_SOURCE_CHARS],
            "type": "text",
        })

    # Also pull from session store DB directly
    session_history = _get_recent_session_checkpoints(max_sessions=3)
    if session_history:
        sources.append({
            "title": "Session Checkpoints (direct export)",
            "content": session_history[:MAX_SOURCE_CHARS],
            "type": "text",
        })

    return sources


def _collect_control_plane_sources() -> list[dict]:
    """Collect the strategic control-plane corpus for Copilot's own notebook."""
    from engine.nexus.copilot_context import render_context_template_reference
    from engine.nexus.copilot_hook_control import render_hook_control_reference
    from engine.system_registry import render_system_inventory_text

    sources: list[dict] = []
    files = [
        (REPO_ROOT / "data" / "har_files" / "users_dump_folder" / "BRING_IT_HOME.md", "Bring It Home Directive"),
        (REPO_ROOT / "data" / "har_files" / "users_dump_folder" / "USERS_SYSTEM_PLANS.md", "Users System Plans"),
        (REPO_ROOT / ".github" / "copilot-instructions.md", "CosySim Project Copilot Instructions"),
        (REPO_ROOT / ".github" / "README.md", "Copilot Operating Manual"),
        (REPO_ROOT / "docs" / "AGENT_ONBOARDING.md", "Agent Onboarding"),
        (REPO_ROOT / "docs" / "NOTEBOOKLM.md", "NotebookLM Operating Guide"),
        (REPO_ROOT / "docs" / "NLM_KNOWLEDGE_FLYWHEEL.md", "NotebookLM Knowledge Flywheel"),
        (REPO_ROOT / "README.md", "CosySim README"),
        (REPO_ROOT / "CHANGELOG.md", "CosySim CHANGELOG"),
        (REPO_ROOT / "ROADMAP.md", "CosySim ROADMAP"),
    ]
    for path, title in files:
        if not path.exists():
            continue
        content = path.read_text(encoding="utf-8", errors="replace")
        if title.endswith("CHANGELOG"):
            content = content[:8000]
        else:
            content = content[:MAX_SOURCE_CHARS]
        sources.append({"title": title, "content": content, "type": "text"})

    sources.append(
        {
            "title": "Copilot Context Template Reference",
            "content": render_context_template_reference()[:MAX_SOURCE_CHARS],
            "type": "text",
        }
    )
    sources.append(
        {
            "title": "Copilot Hook Control Runtime",
            "content": render_hook_control_reference()[:MAX_SOURCE_CHARS],
            "type": "text",
        }
    )
    sources.append(
        {
            "title": "Canonical System Inventory",
            "content": render_system_inventory_text(include_catalog=False)[:MAX_SOURCE_CHARS],
            "type": "text",
        }
    )

    return sources


def _get_recent_session_checkpoints(max_sessions: int = 3) -> str:
    """Pull recent session checkpoints directly from the session store DB."""
    import sqlite3
    db_candidates = [
        HOME / ".copilot" / "session-store" / "store.sqlite",
        HOME / ".copilot" / "session-store.db",
    ]
    db = next((p for p in db_candidates if p.exists()), None)
    if not db:
        return ""

    try:
        conn = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
        conn.row_factory = sqlite3.Row
        try:
            sessions = conn.execute(
                "SELECT id, summary, branch FROM sessions ORDER BY created_at DESC LIMIT ?",
                (max_sessions,)
            ).fetchall()

            lines = ["# Recent Session Checkpoints\n"]
            for s in sessions:
                lines.append(f"\n## Session: {s['summary'] or s['id'][:16]} ({s['branch']})\n")
                checkpoints = conn.execute(
                    "SELECT checkpoint_number, title, overview, work_done, next_steps "
                    "FROM checkpoints WHERE session_id = ? ORDER BY checkpoint_number DESC LIMIT 20",
                    (s["id"],)
                ).fetchall()
                for cp in checkpoints:
                    lines.append(f"\n### CP {cp['checkpoint_number']}: {cp['title']}\n")
                    if cp["overview"]:
                        lines.append(f"**Overview:** {cp['overview'][:800]}\n")
                    if cp["work_done"]:
                        lines.append(f"**Work Done:** {cp['work_done'][:600]}\n")
                    if cp["next_steps"]:
                        lines.append(f"**Next Steps:** {cp['next_steps'][:300]}\n")
            return "\n".join(lines)
        finally:
            conn.close()
    except Exception as e:
        logger.warning("Cannot read session store: %s", e)
        return ""


def _generate_engine_overview() -> str:
    """Generate a structured overview of the engine/ module layout."""
    engine_dir = REPO_ROOT / "engine"
    if not engine_dir.exists():
        return ""

    lines = ["# CosySim Engine Module Overview\n"]
    lines.append("Generated from file system scan.\n")

    for subdir in sorted(engine_dir.iterdir()):
        if subdir.is_dir() and not subdir.name.startswith("_"):
            py_files = sorted(subdir.glob("*.py"))
            if py_files:
                lines.append(f"\n## engine/{subdir.name}/\n")
                for f in py_files:
                    if f.name.startswith("_"):
                        continue
                    # Read first docstring line
                    try:
                        content = f.read_text(encoding="utf-8", errors="replace")
                        first_line = ""
                        in_docstring = False
                        for line in content.splitlines():
                            stripped = line.strip()
                            if stripped.startswith('"""') and not in_docstring:
                                in_docstring = True
                                text = stripped[3:].strip().rstrip('"')
                                if text:
                                    first_line = text
                                    break
                            elif in_docstring:
                                if stripped:
                                    first_line = stripped
                                    break
                        lines.append(f"- `{f.name}` — {first_line or '(no docstring)'}")
                    except Exception:
                        lines.append(f"- `{f.name}`")

    return "\n".join(lines)


# ── NLM Notebook Bootstrap ────────────────────────────────────────────────────

def _build_browser_bundle_source(name: str, description: str, sources: list[dict]) -> tuple[str, str]:
    """Aggregate notebook sources into a single browser-ingestible markdown bundle."""
    display_name = name.replace("-", " ").title()
    title = f"{display_name} Source Bundle"
    lines = [
        f"# {title}",
        "",
        f"Notebook: {name}",
        f"Description: {description}",
        "",
        "This source bundle was generated by engine.nexus.bootstrap_notebooks",
        "for the browser-attached ARGUS -> NotebookLM bootstrap path.",
        "",
    ]

    for source in sources:
        source_title = str(source.get("title", "Untitled Source")).strip() or "Untitled Source"
        source_type = str(source.get("type", "text"))
        content = str(source.get("content", "")).strip()
        if not content:
            continue
        lines.extend([
            f"## SOURCE: {source_title}",
            f"Type: {source_type}",
            "",
            content,
            "",
        ])

    bundle = "\n".join(lines).strip()
    return title, bundle[:BROWSER_BUNDLE_MAX_CHARS]


def _browser_seed_notebook_bundle(
    name: str,
    description: str,
    sources: list[dict],
    notebook_url: str | None = None,
) -> Optional[str]:
    """Seed or refresh a notebook via browser-attached ARGUS ingestion."""
    from scripts.nlm_ingest import NLMIngestCrawler

    _, bundle_content = _build_browser_bundle_source(name, description, sources)
    if not bundle_content.strip():
        logger.warning("No content available for browser notebook bootstrap: %s", name)
        return notebook_url

    logger.info("Seeding NotebookLM via ARGUS browser flow: %s", name)
    crawler = NLMIngestCrawler(name, bundle_content, notebook_url=notebook_url)
    return asyncio.run(crawler.run())


def _distill_qa_via_argus(notebook_url: str, questions: list[str], category: str) -> int:
    """Ask notebook questions through browser-attached ARGUS and store answers in Nexus."""
    if not questions:
        return 0

    notebook_id = _nb_id(notebook_url)

    async def _run() -> int:
        from playwright.async_api import async_playwright

        from scripts.argus.config import CDP_URL
        from scripts.argus.tools.__main__ import cmd_ask, find_page

        stored = 0
        async with async_playwright() as pw:
            browser = await pw.chromium.connect_over_cdp(CDP_URL)
            ctx = browser.contexts[0]
            page = await find_page(ctx, notebook_id)
            if page is None:
                page = await ctx.new_page()
                await page.goto(notebook_url, wait_until="domcontentloaded", timeout=30000)
            await page.wait_for_selector("textarea[aria-label='Query box']", timeout=15000)
            await page.wait_for_timeout(5000)

            for question in questions:
                answer = await cmd_ask(
                    ctx,
                    question,
                    notebook_id,
                    ARGUS_ASK_TIMEOUT_SECONDS,
                    raw=True,
                    store=False,
                )
                if not answer:
                    logger.warning("  No browser answer for: %s", question[:60])
                    continue

                result = _nexus_post("/api/qa", {
                    "question": question,
                    "answer": answer,
                    "category": category,
                    "tags": f"nlm,distilled,{category}",
                })
                if result and (result.get("ok") or result.get("id")):
                    stored += 1
                    logger.info("  Stored browser Q&A: %s...", question[:50])
                await asyncio.sleep(1)
        return stored

    return asyncio.run(_run())


def _get_or_create_notebook(name: str, description: str, state: dict) -> Optional[str]:
    """Get existing notebook URL from state, or create via the centralised factory."""
    notebooks = state.get("notebooks", {})
    if name in notebooks:
        return notebooks[name]

    from engine.nexus.nlm_notebook_factory import get_notebook_factory

    factory = get_notebook_factory()
    notebook_id = factory.get_or_create(name, category="bootstrap")
    if notebook_id:
        url = f"https://notebooklm.google.com/notebook/{notebook_id}"
        notebooks[name] = url
        state["notebooks"] = notebooks
        logger.info("  Created: %s", url)
        return url

    logger.warning("Failed to create notebook: %s", name)
    return None


def _add_text_source(notebook_url: str, title: str, content: str) -> bool:
    """Add a text source to a notebook via the NLM proxy."""
    notebook_id = _nb_id(notebook_url)

    result = _nlm_post(f"/notebooks/{notebook_id}/sources/text", {
        "title": title,
        "content": content,
    }, timeout=60)
    if result and (result.get("ok") or result.get("source_id") or result.get("id")):
        logger.info("  Added source: %s", title)
        return True

    result = _nlm_post(f"/notebooks/{notebook_id}/sources", {
        "type": "text",
        "title": title,
        "content": content,
        "notebook_url": notebook_url,
    }, timeout=60)
    if result and result.get("ok"):
        logger.info("  Added source via fallback route: %s", title)
        return True

    result = _nlm_post("/add_source", {
        "notebook_url": notebook_url,
        "source": {"type": "text", "value": content, "title": title},
    }, timeout=60)
    return bool(result and result.get("ok"))


def _nb_id(notebook_url: str) -> str:
    """Extract notebook ID from URL."""
    return notebook_url.rstrip("/").split("/")[-1].split("?")[0]


def _source_hash(title: str, content: str, source_type: str) -> str:
    """Build a stable content hash for a notebook source."""
    payload = json.dumps(
        {"title": title, "content": content, "type": source_type},
        sort_keys=True,
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _parse_timestamp(value: str) -> Optional[datetime]:
    """Parse an ISO timestamp from persisted state."""
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None


def _list_notebook_sources(notebook_url: str) -> list[dict[str, Any]]:
    """List all current sources for a notebook."""
    result = _nlm_get(f"/notebooks/{_nb_id(notebook_url)}/sources", timeout=30)
    if isinstance(result, dict):
        sources = result.get("sources", [])
        return sources if isinstance(sources, list) else []
    return result if isinstance(result, list) else []


def _delete_notebook_source(notebook_url: str, source_id: str) -> bool:
    """Delete a single notebook source by ID."""
    result = _nlm_delete(
        f"/notebooks/{_nb_id(notebook_url)}/sources/{urllib.parse.quote(source_id)}",
        timeout=60,
    )
    return bool(result and (result.get("deleted") or result.get("ok")))


def _delete_matching_sources(notebook_url: str, title: str) -> int:
    """Delete all notebook sources that match the given title."""
    deleted = 0
    for source in _list_notebook_sources(notebook_url):
        if source.get("title") != title:
            continue
        source_id = str(source.get("id", "")).strip()
        if source_id and _delete_notebook_source(notebook_url, source_id):
            deleted += 1
    return deleted


def _wait_for_notebook_sources(
    notebook_url: str,
    timeout: int = SOURCE_WAIT_TIMEOUT_SECONDS,
    interval: int = SOURCE_WAIT_POLL_SECONDS,
) -> bool:
    """Wait until NotebookLM reports all notebook sources as processed."""
    notebook_id = _nb_id(notebook_url)
    result = _nlm_get(
        f"/notebooks/{notebook_id}/sources/wait?timeout={timeout}&interval={interval}",
        timeout=timeout + 10,
    )
    if result and result.get("ready"):
        return True
    logger.warning("Notebook sources not ready for distillation: %s", result)
    return False


def _should_distill(
    nb_state: dict[str, Any],
    questions: list[str],
    distill: bool,
    scheduled: bool,
    sources_changed: bool,
) -> tuple[bool, str]:
    """Decide whether this notebook should run a distillation pass."""
    if not distill or not questions:
        return False, ""

    if not scheduled:
        return True, "manual_distill"

    if sources_changed:
        return True, "sources_changed"

    last_attempt = _parse_timestamp(
        str(nb_state.get("last_distill_attempt_at") or nb_state.get("last_distilled_at") or "")
    )
    if last_attempt is None:
        return True, "first_scheduled_distill"

    if datetime.now(timezone.utc) - last_attempt >= timedelta(hours=SCHEDULED_DISTILL_INTERVAL_HOURS):
        return True, "stale_scheduled_distill"

    return False, ""


def bootstrap_notebook(
    name: str,
    description: str,
    sources: list[dict],
    questions: list[str],
    state: dict,
    distill: bool = True,
    force: bool = False,
    scheduled: bool = False,
    seed_mode: str = "proxy",
) -> dict:
    """
    Bootstrap a single NLM notebook:
    1. Create notebook (if not exists)
    2. Add all text sources
    3. Optionally ask distillation questions and store Q&A in Nexus

    Returns result summary.
    """
    result = {
        "notebook": name,
        "notebook_url": "",
        "sources_added": 0,
        "sources_deleted": 0,
        "qa_stored": 0,
        "distilled": False,
        "distill_reason": "",
        "error": None,
    }

    nb_state = state.get("notebooks_detail", {}).get(name, {})
    detail = state.setdefault("notebooks_detail", {}).setdefault(name, {})
    detail["seed_mode"] = seed_mode

    if seed_mode == "browser_bundle":
        bundle_title, bundle_content = _build_browser_bundle_source(name, description, sources)
        bundle_hash = _source_hash(bundle_title, bundle_content, "text")
        known_bundle_hash = str(detail.get("browser_bundle_hash", ""))
        nb_url = str(detail.get("notebook_url") or state.get("notebooks", {}).get(name) or "").strip()
        sources_changed = force or bundle_hash != known_bundle_hash or not nb_url

        if sources_changed:
            nb_url = _browser_seed_notebook_bundle(
                name,
                description,
                sources,
                notebook_url=nb_url or None,
            )
            if not nb_url:
                result["error"] = "Could not create/find notebook via browser flow"
                return result
            state.setdefault("notebooks", {})[name] = nb_url
            detail["browser_bundle_hash"] = bundle_hash
            detail["browser_bundle_title"] = bundle_title
            detail["notebook_url"] = nb_url
            result["notebook_url"] = nb_url
            result["sources_added"] = 1
        else:
            result["notebook_url"] = nb_url

        should_distill, reason = _should_distill(
            nb_state=detail,
            questions=questions,
            distill=distill,
            scheduled=scheduled,
            sources_changed=sources_changed,
        )
        if should_distill:
            result["distill_reason"] = reason
            logger.info("  Distilling Q&A from %s via ARGUS (%d questions)...", name, len(questions))
            qa_stored = _distill_qa_via_argus(nb_url, questions, category=f"nlm-{name}")
            result["qa_stored"] = qa_stored
            result["distilled"] = True
            detail["last_distill_attempt_at"] = datetime.now(timezone.utc).isoformat()
            if qa_stored > 0:
                detail["last_distilled_at"] = detail["last_distill_attempt_at"]
        return result

    nb_url = _get_or_create_notebook(name, description, state)
    if not nb_url:
        result["error"] = "Could not create/find notebook"
        return result

    seeded_sources = set(nb_state.get("seeded_sources", []))
    source_hashes = dict(nb_state.get("source_hashes", {}))
    sources_changed = False

    for source in sources:
        title = source["title"]
        source_type = str(source.get("type", "text"))
        content = source.get("content", "")
        if not content.strip():
            continue
        current_hash = _source_hash(title, content, source_type)
        known_hash = str(source_hashes.get(title, ""))

        if not force and known_hash == current_hash:
            logger.info("  Source already synced: %s", title)
            continue

        if title in seeded_sources:
            deleted = _delete_matching_sources(nb_url, title)
            result["sources_deleted"] += deleted

        if _add_text_source(nb_url, title, content):
            seeded_sources.add(title)
            source_hashes[title] = current_hash
            result["sources_added"] += 1
            sources_changed = True
        time.sleep(0.5)  # rate limit

    # Update state
    detail["seeded_sources"] = list(seeded_sources)
    detail["source_hashes"] = source_hashes
    detail["notebook_url"] = nb_url
    result["notebook_url"] = nb_url

    should_distill, reason = _should_distill(
        nb_state=detail,
        questions=questions,
        distill=distill,
        scheduled=scheduled,
        sources_changed=sources_changed,
    )

    if should_distill:
        result["distill_reason"] = reason
        if sources_changed and not _wait_for_notebook_sources(nb_url):
            result["error"] = "Notebook sources were not ready for distillation"
            return result
        logger.info("  Distilling Q&A from %s (%d questions)...", name, len(questions))
        qa_stored = _distill_qa(nb_url, questions, category=f"nlm-{name}")
        result["qa_stored"] = qa_stored
        result["distilled"] = True
        detail["last_distill_attempt_at"] = datetime.now(timezone.utc).isoformat()
        if qa_stored > 0:
            detail["last_distilled_at"] = detail["last_distill_attempt_at"]

    return result


def _distill_qa(notebook_url: str, questions: list[str], category: str) -> int:
    """Ask questions to NLM notebook and store answers in Nexus."""
    stored = 0
    nb_id = _nb_id(notebook_url)

    for question in questions:
        # Ask via NLM proxy (single turn, no session ID needed)
        resp = _nlm_post("/chat", {
            "notebook_id": nb_id,
            "question": question,
        }, timeout=120)

        if not resp or not resp.get("answer"):
            logger.warning("  No answer for: %s", question[:60])
            time.sleep(2)
            continue

        answer = resp["answer"]

        # Store in Nexus Q&A
        result = _nexus_post("/api/qa", {
            "question": question,
            "answer": answer,
            "category": category,
            "tags": f"nlm,distilled,{category}",
        })

        if result and (result.get("ok") or result.get("id")):
            stored += 1
            logger.info("  Stored Q&A: %s...", question[:50])
        time.sleep(1)  # rate limit

    return stored


# ── Main Bootstrap Workflow ───────────────────────────────────────────────────

NOTEBOOK_CONFIGS = {
    "arch": {
        "name": "cosysim-architecture",
        "description": "CosySim architecture docs, README, system audit, roadmap",
        "sources_fn": _collect_architecture_sources,
        "questions": ARCHITECTURE_QUESTIONS,
    },
    "copilot": {
        "name": "copilot-instructions",
        "description": "Copilot CLI rules, instructions, and agent definitions for CosySim",
        "sources_fn": _collect_copilot_instruction_sources,
        "questions": COPILOT_QUESTIONS,
    },
    "history": {
        "name": "copilot-session-history",
        "description": "Recent Copilot session history and checkpoints",
        "sources_fn": _collect_session_history_sources,
        "questions": HISTORY_QUESTIONS,
    },
    "control": {
        "name": "copilot-system-control",
        "description": "Copilot control plane, system plans, hook/runtime templates, NotebookLM flywheel guidance",
        "sources_fn": _collect_control_plane_sources,
        "questions": CONTROL_QUESTIONS,
        "seed_mode": "browser_bundle",
    },
}


def bootstrap_all(
    notebooks: list[str] | None = None,
    force: bool = False,
    distill: bool = True,
    scheduled: bool = False,
) -> dict:
    """
    Bootstrap all (or specified) NLM notebooks.

    Args:
        notebooks: List of notebook keys (arch/copilot/history), or None for all.
        force: Re-add all sources even if already seeded.
        distill: Ask distillation questions after seeding.
        scheduled: Apply scheduler-safe distillation rules instead of manual behavior.

    Returns:
        Summary dict with per-notebook results.
    """
    state = _load_state()
    results = {}

    configs = {k: v for k, v in NOTEBOOK_CONFIGS.items()
               if notebooks is None or k in notebooks}

    for key, cfg in configs.items():
        logger.info("Bootstrapping notebook: %s", cfg["name"])
        sources = cfg["sources_fn"]()
        logger.info("  Collected %d sources", len(sources))

        result = bootstrap_notebook(
            name=cfg["name"],
            description=cfg["description"],
            sources=sources,
            questions=cfg["questions"] if distill else [],
            state=state,
            distill=distill,
            force=force,
            scheduled=scheduled,
            seed_mode=str(cfg.get("seed_mode", "proxy")),
        )
        results[key] = result
        _save_state(state)  # save after each notebook
        logger.info("  Result: %s", result)

    _save_state(state)
    return results


def refresh_history_notebook(distill: bool = True) -> dict:
    """Scheduler callback — refresh the session history notebook with latest checkpoints."""
    state = _load_state()
    cfg = NOTEBOOK_CONFIGS["history"]
    sources = cfg["sources_fn"]()

    result = bootstrap_notebook(
        name=cfg["name"],
        description=cfg["description"],
        sources=sources,
        questions=cfg["questions"] if distill else [],
        state=state,
        distill=distill,
        force=True,  # always re-add to capture latest history
        seed_mode=str(cfg.get("seed_mode", "proxy")),
    )
    _save_state(state)
    return result


def _run_control_notebook_followup(results: dict[str, Any]) -> dict[str, Any]:
    """Run the control-notebook flywheel after control bootstrap refreshes."""
    control_result = results.get("control", {})
    if not isinstance(control_result, dict):
        return {"status": "skipped", "reason": "control_result_missing"}
    if control_result.get("error"):
        return {"status": "skipped", "reason": "control_bootstrap_error"}

    notebook_url = str(control_result.get("notebook_url", "")).strip()
    if not notebook_url:
        return {"status": "skipped", "reason": "control_notebook_url_missing"}

    try:
        from engine.nexus.notebooklm_flywheel import run_control_notebook_flywheel

        return run_control_notebook_flywheel(
            notebook_url=notebook_url,
            reason="bootstrap_refresh",
        )
    except Exception as exc:
        logger.error("control notebook follow-up failed: %s", exc)
        return {"status": "error", "error": str(exc)}


def run_notebook_bootstrap() -> dict:
    """Scheduler callback — weekly notebook bootstrap/refresh."""
    try:
        results = bootstrap_all(distill=True, scheduled=True)
        control_flywheel = _run_control_notebook_followup(results)
        return {
            "status": "ok",
            "results": results,
            "control_flywheel": control_flywheel,
        }
    except Exception as e:
        logger.error("notebook-bootstrap failed: %s", e)
        return {"status": "error", "error": str(e)}


# ── CLI Entry Point ───────────────────────────────────────────────────────────

if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")

    args = sys.argv[1:]
    notebook_filter = None
    force = "--force" in args
    distill = "--distill" in args
    refresh = "--refresh" in args

    # --notebook arch/copilot/history/control
    for i, a in enumerate(args):
        if a == "--notebook" and i + 1 < len(args):
            notebook_filter = [args[i + 1]]
            break

    if refresh:
        result = refresh_history_notebook(distill=distill)
    else:
        result = bootstrap_all(notebooks=notebook_filter, force=force, distill=distill)

    print(json.dumps(result, indent=2))
