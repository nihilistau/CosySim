"""
prompt_skills.py — MCP skills for prompt template management.

Exposes the PromptRegistry to LLM agents via the CosySim skill system,
enabling template listing, rendering, expansion, and quality tracking.
"""
from __future__ import annotations

import json
import logging
from typing import Any

from engine.skills.skill import skill, SkillCategory

logger = logging.getLogger(__name__)


def _registry() -> Any:
    """Lazy import to avoid circular dependencies."""
    from engine.prompts.prompt_registry import get_prompt_registry
    return get_prompt_registry()


@skill(
    pack="prompts",
    description="List available prompt templates, optionally filtered by category or search query",
    category=SkillCategory.SYSTEM,
    tags=["prompt", "template", "registry"],
)
def list_prompt_templates(category: str = "", query: str = "") -> str:
    """List prompt templates with optional filtering.

    Args:
        category: Filter by category (system, character, scene, task, evaluation).
        query: Search query to match against template id, name, or content.

    Returns:
        JSON list of matching templates with id, name, category, and tags.
    """
    reg = _registry()
    results = reg.search(query=query, category=category)
    summary = [
        {
            "id": t.id,
            "name": t.name,
            "category": t.category,
            "version": t.version,
            "tags": t.tags,
            "variables": t.variables,
            "usage_count": t.usage_count,
        }
        for t in results
    ]
    return json.dumps(summary, indent=2)


@skill(
    pack="prompts",
    description="Render a prompt template with variable substitution",
    category=SkillCategory.SYSTEM,
    tags=["prompt", "template", "render"],
)
def render_prompt(template_id: str, variables_json: str = "{}") -> str:
    """Render a prompt template by substituting variables.

    Args:
        template_id: The template identifier to render.
        variables_json: JSON object of variable name-value pairs.

    Returns:
        The rendered prompt text, or an error message.
    """
    reg = _registry()
    try:
        variables = json.loads(variables_json)
    except json.JSONDecodeError as exc:
        return f"Error: invalid variables_json — {exc}"

    try:
        rendered = reg.render(template_id, **variables)
    except KeyError as exc:
        return f"Error: {exc}"
    return rendered


@skill(
    pack="prompts",
    description="Expand a template into multiple prompt variations from a list of variable sets",
    category=SkillCategory.SYSTEM,
    tags=["prompt", "template", "expand", "ab-test"],
)
def expand_prompt(template_id: str, variations_json: str = "[]") -> str:
    """Generate multiple prompts from one template with different variable sets.

    Args:
        template_id: The template identifier to expand.
        variations_json: JSON array of variable-set objects.

    Returns:
        JSON array of rendered prompt strings, or an error message.
    """
    reg = _registry()
    try:
        variations = json.loads(variations_json)
    except json.JSONDecodeError as exc:
        return f"Error: invalid variations_json — {exc}"

    if not isinstance(variations, list):
        return "Error: variations_json must be a JSON array"

    try:
        results = reg.expand(template_id, variations)
    except KeyError as exc:
        return f"Error: {exc}"
    return json.dumps(results, indent=2)


@skill(
    pack="prompts",
    description="Get statistics about the prompt template registry",
    category=SkillCategory.SYSTEM,
    tags=["prompt", "stats", "registry"],
)
def prompt_stats() -> str:
    """Return registry statistics including template counts and top performers.

    Returns:
        JSON object with total templates, category breakdown, top used, top quality.
    """
    reg = _registry()
    stats = reg.get_stats()
    return json.dumps(stats, indent=2)


@skill(
    pack="prompts",
    description="Record quality feedback for a prompt template (0.0-1.0)",
    category=SkillCategory.SYSTEM,
    tags=["prompt", "quality", "feedback", "ab-test"],
)
def rate_prompt(template_id: str, quality: float = 0.5) -> str:
    """Record a quality rating for a prompt template.

    Args:
        template_id: The template identifier to rate.
        quality: Quality score between 0.0 (poor) and 1.0 (excellent).

    Returns:
        Confirmation message with updated stats.
    """
    reg = _registry()
    tpl = reg.get(template_id)
    if tpl is None:
        return f"Error: template '{template_id}' not found"

    reg.record_usage(template_id, quality=quality)
    tpl = reg.get(template_id)
    return json.dumps({
        "template_id": template_id,
        "quality_score": round(tpl.quality_score, 3),
        "usage_count": tpl.usage_count,
        "message": "Quality recorded successfully",
    })
