"""SIGNAL — phone scene package (v0.68 Dark Renaissance).

Version: v1.50.1 [2026-03-22]

Change Log:
    v1.50.1 [2026-03-22] — Removed conflicting NeonPhone import that caused
                            dual Flask app / duplicate skill registration
    v0.68   [2026-03-21] — Dark Renaissance, PhoneSceneV2 + NeonPhone coexist
"""
from .phone_scene_v2 import PhoneSceneV2
from . import phone_skills as _phone_skills  # noqa: F401 — register @skill decorators

# NeonPhone (legacy SIGNAL) archived — PhoneSceneV2 is the active implementation
__all__ = ["PhoneSceneV2"]
