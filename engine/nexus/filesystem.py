"""
NexusFilesystem — Path-based Virtual Filesystem Backed by Nexus KMS
====================================================================

Provides a POSIX-like filesystem abstraction on top of Nexus knowledge
entries.  Every file and directory is a Nexus entry with ``content_type``
set to ``"filesystem"`` and ``category`` of ``"fs_file"`` or
``"fs_directory"``.  Paths are stored as entry titles for uniqueness;
tags encode ownership and parent relationships for efficient listing.

Usage::

    from engine.nexus.filesystem import get_filesystem
    fs = get_filesystem("player")
    fs.mkdir("/home/player/notes")
    fs.write("/home/player/notes/shopping.txt", "Milk, eggs, bread")
    print(fs.read("/home/player/notes/shopping.txt").content)
    print(fs.tree("/home/player"))

Version: v1.51.0 [2026-03-25]
Author:  CosySim Team

Change Log:
    v1.51.0 [2026-03-25] — Initial implementation: read, write, mkdir,
                            list_dir, delete, exists, tree, get_filesystem
"""
from __future__ import annotations

import logging
import posixpath
import threading
import time
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


# ──── Data Model ─────────────────────────────────────────────────────────

# v1.51.0 [2026-03-25] — Filesystem node dataclass
@dataclass
class FSNode:
    """A virtual filesystem node (file or directory).

    Attributes:
        path:     Absolute POSIX path (e.g. "/home/player/notes/todo.txt").
        name:     Leaf name (e.g. "todo.txt").
        fs_type:  Either "file" or "directory".
        content:  File content string (empty for directories).
        size:     Content length in characters.
        entry_id: Nexus entry ID backing this node.
        children: List of child paths (directories only).
        metadata: Arbitrary metadata dict stored alongside the node.
    """

    path: str
    name: str
    fs_type: str  # "file" | "directory"
    content: str = ""
    size: int = 0
    entry_id: str = ""
    children: List[str] = field(default_factory=list)
    metadata: Dict[str, Any] = field(default_factory=dict)


# ──── Constants ──────────────────────────────────────────────────────────

_CONTENT_TYPE = "filesystem"
_CAT_FILE = "fs_file"
_CAT_DIR = "fs_directory"
_CREATED_BY = "filesystem"


# ──── NexusFilesystem Class ──────────────────────────────────────────────

class NexusFilesystem:
    """Path-based virtual filesystem backed by Nexus KMS.

    Each file/directory is a Nexus entry with:
      - ``content_type = "filesystem"``
      - ``title = full_path`` (e.g. "/home/player/notes/shopping.txt")
      - ``category = "fs_file"`` or ``"fs_directory"``
      - ``tags = ["fs", "owner:{owner}", "parent:{parent_path}"]``

    CONNECTS: NexusClient (engine.nexus.client)
    CALLED BY: fs_skills.py, agent filesystem commands
    """

    def __init__(self, owner: str = "player") -> None:
        self._owner = owner
        self._client = None  # lazy NexusClient

    # ── Client Access ──────────────────────────────────────────────

    def _get_client(self):
        """Lazy-load NexusClient to avoid import-time side effects.

        Returns:
            NexusClient singleton instance.
        """
        if self._client is None:
            from engine.nexus.client import get_nexus_client
            self._client = get_nexus_client()
        return self._client

    # ── Tag Helpers ────────────────────────────────────────────────

    def _make_tags(self, path: str) -> List[str]:
        """Build the tag list for a filesystem entry.

        Args:
            path: Absolute POSIX path.

        Returns:
            Tags including "fs", owner tag, and parent path tag.
        """
        parent = posixpath.dirname(path) or "/"
        return ["fs", f"owner:{self._owner}", f"parent:{parent}"]

    # ── Read ───────────────────────────────────────────────────────

    # v1.51.0 [2026-03-25] — Read file or directory metadata by path
    # CONNECTS: NexusClient.list_by_type
    def read(self, path: str) -> Optional[FSNode]:
        """Read a file or directory from the virtual filesystem.

        Args:
            path: Absolute POSIX path to read.

        Returns:
            FSNode if found, None otherwise.
        """
        path = posixpath.normpath(path)
        client = self._get_client()

        try:
            entries = client.list_by_type(_CONTENT_TYPE, limit=200)
        except Exception as exc:
            logger.error(
                "[NexusFilesystem] Read failed (operation=read, path=%s): %s",
                path, exc,
            )
            return None

        for entry in entries:
            title = entry.get("title", "")
            if title == path:
                return self._entry_to_node(entry)

        return None

    # ── Write ──────────────────────────────────────────────────────

    # v1.51.0 [2026-03-25] — Write (create or update) a file
    # CONNECTS: NexusClient.add_entry, NexusClient.update_entry
    def write(self, path: str, content: str, metadata: Optional[Dict] = None) -> Optional[FSNode]:
        """Write content to a file, creating it if it does not exist.

        Automatically creates parent directories.

        Args:
            path:     Absolute POSIX path.
            content:  File content string.
            metadata: Optional metadata dict to store alongside the file.

        Returns:
            FSNode for the written file, or None on failure.
        """
        path = posixpath.normpath(path)
        client = self._get_client()

        # Ensure parent directories exist
        parent = posixpath.dirname(path)
        if parent and parent != "/":
            self.mkdir(parent)

        tags = self._make_tags(path)
        if metadata:
            # Encode metadata keys as extra tags for search
            for k, v in metadata.items():
                tags.append(f"meta:{k}={v}")

        # Check if file already exists — update instead of creating duplicate
        existing = self.read(path)
        if existing and existing.entry_id:
            try:
                success = client.update_entry(
                    existing.entry_id,
                    content=content,
                    tags=tags,
                )
                if success:
                    logger.info(
                        "[NexusFilesystem] File updated (operation=write, path=%s)",
                        path,
                    )
                    return FSNode(
                        path=path,
                        name=posixpath.basename(path),
                        fs_type="file",
                        content=content,
                        size=len(content),
                        entry_id=existing.entry_id,
                        metadata=metadata or {},
                    )
            except Exception as exc:
                logger.error(
                    "[NexusFilesystem] Update failed (operation=write, path=%s): %s",
                    path, exc,
                )
                return None

        # Create new entry
        try:
            entry_id = client.add_entry(
                title=path,
                content=content,
                content_type=_CONTENT_TYPE,
                category=_CAT_FILE,
                tags=tags,
                created_by=_CREATED_BY,
            )
            if entry_id:
                logger.info(
                    "[NexusFilesystem] File created (operation=write, path=%s, id=%s)",
                    path, entry_id,
                )
                return FSNode(
                    path=path,
                    name=posixpath.basename(path),
                    fs_type="file",
                    content=content,
                    size=len(content),
                    entry_id=entry_id,
                    metadata=metadata or {},
                )
        except Exception as exc:
            logger.error(
                "[NexusFilesystem] Create failed (operation=write, path=%s): %s",
                path, exc,
            )
        return None

    # ── Mkdir ──────────────────────────────────────────────────────

    # v1.51.0 [2026-03-25] — Create directory (and parents recursively)
    # CONNECTS: NexusClient.add_entry
    def mkdir(self, path: str) -> Optional[FSNode]:
        """Create a directory, including any missing parent directories.

        Args:
            path: Absolute POSIX path for the directory.

        Returns:
            FSNode for the directory, or None on failure.
        """
        path = posixpath.normpath(path)
        if path == "/":
            return FSNode(path="/", name="/", fs_type="directory")

        # Check if already exists
        existing = self.read(path)
        if existing:
            return existing

        # Recursively create parents
        parent = posixpath.dirname(path)
        if parent and parent != "/" and parent != path:
            self.mkdir(parent)

        client = self._get_client()
        tags = self._make_tags(path)

        try:
            entry_id = client.add_entry(
                title=path,
                content="",
                content_type=_CONTENT_TYPE,
                category=_CAT_DIR,
                tags=tags,
                created_by=_CREATED_BY,
            )
            if entry_id:
                logger.info(
                    "[NexusFilesystem] Directory created (operation=mkdir, path=%s)",
                    path,
                )
                return FSNode(
                    path=path,
                    name=posixpath.basename(path),
                    fs_type="directory",
                    entry_id=entry_id,
                )
        except Exception as exc:
            logger.error(
                "[NexusFilesystem] mkdir failed (operation=mkdir, path=%s): %s",
                path, exc,
            )
        return None

    # ── List Directory ─────────────────────────────────────────────

    # v1.51.0 [2026-03-25] — List immediate children of a directory
    # CONNECTS: NexusClient.list_by_type
    def list_dir(self, path: str) -> List[FSNode]:
        """List the immediate children of a directory.

        Uses tag filtering on ``parent:{path}`` to find entries whose
        parent is the given path.

        Args:
            path: Absolute POSIX path of the directory to list.

        Returns:
            List of FSNode children.  Empty list if path is not a
            directory or has no children.
        """
        path = posixpath.normpath(path)
        client = self._get_client()

        try:
            all_entries = client.list_by_type(_CONTENT_TYPE, limit=500)
        except Exception as exc:
            logger.error(
                "[NexusFilesystem] list_dir failed (operation=list_dir, path=%s): %s",
                path, exc,
            )
            return []

        parent_tag = f"parent:{path}"
        owner_tag = f"owner:{self._owner}"

        children: List[FSNode] = []
        for entry in all_entries:
            tags = entry.get("tags", [])
            if isinstance(tags, str):
                tags = [tags]
            if parent_tag in tags and owner_tag in tags:
                children.append(self._entry_to_node(entry))

        # Sort: directories first, then alphabetically by name
        children.sort(key=lambda n: (0 if n.fs_type == "directory" else 1, n.name.lower()))
        return children

    # ── Delete ─────────────────────────────────────────────────────

    # v1.51.0 [2026-03-25] — Delete a file or empty directory
    # CONNECTS: NexusClient.delete_entry
    def delete(self, path: str) -> bool:
        """Delete a file or empty directory.

        Refuses to delete non-empty directories (delete children first).

        Args:
            path: Absolute POSIX path to delete.

        Returns:
            True if deleted, False otherwise.
        """
        path = posixpath.normpath(path)
        node = self.read(path)
        if not node:
            logger.warning(
                "[NexusFilesystem] Delete target not found (operation=delete, path=%s)",
                path,
            )
            return False

        # Refuse to delete non-empty directories
        if node.fs_type == "directory":
            children = self.list_dir(path)
            if children:
                logger.warning(
                    "[NexusFilesystem] Cannot delete non-empty directory "
                    "(operation=delete, path=%s, children=%d)",
                    path, len(children),
                )
                return False

        client = self._get_client()
        try:
            success = client.delete_entry(node.entry_id)
            if success:
                logger.info(
                    "[NexusFilesystem] Deleted (operation=delete, path=%s)",
                    path,
                )
            return success
        except Exception as exc:
            logger.error(
                "[NexusFilesystem] Delete failed (operation=delete, path=%s): %s",
                path, exc,
            )
            return False

    # ── Exists ─────────────────────────────────────────────────────

    def exists(self, path: str) -> bool:
        """Check if a file or directory exists.

        Args:
            path: Absolute POSIX path.

        Returns:
            True if the path exists in the virtual filesystem.
        """
        return self.read(posixpath.normpath(path)) is not None

    # ── Tree ───────────────────────────────────────────────────────

    # v1.51.0 [2026-03-25] — Recursive ASCII tree view
    def tree(self, path: str = "/", depth: int = 3) -> str:
        """Generate an ASCII tree representation of the directory structure.

        Args:
            path:  Root path to start the tree from.
            depth: Maximum recursion depth (default 3).

        Returns:
            Multi-line ASCII tree string.
        """
        path = posixpath.normpath(path)
        lines: List[str] = [path]
        self._tree_recurse(path, "", depth, lines)
        return "\n".join(lines)

    def _tree_recurse(
        self, path: str, prefix: str, depth: int, lines: List[str]
    ) -> None:
        """Recursive helper for tree().

        Args:
            path:   Current directory path.
            prefix: Indentation prefix for child lines.
            depth:  Remaining recursion depth.
            lines:  Accumulated output lines (mutated in place).
        """
        if depth <= 0:
            return

        children = self.list_dir(path)
        for i, child in enumerate(children):
            is_last = (i == len(children) - 1)
            connector = "\u2514\u2500\u2500 " if is_last else "\u251C\u2500\u2500 "
            suffix = "/" if child.fs_type == "directory" else ""
            lines.append(f"{prefix}{connector}{child.name}{suffix}")

            if child.fs_type == "directory":
                next_prefix = prefix + ("    " if is_last else "\u2502   ")
                self._tree_recurse(child.path, next_prefix, depth - 1, lines)

    # ── Internal Helpers ───────────────────────────────────────────

    def _entry_to_node(self, entry: Any) -> FSNode:
        """Convert a Nexus entry dict/model to an FSNode.

        Args:
            entry: NexusEntry (dict-compatible) from NexusClient.

        Returns:
            FSNode populated from the entry fields.
        """
        title = entry.get("title", "")
        content = entry.get("content", "")
        category = entry.get("category", "")
        fs_type = "directory" if category == _CAT_DIR else "file"
        entry_id = entry.get("id", "")

        # Extract metadata from tags
        tags = entry.get("tags", [])
        if isinstance(tags, str):
            tags = [tags]
        metadata: Dict[str, Any] = {}
        for tag in tags:
            if tag.startswith("meta:") and "=" in tag:
                key, _, val = tag[5:].partition("=")
                metadata[key] = val

        return FSNode(
            path=title,
            name=posixpath.basename(title) or title,
            fs_type=fs_type,
            content=content,
            size=len(content),
            entry_id=entry_id,
            metadata=metadata,
        )


# ──── Singleton Factory ──────────────────────────────────────────────────

_instances: Dict[str, NexusFilesystem] = {}
_lock = threading.Lock()


# v1.51.0 [2026-03-25] — Thread-safe singleton per owner
def get_filesystem(owner: str = "player") -> NexusFilesystem:
    """Get or create a NexusFilesystem instance for the given owner.

    Args:
        owner: Filesystem owner identifier (default "player").

    Returns:
        NexusFilesystem singleton for this owner.

    CALLED BY: fs_skills.py, agent filesystem commands
    """
    if owner not in _instances:
        with _lock:
            if owner not in _instances:
                _instances[owner] = NexusFilesystem(owner=owner)
    return _instances[owner]
