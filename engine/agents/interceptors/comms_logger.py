"""Interceptor: CommsLoggerInterceptor.

Post-call interceptor (CB-T2) that feeds **every governed agent reply** into
the :class:`~engine.world.comms_log.GlobalCommsLog` — the single source of
truth for all communication in CosySim. It runs at priority 90, before the
SpectatorBroadcastInterceptor at 92, so the canonical log is written before
any downstream broadcast/observer fan-out.

De-dup contract (CB-T2)
-----------------------
* The **interceptor** logs all AGENT replies (NPC → user / NPC → NPC). Every
  NPC reply in the phone scene — direct DMs, autotexts, and group replies —
  flows through ``AgentGovernor.reply()`` and therefore through this
  interceptor exactly once.
* The **phone scene** logs only explicit USER sends (and non-agent system
  messages). It must NOT log NPC replies, or entries would be duplicated.

Thread / recipient resolution
-----------------------------
``ResponseContext`` (built inside ``AgentGovernor.reply``) does not natively
carry the phone ``thread_id`` or the addressed recipients. Callers that know
this context (the phone scene) publish it for the current call via
:func:`set_comms_context` / :func:`comms_context` immediately before invoking
the governor; this interceptor reads it back through a thread-local
:class:`contextvars.ContextVar`. When no context is published, recipients fall
back to ``['user']`` (player-facing reply) and ``thread_id`` is left ``None``.

Defensiveness
-------------
A comms-log failure must NEVER break the pipeline: every write is wrapped and
errors are surfaced via ``logger.error("[comms_logger] ... (operation=log)")``
in the Oracle log format, then swallowed.

Version: v1.62.0 [2026-06-15]
Author:  CosySim Team

Change Log:
    v1.62.0 [2026-06-15] — Initial CommsLoggerInterceptor (CB-T2): write every
                            governed agent reply into GlobalCommsLog; thread/
                            recipient context published by callers via a
                            ContextVar.

CONNECTS: AgentGovernor pipeline, engine.world.comms_log.get_comms_log
CALLED BY: InterceptorPipeline.run_post (priority 90)
EMITS: GlobalCommsLog entries (channel derived from scene, kind='message')
"""
from __future__ import annotations

import contextlib
import logging
from contextvars import ContextVar
from typing import Any, Dict, Iterator, List, Optional, Sequence

from engine.mcp.comms_framework import InterceptorBase, ResponseContext

logger = logging.getLogger(__name__)


# ══════════════════════════════════════════════════════════════════════
#  PER-CALL COMMS CONTEXT (published by callers, read by the interceptor)
# ══════════════════════════════════════════════════════════════════════

#: Per-call comms context. Keys: ``channel``, ``thread_id``, ``recipient_ids``,
#: ``sender_id``.
_COMMS_CONTEXT: ContextVar[Optional[Dict[str, Any]]] = ContextVar(
    "comms_logger_context", default=None
)


def set_comms_context(
    *,
    channel: Optional[str] = None,
    thread_id: Optional[str] = None,
    recipient_ids: Optional[Sequence[str]] = None,
    sender_id: Optional[str] = None,
) -> Any:
    """Publish comms context for the current call's governed reply.

    The phone scene calls this immediately before ``AgentGovernor.reply`` so
    the interceptor can align the logged ``thread_id``/recipients/channel with
    the originating phone thread.

    Args:
        channel: Logical channel override, e.g. ``'phone_dm'`` /
            ``'phone_group'``. When ``None`` the interceptor derives the
            channel from the scene.
        thread_id: The originating thread id, so ``comms_log.thread(thread_id)``
            lines up with the phone thread.
        recipient_ids: The addressed recipient ids. When ``None`` the
            interceptor falls back to ``['user']``.
        sender_id: The replying agent's id. Used as a fallback when
            ``ResponseContext['agent_id']`` is missing or ``'unknown'`` (the
            governor cannot derive a clean id for dict-backed phone agents).

    Returns:
        The :class:`contextvars.Token` for the set operation (pass to
        :meth:`ContextVar.reset`). Most callers prefer the :func:`comms_context`
        context manager instead.
    """
    payload: Dict[str, Any] = {}
    if channel is not None:
        payload["channel"] = channel
    if thread_id is not None:
        payload["thread_id"] = thread_id
    if recipient_ids is not None:
        payload["recipient_ids"] = list(recipient_ids)
    if sender_id is not None:
        payload["sender_id"] = sender_id
    return _COMMS_CONTEXT.set(payload or None)


@contextlib.contextmanager
def comms_context(
    *,
    channel: Optional[str] = None,
    thread_id: Optional[str] = None,
    recipient_ids: Optional[Sequence[str]] = None,
    sender_id: Optional[str] = None,
) -> Iterator[None]:
    """Scope comms context to a ``with`` block, resetting it on exit.

    Args:
        channel: Logical channel override (see :func:`set_comms_context`).
        thread_id: Originating thread id (see :func:`set_comms_context`).
        recipient_ids: Addressed recipient ids (see :func:`set_comms_context`).
        sender_id: Replying agent id fallback (see :func:`set_comms_context`).

    Yields:
        ``None`` — the context is active for the duration of the block.
    """
    token = set_comms_context(
        channel=channel, thread_id=thread_id,
        recipient_ids=recipient_ids, sender_id=sender_id,
    )
    try:
        yield
    finally:
        with contextlib.suppress(Exception):
            _COMMS_CONTEXT.reset(token)


# ══════════════════════════════════════════════════════════════════════
#  INTERCEPTOR
# ══════════════════════════════════════════════════════════════════════


class CommsLoggerInterceptor(InterceptorBase):
    """Write every governed agent reply into the :class:`GlobalCommsLog`.

    Runs post-call at priority 90 (before SpectatorBroadcast at 92). Maps the
    :class:`ResponseContext` onto a single ``get_comms_log().log(...)`` call:

    * ``channel``       — published channel, else derived from ``ctx['scene']``
      (``f"scene:{scene}"``, or ``'agent'`` when no scene).
    * ``sender_id``     — published ``sender_id``, else ``ctx['agent_id']`` (the
      governor yields ``'unknown'`` for dict-backed phone agents, so callers
      publish the real agent id).
    * ``recipient_ids`` — published recipients, else ``['user']``.
    * ``content``       — ``ctx['reply']``.
    * ``thread_id``     — published ``thread_id`` (aligns with the phone thread).
    * ``kind``          — ``'message'``.
    * ``mood``          — first mood tag if present.
    * ``metadata``      — ``{scene, response_id, agent_name}`` (best-effort).
    """

    name = "comms_logger"
    priority = 90  # before SpectatorBroadcastInterceptor (92)

    def post_call(self, ctx: ResponseContext) -> None:
        """Log the completed agent reply to the GlobalCommsLog.

        Args:
            ctx: The mutable interaction context after the LLM call.
        """
        reply = ctx.get("reply", "") or ""
        published = _COMMS_CONTEXT.get() or {}

        # The governor extracts agent_id via getattr() and yields 'unknown' for
        # dict-backed phone agents, so prefer a caller-published sender_id.
        ctx_agent_id = ctx.get("agent_id", "") or ""
        sender_id = published.get("sender_id") or ctx_agent_id
        if sender_id == "unknown":
            sender_id = published.get("sender_id") or sender_id
        if not sender_id or not reply.strip():
            return

        scene = ctx.get("scene", "") or ""
        channel = published.get("channel") or (f"scene:{scene}" if scene else "agent")
        recipient_ids = published.get("recipient_ids") or ["user"]
        thread_id = published.get("thread_id")

        mood = self._extract_mood(ctx)
        metadata: Dict[str, Any] = {
            "scene": scene or None,
            "response_id": ctx.get("response_id") or None,
            "agent_name": ctx.get("agent_name") or None,
        }

        try:
            from engine.world.comms_log import get_comms_log

            get_comms_log().log(
                channel,
                sender_id,
                recipient_ids,
                reply,
                thread_id=thread_id,
                kind="message",
                mood=mood,
                metadata=metadata,
            )
        except Exception as exc:  # never break the pipeline
            logger.error(
                "[comms_logger] comms-log write failed "
                "(operation=log, channel=%s, sender=%s, thread=%s): %s",
                channel, sender_id, thread_id, exc,
            )

    # ── helpers ────────────────────────────────────────────────────────

    @staticmethod
    def _extract_mood(ctx: ResponseContext) -> Optional[str]:
        """Return the first mood tag from the context, if any.

        Args:
            ctx: The interaction context.

        Returns:
            The first mood tag string, or ``None`` when no mood is present.
        """
        mood_tags = ctx.get("mood_tags")
        if isinstance(mood_tags, (list, tuple)) and mood_tags:
            first = mood_tags[0]
            return str(first) if first else None
        mood = ctx.get("mood")
        return str(mood) if mood else None
