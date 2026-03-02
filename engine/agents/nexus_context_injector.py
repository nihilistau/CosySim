"""NexusContextInjector — pre-call interceptor that enriches agent context from Nexus.

Searches Nexus for entries relevant to the user's last message and appends
the top results as a ``[NEXUS KNOWLEDGE]`` section in the system prompt.
Agents automatically benefit from accumulated Nexus knowledge without any
per-skill changes.
"""
from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

from engine.nexus.client import get_nexus_client

logger = logging.getLogger(__name__)


class NexusContextInjector:
    """Interceptor that searches Nexus for relevant context before each LLM call.

    Injects top Nexus search results as additional system context so agents
    automatically benefit from accumulated knowledge over time.

    Attributes:
        NAME: Identifier used in ``comms.interceptors`` config.
    """

    NAME = "nexus_context_injector"

    def __init__(self, max_results: int = 3, min_score: float = 0.5) -> None:
        """Initialise injector.

        Args:
            max_results: Maximum number of Nexus snippets to inject.
            min_score: Minimum relevance score for inclusion (reserved for
                future scored search; currently all returned results are
                included up to *max_results*).
        """
        self._max_results = max_results
        self._min_score = min_score

    # ── Interceptor interface ────────────────────────────────────────────

    def pre_call(self, request: Dict[str, Any], context: Dict[str, Any]) -> Dict[str, Any]:
        """Inject Nexus knowledge into the system message before the LLM call.

        Args:
            request: The LLM request dict (must contain ``messages`` list).
            context: Interceptor context (pass-through, not modified).

        Returns:
            Modified *request* with Nexus snippets appended to system message,
            or the original *request* unchanged if injection is skipped.
        """
        messages: List[Dict[str, Any]] = request.get("messages", [])
        if not messages:
            return request

        # Use the last user message as the search query
        last_user: Optional[str] = next(
            (m.get("content") for m in reversed(messages) if m.get("role") == "user"),
            None,
        )
        if not last_user or len(last_user) < 10:
            return request

        try:
            client = get_nexus_client()
            results = client.search(str(last_user)[:200])
            if not results:
                return request

            snippets: List[str] = []
            for entry in results[: self._max_results]:
                title = entry.get("title", "")
                content = (entry.get("content") or "")[:300]
                if title or content:
                    snippets.append(f"[{title}]: {content}")

            if snippets:
                nexus_ctx = "\n\n[NEXUS KNOWLEDGE]\n" + "\n---\n".join(snippets)
                sys_msg = next(
                    (m for m in request["messages"] if m.get("role") == "system"),
                    None,
                )
                if sys_msg:
                    sys_msg["content"] = (sys_msg.get("content") or "") + nexus_ctx
                    logger.debug(
                        "NexusContextInjector: injected %d snippets", len(snippets)
                    )
        except Exception as exc:
            logger.debug("NexusContextInjector failed (non-fatal): %s", exc)

        return request

    def post_call(self, response: Dict[str, Any], context: Dict[str, Any]) -> Dict[str, Any]:
        """Pass response through unchanged.

        Args:
            response: Raw LLM response dict.
            context: Interceptor context (pass-through).

        Returns:
            Unmodified *response*.
        """
        return response
