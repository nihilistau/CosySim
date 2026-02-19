"""
Event Chain System for CosySim
==============================

Every meaningful action that flows through the system — user messages, LLM calls,
skill invocations, media generation, autonomous triggers, memory writes — is recorded
here as a causally-linked event row.

Why:
  - Full diagnostic visibility: trace exactly how a response was produced
  - Memory compaction input: summarize_chain() agent skill condenses a chain into a
    long-term memory without discarding the raw record
  - Real-time monitoring: the Terminal tab polls /api/events/chain for the current turn
  - Tuning: compare chains across sessions to understand agent behaviour

Chain lifecycle:
  1. start_chain(scene_id)              → chain_id (UUID)
  2. log(..., chain_id=chain_id)        → event_id  (root and child events)
  3. get_chain(chain_id)                → flat ordered list for display
  4. get_chain_as_tree(chain_id)        → causal tree for rich UI rendering
  5. (optional) delete_chain(chain_id) → prune old chains after compaction
"""

import uuid
import json
from datetime import datetime
from typing import Dict, List, Optional, Any
from pathlib import Path
import sys

project_root = Path(__file__).parent.parent.parent.parent
sys.path.insert(0, str(project_root))

from content.simulation.database.db import Database


# ---------------------------------------------------------------------------
# Event type registry — extensible, stored as plain TEXT in the DB
# ---------------------------------------------------------------------------

EVENT_TYPES = frozenset({
    # Conversation flow
    'message_in',          # User/external message received
    'message_out',         # Agent response sent
    # LLM lifecycle
    'llm_request',         # LMStudio inference started
    'llm_response',        # LMStudio inference completed
    'llm_cancelled',       # Prediction cancelled mid-stream
    # RAG / memory
    'rag_query',           # Semantic search issued to ChromaDB
    'rag_result',          # ChromaDB results returned
    'memory_stored',       # Memory written to DB + ChromaDB
    # Skills / tools
    'skill_called',        # A @skill decorated function was invoked
    'skill_result',        # Skill returned a result
    'tool_call',           # LMStudio native tool_call (via .act())
    'tool_result',         # Tool call result from LMStudio
    # Media generation
    'media_generated',     # Image / audio / video produced
    # Autonomous behaviour
    'autonomous_trigger',  # AutonomousMessenger cycle fired
    # Scene / system
    'scene_state_change',  # Scene state mutated (chain open/close, char loaded, etc.)
    'error',               # Exception anywhere in the chain
})


class EventChain:
    """
    Append-only event log with parent_id links forming a causal tree per chain.

    Typical usage (inside PhoneScene._generate_response):

        chain_id = self.event_chain.start_chain('phone', character_id=char.id,
                                                 summary=f'User: {user_msg[:60]}')

        user_ev = self.event_chain.log('message_in', actor='user',
                                        payload={'content': user_msg},
                                        chain_id=chain_id, scene_id='phone',
                                        character_id=char.id)

        llm_ev = self.event_chain.log('llm_request', actor='llm',
                                       payload={'model': model_key, 'prompt_len': ...},
                                       chain_id=chain_id, scene_id='phone',
                                       character_id=char.id, parent_id=user_ev)

        # … call LMStudio …

        self.event_chain.log('llm_response', actor='agent',
                              payload={'content': response, 'tokens': ...},
                              chain_id=chain_id, scene_id='phone',
                              character_id=char.id, parent_id=llm_ev)
    """

    def __init__(self, db: Optional[Database] = None):
        self.db = db or Database()

    # ------------------------------------------------------------------
    # Chain management
    # ------------------------------------------------------------------

    def start_chain(
        self,
        scene_id: str,
        character_id: Optional[str] = None,
        summary: str = '',
    ) -> str:
        """
        Begin a new event chain. Returns the chain_id UUID.

        Logs a root 'scene_state_change' event so the chain has at least one row
        and appears in get_recent_chains() immediately.
        """
        chain_id = str(uuid.uuid4())
        self.log(
            event_type='scene_state_change',
            actor='system',
            payload={'action': 'chain_started', 'scene_id': scene_id},
            summary=summary or f'Chain opened in {scene_id}',
            chain_id=chain_id,
            scene_id=scene_id,
            character_id=character_id,
            parent_id=None,
        )
        return chain_id

    # ------------------------------------------------------------------
    # Logging
    # ------------------------------------------------------------------

    def log(
        self,
        event_type: str,
        actor: str,
        payload: Any,
        summary: str = '',
        chain_id: Optional[str] = None,
        scene_id: str = 'unknown',
        character_id: Optional[str] = None,
        parent_id: Optional[str] = None,
    ) -> str:
        """
        Append one event row. Returns the new event_id.

        Args:
            event_type:   One of EVENT_TYPES (or any string — new types are valid)
            actor:        Who fired this — 'user', 'agent', 'system', 'llm',
                          'skill:<name>', 'mcp:<server>'
            payload:      JSON-serialisable dict/list/scalar with full input + output
            summary:      Short human-readable label shown in the diagnostics panel
            chain_id:     Groups events belonging to one turn/cycle.
                          Auto-generated if None (creates an orphan chain).
            scene_id:     Scene that owns this chain ('phone', 'bedroom', 'unknown')
            character_id: Character involved (nullable for system events)
            parent_id:    event_id of the cause — creates the causal tree edge.
                          None for root events.
        """
        event_id = str(uuid.uuid4())
        timestamp = datetime.now().isoformat()

        if isinstance(payload, (dict, list)):
            payload_json = json.dumps(payload, default=str)
        else:
            payload_json = json.dumps({'value': str(payload)})

        effective_chain = chain_id or str(uuid.uuid4())

        with self.db.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                """
                INSERT INTO events
                    (id, chain_id, parent_id, scene_id, character_id,
                     event_type, actor, payload, summary, timestamp)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    event_id, effective_chain, parent_id, scene_id,
                    character_id, event_type, actor, payload_json,
                    summary, timestamp,
                ),
            )

        return event_id

    def log_error(
        self,
        error: Exception,
        chain_id: Optional[str] = None,
        scene_id: str = 'unknown',
        character_id: Optional[str] = None,
        parent_id: Optional[str] = None,
        context: Optional[Dict] = None,
    ) -> str:
        """Convenience wrapper for logging exceptions into a chain."""
        return self.log(
            event_type='error',
            actor='system',
            payload={
                'error_type': type(error).__name__,
                'message': str(error),
                **(context or {}),
            },
            summary=f'Error: {type(error).__name__}: {str(error)[:80]}',
            chain_id=chain_id,
            scene_id=scene_id,
            character_id=character_id,
            parent_id=parent_id,
        )

    # ------------------------------------------------------------------
    # Retrieval
    # ------------------------------------------------------------------

    def get_event(self, event_id: str) -> Optional[Dict]:
        """Fetch a single event by ID."""
        with self.db.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute('SELECT * FROM events WHERE id = ?', (event_id,))
            row = cursor.fetchone()
            if row:
                e = dict(row)
                e['payload'] = json.loads(e['payload']) if e['payload'] else {}
                return e
            return None

    def get_chain(self, chain_id: str) -> List[Dict]:
        """
        Return all events in a chain as a flat list ordered by timestamp (oldest first).
        This is the raw unfiltered record — nothing is omitted.
        """
        with self.db.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                'SELECT * FROM events WHERE chain_id = ? ORDER BY timestamp ASC',
                (chain_id,),
            )
            events = []
            for row in cursor.fetchall():
                e = dict(row)
                e['payload'] = json.loads(e['payload']) if e['payload'] else {}
                events.append(e)
            return events

    def get_chain_as_tree(self, chain_id: str) -> Dict:
        """
        Return the chain as a nested tree based on parent_id edges.

        Structure:
          {
            'chain_id': <chain_id>,
            'events': [           # root events (parent_id IS NULL or points outside chain)
              {
                ...event fields...,
                'children': [     # events whose parent_id == this event's id
                  { ...event..., 'children': [...] },
                  ...
                ]
              },
              ...
            ]
          }

        Root events are those with parent_id = None or a parent outside this chain.
        Useful for rendering the causal tree in the diagnostics panel.
        """
        events = self.get_chain(chain_id)
        chain_ids = {e['id'] for e in events}
        by_id: Dict[str, Dict] = {e['id']: {**e, 'children': []} for e in events}
        roots: List[Dict] = []

        for e in by_id.values():
            pid = e.get('parent_id')
            if pid and pid in chain_ids:
                by_id[pid]['children'].append(e)
            else:
                roots.append(e)

        return {'chain_id': chain_id, 'events': roots}

    def get_recent_chains(
        self,
        scene_id: Optional[str] = None,
        character_id: Optional[str] = None,
        limit: int = 20,
    ) -> List[Dict]:
        """
        Return summary rows for the most recent chains (one row per chain_id).

        Columns returned: chain_id, scene_id, character_id, started_at,
                          ended_at, event_count, summary (first event's summary).
        """
        with self.db.get_connection() as conn:
            cursor = conn.cursor()

            where_clauses = []
            params: List[Any] = []
            if scene_id:
                where_clauses.append('scene_id = ?')
                params.append(scene_id)
            if character_id:
                where_clauses.append('character_id = ?')
                params.append(character_id)

            where_sql = ('WHERE ' + ' AND '.join(where_clauses)) if where_clauses else ''
            params.append(limit)

            cursor.execute(
                f"""
                SELECT
                    chain_id,
                    scene_id,
                    character_id,
                    MIN(timestamp) AS started_at,
                    MAX(timestamp) AS ended_at,
                    COUNT(*)       AS event_count,
                    (
                        SELECT summary FROM events e2
                        WHERE e2.chain_id = e.chain_id
                        ORDER BY e2.timestamp ASC
                        LIMIT 1
                    ) AS summary
                FROM events e
                {where_sql}
                GROUP BY chain_id
                ORDER BY started_at DESC
                LIMIT ?
                """,
                params,
            )
            return [dict(row) for row in cursor.fetchall()]

    def get_events_by_type(
        self,
        event_type: str,
        chain_id: Optional[str] = None,
        limit: int = 50,
    ) -> List[Dict]:
        """Retrieve events filtered by type, optionally within a chain."""
        with self.db.get_connection() as conn:
            cursor = conn.cursor()
            if chain_id:
                cursor.execute(
                    'SELECT * FROM events WHERE event_type = ? AND chain_id = ? '
                    'ORDER BY timestamp DESC LIMIT ?',
                    (event_type, chain_id, limit),
                )
            else:
                cursor.execute(
                    'SELECT * FROM events WHERE event_type = ? '
                    'ORDER BY timestamp DESC LIMIT ?',
                    (event_type, limit),
                )
            events = []
            for row in cursor.fetchall():
                e = dict(row)
                e['payload'] = json.loads(e['payload']) if e['payload'] else {}
                events.append(e)
            return events

    # ------------------------------------------------------------------
    # Maintenance
    # ------------------------------------------------------------------

    def delete_chain(self, chain_id: str) -> int:
        """
        Delete all events in a chain. Returns count of deleted rows.

        Safe to call after a chain has been compacted into a memory via
        the summarize_chain skill — the raw record is no longer needed.
        """
        with self.db.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute('DELETE FROM events WHERE chain_id = ?', (chain_id,))
            return cursor.rowcount

    def get_event_count(
        self,
        chain_id: Optional[str] = None,
        scene_id: Optional[str] = None,
    ) -> int:
        """Count events, optionally scoped to a chain or scene."""
        with self.db.get_connection() as conn:
            cursor = conn.cursor()
            if chain_id:
                cursor.execute('SELECT COUNT(*) FROM events WHERE chain_id = ?', (chain_id,))
            elif scene_id:
                cursor.execute('SELECT COUNT(*) FROM events WHERE scene_id = ?', (scene_id,))
            else:
                cursor.execute('SELECT COUNT(*) FROM events')
            return cursor.fetchone()[0]

    def prune_old_chains(self, keep_latest: int = 500) -> int:
        """
        Delete chains beyond the most recent `keep_latest` to prevent unbounded growth.
        Chains are ordered by their most recent event timestamp.
        Returns number of chains deleted.
        """
        with self.db.get_connection() as conn:
            cursor = conn.cursor()
            # Find chain_ids to keep
            cursor.execute(
                """
                SELECT chain_id FROM (
                    SELECT chain_id, MAX(timestamp) AS last_event
                    FROM events
                    GROUP BY chain_id
                    ORDER BY last_event DESC
                    LIMIT ?
                )
                """,
                (keep_latest,),
            )
            keep_ids = {row[0] for row in cursor.fetchall()}
            if not keep_ids:
                return 0
            placeholders = ','.join('?' * len(keep_ids))
            cursor.execute(
                f'SELECT COUNT(DISTINCT chain_id) FROM events WHERE chain_id NOT IN ({placeholders})',
                list(keep_ids),
            )
            to_delete = cursor.fetchone()[0]
            cursor.execute(
                f'DELETE FROM events WHERE chain_id NOT IN ({placeholders})',
                list(keep_ids),
            )
            return to_delete


# ---------------------------------------------------------------------------
# Module-level singleton helper — same pattern as get_llm_service()
# ---------------------------------------------------------------------------

_chain_instance: Optional[EventChain] = None


def get_event_chain(db: Optional[Database] = None) -> EventChain:
    """Return the process-level EventChain singleton."""
    global _chain_instance
    if _chain_instance is None:
        _chain_instance = EventChain(db=db)
    return _chain_instance


if __name__ == '__main__':
    # Quick smoke-test
    ec = EventChain()
    chain = ec.start_chain('phone', summary='Test chain')
    ev1 = ec.log('message_in', 'user', {'content': 'Hello!'}, chain_id=chain, scene_id='phone')
    ev2 = ec.log('llm_request', 'llm', {'model': 'test-model'}, chain_id=chain,
                  scene_id='phone', parent_id=ev1)
    ev3 = ec.log('llm_response', 'agent', {'content': 'Hi there!'}, chain_id=chain,
                  scene_id='phone', parent_id=ev2)

    flat = ec.get_chain(chain)
    tree = ec.get_chain_as_tree(chain)

    print(f'Chain {chain[:8]}... has {len(flat)} events')
    for e in flat:
        indent = '  ' if e['parent_id'] else ''
        print(f'{indent}[{e["event_type"]}] {e["actor"]}: {e["summary"] or list(e["payload"].keys())}')

    print(f'\nTree roots: {len(tree["events"])}')
    print('\n✅ EventChain system working')
