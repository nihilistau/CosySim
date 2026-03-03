"""Extract conversation training data from EventChain logs and Nexus."""
from __future__ import annotations

import json
import logging
import random
from pathlib import Path
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

_OUTPUT_PATH = Path("training/datasets/conversational_train.jsonl")
_INSTRUCTION = "Continue this conversation naturally, in character."

_KNOWN_CHARACTERS = ["aria", "lola", "viktor", "frankie", "mira"]


def extract_from_event_chain(limit: int = 2000) -> List[Dict[str, Any]]:
    """Extract conversation samples from EventChain database.

    Args:
        limit: Maximum number of conversation turns to extract.

    Returns:
        List of conversation example dicts.
    """
    examples: List[Dict[str, Any]] = []
    try:
        from engine.mcp import get_dialog_system
        dialog = get_dialog_system()
        conversations = dialog.list_conversations(limit=limit)
        for conv in conversations:
            turns = conv.get("turns", [])
            if len(turns) < 2:
                continue
            system_prompt = conv.get("system_prompt", "")
            character_id = conv.get("character_id", "unknown")

            # Generate training examples from consecutive turn pairs
            for i in range(1, len(turns)):
                prior = turns[:i]
                current = turns[i]
                if current.get("role") != "assistant":
                    continue
                response = current.get("content", "")
                if not response or len(response) < 10:
                    continue

                turns_text = "\n".join(
                    f"{t.get('role', '').upper()}: {t.get('content', '')}"
                    for t in prior
                )
                examples.append({
                    "input": f"System: {system_prompt}\n\n{turns_text}" if system_prompt else turns_text,
                    "output": response,
                    "metadata": {"character_id": character_id, "source": "event_chain"},
                })
    except Exception as e:
        logger.debug(f"extract_from_event_chain failed: {e}")
    return examples


def extract_from_nexus(limit: int = 1000) -> List[Dict[str, Any]]:
    """Extract conversation samples from Nexus dialog entries.

    Args:
        limit: Maximum number of entries to extract.

    Returns:
        List of conversation example dicts.
    """
    examples: List[Dict[str, Any]] = []
    try:
        from engine.nexus.client import get_nexus_client
        client = get_nexus_client()
        results = client.search("dialog conversation turns character", limit=limit)
        for entry in results:
            content = entry.get("content", "")
            if not content:
                continue
            try:
                data = json.loads(content)
                turns = data.get("turns", [])
                system_prompt = data.get("system_prompt", "")
                character_id = data.get("character_id", "unknown")
                if len(turns) < 2:
                    continue
                # Use last assistant turn as output
                for i in range(1, len(turns)):
                    if turns[i].get("role") == "assistant":
                        prior = turns[:i]
                        response = turns[i].get("content", "")
                        if response and len(response) > 10:
                            turns_text = "\n".join(
                                f"{t.get('role', '').upper()}: {t.get('content', '')}"
                                for t in prior
                            )
                            examples.append({
                                "input": f"System: {system_prompt}\n\n{turns_text}" if system_prompt else turns_text,
                                "output": response,
                                "metadata": {"character_id": character_id, "source": "nexus"},
                            })
            except (json.JSONDecodeError, KeyError):
                continue
    except Exception as e:
        logger.debug(f"extract_from_nexus failed: {e}")
    return examples


def generate_synthetic_conversations(count: int = 100) -> List[Dict[str, Any]]:
    """Generate synthetic conversation examples for bootstrapping.

    Args:
        count: Number of synthetic examples to generate.

    Returns:
        List of synthetic conversation example dicts.
    """
    examples: List[Dict[str, Any]] = []

    templates = [
        {
            "system": "You are Aria, a helpful and friendly AI assistant.",
            "turns": [
                {"role": "user", "content": "Hello, how are you?"},
                {"role": "assistant", "content": "I'm doing well, thank you for asking! How can I help you today?"},
            ],
        },
        {
            "system": "You are Lola, a mysterious and alluring character.",
            "turns": [
                {"role": "user", "content": "What do you know about the heist?"},
                {"role": "assistant", "content": "I know more than you'd expect... but information like that comes at a price."},
            ],
        },
        {
            "system": "You are Viktor, a gruff but reliable ally.",
            "turns": [
                {"role": "user", "content": "Can we trust the new recruit?"},
                {"role": "assistant", "content": "Trust is earned, not given. I've seen their work — competent, but still an unknown."},
            ],
        },
        {
            "system": "You are Frankie, the team's tech expert.",
            "turns": [
                {"role": "user", "content": "Can you hack into their system?"},
                {"role": "assistant", "content": "Give me five minutes and the right tools. Their security's good, but not that good."},
            ],
        },
        {
            "system": "You are Mira, the team medic and voice of reason.",
            "turns": [
                {"role": "user", "content": "Is the plan too risky?"},
                {"role": "assistant", "content": "Every plan has risk. The question is whether we've mitigated enough of it. Let's go over the contingencies."},
            ],
        },
    ]

    for i in range(count):
        template = templates[i % len(templates)]
        system = template["system"]
        turns = template["turns"]
        turns_text = "\n".join(
            f"{t['role'].upper()}: {t['content']}" for t in turns[:-1]
        )
        response = turns[-1]["content"]
        examples.append({
            "input": f"System: {system}\n\n{turns_text}",
            "output": response,
            "metadata": {"source": "synthetic"},
        })

    return examples


def save_dataset(
    examples: List[Dict[str, Any]],
    output_path: Optional[Path] = None,
) -> Path:
    """Save conversation examples to JSONL in Alpaca format.

    Args:
        examples: List of example dicts with input/output keys.
        output_path: Output path. Defaults to training/datasets/conversational_train.jsonl.

    Returns:
        Path to the saved file.
    """
    out = output_path or _OUTPUT_PATH
    out.parent.mkdir(parents=True, exist_ok=True)

    random.shuffle(examples)
    with out.open("w", encoding="utf-8") as f:
        for ex in examples:
            record = {
                "instruction": _INSTRUCTION,
                "input": ex.get("input", ""),
                "output": ex.get("output", ""),
                "model_type": "conversational",
                "metadata": ex.get("metadata", {}),
            }
            f.write(json.dumps(record) + "\n")

    logger.info(f"Saved {len(examples)} conversation examples to {out}")
    return out


def main() -> None:
    """Generate and save the conversational training dataset."""
    logging.basicConfig(level=logging.INFO)
    examples: List[Dict[str, Any]] = []

    # 1. Extract from EventChain
    ec_examples = extract_from_event_chain(limit=2000)
    examples.extend(ec_examples)
    logger.info(f"EventChain: {len(ec_examples)} examples")

    # 2. Extract from Nexus
    nexus_examples = extract_from_nexus(limit=1000)
    examples.extend(nexus_examples)
    logger.info(f"Nexus: {len(nexus_examples)} examples")

    # 3. Generate synthetic examples for bootstrapping
    if len(examples) < 50:
        synthetic = generate_synthetic_conversations(count=100)
        examples.extend(synthetic)
        logger.info(f"Synthetic: {len(synthetic)} examples added (bootstrap)")

    # Deduplicate
    seen: set = set()
    unique: List[Dict[str, Any]] = []
    for ex in examples:
        key = ex.get("input", "")[:150]
        if key not in seen:
            seen.add(key)
            unique.append(ex)

    path = save_dataset(unique[:5000])
    print(f"Generated {len(unique)} conversation examples → {path}")


if __name__ == "__main__":
    main()
