"""Interceptor: NexusPromptInterceptor.

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

class NexusPromptInterceptor(InterceptorBase):
    """
    Pre-call interceptor that enriches agent system prompts with knowledge
    from Nexus KMS — stored prompts, governance rules, and scene-specific
    context retrieved at runtime.

    This enables dynamic prompt updates without code changes: modify the
    prompt in Nexus and agents pick it up on next call.

    Priority 6 — runs after NaturalMoodDriftInterceptor (5) so mood context
    is established before Nexus knowledge is injected.
    """
    name     = "nexus_prompt"
    priority = 6

    _TTL_SECS = 300  # Cache Nexus responses for 5 minutes
    _cache: Dict[str, Any] = {}
    _cache_ts: Dict[str, float] = {}
    _lock = threading.Lock()

    def _cached_fetch(self, key: str, fetcher: Any) -> Any:
        """Fetch with TTL caching to avoid hammering Nexus on every call."""
        now = time.time()
        with self._lock:
            if key in self._cache and (now - self._cache_ts.get(key, 0)) < self._TTL_SECS:
                return self._cache[key]
        try:
            result = fetcher()
            with self._lock:
                self._cache[key] = result
                self._cache_ts[key] = now
            return result
        except Exception as exc:
            logger.debug("NexusPromptInterceptor: fetch failed for '%s': %s", key, exc)
            with self._lock:
                return self._cache.get(key)

    def pre_call(self, ctx: ResponseContext) -> None:
        """Inject Nexus-sourced prompt fragments and rules into system prompt."""
        try:
            from engine.nexus.client import get_nexus_client
            nx = get_nexus_client()
            if not nx:
                return
        except Exception:
            return

        parts: List[str] = []

        # 1. Fetch base agent prompt from Nexus (if stored)
        base_prompt = self._cached_fetch(
            "prompt:base_agent",
            lambda: nx.search("CosySim Agent Base System Prompt", limit=1),
        )
        if base_prompt and isinstance(base_prompt, list) and len(base_prompt) > 0:
            content = base_prompt[0].get("content", "")
            if content and len(content) > 20:
                parts.append(content)

        # 2. Fetch governance rules for the scene
        scene_id = ctx.get("scene_id", ctx.get("scene", ""))
        if scene_id:
            rules = self._cached_fetch(
                f"rules:scene:{scene_id}",
                lambda: nx.get_rules(scope=f"scene:{scene_id}"),
            )
            if rules:
                rule_text = "\n".join(
                    f"- [{r.get('scope', '?')}] {r.get('rule', r.get('content', ''))}"
                    for r in rules
                    if isinstance(r, dict)
                )
                if rule_text:
                    parts.append(f"GOVERNANCE RULES:\n{rule_text}")

        # 3. Fetch global rules
        global_rules = self._cached_fetch(
            "rules:global",
            lambda: nx.get_rules(scope="global"),
        )
        if global_rules:
            global_text = "\n".join(
                f"- {r.get('rule', r.get('content', ''))}"
                for r in global_rules
                if isinstance(r, dict)
            )
            if global_text:
                parts.append(f"GLOBAL RULES:\n{global_text}")

        # 4. Fetch agent-specific rules
        agent_rules = self._cached_fetch(
            "rules:agent",
            lambda: nx.get_rules(scope="agent:*"),
        )
        if agent_rules:
            agent_text = "\n".join(
                f"- {r.get('rule', r.get('content', ''))}"
                for r in agent_rules
                if isinstance(r, dict)
            )
            if agent_text:
                parts.append(f"AGENT RULES:\n{agent_text}")

        if parts:
            nexus_context = "\n\n".join(parts)
            ctx["system_prompt"] = (
                ctx.get("system_prompt", "")
                + "\n\n--- Nexus Knowledge Context ---\n"
                + nexus_context
                + "\n---"
            )
