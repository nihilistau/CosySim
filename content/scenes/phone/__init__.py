"""SIGNAL — phone scene package (v0.68 Dark Renaissance).

Version: v1.62.0 [2026-06-15]

Change Log:
    v1.62.0 [2026-06-15] — PH-T3: import phone_hack to register the
                            player→NPC phone-hacking @skill at package load.
    v1.50.1 [2026-03-22] — Removed conflicting NeonPhone import that caused
                            dual Flask app / duplicate skill registration
    v0.68   [2026-03-21] — Dark Renaissance, PhoneSceneV2 + NeonPhone coexist
"""
from .phone_scene_v2 import PhoneSceneV2
from . import phone_skills as _phone_skills  # noqa: F401 — register @skill decorators
from . import phone_hack as _phone_hack      # noqa: F401 — register PH-T3 @skill

# NeonPhone (legacy SIGNAL) archived — PhoneSceneV2 is the active implementation
__all__ = ["PhoneSceneV2"]
