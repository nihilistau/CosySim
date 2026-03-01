"""SIGNAL — phone scene package (v0.68 Dark Renaissance)."""
from .neon_phone import NeonPhone
from . import phone_skills as _phone_skills  # noqa: F401 — register @skill decorators

# Legacy alias kept for loader compatibility
PhoneSceneV2 = NeonPhone

__all__ = ["NeonPhone", "PhoneSceneV2"]
