"""
CharacterAgent — v2.5 thin adapter around VirtualAgent.

All LLM inference is routed through the :class:`VirtualAgentManager`.
``CharacterAgent`` exists purely as a convenience constructor that
translates the traditional ``(character, db, skill_packs, …)`` signature
into a ``VirtualAgent`` instance managed by the global singleton.

Usage::

    from engine.agents import CharacterAgent

    agent = CharacterAgent(char, db=db, scene="bedroom")
    reply = agent.reply("Hey, what are you up to?")
    print(reply)
"""
from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional, Set

from engine.agents.protocols import AgentCapability

logger = logging.getLogger(__name__)


class CharacterAgent:
    """
    Thin adapter: creates a :class:`VirtualAgent` internally and delegates
    every call to it.  The ``use_virtual`` parameter is accepted for
    backward compatibility but ignored — VirtualAgent is always used.

    Parameters
    ----------
    character : Character
        The character whose persona drives the system prompt.
    db : Database, optional
        Database instance for RAG queries and event logging.
    config : ConfigManager, optional
        Config override.  Uses global config if None.
    skill_packs : list[str], optional
        Skill pack names (e.g. ``["comfyui", "memory"]``).
    model : str, optional
        LMStudio model key.  Defaults to the currently loaded model.
    max_context_memories : int
        RAG memories to inject (default 5).
    scene : str, optional
        Scene identifier — passed to MCP framework for tracking.
    """

    def __init__(
        self,
        character,
        *,
        db=None,
        config=None,
        skill_packs: Optional[List[str]] = None,
        model:       Optional[str]       = None,
        max_context_memories: int        = 5,
        use_mcp:     bool                = False,
        mcp_servers: Optional[List[Dict]] = None,
        scene:       Optional[str]       = None,
        inference_config: Optional[Any]  = None,
        use_virtual: bool                = True,   # kept for compat; always True
    ) -> None:
        self.character = character
        self.db = db
        self.skill_packs = skill_packs or []
        self.model = model
        self.max_context_memories = max_context_memories
        self.use_mcp = use_mcp
        self.mcp_servers = mcp_servers or []
        self.scene = scene
        self._inference_config = inference_config

        if config is None:
            from engine.config import get_config
            config = get_config()
        self.config = config

        if not self.use_mcp:
            self.use_mcp = bool(config.get("lmstudio.mcp_enabled", False))

        # Capabilities — mirrored from the underlying VirtualAgent
        self.capabilities: Set[AgentCapability] = {
            AgentCapability.TEXT, AgentCapability.MEMORY,
        }
        if self.skill_packs:
            self.capabilities.add(AgentCapability.TOOLS)
        if self.use_mcp:
            self.capabilities.add(AgentCapability.GOVERNED)

        # Create the underlying VirtualAgent via the manager
        from engine.agents.virtual_agent_manager import get_virtual_agent_manager
        mgr = get_virtual_agent_manager()
        self._virtual = mgr.create_agent(
            character,
            db=db,
            config=config,
            scene=scene,
            model=model,
            skill_packs=skill_packs,
            use_mcp=self.use_mcp,
            mcp_servers=mcp_servers,
            inference_config=inference_config,
            max_context_memories=max_context_memories,
        )

    # ──────────────────────────────────────────────────── public API ──

    def reply(
        self,
        user_message: str,
        *,
        chain_id:  Optional[str]        = None,
        history:   Optional[List[Dict]] = None,
        use_tools: bool                 = True,
        **kwargs,
    ) -> str:
        """Generate a reply by delegating to the underlying VirtualAgent."""
        return self._virtual.reply(
            user_message,
            chain_id=chain_id,
            history=history,
            use_tools=use_tools,
            **kwargs,
        )

    def quick_query(self, prompt: str, *, max_tokens: int = 2000) -> str:
        """Lightweight single-shot completion via VirtualAgent."""
        return self._virtual.quick_query(prompt, max_tokens=max_tokens)

    def cancel(self) -> None:
        """Cancel the current inference request."""
        self._virtual.cancel()

    # ──────────────────────────────────── state / model accessors ──

    def get_state(self) -> Dict[str, Any]:
        """Return the underlying VirtualAgent's state snapshot."""
        return self._virtual.get_state()

    def update_state(self, **kwargs: Any) -> None:
        """Update state on the underlying VirtualAgent."""
        self._virtual.update_state(**kwargs)

    def set_model(self, model: str) -> None:
        """Change the model used for inference."""
        self.model = model
        self._virtual.set_model(model)

    @property
    def virtual(self):
        """Direct access to the underlying VirtualAgent."""
        return self._virtual

    def __repr__(self) -> str:
        return (
            f"<CharacterAgent → {self._virtual!r}>"
        )
