"""Tool Registry — Bridge between MCP tools and SDK .act() tool calling.

The LMStudio SDK's ``llm.act()`` accepts plain Python callables.  This
module gathers the MCP tool functions, organises them into scoped sets
(character, game, system, router), and provides them as ready-to-use
lists for the SDK or as JSON-schema descriptors for the REST /tools
endpoint.

Usage::

    from engine.lmstudio.tool_registry import get_tool_registry

    registry = get_tool_registry()
    tools = registry.get_tools("character")      # [callable, ...]
    schemas = registry.get_tool_schemas("game")   # [{name, desc, params}, ...]
"""
from __future__ import annotations

import inspect
import logging
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Callable, Dict, List, Optional, Set

logger = logging.getLogger(__name__)


# ── Scope enum ───────────────────────────────────────────────────────

class ToolScope(str, Enum):
    """Logical grouping of tools visible to different agent roles."""
    CHARACTER = "character"
    GAME = "game"
    SYSTEM = "system"
    ROUTER = "router"
    SCENE = "scene"
    CONVERSATION = "conversation"
    ADMIN = "admin"


# ── Tool descriptor ──────────────────────────────────────────────────

@dataclass
class ToolSpec:
    """Metadata wrapper around a plain callable for the SDK."""
    name: str
    fn: Callable
    description: str = ""
    scopes: Set[ToolScope] = field(default_factory=set)
    parameters: Dict[str, Any] = field(default_factory=dict)
    thread_safe: bool = True
    cooldown_ms: int = 0

    # ── JSON schema for REST / overlay ──
    def to_schema(self) -> Dict[str, Any]:
        """Return a JSON-schema-compatible descriptor."""
        return {
            "name": self.name,
            "description": self.description,
            "parameters": self.parameters,
            "scopes": [s.value for s in self.scopes],
            "thread_safe": self.thread_safe,
        }


# ── Registry ─────────────────────────────────────────────────────────

# Default scope assignments for known MCP tools.
# Tools not listed here get assigned to SYSTEM by default.
_SCOPE_MAP: Dict[str, Set[ToolScope]] = {
    # -- Character tools --
    "search_memory":        {ToolScope.CHARACTER, ToolScope.SYSTEM},
    "store_memory":         {ToolScope.CHARACTER, ToolScope.SYSTEM},
    "get_character_state":  {ToolScope.CHARACTER, ToolScope.SYSTEM},
    "adjust_relationship":  {ToolScope.CHARACTER, ToolScope.GAME},
    "update_mood":          {ToolScope.CHARACTER, ToolScope.GAME},
    "apply_effect":         {ToolScope.CHARACTER, ToolScope.GAME},
    "check_relationship":   {ToolScope.CHARACTER},
    "memory_recall":        {ToolScope.CHARACTER},
    "speak_as":             {ToolScope.CHARACTER},
    "enforce_behavior":     {ToolScope.CHARACTER},
    "mood_contagion":       {ToolScope.CHARACTER},
    "character_register":   {ToolScope.CHARACTER, ToolScope.ADMIN},
    "character_query":      {ToolScope.CHARACTER},
    "character_set_attribute":  {ToolScope.CHARACTER, ToolScope.ADMIN},
    "character_get_summary":    {ToolScope.CHARACTER},
    "character_assign_skill":   {ToolScope.CHARACTER, ToolScope.ADMIN},
    "character_revoke_skill":   {ToolScope.CHARACTER, ToolScope.ADMIN},
    "character_get_skills":     {ToolScope.CHARACTER},
    "character_add_restriction":    {ToolScope.CHARACTER, ToolScope.ADMIN},
    "character_remove_restriction": {ToolScope.CHARACTER, ToolScope.ADMIN},
    "get_character_agency_summary": {ToolScope.CHARACTER},
    "check_character_consent":      {ToolScope.CHARACTER},

    # -- Wardrobe tools --
    "wardrobe_get":         {ToolScope.CHARACTER, ToolScope.GAME},
    "wardrobe_init":        {ToolScope.CHARACTER, ToolScope.ADMIN},
    "wardrobe_remove_item":     {ToolScope.CHARACTER, ToolScope.GAME},
    "wardrobe_remove_outermost":{ToolScope.CHARACTER, ToolScope.GAME},
    "wardrobe_add_item":        {ToolScope.CHARACTER, ToolScope.GAME},
    "wardrobe_redress":         {ToolScope.CHARACTER, ToolScope.GAME},

    # -- Game tools --
    "get_game_state":       {ToolScope.GAME},
    "set_game_state":       {ToolScope.GAME},
    "start_game":           {ToolScope.GAME},
    "end_game":             {ToolScope.GAME},
    "launch_game":          {ToolScope.GAME},
    "get_active_game":      {ToolScope.GAME},
    "game_action":          {ToolScope.GAME},
    "game_history":         {ToolScope.GAME},
    "roll_dice":            {ToolScope.GAME, ToolScope.CHARACTER},
    "get_random_topic":     {ToolScope.GAME, ToolScope.CHARACTER},
    "random_pick":          {ToolScope.GAME, ToolScope.CHARACTER},
    "get_dialog_options":   {ToolScope.GAME, ToolScope.CHARACTER},
    "speech_enhance":       {ToolScope.GAME, ToolScope.CHARACTER},
    "perform_interaction":          {ToolScope.GAME},
    "list_available_interactions":  {ToolScope.GAME},
    "get_interaction_details":      {ToolScope.GAME},
    "start_timed_action":   {ToolScope.GAME},
    "poll_timed_action":    {ToolScope.GAME},
    "abort_timed_action":   {ToolScope.GAME},
    "list_active_timed_actions":    {ToolScope.GAME},
    "get_character_scene_stats":    {ToolScope.GAME, ToolScope.CHARACTER},
    "update_character_scene_stats": {ToolScope.GAME},
    "set_character_scene_stat":     {ToolScope.GAME, ToolScope.ADMIN},
    "reset_character_scene_stats":  {ToolScope.GAME, ToolScope.ADMIN},

    # -- Scene tools --
    "get_scene_context":        {ToolScope.SCENE, ToolScope.CHARACTER},
    "add_scene_narrative":      {ToolScope.SCENE},
    "get_scene_narrative":      {ToolScope.SCENE},
    "get_full_scene_snapshot":  {ToolScope.SCENE, ToolScope.SYSTEM},
    "set_scene_atmosphere":     {ToolScope.SCENE},
    "get_scene_rules":          {ToolScope.SCENE},
    "get_all_tools_for_scene":  {ToolScope.SCENE, ToolScope.ADMIN},
    "director_action":          {ToolScope.SCENE, ToolScope.ADMIN},
    "resolve_random_scene_event":   {ToolScope.SCENE, ToolScope.GAME},
    "scene_broadcast":          {ToolScope.SCENE},
    "get_scene_rules_summary":  {ToolScope.SCENE, ToolScope.CHARACTER},
    "get_scene_available_actions":  {ToolScope.SCENE, ToolScope.GAME},
    "apply_scene_rule":         {ToolScope.SCENE},
    "suggest_activity":         {ToolScope.SCENE, ToolScope.GAME},

    # -- Conversation tools --
    "set_response_directive":   {ToolScope.CONVERSATION, ToolScope.SYSTEM},
    "get_active_directive":     {ToolScope.CONVERSATION},
    "clear_directive":          {ToolScope.CONVERSATION},
    "get_conversation_heat":    {ToolScope.CONVERSATION, ToolScope.CHARACTER},
    "bump_conversation_heat":   {ToolScope.CONVERSATION, ToolScope.GAME},
    "get_conversation_heat_level":  {ToolScope.CONVERSATION},
    "check_conversation_history":   {ToolScope.CONVERSATION},
    "get_conversation_info":    {ToolScope.CONVERSATION},
    "fork_conversation":        {ToolScope.CONVERSATION, ToolScope.ADMIN},
    "query_stateless":          {ToolScope.CONVERSATION, ToolScope.SYSTEM},
    "send_to_agent":            {ToolScope.CONVERSATION, ToolScope.SYSTEM},
    "cross_scene_message":      {ToolScope.CONVERSATION},
    "get_cross_scene_inbox":    {ToolScope.CONVERSATION},

    # -- Media tools --
    "generate_image_request":   {ToolScope.CHARACTER, ToolScope.GAME},
    "send_selfie":              {ToolScope.CHARACTER, ToolScope.GAME},
    "send_voice_message":       {ToolScope.CHARACTER},

    # -- System / admin tools --
    "get_chain_events":     {ToolScope.SYSTEM},
    "log_event":            {ToolScope.SYSTEM},
    "list_characters":      {ToolScope.SYSTEM, ToolScope.ADMIN},
    "get_benchmark_stats":  {ToolScope.SYSTEM, ToolScope.ADMIN},
    "get_my_skills":        {ToolScope.SYSTEM, ToolScope.CHARACTER},
    "get_system_stats":     {ToolScope.SYSTEM, ToolScope.ADMIN},
    "search_web":           {ToolScope.SYSTEM},
    "get_framework_status": {ToolScope.SYSTEM, ToolScope.ADMIN},

    # -- Timer tools --
    "start_timer":          {ToolScope.GAME, ToolScope.SCENE},
    "check_timer":          {ToolScope.GAME, ToolScope.SCENE},
    "cancel_timer":         {ToolScope.GAME, ToolScope.SCENE},

    # -- Consequence tools --
    "schedule_consequence":     {ToolScope.GAME, ToolScope.SCENE},
    "get_pending_consequences": {ToolScope.GAME, ToolScope.SCENE},
    "cancel_consequence":       {ToolScope.GAME, ToolScope.SCENE},

    # -- Flavour / creative tools --
    "dream_whisper":        {ToolScope.CHARACTER},
    "mirror_soul":          {ToolScope.CHARACTER},
    "time_echo":            {ToolScope.SCENE, ToolScope.GAME},

    # -- Lounge scene tools --
    "serve_lounge_drink":       {ToolScope.GAME, ToolScope.SCENE},
    "start_lounge_performance": {ToolScope.GAME, ToolScope.SCENE},
    "get_lounge_menu":          {ToolScope.GAME, ToolScope.SCENE},
    "get_lounge_state":         {ToolScope.GAME, ToolScope.SCENE},
    "reveal_lounge_secret":     {ToolScope.GAME, ToolScope.SCENE},
    "trigger_lounge_event":     {ToolScope.GAME, ToolScope.SCENE},
    "lounge_heat_tick":         {ToolScope.GAME, ToolScope.SCENE},
}


def _extract_params(fn: Callable) -> Dict[str, Any]:
    """Build a simplified JSON-schema ``properties`` dict from type hints."""
    sig = inspect.signature(fn)
    hints = getattr(fn, "__annotations__", {})
    props: Dict[str, Any] = {}
    required: List[str] = []
    for name, param in sig.parameters.items():
        ptype = hints.get(name, str)
        type_name = getattr(ptype, "__name__", str(ptype))
        schema_type = {
            "str": "string", "int": "integer", "float": "number",
            "bool": "boolean",
        }.get(type_name, "string")
        props[name] = {"type": schema_type}
        if param.default is inspect.Parameter.empty:
            required.append(name)
    return {"type": "object", "properties": props, "required": required}


class ToolRegistry:
    """Central registry of all tools available for SDK .act() calls.

    Collects MCP tool functions by importing the server module, wraps
    them in :class:`ToolSpec` descriptors, and exposes scoped subsets.
    """

    def __init__(self) -> None:
        self._tools: Dict[str, ToolSpec] = {}
        self._loaded = False

    # ── Loading ──────────────────────────────────────────────────────

    def load_from_mcp_server(self) -> int:
        """Import all @mcp.tool() functions from cosysim_server.

        Returns the number of tools registered.
        """
        try:
            from engine.mcp import cosysim_server as srv
        except ImportError:
            logger.warning("cosysim_server not importable — no tools loaded")
            return 0

        mcp_obj = getattr(srv, "mcp", None)
        if mcp_obj is None:
            logger.warning("No 'mcp' FastMCP instance found in cosysim_server")
            return 0

        # FastMCP stores tools in ._tool_manager._tools dict
        tool_mgr = getattr(mcp_obj, "_tool_manager", None)
        raw_tools = {}
        if tool_mgr:
            raw_tools = getattr(tool_mgr, "_tools", {})

        count = 0
        for name, tool_obj in raw_tools.items():
            fn = getattr(tool_obj, "fn", None)
            if fn is None:
                continue
            self.register(
                name=name,
                fn=fn,
                description=getattr(tool_obj, "description", "") or (fn.__doc__ or ""),
                scopes=_SCOPE_MAP.get(name, {ToolScope.SYSTEM}),
            )
            count += 1

        self._loaded = True
        logger.info("ToolRegistry loaded %d tools from MCP server", count)
        return count

    def register(
        self,
        name: str,
        fn: Callable,
        description: str = "",
        scopes: Optional[Set[ToolScope]] = None,
        thread_safe: bool = True,
        cooldown_ms: int = 0,
    ) -> ToolSpec:
        """Register a single tool function."""
        spec = ToolSpec(
            name=name,
            fn=fn,
            description=description or (fn.__doc__ or ""),
            scopes=scopes or {ToolScope.SYSTEM},
            parameters=_extract_params(fn),
            thread_safe=thread_safe,
            cooldown_ms=cooldown_ms,
        )
        self._tools[name] = spec
        return spec

    def unregister(self, name: str) -> bool:
        """Remove a tool by name. Returns True if it existed."""
        return self._tools.pop(name, None) is not None

    # ── Queries ──────────────────────────────────────────────────────

    def get_tool(self, name: str) -> Optional[ToolSpec]:
        return self._tools.get(name)

    def get_tools(
        self,
        scope: ToolScope | str | None = None,
        names: Optional[List[str]] = None,
    ) -> List[Callable]:
        """Return a list of plain callables filtered by scope or names.

        These are directly usable with ``llm.act(chat, tools=...)``.
        """
        if isinstance(scope, str):
            scope = ToolScope(scope)

        specs = self._filter(scope=scope, names=names)
        return [s.fn for s in specs]

    def get_tool_specs(
        self,
        scope: ToolScope | str | None = None,
        names: Optional[List[str]] = None,
    ) -> List[ToolSpec]:
        """Return ToolSpec objects filtered by scope or names."""
        if isinstance(scope, str):
            scope = ToolScope(scope)
        return self._filter(scope=scope, names=names)

    def get_tool_schemas(
        self,
        scope: ToolScope | str | None = None,
        names: Optional[List[str]] = None,
    ) -> List[Dict[str, Any]]:
        """Return JSON-schema descriptors filtered by scope or names."""
        specs = self.get_tool_specs(scope=scope, names=names)
        return [s.to_schema() for s in specs]

    def list_names(self, scope: ToolScope | str | None = None) -> List[str]:
        """List tool names, optionally filtered by scope."""
        if isinstance(scope, str):
            scope = ToolScope(scope)
        return [s.name for s in self._filter(scope=scope)]

    @property
    def all_tools(self) -> Dict[str, ToolSpec]:
        return dict(self._tools)

    @property
    def count(self) -> int:
        return len(self._tools)

    # ── Composite scopes for agent roles ─────────────────────────────

    def for_character_agent(self, character_id: str, scene_id: str = "") -> List[Callable]:
        """Tools a character agent should see during .act()."""
        scopes = {ToolScope.CHARACTER, ToolScope.GAME}
        specs = [s for s in self._tools.values() if s.scopes & scopes]
        return [s.fn for s in specs]

    def for_game_master(self, scene_id: str = "") -> List[Callable]:
        """Tools the game master / scene director should see."""
        scopes = {ToolScope.GAME, ToolScope.SCENE, ToolScope.CHARACTER}
        specs = [s for s in self._tools.values() if s.scopes & scopes]
        return [s.fn for s in specs]

    def for_system(self) -> List[Callable]:
        """All tools — used for system-level / admin .act() calls."""
        return [s.fn for s in self._tools.values()]

    def for_router(self) -> List[Callable]:
        """Tools the Gemma router model can call (lightweight only)."""
        scopes = {ToolScope.ROUTER}
        specs = [s for s in self._tools.values() if s.scopes & scopes]
        return [s.fn for s in specs]

    # ── Internal ─────────────────────────────────────────────────────

    def _filter(
        self,
        scope: Optional[ToolScope] = None,
        names: Optional[List[str]] = None,
    ) -> List[ToolSpec]:
        specs = list(self._tools.values())
        if scope is not None:
            specs = [s for s in specs if scope in s.scopes]
        if names is not None:
            name_set = set(names)
            specs = [s for s in specs if s.name in name_set]
        return sorted(specs, key=lambda s: s.name)


# ── Singleton ────────────────────────────────────────────────────────

_registry: Optional[ToolRegistry] = None


def get_tool_registry(auto_load: bool = True) -> ToolRegistry:
    """Return the singleton ToolRegistry, optionally loading MCP tools."""
    global _registry
    if _registry is None:
        _registry = ToolRegistry()
        if auto_load:
            _registry.load_from_mcp_server()
    return _registry


def reset_tool_registry() -> None:
    """Reset singleton (for tests)."""
    global _registry
    _registry = None
