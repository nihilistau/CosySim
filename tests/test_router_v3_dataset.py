"""Tests for the router_v3 training dataset."""
from __future__ import annotations

import json
from collections import Counter
from pathlib import Path

DATASET = Path("training/datasets/router_v3.jsonl")
EXPECTED_CLASSES = {
    "small_talk", "game_action", "story_narrative", "character_emotion",
    "world_query", "skill_call", "memory_recall", "scene_transition",
    "system_command", "creative_generation", "information_lookup",
    "emotional_support", "adult_content", "combat_narrative",
    "economic_action", "investigation",
}


class TestRouterV3Dataset:
    @classmethod
    def setup_class(cls) -> None:
        assert DATASET.exists(), f"Dataset missing: {DATASET}"
        with open(DATASET, encoding="utf-8") as f:
            cls.examples = [json.loads(line) for line in f if line.strip()]

    def test_minimum_size(self) -> None:
        assert len(self.examples) >= 2000, f"Only {len(self.examples)} examples"

    def test_all_classes_present(self) -> None:
        found = {e["label"] for e in self.examples}
        missing = EXPECTED_CLASSES - found
        assert not missing, f"Missing classes: {missing}"

    def test_class_count(self) -> None:
        found = {e["label"] for e in self.examples}
        assert len(found) == 16, f"Expected 16 classes, got {len(found)}"

    def test_balanced_distribution(self) -> None:
        counts = Counter(e["label"] for e in self.examples)
        min_count = min(counts.values())
        max_count = max(counts.values())
        assert max_count / min_count <= 3, f"Imbalanced: {min_count}-{max_count}"

    def test_example_format(self) -> None:
        ex = self.examples[0]
        assert "messages" in ex
        assert "label" in ex
        assert ex["label"] in EXPECTED_CLASSES
        assert isinstance(ex["messages"], list)
        assert ex["messages"][0]["role"] == "user"

    def test_no_empty_messages(self) -> None:
        for ex in self.examples:
            for msg in ex["messages"]:
                assert msg["content"].strip(), "Empty message content"

    def test_class_description_present(self) -> None:
        for ex in self.examples:
            assert "class_description" in ex, f"Missing class_description in {ex}"
            assert ex["class_description"].strip(), "Empty class_description"
