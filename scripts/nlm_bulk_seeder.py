"""NLM Bulk Q&A Seeder — one API call instead of 60 browser round-trips.

Uses NLMDirectClient to make a single create_note() call with a structured
prompt asking Gemini to answer all questions as JSON. Then parses the response
and stores every Q&A pair in Nexus at once.

Also calls generate_flashcards() to harvest Gemini's own organic Q&A pairs
on top of the prompted ones.

Result: 60+ Q&A pairs in Nexus in ~60 seconds instead of ~20 minutes.

Usage:
    python scripts/nlm_bulk_seeder.py                              # full run
    python scripts/nlm_bulk_seeder.py --notebook-id <uuid>        # specific notebook
    python scripts/nlm_bulk_seeder.py --flashcards-only           # just flashcard harvest
    python scripts/nlm_bulk_seeder.py --dry-run                   # print prompt, no calls
    python scripts/nlm_bulk_seeder.py --list-notebooks            # list available notebooks
"""
from __future__ import annotations

import argparse
import json
import logging
import re
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional

PROJECT_ROOT = Path(__file__).parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger(__name__)

# ──── Notebook to target ─────────────────────────────────────────────────────

# Default: the PROJECT_JOURNAL notebook uploaded by nlm_ingest.py
DEFAULT_NOTEBOOK_ID = "e81e6364-ce39-401e-b7db-bb6bfd7970f7"

# ──── Bulk prompt ────────────────────────────────────────────────────────────

_BULK_PROMPT = """
You are producing a comprehensive knowledge base for the CosySim AI simulation framework.

Please answer ALL of the following questions using ONLY information from the notebook sources.
Return your response as a single valid JSON array. Each element must be an object with exactly
two string fields: "question" and "answer". Answers should be detailed (3-10 sentences each).
Do not include any text outside the JSON array — just the raw JSON starting with [ and ending with ].

Questions:

1. What is CosySim and what is its core purpose?
2. How does the MCPFramework work and what is its role as the root singleton?
3. What are the main components of the CosySim engine and how do they relate?
4. How does the InterceptorPipeline work and when does it execute?
5. What is the MCPSceneNode and how does per-scene state work?
6. What is the MCPCharacterNode and what state does it hold?
7. How does the EventChain audit logging system work?
8. What is the AgentGovernor and how does it enforce governance on agent calls?
9. How does the SceneStateManager differ from the MCPFramework tree?
10. What is the DialogSystem and how does it thread conversations?
11. How do you create a new CosySim scene from scratch?
12. What is the BaseScene class and what methods must every scene override?
13. How does the @skill decorator work and what parameters does it accept?
14. What are skill packs and how are they organised?
15. How does skill discovery work so agents can find available tools?
16. What is the StreamProcessor and what tags does it extract from LLM output?
17. How does infer_processed() work and what does it return?
18. What is the SCENE_METADATA dict and what does each field mean?
19. How does character lifecycle work (on_character_added/removed)?
20. What are the 18 active scenes in CosySim and what is each one's purpose?
21. How does LMStudio integrate with CosySim via the v1 API?
22. What is the InferenceOrchestrator and how does it route requests between models?
23. How does stateful conversation threading work with store:true and previous_response_id?
24. What are the model profiles (big, small, router, draft) and when is each used?
25. How does SSE streaming work in the LMStudio v1 API?
26. What is the AgentRouter and how does it classify requests?
27. How does the VirtualAgent work and what is its reply() method flow?
28. What is the RouterDataCollector and what data does it capture?
29. How does speculative decoding work with draft models in the pipeline?
30. What configuration keys control the LMStudio integration?
31. What is Nexus and what are its three database layers (Hot/Warm/Deep)?
32. How does the Nexus Q&A cache work as the first lookup tier?
33. What is the NLM-first pipeline and how do its 4 tiers work?
34. How does nexus_smart_query() work and what is its fallback chain?
35. What content types are stored in Nexus and when should each be used?
36. How does the Nexus governance rules engine work?
37. What is the NexusPromptInterceptor and what does it inject?
38. How does the scheduler daemon interact with Nexus?
39. What are the 52 built-in scheduler tasks and how are they categorised?
40. How does the knowledge flywheel create a self-improving loop?
41. How does ARGUS work and what Google APIs has it mapped?
42. What is the GAS SDK and what are its key rpcids?
43. How does the HAR replay system work?
44. What is the V8 heap analyzer and how does it confirm rpcid mappings?
45. How does the CDP bridge work and what Chrome internals can it access?
46. What is the artifact bus and how do Google services hand off artifacts?
47. How does the Colab integration work (colab_gpu_manager, colab_venv_manager)?
48. How does the GSheets client work and what operations does it support?
49. What is the NLM direct client and how does it bypass browser automation?
50. How does generate_flashcards() work and what does it return?
51. What is the training flywheel and what data does the DataCollector capture?
52. How does the Model Zoo work and what model types does it contain?
53. What is the CoderPipeline and what LoRA configuration does it use?
54. How does the router fine-tune cycle work?
55. What is the GrammarScannerInterceptor and how does it validate LLM output?
56. What is the OutputEvaluator and how does it score responses?
57. How does the TTS system work (Piper, Orpheus, Qwen3 voice options)?
58. What is the WorldSim daemon and what autonomous events does it generate?
59. How does the WorldAnnouncer broadcast events across all 18 scenes?
60. What is the Universal HUD and what state does it display?

Return ONLY the JSON array. Start your response with [ and end with ].
"""


# ──── Nexus helpers ──────────────────────────────────────────────────────────

def _store_qa_pairs(pairs: List[Dict[str, str]], source: str = "nlm_bulk") -> int:
    """Store Q&A pairs in Nexus. Returns count stored."""
    try:
        from engine.nexus.client import get_nexus_client
        client = get_nexus_client()
        stored = 0
        for pair in pairs:
            q = pair.get("question", "").strip()
            a = pair.get("answer", "").strip()
            if q and a and len(a) > 30:
                client.add_qa(q, a, category="cosysim_knowledge")
                stored += 1
        logger.info("[nexus] Stored %d/%d Q&A pairs (source: %s)", stored, len(pairs), source)
        return stored
    except Exception as exc:
        logger.warning("[nexus] Store failed: %s", exc)
        return 0


# ──── JSON extraction ────────────────────────────────────────────────────────

def _extract_json_pairs(content: str) -> List[Dict[str, str]]:
    """Extract Q&A pairs from NLM create_note response.

    Tries strict JSON parse first, then falls back to regex extraction
    for partial/malformed responses.
    """
    content = content.strip()

    # Strip markdown code fences if present
    content = re.sub(r"^```(?:json)?\s*", "", content)
    content = re.sub(r"\s*```$", "", content)

    # Attempt 1: full parse
    try:
        data = json.loads(content)
        if isinstance(data, list):
            return [d for d in data if isinstance(d, dict) and "question" in d and "answer" in d]
    except json.JSONDecodeError:
        pass

    # Attempt 2: extract the JSON array portion
    match = re.search(r"\[.*\]", content, re.DOTALL)
    if match:
        try:
            data = json.loads(match.group())
            if isinstance(data, list):
                return [d for d in data if isinstance(d, dict) and "question" in d and "answer" in d]
        except json.JSONDecodeError:
            pass

    # Attempt 3: regex-extract individual objects
    pairs: List[Dict[str, str]] = []
    pattern = r'\{\s*"question"\s*:\s*"((?:[^"\\]|\\.)*)"\s*,\s*"answer"\s*:\s*"((?:[^"\\]|\\.)*)"\s*\}'
    for m in re.finditer(pattern, content, re.DOTALL):
        pairs.append({"question": m.group(1), "answer": m.group(2)})

    return pairs


# ──── Core runners ───────────────────────────────────────────────────────────

def run_create_note_seeder(client: Any, notebook_id: str, dry_run: bool = False) -> List[Dict[str, str]]:
    """Ask Gemini to answer all 60 questions in one create_note() call.

    Returns list of extracted Q&A pairs.
    """
    if dry_run:
        print("=" * 70)
        print("DRY RUN — would call create_note() with this prompt:")
        print(_BULK_PROMPT[:500] + "...")
        print(f"  (total prompt: {len(_BULK_PROMPT)} chars, 60 questions)")
        return []

    print(f"\n  → create_note() on notebook {notebook_id}")
    print(f"  → Prompt: {len(_BULK_PROMPT)} chars, 60 questions")
    print(f"  → Gemini will answer all questions in one shot...\n")

    try:
        result = client.create_note(notebook_id, _BULK_PROMPT)
    except Exception as exc:
        logger.error("create_note failed: %s", exc)
        return []

    content = result.get("content", "")
    note_id = result.get("id", "unknown")
    logger.info("create_note returned %d chars (artifact id: %s)", len(content), note_id)

    if not content:
        logger.warning("Empty content from create_note — notebook may have no sources yet")
        return []

    pairs = _extract_json_pairs(content)
    logger.info("Extracted %d Q&A pairs from create_note response", len(pairs))

    if not pairs:
        # Save raw response for debugging
        debug_path = PROJECT_ROOT / "data" / "argus" / "bulk_seeder_raw.txt"
        debug_path.parent.mkdir(parents=True, exist_ok=True)
        debug_path.write_text(content, encoding="utf-8")
        logger.warning("JSON extraction failed. Raw response saved to %s", debug_path)

    return pairs


def run_flashcard_seeder(client: Any, notebook_id: str, source_ids: Optional[List[str]] = None) -> List[Dict[str, str]]:
    """Use generate_flashcards() to get Gemini's organic Q&A pairs.

    These are different from the prompted Q&A — Gemini decides what
    the most important concepts are and formulates its own questions.
    """
    print(f"\n  → generate_flashcards() on notebook {notebook_id}")
    try:
        cards = client.generate_flashcards(notebook_id, source_ids=source_ids)
        logger.info("generate_flashcards returned %d cards", len(cards))
        return cards
    except Exception as exc:
        logger.error("generate_flashcards failed: %s", exc)
        return []


# ──── CLI ────────────────────────────────────────────────────────────────────

def main() -> None:
    p = argparse.ArgumentParser(
        description="Bulk-seed Nexus Q&A from NLM in one API call",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    p.add_argument("--notebook-id",     default=DEFAULT_NOTEBOOK_ID, help="NLM notebook UUID")
    p.add_argument("--flashcards-only", action="store_true",          help="Only run flashcard harvest (no create_note)")
    p.add_argument("--note-only",       action="store_true",          help="Only run create_note (no flashcards)")
    p.add_argument("--dry-run",         action="store_true",          help="Print prompt without making API calls")
    p.add_argument("--list-notebooks",  action="store_true",          help="List notebooks and exit")
    p.add_argument("--account",         default=None,                 help="Account name (default: round-robin)")
    args = p.parse_args()

    from engine.integrations.nlm_direct_client import get_nlm_direct_client
    client = get_nlm_direct_client(args.account)
    if client is None:
        print("ERROR: No NLM account available.")
        print("Import one with: python -m engine.integrations.google_account_importer")
        sys.exit(1)

    if args.list_notebooks:
        notebooks = client.list_notebooks()
        print(f"\n{'═'*70}")
        print(f"  {len(notebooks)} notebooks found")
        print(f"{'═'*70}")
        for nb in notebooks:
            print(f"  {nb.get('id', '?'):40s}  {nb.get('title', '?')}")
        return

    print(f"\n{'═'*70}")
    print(f"  NLM Bulk Q&A Seeder")
    print(f"  Notebook : {args.notebook_id}")
    print(f"  Mode     : {'dry-run' if args.dry_run else 'flashcards-only' if args.flashcards_only else 'note-only' if args.note_only else 'full (note + flashcards)'}")
    print(f"{'═'*70}\n")

    total_stored = 0

    # ── Phase 1: create_note bulk Q&A ────────────────────────────────────────
    if not args.flashcards_only:
        pairs = run_create_note_seeder(client, args.notebook_id, dry_run=args.dry_run)
        if pairs:
            print(f"  ✓ Extracted {len(pairs)} Q&A pairs from create_note")
            stored = _store_qa_pairs(pairs, source="nlm_create_note")
            total_stored += stored
            print(f"  ✓ Stored {stored} pairs in Nexus\n")
        elif not args.dry_run:
            print("  ✗ No pairs extracted from create_note\n")

    # ── Phase 2: generate_flashcards organic Q&A ─────────────────────────────
    if not args.note_only and not args.dry_run:
        cards = run_flashcard_seeder(client, args.notebook_id)
        if cards:
            print(f"  ✓ generate_flashcards returned {len(cards)} cards")
            stored = _store_qa_pairs(cards, source="nlm_flashcards")
            total_stored += stored
            print(f"  ✓ Stored {stored} flashcard pairs in Nexus\n")

    print(f"{'═'*70}")
    print(f"  Total stored in Nexus: {total_stored} Q&A pairs")
    print(f"{'═'*70}\n")


if __name__ == "__main__":
    main()
