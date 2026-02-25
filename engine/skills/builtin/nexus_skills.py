"""Nexus Knowledge System skills for CosySim agents."""
from engine.skills.skill import skill

@skill(pack="nexus", description="Search the Nexus knowledge base", tags=["nexus","search","knowledge"])
def nexus_search(query: str, limit: int = 10) -> str:
    from engine.nexus.client import get_nexus_client
    import json
    results = get_nexus_client().search(query, limit)
    return json.dumps(results[:limit])

@skill(pack="nexus", description="Add a knowledge entry to Nexus", tags=["nexus","store","knowledge"])
def nexus_add(title: str, content: str, content_type: str = "note", category: str = "") -> str:
    from engine.nexus.client import get_nexus_client
    import json
    entry_id = get_nexus_client().add_entry(title, content, content_type, category)
    return json.dumps({"ok": bool(entry_id), "entry_id": entry_id})

@skill(pack="nexus", description="Query NotebookLM via best backend (HTTP or browser)", tags=["nexus","notebooklm","research"])
def nexus_nlm_ask(question: str, notebook_id: str = "", notebook_url: str = "") -> str:
    from engine.nexus.client import get_nexus_client
    import json
    result = get_nexus_client().nlm_unified_ask(question, notebook_id, notebook_url)
    return json.dumps(result)

@skill(pack="nexus", description="Check Nexus knowledge base and NLM backend status", tags=["nexus","status"])
def nexus_status() -> str:
    from engine.nexus.client import get_nexus_client
    import json
    client = get_nexus_client()
    stats = client.stats()
    nlm = client.nlm_status()
    return json.dumps({"stats": stats, "nlm_backends": nlm})
