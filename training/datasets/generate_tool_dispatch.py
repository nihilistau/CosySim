"""Auto-generate tool_dispatch training dataset from the CosySim skill registry."""
from __future__ import annotations

import json
import logging
import random
from pathlib import Path
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

_OUTPUT_PATH = Path("training/datasets/tool_dispatch_train.jsonl")

_INSTRUCTION = 'Route this instruction to the correct tool. Respond with JSON: {"tool": "skill_name", "args": {...}}'

# Manually curated examples for well-known skills that may not have dynamic examples
_SEED_EXAMPLES: List[Dict[str, Any]] = [
    {
        "input": "search nexus for interceptor pipeline",
        "output": '{"tool": "nexus_search", "args": {"query": "interceptor pipeline"}}',
    },
    {
        "input": "ask nexus how the MCP framework works",
        "output": '{"tool": "nexus_ask", "args": {"question": "how does the MCP framework work"}}',
    },
    {
        "input": "store a note about the architecture decision",
        "output": '{"tool": "nexus_add", "args": {"title": "Architecture Decision", "content": "...", "content_type": "note"}}',
    },
    {
        "input": "check system health",
        "output": '{"tool": "system_status", "args": {}}',
    },
    {
        "input": "list all available skills",
        "output": '{"tool": "list_all_skills", "args": {}}',
    },
    {
        "input": "run backup now",
        "output": '{"tool": "backup_databases", "args": {}}',
    },
    {
        "input": "speak hello world using aria",
        "output": '{"tool": "tts_speak", "args": {"text": "hello world", "character": "aria"}}',
    },
    {
        "input": "start the bedroom scene",
        "output": '{"tool": "scene_start", "args": {"scene": "bedroom"}}',
    },
    {
        "input": "stop all running scenes",
        "output": '{"tool": "scene_stop_all", "args": {}}',
    },
    {
        "input": "add a qa pair to nexus about LMStudio port",
        "output": '{"tool": "nexus_add_qa", "args": {"question": "what port is LMStudio on", "answer": "1234"}}',
    },
    {
        "input": "get the nexus status",
        "output": '{"tool": "nexus_status", "args": {}}',
    },
    {
        "input": "research best practices for scene development",
        "output": '{"tool": "nexus_research", "args": {"question": "best practices for scene development"}}',
    },
    {
        "input": "get governance rules for coding",
        "output": '{"tool": "nexus_get_rules", "args": {"scope": "coding"}}',
    },
    {
        "input": "log a training session for cosysim",
        "output": '{"tool": "nexus_log_session", "args": {"project": "CosySim"}}',
    },
    {
        "input": "get info about the nexus_search skill",
        "output": '{"tool": "get_skill_info", "args": {"skill_name": "nexus_search"}}',
    },
]


def generate_from_registry(limit: int = 500) -> List[Dict[str, Any]]:
    """Generate tool_dispatch examples from the skill registry.

    Iterates through all registered skills and creates routing examples.

    Args:
        limit: Maximum number of examples to generate.

    Returns:
        List of (input, output) example dicts.
    """
    examples: List[Dict[str, Any]] = list(_SEED_EXAMPLES)

    try:
        from engine.skills.registry import get_skill_registry
        registry = get_skill_registry()
        skills = registry.list_skills()

        for skill_info in skills:
            skill_name = skill_info.get("name", "")
            description = skill_info.get("description", "")
            params = skill_info.get("parameters", {})
            if not skill_name:
                continue

            # Generate natural language input from description
            if description:
                nl_input = _description_to_nl(description, skill_name)
                args = _build_example_args(params)
                output = json.dumps({"tool": skill_name, "args": args})
                examples.append({"input": nl_input, "output": output})

            # Generate a second variant with different phrasing
            variant_input = _build_variant(skill_name, description)
            if variant_input:
                args = _build_example_args(params)
                examples.append({"input": variant_input, "output": json.dumps({"tool": skill_name, "args": args})})

        logger.info(f"generate_tool_dispatch: generated {len(examples)} examples from {len(skills)} skills")
    except Exception as e:
        logger.warning(f"Could not load skill registry: {e}, using seed examples only")

    random.shuffle(examples)
    return examples[:limit]


def _description_to_nl(description: str, skill_name: str) -> str:
    """Convert a skill description to a natural language instruction.

    Args:
        description: Skill description text.
        skill_name: Skill name for fallback.

    Returns:
        Natural language instruction string.
    """
    desc = description.strip().rstrip(".")
    if desc:
        return desc[0].lower() + desc[1:] if len(desc) > 1 else desc
    return f"use the {skill_name} skill"


def _build_variant(skill_name: str, description: str) -> Optional[str]:
    """Build a variant phrasing for a skill.

    Args:
        skill_name: Skill name.
        description: Skill description.

    Returns:
        Variant input string, or None if cannot generate.
    """
    prefixes = [
        "please ", "can you ", "I need to ", "help me ",
        "go ahead and ", "quickly ", "use the skill to ",
    ]
    desc = description.strip().rstrip(".")
    if not desc:
        return None
    prefix = random.choice(prefixes)
    low_desc = desc[0].lower() + desc[1:] if len(desc) > 1 else desc
    return f"{prefix}{low_desc}"


def _build_example_args(params: Dict[str, Any]) -> Dict[str, Any]:
    """Build example parameter values for a skill.

    Args:
        params: Parameter schema dict.

    Returns:
        Dict of example parameter values.
    """
    args: Dict[str, Any] = {}
    for param_name, param_info in params.items():
        if isinstance(param_info, dict):
            param_type = param_info.get("type", "string")
        else:
            param_type = "string"

        if param_type in ("string", "str"):
            args[param_name] = f"example_{param_name}"
        elif param_type in ("int", "integer", "number"):
            args[param_name] = 1
        elif param_type in ("bool", "boolean"):
            args[param_name] = True
        elif param_type in ("list", "array"):
            args[param_name] = []
        else:
            args[param_name] = None
    return args


def save_dataset(examples: List[Dict[str, Any]], output_path: Optional[Path] = None) -> Path:
    """Save examples to a JSONL file in Alpaca format.

    Args:
        examples: List of example dicts with input/output keys.
        output_path: Output path. Defaults to training/datasets/tool_dispatch_train.jsonl.

    Returns:
        Path to the saved file.
    """
    out = output_path or _OUTPUT_PATH
    out.parent.mkdir(parents=True, exist_ok=True)
    with out.open("w", encoding="utf-8") as f:
        for ex in examples:
            record = {
                "instruction": _INSTRUCTION,
                "input": ex.get("input", ""),
                "output": ex.get("output", ""),
                "model_type": "tool_dispatch",
            }
            f.write(json.dumps(record) + "\n")
    logger.info(f"Saved {len(examples)} tool_dispatch examples to {out}")
    return out


def main() -> None:
    """Generate and save the tool_dispatch training dataset."""
    logging.basicConfig(level=logging.INFO)
    examples = generate_from_registry(limit=1000)
    path = save_dataset(examples)
    print(f"Generated {len(examples)} examples → {path}")


if __name__ == "__main__":
    main()
