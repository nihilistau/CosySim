"""Conversation trainer — builds per-character dialog datasets and trains conversational models."""
from __future__ import annotations

import json
import logging
import threading
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

_CONV_DATA_DIR = Path("training/datasets")
_instance: Optional["ConversationTrainer"] = None
_lock = threading.Lock()


@dataclass
class ConvSample:
    """A single conversation training sample."""

    character_id: str
    system_prompt: str
    turns: List[Dict[str, str]]
    quality_rating: float = 1.0
    source: str = "event_chain"
    timestamp: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())

    def to_alpaca(self) -> Dict[str, Any]:
        """Convert to Alpaca training format.

        Returns:
            Alpaca-formatted dict with instruction, input, output fields.
        """
        turns_text = "\n".join(
            f"{t.get('role', 'user').upper()}: {t.get('content', '')}"
            for t in self.turns[:-1]
        ) if len(self.turns) > 1 else ""

        last_turn = self.turns[-1] if self.turns else {}
        response = last_turn.get("content", "") if last_turn.get("role") == "assistant" else ""

        return {
            "instruction": self.system_prompt or "Continue this conversation naturally, in character.",
            "input": turns_text,
            "output": response,
            "metadata": {
                "character_id": self.character_id,
                "source": self.source,
                "quality_rating": self.quality_rating,
            },
        }


class ConversationTrainer:
    """Builds per-character dialog datasets and manages conversational fine-tuning.

    Extracts samples from:
    1. EventChain dialog logs
    2. Nexus dialog knowledge entries
    3. Directly collected ConvSamples via DataCollector

    Outputs Alpaca-format JSONL files ready for FinetuneOrchestrator.
    """

    def __init__(self, base_dir: Optional[Path] = None) -> None:
        """Initialize ConversationTrainer.

        Args:
            base_dir: Base directory for datasets. Defaults to training/datasets.
        """
        self._base_dir = base_dir or _CONV_DATA_DIR
        self._base_dir.mkdir(parents=True, exist_ok=True)
        self._active_jobs: Dict[str, str] = {}
        self._write_lock = threading.Lock()

    # ── Public API ────────────────────────────────────────────────────────────

    def build_dataset(
        self,
        character_id: Optional[str] = None,
        output_path: Optional[str] = None,
        min_quality: float = 0.6,
        max_samples: int = 5000,
    ) -> str:
        """Build a conversational training dataset.

        Extracts samples from EventChain and Nexus, filters by quality,
        and writes an Alpaca-format JSONL file.

        Args:
            character_id: If specified, only include samples for this character.
            output_path: Output file path. Defaults to training/datasets/conversational_train.jsonl.
            min_quality: Minimum quality rating threshold.
            max_samples: Maximum number of samples to include.

        Returns:
            Path to the generated dataset file.
        """
        if output_path is None:
            suffix = f"_{character_id}" if character_id else ""
            output_path = str(self._base_dir / f"conversational{suffix}_train.jsonl")

        samples: List[ConvSample] = []

        # Extract from EventChain
        ec_samples = self.extract_from_event_chain(character_id=character_id, limit=max_samples)
        samples.extend(ec_samples)
        logger.info(f"ConversationTrainer: extracted {len(ec_samples)} samples from EventChain")

        # Extract from Nexus
        nexus_samples = self.extract_from_nexus(character_id=character_id, limit=max_samples)
        samples.extend(nexus_samples)
        logger.info(f"ConversationTrainer: extracted {len(nexus_samples)} samples from Nexus")

        # Extract from collected data
        collected_samples = self.extract_from_collected(character_id=character_id)
        samples.extend(collected_samples)
        logger.info(f"ConversationTrainer: extracted {len(collected_samples)} samples from collected data")

        # Filter by quality
        samples = [s for s in samples if s.quality_rating >= min_quality]

        # Deduplicate by turn content
        seen: set = set()
        unique_samples: List[ConvSample] = []
        for s in samples:
            key = json.dumps(s.turns, sort_keys=True)[:200]
            if key not in seen:
                seen.add(key)
                unique_samples.append(s)

        # Limit
        unique_samples = unique_samples[:max_samples]

        # Write output
        out_path = Path(output_path)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        with self._write_lock:
            with out_path.open("w", encoding="utf-8") as f:
                for sample in unique_samples:
                    f.write(json.dumps(sample.to_alpaca()) + "\n")

        logger.info(
            f"ConversationTrainer: wrote {len(unique_samples)} samples to {output_path}"
        )

        # Store stats in Nexus
        try:
            from engine.nexus.client import get_nexus_client
            client = get_nexus_client()
            client.add_entry(
                title=f"ConversationTrainer: dataset built{'for ' + character_id if character_id else ''}",
                content=f"Samples: {len(unique_samples)}, path: {output_path}",
                content_type="history",
                category="training",
            )
        except Exception:
            pass

        return output_path

    def build_all_characters(
        self,
        character_ids: Optional[List[str]] = None,
        min_quality: float = 0.6,
    ) -> Dict[str, str]:
        """Build datasets for all characters.

        Args:
            character_ids: List of character IDs. Defaults to all known characters.
            min_quality: Minimum quality threshold.

        Returns:
            Dict mapping character_id to output dataset path.
        """
        if character_ids is None:
            character_ids = ["aria", "lola", "viktor", "frankie", "mira"]

        results: Dict[str, str] = {}
        for char_id in character_ids:
            try:
                path = self.build_dataset(character_id=char_id, min_quality=min_quality)
                results[char_id] = path
            except Exception as e:
                logger.error(f"ConversationTrainer.build_all_characters failed for {char_id}: {e}")

        return results

    def extract_from_event_chain(
        self,
        character_id: Optional[str] = None,
        limit: int = 2000,
    ) -> List[ConvSample]:
        """Extract conversation samples from the EventChain database.

        Args:
            character_id: Optional filter by character ID.
            limit: Maximum number of samples to extract.

        Returns:
            List of ConvSample extracted from EventChain logs.
        """
        samples: List[ConvSample] = []
        try:
            from engine.mcp import get_dialog_system
            dialog = get_dialog_system()
            conversations = dialog.list_conversations(limit=limit)
            for conv in conversations:
                if character_id and conv.get("character_id") != character_id:
                    continue
                turns = conv.get("turns", [])
                if len(turns) < 2:
                    continue
                sample = ConvSample(
                    character_id=conv.get("character_id", "unknown"),
                    system_prompt=conv.get("system_prompt", ""),
                    turns=turns,
                    quality_rating=conv.get("quality_rating", 0.8),
                    source="event_chain",
                )
                samples.append(sample)
        except Exception as e:
            logger.debug(f"ConversationTrainer.extract_from_event_chain: {e}")
        return samples

    def extract_from_nexus(
        self,
        character_id: Optional[str] = None,
        limit: int = 1000,
    ) -> List[ConvSample]:
        """Extract conversation samples from Nexus knowledge entries.

        Args:
            character_id: Optional filter by character ID.
            limit: Maximum number of samples to extract.

        Returns:
            List of ConvSample extracted from Nexus.
        """
        samples: List[ConvSample] = []
        try:
            from engine.nexus.client import get_nexus_client
            client = get_nexus_client()
            query = f"dialog conversation {character_id}" if character_id else "dialog conversation scene"
            results = client.search(query, limit=limit)
            for entry in results:
                content = entry.get("content", "")
                if not content:
                    continue
                try:
                    data = json.loads(content)
                    turns = data.get("turns", [])
                    if len(turns) >= 2:
                        sample = ConvSample(
                            character_id=data.get("character_id", character_id or "unknown"),
                            system_prompt=data.get("system_prompt", ""),
                            turns=turns,
                            quality_rating=data.get("quality_rating", 0.7),
                            source="nexus",
                        )
                        samples.append(sample)
                except (json.JSONDecodeError, KeyError):
                    pass
        except Exception as e:
            logger.debug(f"ConversationTrainer.extract_from_nexus: {e}")
        return samples

    def extract_from_collected(
        self,
        character_id: Optional[str] = None,
    ) -> List[ConvSample]:
        """Extract conversation samples from DataCollector live files.

        Args:
            character_id: Optional filter by character ID.

        Returns:
            List of ConvSample from live collected data.
        """
        samples: List[ConvSample] = []
        collected_path = Path("training/datasets/collected/conversational_live.jsonl")
        if not collected_path.exists():
            return samples
        try:
            with collected_path.open("r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        record = json.loads(line)
                        meta = record.get("metadata", {})
                        char_id = meta.get("character_id", "unknown")
                        if character_id and char_id != character_id:
                            continue
                        history = meta.get("history", [])
                        response = record.get("output", "")
                        if history and response:
                            all_turns = list(history) + [{"role": "assistant", "content": response}]
                            sample = ConvSample(
                                character_id=char_id,
                                system_prompt=meta.get("system_prompt", ""),
                                turns=all_turns,
                                quality_rating=record.get("quality", 1.0),
                                source="collected",
                            )
                            samples.append(sample)
                    except (json.JSONDecodeError, KeyError):
                        continue
        except Exception as e:
            logger.debug(f"ConversationTrainer.extract_from_collected: {e}")
        return samples

    def get_status(self) -> Dict[str, Any]:
        """Get current status of all conversation datasets.

        Returns:
            Dict with dataset_sizes and active_jobs info.
        """
        dataset_sizes: Dict[str, int] = {}
        if self._base_dir.exists():
            for path in self._base_dir.glob("conversational*_train.jsonl"):
                name = path.stem.replace("_train", "")
                try:
                    count = sum(1 for line in path.open("r", encoding="utf-8") if line.strip())
                    dataset_sizes[name] = count
                except Exception:
                    dataset_sizes[name] = 0

        return {
            "dataset_sizes": dataset_sizes,
            "active_jobs": dict(self._active_jobs),
        }


def get_conversation_trainer() -> ConversationTrainer:
    """Get the ConversationTrainer singleton.

    Returns:
        The global ConversationTrainer instance.
    """
    global _instance
    if _instance is None:
        with _lock:
            if _instance is None:
                _instance = ConversationTrainer()
    return _instance
