"""
prompts.chat integration skills for CosySim agents.

Provides MCP skills to search, retrieve, and improve prompts via the
prompts.chat API. Results are optionally stored in Nexus for local reuse.

Sprint 8.5: Initial implementation with search, get, improve, and ingest.
"""
import json
import logging
import urllib.request
import urllib.error
from typing import Any, Dict, Optional

from engine.config import get_config
from engine.skills.skill import skill, SkillCategory

logger = logging.getLogger(__name__)

_BASE_URL = "https://prompts.chat/api"


def _get_api_key() -> str:
    """Retrieve prompts.chat API key from config."""
    return get_config().get("prompts_chat.api_key", "")


def _request(method: str, path: str, data: Optional[Dict] = None,
             timeout: int = 15) -> Dict[str, Any]:
    """Make HTTP request to prompts.chat API."""
    url = f"{_BASE_URL}{path}"
    headers = {"Content-Type": "application/json"}

    api_key = _get_api_key()
    if api_key:
        headers["PROMPTS_API_KEY"] = api_key
        headers["X-API-Key"] = api_key

    if data is not None:
        body = json.dumps(data).encode("utf-8")
        req = urllib.request.Request(url, data=body, headers=headers, method=method)
    else:
        req = urllib.request.Request(url, headers=headers, method=method)

    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        body = e.read().decode("utf-8", errors="replace")
        logger.warning("prompts.chat %s %s → %s: %s", method, path, e.code, body[:200])
        return {"error": f"HTTP {e.code}", "detail": body[:200]}
    except Exception as e:
        logger.error("prompts.chat request failed: %s", e)
        return {"error": str(e)}


def _mcp_call(tool_name: str, arguments: Dict[str, Any],
              timeout: int = 15) -> Dict[str, Any]:
    """Call a prompts.chat MCP tool via JSON-RPC 2.0."""
    payload = {
        "jsonrpc": "2.0",
        "id": 1,
        "method": "tools/call",
        "params": {"name": tool_name, "arguments": arguments},
    }
    return _request("POST", "/mcp", data=payload, timeout=timeout)


# ── Search & Retrieve ─────────────────────────────────────────


@skill(
    pack="prompts_chat",
    description="Search prompts.chat for AI prompts by keyword",
    tags=["prompts", "search", "prompt-engineering"],
    category=SkillCategory.SYSTEM,
)
def search_prompts(query: str, limit: int = 10,
                   prompt_type: str = "", category: str = "") -> str:
    """Search prompts.chat for prompts matching a query.

    Args:
        query: Search keywords.
        limit: Max results (1-50).
        prompt_type: Filter by type: TEXT, STRUCTURED, IMAGE, VIDEO, AUDIO.
        category: Filter by category slug.

    Returns:
        JSON array of matching prompts with title, description, content.
    """
    args: Dict[str, Any] = {"query": query, "limit": min(limit, 50)}
    if prompt_type:
        args["type"] = prompt_type
    if category:
        args["category"] = category

    result = _mcp_call("search_prompts", args)
    return json.dumps(result, indent=2)


@skill(
    pack="prompts_chat",
    description="Get a specific prompt from prompts.chat by ID",
    tags=["prompts", "retrieve"],
    category=SkillCategory.SYSTEM,
)
def get_prompt(prompt_id: str) -> str:
    """Retrieve a single prompt from prompts.chat by its ID.

    Args:
        prompt_id: The prompt identifier.

    Returns:
        JSON object with full prompt details.
    """
    result = _mcp_call("get_prompt", {"id": prompt_id})
    return json.dumps(result, indent=2)


@skill(
    pack="prompts_chat",
    description="Get an Agent Skill from prompts.chat by ID",
    tags=["prompts", "skills", "retrieve"],
    category=SkillCategory.SYSTEM,
)
def get_skill_from_prompts(skill_id: str) -> str:
    """Retrieve an Agent Skill from prompts.chat including all files.

    Args:
        skill_id: The skill identifier.

    Returns:
        JSON object with skill metadata and files.
    """
    result = _mcp_call("get_skill", {"id": skill_id})
    return json.dumps(result, indent=2)


# ── Prompt Enhancement ────────────────────────────────────────


@skill(
    pack="prompts_chat",
    description="Improve a prompt using prompts.chat AI enhancement",
    tags=["prompts", "enhance", "prompt-engineering"],
    category=SkillCategory.SYSTEM,
    cooldown=5.0,
)
def improve_prompt(prompt: str, output_type: str = "text",
                   output_format: str = "text") -> str:
    """Transform a basic prompt into a well-structured one using AI.

    Args:
        prompt: The prompt text to improve (max 10,000 chars).
        output_type: Content type — text, image, video, sound.
        output_format: Response format — text, structured_json, structured_yaml.

    Returns:
        JSON with original, improved prompt, and inspirations.
    """
    result = _request("POST", "/improve-prompt", data={
        "prompt": prompt[:10000],
        "outputType": output_type,
        "outputFormat": output_format,
    })
    return json.dumps(result, indent=2)


# ── Nexus Integration ─────────────────────────────────────────


@skill(
    pack="prompts_chat",
    description="Search prompts.chat and store best results in Nexus",
    tags=["prompts", "nexus", "ingest"],
    category=SkillCategory.SYSTEM,
    cooldown=10.0,
)
def ingest_prompts_to_nexus(query: str, limit: int = 5,
                            nexus_category: str = "prompts") -> str:
    """Search prompts.chat, then store top results in Nexus for local reuse.

    Args:
        query: Search keywords.
        limit: Number of prompts to ingest (1-10).
        nexus_category: Nexus category for stored entries.

    Returns:
        Summary of ingested prompts.
    """
    from engine.nexus.client import get_nexus_client

    search_result = _mcp_call("search_prompts", {
        "query": query, "limit": min(limit, 10),
    })

    # Extract prompts from MCP response
    prompts = []
    if isinstance(search_result, dict):
        result_data = search_result.get("result", search_result)
        if isinstance(result_data, dict):
            content = result_data.get("content", [])
            if content and isinstance(content, list):
                for item in content:
                    text = item.get("text", "")
                    try:
                        parsed = json.loads(text)
                        prompts = parsed.get("prompts", [])
                    except (json.JSONDecodeError, AttributeError):
                        logger.debug("Suppressed exception", exc_info=True)

    client = get_nexus_client()
    stored = 0
    for p in prompts[:limit]:
        title = p.get("title", "Untitled Prompt")
        content = p.get("content", "")
        desc = p.get("description", "")
        tags = p.get("tags", [])
        if isinstance(tags, list):
            tags = [str(t) for t in tags]

        full_content = f"# {title}\n\n{desc}\n\n{content}"
        try:
            entry_id = client.add_entry(
                f"Prompt: {title}",
                full_content,
                content_type="prompt",
                category=nexus_category,
            )
            if entry_id:
                stored += 1
        except Exception as e:
            logger.warning("Failed to store prompt '%s': %s", title, e)

    return json.dumps({
        "query": query,
        "found": len(prompts),
        "stored_in_nexus": stored,
    })
