"""Operator inbox for off-turn user directives and cockpit intake.

The inbox provides a durable communication path for requests that arrive outside
the normal Copilot turn flow. Each submission is stored in Nexus for durable
search/reuse and mirrored into a local JSON state file so workflow state
transitions (pending, queued, integrated, failed, done) can be tracked without
overloading the core Nexus entry schema.
"""
from __future__ import annotations

import argparse
import json
import logging
import sys
import threading
import uuid
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

from engine.config import get_config

logger = logging.getLogger(__name__)

VALID_ITEM_TYPES = {
    "feature",
    "change",
    "direction",
    "question",
    "note",
    "idea",
    "bug",
    "command",
}
VALID_STATUSES = {
    "pending",
    "queued",
    "integrated",
    "done",
    "archived",
    "failed",
}
VALID_PRIORITIES = {"low", "normal", "high", "critical"}
STATUS_ORDER = {
    "pending": 0,
    "queued": 1,
    "integrated": 2,
    "done": 3,
    "archived": 4,
    "failed": 5,
}
PRIORITY_ORDER = {
    "critical": 0,
    "high": 1,
    "normal": 2,
    "low": 3,
}


def _utc_now() -> str:
    """Return the current UTC time as an ISO-8601 string."""
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _normalise_item_type(value: str) -> str:
    """Return a supported inbox item type."""
    candidate = (value or "note").strip().lower()
    return candidate if candidate in VALID_ITEM_TYPES else "note"


def _normalise_status(value: str) -> str:
    """Return a supported inbox workflow status."""
    candidate = (value or "pending").strip().lower()
    return candidate if candidate in VALID_STATUSES else "pending"


def _normalise_priority(value: str) -> str:
    """Return a supported inbox priority label."""
    candidate = (value or "normal").strip().lower()
    return candidate if candidate in VALID_PRIORITIES else "normal"


def _tagify(value: str) -> str:
    """Convert a free-form value into a safe tag token."""
    token = (value or "").strip().lower().replace(" ", "-").replace("_", "-")
    return "".join(ch for ch in token if ch.isalnum() or ch == "-").strip("-")


def _dedupe_tags(tags: Optional[List[str]]) -> List[str]:
    """Return unique non-empty tags while preserving order."""
    result: List[str] = []
    seen = set()
    for tag in tags or []:
        cleaned = _tagify(str(tag))
        if cleaned and cleaned not in seen:
            seen.add(cleaned)
            result.append(cleaned)
    return result


@dataclass
class OperatorInboxItem:
    """A single operator submission tracked across review and planning."""

    item_id: str = field(default_factory=lambda: str(uuid.uuid4())[:12])
    title: str = ""
    content: str = ""
    item_type: str = "note"
    priority: str = "normal"
    status: str = "pending"
    source: str = "web"
    author: str = "user"
    tags: List[str] = field(default_factory=list)
    metadata: Dict[str, Any] = field(default_factory=dict)
    nexus_entry_id: str = ""
    task_id: str = ""
    digest_entry_id: str = ""
    processor_notes: str = ""
    created_at: str = field(default_factory=_utc_now)
    updated_at: str = field(default_factory=_utc_now)
    processed_at: str = ""

    def to_dict(self) -> Dict[str, Any]:
        """Return a JSON-serializable representation of the item."""
        return asdict(self)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "OperatorInboxItem":
        """Build an inbox item from a persisted state payload."""
        payload = dict(data or {})
        if "item_id" not in payload and "id" in payload:
            payload["item_id"] = payload["id"]
        return cls(
            item_id=str(payload.get("item_id", str(uuid.uuid4())[:12])),
            title=str(payload.get("title", "")),
            content=str(payload.get("content", "")),
            item_type=_normalise_item_type(str(payload.get("item_type", "note"))),
            priority=_normalise_priority(str(payload.get("priority", "normal"))),
            status=_normalise_status(str(payload.get("status", "pending"))),
            source=str(payload.get("source", "web") or "web"),
            author=str(payload.get("author", "user") or "user"),
            tags=_dedupe_tags(payload.get("tags", [])),
            metadata=dict(payload.get("metadata", {}) or {}),
            nexus_entry_id=str(payload.get("nexus_entry_id", "")),
            task_id=str(payload.get("task_id", "")),
            digest_entry_id=str(payload.get("digest_entry_id", "")),
            processor_notes=str(payload.get("processor_notes", "")),
            created_at=str(payload.get("created_at", _utc_now())),
            updated_at=str(payload.get("updated_at", payload.get("created_at", _utc_now()))),
            processed_at=str(payload.get("processed_at", "")),
        )


class OperatorInbox:
    """Durable intake queue for off-turn operator notes and commands."""

    def __init__(
        self,
        config: Optional[Any] = None,
        state_path: Optional[Path] = None,
    ) -> None:
        self._config = config or get_config()
        configured_path = state_path or Path(
            self._config.get(
                "nexus.operator_inbox.state_path",
                "data/operator_inbox_state.json",
            )
        )
        self._state_path = Path(configured_path)
        self._digest_limit = int(
            self._config.get("nexus.operator_inbox.plan_digest_limit", 10)
        )
        self._lock = threading.RLock()
        self._items: Dict[str, OperatorInboxItem] = {}
        self._load_state()

    def list_items(
        self,
        *,
        status: str = "",
        item_type: str = "",
        limit: int = 50,
    ) -> List[OperatorInboxItem]:
        """Return inbox items sorted for UI and planning consumption."""
        desired_status = _normalise_status(status) if status else ""
        desired_type = _normalise_item_type(item_type) if item_type else ""
        with self._lock:
            items = list(self._items.values())
        if desired_status:
            items = [item for item in items if item.status == desired_status]
        if desired_type:
            items = [item for item in items if item.item_type == desired_type]
        items.sort(
            key=lambda item: (
                STATUS_ORDER.get(item.status, 99),
                PRIORITY_ORDER.get(item.priority, 99),
                item.updated_at,
            ),
            reverse=False,
        )
        return items[: max(1, int(limit))]

    def get_item(self, item_id: str) -> Optional[OperatorInboxItem]:
        """Return a single inbox item by ID."""
        with self._lock:
            return self._items.get(item_id)

    def get_summary(self) -> Dict[str, Any]:
        """Return queue counts for dashboard badges and onboarding."""
        with self._lock:
            items = list(self._items.values())
        by_status = {status: 0 for status in VALID_STATUSES}
        by_type = {item_type: 0 for item_type in VALID_ITEM_TYPES}
        for item in items:
            by_status[item.status] = by_status.get(item.status, 0) + 1
            by_type[item.item_type] = by_type.get(item.item_type, 0) + 1
        return {
            "total": len(items),
            "pending": by_status.get("pending", 0),
            "queued": by_status.get("queued", 0),
            "integrated": by_status.get("integrated", 0),
            "done": by_status.get("done", 0),
            "failed": by_status.get("failed", 0),
            "by_status": by_status,
            "by_type": by_type,
            "latest_update": max((item.updated_at for item in items), default=""),
        }

    def submit_item(
        self,
        *,
        title: str,
        content: str,
        item_type: str = "note",
        priority: str = "normal",
        tags: Optional[List[str]] = None,
        source: str = "web",
        author: str = "user",
        metadata: Optional[Dict[str, Any]] = None,
    ) -> OperatorInboxItem:
        """Store a new operator submission in Nexus and local workflow state."""
        clean_title = (title or "").strip()
        clean_content = (content or "").strip()
        if not clean_title:
            raise ValueError("title is required")
        if not clean_content:
            raise ValueError("content is required")

        item = OperatorInboxItem(
            title=clean_title,
            content=clean_content,
            item_type=_normalise_item_type(item_type),
            priority=_normalise_priority(priority),
            source=(source or "web").strip() or "web",
            author=(author or "user").strip() or "user",
            tags=_dedupe_tags(tags),
            metadata=dict(metadata or {}),
        )
        entry_id = self._store_item_entry(item)
        if not entry_id:
            raise RuntimeError("failed to store operator inbox item in Nexus")
        item.nexus_entry_id = entry_id

        with self._lock:
            self._items[item.item_id] = item
            self._save_state()
        return item

    def update_item_status(
        self,
        item_id: str,
        *,
        status: str,
        processor_notes: str = "",
        task_id: str = "",
        digest_entry_id: str = "",
    ) -> OperatorInboxItem:
        """Update workflow state for an existing inbox item."""
        with self._lock:
            item = self._items.get(item_id)
            if item is None:
                raise KeyError(f"unknown operator inbox item: {item_id}")
            item.status = _normalise_status(status)
            if processor_notes:
                item.processor_notes = processor_notes.strip()
            if task_id:
                item.task_id = task_id
            if digest_entry_id:
                item.digest_entry_id = digest_entry_id
            if item.status != "pending":
                item.processed_at = _utc_now()
            item.updated_at = _utc_now()
            self._save_state()

        if not self._sync_item_entry(item):
            raise RuntimeError(f"failed to sync operator inbox item {item_id} to Nexus")
        return item

    def process_items(
        self,
        *,
        item_ids: Optional[List[str]] = None,
        limit: Optional[int] = None,
    ) -> Dict[str, Any]:
        """Promote pending inbox items into tasks and a Copilot plan digest."""
        candidates = self._resolve_candidates(item_ids=item_ids, limit=limit)
        if not candidates:
            return {
                "ok": True,
                "processed": 0,
                "created_tasks": 0,
                "digest_entry_id": "",
                "items": [],
                "errors": [],
            }

        from engine.nexus.task_scheduler import (
            TaskComplexity,
            TaskPriority,
            get_task_scheduler,
        )

        scheduler = get_task_scheduler()
        queued_items: List[Dict[str, Any]] = []
        errors: List[Dict[str, Any]] = []
        priority_map = {
            "low": TaskPriority.LOW,
            "normal": TaskPriority.MEDIUM,
            "high": TaskPriority.HIGH,
            "critical": TaskPriority.CRITICAL,
        }
        complexity_map = {
            "note": TaskComplexity.LOW,
            "idea": TaskComplexity.LOW,
            "question": TaskComplexity.MEDIUM,
            "feature": TaskComplexity.HIGH,
            "change": TaskComplexity.MEDIUM,
            "direction": TaskComplexity.MEDIUM,
            "bug": TaskComplexity.HIGH,
            "command": TaskComplexity.MEDIUM,
        }

        for item in candidates:
            try:
                task = scheduler.create_task(
                    title=f"Operator: {item.title}",
                    description=self._render_task_description(item),
                    priority=priority_map.get(item.priority, TaskPriority.MEDIUM),
                    complexity=complexity_map.get(item.item_type, TaskComplexity.MEDIUM),
                    allowed_operations=["read", "edit", "create", "test"],
                    target_files=list(item.metadata.get("target_files", []))
                    if isinstance(item.metadata.get("target_files"), list)
                    else [],
                    tags=[
                        "operator-request",
                        item.item_type,
                        f"priority-{item.priority}",
                        "copilot",
                    ]
                    + item.tags,
                )
                queued_items.append(
                    {
                        "item": item,
                        "task_id": task.id,
                        "title": task.title,
                        "status": "queued",
                        "summary": f"Queued operator {item.item_type} for follow-up.",
                    }
                )
            except Exception as exc:
                logger.warning("Operator inbox task creation failed for %s: %s", item.item_id, exc)
                errors.append(
                    {
                        "item_id": item.item_id,
                        "title": item.title,
                        "error": str(exc),
                    }
                )

        digest_entry_id = ""
        if queued_items:
            digest_entry_id = self._store_plan_digest(queued_items) or ""

        for queued in queued_items:
            try:
                self.update_item_status(
                    queued["item"].item_id,
                    status=queued["status"],
                    task_id=queued["task_id"],
                    digest_entry_id=digest_entry_id,
                    processor_notes=queued["summary"],
                )
            except Exception as exc:
                errors.append(
                    {
                        "item_id": queued["item"].item_id,
                        "title": queued["item"].title,
                        "error": str(exc),
                    }
                )

        return {
            "ok": len(errors) == 0,
            "processed": len(queued_items),
            "created_tasks": len(queued_items),
            "digest_entry_id": digest_entry_id,
            "items": [
                {
                    "item_id": queued["item"].item_id,
                    "title": queued["item"].title,
                    "task_id": queued["task_id"],
                }
                for queued in queued_items
            ],
            "errors": errors,
        }

    def pending_for_onboarding(self, limit: int = 5) -> Dict[str, Any]:
        """Return a compact operator-directive summary for Copilot onboarding."""
        items = self.list_items(status="pending", limit=limit)
        return {
            "summary": self.get_summary(),
            "items": [
                {
                    "item_id": item.item_id,
                    "title": item.title,
                    "item_type": item.item_type,
                    "priority": item.priority,
                    "created_at": item.created_at,
                }
                for item in items
            ],
        }

    def _resolve_candidates(
        self,
        *,
        item_ids: Optional[List[str]],
        limit: Optional[int],
    ) -> List[OperatorInboxItem]:
        """Resolve which pending items should be processed in this cycle."""
        with self._lock:
            items = list(self._items.values())
        if item_ids:
            wanted = set(item_ids)
            filtered = [item for item in items if item.item_id in wanted]
        else:
            filtered = items
        filtered = [item for item in filtered if item.status == "pending"]
        filtered.sort(
            key=lambda item: (
                PRIORITY_ORDER.get(item.priority, 99),
                item.created_at,
            )
        )
        if limit is not None:
            filtered = filtered[: max(1, int(limit))]
        else:
            filtered = filtered[: self._digest_limit]
        return filtered

    def _render_task_description(self, item: OperatorInboxItem) -> str:
        """Build the task description mirrored into the agent queue."""
        metadata = json.dumps(item.metadata, indent=2, sort_keys=True) if item.metadata else "{}"
        return (
            f"Operator inbox item: {item.item_id}\n"
            f"Type: {item.item_type}\n"
            f"Priority: {item.priority}\n"
            f"Source: {item.source}\n"
            f"Author: {item.author}\n"
            f"Nexus Entry: {item.nexus_entry_id or 'pending'}\n\n"
            f"{item.content}\n\n"
            f"Metadata:\n{metadata}"
        )

    def _render_entry_title(self, item: OperatorInboxItem) -> str:
        """Build the human-readable Nexus entry title for an inbox item."""
        return f"Operator Inbox [{item.item_type}] {item.title}"

    def _render_entry_content(self, item: OperatorInboxItem) -> str:
        """Build the Nexus content body for an inbox item."""
        metadata = json.dumps(item.metadata, indent=2, sort_keys=True) if item.metadata else "{}"
        processor_notes = item.processor_notes or "Not processed yet."
        return (
            "Operator inbox item captured for Copilot planning and queue integration.\n\n"
            f"- Item ID: {item.item_id}\n"
            f"- Type: {item.item_type}\n"
            f"- Priority: {item.priority}\n"
            f"- Status: {item.status}\n"
            f"- Source: {item.source}\n"
            f"- Author: {item.author}\n"
            f"- Nexus Entry: {item.nexus_entry_id or 'pending'}\n"
            f"- Queue Task: {item.task_id or 'not queued'}\n"
            f"- Plan Digest: {item.digest_entry_id or 'not generated'}\n"
            f"- Created At: {item.created_at}\n"
            f"- Updated At: {item.updated_at}\n"
            f"- Processed At: {item.processed_at or 'pending'}\n\n"
            "## Request\n\n"
            f"{item.content}\n\n"
            "## Metadata\n\n"
            f"{metadata}\n\n"
            "## Processor Notes\n\n"
            f"{processor_notes}\n"
        )

    def _build_tags(self, item: OperatorInboxItem) -> List[str]:
        """Return the canonical tags applied to the mirrored Nexus entry."""
        auto_tags = [
            "copilot",
            "operator-inbox",
            "operator-request",
            _tagify(item.item_type),
            f"status-{_tagify(item.status)}",
            f"priority-{_tagify(item.priority)}",
            _tagify(item.source),
        ]
        if item.metadata.get("dispatch_mode"):
            auto_tags.append(f"dispatch-{_tagify(str(item.metadata['dispatch_mode']))}")
        if item.metadata.get("scene_id"):
            auto_tags.append(f"scene-{_tagify(str(item.metadata['scene_id']))}")
        return _dedupe_tags(auto_tags + item.tags)

    def _store_item_entry(self, item: OperatorInboxItem) -> Optional[str]:
        """Create the mirrored Nexus entry for a new inbox item."""
        from engine.nexus.client import get_nexus_client

        client = get_nexus_client()
        return client.add_entry(
            title=self._render_entry_title(item),
            content=self._render_entry_content(item),
            content_type="note",
            category="development",
            tags=self._build_tags(item),
            created_by="copilot",
            namespace="copilot",
        )

    def _sync_item_entry(self, item: OperatorInboxItem) -> bool:
        """Update the mirrored Nexus entry when workflow state changes."""
        if not item.nexus_entry_id:
            return False
        from engine.nexus.client import get_nexus_client

        client = get_nexus_client()
        return client.update_entry(
            item.nexus_entry_id,
            title=self._render_entry_title(item),
            content=self._render_entry_content(item),
            content_type="note",
            category="development",
            tags=self._build_tags(item),
            namespace="copilot",
        )

    def _store_plan_digest(self, queued_items: List[Dict[str, Any]]) -> Optional[str]:
        """Store a Copilot plan digest entry for a processed inbox batch."""
        from engine.nexus.client import get_nexus_client

        lines = [
            "Operator inbox digest generated from queued off-turn directives.",
            "",
            f"Items processed: {len(queued_items)}",
            "",
        ]
        for queued in queued_items:
            item = queued["item"]
            lines.extend(
                [
                    f"### {item.title}",
                    f"- Item ID: {item.item_id}",
                    f"- Type: {item.item_type}",
                    f"- Priority: {item.priority}",
                    f"- Queue Task: {queued['task_id']}",
                    f"- Nexus Entry: {item.nexus_entry_id}",
                    "",
                    item.content,
                    "",
                ]
            )

        client = get_nexus_client()
        return client.add_entry(
            title=f"Operator Inbox Digest — {_utc_now()}",
            content="\n".join(lines),
            content_type="document",
            category="copilot-plans",
            tags=["copilot", "operator-inbox", "plan-digest"],
            created_by="copilot",
            namespace="copilot",
        )

    def _load_state(self) -> None:
        """Load the workflow state file if it exists."""
        if not self._state_path.exists():
            return
        try:
            payload = json.loads(self._state_path.read_text(encoding="utf-8"))
            items = payload.get("items", [])
            self._items = {
                item["item_id"]: OperatorInboxItem.from_dict(item)
                for item in items
                if isinstance(item, dict)
            }
        except Exception as exc:
            logger.warning("Failed to load operator inbox state: %s", exc)
            self._items = {}

    def _save_state(self) -> None:
        """Persist workflow state to the configured JSON file."""
        payload = {
            "updated_at": _utc_now(),
            "items": [item.to_dict() for item in self.list_items(limit=10000)],
        }
        self._state_path.parent.mkdir(parents=True, exist_ok=True)
        self._state_path.write_text(
            json.dumps(payload, indent=2, ensure_ascii=True),
            encoding="utf-8",
        )


_operator_inbox: Optional[OperatorInbox] = None
_operator_inbox_lock = threading.Lock()


def get_operator_inbox() -> OperatorInbox:
    """Return the singleton operator inbox."""
    global _operator_inbox
    if _operator_inbox is None:
        with _operator_inbox_lock:
            if _operator_inbox is None:
                _operator_inbox = OperatorInbox()
    return _operator_inbox


def main(argv: Optional[List[str]] = None) -> int:
    """Simple CLI for submitting and reviewing operator inbox items."""
    parser = argparse.ArgumentParser(description="Operator inbox utility")
    subparsers = parser.add_subparsers(dest="command", required=True)

    submit = subparsers.add_parser("submit", help="Submit a new operator inbox item")
    submit.add_argument("title")
    submit.add_argument("content")
    submit.add_argument("--type", default="note", dest="item_type")
    submit.add_argument("--priority", default="normal")
    submit.add_argument("--source", default="cli")
    submit.add_argument("--author", default="user")
    submit.add_argument("--tags", nargs="*", default=[])

    list_cmd = subparsers.add_parser("list", help="List inbox items")
    list_cmd.add_argument("--status", default="")
    list_cmd.add_argument("--type", default="", dest="item_type")
    list_cmd.add_argument("--limit", type=int, default=20)

    process = subparsers.add_parser("process", help="Process pending inbox items")
    process.add_argument("--limit", type=int, default=10)

    subparsers.add_parser("summary", help="Show queue summary")

    args = parser.parse_args(argv)
    inbox = get_operator_inbox()

    if args.command == "submit":
        item = inbox.submit_item(
            title=args.title,
            content=args.content,
            item_type=args.item_type,
            priority=args.priority,
            source=args.source,
            author=args.author,
            tags=args.tags,
        )
        sys.stdout.write(f"{json.dumps(item.to_dict(), indent=2)}\n")
        return 0

    if args.command == "list":
        sys.stdout.write(
            f"{json.dumps([item.to_dict() for item in inbox.list_items(status=args.status, item_type=args.item_type, limit=args.limit)], indent=2)}\n"
        )
        return 0

    if args.command == "process":
        sys.stdout.write(f"{json.dumps(inbox.process_items(limit=args.limit), indent=2)}\n")
        return 0

    if args.command == "summary":
        sys.stdout.write(f"{json.dumps(inbox.get_summary(), indent=2)}\n")
        return 0

    return 1


if __name__ == "__main__":
    raise SystemExit(main())
