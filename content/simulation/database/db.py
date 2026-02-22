"""
SQLite Database Management for CosySim
=======================================

Central CRUD layer for all simulation data: characters, personalities, roles,
conversations, interactions, media, character states, and events.

Every public method:
  - Uses parameterised queries (no SQL injection)
  - Returns typed results (Dict, List[Dict], bool, str, int)
  - Logs errors via the standard ``logging`` module
  - Validates column names against whitelists before any dynamic SQL

Usage::

    from content.simulation.database.db import Database
    db = Database()                       # default path
    db = Database("path/to/custom.db")    # custom path

    char_id = db.create_character(name="Luna", age=22)
    char    = db.get_character(char_id)
    db.update_character(char_id, mood="happy")
    db.delete_character(char_id)
"""
import sqlite3
import json
import logging
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional, Any, Tuple
import uuid
from contextlib import contextmanager

logger = logging.getLogger(__name__)


class Database:
    """Central SQLite database for the simulation system"""
    
    def __init__(self, db_path: str = "simulation/simulation.db"):
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self.init_database()
    
    @contextmanager
    def get_connection(self):
        """Context manager for database connections"""
        conn = sqlite3.connect(str(self.db_path))
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")
        try:
            yield conn
            conn.commit()
        except Exception as e:
            conn.rollback()
            raise e
        finally:
            conn.close()
    
    def init_database(self):
        """Initialize all database tables"""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            
            # Characters table
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS characters (
                    id TEXT PRIMARY KEY,
                    name TEXT NOT NULL,
                    age INTEGER,
                    sex TEXT,
                    hair_color TEXT,
                    eye_color TEXT,
                    height TEXT,
                    body_type TEXT,
                    personality_id TEXT,
                    tags TEXT,
                    metadata TEXT,
                    created_at TEXT NOT NULL,
                    updated_at TEXT,
                    FOREIGN KEY (personality_id) REFERENCES personalities(id)
                )
            """)
            
            # Personalities table
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS personalities (
                    id TEXT PRIMARY KEY,
                    name TEXT NOT NULL UNIQUE,
                    system_prompt TEXT NOT NULL,
                    traits TEXT,
                    communication_style TEXT,
                    sexual_openness REAL DEFAULT 0.5,
                    personality_values TEXT,
                    created_at TEXT NOT NULL
                )
            """)
            
            # Roles table
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS roles (
                    id TEXT PRIMARY KEY,
                    name TEXT NOT NULL UNIQUE,
                    description TEXT,
                    required_traits TEXT,
                    context TEXT,
                    scenario TEXT,
                    created_at TEXT NOT NULL
                )
            """)
            
            # Memories table (metadata for RAG)
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS memories (
                    id TEXT PRIMARY KEY,
                    character_id TEXT NOT NULL,
                    content TEXT NOT NULL,
                    importance REAL DEFAULT 0.5,
                    emotion TEXT,
                    timestamp TEXT NOT NULL,
                    metadata TEXT,
                    FOREIGN KEY (character_id) REFERENCES characters(id)
                )
            """)
            
            # Conversations table
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS conversations (
                    id TEXT PRIMARY KEY,
                    character_id TEXT NOT NULL,
                    role_id TEXT,
                    chain_id TEXT NOT NULL,
                    messages TEXT NOT NULL,
                    started_at TEXT NOT NULL,
                    ended_at TEXT,
                    metadata TEXT,
                    FOREIGN KEY (character_id) REFERENCES characters(id),
                    FOREIGN KEY (role_id) REFERENCES roles(id)
                )
            """)
            
            # Interactions table
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS interactions (
                    id TEXT PRIMARY KEY,
                    type TEXT NOT NULL,
                    character_id TEXT NOT NULL,
                    content TEXT NOT NULL,
                    metadata TEXT,
                    timestamp TEXT NOT NULL,
                    chain_id TEXT,
                    FOREIGN KEY (character_id) REFERENCES characters(id)
                )
            """)
            
            # Media table
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS media (
                    id TEXT PRIMARY KEY,
                    character_id TEXT NOT NULL,
                    type TEXT NOT NULL,
                    filepath TEXT NOT NULL,
                    thumbnail TEXT,
                    metadata TEXT,
                    created_at TEXT NOT NULL,
                    FOREIGN KEY (character_id) REFERENCES characters(id)
                )
            """)
            
            # Character states table (for tracking mood, relationship, etc.)
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS character_states (
                    id TEXT PRIMARY KEY,
                    character_id TEXT NOT NULL UNIQUE,
                    mood TEXT DEFAULT 'neutral',
                    energy REAL DEFAULT 0.8,
                    relationship_level REAL DEFAULT 0.0,
                    arousal REAL DEFAULT 0.0,
                    last_interaction TEXT,
                    metadata TEXT,
                    updated_at TEXT NOT NULL,
                    FOREIGN KEY (character_id) REFERENCES characters(id)
                )
            """)
            
            # Events table — causal event chain for diagnostics and memory compaction
            # NOTE: No FK on character_id — EventChain is the ground truth and must
            # log events for any actor, even if the character isn't in the DB yet.
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS events (
                    id TEXT PRIMARY KEY,
                    chain_id TEXT NOT NULL,
                    parent_id TEXT,
                    scene_id TEXT NOT NULL DEFAULT 'unknown',
                    character_id TEXT,
                    event_type TEXT NOT NULL,
                    actor TEXT NOT NULL,
                    payload TEXT NOT NULL,
                    summary TEXT DEFAULT '',
                    timestamp TEXT NOT NULL,
                    FOREIGN KEY (parent_id) REFERENCES events(id)
                )
            """)

            # ── Character relationships (per-pair) ──
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS character_relationships (
                    id TEXT PRIMARY KEY,
                    character_a_id TEXT NOT NULL,
                    character_b_id TEXT NOT NULL,
                    relationship_level REAL DEFAULT 0.5,
                    trust REAL DEFAULT 0.5,
                    attraction REAL DEFAULT 0.5,
                    arousal_a REAL DEFAULT 0.0,
                    arousal_b REAL DEFAULT 0.0,
                    interaction_count INTEGER DEFAULT 0,
                    last_interaction TEXT,
                    metadata TEXT DEFAULT '{}',
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    UNIQUE(character_a_id, character_b_id)
                )
            """)

            # Create indexes for performance
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_memories_character ON memories(character_id)")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_conversations_character ON conversations(character_id)")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_interactions_character ON interactions(character_id)")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_interactions_chain ON interactions(chain_id)")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_media_character ON media(character_id)")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_events_chain ON events(chain_id)")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_events_scene ON events(scene_id)")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_events_character ON events(character_id)")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_rel_a ON character_relationships(character_a_id)")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_rel_b ON character_relationships(character_b_id)")

        # Apply column migrations for existing databases
        self._migrate_schema()
        # Ensure default characters exist
        self.seed_default_characters()
    
    def _migrate_schema(self):
        """
        Safely add new columns to existing databases.
        Uses PRAGMA table_info to check before ALTER TABLE — idempotent.
        """
        # Whitelist for security - prevent SQL injection
        VALID_TABLES = {'characters', 'personalities', 'character_states'}
        VALID_COLUMNS = {'nsfw_enabled', 'warmth', 'formality', 'humor', 
                         'flirtiness', 'intelligence', 'creativity'}
        
        migrations = {
            'characters': [
                ('nsfw_enabled', 'INTEGER DEFAULT 0'),
            ],
            'personalities': [
                ('warmth',       'REAL DEFAULT 0.5'),
                ('formality',    'REAL DEFAULT 0.5'),
                ('humor',        'REAL DEFAULT 0.5'),
                ('flirtiness',   'REAL DEFAULT 0.5'),
                ('intelligence', 'REAL DEFAULT 0.5'),
                ('creativity',   'REAL DEFAULT 0.5'),
            ],
            'character_states': [
                ('warmth',       'REAL DEFAULT 0.5'),
                ('formality',    'REAL DEFAULT 0.5'),
                ('humor',        'REAL DEFAULT 0.5'),
                ('flirtiness',   'REAL DEFAULT 0.5'),
                ('intelligence', 'REAL DEFAULT 0.5'),
                ('creativity',   'REAL DEFAULT 0.5'),
            ],
        }
        with self.get_connection() as conn:
            cursor = conn.cursor()
            for table, columns in migrations.items():
                if table not in VALID_TABLES:
                    raise ValueError(f"Invalid table name: {table}")
                cursor.execute(f"PRAGMA table_info({table})")
                existing = {row[1] for row in cursor.fetchall()}
                for col_name, col_def in columns:
                    if col_name not in VALID_COLUMNS:
                        raise ValueError(f"Invalid column name: {col_name}")
                    if col_name not in existing:
                        cursor.execute(f"ALTER TABLE {table} ADD COLUMN {col_name} {col_def}")

    # ============= CHARACTER OPERATIONS =============
    
    def create_character(self, name: str, **kwargs) -> str:
        """Create a new character"""
        char_id = str(uuid.uuid4())
        timestamp = datetime.now().isoformat()
        
        tags = json.dumps(kwargs.get('tags', []))
        metadata = json.dumps(kwargs.get('metadata', {}))
        nsfw_enabled = 1 if kwargs.get('nsfw_enabled') else 0
        
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                INSERT INTO characters 
                (id, name, age, sex, hair_color, eye_color, height, body_type, 
                 personality_id, tags, metadata, nsfw_enabled, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                char_id, name, 
                kwargs.get('age'), kwargs.get('sex'),
                kwargs.get('hair_color'), kwargs.get('eye_color'),
                kwargs.get('height'), kwargs.get('body_type'),
                kwargs.get('personality_id'),
                tags, metadata, nsfw_enabled, timestamp, timestamp
            ))
            
            # Seed character_state traits from personality if provided
            trait_defaults = {'warmth': 0.5, 'formality': 0.5, 'humor': 0.5,
                              'flirtiness': 0.5, 'intelligence': 0.5, 'creativity': 0.5}
            if kwargs.get('personality_id'):
                cursor.execute(
                    "SELECT warmth, formality, humor, flirtiness, intelligence, creativity "
                    "FROM personalities WHERE id = ?",
                    (kwargs['personality_id'],)
                )
                row = cursor.fetchone()
                if row:
                    trait_defaults = {
                        'warmth': row[0] or 0.5, 'formality': row[1] or 0.5,
                        'humor': row[2] or 0.5,   'flirtiness': row[3] or 0.5,
                        'intelligence': row[4] or 0.5, 'creativity': row[5] or 0.5,
                    }

            # Initialize character state with seeded traits
            cursor.execute("""
                INSERT INTO character_states 
                (id, character_id, warmth, formality, humor, flirtiness, intelligence, creativity, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                str(uuid.uuid4()), char_id,
                trait_defaults['warmth'], trait_defaults['formality'],
                trait_defaults['humor'], trait_defaults['flirtiness'],
                trait_defaults['intelligence'], trait_defaults['creativity'],
                timestamp
            ))
        
        return char_id
    
    def get_character(self, char_id: str) -> Optional[Dict]:
        """Get character by ID"""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM characters WHERE id = ?", (char_id,))
            row = cursor.fetchone()
            
            if row:
                char = dict(row)
                char['tags'] = json.loads(char['tags']) if char['tags'] else []
                char['metadata'] = json.loads(char['metadata']) if char['metadata'] else {}
                return char
            return None
    
    def get_all_characters(self) -> List[Dict]:
        """Get all characters"""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM characters ORDER BY created_at DESC")
            rows = cursor.fetchall()
            
            characters = []
            for row in rows:
                char = dict(row)
                char['tags'] = json.loads(char['tags']) if char['tags'] else []
                char['metadata'] = json.loads(char['metadata']) if char['metadata'] else {}
                characters.append(char)
            
            return characters

    def seed_default_characters(self) -> int:
        """Seed the database with well-known characters if they don't exist.

        Returns the number of characters inserted.
        """
        defaults = [
            {"id": "lola",    "name": "Lola Voss",       "age": 29, "sex": "female",
             "hair_color": "dark brunette", "eye_color": "deep brown", "height": "5'6",
             "personality_id": None, "tags": ["lounge", "singer"],
             "metadata": {"backstory": "Fled Vienna in 1919, built The Velvet Lounge from nothing."}},
            {"id": "viktor",  "name": "Viktor Marlowe",  "age": 38, "sex": "male",
             "hair_color": "dark with grey", "eye_color": "pale grey", "height": "6'2",
             "personality_id": None, "tags": ["lounge", "bartender"],
             "metadata": {"backstory": "A past he doesn't discuss. Measures people like spirits."}},
            {"id": "aria",    "name": "Aria",             "age": 22, "sex": "female",
             "hair_color": "platinum blonde", "eye_color": "blue", "height": "5'4",
             "personality_id": None, "tags": ["phone", "companion"],
             "metadata": {"backstory": "Your playful, flirty companion on CosyPhone."}},
            {"id": "frankie", "name": "Frankie DeLuca",   "age": 45, "sex": "male",
             "hair_color": "slicked black", "eye_color": "dark", "height": "5'11",
             "personality_id": None, "tags": ["casino", "dealer"],
             "metadata": {"backstory": "The Midnight Casino's head dealer. Smooth operator."}},
            {"id": "mira",    "name": "Mira Vex",         "age": 28, "sex": "female",
             "hair_color": "red", "eye_color": "green", "height": "5'7",
             "personality_id": None, "tags": ["casino", "hustler"],
             "metadata": {"backstory": "Card shark and confidence artist. Never loses twice."}},
        ]
        inserted = 0
        for ch in defaults:
            if self.get_character(ch["id"]) is not None:
                continue
            with self.get_connection() as conn:
                cursor = conn.cursor()
                ts = datetime.now().isoformat()
                cursor.execute("""
                    INSERT INTO characters
                    (id, name, age, sex, hair_color, eye_color, height, body_type,
                     personality_id, tags, metadata, nsfw_enabled, created_at, updated_at)
                    VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                    (ch["id"], ch["name"], ch.get("age"), ch.get("sex"),
                     ch.get("hair_color"), ch.get("eye_color"), ch.get("height"), None,
                     ch.get("personality_id"), json.dumps(ch.get("tags", [])),
                     json.dumps(ch.get("metadata", {})), 0, ts, ts))
                # Seed character state
                cursor.execute("""
                    INSERT OR IGNORE INTO character_states
                    (id, character_id, warmth, formality, humor, flirtiness, intelligence, creativity, updated_at)
                    VALUES (?,?,?,?,?,?,?,?,?)""",
                    (str(uuid.uuid4()), ch["id"], 0.5, 0.5, 0.5, 0.5, 0.5, 0.5, ts))
            inserted += 1
        return inserted
    
    def update_character(self, char_id: str, **kwargs) -> bool:
        """Update character attributes"""
        # Whitelist of allowed columns to prevent SQL injection
        ALLOWED_COLUMNS = {
            'name', 'age', 'sex', 'hair_color', 'eye_color', 'height', 'body_type',
            'personality_id', 'tags', 'metadata', 'nsfw_enabled',
        }
        
        timestamp = datetime.now().isoformat()
        
        updates = []
        values = []
        
        for key, value in kwargs.items():
            # Validate column name against whitelist
            if key not in ALLOWED_COLUMNS:
                raise ValueError(f"Invalid column name: {key}")
            
            if key in ['tags', 'metadata']:
                value = json.dumps(value)
            updates.append(f"{key} = ?")
            values.append(value)
        
        if not updates:
            return False
        
        updates.append("updated_at = ?")
        values.append(timestamp)
        values.append(char_id)
        
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(f"""
                UPDATE characters 
                SET {', '.join(updates)}
                WHERE id = ?
            """, values)
            
            return cursor.rowcount > 0
    
    def delete_character(self, char_id: str) -> bool:
        """Delete character and all related data"""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            
            # Delete related data
            cursor.execute("DELETE FROM memories WHERE character_id = ?", (char_id,))
            cursor.execute("DELETE FROM conversations WHERE character_id = ?", (char_id,))
            cursor.execute("DELETE FROM interactions WHERE character_id = ?", (char_id,))
            cursor.execute("DELETE FROM media WHERE character_id = ?", (char_id,))
            cursor.execute("DELETE FROM character_states WHERE character_id = ?", (char_id,))
            
            # Delete character
            cursor.execute("DELETE FROM characters WHERE id = ?", (char_id,))
            
            return cursor.rowcount > 0
    
    # ============= PERSONALITY OPERATIONS =============
    
    def create_personality(self, name: str, system_prompt: str, **kwargs) -> str:
        """Create a new personality"""
        pers_id = str(uuid.uuid4())
        timestamp = datetime.now().isoformat()
        
        traits = json.dumps(kwargs.get('traits', []))
        communication_style = json.dumps(kwargs.get('communication_style', {}))
        personality_values = json.dumps(kwargs.get('values', []))
        
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                INSERT INTO personalities 
                (id, name, system_prompt, traits, communication_style, 
                 sexual_openness, personality_values,
                 warmth, formality, humor, flirtiness, intelligence, creativity,
                 created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                pers_id, name, system_prompt, traits, communication_style,
                kwargs.get('sexual_openness', 0.5), personality_values,
                kwargs.get('warmth', 0.5), kwargs.get('formality', 0.5),
                kwargs.get('humor', 0.5), kwargs.get('flirtiness', 0.5),
                kwargs.get('intelligence', 0.5), kwargs.get('creativity', 0.5),
                timestamp
            ))
        
        return pers_id
    
    def get_personality(self, pers_id: str) -> Optional[Dict]:
        """Get personality by ID"""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM personalities WHERE id = ?", (pers_id,))
            row = cursor.fetchone()
            
            if row:
                pers = dict(row)
                pers['traits'] = json.loads(pers['traits']) if pers['traits'] else []
                pers['communication_style'] = json.loads(pers['communication_style']) if pers['communication_style'] else {}
                pers['values'] = json.loads(pers['personality_values']) if pers.get('personality_values') else []
                return pers
            return None
    
    def get_personality_by_name(self, name: str) -> Optional[Dict]:
        """Get personality by name"""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM personalities WHERE name = ?", (name,))
            row = cursor.fetchone()
            
            if row:
                pers = dict(row)
                pers['traits'] = json.loads(pers['traits']) if pers['traits'] else []
                pers['communication_style'] = json.loads(pers['communication_style']) if pers['communication_style'] else {}
                pers['values'] = json.loads(pers['personality_values']) if pers['personality_values'] else []
                return pers
            return None
    
    def get_all_personalities(self) -> List[Dict]:
        """Get all personalities"""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM personalities ORDER BY name")
            rows = cursor.fetchall()
            
            personalities = []
            for row in rows:
                pers = dict(row)
                pers['traits'] = json.loads(pers['traits']) if pers['traits'] else []
                pers['communication_style'] = json.loads(pers['communication_style']) if pers['communication_style'] else {}
                pers['values'] = json.loads(pers['personality_values']) if pers['personality_values'] else []
                personalities.append(pers)
            
            return personalities
    
    def update_personality(self, pers_id: str, **kwargs) -> bool:
        """Update a personality's attributes.
        
        Allowed fields: name, system_prompt, traits, communication_style,
        sexual_openness, warmth, formality, humor, flirtiness, intelligence, creativity.
        """
        ALLOWED = {
            'name', 'system_prompt', 'traits', 'communication_style',
            'sexual_openness', 'personality_values',
            'warmth', 'formality', 'humor', 'flirtiness', 'intelligence', 'creativity',
        }
        updates, values = [], []
        for key, value in kwargs.items():
            if key not in ALLOWED:
                raise ValueError(f"Invalid personality column: {key}")
            if key in ('traits', 'communication_style', 'personality_values'):
                value = json.dumps(value)
            updates.append(f"{key} = ?")
            values.append(value)
        if not updates:
            return False
        values.append(pers_id)
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                f"UPDATE personalities SET {', '.join(updates)} WHERE id = ?",
                values,
            )
            return cursor.rowcount > 0

    def delete_personality(self, pers_id: str) -> bool:
        """Delete a personality. Characters referencing it keep their personality_id
        but will need reassignment."""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("DELETE FROM personalities WHERE id = ?", (pers_id,))
            return cursor.rowcount > 0
    
    # ============= ROLE OPERATIONS =============
    
    def create_role(self, name: str, description: str, **kwargs) -> str:
        """Create a new role"""
        role_id = str(uuid.uuid4())
        timestamp = datetime.now().isoformat()
        
        required_traits = json.dumps(kwargs.get('required_traits', []))
        context = kwargs.get('context', '')
        scenario = kwargs.get('scenario', '')
        
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                INSERT INTO roles 
                (id, name, description, required_traits, context, scenario, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?)
            """, (role_id, name, description, required_traits, context, scenario, timestamp))
        
        return role_id
    
    def get_role(self, role_id: str) -> Optional[Dict]:
        """Get role by ID"""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM roles WHERE id = ?", (role_id,))
            row = cursor.fetchone()
            
            if row:
                role = dict(row)
                role['required_traits'] = json.loads(role['required_traits']) if role['required_traits'] else []
                return role
            return None
    
    def get_all_roles(self) -> List[Dict]:
        """Get all roles"""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM roles ORDER BY name")
            rows = cursor.fetchall()
            
            roles = []
            for row in rows:
                role = dict(row)
                role['required_traits'] = json.loads(role['required_traits']) if role['required_traits'] else []
                roles.append(role)
            
            return roles
    
    def update_role(self, role_id: str, **kwargs) -> bool:
        """Update a role's attributes.
        
        Allowed fields: name, description, required_traits, context, scenario.
        """
        ALLOWED = {'name', 'description', 'required_traits', 'context', 'scenario'}
        updates, values = [], []
        for key, value in kwargs.items():
            if key not in ALLOWED:
                raise ValueError(f"Invalid role column: {key}")
            if key == 'required_traits':
                value = json.dumps(value)
            updates.append(f"{key} = ?")
            values.append(value)
        if not updates:
            return False
        values.append(role_id)
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                f"UPDATE roles SET {', '.join(updates)} WHERE id = ?",
                values,
            )
            return cursor.rowcount > 0

    def delete_role(self, role_id: str) -> bool:
        """Delete a role by ID."""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("DELETE FROM roles WHERE id = ?", (role_id,))
            return cursor.rowcount > 0
    
    # ============= MEMORY OPERATIONS =============
    
    def add_memory(self, character_id: str, content: str, **kwargs) -> str:
        """Add a memory entry"""
        mem_id = str(uuid.uuid4())
        timestamp = datetime.now().isoformat()
        
        metadata = json.dumps(kwargs.get('metadata', {}))
        
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                INSERT INTO memories 
                (id, character_id, content, importance, emotion, timestamp, metadata)
                VALUES (?, ?, ?, ?, ?, ?, ?)
            """, (
                mem_id, character_id, content,
                kwargs.get('importance', 0.5),
                kwargs.get('emotion'),
                timestamp, metadata
            ))
        
        return mem_id
    
    def get_character_memories(self, character_id: str, limit: int = 100) -> List[Dict]:
        """Get memories for a character"""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                SELECT * FROM memories 
                WHERE character_id = ?
                ORDER BY importance DESC, timestamp DESC
                LIMIT ?
            """, (character_id, limit))
            rows = cursor.fetchall()
            
            memories = []
            for row in rows:
                mem = dict(row)
                mem['metadata'] = json.loads(mem['metadata']) if mem['metadata'] else {}
                memories.append(mem)
            
            return memories
    
    def update_memory(self, memory_id: str, **kwargs) -> bool:
        """Update a memory entry's content and/or importance"""
        ALLOWED = {'content', 'importance', 'emotion', 'metadata'}
        updates = []
        values = []
        for key, value in kwargs.items():
            if key not in ALLOWED:
                raise ValueError(f"Invalid memory column: {key}")
            if key == 'metadata':
                value = json.dumps(value)
            updates.append(f"{key} = ?")
            values.append(value)
        if not updates:
            return False
        values.append(memory_id)
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                f"UPDATE memories SET {', '.join(updates)} WHERE id = ?",
                values
            )
            return cursor.rowcount > 0

    def delete_memory(self, memory_id: str) -> bool:
        """Delete a memory entry by ID"""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("DELETE FROM memories WHERE id = ?", (memory_id,))
            return cursor.rowcount > 0

    # ============= CONVERSATION OPERATIONS =============
    
    def create_conversation(self, character_id: str, chain_id: str, **kwargs) -> str:
        """Create a new conversation"""
        conv_id = str(uuid.uuid4())
        timestamp = datetime.now().isoformat()
        
        messages = json.dumps(kwargs.get('messages', []))
        metadata = json.dumps(kwargs.get('metadata', {}))
        
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                INSERT INTO conversations 
                (id, character_id, role_id, chain_id, messages, started_at, metadata)
                VALUES (?, ?, ?, ?, ?, ?, ?)
            """, (
                conv_id, character_id, kwargs.get('role_id'),
                chain_id, messages, timestamp, metadata
            ))
        
        return conv_id
    
    def update_conversation(self, conv_id: str, messages: List[Dict], ended: bool = False) -> bool:
        """Update conversation messages"""
        messages_json = json.dumps(messages)
        
        with self.get_connection() as conn:
            cursor = conn.cursor()
            
            if ended:
                timestamp = datetime.now().isoformat()
                cursor.execute("""
                    UPDATE conversations 
                    SET messages = ?, ended_at = ?
                    WHERE id = ?
                """, (messages_json, timestamp, conv_id))
            else:
                cursor.execute("""
                    UPDATE conversations 
                    SET messages = ?
                    WHERE id = ?
                """, (messages_json, conv_id))
            
            return cursor.rowcount > 0
    
    def get_conversation(self, conv_id: str) -> Optional[Dict]:
        """Get conversation by ID"""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM conversations WHERE id = ?", (conv_id,))
            row = cursor.fetchone()
            
            if row:
                conv = dict(row)
                conv['messages'] = json.loads(conv['messages'])
                conv['metadata'] = json.loads(conv['metadata']) if conv['metadata'] else {}
                return conv
            return None
    
    def get_character_conversations(self, character_id: str, limit: int = 10) -> List[Dict]:
        """Get recent conversations for a character"""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                SELECT * FROM conversations 
                WHERE character_id = ?
                ORDER BY started_at DESC
                LIMIT ?
            """, (character_id, limit))
            rows = cursor.fetchall()
            
            conversations = []
            for row in rows:
                conv = dict(row)
                conv['messages'] = json.loads(conv['messages'])
                conv['metadata'] = json.loads(conv['metadata']) if conv['metadata'] else {}
                conversations.append(conv)
            
            return conversations
    
    def delete_conversation(self, conv_id: str) -> bool:
        """Delete a conversation by ID."""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("DELETE FROM conversations WHERE id = ?", (conv_id,))
            return cursor.rowcount > 0

    def delete_character_conversations(self, character_id: str) -> int:
        """Delete all conversations for a character. Returns count deleted."""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("DELETE FROM conversations WHERE character_id = ?", (character_id,))
            return cursor.rowcount
    
    # ============= INTERACTION OPERATIONS =============
    
    def log_interaction(self, interaction_type: str, character_id: str, content: str, **kwargs) -> str:
        """Log an interaction"""
        inter_id = str(uuid.uuid4())
        timestamp = datetime.now().isoformat()
        
        metadata = json.dumps(kwargs.get('metadata', {}))
        
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                INSERT INTO interactions 
                (id, type, character_id, content, metadata, timestamp, chain_id)
                VALUES (?, ?, ?, ?, ?, ?, ?)
            """, (
                inter_id, interaction_type, character_id, content,
                metadata, timestamp, kwargs.get('chain_id')
            ))
        
        return inter_id
    
    def get_interaction_chain(self, chain_id: str) -> List[Dict]:
        """Get all interactions in a chain"""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                SELECT * FROM interactions 
                WHERE chain_id = ?
                ORDER BY timestamp ASC
            """, (chain_id,))
            rows = cursor.fetchall()
            
            interactions = []
            for row in rows:
                inter = dict(row)
                inter['metadata'] = json.loads(inter['metadata']) if inter['metadata'] else {}
                interactions.append(inter)
            
            return interactions
    
    def get_character_interactions(self, character_id: str, limit: int = 50,
                                   interaction_type: Optional[str] = None) -> List[Dict]:
        """Get recent interactions for a character, optionally filtered by type."""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            if interaction_type:
                cursor.execute(
                    "SELECT * FROM interactions WHERE character_id = ? AND type = ? "
                    "ORDER BY timestamp DESC LIMIT ?",
                    (character_id, interaction_type, limit),
                )
            else:
                cursor.execute(
                    "SELECT * FROM interactions WHERE character_id = ? "
                    "ORDER BY timestamp DESC LIMIT ?",
                    (character_id, limit),
                )
            return [
                {**dict(r), 'metadata': json.loads(r['metadata']) if r['metadata'] else {}}
                for r in cursor.fetchall()
            ]

    def delete_interaction(self, interaction_id: str) -> bool:
        """Delete a single interaction by ID."""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("DELETE FROM interactions WHERE id = ?", (interaction_id,))
            return cursor.rowcount > 0

    def delete_interaction_chain(self, chain_id: str) -> int:
        """Delete all interactions in a chain. Returns count deleted."""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("DELETE FROM interactions WHERE chain_id = ?", (chain_id,))
            return cursor.rowcount
    
    # ============= CHARACTER STATE OPERATIONS =============
    
    def get_character_state(self, character_id: str) -> Optional[Dict]:
        """Get character's current state"""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM character_states WHERE character_id = ?", (character_id,))
            row = cursor.fetchone()
            
            if row:
                state = dict(row)
                state['metadata'] = json.loads(state['metadata']) if state['metadata'] else {}
                return state
            return None
    
    def update_character_state(self, character_id: str, **kwargs) -> bool:
        """Update character state"""
        # Whitelist of allowed columns to prevent SQL injection
        ALLOWED_COLUMNS = {
            'mood', 'energy', 'relationship_level', 'arousal', 'last_interaction',
            'metadata',
            'warmth', 'formality', 'humor', 'flirtiness', 'intelligence', 'creativity',
        }
        
        timestamp = datetime.now().isoformat()
        
        updates = []
        values = []
        
        for key, value in kwargs.items():
            # Validate column name against whitelist
            if key not in ALLOWED_COLUMNS:
                raise ValueError(f"Invalid column name: {key}")
            
            if key == 'metadata':
                value = json.dumps(value)
            updates.append(f"{key} = ?")
            values.append(value)
        
        if not updates:
            return False
        
        updates.append("updated_at = ?")
        values.append(timestamp)
        values.append(character_id)
        
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(f"""
                UPDATE character_states 
                SET {', '.join(updates)}
                WHERE character_id = ?
            """, values)
            
            return cursor.rowcount > 0
    
    def delete_character_state(self, character_id: str) -> bool:
        """Delete state for a character."""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("DELETE FROM character_states WHERE character_id = ?", (character_id,))
            return cursor.rowcount > 0
    
    # ============= MEDIA OPERATIONS =============
    
    def add_media(self, character_id: str, media_type: str, filepath: str, **kwargs) -> str:
        """Add media reference"""
        media_id = str(uuid.uuid4())
        timestamp = datetime.now().isoformat()
        
        metadata = json.dumps(kwargs.get('metadata', {}))
        
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                INSERT INTO media 
                (id, character_id, type, filepath, thumbnail, metadata, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?)
            """, (
                media_id, character_id, media_type, filepath,
                kwargs.get('thumbnail'), metadata, timestamp
            ))
        
        return media_id
    
    def get_character_media(self, character_id: str, media_type: Optional[str] = None) -> List[Dict]:
        """Get media for a character"""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            
            if media_type:
                cursor.execute("""
                    SELECT * FROM media 
                    WHERE character_id = ? AND type = ?
                    ORDER BY created_at DESC
                """, (character_id, media_type))
            else:
                cursor.execute("""
                    SELECT * FROM media 
                    WHERE character_id = ?
                    ORDER BY created_at DESC
                """, (character_id,))
            
            rows = cursor.fetchall()
            
            media_list = []
            for row in rows:
                media = dict(row)
                media['metadata'] = json.loads(media['metadata']) if media['metadata'] else {}
                media_list.append(media)
            
            return media_list

    def get_media(self, media_id: str) -> Optional[Dict]:
        """Get a single media record by ID."""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM media WHERE id = ?", (media_id,))
            row = cursor.fetchone()
            if row:
                m = dict(row)
                m['metadata'] = json.loads(m['metadata']) if m['metadata'] else {}
                return m
            return None

    def update_media(self, media_id: str, **kwargs) -> bool:
        """Update media metadata.
        
        Allowed fields: filepath, thumbnail, metadata.
        """
        ALLOWED = {'filepath', 'thumbnail', 'metadata'}
        updates, values = [], []
        for key, value in kwargs.items():
            if key not in ALLOWED:
                raise ValueError(f"Invalid media column: {key}")
            if key == 'metadata':
                value = json.dumps(value)
            updates.append(f"{key} = ?")
            values.append(value)
        if not updates:
            return False
        values.append(media_id)
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                f"UPDATE media SET {', '.join(updates)} WHERE id = ?",
                values,
            )
            return cursor.rowcount > 0

    def delete_media(self, media_id: str) -> bool:
        """Delete a single media record by ID."""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("DELETE FROM media WHERE id = ?", (media_id,))
            return cursor.rowcount > 0

    def delete_character_media(self, character_id: str,
                                media_type: Optional[str] = None) -> int:
        """Delete media for a character, optionally filtered by type. Returns count."""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            if media_type:
                cursor.execute(
                    "DELETE FROM media WHERE character_id = ? AND type = ?",
                    (character_id, media_type),
                )
            else:
                cursor.execute(
                    "DELETE FROM media WHERE character_id = ?",
                    (character_id,),
                )
            return cursor.rowcount

    # ============= COUNT / SEARCH HELPERS =============

    def count_characters(self) -> int:
        """Return total number of characters."""
        with self.get_connection() as conn:
            return conn.execute("SELECT COUNT(*) FROM characters").fetchone()[0]

    def count_conversations(self, character_id: Optional[str] = None) -> int:
        """Count conversations, optionally scoped to a character."""
        with self.get_connection() as conn:
            if character_id:
                return conn.execute(
                    "SELECT COUNT(*) FROM conversations WHERE character_id = ?",
                    (character_id,),
                ).fetchone()[0]
            return conn.execute("SELECT COUNT(*) FROM conversations").fetchone()[0]

    def count_interactions(self, character_id: Optional[str] = None) -> int:
        """Count interactions, optionally scoped to a character."""
        with self.get_connection() as conn:
            if character_id:
                return conn.execute(
                    "SELECT COUNT(*) FROM interactions WHERE character_id = ?",
                    (character_id,),
                ).fetchone()[0]
            return conn.execute("SELECT COUNT(*) FROM interactions").fetchone()[0]

    def count_media(self, character_id: Optional[str] = None,
                    media_type: Optional[str] = None) -> int:
        """Count media records with optional character and type filters."""
        clauses, params = [], []
        if character_id:
            clauses.append("character_id = ?")
            params.append(character_id)
        if media_type:
            clauses.append("type = ?")
            params.append(media_type)
        where = f" WHERE {' AND '.join(clauses)}" if clauses else ""
        with self.get_connection() as conn:
            return conn.execute(f"SELECT COUNT(*) FROM media{where}", params).fetchone()[0]

    def count_memories(self, character_id: Optional[str] = None) -> int:
        """Count memories, optionally scoped to a character."""
        with self.get_connection() as conn:
            if character_id:
                return conn.execute(
                    "SELECT COUNT(*) FROM memories WHERE character_id = ?",
                    (character_id,),
                ).fetchone()[0]
            return conn.execute("SELECT COUNT(*) FROM memories").fetchone()[0]

    def search_characters(self, query: str) -> List[Dict]:
        """Search characters by name (case-insensitive LIKE)."""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                "SELECT * FROM characters WHERE name LIKE ? ORDER BY name",
                (f"%{query}%",),
            )
            results = []
            for row in cursor.fetchall():
                c = dict(row)
                c['tags'] = json.loads(c['tags']) if c['tags'] else []
                c['metadata'] = json.loads(c['metadata']) if c['metadata'] else {}
                results.append(c)
            return results

    def get_conversations_paginated(self, character_id: str,
                                     offset: int = 0, limit: int = 20) -> Tuple[List[Dict], int]:
        """Return (page_of_conversations, total_count) for a character."""
        total = self.count_conversations(character_id)
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                "SELECT * FROM conversations WHERE character_id = ? "
                "ORDER BY started_at DESC LIMIT ? OFFSET ?",
                (character_id, limit, offset),
            )
            items = []
            for row in cursor.fetchall():
                c = dict(row)
                c['messages'] = json.loads(c['messages'])
                c['metadata'] = json.loads(c['metadata']) if c['metadata'] else {}
                items.append(c)
        return items, total

    def get_media_paginated(self, character_id: str,
                            media_type: Optional[str] = None,
                            offset: int = 0, limit: int = 20) -> Tuple[List[Dict], int]:
        """Return (page_of_media, total_count) for a character."""
        total = self.count_media(character_id, media_type)
        clauses = ["character_id = ?"]
        params: list = [character_id]
        if media_type:
            clauses.append("type = ?")
            params.append(media_type)
        where = " AND ".join(clauses)
        params += [limit, offset]
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                f"SELECT * FROM media WHERE {where} ORDER BY created_at DESC LIMIT ? OFFSET ?",
                params,
            )
            items = []
            for row in cursor.fetchall():
                m = dict(row)
                m['metadata'] = json.loads(m['metadata']) if m['metadata'] else {}
                items.append(m)
        return items, total

    # ============= CHARACTER RELATIONSHIPS =============

    def _rel_key(self, a: str, b: str):
        """Canonical order so (a,b) and (b,a) map to the same row."""
        return (min(a, b), max(a, b))

    def get_relationship(self, char_a: str, char_b: str) -> dict | None:
        """Get the relationship between two characters (order-independent)."""
        a, b = self._rel_key(char_a, char_b)
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                "SELECT * FROM character_relationships WHERE character_a_id=? AND character_b_id=?",
                (a, b),
            )
            row = cursor.fetchone()
            if not row:
                return None
            r = dict(row)
            r['metadata'] = json.loads(r['metadata']) if r['metadata'] else {}
            return r

    def create_relationship(self, char_a: str, char_b: str, **kwargs) -> str:
        """Create a new relationship between two characters."""
        a, b = self._rel_key(char_a, char_b)
        rel_id = str(uuid.uuid4())
        ts = datetime.now().isoformat()
        meta = json.dumps(kwargs.get('metadata', {}))
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                INSERT OR IGNORE INTO character_relationships
                (id, character_a_id, character_b_id, relationship_level, trust, attraction,
                 arousal_a, arousal_b, interaction_count, last_interaction, metadata, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                rel_id, a, b,
                kwargs.get('relationship_level', 0.5),
                kwargs.get('trust', 0.5),
                kwargs.get('attraction', 0.5),
                kwargs.get('arousal_a', 0.0),
                kwargs.get('arousal_b', 0.0),
                kwargs.get('interaction_count', 0),
                kwargs.get('last_interaction'),
                meta, ts, ts,
            ))
        return rel_id

    def update_relationship(self, char_a: str, char_b: str, **kwargs) -> bool:
        """Update relationship fields between two characters."""
        a, b = self._rel_key(char_a, char_b)
        allowed = {'relationship_level', 'trust', 'attraction', 'arousal_a',
                    'arousal_b', 'interaction_count', 'last_interaction', 'metadata'}
        sets = []
        vals = []
        for k, v in kwargs.items():
            if k not in allowed:
                continue
            if k == 'metadata':
                v = json.dumps(v) if isinstance(v, dict) else v
            sets.append(f"{k} = ?")
            vals.append(v)
        if not sets:
            return False
        sets.append("updated_at = ?")
        vals.append(datetime.now().isoformat())
        vals.extend([a, b])
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                f"UPDATE character_relationships SET {', '.join(sets)} "
                f"WHERE character_a_id=? AND character_b_id=?",
                vals,
            )
            return cursor.rowcount > 0

    def get_or_create_relationship(self, char_a: str, char_b: str, **defaults) -> dict:
        """Get existing relationship or create a new one with defaults."""
        rel = self.get_relationship(char_a, char_b)
        if rel:
            return rel
        self.create_relationship(char_a, char_b, **defaults)
        return self.get_relationship(char_a, char_b)

    def list_relationships(self, character_id: str) -> list:
        """List all relationships for a character."""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                "SELECT * FROM character_relationships "
                "WHERE character_a_id=? OR character_b_id=? "
                "ORDER BY updated_at DESC",
                (character_id, character_id),
            )
            rows = []
            for row in cursor.fetchall():
                r = dict(row)
                r['metadata'] = json.loads(r['metadata']) if r['metadata'] else {}
                rows.append(r)
            return rows

    def delete_relationship(self, char_a: str, char_b: str) -> bool:
        """Delete a relationship."""
        a, b = self._rel_key(char_a, char_b)
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                "DELETE FROM character_relationships WHERE character_a_id=? AND character_b_id=?",
                (a, b),
            )
            return cursor.rowcount > 0


if __name__ == "__main__":
    # Test the database
    db = Database()
    print("✅ Database initialized successfully")
    
    # Test creating a personality
    pers_id = db.create_personality(
        name="Playful Girlfriend",
        system_prompt="You are a playful, affectionate girlfriend who loves to tease and flirt.",
        traits=["playful", "affectionate", "teasing", "romantic"],
        communication_style={"tone": "casual", "emoji_usage": "high"},
        sexual_openness=0.7
    )
    print(f"✅ Created personality: {pers_id}")
    
    # Test creating a character
    char_id = db.create_character(
        name="Emma",
        age=24,
        sex="female",
        hair_color="blonde",
        eye_color="blue",
        height="5'6\"",
        body_type="athletic",
        personality_id=pers_id,
        tags=["girlfriend", "playful", "romantic"]
    )
    print(f"✅ Created character: {char_id}")
    
    # Test getting character
    char = db.get_character(char_id)
    print(f"✅ Retrieved character: {char['name']}")
    
    print("\n🎉 Database system is working!")
