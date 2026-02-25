"""Phone scene module"""
from .phone_scene_v2 import PhoneSceneV2
from . import phone_skills as _phone_skills  # noqa: F401 — register @skill decorators

__all__ = ['PhoneSceneV2']
