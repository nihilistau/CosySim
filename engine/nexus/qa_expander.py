"""QA Expander — reverse-generates Q&A pairs from every Nexus knowledge entry.

For each Nexus entry, asks NLM:
  "What 5 questions does this knowledge entry answer?"

Each generated pair is stored back in Nexus as a cached Q&A item, dramatically
increasing the cache hit rate for the 4-tier query router. Designed to compound:
the more entries in Nexus, the more Q&A pairs generated, the faster future
queries are answered without LLM compute.

Architecture:
  - Runs daily via scheduler callback ``_qa_expander_callback``
  - Processes entries in batches (configurable, default 20 per run)
  - Tracks progress via state file — resumes on next run
  - Skips entries already expanded (hash-based dedup)
  - Works for ALL content types: document, note, code, research, history

Target: 3,000+ Q&A pairs total (currently ~217).

Usage::

    python -m engine.nexus.qa_expander                   # expand next batch
    python -m engine.nexus.qa_expander --batch-size 50   # larger batch
    python -m engine.nexus.qa_expander --reset            # restart from scratch
    python -m engine.nexus.qa_expander --dry-run          # show what would run
    python -m engine.nexus.qa_expander --stats            # show progress stats
"""
from __future__ import annotations

import argparse
import hashlib
import json
import logging
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

# ── Constants ─────────────────────────────────────────────────────────────────

_ROOT = Path(__file__).resolve().parent.parent.parent
_STATE_FILE = _ROOT / ".github" / "hooks" / "logs" / "qa_expander_state.json"

# How many questions to generate per entry
_QUESTIONS_PER_ENTRY = 5

# Minimum entry content length to bother expanding
_MIN_CONTENT_LEN = 80

# Content types to skip (too short / meta / already Q&A)
_SKIP_TYPES = {"qa", "prompt", "transcript"}

# Prompt template — sent to NLM
_PROMPT_TEMPLATE = (
    "Read this knowledge entry carefully and generate exactly {n} distinct questions "
    "that this content directly answers. Return ONLY a numbered list of questions, "
    "one per line. Questions should be clear, specific, and useful to a developer "
    "working on an AI simulation framework.\n\n"
    "KNOWLEDGE ENTRY:\nTitle: {title}\nType: {content_type}\n\n{content}"
)

# ── State helpers ─────────────────────────────────────────────────────────────

def _load_state() -> Dict[str, Any]:
    """Load persistent expander state."""
    try:
        if _STATE_FILE.exists():
            return json.loads(_STATE_FILE.read_text(encoding="utf-8"))
    except Exception:
        pass
    return {"expanded_hashes": [], "total_generated": 0, "last_run": None, "runs": 0}


def _save_state(state: Dict[str, Any]) -> None:
    """Persist expander state."""
    try:
        _STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
        _STATE_FILE.write_text(json.dumps(state, indent=2, default=str), encoding="utf-8")
    except Exception as exc:
        logger.warning("Could not save QA expander state: %s", exc)


def _entry_hash(entry: Dict[str, Any]) -> str:
    """Stable hash for a Nexus entry (title + first 200 chars of content)."""
    key = f"{entry.get('title', '')}:{entry.get('content', '')[:200]}"
    return hashlib.sha1(key.encode()).hexdigest()[:12]


# ── NLM helpers ───────────────────────────────────────────────────────────────

def _get_hybrid() -> Any:
    """Lazy-load NLM hybrid router."""
    from engine.mcp.nlm_hybrid import get_nlm_hybrid
    return get_nlm_hybrid()


def _get_nexus() -> Any:
    """Lazy-load Nexus client."""
    from engine.nexus.client import get_nexus_client
    return get_nexus_client()


# ── Question parsing ──────────────────────────────────────────────────────────

def _parse_questions(raw: str) -> List[str]:
    """Extract numbered questions from NLM response text.

    Handles:
      - ``1. Question text?``
      - ``1) Question text?``
      - plain lines starting with digits
    """
    questions: List[str] = []
    for line in raw.splitlines():
        line = line.strip()
        if not line:
            continue
        # Strip leading number + punctuation
        for sep in (". ", ") ", ": "):
            if len(line) > 2 and line[0].isdigit() and sep in line[:4]:
                _, _, rest = line.partition(sep)
                line = rest.strip()
                break
        if len(line) > 7 and "?" in line:
            questions.append(line)
    return questions[:_QUESTIONS_PER_ENTRY]


# ── Core expander ─────────────────────────────────────────────────────────────

class QAExpander:
    """Reverse-generates Q&A pairs from Nexus knowledge entries."""

    def __init__(self, dry_run: bool = False, notebook_id: str = "") -> None:
        self.dry_run = dry_run
        self.notebook_id = notebook_id
        self._state = _load_state()
        self._nexus: Optional[Any] = None
        self._hybrid: Optional[Any] = None

    def _client(self) -> Any:
        if self._nexus is None:
            self._nexus = _get_nexus()
        return self._nexus

    def _nlm(self) -> Any:
        if self._hybrid is None:
            self._hybrid = _get_hybrid()
        return self._hybrid

    def _get_or_find_notebook(self) -> str:
        """Return the expansion notebook ID, creating one if needed."""
        if self.notebook_id:
            return self.notebook_id
        stored = self._state.get("notebook_id", "")
        if stored:
            return stored
        if self.dry_run:
            return "dry-run-nb"
        # Create a dedicated expansion notebook
        nlm = self._nlm()
        result = nlm.create_notebook("CosySim QA Expansion Workspace")
        nb_id = result.get("notebook_id", result.get("id", ""))
        if not nb_id:
            raise RuntimeError(f"Could not create expansion notebook: {result}")
        self._state["notebook_id"] = nb_id
        _save_state(self._state)
        logger.info("Created QA expansion notebook: %s", nb_id)
        return nb_id

    def _fetch_unexpanded_entries(self, limit: int) -> List[Dict[str, Any]]:
        """Fetch Nexus entries that haven't been expanded yet."""
        nexus = self._client()
        already_done: set = set(self._state.get("expanded_hashes", []))

        # Fetch a broad set of entries — we'll filter locally
        all_entries: List[Dict[str, Any]] = []
        try:
            # Try paginated listing first
            results = nexus.list_entries(limit=500)
            if isinstance(results, list):
                all_entries = results
            elif isinstance(results, dict):
                all_entries = results.get("entries", results.get("items", []))
        except AttributeError:
            # Fall back to broad search if list_entries not available
            for term in ["architecture", "skill", "mcp", "nexus", "scene", "config",
                         "test", "agent", "lmstudio", "interceptor", "dialog"]:
                try:
                    results = nexus.search(term, limit=50)
                    all_entries.extend(results if isinstance(results, list) else [])
                except Exception:
                    pass
            # Deduplicate by ID
            seen: set = set()
            deduped: List[Dict[str, Any]] = []
            for e in all_entries:
                eid = e.get("id", e.get("title", ""))
                if eid not in seen:
                    seen.add(eid)
                    deduped.append(e)
            all_entries = deduped

        # Filter: skip already-expanded, skip short/meta types
        candidates: List[Dict[str, Any]] = []
        for entry in all_entries:
            content = entry.get("content", "")
            content_type = entry.get("content_type", "note")
            if content_type in _SKIP_TYPES:
                continue
            if len(content) < _MIN_CONTENT_LEN:
                continue
            eh = _entry_hash(entry)
            if eh in already_done:
                continue
            candidates.append(entry)
            if len(candidates) >= limit:
                break

        logger.info("Found %d unexpanded entries (of %d total)", len(candidates), len(all_entries))
        return candidates

    def _expand_entry(self, entry: Dict[str, Any], notebook_id: str) -> List[str]:
        """Ask NLM to generate questions for a single entry.

        Returns list of question strings.
        """
        title = entry.get("title", "untitled")
        content = entry.get("content", "")[:2000]  # cap per-entry context
        content_type = entry.get("content_type", "note")

        prompt = _PROMPT_TEMPLATE.format(
            n=_QUESTIONS_PER_ENTRY,
            title=title,
            content_type=content_type,
            content=content,
        )

        try:
            nlm = self._nlm()
            result = nlm.ask(notebook_id, prompt, session_id=f"qa-expand-{_entry_hash(entry)}")
            raw_answer = result.get("answer", "") if isinstance(result, dict) else str(result)
            questions = _parse_questions(raw_answer)
            logger.debug("Entry '%s': generated %d questions", title[:50], len(questions))
            return questions
        except Exception as exc:
            logger.warning("NLM expand failed for '%s': %s", title[:50], exc)
            return []

    def _store_pairs(
        self,
        entry: Dict[str, Any],
        questions: List[str],
        nexus: Any,
    ) -> int:
        """Store each question + the original content as a Q&A pair in Nexus.

        Returns count stored.
        """
        content = entry.get("content", "")
        title = entry.get("title", "untitled")
        category = entry.get("category", "knowledge")
        stored = 0

        for question in questions:
            # Answer is the original entry content (truncated if long)
            answer = content[:1500]
            if len(content) > 1500:
                answer += f"\n\n[Source: '{title}' — see full entry for details]"
            try:
                nexus.add_qa(
                    question=question,
                    answer=answer,
                    category=f"expanded-{category}",
                )
                stored += 1
            except Exception as exc:
                logger.debug("Could not store Q&A pair: %s", exc)
        return stored

    def run(self, batch_size: int = 20) -> Dict[str, Any]:
        """Expand one batch of Nexus entries into Q&A pairs.

        Args:
            batch_size: How many entries to process in this run.

        Returns:
            Summary dict: entries_processed, pairs_generated, pairs_stored, total_generated.
        """
        logger.info("QA Expander starting (batch_size=%d, dry_run=%s)", batch_size, self.dry_run)

        entries = self._fetch_unexpanded_entries(limit=batch_size)
        if not entries:
            logger.info("No unexpanded entries found — all done!")
            return {
                "status": "complete",
                "entries_processed": 0,
                "pairs_generated": 0,
                "pairs_stored": 0,
                "total_generated": self._state.get("total_generated", 0),
            }

        notebook_id = self._get_or_find_notebook()
        nexus = self._client()

        entries_processed = 0
        pairs_generated = 0
        pairs_stored = 0
        already_done: set = set(self._state.get("expanded_hashes", []))

        for entry in entries:
            title = entry.get("title", "?")[:60]
            eh = _entry_hash(entry)

            if self.dry_run:
                logger.info("  [DRY-RUN] Would expand: %s", title)
                already_done.add(eh)
                entries_processed += 1
                pairs_generated += _QUESTIONS_PER_ENTRY
                # Track progress even in dry-run so state reflects what would run
                self._state["expanded_hashes"] = list(already_done)
                _save_state(self._state)
                continue

            questions = self._expand_entry(entry, notebook_id)
            entry_stored = 0
            if questions:
                entry_stored = self._store_pairs(entry, questions, nexus)
                pairs_stored += entry_stored
                pairs_generated += len(questions)

            already_done.add(eh)
            entries_processed += 1

            # Save progress after each entry so we can resume
            self._state["expanded_hashes"] = list(already_done)
            self._state["total_generated"] = self._state.get("total_generated", 0) + entry_stored
            _save_state(self._state)

            # Respectful pacing — NLM is rate-limited
            if not self.dry_run:
                time.sleep(3.0)

        # Final state update
        self._state["last_run"] = datetime.now(timezone.utc).isoformat()
        self._state["runs"] = self._state.get("runs", 0) + 1
        _save_state(self._state)

        total = self._state.get("total_generated", 0)
        logger.info(
            "QA Expander done: %d entries, %d pairs generated, %d stored (total: %d)",
            entries_processed, pairs_generated, pairs_stored, total,
        )
        return {
            "status": "done",
            "entries_processed": entries_processed,
            "pairs_generated": pairs_generated,
            "pairs_stored": pairs_stored,
            "total_generated": total,
        }

    def stats(self) -> Dict[str, Any]:
        """Return current expansion stats."""
        state = self._state  # use in-memory state
        nexus = self._client()
        try:
            info = nexus.stats() if hasattr(nexus, "stats") else {}
            qa_count = info.get("qa_count", info.get("qa_pairs", "?"))
        except Exception:
            qa_count = "?"
        return {
            "entries_expanded": len(state.get("expanded_hashes", [])),
            "total_generated": state.get("total_generated", 0),
            "last_run": state.get("last_run", "never"),
            "runs": state.get("runs", 0),
            "notebook_id": state.get("notebook_id", "not created"),
            "nexus_qa_count": qa_count,
        }

    def reset(self) -> None:
        """Reset expansion state — next run starts from scratch."""
        if _STATE_FILE.exists():
            _STATE_FILE.unlink()
        self._state = {"expanded_hashes": [], "total_generated": 0, "last_run": None, "runs": 0}
        logger.info("QA expander state reset.")


# ── Singleton ─────────────────────────────────────────────────────────────────

_EXPANDER: Optional[QAExpander] = None


def get_qa_expander(dry_run: bool = False) -> QAExpander:
    """Return the shared QAExpander instance."""
    global _EXPANDER
    if _EXPANDER is None:
        _EXPANDER = QAExpander(dry_run=dry_run)
    return _EXPANDER


def run_qa_expansion(batch_size: int = 20) -> Dict[str, Any]:
    """Scheduler-callable: expand one batch of entries into Q&A pairs."""
    try:
        return get_qa_expander().run(batch_size=batch_size)
    except Exception as exc:
        logger.error("QA expansion failed: %s", exc)
        return {"error": str(exc)}


# ── CLI ────────────────────────────────────────────────────────────────────────

def _main() -> None:
    parser = argparse.ArgumentParser(description="QA Expander — expand Nexus entries into Q&A pairs")
    parser.add_argument("--batch-size", type=int, default=20, help="Entries to process per run")
    parser.add_argument("--dry-run", action="store_true", help="Print plan without NLM calls")
    parser.add_argument("--reset", action="store_true", help="Reset progress and start over")
    parser.add_argument("--stats", action="store_true", help="Show progress stats and exit")
    parser.add_argument("--notebook-id", default="", help="Reuse existing NLM notebook ID")
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")

    expander = QAExpander(dry_run=args.dry_run, notebook_id=args.notebook_id)

    if args.reset:
        expander.reset()
        print("State reset.")
        return

    if args.stats:
        s = expander.stats()
        print(f"Entries expanded : {s['entries_expanded']}")
        print(f"Pairs generated  : {s['total_generated']}")
        print(f"Nexus Q&A count  : {s['nexus_qa_count']}")
        print(f"Last run         : {s['last_run']}")
        print(f"Total runs       : {s['runs']}")
        print(f"Notebook ID      : {s['notebook_id']}")
        return

    result = expander.run(batch_size=args.batch_size)
    print(json.dumps(result, indent=2, default=str))


if __name__ == "__main__":
    _main()
