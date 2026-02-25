"""
engine.mcp.tools — Extracted business-logic helpers for MCP tool handlers.

Each sub-module contains pure functions (no ``@mcp.tool`` decorators, no
module-level globals).  The thin wrappers in ``cosysim_server.py`` call
these functions, passing service dependencies as explicit arguments.
"""

from engine.mcp.tools.memory_tools import search_memory, store_memory
from engine.mcp.tools.character_tools import (
    get_character_state,
    adjust_relationship,
    list_characters,
    character_register,
    character_query,
    character_set_attribute,
    character_get_summary,
    character_assign_skill,
    character_revoke_skill,
    character_get_skills,
    character_add_restriction,
    character_remove_restriction,
)

__all__ = [
    # memory
    "search_memory",
    "store_memory",
    # character (db-backed)
    "get_character_state",
    "adjust_relationship",
    "list_characters",
    # character (registry-backed)
    "character_register",
    "character_query",
    "character_set_attribute",
    "character_get_summary",
    "character_assign_skill",
    "character_revoke_skill",
    "character_get_skills",
    "character_add_restriction",
    "character_remove_restriction",
]