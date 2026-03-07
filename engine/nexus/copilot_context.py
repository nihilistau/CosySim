"""Structured Copilot context templates for checkpoints, compaction, and resume.

These templates keep the Copilot/Nexus control plane aligned around a stable
set of packet shapes that can be persisted to Nexus, reloaded at startup, and
used to prime the next work block with the right operating context.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

MAIN_SYSTEMS = [
    "NLM & COLAB",
    "NEXUS",
    "COPILOT",
    "ARGUS",
    "TRAINING",
    "LMSTUDIO",
    "CREDS/AUTH",
    "USER INTERFACE",
    "SCENES",
    "LAUNCHER",
    "CLI",
    "CDP/BROWSER",
    "DOCS",
]

PROJECT_GOAL = (
    "Bring the Copilot, Nexus, NotebookLM, Colab, ARGUS, LMStudio, auth, UI, "
    "scene, launcher, and CLI systems into one Nexus-first control plane that "
    "stores the right context as it works and reuses that context on the next "
    "startup instead of rediscovering it."
)

CAPTURE_POLICY = {
    "nexus_first": True,
    "backfill_external_discoveries": True,
    "preferred_capture": ["knowledge_entry", "qa_pair"],
    "browser_attached_notebooklm_auth": True,
    "chain_prompting_enabled": True,
}

TEMPLATE_IDS = {
    "checkpoint": "copilot-checkpoint-context-v1",
    "compaction": "copilot-compaction-context-v1",
    "startup": "copilot-startup-context-v1",
}


def _now() -> str:
    """Return an ISO timestamp for packet generation."""
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _truncate(value: str, *, limit: int) -> str:
    """Return a compact string suitable for context packets."""
    if len(value) <= limit:
        return value
    shortened = value[: limit - 3].rstrip()
    if " " in shortened:
        shortened = shortened.rsplit(" ", 1)[0]
    return f"{shortened}..."


def _single_line(value: str) -> str:
    """Collapse repeated whitespace for compact summaries."""
    return " ".join(str(value).split())


def _recent_turns(history: Dict[str, Any], limit: int = 3) -> List[Dict[str, str]]:
    """Return the most recent conversation turns in compact form."""
    turns = history.get("turns", []) or []
    compact: List[Dict[str, str]] = []
    for turn in turns[-limit:]:
        compact.append(
            {
                "turn": str(turn.get("turn", "")),
                "user": _truncate(_single_line(str(turn.get("user", ""))), limit=220),
                "assistant": _truncate(_single_line(str(turn.get("assistant", ""))), limit=320),
            }
        )
    return compact


def _recent_checkpoints(history: Dict[str, Any], limit: int = 5) -> List[Dict[str, str]]:
    """Return the newest checkpoint summaries."""
    checkpoints = history.get("checkpoints", []) or []
    compact: List[Dict[str, str]] = []
    for checkpoint in checkpoints[-limit:]:
        compact.append(
            {
                "number": str(checkpoint.get("number", "")),
                "title": str(checkpoint.get("title", "")),
                "overview": _truncate(_single_line(str(checkpoint.get("overview", ""))), limit=220),
                "work_done": _truncate(_single_line(str(checkpoint.get("work_done", ""))), limit=220),
            }
        )
    return compact


def _key_decisions(history: Dict[str, Any], limit: int = 8) -> List[str]:
    """Extract lightweight decision markers from recent assistant messages."""
    markers = ("Decision:", "Fixed:", "Created:", "Added:", "Updated:", "Result:", "Architecture:")
    decisions: List[str] = []
    for turn in history.get("turns", []) or []:
        assistant = str(turn.get("assistant", ""))
        for marker in markers:
            if marker in assistant:
                snippet = assistant[assistant.index(marker):].splitlines()[0]
                compact = _truncate(_single_line(snippet), limit=220)
                if compact not in decisions:
                    decisions.append(compact)
    return decisions[:limit]


def build_context_packet(
    packet_type: str,
    *,
    session: Optional[Dict[str, Any]] = None,
    git_ctx: Optional[Dict[str, Any]] = None,
    history: Optional[Dict[str, Any]] = None,
    hook_snapshot: Optional[Dict[str, Any]] = None,
    generated_at: str = "",
) -> Dict[str, Any]:
    """Build a structured Copilot context packet for durable reloads."""
    session = dict(session or {})
    git_ctx = dict(git_ctx or {})
    history = dict(history or {})
    packet_timestamp = generated_at or _now()
    template_id = TEMPLATE_IDS.get(packet_type, f"copilot-{packet_type}-context-v1")
    plan_excerpt = _truncate(str(history.get("plan", "")), limit=2500)
    focus_title = ""
    checkpoints = _recent_checkpoints(history)
    if checkpoints:
        focus_title = checkpoints[-1].get("title", "")
    elif history.get("turns"):
        focus_title = _truncate(_single_line(str(history["turns"][-1].get("user", ""))), limit=120)

    return {
        "template_id": template_id,
        "packet_type": packet_type,
        "generated_at": packet_timestamp,
        "session": {
            "session_id": str(session.get("session_id", "")),
            "nexus_session_id": str(session.get("nexus_session_id", "")),
            "cwd": str(session.get("cwd", "")),
            "started_at": str(session.get("started_at", "")),
            "last_prompt_at": str(session.get("last_prompt_at", "")),
            "prompts": int(session.get("prompts", 0) or 0),
            "focus": focus_title,
        },
        "project": {
            "goal": PROJECT_GOAL,
            "main_systems": list(MAIN_SYSTEMS),
            "capture_policy": dict(CAPTURE_POLICY),
            "template_family": list(TEMPLATE_IDS.values()),
            "reload_contract": [
                "Load onboarding rules, resume handoff, and the latest context packet before planning new work.",
                "Use Nexus-first retrieval and backfill any external discoveries before moving on.",
                "Prefer browser-attached NotebookLM auth/session recovery before deep notebook workflows.",
            ],
        },
        "git": {
            "branch": str(git_ctx.get("branch", "")),
            "last_commit": str(git_ctx.get("last_commit", "")),
            "recent_commits": list(git_ctx.get("recent_commits", []) or [])[:5],
            "modified_files": list(git_ctx.get("modified_files", []) or [])[:20],
        },
        "history": {
            "checkpoint_count": len(history.get("checkpoints", []) or []),
            "files_touched": list(history.get("files", []) or [])[:20],
            "recent_checkpoints": checkpoints,
            "recent_turns": _recent_turns(history),
            "key_decisions": _key_decisions(history),
            "references": list(history.get("refs", []) or [])[:10],
        },
        "plan": {
            "present": bool(history.get("plan")),
            "excerpt": plan_excerpt,
        },
        "hook_snapshot": dict(hook_snapshot or {}),
        "reload_guidance": [
            "Prime the next session with this packet plus the latest resume handoff.",
            "Check hook, Nexus, NotebookLM, and launcher health before large edits.",
            "Treat this packet as the compacted immediate context for restart and compaction recovery.",
        ],
    }


def packet_entry_payload(
    packet: Dict[str, Any],
    *,
    branch: str = "",
) -> Dict[str, Any]:
    """Build a Nexus entry payload for a context packet."""
    packet_type = str(packet.get("packet_type", "context"))
    generated_at = str(packet.get("generated_at", _now()))
    template_id = str(packet.get("template_id", "copilot-context-v1"))
    tags = ["copilot", "context-packet", packet_type, template_id]
    if branch:
        tags.append(branch)
    return {
        "title": f"Copilot Context Packet — {packet_type} — {generated_at}",
        "content": json.dumps(packet, indent=2),
        "content_type": "history",
        "category": "sessions",
        "tags": tags,
    }


def parse_context_packet(content: str) -> Dict[str, Any]:
    """Best-effort parse of a stored context packet from Nexus content."""
    try:
        parsed = json.loads(content)
        return parsed if isinstance(parsed, dict) else {}
    except Exception:
        return {}


def render_context_template_reference() -> str:
    """Render the stable context-template contract as notebook-friendly text."""
    sections = [
        "# Copilot Context Template Reference",
        "",
        "These templates define the compacted context Copilot should store and reload.",
        "",
        "## Templates",
    ]
    for packet_type, template_id in TEMPLATE_IDS.items():
        sections.extend(
            [
                f"- **{template_id}**",
                f"  - packet_type: `{packet_type}`",
                "  - required sections: session, project, git, history, plan, hook_snapshot, reload_guidance",
            ]
        )
    sections.extend(
        [
            "",
            "## Main systems",
            ", ".join(MAIN_SYSTEMS),
            "",
            "## Capture policy",
            json.dumps(CAPTURE_POLICY, indent=2),
            "",
            "## Reload guidance",
            "- Load the latest context packet on startup.",
            "- Pair it with resume handoff + onboarding rules before planning.",
            "- Treat it as the durable immediate-context bridge across compaction boundaries.",
        ]
    )
    return "\n".join(sections)
