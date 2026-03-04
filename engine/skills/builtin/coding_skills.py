"""
Coding agent skills — development workflow tools powered by Nexus.

v0.50b: 8 skills for coding agents to store, search, and manage
development knowledge through Nexus.
"""
import json

from engine.skills.skill import skill, SkillCategory


def _client():
    from engine.nexus.client import get_nexus_client
    return get_nexus_client()


@skill(pack="coding", description="Store a reusable code snippet in Nexus",
       tags=["coding", "nexus", "snippet", "store"], category=SkillCategory.SYSTEM,
       cooldown=5)
def coding_store_snippet(title: str, code: str, language: str = "python",
                         tags: str = "") -> str:
    """Store a code snippet/pattern/template in Nexus for future reuse.
    Tags are comma-separated. Language is auto-tagged."""
    tag_list = [t.strip() for t in tags.split(",") if t.strip()] if tags else []
    tag_list.extend(["snippet", language])
    entry_id = _client().add_entry(
        title=title, content=f"```{language}\n{code}\n```",
        content_type="code", category="development",
        tags=tag_list, created_by="coding_agent",
    )
    return json.dumps({"ok": bool(entry_id), "entry_id": entry_id})


@skill(pack="coding", description="Search Nexus for code patterns, snippets, and dev knowledge",
       tags=["coding", "nexus", "search"], category=SkillCategory.SYSTEM)
def coding_search(query: str, content_type: str = "", limit: int = 10) -> str:
    """Search development knowledge in Nexus. Optionally filter by type (code, document, note)."""
    client = _client()
    if content_type:
        results = client.list_entries(content_type=content_type, limit=limit)
        # Client-side filter by query terms
        terms = query.lower().split()
        results = [r for r in results if any(
            t in r.get("title", "").lower() or t in r.get("content", "").lower()
            for t in terms
        )]
    else:
        results = client.search(query, limit=limit)
    return json.dumps([{
        "id": r.get("id"), "title": r.get("title"),
        "type": r.get("content_type"), "category": r.get("category"),
        "preview": r.get("content", "")[:200],
    } for r in results])


@skill(pack="coding", description="Store an architecture or design decision in Nexus",
       tags=["coding", "nexus", "architecture", "decision"], category=SkillCategory.SYSTEM,
       cooldown=10)
def coding_store_decision(title: str, decision: str, rationale: str = "",
                          alternatives: str = "", category: str = "architecture") -> str:
    """Record an architecture/design decision with rationale and alternatives considered."""
    content = f"## Decision\n{decision}"
    if rationale:
        content += f"\n\n## Rationale\n{rationale}"
    if alternatives:
        content += f"\n\n## Alternatives Considered\n{alternatives}"
    entry_id = _client().add_entry(
        title=f"Decision: {title}", content=content,
        content_type="document", category=category,
        tags=["decision", "architecture"], created_by="coding_agent",
    )
    return json.dumps({"ok": bool(entry_id), "entry_id": entry_id})


@skill(pack="coding", description="Log a development session with summary and changes",
       tags=["coding", "nexus", "session", "log"], category=SkillCategory.SYSTEM,
       cooldown=5)
def coding_log_session(summary: str, files_changed: str = "",
                       commits: str = "", project: str = "CosySim") -> str:
    """Log a development session to Nexus for tracking and history."""
    client = _client()
    sid = client.log_session(project=project)
    if sid:
        updates = {"summary": summary}
        if files_changed:
            updates["files_changed"] = [f.strip() for f in files_changed.split(",")]
        if commits:
            updates["commits"] = [c.strip() for c in commits.split(",")]
        client.update_session(sid, **updates)
    return json.dumps({"ok": bool(sid), "session_id": sid})


@skill(pack="coding", description="Research an API, library, or tech topic via Nexus",
       tags=["coding", "nexus", "research", "api"], category=SkillCategory.SYSTEM,
       cooldown=15)
def coding_research(question: str, depth: str = "auto") -> str:
    """Research a coding topic. Searches Q&A cache, knowledge base, then NLM.

    depth: 'shallow' (cache + FTS), 'deep' (includes NLM), 'auto'.
    """
    result = _client().ask(question, depth=depth, category="development")
    return json.dumps(result, default=str)


@skill(pack="coding", description="Store a bug analysis or debugging note",
       tags=["coding", "nexus", "debug", "bug"], category=SkillCategory.SYSTEM,
       cooldown=5)
def coding_store_bug(title: str, description: str, fix: str = "",
                     root_cause: str = "") -> str:
    """Record a bug analysis with root cause and fix for future reference."""
    content = f"## Bug\n{description}"
    if root_cause:
        content += f"\n\n## Root Cause\n{root_cause}"
    if fix:
        content += f"\n\n## Fix\n{fix}"
    entry_id = _client().add_entry(
        title=f"Bug: {title}", content=content,
        content_type="note", category="debugging",
        tags=["bug", "debugging", "fix"], created_by="coding_agent",
    )
    return json.dumps({"ok": bool(entry_id), "entry_id": entry_id})


@skill(pack="coding", description="Store a test strategy or testing pattern",
       tags=["coding", "nexus", "testing", "pattern"], category=SkillCategory.SYSTEM,
       cooldown=5)
def coding_store_test_pattern(title: str, pattern: str,
                               example: str = "") -> str:
    """Record a testing strategy, pattern, or approach for future reference."""
    content = f"## Pattern\n{pattern}"
    if example:
        content += f"\n\n## Example\n```python\n{example}\n```"
    entry_id = _client().add_entry(
        title=f"Test Pattern: {title}", content=content,
        content_type="document", category="testing",
        tags=["testing", "pattern"], created_by="coding_agent",
    )
    return json.dumps({"ok": bool(entry_id), "entry_id": entry_id})


@skill(pack="coding", description="Get the current project status from Nexus",
       tags=["coding", "nexus", "status"], category=SkillCategory.SYSTEM)
def coding_project_status(project: str = "CosySim") -> str:
    """Get project health: recent sessions, active research, knowledge stats."""
    client = _client()
    stats = client.stats()
    sessions = client.list_sessions(project=project, limit=5)
    research = client.list_research(status="active", limit=5)
    return json.dumps({
        "nexus_stats": stats.get("data", {}),
        "recent_sessions": [{
            "id": s.get("id"), "summary": s.get("summary"),
            "created_at": s.get("created_at"),
        } for s in sessions],
        "active_research": [{
            "id": r.get("id"), "query": r.get("query"),
        } for r in research],
    })
