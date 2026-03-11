"""
ModelCatalog — External 3D model management for CosySim scenes.

Provides:
- YAML-based model catalog with metadata
- Directory scanning for GLB/GLTF/VRM models
- Model import pipeline (normalize, scale, center)
- Skeleton bone mapping for animation retargeting
- Thumbnail generation support
"""
from __future__ import annotations

import logging
import os
from typing import Any, Dict, List, Optional

import yaml

logger = logging.getLogger(__name__)

SUPPORTED_FORMATS = {".glb", ".gltf", ".vrm"}


class ModelCatalog:
    """YAML-backed catalog of external 3D models.

    Args:
        catalog_path: Path to the catalog YAML file.
    """

    def __init__(self, catalog_path: str) -> None:
        self.catalog_path = catalog_path
        self._data: Dict[str, Any] = {}
        self._load()

    def _load(self) -> None:
        """Load catalog from YAML."""
        if not os.path.exists(self.catalog_path):
            logger.info("No model catalog at %s — starting empty", self.catalog_path)
            self._data = {"catalog": {}, "source_directories": [], "import": {}}
            return
        try:
            with open(self.catalog_path, "r", encoding="utf-8") as f:
                self._data = yaml.safe_load(f) or {}
            cat = self._data.get("catalog", {})
            logger.info("Loaded model catalog with %d entries", len(cat))
        except Exception as exc:
            logger.error("Failed to load model catalog: %s", exc)
            self._data = {"catalog": {}, "source_directories": [], "import": {}}

    def _save(self) -> None:
        """Save catalog to YAML."""
        os.makedirs(os.path.dirname(self.catalog_path), exist_ok=True)
        try:
            with open(self.catalog_path, "w", encoding="utf-8") as f:
                yaml.dump(self._data, f, default_flow_style=False, sort_keys=False)
        except Exception as exc:
            logger.error("Failed to save model catalog: %s", exc)

    def reload(self) -> None:
        """Reload catalog from disk."""
        self._data.clear()
        self._load()

    # ── Query ──

    def get(self, model_id: str) -> Optional[Dict[str, Any]]:
        """Get a model entry by ID."""
        return self._data.get("catalog", {}).get(model_id)

    def get_all(self) -> Dict[str, Dict[str, Any]]:
        """Get all catalog entries."""
        return dict(self._data.get("catalog", {}))

    def count(self) -> int:
        """Total number of cataloged models."""
        return len(self._data.get("catalog", {}))

    def get_by_type(self, model_type: str) -> Dict[str, Dict[str, Any]]:
        """Get models filtered by type (character, prop, clothing, environment)."""
        return {
            mid: entry for mid, entry in self._data.get("catalog", {}).items()
            if entry.get("type") == model_type
        }

    def get_by_tag(self, tag: str) -> Dict[str, Dict[str, Any]]:
        """Get models that have a specific tag."""
        return {
            mid: entry for mid, entry in self._data.get("catalog", {}).items()
            if tag in entry.get("tags", [])
        }

    def search(self, query: str) -> Dict[str, Dict[str, Any]]:
        """Search models by ID, description, or tags."""
        q = query.lower()
        return {
            mid: entry for mid, entry in self._data.get("catalog", {}).items()
            if q in mid.lower()
            or q in entry.get("description", "").lower()
            or q in entry.get("file", "").lower()
            or any(q in tag for tag in entry.get("tags", []))
        }

    def get_full_path(self, model_id: str) -> Optional[str]:
        """Get the full file path for a model."""
        entry = self.get(model_id)
        if not entry:
            return None
        source_dir = entry.get("source_dir", "")
        filename = entry.get("file", "")
        if not source_dir or not filename:
            return None
        return os.path.join(source_dir, filename)

    # ── Scanning ──

    def scan_directory(self, directory: str, label: str = "Scanned") -> int:
        """Scan a directory for new model files and add them to catalog.

        Args:
            directory: Directory path to scan.
            label: Label for the source directory.

        Returns:
            Number of new models found and added.
        """
        if not os.path.isdir(directory):
            logger.warning("Directory not found: %s", directory)
            return 0

        catalog = self._data.setdefault("catalog", {})
        existing_files = {
            entry.get("file") for entry in catalog.values()
        }

        new_count = 0
        for filename in os.listdir(directory):
            ext = os.path.splitext(filename)[1].lower()
            if ext not in SUPPORTED_FORMATS:
                continue
            if filename in existing_files:
                continue

            model_id = os.path.splitext(filename)[0].lower()
            model_id = model_id.replace(" ", "_").replace("(", "").replace(")", "")
            model_id = model_id.rstrip("_")

            # Avoid ID collisions
            if model_id in catalog:
                model_id = f"{model_id}_2"

            filepath = os.path.join(directory, filename)
            size_mb = round(os.path.getsize(filepath) / (1024 * 1024), 1)

            catalog[model_id] = {
                "file": filename,
                "source_dir": directory.replace("\\", "/"),
                "size_mb": size_mb,
                "type": "unknown",
                "gender": "unknown",
                "description": f"Auto-scanned: {filename}",
                "tags": ["auto_scanned"],
                "has_skeleton": False,
                "has_animations": False,
                "poly_estimate": "unknown",
                "thumbnail": None,
            }
            new_count += 1
            logger.info("Added model: %s (%s, %.1fMB)", model_id, filename, size_mb)

        if new_count > 0:
            self._save()
        logger.info("Scan complete: %d new models from %s", new_count, directory)
        return new_count

    def scan_all_sources(self) -> int:
        """Scan all configured source directories for new models."""
        total = 0
        for source in self._data.get("source_directories", []):
            path = source.get("path", "")
            label = source.get("label", "Unknown")
            if path and source.get("auto_scan", True):
                total += self.scan_directory(path, label)
        return total

    # ── Mutation ──

    def add(
        self,
        model_id: str,
        file: str,
        source_dir: str,
        model_type: str = "unknown",
        gender: str = "unknown",
        description: str = "",
        tags: Optional[List[str]] = None,
        has_skeleton: bool = False,
        has_animations: bool = False,
    ) -> bool:
        """Add a model to the catalog.

        Args:
            model_id: Unique identifier for the model.
            file: Filename of the model file.
            source_dir: Directory containing the model.
            model_type: Model type (character, prop, clothing, environment).
            gender: Character gender if applicable.
            description: Human-readable description.
            tags: Tags for searching.
            has_skeleton: Whether the model has a skeleton.
            has_animations: Whether the model has embedded animations.

        Returns:
            True if added successfully.
        """
        catalog = self._data.setdefault("catalog", {})
        if model_id in catalog:
            logger.warning("Model '%s' already exists", model_id)
            return False

        filepath = os.path.join(source_dir, file)
        size_mb = 0.0
        if os.path.exists(filepath):
            size_mb = round(os.path.getsize(filepath) / (1024 * 1024), 1)

        catalog[model_id] = {
            "file": file,
            "source_dir": source_dir.replace("\\", "/"),
            "size_mb": size_mb,
            "type": model_type,
            "gender": gender,
            "description": description,
            "tags": tags or [],
            "has_skeleton": has_skeleton,
            "has_animations": has_animations,
            "poly_estimate": "unknown",
            "thumbnail": None,
        }
        self._save()
        return True

    def update(self, model_id: str, **kwargs: Any) -> bool:
        """Update a model entry's metadata."""
        catalog = self._data.get("catalog", {})
        if model_id not in catalog:
            return False
        catalog[model_id].update(kwargs)
        self._save()
        return True

    def remove(self, model_id: str) -> bool:
        """Remove a model from the catalog (does not delete the file)."""
        catalog = self._data.get("catalog", {})
        if model_id not in catalog:
            return False
        del catalog[model_id]
        self._save()
        return True

    # ── Bone Mapping ──

    def get_bone_mapping(self) -> Dict[str, str]:
        """Get the skeleton bone name mapping."""
        return dict(self._data.get("bone_mapping", {}))

    def map_bone_name(self, external_name: str) -> str:
        """Map an external bone name to internal name."""
        mapping = self._data.get("bone_mapping", {})
        return mapping.get(external_name, external_name)

    # ── Import Settings ──

    def get_import_settings(self) -> Dict[str, Any]:
        """Get model import configuration."""
        return dict(self._data.get("import", {}))

    # ── Stats ──

    def stats(self) -> Dict[str, Any]:
        """Return catalog statistics."""
        catalog = self._data.get("catalog", {})
        types: Dict[str, int] = {}
        total_size = 0.0
        for entry in catalog.values():
            t = entry.get("type", "unknown")
            types[t] = types.get(t, 0) + 1
            total_size += entry.get("size_mb", 0)

        return {
            "total": len(catalog),
            "types": types,
            "total_size_mb": round(total_size, 1),
            "source_directories": len(self._data.get("source_directories", [])),
        }
