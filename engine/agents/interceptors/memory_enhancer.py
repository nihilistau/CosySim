"""Interceptor: MemoryEnhancerInterceptor.

Split from engine/agents/interceptors.py by scripts/hindsight/split_interceptors.py.
"""

from __future__ import annotations

import json
import logging
import threading
import time
from typing import Any, Dict, List, Optional, Tuple

from engine.mcp.comms_framework import (
    InterceptorBase,
    ResponseContext,
    TRIGGER_OPTIONAL,
    TRIGGER_REQUIRED,
)

logger = logging.getLogger(__name__)

class MemoryEnhancerInterceptor(InterceptorBase):
    """
    Pre-call: run an additional RAG search targeting the current user message
    and append any *highly relevant* extra memories (beyond what CharacterAgent
    already injects) as a supplemental context block.

    Disabled by default (add to pipeline explicitly when deep recall matters).
    """
    name     = "memory_enhancer"
    priority = 70

    def __init__(self, top_k: int = 3) -> None:
        super().__init__()
        self.top_k = top_k

    def pre_call(self, ctx: ResponseContext) -> None:
        agent_id = ctx.get("agent_id", "")
        if not agent_id:
            return
        user_msg = ctx.get("user_message", "")
        if not user_msg:
            return
        try:
            from content.simulation.database.rag import RAGMemory
            rag = RAGMemory()
            results = rag.search(user_msg, n_results=self.top_k, character_id=agent_id)
            if results:
                snippets = []
                for r in results:
                    text = r.get("content", str(r)) if isinstance(r, dict) else str(r)
                    snippets.append(f"• {text[:200]}")
                block = "\n".join(snippets)
                ctx["system_prompt"] = ctx.get("system_prompt", "") + (
                    f"\n\n--- Enhanced memory context ---\n{block}\n---"
                )
        except Exception as exc:
            logger.debug("MemoryEnhancerInterceptor failed: %s", exc)
