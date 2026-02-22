"""The Realm — AI-Directed LitRPG / Visual Novel scene."""
from .realm_scene import RealmScene
from . import realm_skills as _realm_skills  # noqa: F401 — register @skill decorators

__all__ = ["RealmScene"]
