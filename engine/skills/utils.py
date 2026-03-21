"""Shared utilities for skill packs."""
from __future__ import annotations

import json
from typing import Any


def to_json(obj: Any, **kwargs: Any) -> str:
    """Serialize *obj* to a compact JSON string."""
    kwargs.setdefault("default", str)
    return json.dumps(obj, **kwargs)
