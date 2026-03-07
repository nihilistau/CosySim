"""Tests for structured Copilot context packets."""

from __future__ import annotations

import json

from engine.nexus.copilot_context import (
    build_context_packet,
    packet_entry_payload,
    parse_context_packet,
    render_context_template_reference,
)


def test_build_context_packet_compacts_recent_history() -> None:
    """Context packets should preserve the most useful recent state."""
    packet = build_context_packet(
        "checkpoint",
        session={"session_id": "s1", "prompts": 3},
        git_ctx={"branch": "main", "last_commit": "abc123"},
        history={
            "plan": "A" * 2600,
            "turns": [
                {"turn": 1, "user": "Investigate hooks", "assistant": "Decision: Keep hook control active."},
                {"turn": 2, "user": "Store the packet", "assistant": "Updated: Session logger now stores packets."},
            ],
            "checkpoints": [{"number": 1, "title": "Control Plane Unification", "overview": "overview", "work_done": "done"}],
        },
        hook_snapshot={"event": "checkpoint"},
        generated_at="2026-03-07T14:00:00+00:00",
    )

    assert packet["packet_type"] == "checkpoint"
    assert packet["session"]["focus"] == "Control Plane Unification"
    assert packet["git"]["branch"] == "main"
    assert packet["history"]["recent_turns"][-1]["user"] == "Store the packet"
    assert packet["history"]["key_decisions"][0].startswith("Decision:")
    assert packet["plan"]["present"] is True
    assert len(packet["plan"]["excerpt"]) < 2600


def test_packet_entry_payload_wraps_packet_for_nexus() -> None:
    """Context packets should be serializable as history entries."""
    packet = build_context_packet("compaction", generated_at="2026-03-07T14:05:00+00:00")
    payload = packet_entry_payload(packet, branch="main")

    assert payload["content_type"] == "history"
    assert payload["category"] == "sessions"
    assert "context-packet" in payload["tags"]
    assert "main" in payload["tags"]
    assert json.loads(payload["content"])["packet_type"] == "compaction"


def test_parse_context_packet_returns_empty_dict_on_invalid_json() -> None:
    """Invalid stored packet content should not raise on reload."""
    assert parse_context_packet("{not json}") == {}


def test_render_context_template_reference_lists_templates() -> None:
    """Notebook-friendly context template references should mention packet families."""
    reference = render_context_template_reference()

    assert "copilot-checkpoint-context-v1" in reference
    assert "copilot-compaction-context-v1" in reference
    assert "Load the latest context packet on startup." in reference
