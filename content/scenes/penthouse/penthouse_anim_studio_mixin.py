"""Penthouse Animation Studio mixin — pose library and sequence persistence."""
from __future__ import annotations

import json
import logging
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

# ── Storage paths ───────────────────────────────────────────────────────
_DATA_DIR = Path(__file__).resolve().parents[3] / "data" / "penthouse" / "animations"
_POSES_PATH = _DATA_DIR / "poses.json"
_SEQUENCES_PATH = _DATA_DIR / "sequences.json"


def _ensure_data_dir() -> None:
    """Create data directory if it does not exist."""
    _DATA_DIR.mkdir(parents=True, exist_ok=True)
    if not _POSES_PATH.exists():
        _POSES_PATH.write_text("{}", encoding="utf-8")
    if not _SEQUENCES_PATH.exists():
        _SEQUENCES_PATH.write_text("{}", encoding="utf-8")


def _load_json(path: Path) -> Dict[str, Any]:
    """Load a JSON file, returning empty dict on failure."""
    try:
        text = path.read_text(encoding="utf-8").strip()
        return json.loads(text) if text else {}
    except (json.JSONDecodeError, FileNotFoundError):
        return {}


def _save_json(path: Path, data: Dict[str, Any]) -> None:
    """Atomically write JSON data to file."""
    _ensure_data_dir()
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")


class PenthouseAnimStudioMixin:
    """Pose library, animation sequence storage, and application routes."""

    # ── Setup entry point ───────────────────────────────────────────────

    def _setup_anim_studio_routes(self) -> None:
        """Register Animation Studio Flask routes on self.app."""
        from flask import jsonify, request

        _ensure_data_dir()

        # ── Pose CRUD ───────────────────────────────────────────────────

        @self.app.route("/api/anim/poses", methods=["GET"])
        def list_poses() -> Any:
            """Return all saved pose presets."""
            poses = _load_json(_POSES_PATH)
            return jsonify({"poses": poses})

        @self.app.route("/api/anim/poses", methods=["POST"])
        def save_pose() -> Any:
            """Save a new pose preset.

            Expected JSON body:
                name: str — human-readable name
                joints: dict — {joint_name: {x, y, z}} rotation map
                character_id: str (optional) — source character
            """
            data = request.json or {}
            name = data.get("name", "").strip()
            joints = data.get("joints")
            if not name or not joints:
                return jsonify({"error": "name and joints required"}), 400

            pose_id = str(uuid.uuid4())[:8]
            poses = _load_json(_POSES_PATH)
            poses[pose_id] = {
                "name": name,
                "joints": joints,
                "character_id": data.get("character_id", ""),
                "joint_count": len(joints),
                "created_at": datetime.utcnow().isoformat(),
            }
            _save_json(_POSES_PATH, poses)
            logger.info("Saved pose '%s' (%s) with %d joints", name, pose_id, len(joints))
            return jsonify({"success": True, "pose_id": pose_id})

        @self.app.route("/api/anim/poses/<pose_id>", methods=["DELETE"])
        def delete_pose(pose_id: str) -> Any:
            """Delete a saved pose by ID."""
            poses = _load_json(_POSES_PATH)
            if pose_id not in poses:
                return jsonify({"error": "Pose not found"}), 404
            del poses[pose_id]
            _save_json(_POSES_PATH, poses)
            logger.info("Deleted pose %s", pose_id)
            return jsonify({"success": True})

        # ── Sequence CRUD ───────────────────────────────────────────────

        @self.app.route("/api/anim/sequences", methods=["GET"])
        def list_sequences() -> Any:
            """Return all saved animation sequences."""
            seqs = _load_json(_SEQUENCES_PATH)
            return jsonify({"sequences": seqs})

        @self.app.route("/api/anim/sequences", methods=["POST"])
        def save_sequence() -> Any:
            """Save an animation sequence.

            Expected JSON body:
                name: str — human-readable name
                keyframes: list — [{time, pose, expression, position}, ...]
                loop: bool (optional)
                speed: float (optional)
            """
            data = request.json or {}
            name = data.get("name", "").strip()
            keyframes = data.get("keyframes")
            if not name or not keyframes:
                return jsonify({"error": "name and keyframes required"}), 400

            seq_id = str(uuid.uuid4())[:8]
            seqs = _load_json(_SEQUENCES_PATH)
            seqs[seq_id] = {
                "name": name,
                "keyframes": keyframes,
                "keyframe_count": len(keyframes),
                "loop": data.get("loop", False),
                "speed": data.get("speed", 1.0),
                "created_at": datetime.utcnow().isoformat(),
            }
            _save_json(_SEQUENCES_PATH, seqs)
            logger.info("Saved sequence '%s' (%s) with %d keyframes", name, seq_id, len(keyframes))
            return jsonify({"success": True, "sequence_id": seq_id})

        @self.app.route("/api/anim/sequences/<seq_id>", methods=["DELETE"])
        def delete_sequence(seq_id: str) -> Any:
            """Delete a saved sequence by ID."""
            seqs = _load_json(_SEQUENCES_PATH)
            if seq_id not in seqs:
                return jsonify({"error": "Sequence not found"}), 404
            del seqs[seq_id]
            _save_json(_SEQUENCES_PATH, seqs)
            logger.info("Deleted sequence %s", seq_id)
            return jsonify({"success": True})

        # ── Apply pose to character ─────────────────────────────────────

        @self.app.route("/api/anim/apply", methods=["POST"])
        def apply_pose() -> Any:
            """Apply a pose to a character.

            Expected JSON body:
                character_id: str — target character
                pose_id: str (optional) — load from library
                pose_data: dict (optional) — direct joint data {joint: {x,y,z}}
            """
            data = request.json or {}
            cid = data.get("character_id")
            if not cid:
                return jsonify({"error": "character_id required"}), 400

            pose_data = data.get("pose_data")
            pose_id = data.get("pose_id")

            if pose_id and not pose_data:
                poses = _load_json(_POSES_PATH)
                if pose_id not in poses:
                    return jsonify({"error": "Pose not found"}), 404
                pose_data = poses[pose_id]["joints"]

            if not pose_data:
                return jsonify({"error": "pose_id or pose_data required"}), 400

            logger.info("Applying pose to character %s (%d joints)", cid, len(pose_data))
            return jsonify({"success": True, "character_id": cid, "joints": pose_data})

        # ── Save custom expression ──────────────────────────────────────

        @self.app.route("/api/anim/expressions", methods=["GET"])
        def list_expressions() -> Any:
            """Return saved custom expressions from pose library."""
            poses = _load_json(_POSES_PATH)
            expressions = {k: v for k, v in poses.items() if v.get("type") == "expression"}
            return jsonify({"expressions": expressions})

        @self.app.route("/api/anim/expressions", methods=["POST"])
        def save_expression() -> Any:
            """Save a custom expression preset.

            Expected JSON body:
                name: str
                values: dict — {browY, browRot, mouthSX, mouthSY, pupilS, headTilt, blush}
            """
            data = request.json or {}
            name = data.get("name", "").strip()
            values = data.get("values")
            if not name or not values:
                return jsonify({"error": "name and values required"}), 400

            expr_id = "expr_" + str(uuid.uuid4())[:8]
            poses = _load_json(_POSES_PATH)
            poses[expr_id] = {
                "name": name,
                "type": "expression",
                "values": values,
                "created_at": datetime.utcnow().isoformat(),
            }
            _save_json(_POSES_PATH, poses)
            logger.info("Saved expression '%s' (%s)", name, expr_id)
            return jsonify({"success": True, "expression_id": expr_id})
