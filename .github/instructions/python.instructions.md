---
description: 'CosySim Python coding conventions — absolute imports, type hints, Google docstrings, 4-space indent, MCP-first state management'
applyTo: '**/*.py'
---

# CosySim Python Conventions

## Imports
- Use absolute imports only: `from engine.config import get_config`
- Never use relative imports (`from .module import X`)
- Group imports: stdlib → third-party → engine → content → local

## Type Hints
- Required on all function signatures (parameters and return type)
- Use `from __future__ import annotations` for forward references
- Import from `typing`: `Optional`, `Dict`, `List`, `Any`, `Callable`, `Protocol`

## Docstrings
- Google style with summary line, then `Args:`, `Returns:`, `Raises:`
- Module-level docstrings before imports
- Class docstrings immediately after `class` line

## Naming
- Classes: PascalCase (`MCPFramework`, `BaseScene`)
- Functions/methods: snake_case (`get_active_scene`)
- Constants: UPPER_SNAKE (`SKILL_REGISTRY`)
- Private: underscore prefix (`_build_request`)
- Files: snake_case (`character_registry.py`)

## Formatting
- 4 spaces, no tabs
- Double quotes for strings
- f-strings preferred over `.format()` or `%`
- Line length: 88–100 (soft), 120 max for type hints
- Section dividers: `# ──── Section Name ────`

## Logging
- Use `logger = logging.getLogger(__name__)` per module
- Never use `print()` — use `logger.info/debug/warning/error`

## State Management
- All mutable game state must sync to the MCPFramework tree
- Access config via `get_config().get("dot.path", default)`
- Never hardcode ports, paths, or model names
