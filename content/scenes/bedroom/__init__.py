"""The Director's Bedroom — scene package."""
from .bedroom_scene import BedroomScene
from . import bedroom_skills as _bedroom_skills  # noqa: F401 — register @skill decorators

__all__ = ["BedroomScene"]