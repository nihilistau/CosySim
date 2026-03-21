"""Asset Registry — discovers and indexes game assets across the project.

Scans ``content/assets/``, ``content/simulation/media/``, and scene-local
``static/`` directories to build a searchable catalogue of models, textures,
audio, and templates.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import List, Optional

logger = logging.getLogger(__name__)

PROJECT_ROOT = Path(__file__).resolve().parents[2]

# Asset type classification by extension
_TYPE_MAP = {
    ".png": "image", ".jpg": "image", ".jpeg": "image", ".webp": "image",
    ".gif": "image", ".svg": "image",
    ".mp3": "audio", ".wav": "audio", ".ogg": "audio", ".flac": "audio",
    ".mp4": "video", ".webm": "video",
    ".json": "data", ".yaml": "data", ".yml": "data",
    ".html": "template", ".jinja2": "template",
    ".js": "script", ".css": "style",
    ".glb": "model", ".gltf": "model", ".obj": "model",
    ".ttf": "font", ".woff": "font", ".woff2": "font",
}


@dataclass
class AssetEntry:
    """A single discovered asset."""

    asset_id: str
    name: str
    path: Path
    asset_type: str
    source_dir: str
    size_bytes: int = 0
    tags: List[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "asset_id": self.asset_id,
            "name": self.name,
            "path": str(self.path),
            "type": self.asset_type,
            "source": self.source_dir,
            "size": self.size_bytes,
            "tags": self.tags,
        }


class AssetRegistry:
    """Discovers and indexes assets from content directories."""

    SCAN_DIRS = [
        "content/assets",
        "content/simulation/media",
    ]

    def __init__(self) -> None:
        self._entries: List[AssetEntry] = []
        self._index: dict[str, AssetEntry] = {}

    def scan(self) -> List[AssetEntry]:
        """Scan all asset directories and return discovered entries."""
        self._entries.clear()
        self._index.clear()

        for scan_dir in self.SCAN_DIRS:
            root = PROJECT_ROOT / scan_dir
            if not root.is_dir():
                logger.debug("Asset scan dir not found: %s", root)
                continue
            self._scan_directory(root, scan_dir)

        # Also scan scene static dirs
        scenes_root = PROJECT_ROOT / "content" / "scenes"
        if scenes_root.is_dir():
            for scene_dir in sorted(scenes_root.iterdir()):
                static = scene_dir / "static"
                if static.is_dir():
                    self._scan_directory(static, f"scenes/{scene_dir.name}/static")

        logger.info("Asset scan complete: %d entries", len(self._entries))
        return list(self._entries)

    def _scan_directory(self, root: Path, source_label: str) -> None:
        """Recursively scan *root* for asset files."""
        for path in root.rglob("*"):
            if not path.is_file():
                continue
            ext = path.suffix.lower()
            asset_type = _TYPE_MAP.get(ext)
            if not asset_type:
                continue

            rel = path.relative_to(PROJECT_ROOT)
            asset_id = str(rel).replace("\\", "/")
            entry = AssetEntry(
                asset_id=asset_id,
                name=path.stem,
                path=rel,
                asset_type=asset_type,
                source_dir=source_label,
                size_bytes=path.stat().st_size,
            )
            self._entries.append(entry)
            self._index[asset_id] = entry

    def get(self, asset_id: str) -> Optional[AssetEntry]:
        """Retrieve a single asset by ID."""
        return self._index.get(asset_id)

    def search(
        self,
        query: str,
        asset_type: Optional[str] = None,
    ) -> List[AssetEntry]:
        """Search assets by name substring and optional type filter."""
        query_lower = query.lower()
        results = []
        for entry in self._entries:
            if asset_type and entry.asset_type != asset_type:
                continue
            if query_lower in entry.name.lower() or query_lower in entry.asset_id.lower():
                results.append(entry)
        return results

    def by_type(self, asset_type: str) -> List[AssetEntry]:
        """Return all assets of a given type."""
        return [e for e in self._entries if e.asset_type == asset_type]

    def summary(self) -> dict:
        """Return a summary of discovered assets by type."""
        counts: dict[str, int] = {}
        for entry in self._entries:
            counts[entry.asset_type] = counts.get(entry.asset_type, 0) + 1
        return {"total": len(self._entries), "by_type": counts}
