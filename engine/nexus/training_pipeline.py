"""
training_pipeline.py — Training data collection and export for fine-tuning.

Captures LLM interactions, stores them in Nexus as training pairs,
and exports them to JSONL format for fine-tuning with the existing
training infrastructure (training/finetune_local.py).

Workflow:
    1. Capture: Agent interactions are logged via capture_interaction()
    2. Store: Training pairs saved to Nexus with namespace:training tags
    3. Review: Optional quality scoring and filtering
    4. Export: Generate JSONL datasets for fine-tuning
    5. Train: Feed into training/finetune_local.py

Usage:
    from engine.nexus.training_pipeline import TrainingPipeline

    pipeline = TrainingPipeline()
    pipeline.capture_interaction(user_msg, agent_response, context)
    pipeline.export_dataset("tag_extraction", "training/datasets/custom/")
"""
from __future__ import annotations

import json
import logging
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

from engine.nexus.nexus_namespaces import enforce_namespace

logger = logging.getLogger(__name__)

# Training data categories matching existing dataset structure
DATASET_TYPES = {
    "tag_extraction": {
        "description": "Parse [MOOD:x], [ACTION:x], [STAT:x] tags from responses",
        "system_prompt": "Extract all tags from the agent response.",
    },
    "tool_routing": {
        "description": "Classify user intent to appropriate skill/tool call",
        "system_prompt": "Classify the user request to the appropriate tool.",
    },
    "response_quality": {
        "description": "Rate response quality for character consistency",
        "system_prompt": "Rate the response quality on a scale of 1-10.",
    },
    "conversation": {
        "description": "Full conversation turns for dialog fine-tuning",
        "system_prompt": "You are a virtual character in CosySim.",
    },
    "style_transfer": {
        "description": "Character-specific speech patterns and vocabulary",
        "system_prompt": "Respond in the character's unique voice and style.",
    },
}


class TrainingPipeline:
    """Captures, stores, and exports training data via Nexus.

    Args:
        nexus_url: Nexus API base URL.
        auto_capture: If True, automatically score and tag interactions.
    """

    def __init__(
        self,
        nexus_url: str = "",
        auto_capture: bool = True,
    ) -> None:
        if not nexus_url:
            from engine.port_registry import get_service_url
            nexus_url = get_service_url("nexus")
        self._url = nexus_url
        self._auto_capture = auto_capture
        self._buffer: List[Dict[str, Any]] = []
        self._buffer_limit = 50

    def capture_interaction(
        self,
        user_message: str,
        agent_response: str,
        context: Optional[Dict[str, Any]] = None,
        dataset_type: str = "conversation",
        quality_score: float = 0.7,
        character_id: str = "",
        scene_id: str = "",
    ) -> Optional[str]:
        """Capture a single interaction as training data.

        Args:
            user_message: The user's input.
            agent_response: The agent's response.
            context: Additional context (character state, scene state, etc).
            dataset_type: Type of training data.
            quality_score: Quality rating 0.0-1.0.
            character_id: Character that generated the response.
            scene_id: Scene where interaction occurred.

        Returns:
            Entry ID if stored, None otherwise.
        """
        import requests

        ctx = context or {}
        training_pair = {
            "user": user_message,
            "assistant": agent_response,
            "character": character_id,
            "scene": scene_id,
            "quality": quality_score,
            "dataset_type": dataset_type,
            "context": ctx,
            "timestamp": time.time(),
        }

        # Buffer for batch storage
        self._buffer.append(training_pair)

        # Store in Nexus
        tags = [
            "training",
            f"dataset:{dataset_type}",
            f"quality:{int(quality_score * 10)}",
        ]
        if character_id:
            tags.append(f"character:{character_id}")
        if scene_id:
            tags.append(f"scene:{scene_id}")

        entry = enforce_namespace(
            title=f"Training [{dataset_type}]: {user_message[:50]}",
            content=json.dumps(training_pair, ensure_ascii=False),
            content_type="code",
            category="training",
            tags=tags,
            namespace="training",
        )

        try:
            from engine.nexus.client import get_nexus_client
            return get_nexus_client().add_entry(
                title=entry["title"],
                content=entry["content"],
                content_type="code",
                category="training",
                tags=entry["tags"],
                created_by="training_pipeline",
            )
        except Exception as exc:
            logger.warning("TrainingPipeline: capture failed: %s", exc)

        return None

    def export_dataset(
        self,
        dataset_type: str = "conversation",
        output_dir: str = "training/datasets/custom",
        min_quality: float = 0.5,
        format: str = "jsonl",
    ) -> Dict[str, Any]:
        """Export training data from Nexus to JSONL files.

        Args:
            dataset_type: Type of training data to export.
            output_dir: Directory for output files.
            min_quality: Minimum quality score filter.
            format: Output format ('jsonl' or 'json').

        Returns:
            Dict with export stats (count, path, etc).
        """
        out_path = Path(output_dir)
        out_path.mkdir(parents=True, exist_ok=True)

        try:
            from engine.nexus.client import get_nexus_client
            results = get_nexus_client().search(
                f"dataset:{dataset_type} training", limit=500
            )

            # Parse and filter
            pairs: List[Dict[str, Any]] = []
            for entry in results:
                if "training" not in entry.tags:
                    continue
                try:
                    pair = json.loads(entry.content)
                    if pair.get("quality", 0) >= min_quality:
                        pairs.append(pair)
                except json.JSONDecodeError:
                    continue

            if not pairs:
                return {"count": 0, "message": "No matching training data found"}

            # Get system prompt for this dataset type
            ds_info = DATASET_TYPES.get(dataset_type, {})
            sys_prompt = ds_info.get("system_prompt", "You are a helpful assistant.")

            # Export to JSONL (chat format compatible with finetune_local.py)
            train_file = out_path / f"{dataset_type}_train.jsonl"
            val_file = out_path / f"{dataset_type}_val.jsonl"

            # 90/10 train/val split
            split_idx = max(1, int(len(pairs) * 0.9))
            train_pairs = pairs[:split_idx]
            val_pairs = pairs[split_idx:]

            for filepath, data in [(train_file, train_pairs), (val_file, val_pairs)]:
                with open(filepath, "w", encoding="utf-8") as f:
                    for pair in data:
                        record = {
                            "messages": [
                                {"role": "system", "content": sys_prompt},
                                {"role": "user", "content": pair.get("user", "")},
                                {"role": "assistant", "content": pair.get("assistant", "")},
                            ]
                        }
                        f.write(json.dumps(record, ensure_ascii=False) + "\n")

            return {
                "count": len(pairs),
                "train": len(train_pairs),
                "val": len(val_pairs),
                "train_file": str(train_file),
                "val_file": str(val_file),
                "dataset_type": dataset_type,
            }

        except Exception as exc:
            return {"error": str(exc), "count": 0}

    def get_stats(self) -> Dict[str, Any]:
        """Get training data statistics from Nexus.

        Returns:
            Dict with counts by dataset type, quality distribution, etc.
        """
        try:
            from engine.nexus.client import get_nexus_client
            results = get_nexus_client().search("training dataset", limit=500)

            by_type: Dict[str, int] = {}
            by_quality: Dict[str, int] = {"high": 0, "medium": 0, "low": 0}
            total = 0

            for entry in results:
                if "training" not in entry.tags:
                    continue
                total += 1

                # Count by dataset type
                for ds_type in DATASET_TYPES:
                    if f"dataset:{ds_type}" in entry.tags:
                        by_type[ds_type] = by_type.get(ds_type, 0) + 1
                        break

                # Count by quality
                for q in range(10, -1, -1):
                    if f"quality:{q}" in entry.tags:
                        if q >= 7:
                            by_quality["high"] += 1
                        elif q >= 4:
                            by_quality["medium"] += 1
                        else:
                            by_quality["low"] += 1
                        break

            return {
                "total": total,
                "by_type": by_type,
                "by_quality": by_quality,
                "buffer_size": len(self._buffer),
            }
        except Exception as exc:
            return {"error": str(exc)}

    def generate_synthetic(
        self,
        dataset_type: str = "tag_extraction",
        count: int = 10,
    ) -> List[Dict[str, Any]]:
        """Generate synthetic training examples for a dataset type.

        Uses template-based generation (no LLM required).

        Args:
            dataset_type: Type of examples to generate.
            count: Number of examples.

        Returns:
            List of generated training pairs.
        """
        examples: List[Dict[str, Any]] = []

        if dataset_type == "tag_extraction":
            templates = [
                ("How are you feeling?", '*smiles warmly* [ACTION:twirls hair] "I\'m feeling great today!" [MOOD:happy] [STAT:trust+2]'),
                ("Tell me about yourself", '*leans back* [ACTION:crosses legs] "Well, I\'m quite the adventurer..." [MOOD:confident]'),
                ("I missed you", '*blushes* [ACTION:looks down shyly] "I... I missed you too." [MOOD:bashful] [STAT:affection+5]'),
                ("Want to play a game?", '*eyes light up* [ACTION:claps hands] "Oh yes! What kind of game?" [MOOD:excited] [STAT:engagement+3]'),
                ("That was rude", '*frowns* [ACTION:crosses arms] "I didn\'t mean it that way..." [MOOD:defensive] [STAT:trust-3]'),
            ]
            for i in range(min(count, len(templates))):
                user, assistant = templates[i]
                pair = {
                    "user": user,
                    "assistant": assistant,
                    "dataset_type": "tag_extraction",
                    "quality": 0.9,
                }
                examples.append(pair)
                self.capture_interaction(
                    user, assistant,
                    dataset_type="tag_extraction",
                    quality_score=0.9,
                )

        elif dataset_type == "tool_routing":
            templates = [
                ("What's on TV?", "search_media", "MEDIA"),
                ("Change into something sexy", "wardrobe_change", "GAME"),
                ("How do you feel about me?", "check_relationship", "SOCIAL"),
                ("Remember when we first met?", "search_memory", "MEMORY"),
                ("Take a photo", "generate_image", "MEDIA"),
            ]
            for i in range(min(count, len(templates))):
                user, tool, category = templates[i]
                assistant = f'<tool_call>{{"name":"{tool}","arguments":{{}}}}</tool_call>'
                pair = {
                    "user": user,
                    "assistant": assistant,
                    "dataset_type": "tool_routing",
                    "quality": 0.9,
                }
                examples.append(pair)
                self.capture_interaction(
                    user, assistant,
                    dataset_type="tool_routing",
                    quality_score=0.9,
                )

        return examples


# ══════════════════════════════════════════════════════════════════════
#  Singleton access
# ══════════════════════════════════════════════════════════════════════

_pipeline: Optional[TrainingPipeline] = None


def get_training_pipeline() -> TrainingPipeline:
    """Get or create the singleton TrainingPipeline instance."""
    global _pipeline
    if _pipeline is None:
        _pipeline = TrainingPipeline()
    return _pipeline
