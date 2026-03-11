"""Mixin for GLB/VRM model upload, validation, and asset management.

Provides Flask routes for uploading 3D model files (GLB, VRM, GLTF),
managing a model library, and assigning uploaded models to scene characters.
Assets are stored in ``data/penthouse/models/`` with a JSON manifest.
"""
from __future__ import annotations

import json
import logging
import os
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

# Defaults — overridden by YAML config when available
_DEFAULT_MAX_FILE_SIZE_MB: int = 50
_DEFAULT_ALLOWED_FORMATS: List[str] = ["glb", "vrm", "gltf"]
_DEFAULT_MODELS_DIR: str = "data/penthouse/models"
_DEFAULT_SCALE: float = 1.0
_DEFAULT_HEIGHT: float = 1.7

_MAGIC_BYTES = {
    "glb": b"glTF",
}


def _project_root() -> Path:
    """Return the CosySim repository root."""
    return Path(__file__).resolve().parents[3]


class PenthouseModelMixin:
    """GLB / VRM / GLTF model upload and assignment routes."""

    # ── Internal helpers ───────────────────────────────────────────────

    def _model_config(self) -> Dict[str, Any]:
        """Load model_import config from characters.yaml, with safe defaults."""
        try:
            import yaml
            cfg_path = _project_root() / "config" / "penthouse" / "characters.yaml"
            if cfg_path.exists():
                with open(cfg_path, "r", encoding="utf-8") as fh:
                    data = yaml.safe_load(fh) or {}
                return data.get("model_import", {})
        except Exception as exc:
            logger.warning("Failed to load model_import config: %s", exc)
        return {}

    def _models_dir(self) -> Path:
        """Resolved path to the models asset directory (created on first call)."""
        cfg = self._model_config()
        rel = cfg.get("models_directory", _DEFAULT_MODELS_DIR)
        d = _project_root() / rel
        d.mkdir(parents=True, exist_ok=True)
        return d

    def _manifest_path(self) -> Path:
        return self._models_dir() / "models.json"

    def _load_manifest(self) -> Dict[str, Any]:
        mp = self._manifest_path()
        if mp.exists():
            try:
                with open(mp, "r", encoding="utf-8") as fh:
                    return json.load(fh)
            except Exception as exc:
                logger.error("Corrupt models.json — resetting: %s", exc)
        return {"models": {}, "assignments": {}}

    def _save_manifest(self, manifest: Dict[str, Any]) -> None:
        mp = self._manifest_path()
        mp.parent.mkdir(parents=True, exist_ok=True)
        with open(mp, "w", encoding="utf-8") as fh:
            json.dump(manifest, fh, indent=2, ensure_ascii=False)

    def _max_file_bytes(self) -> int:
        cfg = self._model_config()
        return int(cfg.get("max_file_size_mb", _DEFAULT_MAX_FILE_SIZE_MB)) * 1024 * 1024

    def _allowed_formats(self) -> List[str]:
        cfg = self._model_config()
        return [f.lower() for f in cfg.get("allowed_formats", _DEFAULT_ALLOWED_FORMATS)]

    @staticmethod
    def _detect_format(filename: str, header: bytes) -> Optional[str]:
        """Detect file format from extension and magic bytes."""
        ext = filename.rsplit(".", 1)[-1].lower() if "." in filename else ""
        if ext == "glb" and header[:4] == _MAGIC_BYTES.get("glb", b""):
            return "glb"
        if ext == "vrm":
            if header[:4] == _MAGIC_BYTES.get("glb", b""):
                return "vrm"
        if ext == "gltf":
            return "gltf"
        return None

    # ── Route registration ─────────────────────────────────────────────

    def _setup_model_routes(self) -> None:
        """Register model management Flask routes on ``self.app``."""
        from flask import jsonify, request, send_from_directory

        @self.app.route("/api/models/upload", methods=["POST"])
        def upload_model():
            """Upload a GLB/VRM/GLTF file.

            Expects multipart/form-data with a ``file`` field.
            Returns model metadata on success.
            """
            if "file" not in request.files:
                return jsonify({"error": "No file provided"}), 400

            f = request.files["file"]
            if not f.filename:
                return jsonify({"error": "Empty filename"}), 400

            # Size guard (read into memory for small-ish 3D assets)
            data = f.read()
            max_bytes = self._max_file_bytes()
            if len(data) > max_bytes:
                return jsonify({
                    "error": f"File too large ({len(data) / 1048576:.1f} MB). "
                             f"Max is {max_bytes / 1048576:.0f} MB.",
                }), 413

            # Format validation
            fmt = self._detect_format(f.filename, data[:8])
            allowed = self._allowed_formats()
            if fmt not in allowed:
                return jsonify({
                    "error": f"Unsupported format. Allowed: {', '.join(allowed)}",
                }), 415

            # Persist file
            model_id = uuid.uuid4().hex[:12]
            safe_name = f"{model_id}_{f.filename.replace(os.sep, '_')}"
            dest = self._models_dir() / safe_name
            dest.write_bytes(data)

            # Build metadata
            meta = {
                "id": model_id,
                "filename": f.filename,
                "stored_as": safe_name,
                "format": fmt,
                "size_bytes": len(data),
                "size_mb": round(len(data) / 1048576, 2),
                "uploaded_at": datetime.now(timezone.utc).isoformat(),
                "scale": self._model_config().get("default_scale", _DEFAULT_SCALE),
                "height": self._model_config().get("default_height", _DEFAULT_HEIGHT),
            }

            manifest = self._load_manifest()
            manifest["models"][model_id] = meta
            self._save_manifest(manifest)

            logger.info("Model uploaded: %s (%s, %.2f MB)", f.filename, fmt, meta["size_mb"])
            return jsonify({"success": True, "model": meta}), 201

        @self.app.route("/api/models/library")
        def model_library():
            """Return all uploaded models and their assignments."""
            manifest = self._load_manifest()
            models = list(manifest.get("models", {}).values())
            assignments = manifest.get("assignments", {})
            return jsonify({"models": models, "assignments": assignments})

        @self.app.route("/api/models/<model_id>/info")
        def model_info(model_id: str):
            """Return metadata for a single model."""
            manifest = self._load_manifest()
            meta = manifest.get("models", {}).get(model_id)
            if not meta:
                return jsonify({"error": "Model not found"}), 404
            # Include which characters use this model
            assigned_to = [
                cid for cid, mid in manifest.get("assignments", {}).items()
                if mid == model_id
            ]
            return jsonify({"model": meta, "assigned_to": assigned_to})

        @self.app.route("/api/models/<model_id>", methods=["DELETE"])
        def delete_model(model_id: str):
            """Remove a model from the library and disk."""
            manifest = self._load_manifest()
            meta = manifest.get("models", {}).pop(model_id, None)
            if not meta:
                return jsonify({"error": "Model not found"}), 404

            # Remove file
            stored = self._models_dir() / meta["stored_as"]
            if stored.exists():
                stored.unlink()

            # Remove any assignments pointing to this model
            assignments = manifest.get("assignments", {})
            to_remove = [cid for cid, mid in assignments.items() if mid == model_id]
            for cid in to_remove:
                del assignments[cid]

            self._save_manifest(manifest)
            logger.info("Model deleted: %s (%s)", meta["filename"], model_id)
            return jsonify({"success": True, "deleted": model_id})

        @self.app.route("/api/models/assign", methods=["POST"])
        def assign_model():
            """Assign an uploaded model to a character.

            JSON body: ``{"character_id": "lola", "model_id": "abc123"}``
            Pass ``model_id: null`` to unassign.
            """
            data = request.json or {}
            cid = data.get("character_id")
            mid = data.get("model_id")

            if not cid:
                return jsonify({"error": "character_id required"}), 400

            manifest = self._load_manifest()

            if mid is None:
                # Unassign
                manifest.setdefault("assignments", {}).pop(cid, None)
                self._save_manifest(manifest)
                logger.info("Model unassigned from character: %s", cid)
                if hasattr(self, "socketio"):
                    self.socketio.emit("model_assigned", {
                        "character_id": cid, "model_id": None,
                    })
                return jsonify({"success": True, "character_id": cid, "model_id": None})

            if mid not in manifest.get("models", {}):
                return jsonify({"error": "Model not found"}), 404

            manifest.setdefault("assignments", {})[cid] = mid
            self._save_manifest(manifest)

            model_meta = manifest["models"][mid]
            logger.info("Model %s assigned to character %s", mid, cid)

            if hasattr(self, "socketio"):
                self.socketio.emit("model_assigned", {
                    "character_id": cid,
                    "model_id": mid,
                    "filename": model_meta.get("filename"),
                    "format": model_meta.get("format"),
                })

            return jsonify({
                "success": True,
                "character_id": cid,
                "model_id": mid,
                "model": model_meta,
            })

        @self.app.route("/api/models/file/<path:filename>")
        def serve_model_file(filename: str):
            """Serve a model file for Three.js GLTFLoader consumption."""
            models_dir = self._models_dir()
            file_path = models_dir / filename
            if not file_path.exists():
                return jsonify({"error": "File not found"}), 404
            return send_from_directory(
                str(models_dir), filename,
                mimetype="application/octet-stream",
            )
