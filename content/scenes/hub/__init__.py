"""THE TERMINAL — CosySim navigation hub. v0.68 Dark Renaissance."""
from .hub_flask import HubScene
from . import hub_skills as _hub_skills  # noqa: F401 — register @skill decorators

__all__ = ["HubScene"]
