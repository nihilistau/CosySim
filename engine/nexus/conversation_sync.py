"""Scene-to-Nexus conversation sync.

Syncs conversation activity from scene EventChains to Nexus knowledge base
and training pipeline. Tracks sync position to avoid re-processing.
Closes the conversation→knowledge→training feedback loop.

Usage::

    from engine.nexus.conversation_sync import get_conversation_sync

    sync = get_conversation_sync()
    sync.register_task()          # register periodic scheduler task
    result = sync.force_sync()    # run sync immediately
    status = sync.get_sync_status()
"""
from __future__ import annotations

import json
import logging
import sqlite3
import threading
import time
import uuid
from collections import defaultdict
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)

# ──── Constants ────

_DEFAULT_SYNC_DB = "data/conversation_sync.db"
_DEFAULT_BATCH_SIZE = 200
_EVENT_TYPE_GOVERNED = "governed_response"
_MIN_CHAIN_EVENTS = 3
_SYNC_SCHEDULE = "every_2h"


# ──── SyncRecord Dataclass ────

@dataclass
class SyncRecord:
    """Tracks the result of a single sync operation."""

    sync_id: str
    sync_type: str  # "conversation" | "skill_usage" | "interaction_pattern"
    events_processed: int = 0
    entries_created: int = 0
    started_at: float = field(default_factory=time.time)
    completed_at: Optional[float] = None
    status: str = "running"  # "running" | "completed" | "failed"
    error: Optional[str] = None


# ──── ConversationSync ────

class ConversationSync:
    """Syncs scene conversation data from EventChain to Nexus and TrainingFlywheel.

    Reads governed_response events from the simulation database, groups them
    by chain_id, and generates Nexus knowledge entries, Q&A pairs, and
    training signals. Tracks the last-synced event position in a local
    SQLite database to avoid re-processing.

    Thread-safe — all public methods acquire the instance lock.
    """

    def __init__(self, db_path: str = _DEFAULT_SYNC_DB) -> None:
        self._db_path = self._resolve_path(db_path)
        self._db_path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()
        self._local = threading.local()
        self._init_schema()
        logger.info("ConversationSync initialised — db=%s", self._db_path)

    # ──── Schema & DB Helpers ────

    @staticmethod
    def _resolve_path(raw: str) -> Path:
        """Resolve a relative path against the project root."""
        p = Path(raw)
        if p.is_absolute():
            return p
        try:
            from engine.paths import ROOT
            return ROOT / p
        except Exception:
            return Path.cwd() / p

    def _get_conn(self) -> sqlite3.Connection:
        """Return a thread-local SQLite connection to the sync DB."""
        if not hasattr(self._local, "conn") or self._local.conn is None:
            self._local.conn = sqlite3.connect(str(self._db_path), timeout=10)
            self._local.conn.row_factory = sqlite3.Row
            self._local.conn.execute("PRAGMA journal_mode=WAL")
            self._local.conn.execute("PRAGMA synchronous=NORMAL")
        return self._local.conn

    @contextmanager
    def _cursor(self):
        """Context manager yielding a cursor with auto-commit/rollback."""
        conn = self._get_conn()
        cursor = conn.cursor()
        try:
            yield cursor
            conn.commit()
        except Exception:
            conn.rollback()
            raise

    def _init_schema(self) -> None:
        """Create tracking tables if they don't exist."""
        with self._cursor() as cur:
            cur.execute("""
                CREATE TABLE IF NOT EXISTS sync_state (
                    key   TEXT PRIMARY KEY,
                    value TEXT NOT NULL
                )
            """)
            cur.execute("""
                CREATE TABLE IF NOT EXISTS sync_records (
                    sync_id          TEXT PRIMARY KEY,
                    sync_type        TEXT NOT NULL,
                    events_processed INTEGER DEFAULT 0,
                    entries_created  INTEGER DEFAULT 0,
                    started_at       REAL NOT NULL,
                    completed_at     REAL,
                    status           TEXT DEFAULT 'running',
                    error            TEXT
                )
            """)
            # Seed initial state if absent
            cur.execute(
                "INSERT OR IGNORE INTO sync_state (key, value) VALUES (?, ?)",
                ("last_event_id", "0"),
            )
            cur.execute(
                "INSERT OR IGNORE INTO sync_state (key, value) VALUES (?, ?)",
                ("last_sync_timestamp", "0"),
            )

    # ──── Sync State Accessors ────

    def _get_last_event_id(self) -> int:
        """Read the last-synced event row-id from sync_state."""
        with self._cursor() as cur:
            row = cur.execute(
                "SELECT value FROM sync_state WHERE key = ?", ("last_event_id",)
            ).fetchone()
            return int(row["value"]) if row else 0

    def _set_last_event_id(self, event_id: int) -> None:
        """Persist the most-recently synced event row-id."""
        with self._cursor() as cur:
            cur.execute(
                "INSERT OR REPLACE INTO sync_state (key, value) VALUES (?, ?)",
                ("last_event_id", str(event_id)),
            )
            cur.execute(
                "INSERT OR REPLACE INTO sync_state (key, value) VALUES (?, ?)",
                ("last_sync_timestamp", str(time.time())),
            )

    # ──── EventChain DB Access (READ-ONLY) ────

    def _get_event_chain_db_path(self) -> Path:
        """Resolve the EventChain (simulation) DB path from config or default."""
        try:
            from engine.paths import DB_SIMULATION
            return DB_SIMULATION
        except Exception:
            pass
        try:
            from engine.config import get_config
            raw = get_config().get("database.sqlite.path", "data/simulation.db")
            return self._resolve_path(raw)
        except Exception:
            return self._resolve_path("data/simulation.db")

    def _read_events(self, after_id: int, batch_size: int) -> List[Dict[str, Any]]:
        """Read governed_response events from the EventChain DB.

        The EventChain table uses a TEXT primary key (UUID), but events are
        chronologically ordered by the ``timestamp`` column (ISO-8601 string).
        We use rowid as the monotonic cursor for sync tracking since TEXT PKs
        can't be compared numerically.

        Args:
            after_id: Rowid to read after (exclusive).
            batch_size: Maximum events to return.

        Returns:
            List of event dicts with an injected ``_rowid`` key.
        """
        ec_path = self._get_event_chain_db_path()
        if not ec_path.exists():
            logger.debug("EventChain DB not found at %s", ec_path)
            return []

        events: List[Dict[str, Any]] = []
        try:
            conn = sqlite3.connect(f"file:{ec_path}?mode=ro", uri=True, timeout=5)
            conn.row_factory = sqlite3.Row
            rows = conn.execute(
                """
                SELECT rowid, id, timestamp, event_type, actor, payload,
                       summary, chain_id, character_id, scene_id
                FROM events
                WHERE rowid > ? AND event_type = ?
                ORDER BY rowid ASC
                LIMIT ?
                """,
                (after_id, _EVENT_TYPE_GOVERNED, batch_size),
            ).fetchall()
            for row in rows:
                ev = dict(row)
                ev["_rowid"] = ev.pop("rowid")
                # Parse payload JSON
                try:
                    ev["payload"] = json.loads(ev["payload"]) if ev["payload"] else {}
                except (json.JSONDecodeError, TypeError):
                    ev["payload"] = {}
                events.append(ev)
            conn.close()
        except Exception as exc:
            logger.warning("Failed to read EventChain DB: %s", exc)
        return events

    def _read_events_since(self, hours: float, event_type: Optional[str] = None) -> List[Dict[str, Any]]:
        """Read events from the last N hours, optionally filtered by type.

        Args:
            hours: Look-back window in hours.
            event_type: Optional event_type filter. Reads all types if ``None``.

        Returns:
            List of event dicts.
        """
        ec_path = self._get_event_chain_db_path()
        if not ec_path.exists():
            return []

        cutoff = (datetime.now() - timedelta(hours=hours)).isoformat()
        events: List[Dict[str, Any]] = []
        try:
            conn = sqlite3.connect(f"file:{ec_path}?mode=ro", uri=True, timeout=5)
            conn.row_factory = sqlite3.Row
            if event_type:
                rows = conn.execute(
                    "SELECT * FROM events WHERE timestamp >= ? AND event_type = ? ORDER BY timestamp ASC",
                    (cutoff, event_type),
                ).fetchall()
            else:
                rows = conn.execute(
                    "SELECT * FROM events WHERE timestamp >= ? ORDER BY timestamp ASC",
                    (cutoff,),
                ).fetchall()
            for row in rows:
                ev = dict(row)
                try:
                    ev["payload"] = json.loads(ev["payload"]) if ev["payload"] else {}
                except (json.JSONDecodeError, TypeError):
                    ev["payload"] = {}
                events.append(ev)
            conn.close()
        except Exception as exc:
            logger.warning("Failed to read EventChain timed events: %s", exc)
        return events

    # ──── Grouping ────

    @staticmethod
    def _group_by_chain(events: List[Dict[str, Any]]) -> Dict[str, List[Dict[str, Any]]]:
        """Group a list of events by their ``chain_id``.

        Args:
            events: Flat list of event dicts.

        Returns:
            Mapping of chain_id → ordered event list.
        """
        chains: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
        for ev in events:
            cid = ev.get("chain_id")
            if cid:
                chains[cid].append(ev)
        return dict(chains)

    # ──── Nexus & Flywheel Storage Helpers ────

    def _store_to_nexus(
        self,
        title: str,
        content: str,
        category: str = "conversation",
        content_type: str = "memory",
    ) -> bool:
        """Store a knowledge entry in Nexus with graceful error handling.

        Args:
            title: Entry title.
            content: Entry body text.
            category: Nexus category.
            content_type: Nexus content type.

        Returns:
            ``True`` if stored successfully, ``False`` otherwise.
        """
        try:
            from engine.nexus.client import get_nexus_client
            client = get_nexus_client()
            entry_id = client.add_entry(
                title=title,
                content=content,
                content_type=content_type,
                category=category,
                tags=["conversation_sync", "auto"],
                created_by="conversation_sync",
            )
            if entry_id:
                logger.debug("Nexus entry stored: %s — %s", entry_id, title)
                return True
            logger.debug("Nexus rejected entry: %s", title)
            return False
        except Exception as exc:
            logger.warning("Nexus store failed for '%s': %s", title, exc)
            return False

    def _store_qa(
        self,
        question: str,
        answer: str,
        category: str = "conversation",
    ) -> bool:
        """Store a Q&A pair in Nexus with graceful error handling.

        Args:
            question: The question text.
            answer: The answer text.
            category: Nexus category.

        Returns:
            ``True`` if stored successfully, ``False`` otherwise.
        """
        try:
            from engine.nexus.client import get_nexus_client
            client = get_nexus_client()
            qa_id = client.add_qa(
                question=question,
                answer=answer,
                category=category,
                tags=["conversation_sync", "auto"],
                quality_score=0.6,
                agent_id="conversation_sync",
            )
            if qa_id:
                logger.debug("Nexus Q&A stored: %s", qa_id)
                return True
            return False
        except Exception as exc:
            logger.warning("Nexus Q&A store failed: %s", exc)
            return False

    def _feed_training_flywheel(
        self,
        question: str,
        answer: str,
        source: str = "conversation_sync",
    ) -> bool:
        """Forward a Q&A pair to the TrainingFlywheel.

        Args:
            question: Input text.
            answer: Output text.
            source: Origin label.

        Returns:
            ``True`` if collected, ``False`` otherwise.
        """
        try:
            from engine.nexus.training_flywheel import get_training_flywheel
            flywheel = get_training_flywheel()
            eid = flywheel.collect_from_qa(
                question=question,
                answer=answer,
                source=source,
                confidence=0.6,
            )
            return bool(eid)
        except Exception as exc:
            logger.debug("TrainingFlywheel feed failed: %s", exc)
            return False

    # ──── SyncRecord Lifecycle ────

    def _start_sync(self, sync_type: str) -> SyncRecord:
        """Create and persist a new SyncRecord.

        Args:
            sync_type: Type of sync being started.

        Returns:
            The new SyncRecord.
        """
        rec = SyncRecord(
            sync_id=f"sync-{uuid.uuid4().hex[:8]}",
            sync_type=sync_type,
        )
        with self._cursor() as cur:
            cur.execute(
                """
                INSERT INTO sync_records
                    (sync_id, sync_type, events_processed, entries_created,
                     started_at, status)
                VALUES (?, ?, 0, 0, ?, 'running')
                """,
                (rec.sync_id, rec.sync_type, rec.started_at),
            )
        logger.info("Started sync %s (%s)", rec.sync_id, sync_type)
        return rec

    def _complete_sync(self, sync: SyncRecord, result: Dict[str, Any]) -> None:
        """Mark a SyncRecord as completed and persist its stats.

        Args:
            sync: The record to complete.
            result: Dict with ``events_processed`` and ``entries_created`` keys.
        """
        sync.status = "completed"
        sync.completed_at = time.time()
        sync.events_processed = result.get("events_processed", 0)
        sync.entries_created = result.get("entries_created", 0)
        with self._cursor() as cur:
            cur.execute(
                """
                UPDATE sync_records
                SET status = 'completed', completed_at = ?,
                    events_processed = ?, entries_created = ?
                WHERE sync_id = ?
                """,
                (
                    sync.completed_at,
                    sync.events_processed,
                    sync.entries_created,
                    sync.sync_id,
                ),
            )
        duration = sync.completed_at - sync.started_at
        logger.info(
            "Completed sync %s — %d events, %d entries, %.1fs",
            sync.sync_id,
            sync.events_processed,
            sync.entries_created,
            duration,
        )

    def _fail_sync(self, sync: SyncRecord, error: str) -> None:
        """Mark a SyncRecord as failed and persist the error.

        Args:
            sync: The record that failed.
            error: Error description.
        """
        sync.status = "failed"
        sync.completed_at = time.time()
        sync.error = error
        try:
            with self._cursor() as cur:
                cur.execute(
                    """
                    UPDATE sync_records
                    SET status = 'failed', completed_at = ?, error = ?
                    WHERE sync_id = ?
                    """,
                    (sync.completed_at, error, sync.sync_id),
                )
        except Exception as exc:
            logger.error("Failed to persist sync failure: %s", exc)
        logger.error("Sync %s failed: %s", sync.sync_id, error)

    # ──── Core Sync Methods ────

    def sync_conversations(self, batch_size: int = _DEFAULT_BATCH_SIZE) -> Dict[str, Any]:
        """Sync conversation events from EventChain to Nexus.

        Reads new ``governed_response`` events since the last sync position,
        groups them by chain_id, and for each conversation thread with
        sufficient depth, creates a Nexus knowledge entry summarising the
        conversation, stores skill-usage Q&A pairs, and feeds the
        TrainingFlywheel.

        Args:
            batch_size: Maximum events to process per call.

        Returns:
            Summary dict with ``events_processed``, ``entries_created``,
            ``chains_processed``, and ``skipped_short_chains``.
        """
        with self._lock:
            sync = self._start_sync("conversation")
            try:
                last_id = self._get_last_event_id()
                events = self._read_events(last_id, batch_size)

                if not events:
                    result = {
                        "events_processed": 0,
                        "entries_created": 0,
                        "chains_processed": 0,
                        "skipped_short_chains": 0,
                    }
                    self._complete_sync(sync, result)
                    return result

                chains = self._group_by_chain(events)
                entries_created = 0
                chains_processed = 0
                skipped = 0

                for chain_id, chain_events in chains.items():
                    if len(chain_events) < _MIN_CHAIN_EVENTS:
                        skipped += 1
                        continue

                    chains_processed += 1

                    # Extract metadata from chain
                    characters = set()
                    scenes = set()
                    all_skills: List[str] = []
                    summaries: List[str] = []

                    for ev in chain_events:
                        if ev.get("actor"):
                            characters.add(ev["actor"])
                        payload = ev.get("payload", {})
                        if isinstance(payload, dict):
                            scene = payload.get("scene")
                            if scene:
                                scenes.add(scene)
                            skills = payload.get("skills_auto", [])
                            if isinstance(skills, list):
                                all_skills.extend(skills)
                        if ev.get("summary"):
                            summaries.append(ev["summary"])

                    character_str = ", ".join(sorted(characters)) or "unknown"
                    scene_str = ", ".join(sorted(scenes)) or "unknown"
                    turn_count = len(chain_events)

                    # Build Nexus entry content
                    skill_counts: Dict[str, int] = defaultdict(int)
                    for sk in all_skills:
                        skill_counts[sk] += 1

                    content_parts = [
                        f"Chain ID: {chain_id}",
                        f"Characters: {character_str}",
                        f"Scenes: {scene_str}",
                        f"Turns: {turn_count}",
                        f"Skills used: {dict(skill_counts) if skill_counts else 'none'}",
                        "",
                        "Conversation summaries:",
                    ]
                    for i, s in enumerate(summaries[:20], 1):
                        content_parts.append(f"  {i}. {s}")

                    title = f"Conversation: {character_str} in {scene_str} ({turn_count} turns)"
                    content = "\n".join(content_parts)

                    if self._store_to_nexus(title, content, "conversation", "memory"):
                        entries_created += 1

                    # Store skill usage Q&A for this character
                    if skill_counts:
                        top_skills = sorted(
                            skill_counts.items(), key=lambda x: x[1], reverse=True
                        )[:5]
                        skill_answer = ", ".join(
                            f"{name} ({count}x)" for name, count in top_skills
                        )
                        q = f"What skills does {character_str} use most in {scene_str}?"
                        a = f"Top skills: {skill_answer} (from {turn_count} turns)"
                        if self._store_qa(q, a, "conversation"):
                            entries_created += 1

                    # Feed training flywheel with conversation summaries
                    if summaries:
                        summary_text = " | ".join(summaries[:10])
                        self._feed_training_flywheel(
                            question=f"Conversation with {character_str} in {scene_str}",
                            answer=summary_text,
                            source="conversation_sync",
                        )

                # Update sync position to the highest rowid we processed
                max_rowid = max(ev["_rowid"] for ev in events)
                self._set_last_event_id(max_rowid)

                result = {
                    "events_processed": len(events),
                    "entries_created": entries_created,
                    "chains_processed": chains_processed,
                    "skipped_short_chains": skipped,
                }
                self._complete_sync(sync, result)
                return result

            except Exception as exc:
                self._fail_sync(sync, str(exc))
                return {
                    "events_processed": 0,
                    "entries_created": 0,
                    "chains_processed": 0,
                    "error": str(exc),
                }

    def sync_skill_usage(self) -> Dict[str, Any]:
        """Aggregate skill usage patterns from EventChain and store in Nexus.

        Queries the last 24 hours of ``governed_response`` events, parses
        ``skills_auto`` from each payload, aggregates by skill name, and
        stores a summary knowledge entry plus individual high-usage Q&A
        pairs in Nexus.

        Returns:
            Summary dict with ``total_events``, ``unique_skills``,
            ``entries_created``.
        """
        with self._lock:
            sync = self._start_sync("skill_usage")
            try:
                events = self._read_events_since(24.0, event_type=_EVENT_TYPE_GOVERNED)

                skill_agg: Dict[str, Dict[str, Any]] = defaultdict(
                    lambda: {"count": 0, "scenes": set(), "characters": set()}
                )

                for ev in events:
                    payload = ev.get("payload", {})
                    if not isinstance(payload, dict):
                        continue
                    skills = payload.get("skills_auto", [])
                    if not isinstance(skills, list):
                        continue
                    scene = payload.get("scene", "unknown")
                    character = ev.get("actor", "unknown")
                    for skill_name in skills:
                        if not skill_name:
                            continue
                        entry = skill_agg[skill_name]
                        entry["count"] += 1
                        entry["scenes"].add(scene)
                        entry["characters"].add(character)

                if not skill_agg:
                    result = {
                        "total_events": len(events),
                        "unique_skills": 0,
                        "entries_created": 0,
                    }
                    self._complete_sync(sync, result)
                    return result

                entries_created = 0

                # Build report content
                sorted_skills = sorted(
                    skill_agg.items(), key=lambda x: x[1]["count"], reverse=True
                )
                report_lines = [
                    f"Skill Usage Report — last 24h ({len(events)} events)",
                    f"Generated: {datetime.now().isoformat()}",
                    "",
                ]
                for skill_name, data in sorted_skills:
                    scenes_str = ", ".join(sorted(data["scenes"]))
                    chars_str = ", ".join(sorted(data["characters"]))
                    report_lines.append(
                        f"  {skill_name}: {data['count']}x "
                        f"(scenes: {scenes_str}; characters: {chars_str})"
                    )

                title = f"Skill Usage Report ({datetime.now().strftime('%Y-%m-%d %H:%M')})"
                if self._store_to_nexus(
                    title, "\n".join(report_lines), "skill_usage", "memory"
                ):
                    entries_created += 1

                # Top-5 Q&A
                top5 = sorted_skills[:5]
                if top5:
                    answer_parts = [
                        f"{name} ({data['count']}x)" for name, data in top5
                    ]
                    q = "Which skills are most used in the last 24 hours?"
                    a = f"Top {len(top5)}: {', '.join(answer_parts)}"
                    if self._store_qa(q, a, "skill_usage"):
                        entries_created += 1

                    # Per-skill high-usage Q&A (count >= 5)
                    for skill_name, data in sorted_skills:
                        if data["count"] >= 5:
                            chars = ", ".join(sorted(data["characters"]))
                            q = f"Which characters use the '{skill_name}' skill?"
                            a = (
                                f"Characters using '{skill_name}': {chars} "
                                f"({data['count']} uses in last 24h)"
                            )
                            if self._store_qa(q, a, "skill_usage"):
                                entries_created += 1

                result = {
                    "total_events": len(events),
                    "unique_skills": len(skill_agg),
                    "entries_created": entries_created,
                }
                self._complete_sync(
                    sync,
                    {
                        "events_processed": len(events),
                        "entries_created": entries_created,
                    },
                )
                return result

            except Exception as exc:
                self._fail_sync(sync, str(exc))
                return {
                    "total_events": 0,
                    "unique_skills": 0,
                    "entries_created": 0,
                    "error": str(exc),
                }

    def sync_interaction_patterns(self) -> Dict[str, Any]:
        """Detect and store interaction patterns from conversation data.

        Analyses the last 7 days of events to identify:
        - Average conversation length by scene
        - Most active characters
        - Peak activity hours
        - Common skill sequences (skill A followed by skill B)
        - Training signals (short conversations, frequent skill combos)

        Returns:
            Pattern summary dict.
        """
        with self._lock:
            sync = self._start_sync("interaction_pattern")
            try:
                events = self._read_events_since(168.0)  # 7 days

                if not events:
                    result: Dict[str, Any] = {
                        "total_events": 0,
                        "patterns_found": 0,
                        "entries_created": 0,
                    }
                    self._complete_sync(
                        sync,
                        {"events_processed": 0, "entries_created": 0},
                    )
                    return result

                # Group by chain for conversation-level analysis
                chains = self._group_by_chain(events)
                entries_created = 0

                # ── Pattern 1: Average conversation length by scene ──
                scene_lengths: Dict[str, List[int]] = defaultdict(list)
                for chain_events in chains.values():
                    for ev in chain_events:
                        payload = ev.get("payload", {})
                        if isinstance(payload, dict):
                            scene = payload.get("scene")
                            if scene:
                                scene_lengths[scene].append(len(chain_events))
                                break  # one scene tag per chain is enough

                avg_lengths: Dict[str, float] = {}
                for scene, lengths in scene_lengths.items():
                    avg_lengths[scene] = round(sum(lengths) / len(lengths), 1)

                # ── Pattern 2: Most active characters ──
                char_activity: Dict[str, int] = defaultdict(int)
                for ev in events:
                    actor = ev.get("actor")
                    if actor and actor != "system":
                        char_activity[actor] += 1
                top_characters = sorted(
                    char_activity.items(), key=lambda x: x[1], reverse=True
                )[:10]

                # ── Pattern 3: Peak activity hours ──
                hour_counts: Dict[int, int] = defaultdict(int)
                for ev in events:
                    ts = ev.get("timestamp", "")
                    if ts and isinstance(ts, str):
                        try:
                            dt = datetime.fromisoformat(ts)
                            hour_counts[dt.hour] += 1
                        except (ValueError, TypeError):
                            pass
                peak_hours = sorted(
                    hour_counts.items(), key=lambda x: x[1], reverse=True
                )[:5]

                # ── Pattern 4: Common skill sequences ──
                skill_sequences: Dict[Tuple[str, str], int] = defaultdict(int)
                for chain_events in chains.values():
                    prev_skills: List[str] = []
                    for ev in chain_events:
                        payload = ev.get("payload", {})
                        if not isinstance(payload, dict):
                            continue
                        cur_skills = payload.get("skills_auto", [])
                        if not isinstance(cur_skills, list):
                            continue
                        for prev_sk in prev_skills:
                            for cur_sk in cur_skills:
                                if prev_sk and cur_sk and prev_sk != cur_sk:
                                    skill_sequences[(prev_sk, cur_sk)] += 1
                        prev_skills = cur_skills

                top_sequences = sorted(
                    skill_sequences.items(), key=lambda x: x[1], reverse=True
                )[:10]

                # ── Pattern 5: Training signals ──
                training_signals: List[str] = []

                # Characters with short conversations might need better prompts
                for scene, avg_len in avg_lengths.items():
                    if avg_len < 3:
                        training_signals.append(
                            f"Scene '{scene}' has short conversations "
                            f"(avg {avg_len} turns) — may need better prompts"
                        )

                # Frequently co-occurring skills → combo skill candidates
                for (sk_a, sk_b), count in top_sequences[:3]:
                    if count >= 5:
                        training_signals.append(
                            f"Skills '{sk_a}' → '{sk_b}' frequently paired "
                            f"({count}x) — candidate for combo skill"
                        )

                # ── Store patterns in Nexus ──
                report_lines = [
                    f"Interaction Pattern Report — last 7 days ({len(events)} events)",
                    f"Generated: {datetime.now().isoformat()}",
                    "",
                    "Average conversation length by scene:",
                ]
                for scene, avg in sorted(avg_lengths.items()):
                    report_lines.append(f"  {scene}: {avg} turns")

                report_lines.append("\nMost active characters:")
                for char, count in top_characters:
                    report_lines.append(f"  {char}: {count} events")

                report_lines.append("\nPeak activity hours:")
                for hour, count in peak_hours:
                    report_lines.append(f"  {hour:02d}:00 — {count} events")

                if top_sequences:
                    report_lines.append("\nCommon skill sequences:")
                    for (sk_a, sk_b), count in top_sequences:
                        report_lines.append(f"  {sk_a} → {sk_b}: {count}x")

                if training_signals:
                    report_lines.append("\nTraining signals:")
                    for sig in training_signals:
                        report_lines.append(f"  ⚡ {sig}")

                title = f"Interaction Patterns ({datetime.now().strftime('%Y-%m-%d %H:%M')})"
                if self._store_to_nexus(
                    title, "\n".join(report_lines), "interaction_patterns", "memory"
                ):
                    entries_created += 1

                # Store key Q&A pairs
                if top_characters:
                    chars_str = ", ".join(
                        f"{c} ({n} events)" for c, n in top_characters[:5]
                    )
                    if self._store_qa(
                        "Which characters are most active in conversations?",
                        f"Most active (last 7 days): {chars_str}",
                        "interaction_patterns",
                    ):
                        entries_created += 1

                if avg_lengths:
                    lengths_str = ", ".join(
                        f"{s}: {l} turns" for s, l in sorted(avg_lengths.items())
                    )
                    if self._store_qa(
                        "What is the average conversation length by scene?",
                        f"Average conversation lengths: {lengths_str}",
                        "interaction_patterns",
                    ):
                        entries_created += 1

                patterns_found = (
                    len(avg_lengths)
                    + len(top_characters)
                    + len(peak_hours)
                    + len(top_sequences)
                    + len(training_signals)
                )

                result = {
                    "total_events": len(events),
                    "patterns_found": patterns_found,
                    "entries_created": entries_created,
                    "avg_lengths": avg_lengths,
                    "top_characters": dict(top_characters),
                    "peak_hours": dict(peak_hours),
                    "top_sequences": {
                        f"{a}→{b}": c for (a, b), c in top_sequences
                    },
                    "training_signals": training_signals,
                }
                self._complete_sync(
                    sync,
                    {
                        "events_processed": len(events),
                        "entries_created": entries_created,
                    },
                )
                return result

            except Exception as exc:
                self._fail_sync(sync, str(exc))
                return {
                    "total_events": 0,
                    "patterns_found": 0,
                    "entries_created": 0,
                    "error": str(exc),
                }

    # ──── Scheduler Integration ────

    def _sync_callback(self) -> Dict[str, Any]:
        """Main sync callback for the scheduler daemon.

        Orchestrates all three sync operations and returns combined results.

        Returns:
            Combined result dict from all sync passes.
        """
        logger.info("Conversation sync callback triggered")
        conv_result = self.sync_conversations()
        skill_result = self.sync_skill_usage()
        pattern_result = self.sync_interaction_patterns()

        combined = {
            "conversations": conv_result,
            "skill_usage": skill_result,
            "interaction_patterns": pattern_result,
            "total_events": (
                conv_result.get("events_processed", 0)
                + skill_result.get("total_events", 0)
                + pattern_result.get("total_events", 0)
            ),
            "total_entries": (
                conv_result.get("entries_created", 0)
                + skill_result.get("entries_created", 0)
                + pattern_result.get("entries_created", 0)
            ),
        }
        logger.info(
            "Conversation sync complete — %d events, %d entries",
            combined["total_events"],
            combined["total_entries"],
        )
        return combined

    def register_task(self) -> None:
        """Register a periodic sync task with the scheduler daemon.

        Creates a recurring ``conversation-sync`` task that runs every 2 hours.
        Safe to call multiple times — the scheduler will overwrite duplicate
        task IDs.
        """
        try:
            from engine.nexus.scheduler_daemon import get_scheduler_daemon
            daemon = get_scheduler_daemon()
            daemon.register(
                task_id="conversation-sync",
                name="Scene Conversation Sync",
                schedule=_SYNC_SCHEDULE,
                callback=self._sync_callback,
                enabled=True,
            )
            logger.info("Registered conversation-sync task (%s)", _SYNC_SCHEDULE)
        except Exception as exc:
            logger.warning("Failed to register scheduler task: %s", exc)

    # ──── Public API ────

    def force_sync(self) -> Dict[str, Any]:
        """Run sync immediately regardless of schedule.

        Returns:
            Combined result dict from all sync passes.
        """
        logger.info("Force sync requested")
        return self._sync_callback()

    def get_sync_status(self) -> Dict[str, Any]:
        """Return current sync state and recent history.

        Returns:
            Dict with ``last_sync_timestamp``, ``last_event_id``,
            ``events_pending``, ``total_synced``, and ``recent_syncs``.
        """
        with self._lock:
            last_id = self._get_last_event_id()

            # Read last sync timestamp
            with self._cursor() as cur:
                row = cur.execute(
                    "SELECT value FROM sync_state WHERE key = ?",
                    ("last_sync_timestamp",),
                ).fetchone()
                last_ts = float(row["value"]) if row else 0.0

            # Count pending events in EventChain
            events_pending = 0
            try:
                ec_path = self._get_event_chain_db_path()
                if ec_path.exists():
                    conn = sqlite3.connect(
                        f"file:{ec_path}?mode=ro", uri=True, timeout=5
                    )
                    row = conn.execute(
                        "SELECT COUNT(*) as cnt FROM events "
                        "WHERE rowid > ? AND event_type = ?",
                        (last_id, _EVENT_TYPE_GOVERNED),
                    ).fetchone()
                    events_pending = row[0] if row else 0
                    conn.close()
            except Exception as exc:
                logger.debug("Failed to count pending events: %s", exc)

            # Total synced and recent records
            with self._cursor() as cur:
                total_row = cur.execute(
                    "SELECT COALESCE(SUM(events_processed), 0) as total "
                    "FROM sync_records WHERE status = 'completed'"
                ).fetchone()
                total_synced = total_row["total"] if total_row else 0

                recent_rows = cur.execute(
                    "SELECT * FROM sync_records ORDER BY started_at DESC LIMIT 10"
                ).fetchall()
                recent_syncs = [dict(r) for r in recent_rows]

            return {
                "last_sync_timestamp": last_ts,
                "last_sync_iso": (
                    datetime.fromtimestamp(last_ts).isoformat()
                    if last_ts > 0
                    else None
                ),
                "last_event_id": last_id,
                "events_pending": events_pending,
                "total_synced": total_synced,
                "recent_syncs": recent_syncs,
            }


# ──── Module-Level Singleton ────

_conversation_sync: Optional[ConversationSync] = None
_lock = threading.Lock()


def get_conversation_sync(db_path: str = _DEFAULT_SYNC_DB) -> ConversationSync:
    """Return the global ConversationSync singleton.

    Args:
        db_path: Path to the sync tracking database. Only used on first call.

    Returns:
        The singleton ConversationSync instance.
    """
    global _conversation_sync
    if _conversation_sync is None:
        with _lock:
            if _conversation_sync is None:
                _conversation_sync = ConversationSync(db_path=db_path)
    return _conversation_sync
