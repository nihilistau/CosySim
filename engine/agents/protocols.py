"""
engine.agents.protocols — Shared interfaces for the CosySim agent layer
=====================================================================

Defines the ``IAgent`` protocol so any agent-compatible object (CharacterAgent,
AgentGovernor, _PhoneCharacterAgent adapter, test doubles, etc.) is type-safe
and interchangeable without importing the concrete classes.

Usage::

    from engine.agents.protocols import IAgent

    def run_agent(agent: IAgent, message: str) -> str:
        return agent.reply(message)

    # Any class that implements .character, .reply(), .quick_query(), .cancel()
    # satisfies IAgent without subclassing.
"""
from __future__ import annotations

import enum
import typing
from typing import Any, Dict, List, Optional

# runtime_checkable makes isinstance(obj, IAgent) work
from typing import runtime_checkable, Protocol


# ══════════════════════════════════════════════════════════════════════
#  IAgent — the minimal agent contract
# ══════════════════════════════════════════════════════════════════════

@runtime_checkable
class IAgent(Protocol):
    """
    Structural protocol for CosySim agent objects.

    Any object that provides these attributes and methods satisfies ``IAgent``
    without inheriting from it.

    Attributes
    ----------
    character
        A character data object.  Expected to have at least ``.id`` and
        ``.name`` attributes.  May be None for system / utility agents.

    Methods
    -------
    reply(user_message, *, chain_id, history, **kwargs) -> str
        Generate a reply to *user_message*.  ``chain_id`` and ``history``
        are optional keyword-only.  Extra ``**kwargs`` must be accepted
        and silently ignored (e.g. ``use_tools=False`` from AgentLoop).

    quick_query(prompt) -> str
        Lightweight single-prompt completion — no chain, no tools, just text.
        Used by AgentLoop for fast JSON decision generation.

    cancel() -> None
        Abort the currently running LLM prediction (best-effort).
    """

    character: Any  # CharacterData-compatible; None allowed

    def reply(
        self,
        user_message: str,
        *,
        chain_id: Optional[str] = None,
        history:  Optional[List[Dict]] = None,
        **kwargs: Any,
    ) -> str: ...

    def quick_query(self, prompt: str) -> str: ...

    def cancel(self) -> None: ...


# ══════════════════════════════════════════════════════════════════════
#  AgentCapability — enum of declared agent capabilities
# ══════════════════════════════════════════════════════════════════════

class AgentCapability(str, enum.Enum):
    """
    Capabilities that an agent can declare.

    Used by AgentRouter and AgentLoop to route tasks to capable agents.

    Example::

        agent.capabilities = {AgentCapability.TTS, AgentCapability.MEMORY}
    """
    # Core
    TEXT         = "text"          # basic text reply
    TOOLS        = "tools"         # can execute skill-pack tools
    MEMORY       = "memory"        # performs RAG memory lookups
    STREAMING    = "streaming"     # supports token-by-token streaming

    # Modalities
    TTS          = "tts"           # generates / triggers TTS audio
    VISION       = "vision"        # processes image inputs
    IMAGE_GEN    = "image_gen"     # can generate images via ComfyUI / DALL-E

    # Governance
    GOVERNED     = "governed"      # wrapped in AgentGovernor interceptor pipeline
    POLICY       = "policy"        # respects InteractionPolicy constraints

    # Game
    GAME_PLAYER  = "game_player"   # participates in MCPGameSession
    GAME_HOST    = "game_host"     # hosts a MCPGameSession


# ══════════════════════════════════════════════════════════════════════
#  IInterceptor — the minimal interceptor contract
# ══════════════════════════════════════════════════════════════════════

@runtime_checkable
class IInterceptor(Protocol):
    """
    Structural protocol for pipeline interceptors.

    Matches ``InterceptorBase`` from ``comms_framework`` without importing it,
    breaking potential circular imports.
    """
    name:     str
    priority: int

    def pre_call(self, ctx: Dict) -> None: ...
    def post_call(self, ctx: Dict) -> None: ...


# ══════════════════════════════════════════════════════════════════════
#  Type aliases
# ══════════════════════════════════════════════════════════════════════

AgentId        = str
SceneId        = str
ChainId        = str
CharacterId    = str
MessageList    = List[Dict[str, str]]   # [{"role": ..., "content": ...}]

__all__ = [
    "IAgent",
    "IInterceptor",
    "AgentCapability",
    "AgentId",
    "SceneId",
    "ChainId",
    "CharacterId",
    "MessageList",
]
