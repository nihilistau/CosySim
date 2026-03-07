"""Tests for Action Manifest helpers."""
from __future__ import annotations

from engine.nexus.action_manifest import build_preplan_manifest


def test_build_preplan_manifest_preserves_context_files():
    """Manifest keeps provided context files and extracts steps."""
    manifest = build_preplan_manifest(
        "Patch router fallback",
        [
            {
                "question": "Which file should be updated to add the fallback?",
                "answer": "Update engine/nexus/query_router.py to add the direct NotebookLM fallback.",
                "source": "nlm",
            }
        ],
        context_files=["engine\\nexus\\query_router.py"],
    )

    data = manifest.to_dict()
    assert data["context_files"] == ["engine\\nexus\\query_router.py"]
    assert data["steps"][0]["target_file"] == "engine/nexus/query_router.py"
    assert data["steps"][0]["action_type"] == "EDIT"


def test_build_preplan_manifest_groups_validation_steps():
    """Validation questions land in the validation milestone."""
    manifest = build_preplan_manifest(
        "Validate bridge changes",
        [
            {
                "question": "What tests should we run to validate the change?",
                "answer": "Run python -m pytest tests/test_copilot_bridge.py -q.",
                "source": "nlm",
            }
        ],
    )

    data = manifest.to_dict()
    assert data["milestones"][0]["title"] == "Validate the outcome"
    assert data["steps"][0]["action_type"] == "TEST"
    assert data["steps"][0]["validation"]


def test_build_preplan_manifest_creates_dependency_chain():
    """Steps are linked in execution order for downstream agents."""
    manifest = build_preplan_manifest(
        "Implement and verify",
        [
            {
                "question": "Which module should be edited?",
                "answer": "Edit engine/nexus/copilot_bridge.py to persist the manifest artifact.",
                "source": "nlm",
            },
            {
                "question": "How should we validate it?",
                "answer": "Run focused regression tests after the edit.",
                "source": "nlm",
            },
        ],
    )

    data = manifest.to_dict()
    assert data["steps"][0]["dependencies"] == []
    assert data["steps"][1]["dependencies"] == ["step-01"]
    assert data["next_actions"][0].startswith("step-01:")
