"""
Filesystem Skills — Virtual Filesystem over Nexus KMS
=====================================================

Agent-callable skills for reading, writing, listing, and managing files
in the NexusFilesystem virtual filesystem.  Every operation is backed by
Nexus knowledge entries, giving agents persistent, searchable file storage.

Version: v1.51.0 [2026-03-25]
Author:  CosySim Team

Change Log:
    v1.51.0 [2026-03-25] — Initial implementation: read_file, write_file,
                            list_files, make_directory, delete_file, show_tree

CONNECTS: engine.nexus.filesystem.NexusFilesystem
CALLED BY: MCP skill pipeline, agent auto_skill invocations
"""
from __future__ import annotations

import json

from engine.skills.skill import skill, SkillCategory


# ──── Helpers ────────────────────────────────────────────────────────────

def _fs(owner: str = "player"):
    """Lazy-load the NexusFilesystem singleton.

    Args:
        owner: Filesystem owner (default "player").

    Returns:
        NexusFilesystem instance.
    """
    from engine.nexus.filesystem import get_filesystem
    return get_filesystem(owner)


# ──── Read ───────────────────────────────────────────────────────────────

# v1.51.0 [2026-03-25] — Read file content from virtual filesystem
@skill(
    pack="filesystem",
    description="Read a file from the virtual filesystem",
    category=SkillCategory.SYSTEM,
    tags=["filesystem", "read", "file"],
    cooldown=1.0,
    cost=0.5,
)
def read_file(path: str) -> str:
    """Read the content of a file at the given path.

    Args:
        path: Absolute path in the virtual filesystem (e.g. "/notes/todo.txt").

    Returns:
        JSON with file content and metadata, or error message.
    """
    node = _fs().read(path)
    if node is None:
        return json.dumps({"ok": False, "error": f"File not found: {path}"})
    if node.fs_type == "directory":
        return json.dumps({"ok": False, "error": f"Path is a directory: {path}"})
    return json.dumps({
        "ok": True,
        "path": node.path,
        "content": node.content,
        "size": node.size,
        "metadata": node.metadata,
    })


# ──── Write ──────────────────────────────────────────────────────────────

# v1.51.0 [2026-03-25] — Write content to a virtual file
@skill(
    pack="filesystem",
    description="Write content to a file in the virtual filesystem",
    category=SkillCategory.SYSTEM,
    tags=["filesystem", "write", "file"],
    cooldown=2.0,
    cost=1.0,
)
def write_file(path: str, content: str) -> str:
    """Write content to a file, creating it if it doesn't exist.

    Parent directories are created automatically.

    Args:
        path:    Absolute path in the virtual filesystem.
        content: Text content to write.

    Returns:
        JSON with write result and entry ID.
    """
    node = _fs().write(path, content)
    if node is None:
        return json.dumps({"ok": False, "error": f"Failed to write: {path}"})
    return json.dumps({
        "ok": True,
        "path": node.path,
        "size": node.size,
        "entry_id": node.entry_id,
    })


# ──── List ───────────────────────────────────────────────────────────────

# v1.51.0 [2026-03-25] — List directory contents
@skill(
    pack="filesystem",
    description="List files and directories at a path in the virtual filesystem",
    category=SkillCategory.SYSTEM,
    tags=["filesystem", "list", "directory"],
    cooldown=1.0,
    cost=0.5,
)
def list_files(path: str = "/") -> str:
    """List the immediate children of a directory.

    Args:
        path: Directory path to list (default "/").

    Returns:
        JSON array of child entries with name, type, and size.
    """
    children = _fs().list_dir(path)
    items = [
        {
            "name": child.name,
            "path": child.path,
            "type": child.fs_type,
            "size": child.size,
        }
        for child in children
    ]
    return json.dumps({"ok": True, "path": path, "count": len(items), "items": items})


# ──── Mkdir ──────────────────────────────────────────────────────────────

# v1.51.0 [2026-03-25] — Create a directory (with parents)
@skill(
    pack="filesystem",
    description="Create a directory in the virtual filesystem (parents auto-created)",
    category=SkillCategory.SYSTEM,
    tags=["filesystem", "mkdir", "directory"],
    cooldown=2.0,
    cost=0.5,
)
def make_directory(path: str) -> str:
    """Create a directory, including any missing parent directories.

    Args:
        path: Absolute path for the new directory.

    Returns:
        JSON with creation result.
    """
    node = _fs().mkdir(path)
    if node is None:
        return json.dumps({"ok": False, "error": f"Failed to create directory: {path}"})
    return json.dumps({
        "ok": True,
        "path": node.path,
        "entry_id": node.entry_id,
    })


# ──── Delete ─────────────────────────────────────────────────────────────

# v1.51.0 [2026-03-25] — Delete a file or empty directory
@skill(
    pack="filesystem",
    description="Delete a file or empty directory from the virtual filesystem",
    category=SkillCategory.SYSTEM,
    tags=["filesystem", "delete", "file"],
    cooldown=2.0,
    cost=1.0,
)
def delete_file(path: str) -> str:
    """Delete a file or empty directory.

    Non-empty directories cannot be deleted (remove children first).

    Args:
        path: Absolute path to delete.

    Returns:
        JSON with deletion result.
    """
    success = _fs().delete(path)
    if not success:
        return json.dumps({"ok": False, "error": f"Failed to delete: {path}"})
    return json.dumps({"ok": True, "path": path, "deleted": True})


# ──── Tree ───────────────────────────────────────────────────────────────

# v1.51.0 [2026-03-25] — ASCII directory tree view
@skill(
    pack="filesystem",
    description="Show a tree view of the virtual filesystem",
    category=SkillCategory.SYSTEM,
    tags=["filesystem", "tree", "directory"],
    cooldown=1.0,
    cost=0.5,
)
def show_tree(path: str = "/", depth: int = 3) -> str:
    """Generate an ASCII tree representation of the directory structure.

    Args:
        path:  Root path to start the tree from (default "/").
        depth: Maximum recursion depth (default 3).

    Returns:
        Multi-line ASCII tree string.
    """
    tree_str = _fs().tree(path, depth)
    return json.dumps({"ok": True, "path": path, "depth": depth, "tree": tree_str})
