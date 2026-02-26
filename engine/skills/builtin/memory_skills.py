"""
memory_skills.py — Memory query, storage, and chain summarization skills

These skills give the LLM direct access to:
- Long-term memory via ChromaDB RAG (search + store)
- The EventChain diagnostics tree (retrieve + summarize for memory compaction)
- Conversation history summarization (compacts old messages into a single memory)
"""
from __future__ import annotations

from engine.skills.skill import skill
import logging

logger = logging.getLogger(__name__)


@skill(
    pack="memory",
    description=(
        "Search long-term memory for information relevant to a query. "
        "Returns the top matching memories as a formatted string."
    ),
    tags=["memory", "rag", "search"],
)
def search_memory(
    query: str,
    character_id: str = "",
    top_k: int = 5,
) -> str:
    """
    Search the long-term vector memory store for relevant memories.

    Args:
        query:        Natural language query to search for.
        character_id: Filter memories by character (empty = all characters).
        top_k:        Number of top results to return (1–20).

    Returns:
        Formatted string of matching memories, or a message if none found.
    """
    try:
        from content.simulation.database.rag import RAGMemory
        from engine.skills.chain_context import get_chain_context

        ctx     = get_chain_context()
        rag     = RAGMemory()
        top_k   = max(1, min(top_k, 20))
        results = rag.query_memories(
            character_id=character_id or ctx.get("character_id") or "global",
            query=query,
            n_results=top_k,
            chain_id=ctx.get("chain_id"),
            scene_id=ctx.get("scene_id", "unknown"),
        )

        if not results:
            return "No relevant memories found."

        lines = [f"Memory {i+1}: {r.get('content', r)}" for i, r in enumerate(results)]
        return "\n".join(lines)

    except Exception as exc:
        return f"Memory search failed: {exc}"


@skill(
    pack="memory",
    description=(
        "Store a new memory or important fact in long-term memory. "
        "Use this to remember key information from the conversation."
    ),
    tags=["memory", "rag", "store"],
)
def store_memory(
    content: str,
    character_id: str = "",
    importance: float = 0.7,
    memory_type: str = "fact",
) -> str:
    """
    Store a piece of information in long-term vector memory.

    Args:
        content:      The information to remember.
        character_id: Associate this memory with a character ID (optional).
        importance:   Importance score 0.0–1.0 (higher = more likely to be recalled).
        memory_type:  Category: "fact", "event", "preference", "emotion".

    Returns:
        Confirmation string or error message.
    """
    try:
        from content.simulation.database.rag import RAGMemory
        from engine.skills.chain_context import get_chain_context

        ctx = get_chain_context()
        rag = RAGMemory()
        rag.add_memory(
            character_id=character_id or ctx.get("character_id") or "global",
            content=content,
            memory_type=memory_type,
            importance=float(importance),
            chain_id=ctx.get("chain_id"),
            scene_id=ctx.get("scene_id", "unknown"),
        )
        return f"Memory stored successfully (importance={importance:.1f})."

    except Exception as exc:
        return f"Failed to store memory: {exc}"


@skill(
    pack="memory",
    description=(
        "Retrieve and summarize an event chain by its chain ID. "
        "Useful for understanding what happened during a past interaction."
    ),
    tags=["memory", "events", "diagnostics"],
)
def get_event_chain_summary(chain_id: str) -> str:
    """
    Return a human-readable summary of an event chain.

    The event chain records every step of a LLM interaction: the user message,
    RAG queries, LLM calls, tool calls, and the final response.

    Args:
        chain_id: UUID of the event chain to summarize.

    Returns:
        Formatted text summary of the chain (newest events at bottom).
    """
    try:
        from content.simulation.database.events import get_event_chain

        ec     = get_event_chain()
        events = ec.get_chain(chain_id)

        if not events:
            return f"No events found for chain {chain_id}."

        lines = [f"Event chain: {chain_id}", f"Total events: {len(events)}", ""]
        for ev in events:
            ts   = (ev.get("timestamp") or "")[:19]
            etype = ev.get("event_type", "?")
            actor = ev.get("actor", "")
            summ  = ev.get("summary") or ""
            lines.append(f"[{ts}] {etype} ({actor}): {summ}")

        return "\n".join(lines)

    except Exception as exc:
        return f"Failed to retrieve event chain: {exc}"


@skill(
    pack="memory",
    description=(
        "Summarize and compress an event chain into a single memory entry. "
        "This compacts old interaction details to free context space."
    ),
    tags=["memory", "events", "compaction"],
)
def summarize_chain(
    chain_id: str,
    character_id: str = "",
    store_result: bool = True,
) -> str:
    """
    Summarize an event chain into a compact memory entry.

    This is the **memory compaction** operation: it reads all events in the
    chain, produces a one-paragraph summary, and optionally stores it in
    long-term memory so future interactions can recall it without replaying
    the full chain.

    Args:
        chain_id:     UUID of the event chain to summarize.
        character_id: Associate the resulting memory with this character.
        store_result: If True, automatically stores the summary in RAG memory.

    Returns:
        The produced summary text, or an error message.
    """
    try:
        from content.simulation.database.events import get_event_chain

        ec     = get_event_chain()
        events = ec.get_chain(chain_id)

        if not events:
            return f"No events found for chain {chain_id} — nothing to summarize."

        # Build a compact representation for the LLM to summarize
        lines = []
        for ev in events:
            etype  = ev.get("event_type", "?")
            actor  = ev.get("actor", "")
            summary = ev.get("summary") or ""
            if summary:
                lines.append(f"{etype} ({actor}): {summary}")

        chain_text = "\n".join(lines)

        # Use the LLM to produce the summary
        try:
            import lmstudio as lms
            llm     = lms.llm()
            prompt  = (
                "Summarise the following AI interaction log into a single concise paragraph "
                "suitable for storing as a long-term memory.  Focus on key facts, decisions, "
                "and outcomes.  Be factual, third-person, under 150 words.\n\n"
                f"{chain_text}"
            )
            summary_text = str(llm.complete(prompt)).strip()
        except Exception:
            # Fallback: just join the summaries
            summary_text = " | ".join(lines[:8])

        if store_result:
            from content.simulation.database.rag import RAGMemory
            from engine.skills.chain_context import get_chain_context
            ctx = get_chain_context()
            rag = RAGMemory()
            rag.add_memory(
                character_id=character_id or ctx.get("character_id") or "global",
                content=summary_text,
                memory_type="chain_summary",
                importance=0.8,
                metadata={"chain_id": chain_id},
                chain_id=ctx.get("chain_id"),
                scene_id=ctx.get("scene_id", "unknown"),
            )

            # Log memory_compacted event
            try:
                from content.simulation.database.events import EventChain as EC
                ec2 = EC()
                if ctx.get("chain_id"):
                    ec2.log(
                        'memory_stored', actor='skill:summarize_chain',
                        payload={'compacted_chain': chain_id,
                                 'summary': summary_text[:200]},
                        summary=f'Chain {chain_id[:8]} compacted to memory',
                        chain_id=ctx.get("chain_id"),
                        scene_id=ctx.get("scene_id", "unknown"),
                        character_id=character_id or ctx.get("character_id"),
                    )
            except Exception:
                logger.debug("Suppressed exception", exc_info=True)

            return f"Chain summarized and stored in long-term memory:\n\n{summary_text}"

        return f"Chain summary (not stored):\n\n{summary_text}"

    except Exception as exc:
        return f"Failed to summarize chain {chain_id}: {exc}"
