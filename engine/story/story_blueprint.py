"""Shared Flask blueprint for story arc API endpoints."""
from __future__ import annotations

from flask import Blueprint, jsonify

from engine.story.story_arc import get_story_arc_engine

story_bp = Blueprint("story", __name__)


@story_bp.route("/api/story/state/<scene>")
def story_state(scene: str):
    """Return arc state summary for a scene."""
    return jsonify(get_story_arc_engine().get_scene_state(scene))


@story_bp.route("/api/story/arc/<arc_id>")
def arc_detail(arc_id: str):
    """Return detailed information about a single arc."""
    arc = get_story_arc_engine().get_arc(arc_id)
    if not arc:
        return jsonify({"error": "not found"}), 404
    return jsonify({
        "id": arc.id,
        "name": arc.name,
        "scene": arc.scene,
        "status": arc.status,
        "progress": arc.progress,
        "outcome": arc.outcome,
        "steps": [
            {
                "id": s.id,
                "description": s.description,
                "completed": s.completed,
                "failed": s.failed,
            }
            for s in arc.steps
        ],
    })
