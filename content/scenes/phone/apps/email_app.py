"""
Email App Backend — Virtual email inbox powered by NexusFilesystem
==================================================================

Reads emails from /home/{character}/inbox/ in the virtual filesystem.
Emails are JSON files created by the compose_message skill or the
OracleCompanion agent. Users can list, read, star, and delete emails.

Version: v1.51.1 [2026-03-25]
Author:  CosySim Team

Change Log:
    v1.51.1 [2026-03-25] — Initial: list, read, star, delete, unread count

CONNECTS: engine.nexus.filesystem (NexusFilesystem)
CALLED BY: phone_scene_v2.py routes
"""
from __future__ import annotations

import json
import logging
import time
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


# ──── Data Model ─────────────────────────────────────────────────────────

@dataclass
class Email:
    """A single email message."""

    id: str
    sender: str
    recipient: str
    subject: str = ""
    body: str = ""
    timestamp: str = ""
    read: bool = False
    starred: bool = False
    deleted: bool = False
    metadata: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "sender": self.sender,
            "recipient": self.recipient,
            "subject": self.subject,
            "body": self.body,
            "timestamp": self.timestamp,
            "read": self.read,
            "starred": self.starred,
            "metadata": self.metadata,
        }


# ──── Email App ──────────────────────────────────────────────────────────

class EmailApp:
    """Email backend reading from NexusFilesystem inbox."""

    def __init__(self, owner: str = "player"):
        self.owner = owner
        self._read_ids: set = set()
        self._starred_ids: set = set()
        self._deleted_ids: set = set()

    def _fs(self):
        """Lazy-load filesystem."""
        from engine.nexus.filesystem import get_filesystem
        return get_filesystem(self.owner)

    def _inbox_path(self) -> str:
        return f"/home/{self.owner}/inbox/"

    def _parse_email(self, node) -> Optional[Email]:
        """Parse a filesystem node into an Email object."""
        try:
            content = node.content if hasattr(node, "content") else ""
            if not content:
                return None

            # Try JSON format first
            try:
                data = json.loads(content)
                return Email(
                    id=node.name if hasattr(node, "name") else node.path.split("/")[-1],
                    sender=data.get("From", data.get("from", data.get("author", "unknown"))),
                    recipient=data.get("To", data.get("to", self.owner)),
                    subject=data.get("Subject", data.get("subject", "")),
                    body=data.get("body", data.get("content", content)),
                    timestamp=data.get("Date", data.get("date", data.get("posted_at", ""))),
                    read=node.name in self._read_ids if hasattr(node, "name") else False,
                    starred=node.name in self._starred_ids if hasattr(node, "name") else False,
                    metadata=data.get("metadata", {}),
                )
            except json.JSONDecodeError:
                pass

            # Plain text format: parse From/To/Subject/Date headers
            lines = content.split("\n")
            headers: Dict[str, str] = {}
            body_start = 0
            for i, line in enumerate(lines):
                if line.startswith("---"):
                    body_start = i + 1
                    break
                if ": " in line:
                    key, val = line.split(": ", 1)
                    headers[key.strip()] = val.strip()
                else:
                    body_start = i
                    break

            email_id = node.name if hasattr(node, "name") else str(time.time())
            return Email(
                id=email_id,
                sender=headers.get("From", "unknown"),
                recipient=headers.get("To", self.owner),
                subject=headers.get("Subject", ""),
                body="\n".join(lines[body_start:]).strip(),
                timestamp=headers.get("Date", ""),
                read=email_id in self._read_ids,
                starred=email_id in self._starred_ids,
            )
        except Exception as exc:
            logger.debug("[EmailApp] Parse failed: %s", exc)
            return None

    def list_emails(self, include_deleted: bool = False) -> List[Dict[str, Any]]:
        """List all emails in the inbox."""
        try:
            fs = self._fs()
            inbox_path = self._inbox_path()

            # Ensure inbox exists
            if not fs.exists(inbox_path):
                fs.mkdir(inbox_path)
                return []

            nodes = fs.list_dir(inbox_path)
            emails = []
            for node in nodes:
                if node.fs_type == "directory":
                    continue
                if node.name in self._deleted_ids and not include_deleted:
                    continue

                # Read file content
                full_node = fs.read(node.path)
                if full_node:
                    email = self._parse_email(full_node)
                    if email:
                        emails.append(email.to_dict())

            # Sort by timestamp (newest first)
            emails.sort(key=lambda e: e.get("timestamp", ""), reverse=True)
            return emails

        except Exception as exc:
            logger.error("[EmailApp] List failed (operation=list_email): %s", exc)
            return []

    def get_email(self, email_id: str) -> Optional[Dict[str, Any]]:
        """Read a single email and mark as read."""
        try:
            fs = self._fs()
            inbox_path = self._inbox_path()
            nodes = fs.list_dir(inbox_path)

            for node in nodes:
                if node.name == email_id or node.path.endswith(email_id):
                    full_node = fs.read(node.path)
                    if full_node:
                        self._read_ids.add(email_id)
                        email = self._parse_email(full_node)
                        if email:
                            email.read = True
                            return email.to_dict()
            return None

        except Exception as exc:
            logger.error("[EmailApp] Get failed (operation=get_email): %s", exc)
            return None

    def star_email(self, email_id: str) -> bool:
        """Toggle star on an email."""
        if email_id in self._starred_ids:
            self._starred_ids.discard(email_id)
            return False
        else:
            self._starred_ids.add(email_id)
            return True

    def delete_email(self, email_id: str) -> bool:
        """Soft-delete an email."""
        self._deleted_ids.add(email_id)
        return True

    def unread_count(self) -> int:
        """Count unread emails."""
        try:
            emails = self.list_emails()
            return sum(1 for e in emails if not e.get("read", False))
        except Exception:
            return 0
