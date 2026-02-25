"""
Nexus Knowledge System skills for CosySim agents.

v0.50a: Expanded from 4→11 skills. Now covers knowledge CRUD, sessions,
prompts, rules, experiments, ideas, and changelog tracking.
"""
import json

from engine.skills.skill import skill, SkillCategory


def _client():
    from engine.nexus.client import get_nexus_client
    return get_nexus_client()


# ── Knowledge Search & Store ──────────────────────────────────

@skill(pack="nexus", description="Search the Nexus knowledge base",
       tags=["nexus", "search", "knowledge"], category=SkillCategory.SYSTEM)
def nexus_search(query: str, limit: int = 10) -> str:
    """Full-text search across all Nexus knowledge entries."""
    results = _client().search(query, limit)
    return json.dumps(results[:limit])


@skill(pack="nexus", description="Add a knowledge entry to Nexus",
       tags=["nexus", "store", "knowledge"], category=SkillCategory.SYSTEM)
def nexus_add(title: str, content: str, content_type: str = "note",
              category: str = "") -> str:
    """Store new knowledge in Nexus. Types: note, prompt, session, experiment, rule, changelog."""
    entry_id = _client().add_entry(title, content, content_type, category)
    return json.dumps({"ok": bool(entry_id), "entry_id": entry_id})


@skill(pack="nexus", description="Query NotebookLM via best backend (HTTP or browser)",
       tags=["nexus", "notebooklm", "research"], category=SkillCategory.SYSTEM)
def nexus_nlm_ask(question: str, notebook_id: str = "",
                  notebook_url: str = "") -> str:
    """Ask a question through the NotebookLM research backend."""
    result = _client().nlm_unified_ask(question, notebook_id, notebook_url)
    return json.dumps(result)


@skill(pack="nexus", description="Check Nexus knowledge base and NLM backend status",
       tags=["nexus", "status"], category=SkillCategory.SYSTEM)
def nexus_status() -> str:
    """Get Nexus database stats and backend health."""
    client = _client()
    stats = client.stats()
    nlm = client.nlm_status()
    return json.dumps({"stats": stats, "nlm_backends": nlm})


# ── Session Tracking ──────────────────────────────────────────

@skill(pack="nexus", description="Log a session to Nexus — tracks work across agents",
       tags=["nexus", "session", "tracking"], category=SkillCategory.SYSTEM)
def nexus_log_session(project: str = "CosySim", repo: str = "",
                      branch: str = "", summary: str = "") -> str:
    """Create or update a session record in Nexus for audit and history."""
    client = _client()
    sid = client.log_session(project=project, repo=repo, branch=branch)
    if sid and summary:
        client.update_session(sid, summary=summary)
    return json.dumps({"ok": bool(sid), "session_id": sid})


# ── Prompt Management ─────────────────────────────────────────

@skill(pack="nexus", description="Store a prompt in Nexus with versioning",
       tags=["nexus", "prompt", "store"], category=SkillCategory.SYSTEM,
       cooldown=5)
def nexus_store_prompt(name: str, content: str, category: str = "system",
                       version: str = "1") -> str:
    """Store a system/agent/scene prompt for versioning and A/B testing."""
    entry_id = _client().store_prompt(name, content, category, version)
    return json.dumps({"ok": bool(entry_id), "entry_id": entry_id})


@skill(pack="nexus", description="Search stored prompts by name or category",
       tags=["nexus", "prompt", "search"], category=SkillCategory.SYSTEM)
def nexus_search_prompts(name: str = "", category: str = "") -> str:
    """Find prompts stored in Nexus. Filter by name substring or category."""
    prompts = _client().get_prompts(category=category, name=name)
    results = [{"title": p.get("title"), "category": p.get("category"),
                "tags": p.get("tags"), "id": p.get("id")} for p in prompts]
    return json.dumps(results)


# ── Rules ─────────────────────────────────────────────────────

@skill(pack="nexus", description="Get active rules from Nexus for a scope",
       tags=["nexus", "rules", "governance"], category=SkillCategory.SYSTEM)
def nexus_get_rules(scope: str = "global", rule_type: str = "") -> str:
    """Retrieve rules for a scope (global, scene:X, agent:X). Types: validation, access, auto_action, quality_gate."""
    rules = _client().get_rules(scope=scope, rule_type=rule_type)
    return json.dumps(rules)


# ── Ideas & Experiments ───────────────────────────────────────

@skill(pack="nexus", description="Submit an improvement idea to Nexus",
       tags=["nexus", "idea", "improvement"], category=SkillCategory.SYSTEM,
       cooldown=10)
def nexus_submit_idea(title: str, description: str,
                      category: str = "improvement") -> str:
    """Submit an idea for system improvement. Stored as 'experiment' type for later evaluation."""
    entry_id = _client().add_entry(
        title=title, content=description,
        content_type="experiment", category=category,
        tags=["idea", "pending_review"],
    )
    return json.dumps({"ok": bool(entry_id), "entry_id": entry_id})


# ── Changelog ─────────────────────────────────────────────────

@skill(pack="nexus", description="Query change history from Nexus",
       tags=["nexus", "changelog", "history"], category=SkillCategory.SYSTEM)
def nexus_changelog(version: str = "", limit: int = 10) -> str:
    """Retrieve changelog entries from Nexus. Optionally filter by version."""
    entries = _client().list_by_type("changelog", limit=limit)
    if version:
        entries = [e for e in entries if version in e.get("title", "")]
    results = [{"title": e.get("title"), "content": e.get("content", "")[:200],
                "created_at": e.get("created_at")} for e in entries]
    return json.dumps(results)
