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

import json
import logging
import os
import sys
import time
import urllib.request
import urllib.error
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

# ── Configuration ─────────────────────────────────────────────────────────────

NEXUS_URL = os.environ.get("NEXUS_URL", "http://localhost:8700")
NLM_PROXY_URL = os.environ.get("NLM_PROXY_URL", "http://localhost:8800")
REPO_ROOT = Path(__file__).resolve().parent.parent.parent
HOME = Path.home()

# Track bootstrap state
STATE_FILE = REPO_ROOT / ".github" / "hooks" / "logs" / "notebook_bootstrap.json"

# Max chars per source text upload
MAX_SOURCE_CHARS = 50_000

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


# ── NLM API Helpers ───────────────────────────────────────────────────────────

def _nlm_post(path: str, data: dict, timeout: int = 30) -> Optional[dict]:
    """POST to NLM proxy."""
    try:
        body = json.dumps(data).encode()
        req = urllib.request.Request(
            f"{NLM_PROXY_URL}{path}", data=body, method="POST",
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
            f"{NLM_PROXY_URL}{path}",
            headers={"Accept": "application/json"},
        )
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return json.loads(resp.read())
    except Exception as e:
        logger.warning("NLM GET %s failed: %s", path, e)
        return None


def _nexus_post(path: str, data: dict) -> Optional[dict]:
    """POST to Nexus API."""
    try:
        body = json.dumps(data).encode()
        req = urllib.request.Request(
            f"{NEXUS_URL}{path}", data=body, method="POST",
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
        params = f"search={urllib.request.quote(query)}&limit={limit}"
        if category:
            params += f"&category={urllib.request.quote(category)}"
        req = urllib.request.Request(
            f"{NEXUS_URL}/api/entries?{params}",
            headers={"Accept": "application/json"},
        )
        with urllib.request.urlopen(req, timeout=10) as resp:
            data = json.loads(resp.read())
        return data.get("data", data) if isinstance(data, dict) else (data or [])
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
    from datetime import datetime, timezone
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
    """Collect recent session checkpoints from Nexus for the history notebook."""
    sources = []

    # Pull session history entries from Nexus
    entries = _nexus_search("session", category="sessions", limit=50)
    entries += _nexus_search("checkpoint", category="copilot-hooks", limit=50)

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

def _get_or_create_notebook(name: str, description: str, state: dict) -> Optional[str]:
    """Get existing notebook URL from state, or create a new one via NLM proxy."""
    notebooks = state.get("notebooks", {})
    if name in notebooks:
        return notebooks[name]

    logger.info("Creating NLM notebook: %s", name)
    result = _nlm_post("/notebooks", {"name": name, "description": description})
    if result and result.get("notebookUrl"):
        url = result["notebookUrl"]
        notebooks[name] = url
        state["notebooks"] = notebooks
        logger.info("  Created: %s", url)
        return url

    logger.warning("Failed to create notebook: %s — %s", name, result)
    return None


def _add_text_source(notebook_url: str, title: str, content: str) -> bool:
    """Add a text source to a notebook via the NLM proxy."""
    result = _nlm_post(f"/notebooks/{_nb_id(notebook_url)}/sources", {
        "type": "text",
        "title": title,
        "content": content,
        "notebook_url": notebook_url,
    }, timeout=60)
    if result and result.get("ok"):
        logger.info("  Added source: %s", title)
        return True
    # Try alternative endpoint
    result = _nlm_post("/add_source", {
        "notebook_url": notebook_url,
        "source": {"type": "text", "value": content, "title": title},
    }, timeout=60)
    return bool(result and result.get("ok"))


def _nb_id(notebook_url: str) -> str:
    """Extract notebook ID from URL."""
    return notebook_url.rstrip("/").split("/")[-1].split("?")[0]


def bootstrap_notebook(
    name: str,
    description: str,
    sources: list[dict],
    questions: list[str],
    state: dict,
    distill: bool = True,
    force: bool = False,
) -> dict:
    """
    Bootstrap a single NLM notebook:
    1. Create notebook (if not exists)
    2. Add all text sources
    3. Optionally ask distillation questions and store Q&A in Nexus

    Returns result summary.
    """
    result = {"notebook": name, "sources_added": 0, "qa_stored": 0, "error": None}

    nb_url = _get_or_create_notebook(name, description, state)
    if not nb_url:
        result["error"] = "Could not create/find notebook"
        return result

    nb_state = state.get("notebooks_detail", {}).get(name, {})
    seeded_sources = set(nb_state.get("seeded_sources", []))

    for source in sources:
        title = source["title"]
        if not force and title in seeded_sources:
            logger.info("  Source already seeded: %s", title)
            continue
        content = source.get("content", "")
        if not content.strip():
            continue
        if _add_text_source(nb_url, title, content):
            seeded_sources.add(title)
            result["sources_added"] += 1
        time.sleep(0.5)  # rate limit

    # Update state
    detail = state.setdefault("notebooks_detail", {}).setdefault(name, {})
    detail["seeded_sources"] = list(seeded_sources)
    detail["notebook_url"] = nb_url

    if distill and questions and result["sources_added"] > 0:
        logger.info("  Distilling Q&A from %s (%d questions)...", name, len(questions))
        qa_stored = _distill_qa(nb_url, questions, category=f"nlm-{name}")
        result["qa_stored"] = qa_stored

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
}


def bootstrap_all(notebooks: list[str] | None = None, force: bool = False, distill: bool = True) -> dict:
    """
    Bootstrap all (or specified) NLM notebooks.

    Args:
        notebooks: List of notebook keys (arch/copilot/history), or None for all.
        force: Re-add all sources even if already seeded.
        distill: Ask distillation questions after seeding.

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
    )
    _save_state(state)
    return result


def run_notebook_bootstrap() -> dict:
    """Scheduler callback — weekly notebook bootstrap/refresh."""
    try:
        results = bootstrap_all(distill=False)  # no distill in scheduler (quota cost)
        return {"status": "ok", "results": results}
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

    # --notebook arch/copilot/history
    for i, a in enumerate(args):
        if a == "--notebook" and i + 1 < len(args):
            notebook_filter = [args[i + 1]]
            break

    if refresh:
        result = refresh_history_notebook(distill=distill)
    else:
        result = bootstrap_all(notebooks=notebook_filter, force=force, distill=distill)

    print(json.dumps(result, indent=2))
