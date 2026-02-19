"""
SQLite Database Management for Virtual Companion System
Handles all character, personality, role, conversation, and media data
"""
import sqlite3
import json
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional, Any, Tuple
import uuid
from contextlib import contextmanager


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
            
            # Create indexes for performance
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_memories_character ON memories(character_id)")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_conversations_character ON conversations(character_id)")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_interactions_character ON interactions(character_id)")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_interactions_chain ON interactions(chain_id)")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_media_character ON media(character_id)")
    
    # ============= CHARACTER OPERATIONS =============
    
    def create_character(self, name: str, **kwargs) -> str:
        """Create a new character"""
        char_id = str(uuid.uuid4())
        timestamp = datetime.now().isoformat()
        
        tags = json.dumps(kwargs.get('tags', []))
        metadata = json.dumps(kwargs.get('metadata', {}))
        
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                INSERT INTO characters 
                (id, name, age, sex, hair_color, eye_color, height, body_type, 
                 personality_id, tags, metadata, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                char_id, name, 
                kwargs.get('age'), kwargs.get('sex'),
                kwargs.get('hair_color'), kwargs.get('eye_color'),
                kwargs.get('height'), kwargs.get('body_type'),
                kwargs.get('personality_id'),
                tags, metadata, timestamp, timestamp
            ))
            
            # Initialize character state
            cursor.execute("""
                INSERT INTO character_states 
                (id, character_id, updated_at)
                VALUES (?, ?, ?)
            """, (str(uuid.uuid4()), char_id, timestamp))
        
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
    
    def update_character(self, char_id: str, **kwargs) -> bool:
        """Update character attributes"""
        # Whitelist of allowed columns to prevent SQL injection
        ALLOWED_COLUMNS = {
            'name', 'age', 'sex', 'hair_color', 'eye_color', 'height', 'body_type',
            'personality_id', 'role_id', 'appearance', 'voice_id', 'traits', 'backstory',
            'tags', 'metadata', 'avatar_url'
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
                 sexual_openness, personality_values, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                pers_id, name, system_prompt, traits, communication_style,
                kwargs.get('sexual_openness', 0.5), personality_values, timestamp
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
            'conversation_id', 'location', 'activity', 'metadata'
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
