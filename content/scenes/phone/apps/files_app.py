"""
Files App Backend — Virtual filesystem browser for NexusFilesystem
==================================================================

Thin wrapper around NexusFilesystem providing a browsable file explorer
for the Phone/Signal desktop app. Supports directory listing, file
reading, and tree views.

Version: v1.51.1 [2026-03-25]
Author:  CosySim Team

Change Log:
    v1.51.1 [2026-03-25] — Initial: list_directory, read_file, get_tree

CONNECTS: engine.nexus.filesystem (NexusFilesystem)
CALLED BY: phone_scene_v2.py routes
"""
from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


class FilesApp:
    """File browser backend wrapping NexusFilesystem."""

    def __init__(self, owner: str = "player"):
        self.owner = owner

    def _fs(self):
        """Lazy-load filesystem."""
        from engine.nexus.filesystem import get_filesystem
        return get_filesystem(self.owner)

    def list_directory(self, path: str = "/") -> Dict[str, Any]:
        """List contents of a directory.

        Returns:
            Dict with path, entries list, and parent path.
        """
        try:
            fs = self._fs()

            # Ensure path exists
            if not fs.exists(path):
                return {"path": path, "entries": [], "exists": False}

            nodes = fs.list_dir(path)
            entries = []
            for node in nodes:
                entries.append({
                    "name": node.name,
                    "path": node.path,
                    "type": node.fs_type,
                    "size": node.size,
                })

            # Calculate parent
            parts = path.rstrip("/").split("/")
            parent = "/".join(parts[:-1]) + "/" if len(parts) > 2 else "/"

            return {
                "path": path,
                "parent": parent,
                "entries": entries,
                "exists": True,
                "count": len(entries),
            }

        except Exception as exc:
            logger.error("[FilesApp] List failed (operation=list_dir, path=%s): %s", path, exc)
            return {"path": path, "entries": [], "exists": False, "error": str(exc)}

    def read_file(self, path: str) -> Dict[str, Any]:
        """Read a file's content.

        Returns:
            Dict with path, content, size, and metadata.
        """
        try:
            fs = self._fs()
            node = fs.read(path)

            if not node:
                return {"path": path, "content": None, "exists": False}

            return {
                "path": path,
                "name": node.name,
                "content": node.content,
                "size": node.size,
                "type": node.fs_type,
                "metadata": node.metadata,
                "exists": True,
            }

        except Exception as exc:
            logger.error("[FilesApp] Read failed (operation=read_file, path=%s): %s", path, exc)
            return {"path": path, "content": None, "exists": False, "error": str(exc)}

    def get_tree(self, path: str = "/", max_depth: int = 3) -> str:
        """Get an ASCII tree representation of the filesystem.

        Returns:
            Formatted tree string.
        """
        try:
            fs = self._fs()
            return fs.tree(path, max_depth=max_depth)
        except Exception as exc:
            logger.error("[FilesApp] Tree failed (operation=tree, path=%s): %s", path, exc)
            return f"Error: {exc}"

    def get_home_paths(self) -> List[str]:
        """Get common home directory paths for quick navigation."""
        return [
            f"/home/{self.owner}/",
            f"/home/{self.owner}/notes/",
            f"/home/{self.owner}/journal/",
            f"/home/{self.owner}/inbox/",
            f"/home/{self.owner}/reports/",
            f"/home/{self.owner}/playlists/",
            "/shared/",
            "/shared/messages/",
            "/shared/social/",
            "/system/",
        ]
