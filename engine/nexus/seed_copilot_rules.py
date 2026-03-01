"""
seed_copilot_rules.py — Seeds all Copilot CLI rules, instructions, and agent
definitions into the Nexus knowledge base.

This makes Nexus the single source of truth for how Copilot and local agents
should behave. Local agents can retrieve governance rules at runtime via
`nexus_get_rules(scope="copilot")` without needing access to the file system.

Sources seeded:
  - ~/.copilot/copilot-instructions.md         → global Copilot rules
  - .github/copilot-instructions.md             → project-level rules
  - .github/instructions/*.instructions.md      → path-specific rules
  - .github/agents/*.agent.md                  → agent definitions
  - CHANGELOG.md                               → version history (latest 200 lines)
  - docs/ARCHITECTURE.md                       → architecture document
  - docs/AGENT_ONBOARDING.md                   → agent onboarding guide

Usage:
    python engine/nexus/seed_copilot_rules.py          # seed all
    python engine/nexus/seed_copilot_rules.py --check  # check which need re-seeding
    python engine/nexus/seed_copilot_rules.py --force  # re-seed all even if unchanged

Called automatically by the scheduler daemon "copilot-rules-refresh" task (weekly).
Called manually to bootstrap a new environment.
"""
from __future__ import annotations

import hashlib
import json
import logging
import os
import sys
import urllib.request
import urllib.error
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

# ── Configuration ─────────────────────────────────────────────────────────────

NEXUS_URL = os.environ.get("NEXUS_URL", "http://localhost:8700")
REPO_ROOT = Path(__file__).resolve().parent.parent.parent
HOME = Path.home()

# State file tracks content hashes so we only re-seed changed files
SEED_STATE_FILE = REPO_ROOT / ".github" / "hooks" / "logs" / "copilot_rules_seed.json"

# ── Source Definitions ────────────────────────────────────────────────────────

def _get_sources() -> list[dict]:
    """Return all source files with their metadata."""
    sources = []

    # Global Copilot instructions
    global_instructions = HOME / ".copilot" / "copilot-instructions.md"
    if global_instructions.exists():
        sources.append({
            "path": global_instructions,
            "title": "[Copilot Rules] Global Instructions",
            "category": "copilot-rules",
            "tags": ["copilot", "global", "instructions", "rules"],
            "scope": "global",
        })

    # Project Copilot instructions
    project_instructions = REPO_ROOT / ".github" / "copilot-instructions.md"
    if project_instructions.exists():
        sources.append({
            "path": project_instructions,
            "title": "[Copilot Rules] CosySim Project Instructions",
            "category": "copilot-rules",
            "tags": ["copilot", "project", "instructions", "cosysim"],
            "scope": "cosysim",
        })

    # Path-specific instructions
    instructions_dir = REPO_ROOT / ".github" / "instructions"
    if instructions_dir.exists():
        for f in sorted(instructions_dir.glob("*.md")):
            name = f.stem.replace(".instructions", "")
            sources.append({
                "path": f,
                "title": f"[Copilot Instruction] {name}",
                "category": "copilot-rules",
                "tags": ["copilot", "instructions", name],
                "scope": f"instructions:{name}",
            })

    # Agent definitions
    agents_dir = REPO_ROOT / ".github" / "agents"
    if agents_dir.exists():
        for f in sorted(agents_dir.glob("*.md")):
            name = f.stem.replace(".agent", "")
            sources.append({
                "path": f,
                "title": f"[Copilot Agent] {name}",
                "category": "copilot-agents",
                "tags": ["copilot", "agent", name],
                "scope": f"agent:{name}",
            })

    # Key documentation
    docs = [
        (REPO_ROOT / "CHANGELOG.md", "[CosySim] CHANGELOG", "copilot-history", ["changelog", "versions", "releases"], None),
        (REPO_ROOT / "README.md", "[CosySim] README", "copilot-rules", ["readme", "overview", "cosysim"], "readme"),
        (REPO_ROOT / "docs" / "ARCHITECTURE.md", "[CosySim] Architecture", "architecture", ["architecture", "design", "cosysim"], "architecture"),
        (REPO_ROOT / "docs" / "AGENT_ONBOARDING.md", "[CosySim] Agent Onboarding", "copilot-rules", ["onboarding", "agents", "local-agents"], "agent-onboarding"),
        (REPO_ROOT / "ROADMAP.md", "[CosySim] ROADMAP", "copilot-plans", ["roadmap", "plans", "future"], "roadmap"),
    ]
    for path, title, category, tags, scope in docs:
        if path.exists():
            sources.append({
                "path": path,
                "title": title,
                "category": category,
                "tags": tags,
                "scope": scope or title,
                "max_chars": 8000,
            })

    return sources


# ── Nexus API Helpers ─────────────────────────────────────────────────────────

def _post(path: str, data: dict, method: str = "POST") -> Optional[dict]:
    """Post to Nexus API."""
    try:
        body = json.dumps(data).encode()
        req = urllib.request.Request(
            f"{NEXUS_URL}{path}", data=body, method=method,
            headers={"Content-Type": "application/json"},
        )
        with urllib.request.urlopen(req, timeout=10) as resp:
            return json.loads(resp.read())
    except urllib.error.HTTPError as e:
        logger.warning("Nexus %s %s: HTTP %d", method, path, e.code)
        return None
    except Exception as e:
        logger.warning("Nexus %s %s failed: %s", method, path, e)
        return None


def _search_existing(title: str) -> Optional[str]:
    """Find existing Nexus entry by exact title. Returns entry ID or None."""
    try:
        encoded = urllib.request.quote(title)
        req = urllib.request.Request(
            f"{NEXUS_URL}/api/entries?search={encoded}&limit=5",
            headers={"Accept": "application/json"},
        )
        with urllib.request.urlopen(req, timeout=5) as resp:
            data = json.loads(resp.read())
        entries = data.get("data", data) if isinstance(data, dict) else data
        for e in (entries or []):
            if e.get("title") == title:
                return e["id"]
    except Exception:
        pass
    return None


def _delete_entry(entry_id: str) -> bool:
    """Delete an existing Nexus entry."""
    try:
        req = urllib.request.Request(
            f"{NEXUS_URL}/api/entries/{entry_id}",
            method="DELETE",
            headers={"Accept": "application/json"},
        )
        with urllib.request.urlopen(req, timeout=5):
            return True
    except Exception:
        return False


# ── State Management ──────────────────────────────────────────────────────────

def _load_state() -> dict:
    if SEED_STATE_FILE.exists():
        try:
            return json.loads(SEED_STATE_FILE.read_text())
        except Exception:
            pass
    return {}


def _save_state(state: dict) -> None:
    SEED_STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
    from datetime import datetime, timezone
    state["last_seed"] = datetime.now(timezone.utc).isoformat()
    SEED_STATE_FILE.write_text(json.dumps(state, indent=2))


def _file_hash(path: Path, max_chars: int = 0) -> str:
    content = path.read_text(encoding="utf-8", errors="replace")
    if max_chars:
        content = content[-max_chars:]  # take tail for CHANGELOG etc
    return hashlib.sha256(content.encode()).hexdigest()[:16]


# ── Core Seed Logic ───────────────────────────────────────────────────────────

def seed_source(source: dict, force: bool = False, state: dict | None = None) -> tuple[str, bool]:
    """
    Seed a single source file into Nexus.

    Returns (status, changed) where status is one of:
    'seeded', 'skipped', 'error'
    """
    if state is None:
        state = {}

    path: Path = source["path"]
    title: str = source["title"]
    category: str = source["category"]
    tags: list[str] = source.get("tags", [])
    max_chars: int = source.get("max_chars", 0)

    try:
        content = path.read_text(encoding="utf-8", errors="replace")
        if max_chars:
            content = content[-max_chars:]  # tail for large files
    except Exception as e:
        logger.warning("Cannot read %s: %s", path, e)
        return "error", False

    # Check if content changed
    current_hash = _file_hash(path, max_chars)
    key = str(path)
    if not force and state.get(key) == current_hash:
        return "skipped", False

    # Delete existing entry if present
    existing_id = _search_existing(title)
    if existing_id:
        _delete_entry(existing_id)

    # Add scope as a rule if it's a rules/instructions file
    content_type = "document"
    if category in ("copilot-rules", "copilot-agents"):
        content_type = "document"

    result = _post("/api/entries", {
        "title": title,
        "content": content,
        "content_type": content_type,
        "category": category,
        "tags": ",".join(tags) if tags else "",
    })

    if result and (result.get("ok") or result.get("id")):
        state[key] = current_hash
        logger.info("Seeded: %s", title)
        return "seeded", True
    else:
        logger.warning("Failed to seed: %s — %s", title, result)
        return "error", False


def seed_all(force: bool = False, check_only: bool = False) -> dict:
    """
    Seed all Copilot rules and documentation into Nexus.

    Args:
        force: Re-seed all sources even if content hasn't changed.
        check_only: Only report what would be seeded without doing it.

    Returns:
        Summary dict with counts.
    """
    sources = _get_sources()
    state = _load_state()

    counts = {"seeded": 0, "skipped": 0, "error": 0, "stale": 0}

    for source in sources:
        path: Path = source["path"]
        title = source["title"]

        if check_only:
            current_hash = _file_hash(path, source.get("max_chars", 0))
            key = str(path)
            if state.get(key) != current_hash:
                print(f"  STALE: {title}")
                counts["stale"] += 1
            else:
                print(f"  OK:    {title}")
            continue

        status, _ = seed_source(source, force=force, state=state)
        counts[status] = counts.get(status, 0) + 1

    if not check_only:
        _save_state(state)
        print(
            f"Copilot rules seed complete: "
            f"{counts['seeded']} seeded, "
            f"{counts['skipped']} skipped, "
            f"{counts['error']} errors"
        )
    else:
        print(f"Check complete: {counts['stale']} stale, "
              f"{len(sources) - counts['stale']} current")

    return counts


# ── Scheduler Callback ────────────────────────────────────────────────────────

def run_copilot_rules_refresh() -> dict:
    """Scheduler callback — re-seed stale Copilot rules (weekly task)."""
    try:
        result = seed_all(force=False)
        return {"status": "ok", **result}
    except Exception as e:
        logger.error("copilot-rules-refresh failed: %s", e)
        return {"status": "error", "error": str(e)}


# ── CLI Entry Point ───────────────────────────────────────────────────────────

if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    args = sys.argv[1:]
    force = "--force" in args
    check = "--check" in args
    seed_all(force=force, check_only=check)
