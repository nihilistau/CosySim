import re

with open("engine/mcp/cosysim_server.py", "r", encoding="utf-8") as f:
    content = f.read()

# Add imports for memory_recall_impl and time_echo_impl
import_pattern = r"from engine\.mcp\.tools\.memory_tools import \("
if "memory_recall as memory_recall_impl" not in content:
    content = re.sub(
        import_pattern,
        "from engine.mcp.tools.memory_tools import (\n    memory_recall as memory_recall_impl,\n    time_echo as time_echo_impl,",
        content,
    )

# Replace memory_recall
old_mr = '''@mcp.tool()
def memory_recall(
    character_id: str,
    query: str,
    context_limit: int = 5,
    scene_id: str = "",
) -> str:
    """
    **MEMORY SKILL** — Retrieve the character's most relevant memories for a query.

    This is the memory skill entry point.  It layers:
    1. RAG search of long-term memory (ChromaDB)
    2. Recent scene narrative (short-term)
    3. A formatted "You remember:" hook ready for system prompt injection

    Use this at the start of every response to ground the character in their
    history and ensure continuity.

    Args:
        character_id:  The character doing the remembering
        query:         What to search for — use the current topic/context
        context_limit: Max memory snippets to return
        scene_id:      Current scene (pulls recent narrative)
    """
    try:
        results: Dict[str, Any] = {}

        # Long-term memory (RAG)
        try:
            rag = _get_rag()
            if rag:
                raw = rag.search(query, character_id=character_id, top_k=context_limit)
                if isinstance(raw, list):
                    results["long_term"] = [
                        r.get("text", r) if isinstance(r, dict) else str(r)
                        for r in raw[:context_limit]
                    ]
                else:
                    results["long_term"] = []
            else:
                results["long_term"] = []
        except Exception:
            results["long_term"] = []

        # Short-term narrative
        try:

            ssm = get_scene_state_manager()
            entries = ssm.get_narrative_entries(scene_id or "bedroom", limit=4)
            results["recent"] = [e.get("event", "") for e in entries if e.get("event")]
        except Exception:
            results["recent"] = []

        # Build the memory hook
        try:

            name = character_id
            try:

                rec = get_character_registry().get_record(character_id)
                if rec:
                    name = rec.profile.name
            except Exception:
                logger.debug("Suppressed exception", exc_info=True)
            all_memories = results["long_term"] + results["recent"]
            hook = get_dialog_system().build_memory_hook(all_memories, name)
            results["memory_hook"] = hook
        except Exception:
            results["memory_hook"] = ""

        results["character_id"] = character_id
        results["query"] = query
        return json.dumps(results, indent=2)
    except Exception as exc:
        return json.dumps({"error": str(exc)})'''

new_mr = '''@mcp.tool()
def memory_recall(
    character_id: str,
    query: str,
    context_limit: int = 5,
    scene_id: str = "",
) -> str:
    """
    **MEMORY SKILL** — Retrieve the character's most relevant memories for a query.

    This is the memory skill entry point.  It layers:
    1. RAG search of long-term memory (ChromaDB)
    2. Recent scene narrative (short-term)
    3. A formatted "You remember:" hook ready for system prompt injection

    Use this at the start of every response to ground the character in their
    history and ensure continuity.

    Args:
        character_id:  The character doing the remembering
        query:         What to search for — use the current topic/context
        context_limit: Max memory snippets to return
        scene_id:      Current scene (pulls recent narrative)
    """
    return memory_recall_impl(
        character_id,
        query,
        _get_rag(),
        get_scene_state_manager(),
        get_dialog_system(),
        get_character_registry(),
        context_limit=context_limit,
        scene_id=scene_id,
    )'''
content = content.replace(old_mr, new_mr)

# Replace time_echo
old_te = '''@mcp.tool()
def time_echo(
    character_id: str,
    echo_query: str,
    emotional_tone: str = "nostalgic",
    scene_id: str = "",
) -> str:
    """
    Pull a specific memory forward into this moment with full emotional resonance.

    Time Echo digs through the character's memory for something matching
    *echo_query*, then injects it into their current response as a vivid,
    felt flashback — not recited, but *experienced in the present tense*.

    The effect: the character suddenly, mid-conversation, partially inhabits
    a past moment.  A phrase they used, a sensation, the exact tone of a
    laugh.  It feels to both of them like déjà vu made real.

    Use this to:
    • Create surprisingly intimate callbacks to shared history
    • Turn a quiet moment into something unexpectedly resonant
    • Recover a character's distinct voice when it has drifted
    • Build cumulative emotional depth over many conversations

    Args:
        character_id:   Who is doing the echoing   (e.g. "aria")
        echo_query:     What memory to surface  (e.g. "the first time we stayed up all night talking",
                        "the joke about the broken umbrella")
        emotional_tone: How the echo is felt  —  nostalgic / warm / aching /
                        amused / bittersweet / excited
        scene_id:       Current scene
    """
    try:

        ds = get_dialog_system()
        ssm = get_scene_state_manager()
        fw = get_framework()

        # Attempt RAG memory search
        memory_fragment = None
        try:
            from content.simulation.database.rag import RAGMemory

            rag = RAGMemory()
            results = rag.search(echo_query, n_results=3, character_id=character_id)
            if results:
                best = results[0]
                memory_fragment = (best.get("content") or str(best))[:200]
        except Exception:
            logger.debug("Suppressed exception", exc_info=True)

        # Build the echoed fragment
        if memory_fragment:
            echo_text = (
                f"[{emotional_tone.upper()} ECHO — drawn from memory] "
                f'"{memory_fragment}" — this surfaces now, vivid and unbidden.'
            )
        else:
            echo_text = (
                f"[{emotional_tone.upper()} ECHO — a felt memory, no exact words] "
                f"Something about '{echo_query}' rises up — not a thought, but a feeling."
                f" The specific gravity of something real."
            )

        # Set as a must_include directive — the character HAS to honour it this turn
        target_scene = (
            scene_id or fw.get_character(character_id).current_scene or "phone"
        )
        ds.set_directive(
            character_id=character_id,
            scene_id=target_scene,
            directive_type="must_include",
            value=echo_text,
            turns=1,
            issued_by="time_echo_skill",
        )

        # Stat effect based on emotional tone
        tone_effects = {
            "nostalgic": {"happiness": 8, "affection": 12, "arousal": 0},
            "warm": {"happiness": 12, "affection": 10, "arousal": 3},
            "aching": {"happiness": -5, "affection": 15, "arousal": 5},
            "amused": {"happiness": 15, "affection": 8, "arousal": 2},
            "bittersweet": {"happiness": 3, "affection": 12, "arousal": 4},
            "excited": {"happiness": 10, "affection": 8, "arousal": 15},
        }
        effects = tone_effects.get(emotional_tone, {"happiness": 5, "affection": 8})
        ssm.update_stats(character_id, **effects)

        ssm.add_narrative(
            target_scene,
            f"[{character_id} experiences a {emotional_tone} Time Echo.]",
            entry_type="system",
            character_id=character_id,
        )

        return json.dumps(
            {
                "ok": True,
                "character_id": character_id,
                "echo_text": echo_text,
                "applied_effects": effects,
            },
            indent=2,
        )

    except Exception as exc:
        return json.dumps({"ok": False, "error": str(exc)})'''

new_te = '''@mcp.tool()
def time_echo(
    character_id: str,
    echo_query: str,
    emotional_tone: str = "nostalgic",
    scene_id: str = "",
) -> str:
    """
    Pull a specific memory forward into this moment with full emotional resonance.

    Time Echo digs through the character's memory for something matching
    *echo_query*, then injects it into their current response as a vivid,
    felt flashback — not recited, but *experienced in the present tense*.

    The effect: the character suddenly, mid-conversation, partially inhabits
    a past moment.  A phrase they used, a sensation, the exact tone of a
    laugh.  It feels to both of them like déjà vu made real.

    Use this to:
    • Create surprisingly intimate callbacks to shared history
    • Turn a quiet moment into something unexpectedly resonant
    • Recover a character's distinct voice when it has drifted
    • Build cumulative emotional depth over many conversations

    Args:
        character_id:   Who is doing the echoing   (e.g. "aria")
        echo_query:     What memory to surface  (e.g. "the first time we stayed up all night talking",
                        "the joke about the broken umbrella")
        emotional_tone: How the echo is felt  —  nostalgic / warm / aching /
                        amused / bittersweet / excited
        scene_id:       Current scene
    """
    try:
        from content.simulation.database.rag import RAGMemory
        rag = RAGMemory()
    except Exception:
        rag = None
        
    return time_echo_impl(
        character_id,
        echo_query,
        rag,
        get_dialog_system(),
        get_scene_state_manager(),
        get_framework(),
        emotional_tone=emotional_tone,
        scene_id=scene_id,
    )'''
content = content.replace(old_te, new_te)

with open("engine/mcp/cosysim_server.py", "w", encoding="utf-8") as f:
    f.write(content)
print("Updated memory_recall and time_echo")
