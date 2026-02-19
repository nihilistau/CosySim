"""
Config Validator — checks config YAML for missing or invalid keys.

Called on startup to surface misconfigurations early.

Usage::

    from engine.config_validator import validate_config
    warnings = validate_config(config_dict)
"""
from __future__ import annotations

import logging
from typing import Any, Dict, List

logger = logging.getLogger(__name__)

# Schema: {dot_path: {"type": type, "required": bool, "range": (min, max)|None}}
_SCHEMA: Dict[str, Dict[str, Any]] = {
    "system.name":              {"type": str,   "required": True},
    "system.version":           {"type": str,   "required": True},
    "database.sqlite.path":     {"type": str,   "required": True},
    "scenes.phone.port":        {"type": int,   "required": True,  "range": (1024, 65535)},
    "scenes.bedroom.port":      {"type": int,   "required": True,  "range": (1024, 65535)},
    "scenes.dashboard.port":    {"type": int,   "required": True,  "range": (1024, 65535)},
    "llm.default.base_url":     {"type": str,   "required": True},
    "llm.default.temperature":  {"type": float, "required": False, "range": (0.0, 2.0)},
    "llm.default.max_tokens":   {"type": int,   "required": False, "range": (1, 100000)},
    "logging.level":            {"type": str,   "required": False},
    "comfyui.base_url":         {"type": str,   "required": False},
}

_MISSING = object()


def _resolve(cfg: Dict, path: str) -> Any:
    """Resolve a dot-notation path in a nested dict."""
    keys = path.split(".")
    current = cfg
    for k in keys:
        if isinstance(current, dict) and k in current:
            current = current[k]
        else:
            return _MISSING
    return current


def validate_config(cfg: Dict[str, Any]) -> List[str]:
    """Validate *cfg* (raw dict from YAML) against the schema.

    Returns a list of human-readable warning strings. Empty = all OK.
    """
    warnings: List[str] = []

    for path, rules in _SCHEMA.items():
        value = _resolve(cfg, path)

        if value is _MISSING:
            if rules.get("required"):
                warnings.append(f"Missing required config key: {path}")
            continue

        expected = rules.get("type")
        if expected and not isinstance(value, expected):
            if expected is float and isinstance(value, (int, float)):
                value = float(value)
            else:
                warnings.append(
                    f"Config '{path}': expected {expected.__name__}, got {type(value).__name__}"
                )
                continue

        rng = rules.get("range")
        if rng and isinstance(value, (int, float)):
            lo, hi = rng
            if value < lo or value > hi:
                warnings.append(f"Config '{path}': value {value} outside range [{lo}, {hi}]")

    # Port uniqueness
    ports: Dict[str, int] = {}
    for path in _SCHEMA:
        if "port" in path:
            val = _resolve(cfg, path)
            if val is not _MISSING and isinstance(val, int):
                if val in ports.values():
                    dup = [k for k, v in ports.items() if v == val][0]
                    warnings.append(f"Port conflict: '{path}' and '{dup}' both use port {val}")
                ports[path] = val

    return warnings


def validate_and_log() -> List[str]:
    """Load the active config and validate it, logging any warnings."""
    try:
        from engine.config import get_config
        cfg = get_config()
        raw = getattr(cfg, '_config', {})
        if not raw:
            return []
        warnings = validate_config(raw)
        for w in warnings:
            logger.warning("Config validation: %s", w)
        if not warnings:
            logger.info("Config validation passed")
        return warnings
    except Exception as e:
        logger.error("Config validation failed: %s", e)
        return [str(e)]
