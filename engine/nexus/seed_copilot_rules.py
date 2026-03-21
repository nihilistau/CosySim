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
import sys
from datetime import datetime, timezone
from pathlib import Path

from engine.nexus.client import get_nexus_client
from engine.nexus.copilot_self_config import get_copilot_config

logger = logging.getLogger(__name__)

# ── Configuration ─────────────────────────────────────────────────────────────

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

    # Key documentation
    docs = [
        (REPO_ROOT / "CHANGELOG.md", "[CosySim] CHANGELOG", "copilot-history", ["changelog", "versions", "releases"], None),
        (REPO_ROOT / "README.md", "[CosySim] README", "copilot-rules", ["readme", "overview", "cosysim"], "readme"),
        (REPO_ROOT / "CLAUDE.md", "[CosySim] Claude Code Instructions", "copilot-rules", ["claude-code", "instructions", "cosysim"], "claude-code"),
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


# ── Nexus Sync Helpers ────────────────────────────────────────────────────────

def _get_sync_query(source: dict) -> str:
    """Return the query used to find an existing entry for a source."""
    return source.get("query") or source["title"]


def _entry_exists(source: dict, *, client=None, sync_config=None) -> bool:
    """Check whether an exact matching entry still exists in Nexus."""
    if client is None:
        client = get_nexus_client()
    if sync_config is None:
        sync_config = get_copilot_config()
    return (
        sync_config._find_existing_entry(  # noqa: SLF001 - intentional shared sync helper reuse
            client,
            _get_sync_query(source),
            source["title"],
            source["category"],
        )
        is not None
    )


def _normalise_sync_summary(result: dict) -> dict[str, int]:
    """Normalise CopilotSelfConfig sync results to stored/updated/skipped counts."""
    summary = result.get("summary", result)
    return {
        "stored": summary.get("stored", summary.get("total_stored", 0)),
        "updated": summary.get("updated", summary.get("total_updated", 0)),
        "skipped": summary.get("skipped", summary.get("total_skipped", 0)),
    }


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


def _read_source_content(source: dict) -> str:
    """Read source content exactly as the seeder would mirror it."""
    content = source["path"].read_text(encoding="utf-8", errors="replace")
    max_chars = source.get("max_chars", 0)
    if max_chars:
        content = content[-max_chars:]
    return content


def _build_sync_targets(sync_config=None) -> list[dict]:
    """Build the full set of Copilot mirror targets expected in Nexus."""
    if sync_config is None:
        sync_config = get_copilot_config()

    targets: list[dict] = []
    seen: set[tuple[str, str]] = set()

    def _add_target(target: dict) -> None:
        key = (target["title"], target["category"])
        if key in seen:
            return
        seen.add(key)
        targets.append(target)

    for source in _get_sources():
        _add_target(dict(source))

    if hasattr(sync_config, "list_instructions"):
        for info in sync_config.list_instructions():
            _add_target({
                "path": Path(info["path"]),
                "title": f"[Copilot Instruction] {info['name']}",
                "category": "copilot-instructions",
                "tags": ["copilot", "instruction", info["name"]],
                "content_type": "document",
            })

    if hasattr(sync_config, "list_agents"):
        for info in sync_config.list_agents():
            _add_target({
                "path": Path(info["path"]),
                "title": f"[Copilot Agent] {info['name']}",
                "category": "copilot-agents",
                "tags": ["copilot", "agent", info["name"]],
                "content_type": "document",
            })

    if hasattr(sync_config, "list_hooks"):
        for info in sync_config.list_hooks():
            _add_target({
                "path": Path(info["path"]),
                "title": f"[Copilot Hook] {info['name']}",
                "category": "copilot-hooks",
                "tags": ["copilot", "hook", info["name"]],
                "content_type": "code",
            })

    return targets


def _matching_entries(
    source: dict,
    *,
    client=None,
    sync_config=None,
    category_entries: list | None = None,
) -> list:
    """Return exact title/category matches for a mirrored source."""
    if client is None:
        client = get_nexus_client()
    if sync_config is None:
        sync_config = get_copilot_config()

    category = source["category"]
    title = source["title"]
    matches = []
    if category_entries is not None:
        for entry in category_entries:
            if (
                sync_config._entry_field(entry, "title", "") == title  # noqa: SLF001
                and sync_config._entry_field(entry, "category", "") == category  # noqa: SLF001
            ):
                matches.append(entry)
    elif hasattr(client, "list_entries"):
        try:
            for entry in client.list_entries(category=category, limit=200):
                if (
                    sync_config._entry_field(entry, "title", "") == title  # noqa: SLF001
                    and sync_config._entry_field(entry, "category", "") == category  # noqa: SLF001
                ):
                    matches.append(entry)
        except Exception as exc:
            logger.debug("Could not list exact matches for %s: %s", title, exc)
    if matches:
        return matches

    existing = sync_config._find_existing_entry(  # noqa: SLF001 - shared exact-match logic
        client,
        _get_sync_query(source),
        title,
        category,
    )
    return [existing] if existing is not None else []


def _entry_matches_source(entry: object, source: dict, *, sync_config=None) -> bool:
    """Return True when a Nexus entry matches the expected mirrored source exactly."""
    if sync_config is None:
        sync_config = get_copilot_config()
    category = source["category"]
    if hasattr(sync_config, "_normalized_tags"):
        expected_tags = sync_config._normalized_tags(category, list(source.get("tags", [])))  # noqa: SLF001
        existing_tags = sync_config._normalized_tags(  # noqa: SLF001
            category,
            list(sync_config._entry_field(entry, "tags", []) or []),  # noqa: SLF001
        )
    else:
        expected_tags = sorted({tag for tag in source.get("tags", []) if tag})
        existing_tags = sorted({
            tag for tag in list(sync_config._entry_field(entry, "tags", []) or [])  # noqa: SLF001
            if tag
        })
    return (
        sync_config._entry_field(entry, "content", "") == _read_source_content(source)  # noqa: SLF001
        and sync_config._entry_field(entry, "content_type", "") == source.get("content_type", "document")  # noqa: SLF001
        and existing_tags == expected_tags
    )


def _entry_sort_key(entry: object, *, sync_config=None) -> tuple[datetime, str]:
    """Return a stable ordering key for duplicate mirror cleanup."""
    if sync_config is None:
        sync_config = get_copilot_config()
    raw_timestamp = (
        sync_config._entry_field(entry, "updated_at", None)  # noqa: SLF001
        or sync_config._entry_field(entry, "created_at", None)  # noqa: SLF001
    )
    timestamp = datetime.fromtimestamp(0, tz=timezone.utc)
    if isinstance(raw_timestamp, datetime):
        timestamp = raw_timestamp
    elif isinstance(raw_timestamp, str):
        try:
            timestamp = datetime.fromisoformat(raw_timestamp.replace("Z", "+00:00"))
        except ValueError:
            timestamp = datetime.fromtimestamp(0, tz=timezone.utc)
    return timestamp, str(sync_config._entry_field(entry, "id", ""))  # noqa: SLF001


def dedupe_copilot_mirrors(
    *,
    dry_run: bool = True,
    targets: list[dict] | None = None,
    client=None,
    sync_config=None,
) -> dict:
    """Remove duplicate exact-title Copilot mirror entries from Nexus."""
    if client is None:
        client = get_nexus_client()
    if sync_config is None:
        sync_config = get_copilot_config()
    selected_targets = list(targets) if targets is not None else _build_sync_targets(sync_config)
    entries_by_category: dict[str, list] = {}
    if hasattr(client, "list_entries"):
        for category in {target["category"] for target in selected_targets}:
            try:
                entries_by_category[category] = list(client.list_entries(category=category, limit=200))
            except Exception as exc:
                logger.debug("Could not prefetch Copilot mirror category %s: %s", category, exc)
                entries_by_category[category] = []

    removed = 0
    duplicate_targets = 0
    unresolved = 0
    groups = []

    for source in selected_targets:
        matches = _matching_entries(
            source,
            client=client,
            sync_config=sync_config,
            category_entries=entries_by_category.get(source["category"]),
        )
        if len(matches) <= 1:
            continue

        duplicate_targets += 1
        exact_matches = [
            entry for entry in matches
            if _entry_matches_source(entry, source, sync_config=sync_config)
        ]
        if not exact_matches:
            unresolved += 1
            groups.append({
                "title": source["title"],
                "category": source["category"],
                "status": "unresolved",
                "count": len(matches),
                "removed_ids": [],
            })
            continue

        keeper = max(exact_matches, key=lambda entry: _entry_sort_key(entry, sync_config=sync_config))
        keeper_id = sync_config._entry_field(keeper, "id", "")  # noqa: SLF001
        removed_ids: list[str] = []
        for entry in matches:
            entry_id = sync_config._entry_field(entry, "id", "")  # noqa: SLF001
            if not entry_id or entry_id == keeper_id:
                continue
            if not dry_run:
                try:
                    if client.delete_entry(entry_id):
                        removed += 1
                        removed_ids.append(entry_id)
                except Exception as exc:
                    logger.warning("Failed to delete duplicate Copilot mirror %s: %s", entry_id, exc)
            else:
                removed += 1
                removed_ids.append(entry_id)

        groups.append({
            "title": source["title"],
            "category": source["category"],
            "status": "deduped" if not dry_run else "would_dedupe",
            "count": len(matches),
            "kept_id": keeper_id,
            "removed_ids": removed_ids,
        })
        if removed_ids and source["category"] in entries_by_category:
            entries_by_category[source["category"]] = [
                entry
                for entry in entries_by_category[source["category"]]
                if sync_config._entry_field(entry, "id", "") not in removed_ids  # noqa: SLF001
            ]

    return {
        "duplicate_targets": duplicate_targets,
        "removed": removed,
        "unresolved": unresolved,
        "dry_run": dry_run,
        "groups": groups,
    }


# ── Core Seed Logic ───────────────────────────────────────────────────────────

def seed_source(
    source: dict,
    force: bool = False,
    state: dict | None = None,
    *,
    client=None,
    sync_config=None,
) -> tuple[str, bool]:
    """
    Seed a single source file into Nexus.

    Returns (status, changed) where status is one of:
    'stored', 'updated', 'skipped', 'error'
    """
    if state is None:
        state = {}
    if client is None:
        client = get_nexus_client()
    if sync_config is None:
        sync_config = get_copilot_config()

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
        try:
            if _entry_exists(source, client=client, sync_config=sync_config):
                return "skipped", False
        except Exception as exc:
            logger.debug("Entry existence check failed for %s: %s", title, exc)

    outcome = sync_config._sync_entry(  # noqa: SLF001 - shared exact-match drift repair logic
        client,
        query=_get_sync_query(source),
        title=title,
        content=content,
        content_type=source.get("content_type", "document"),
        category=category,
        tags=tags,
    )

    if outcome in {"stored", "updated", "skipped"}:
        state[key] = current_hash
        if outcome != "skipped":
            logger.info("%s: %s", outcome.capitalize(), title)
        return outcome, outcome != "skipped"

    logger.warning("Failed to seed: %s", title)
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

    counts = {"stored": 0, "updated": 0, "skipped": 0, "error": 0, "stale": 0, "deduped": 0}
    config_sync_result: dict = {}
    config_sync_summary: dict[str, int] = {"stored": 0, "updated": 0, "skipped": 0}
    dedupe_summary: dict[str, int | list] = {"duplicate_targets": 0, "removed": 0, "unresolved": 0, "groups": []}
    client = None
    sync_config = None

    if not check_only:
        sync_config = get_copilot_config()
        config_sync_result = sync_config.sync_all_to_nexus()
        config_sync_summary = _normalise_sync_summary(config_sync_result)
        counts["stored"] += config_sync_summary.get("stored", 0)
        counts["updated"] += config_sync_summary.get("updated", 0)
        counts["skipped"] += config_sync_summary.get("skipped", 0)
        if config_sync_summary.get("error") or any(
            isinstance(section, dict) and section.get("error")
            for section in config_sync_result.values()
        ):
            counts["error"] += 1
        client = get_nexus_client()
    else:
        try:
            client = get_nexus_client()
            sync_config = get_copilot_config()
        except Exception:
            client = None
            sync_config = None

    for source in sources:
        path: Path = source["path"]
        title = source["title"]

        if check_only:
            current_hash = _file_hash(path, source.get("max_chars", 0))
            key = str(path)
            exists = True
            if client and sync_config:
                try:
                    exists = _entry_exists(source, client=client, sync_config=sync_config)
                except Exception:
                    exists = True
            if state.get(key) != current_hash or not exists:
                print(f"  STALE: {title}")
                counts["stale"] += 1
            else:
                print(f"  OK:    {title}")
            continue

        status, _ = seed_source(
            source,
            force=force,
            state=state,
            client=client,
            sync_config=sync_config,
        )
        counts[status] = counts.get(status, 0) + 1

    if not check_only:
        dedupe_summary = dedupe_copilot_mirrors(
            dry_run=False,
            client=client,
            sync_config=sync_config,
        )
        counts["deduped"] = int(dedupe_summary.get("removed", 0))
        _save_state(state)
        print(
            f"Copilot rules seed complete: "
            f"{counts['stored']} stored, "
            f"{counts['updated']} updated, "
            f"{counts['skipped']} skipped, "
            f"{counts['error']} errors, "
            f"{counts['deduped']} deduped"
        )
    else:
        print(f"Check complete: {counts['stale']} stale, "
              f"{len(sources) - counts['stale']} current")

    counts["config_sync"] = config_sync_summary
    counts["dedupe"] = dedupe_summary
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
