"""
Thread-local chain context for skill functions.

Skills are invoked by the LMStudio SDK (via ``llm.act()``), so the caller
cannot pass extra kwargs like ``chain_id`` directly.  Instead, the agent
sets the chain context *before* calling ``llm.act()`` and each skill reads
it from here.

Usage (agent side)::

    from engine.skills.chain_context import set_chain_context, clear_chain_context

    set_chain_context(chain_id=chain_id, scene_id="phone",
                      character_id=char.id)
    try:
        result = llm.act(chat, tools)
    finally:
        clear_chain_context()

Usage (skill side)::

    from engine.skills.chain_context import get_chain_context

    ctx = get_chain_context()
    chain_id = ctx.get("chain_id")  # may be None if no context set
"""

import threading
from typing import Any, Dict, Optional

_local = threading.local()


def set_chain_context(
    chain_id: Optional[str] = None,
    scene_id: str = "unknown",
    character_id: Optional[str] = None,
    parent_id: Optional[str] = None,
    **extra: Any,
) -> None:
    """Set the chain context for the current thread."""
    _local.chain_ctx = {
        "chain_id": chain_id,
        "scene_id": scene_id,
        "character_id": character_id,
        "parent_id": parent_id,
        **extra,
    }


def get_chain_context() -> Dict[str, Any]:
    """Return the current chain context (empty dict if not set)."""
    return getattr(_local, "chain_ctx", {})


def clear_chain_context() -> None:
    """Clear the chain context for the current thread."""
    _local.chain_ctx = {}
