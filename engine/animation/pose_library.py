"""
PoseLibrary — CRUD manager for pose presets stored in JSON.

Provides:
- Load/save pose presets from a JSON file
- Category-based organization and filtering
- Built-in pose protection (cannot delete built-in poses)
- Pose validation (joint count, required fields)
- Bulk import/export
"""
from __future__ import annotations

import json
import logging
import os
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

REQUIRED_JOINTS = [
    "head", "torso", "arm_l", "arm_r", "forearm_l", "forearm_r",
    "hand_l", "hand_r", "thigh_l", "thigh_r", "shin_l", "shin_r",
]


class PoseLibrary:
    """JSON-backed pose library with category management.

    Args:
        path: Path to the poses.json file.
        auto_save: Whether to auto-save after mutations.
    """

    def __init__(self, path: str, auto_save: bool = True) -> None:
        self.path = path
        self.auto_save = auto_save
        self._poses: Dict[str, Dict[str, Any]] = {}
        self._load()

    def _load(self) -> None:
        """Load poses from disk."""
        if not os.path.exists(self.path):
            logger.info("No pose file at %s — starting empty", self.path)
            self._poses = {}
            return
        try:
            with open(self.path, "r", encoding="utf-8") as f:
                self._poses = json.load(f)
            logger.info("Loaded %d poses from %s", len(self._poses), self.path)
        except Exception as exc:
            logger.error("Failed to load poses from %s: %s", self.path, exc)
            self._poses = {}

    def _save(self) -> None:
        """Save poses to disk."""
        os.makedirs(os.path.dirname(self.path), exist_ok=True)
        try:
            with open(self.path, "w", encoding="utf-8") as f:
                json.dump(self._poses, f, indent=2)
        except Exception as exc:
            logger.error("Failed to save poses to %s: %s", self.path, exc)

    def reload(self) -> None:
        """Reload poses from disk."""
        self._poses.clear()
        self._load()

    # ── Query ──

    def get(self, pose_id: str) -> Optional[Dict[str, Any]]:
        """Get a single pose by ID."""
        return self._poses.get(pose_id)

    def get_all(self) -> Dict[str, Dict[str, Any]]:
        """Get all poses."""
        return dict(self._poses)

    def count(self) -> int:
        """Total number of poses."""
        return len(self._poses)

    def list_ids(self) -> List[str]:
        """List all pose IDs."""
        return list(self._poses.keys())

    def list_categories(self) -> List[str]:
        """List all unique categories."""
        cats = set()
        for pose in self._poses.values():
            cat = pose.get("category", "uncategorized")
            cats.add(cat)
        return sorted(cats)

    def get_by_category(self, category: str) -> Dict[str, Dict[str, Any]]:
        """Get all poses in a category."""
        return {
            pid: pose for pid, pose in self._poses.items()
            if pose.get("category") == category
        }

    def get_by_location(self, location: str) -> Dict[str, Dict[str, Any]]:
        """Get all poses associated with a location."""
        return {
            pid: pose for pid, pose in self._poses.items()
            if pose.get("location") == location
        }

    def get_builtin(self) -> Dict[str, Dict[str, Any]]:
        """Get all built-in poses."""
        return {
            pid: pose for pid, pose in self._poses.items()
            if pose.get("builtin", False)
        }

    def get_custom(self) -> Dict[str, Dict[str, Any]]:
        """Get all user-created (non-builtin) poses."""
        return {
            pid: pose for pid, pose in self._poses.items()
            if not pose.get("builtin", False)
        }

    def search(self, query: str) -> Dict[str, Dict[str, Any]]:
        """Search poses by name, category, or location."""
        q = query.lower()
        return {
            pid: pose for pid, pose in self._poses.items()
            if q in pose.get("name", "").lower()
            or q in pose.get("category", "").lower()
            or q in pose.get("location", "").lower()
            or q in pid.lower()
        }

    # ── Mutation ──

    def add(
        self,
        pose_id: str,
        name: str,
        joints: Dict[str, Dict[str, float]],
        category: str = "custom",
        location: str = "any",
        builtin: bool = False,
    ) -> bool:
        """Add a new pose.

        Args:
            pose_id: Unique identifier for the pose.
            name: Human-readable name.
            joints: Dict of joint rotations {joint_name: {x, y, z}}.
            category: Pose category for grouping.
            location: Associated location (or 'any').
            builtin: Whether this is a built-in pose.

        Returns:
            True if added successfully, False if validation failed.
        """
        if pose_id in self._poses:
            logger.warning("Pose '%s' already exists — use update()", pose_id)
            return False

        if not self._validate_joints(joints):
            return False

        self._poses[pose_id] = {
            "name": name,
            "builtin": builtin,
            "category": category,
            "location": location,
            "joints": joints,
            "joint_count": len(joints),
            "created_at": datetime.now(timezone.utc).isoformat(),
        }

        if self.auto_save:
            self._save()
        return True

    def update(
        self,
        pose_id: str,
        joints: Optional[Dict[str, Dict[str, float]]] = None,
        name: Optional[str] = None,
        category: Optional[str] = None,
        location: Optional[str] = None,
    ) -> bool:
        """Update an existing pose.

        Args:
            pose_id: The pose to update.
            joints: New joint data (optional).
            name: New name (optional).
            category: New category (optional).
            location: New location (optional).

        Returns:
            True if updated, False if pose not found.
        """
        if pose_id not in self._poses:
            logger.warning("Pose '%s' not found", pose_id)
            return False

        pose = self._poses[pose_id]
        if joints is not None:
            if not self._validate_joints(joints):
                return False
            pose["joints"] = joints
            pose["joint_count"] = len(joints)
        if name is not None:
            pose["name"] = name
        if category is not None:
            pose["category"] = category
        if location is not None:
            pose["location"] = location

        if self.auto_save:
            self._save()
        return True

    def delete(self, pose_id: str) -> bool:
        """Delete a pose (built-in poses cannot be deleted).

        Args:
            pose_id: The pose to delete.

        Returns:
            True if deleted, False if not found or built-in.
        """
        pose = self._poses.get(pose_id)
        if not pose:
            return False
        if pose.get("builtin", False):
            logger.warning("Cannot delete built-in pose '%s'", pose_id)
            return False

        del self._poses[pose_id]
        if self.auto_save:
            self._save()
        return True

    # ── Bulk Operations ──

    def import_poses(self, data: Dict[str, Dict[str, Any]], overwrite: bool = False) -> int:
        """Import multiple poses from a dictionary.

        Args:
            data: Dict of pose_id → pose data.
            overwrite: Whether to overwrite existing poses.

        Returns:
            Number of poses imported.
        """
        count = 0
        for pid, pose in data.items():
            if pid in self._poses and not overwrite:
                continue
            if pid in self._poses and self._poses[pid].get("builtin", False) and not overwrite:
                continue
            self._poses[pid] = pose
            count += 1

        if count > 0 and self.auto_save:
            self._save()
        logger.info("Imported %d poses", count)
        return count

    def export_poses(self, category: Optional[str] = None) -> Dict[str, Dict[str, Any]]:
        """Export poses as a dictionary.

        Args:
            category: Optional category filter.

        Returns:
            Dict of pose data.
        """
        if category:
            return self.get_by_category(category)
        return dict(self._poses)

    # ── Validation ──

    def _validate_joints(self, joints: Dict[str, Dict[str, float]]) -> bool:
        """Validate joint data structure."""
        if not isinstance(joints, dict):
            logger.error("joints must be a dict")
            return False
        for jname, jdata in joints.items():
            if jname not in REQUIRED_JOINTS:
                logger.warning("Unknown joint '%s' — accepted but may not render", jname)
            if not isinstance(jdata, dict):
                logger.error("Joint '%s' data must be a dict with x, y, z", jname)
                return False
            for axis in ("x", "y", "z"):
                if axis not in jdata:
                    logger.error("Joint '%s' missing axis '%s'", jname, axis)
                    return False
        return True

    def stats(self) -> Dict[str, Any]:
        """Return library statistics."""
        cats = {}
        builtin_count = 0
        custom_count = 0
        for pose in self._poses.values():
            cat = pose.get("category", "uncategorized")
            cats[cat] = cats.get(cat, 0) + 1
            if pose.get("builtin", False):
                builtin_count += 1
            else:
                custom_count += 1

        return {
            "total": len(self._poses),
            "builtin": builtin_count,
            "custom": custom_count,
            "categories": cats,
        }
