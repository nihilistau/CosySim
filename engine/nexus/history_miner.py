"""History Miner — extracts themed source documents and seed Q&A pairs from the
Copilot session store database.

The Copilot session store (a read-only SQLite file at
``~/.copilot/session-store.db``) contains 164+ checkpoints across all CosySim
development sessions.  Each checkpoint has dense, verified, system-specific
technical knowledge (architecture decisions, API signatures, config keys, test
patterns, etc.).  This module extracts that knowledge and packages it for upload
to NLM notebooks and direct seeding into the Nexus Q&A cache.

Usage::

    from engine.nexus.history_miner import get_history_miner
    miner = get_history_miner()
    docs = miner.mine_all_themes()          # 10 themed SourceDocuments
    seeds = miner.mine_turns()              # direct Q&A seeds from real sessions
    dump = miner.mine_full_dump()           # all checkpoints in one string
"""
from __future__ import annotations

import logging
import os
import sqlite3
import threading
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)

# ──── Constants ──────────────────────────────────────────────────────────────

_DEFAULT_STORE_PATH = Path.home() / ".copilot" / "session-store.db"

# Minimum assistant response length to qualify as a direct-seed Q&A pair
_MIN_TURN_ANSWER_LEN = 400

# Minimum chars in a checkpoint field to bother including
_MIN_CHECKPOINT_FIELD_LEN = 50

# Maximum chars per themed document (NLM source size limit ~500KB)
_MAX_THEME_DOC_CHARS = 300_000


# ──── Data Classes ────────────────────────────────────────────────────────────

@dataclass
class SourceDocument:
    """A document ready for upload to an NLM notebook source."""

    title: str
    content: str
    theme: str
    char_count: int = field(init=False)
    checkpoint_count: int = 0

    def __post_init__(self) -> None:
        self.char_count = len(self.content)


@dataclass
class QAPair:
    """A direct-seed Q&A pair extracted from session turns."""

    question: str
    answer: str
    session_id: str
    turn_index: int
    source: str = "session-turn"


# ──── Theme Definitions ───────────────────────────────────────────────────────

# Each theme is a list of keyword fragments.  A checkpoint is included in a
# theme if ANY of its text fields contain ANY of the keywords (case-insensitive).
THEMES: Dict[str, List[str]] = {
    "nlm-integration": [
        "notebooklm", "nlm", "notebook", "node bridge", "batchexecute",
        "hybrid router", "nlm_hybrid", "nlm_node_bridge", "studio tile",
        "flashcard", "extract_quiz", "generate_report_with_prompt",
        "distill_to_nexus", "data_tables", "nlm_live_proxy", "quota",
    ],
    "architecture": [
        "mcp framework", "mcpframework", "interceptor", "agent governor",
        "virtual_agent", "comms_framework", "agent_loop", "agent router",
        "agentrouter", "agentgovernor", "event chain", "scene state",
        "scenestate", "characternode", "dialog system", "dialogsystem",
        "interceptorbase", "stream processor",
    ],
    "training-pipeline": [
        "training", "finetune", "fine-tune", "dpo", "dataset",
        "training_capture", "router_data", "flywheel", "training flywheel",
        "prepare_from_live", "training_data", "lora", "unsloth",
    ],
    "tts-system": [
        "tts", "orpheus", "piper", "onnx", "native tts", "orpheus_native",
        "tts_manager", "qwen3 tts", "snac", "rtf", "text to speech",
        "voice", "audio generation",
    ],
    "nexus-core": [
        "nexus", "knowledge base", "q&a cache", "qa cache", "query router",
        "nexus_query_router", "qa_expander", "scheduler_daemon", "scheduler",
        "knowledge graph", "nexus_client", "fts5", "nexus kms",
        "qa flywheel", "knowledge entry",
    ],
    "scene-system": [
        "scene", "basescene", "scene_manager", "scene_registry", "flask",
        "scene port", "character", "character_registry", "npc",
        "socket.io", "jinja2", "mcp scene node",
    ],
    "testing-patterns": [
        "pytest", "test", "fixture", "mock", "patch", "assert",
        "conftest", "temp_db", "mock_config", "test suite",
        "test conventions", "test pattern",
    ],
    "config-system": [
        "config", "yaml", "default.yaml", "get_config", "dot-notation",
        "config key", "configmanager", "configuration", "settings",
    ],
    "governance": [
        "governance", "rules engine", "rule", "enforcement",
        "copilot_self_config", "copilot rules", "consensus gate",
        "hook", "check-tool-safety", "coding convention",
        "coding rule", "import convention",
    ],
    "tools-and-skills": [
        "@skill", "skill decorator", "skill pack", "devtools_server",
        "mcp tool", "skill registry", "autonomy_skills",
        "nlm_forge_skills", "builtin skill", "tool call",
    ],
}


# ──── History Miner ───────────────────────────────────────────────────────────

class HistoryMiner:
    """Extracts knowledge from the Copilot session store database.

    The session store is a read-only SQLite database at
    ``~/.copilot/session-store.db``.  It contains:

    - ``sessions``   — project sessions with summaries
    - ``turns``      — user/assistant message pairs
    - ``checkpoints`` — structured snapshots with technical_details,
                        work_done, history, overview, next_steps, files

    Args:
        store_path: Path to session-store.db.  Defaults to
                    ``~/.copilot/session-store.db``.
    """

    def __init__(self, store_path: Optional[Path] = None) -> None:
        self._store_path = Path(store_path) if store_path else _DEFAULT_STORE_PATH
        self._lock = threading.Lock()

    # ── Public API ─────────────────────────────────────────────────────────

    def mine_checkpoints(self, theme: str) -> SourceDocument:
        """Extract checkpoints matching a theme → themed markdown document.

        The returned ``SourceDocument`` is ready for upload to an NLM notebook
        via ``nlm_hybrid.add_text_source()``.

        Args:
            theme: One of the keys in ``THEMES``.

        Returns:
            A ``SourceDocument`` with all matching checkpoint content.

        Raises:
            ValueError: If theme is not in THEMES.
        """
        if theme not in THEMES:
            raise ValueError(f"Unknown theme '{theme}'. Valid: {list(THEMES)}")
        keywords = THEMES[theme]
        rows = self._fetch_checkpoints()
        sections: List[str] = []
        matched = 0
        for row in rows:
            text = self._checkpoint_text(row)
            if self._matches(text, keywords):
                section = self._format_checkpoint_section(row)
                if section:
                    sections.append(section)
                    matched += 1
                    if sum(len(s) for s in sections) > _MAX_THEME_DOC_CHARS:
                        logger.debug("Theme '%s' reached size limit at %d checkpoints", theme, matched)
                        break

        header = (
            f"# CosySim Development History — {theme.replace('-', ' ').title()}\n\n"
            f"Extracted from {matched} Copilot session checkpoints.\n"
            f"Source: {self._store_path}\n\n"
            "---\n\n"
        )
        doc = SourceDocument(
            title=f"CosySim History: {theme.replace('-', ' ').title()}",
            content=header + "\n\n".join(sections),
            theme=theme,
            checkpoint_count=matched,
        )
        logger.info("Theme '%s': %d checkpoints, %d chars", theme, matched, doc.char_count)
        return doc

    def mine_all_themes(self) -> List[SourceDocument]:
        """Extract all 10 themed source documents.

        Returns:
            List of ``SourceDocument`` objects, one per theme in ``THEMES``.
        """
        docs: List[SourceDocument] = []
        for theme in THEMES:
            try:
                doc = self.mine_checkpoints(theme)
                if doc.checkpoint_count > 0:
                    docs.append(doc)
            except Exception as exc:
                logger.warning("Failed to mine theme '%s': %s", theme, exc)
        logger.info("Mined %d themed documents from %d themes", len(docs), len(THEMES))
        return docs

    def mine_turns(self, min_answer_len: int = _MIN_TURN_ANSWER_LEN) -> List[QAPair]:
        """Extract high-quality Q&A pairs from session turn history.

        Turns where the assistant response is long and detailed are treated as
        real Q&A pairs — the user message is the question, the assistant
        response is the answer.  These are the highest-quality source because
        they come from real work, not generated content.

        Args:
            min_answer_len: Minimum assistant response chars (default 400).

        Returns:
            List of ``QAPair`` objects ready for direct Nexus seeding.
        """
        rows = self._fetch_turns(min_answer_len)
        pairs: List[QAPair] = []
        for session_id, turn_index, user_msg, assistant_resp in rows:
            # Filter out non-question user messages (commands, one-word inputs)
            if not user_msg or len(user_msg.strip()) < 10:
                continue
            # Prefer messages that look like questions or requests
            q = user_msg.strip()
            a = assistant_resp.strip()
            pairs.append(QAPair(
                question=q,
                answer=a,
                session_id=session_id,
                turn_index=turn_index,
            ))
        logger.info("Mined %d direct-seed Q&A pairs from turns", len(pairs))
        return pairs

    def mine_full_dump(self) -> str:
        """Concatenate all checkpoint fields into one large document.

        Useful for uploading to a single high-capacity NLM notebook when
        the 1M token context window can hold the entire history.

        Returns:
            Markdown string with all checkpoint data, ~483KB.
        """
        rows = self._fetch_checkpoints()
        sections: List[str] = []
        for row in rows:
            section = self._format_checkpoint_section(row)
            if section:
                sections.append(section)
        header = (
            "# CosySim Full Development History\n\n"
            f"All {len(rows)} Copilot session checkpoints.\n"
            f"Source: {self._store_path}\n\n"
            "---\n\n"
        )
        dump = header + "\n\n".join(sections)
        logger.info("Full dump: %d checkpoints, %d chars", len(rows), len(dump))
        return dump

    def get_stats(self) -> Dict[str, Any]:
        """Return basic statistics about the session store.

        Returns:
            Dict with session_count, checkpoint_count, turn_count, store_size_kb.
        """
        if not self._store_path.exists():
            return {"error": f"Store not found: {self._store_path}"}
        try:
            with self._connect() as conn:
                sessions = conn.execute("SELECT COUNT(*) FROM sessions").fetchone()[0]
                checkpoints = conn.execute("SELECT COUNT(*) FROM checkpoints").fetchone()[0]
                turns = conn.execute("SELECT COUNT(*) FROM turns").fetchone()[0]
            size_kb = round(self._store_path.stat().st_size / 1024, 1)
            return {
                "session_count": sessions,
                "checkpoint_count": checkpoints,
                "turn_count": turns,
                "store_size_kb": size_kb,
                "store_path": str(self._store_path),
            }
        except Exception as exc:
            logger.error("Failed to get stats: %s", exc)
            return {"error": str(exc)}

    # ── Internal ───────────────────────────────────────────────────────────

    def _connect(self) -> sqlite3.Connection:
        """Open a read-only connection to the session store."""
        if not self._store_path.exists():
            raise FileNotFoundError(f"Session store not found: {self._store_path}")
        # uri=True + ?mode=ro ensures we never accidentally write
        uri = f"file:{self._store_path}?mode=ro"
        return sqlite3.connect(uri, uri=True, timeout=10.0)

    def _fetch_checkpoints(self) -> List[Tuple]:
        """Fetch all checkpoints ordered by session + checkpoint_number."""
        query = """
            SELECT
                c.session_id,
                c.checkpoint_number,
                c.title,
                c.overview,
                c.history,
                c.work_done,
                c.technical_details,
                c.next_steps
            FROM checkpoints c
            ORDER BY c.session_id, c.checkpoint_number
        """
        try:
            with self._connect() as conn:
                return conn.execute(query).fetchall()
        except Exception as exc:
            logger.error("Failed to fetch checkpoints: %s", exc)
            return []

    def _fetch_turns(self, min_answer_len: int) -> List[Tuple]:
        """Fetch turns where assistant response meets length threshold."""
        query = """
            SELECT
                t.session_id,
                t.turn_index,
                t.user_message,
                t.assistant_response
            FROM turns t
            WHERE length(t.assistant_response) >= ?
              AND t.user_message IS NOT NULL
              AND length(t.user_message) >= 10
            ORDER BY t.session_id, t.turn_index
        """
        try:
            with self._connect() as conn:
                return conn.execute(query, (min_answer_len,)).fetchall()
        except Exception as exc:
            logger.error("Failed to fetch turns: %s", exc)
            return []

    def _checkpoint_text(self, row: Tuple) -> str:
        """Concatenate all text fields of a checkpoint row for keyword matching."""
        # row: (session_id, number, title, overview, history, work_done, technical, next_steps)
        parts = [str(f) for f in row if f]
        return " ".join(parts).lower()

    def _matches(self, text: str, keywords: List[str]) -> bool:
        """Return True if text contains any keyword (case-insensitive)."""
        return any(kw.lower() in text for kw in keywords)

    def _format_checkpoint_section(self, row: Tuple) -> str:
        """Format a checkpoint row as a readable markdown section."""
        (session_id, number, title, overview, history, work_done,
         technical_details, next_steps) = row
        parts: List[str] = []
        parts.append(f"## Checkpoint {number}: {title or 'Untitled'}")
        parts.append(f"*Session: {session_id[:8]}*")
        if overview and len(overview) >= _MIN_CHECKPOINT_FIELD_LEN:
            parts.append(f"\n### Overview\n{overview}")
        if technical_details and len(technical_details) >= _MIN_CHECKPOINT_FIELD_LEN:
            parts.append(f"\n### Technical Details\n{technical_details}")
        if work_done and len(work_done) >= _MIN_CHECKPOINT_FIELD_LEN:
            parts.append(f"\n### Work Done\n{work_done}")
        if next_steps and len(next_steps) >= _MIN_CHECKPOINT_FIELD_LEN:
            parts.append(f"\n### Next Steps\n{next_steps}")
        if len(parts) <= 2:
            # Only header + session_id — nothing meaningful
            return ""
        return "\n".join(parts)


# ──── Singleton ───────────────────────────────────────────────────────────────

_miner_instance: Optional[HistoryMiner] = None
_miner_lock = threading.Lock()


def get_history_miner(store_path: Optional[Path] = None) -> HistoryMiner:
    """Get the singleton HistoryMiner instance.

    Args:
        store_path: Override the default session store path.

    Returns:
        The singleton ``HistoryMiner``.
    """
    global _miner_instance
    if _miner_instance is None:
        with _miner_lock:
            if _miner_instance is None:
                _miner_instance = HistoryMiner(store_path=store_path)
    return _miner_instance


# ──── CLI ─────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    import argparse
    import json

    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    parser = argparse.ArgumentParser(description="Mine Copilot session history")
    sub = parser.add_subparsers(dest="cmd")

    sub.add_parser("stats", help="Show session store statistics")
    p_theme = sub.add_parser("theme", help="Mine a specific theme")
    p_theme.add_argument("name", choices=list(THEMES), help="Theme name")
    p_theme.add_argument("--output", help="Save to file")
    sub.add_parser("all", help="Mine all themes and print sizes")
    sub.add_parser("seeds", help="Mine direct-seed Q&A pairs")
    sub.add_parser("dump", help="Mine full dump")

    args = parser.parse_args()
    miner = HistoryMiner()

    if args.cmd == "stats":
        print(json.dumps(miner.get_stats(), indent=2))
    elif args.cmd == "theme":
        doc = miner.mine_checkpoints(args.name)
        print(f"Theme: {doc.theme}")
        print(f"Checkpoints: {doc.checkpoint_count}")
        print(f"Chars: {doc.char_count:,}")
        if args.output:
            Path(args.output).write_text(doc.content, encoding="utf-8")
            print(f"Saved to {args.output}")
        else:
            print(doc.content[:2000] + ("..." if doc.char_count > 2000 else ""))
    elif args.cmd == "all":
        docs = miner.mine_all_themes()
        total = sum(d.char_count for d in docs)
        print(f"{'Theme':<25} {'Checkpoints':>12} {'Chars':>10}")
        print("-" * 52)
        for d in docs:
            print(f"{d.theme:<25} {d.checkpoint_count:>12} {d.char_count:>10,}")
        print("-" * 52)
        print(f"{'TOTAL':<25} {sum(d.checkpoint_count for d in docs):>12} {total:>10,}")
    elif args.cmd == "seeds":
        pairs = miner.mine_turns()
        print(f"Direct-seed Q&A pairs: {len(pairs)}")
        for p in pairs[:5]:
            print(f"\nQ: {p.question[:100]}...")
            print(f"A: {p.answer[:200]}...")
    elif args.cmd == "dump":
        dump = miner.mine_full_dump()
        print(f"Full dump: {len(dump):,} chars")
    else:
        parser.print_help()
