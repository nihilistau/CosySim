"""
Character Class for Virtual Companion System
Manages character attributes, state, memory, and behavior
"""
from typing import Dict, List, Optional, Any
from datetime import datetime
import uuid
import sys
from pathlib import Path

# Add parent directory to path for imports
project_root = Path(__file__).parent.parent.parent
sys.path.insert(0, str(project_root))

from content.simulation.database.db import Database
from content.simulation.database.rag import RAGMemory


class Character:
    """
    Represents a virtual character with personality, memory, and state
    """
    
    def __init__(self, character_id: str, db: Optional[Database] = None, rag: Optional[RAGMemory] = None):
        """
        Initialize character from database
        
        Args:
            character_id: Character's unique ID
            db: Database instance (creates new if None)
            rag: RAG memory instance (creates new if None)
        """
        self.id = character_id
        self.db = db or Database()
        self.rag = rag or RAGMemory()
        
        # Load character data
        self._data = self.db.get_character(character_id)
        if not self._data:
            raise ValueError(f"Character {character_id} not found")
        
        # Load state
        self._state = self.db.get_character_state(character_id)
        
        # Load personality
        if self._data.get('personality_id'):
            self._personality = self.db.get_personality(self._data['personality_id'])
        else:
            self._personality = None
        
        # Cache for current conversation
        self._current_chain_id = None
        self._current_conversation_id = None
    
    # ============= PROPERTIES =============
    
    @property
    def name(self) -> str:
        return self._data['name']
    
    @property
    def age(self) -> Optional[int]:
        return self._data.get('age')
    
    @property
    def sex(self) -> Optional[str]:
        return self._data.get('sex')
    
    @property
    def hair_color(self) -> Optional[str]:
        return self._data.get('hair_color')
    
    @property
    def eye_color(self) -> Optional[str]:
        return self._data.get('eye_color')
    
    @property
    def height(self) -> Optional[str]:
        return self._data.get('height')
    
    @property
    def body_type(self) -> Optional[str]:
        return self._data.get('body_type')
    
    @property
    def tags(self) -> List[str]:
        return self._data.get('tags', [])
    
    @property
    def personality(self) -> Optional[Dict]:
        return self._personality
    
    @property
    def mood(self) -> str:
        return self._state.get('mood', 'neutral') if self._state else 'neutral'
    
    @property
    def energy(self) -> float:
        return self._state.get('energy', 0.8) if self._state else 0.8
    
    @property
    def relationship_level(self) -> float:
        return self._state.get('relationship_level', 0.0) if self._state else 0.0
    
    @property
    def arousal(self) -> float:
        return self._state.get('arousal', 0.0) if self._state else 0.0
    
    # ============= CHARACTER MANAGEMENT =============
    
    def update_attributes(self, **kwargs) -> bool:
        """Update character attributes"""
        success = self.db.update_character(self.id, **kwargs)
        if success:
            # Reload data
            self._data = self.db.get_character(self.id)
        return success
    
    def add_tag(self, tag: str) -> bool:
        """Add a tag to the character"""
        if tag not in self.tags:
            new_tags = self.tags + [tag]
            return self.update_attributes(tags=new_tags)
        return False
    
    def remove_tag(self, tag: str) -> bool:
        """Remove a tag from the character"""
        if tag in self.tags:
            new_tags = [t for t in self.tags if t != tag]
            return self.update_attributes(tags=new_tags)
        return False
    
    def get_description(self) -> str:
        """Get formatted character description"""
        parts = [f"Name: {self.name}"]
        
        if self.age:
            parts.append(f"Age: {self.age}")
        if self.sex:
            parts.append(f"Sex: {self.sex}")
        if self.hair_color:
            parts.append(f"Hair: {self.hair_color}")
        if self.eye_color:
            parts.append(f"Eyes: {self.eye_color}")
        if self.height:
            parts.append(f"Height: {self.height}")
        if self.body_type:
            parts.append(f"Build: {self.body_type}")
        if self.tags:
            parts.append(f"Traits: {', '.join(self.tags)}")
        
        return "\n".join(parts)
    
    # ============= STATE MANAGEMENT =============
    
    def update_state(self, **kwargs) -> bool:
        """Update character state"""
        success = self.db.update_character_state(self.id, **kwargs)
        if success:
            # Reload state
            self._state = self.db.get_character_state(self.id)
        return success
    
    def set_mood(self, mood: str) -> bool:
        """Set character mood"""
        return self.update_state(mood=mood)
    
    def adjust_relationship(self, delta: float) -> bool:
        """Adjust relationship level"""
        new_level = max(0.0, min(1.0, self.relationship_level + delta))
        return self.update_state(relationship_level=new_level)
    
    def adjust_arousal(self, delta: float) -> bool:
        """Adjust arousal level"""
        new_level = max(0.0, min(1.0, self.arousal + delta))
        return self.update_state(arousal=new_level)
    
    def adjust_energy(self, delta: float) -> bool:
        """Adjust energy level"""
        new_level = max(0.0, min(1.0, self.energy + delta))
        return self.update_state(energy=new_level)
    
    # ============= MEMORY OPERATIONS =============
    
    def add_memory(self, content: str, memory_type: str = "conversation", importance: float = 0.5, **kwargs) -> str:
        """
        Add a memory for this character
        
        Args:
            content: Memory content
            memory_type: Type of memory
            importance: Importance score (0-1)
            **kwargs: Additional metadata
        
        Returns:
            Memory ID
        """
        # Add to database
        db_mem_id = self.db.add_memory(
            self.id, content, 
            importance=importance, 
            **kwargs
        )
        
        # Add to RAG
        rag_mem_id = self.rag.add_memory(
            self.id, content,
            memory_type=memory_type,
            importance=importance,
            **kwargs
        )
        
        return db_mem_id
    
    def query_memories(self, query: str, n_results: int = 5, **kwargs) -> List[Dict]:
        """Query memories using semantic search"""
        return self.rag.query_memories(self.id, query, n_results=n_results, **kwargs)
    
    def get_recent_memories(self, n_results: int = 10) -> List[Dict]:
        """Get recent memories"""
        return self.rag.get_recent_memories(self.id, n_results=n_results)
    
    def get_important_memories(self, n_results: int = 10, min_importance: float = 0.7) -> List[Dict]:
        """Get important memories"""
        return self.rag.get_important_memories(self.id, n_results=n_results, min_importance=min_importance)
    
    def build_context(self, current_input: str) -> str:
        """Build context from memories for current interaction"""
        return self.rag.build_context(
            self.id, 
            current_input,
            n_recent=5,
            n_semantic=5,
            n_important=3
        )
    
    # ============= CONVERSATION MANAGEMENT =============
    
    def start_conversation(self, role_id: Optional[str] = None, chain_id: Optional[str] = None) -> str:
        """
        Start a new conversation
        
        Args:
            role_id: Optional role for this conversation
            chain_id: Optional chain ID (creates new if None)
        
        Returns:
            Conversation ID
        """
        self._current_chain_id = chain_id or str(uuid.uuid4())
        
        self._current_conversation_id = self.db.create_conversation(
            self.id,
            self._current_chain_id,
            role_id=role_id,
            messages=[]
        )
        
        return self._current_conversation_id
    
    def add_message(self, role: str, content: str, metadata: Optional[Dict] = None) -> bool:
        """
        Add a message to current conversation
        
        Args:
            role: 'user' or 'assistant'
            content: Message content
            metadata: Additional metadata
        
        Returns:
            Success status
        """
        if not self._current_conversation_id:
            self.start_conversation()
        
        # Get current conversation
        conv = self.db.get_conversation(self._current_conversation_id)
        if not conv:
            return False
        
        # Add message
        message = {
            "role": role,
            "content": content,
            "timestamp": datetime.now().isoformat()
        }
        if metadata:
            message["metadata"] = metadata
        
        messages = conv['messages']
        messages.append(message)
        
        # Update conversation
        success = self.db.update_conversation(self._current_conversation_id, messages)
        
        # Log interaction
        if success:
            self.db.log_interaction(
                "message",
                self.id,
                content,
                chain_id=self._current_chain_id,
                metadata={"role": role, **(metadata or {})}
            )
            
            # Add to memory if it's an important message
            if role == "user" or (metadata and metadata.get('important')):
                self.add_memory(
                    f"{role}: {content}",
                    memory_type="conversation",
                    importance=metadata.get('importance', 0.5) if metadata else 0.5
                )
        
        return success
    
    def end_conversation(self) -> bool:
        """End current conversation"""
        if not self._current_conversation_id:
            return False
        
        conv = self.db.get_conversation(self._current_conversation_id)
        if not conv:
            return False
        
        success = self.db.update_conversation(
            self._current_conversation_id,
            conv['messages'],
            ended=True
        )
        
        if success:
            self._current_conversation_id = None
            self._current_chain_id = None
        
        return success
    
    def get_conversation_history(self, limit: int = 10) -> List[Dict]:
        """Get recent conversations"""
        return self.db.get_character_conversations(self.id, limit=limit)
    
    # ============= MEDIA MANAGEMENT =============
    
    def add_media(self, media_type: str, filepath: str, **kwargs) -> str:
        """Add media reference"""
        return self.db.add_media(self.id, media_type, filepath, **kwargs)
    
    def get_media(self, media_type: Optional[str] = None) -> List[Dict]:
        """Get character's media"""
        return self.db.get_character_media(self.id, media_type=media_type)
    
    # ============= BEHAVIOR & AI =============
    
    def get_system_prompt(self) -> str:
        """Build system prompt from character data"""
        parts = []
        
        # Base personality
        if self._personality:
            parts.append(self._personality['system_prompt'])
        
        # Character description
        parts.append(f"\n## Your Identity\n{self.get_description()}")
        
        # Current state
        state_info = [
            f"Current mood: {self.mood}",
            f"Energy level: {self.energy:.1%}",
            f"Relationship closeness: {self.relationship_level:.1%}"
        ]
        parts.append(f"\n## Current State\n{chr(10).join(state_info)}")
        
        # Communication style
        if self._personality and self._personality.get('communication_style'):
            style = self._personality['communication_style']
            parts.append(f"\n## Communication Style\n{style}")
        
        return "\n".join(parts)
    
    def should_initiate_interaction(self) -> bool:
        """
        Determine if character should autonomously initiate interaction
        Based on relationship level, time since last interaction, mood, etc.
        """
        # Simple heuristic - can be made more sophisticated
        if not self._state:
            return False
        
        # High relationship = more likely to reach out
        if self.relationship_level > 0.7:
            return True
        
        # Check time since last interaction
        last_interaction = self._state.get('last_interaction')
        if last_interaction:
            last_time = datetime.fromisoformat(last_interaction)
            hours_since = (datetime.now() - last_time).total_seconds() / 3600
            
            # More likely to reach out if haven't talked in a while
            if hours_since > 6:
                return self.relationship_level > 0.5
        
        return False
    
    def to_dict(self) -> Dict:
        """Convert character to dictionary"""
        return {
            'id': self.id,
            'name': self.name,
            'age': self.age,
            'sex': self.sex,
            'hair_color': self.hair_color,
            'eye_color': self.eye_color,
            'height': self.height,
            'body_type': self.body_type,
            'tags': self.tags,
            'personality': self._personality,
            'state': self._state,
            'created_at': self._data.get('created_at')
        }
    
    @classmethod
    def create(cls, name: str, personality_id: Optional[str] = None, db: Optional[Database] = None, **kwargs) -> 'Character':
        """
        Create a new character
        
        Args:
            name: Character name
            personality_id: Personality ID
            db: Database instance
            **kwargs: Additional character attributes
        
        Returns:
            Character instance
        """
        db = db or Database()
        char_id = db.create_character(name, personality_id=personality_id, **kwargs)
        return cls(char_id, db=db)
    
    @classmethod
    def load(cls, character_id: str, db: Optional[Database] = None) -> Optional['Character']:
        """
        Load character by ID
        
        Args:
            character_id: Character ID
            db: Database instance
        
        Returns:
            Character instance or None
        """
        db = db or Database()
        try:
            return cls(character_id, db=db)
        except ValueError:
            return None
    
    @classmethod
    def load_by_name(cls, name: str, db: Optional[Database] = None) -> Optional['Character']:
        """
        Load character by name
        
        Args:
            name: Character name
            db: Database instance
        
        Returns:
            Character instance or None
        """
        db = db or Database()
        characters = db.get_all_characters()
        
        for char_data in characters:
            if char_data['name'] == name:
                return cls(char_data['id'], db=db)
        
        return None
    
    def __repr__(self) -> str:
        return f"<Character(id='{self.id}', name='{self.name}')>"


if __name__ == "__main__":
    # Test character system
    print("Testing Character System...")
    
    db = Database()
    rag = RAGMemory()
    
    # Create a personality
    pers_id = db.create_personality(
        name="Test Girlfriend",
        system_prompt="You are a sweet, caring girlfriend.",
        traits=["caring", "romantic"],
        communication_style={"tone": "warm"},
        sexual_openness=0.6
    )
    
    # Create character
    char = Character.create(
        "Luna",
        personality_id=pers_id,
        age=25,
        sex="female",
        hair_color="brunette",
        eye_color="green",
        height="5'7\"",
        body_type="athletic",
        tags=["girlfriend", "caring"],
        db=db
    )
    
    print(f"✅ Created character: {char.name}")
    print(f"\n{char.get_description()}")
    
    # Test memory
    char.add_memory("We met at a coffee shop", importance=0.9)
    char.add_memory("You love hiking", importance=0.7)
    
    print(f"\n✅ Added memories: {rag.get_memory_count(char.id)}")
    
    # Test conversation
    conv_id = char.start_conversation()
    char.add_message("user", "Hey, how are you?")
    char.add_message("assistant", "I'm great! Just thinking about you 😊")
    
    print(f"✅ Started conversation: {conv_id}")
    
    # Test state
    char.set_mood("happy")
    char.adjust_relationship(0.1)
    
    print(f"✅ Updated state - Mood: {char.mood}, Relationship: {char.relationship_level:.1%}")
    
    print("\n🎉 Character system is working!")
