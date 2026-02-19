"""
ChromaDB RAG Memory System for Virtual Companion
Provides semantic memory storage and retrieval
"""
import chromadb
from chromadb.config import Settings
from chromadb.utils import embedding_functions
from typing import List, Dict, Optional, Any
import uuid
from datetime import datetime
from pathlib import Path


class RAGMemory:
    """RAG-based memory system using ChromaDB"""
    
    def __init__(self, persist_directory: str = "simulation/chroma_db", collection_name: str = "character_memories"):
        """
        Initialize ChromaDB RAG memory system
        
        Args:
            persist_directory: Directory to persist ChromaDB data
            collection_name: Name of the ChromaDB collection
        """
        self.persist_directory = Path(persist_directory)
        self.persist_directory.mkdir(parents=True, exist_ok=True)
        self.collection_name = collection_name
        
        # Initialize ChromaDB client
        self.client = chromadb.PersistentClient(
            path=str(self.persist_directory),
            settings=Settings(
                anonymized_telemetry=False,
                allow_reset=True
            )
        )
        
        # Use default embedding function (all-MiniLM-L6-v2)
        self.embedding_function = embedding_functions.DefaultEmbeddingFunction()
        
        # Get or create collection
        try:
            self.collection = self.client.get_collection(
                name=self.collection_name,
                embedding_function=self.embedding_function
            )
        except:
            self.collection = self.client.create_collection(
                name=self.collection_name,
                embedding_function=self.embedding_function,
                metadata={"description": "Character memories for Virtual Companion System"}
            )
    
    def add_memory(
        self, 
        character_id: str, 
        content: str, 
        memory_type: str = "conversation",
        importance: float = 0.5,
        emotion: Optional[str] = None,
        metadata: Optional[Dict] = None
    ) -> str:
        """
        Add a memory to the RAG system
        
        Args:
            character_id: ID of the character
            content: Memory content
            memory_type: Type of memory (conversation, event, fact, etc.)
            importance: Importance score (0-1)
            emotion: Associated emotion
            metadata: Additional metadata
        
        Returns:
            Memory ID
        """
        memory_id = str(uuid.uuid4())
        timestamp = datetime.now().isoformat()
        
        # Prepare metadata
        meta = {
            "character_id": character_id,
            "type": memory_type,
            "importance": importance,
            "timestamp": timestamp
        }
        
        if emotion:
            meta["emotion"] = emotion
        
        if metadata:
            meta.update(metadata)
        
        # Add to ChromaDB
        self.collection.add(
            documents=[content],
            metadatas=[meta],
            ids=[memory_id]
        )
        
        return memory_id
    
    def add_memories_batch(
        self,
        character_id: str,
        memories: List[Dict[str, Any]]
    ) -> List[str]:
        """
        Add multiple memories in batch
        
        Args:
            character_id: ID of the character
            memories: List of memory dicts with 'content', 'type', 'importance', etc.
        
        Returns:
            List of memory IDs
        """
        if not memories:
            return []
        
        memory_ids = []
        documents = []
        metadatas = []
        
        timestamp = datetime.now().isoformat()
        
        for memory in memories:
            memory_id = str(uuid.uuid4())
            memory_ids.append(memory_id)
            
            documents.append(memory['content'])
            
            meta = {
                "character_id": character_id,
                "type": memory.get('type', 'conversation'),
                "importance": memory.get('importance', 0.5),
                "timestamp": timestamp
            }
            
            if 'emotion' in memory:
                meta["emotion"] = memory['emotion']
            
            if 'metadata' in memory:
                meta.update(memory['metadata'])
            
            metadatas.append(meta)
        
        # Batch add to ChromaDB
        self.collection.add(
            documents=documents,
            metadatas=metadatas,
            ids=memory_ids
        )
        
        return memory_ids
    
    def query_memories(
        self,
        character_id: str,
        query: str,
        n_results: int = 5,
        memory_type: Optional[str] = None,
        min_importance: Optional[float] = None
    ) -> List[Dict]:
        """
        Query memories using semantic search
        
        Args:
            character_id: ID of the character
            query: Search query
            n_results: Number of results to return
            memory_type: Filter by memory type
            min_importance: Filter by minimum importance
        
        Returns:
            List of relevant memories
        """
        # Build where clause with proper $and operator for multiple conditions
        conditions = [{"character_id": {"$eq": character_id}}]
        
        if memory_type:
            conditions.append({"type": {"$eq": memory_type}})
        
        if min_importance is not None:
            conditions.append({"importance": {"$gte": min_importance}})
        
        # Use $and if multiple conditions, otherwise use single condition
        if len(conditions) > 1:
            where = {"$and": conditions}
        else:
            where = conditions[0]
        
        # Query ChromaDB
        results = self.collection.query(
            query_texts=[query],
            n_results=n_results,
            where=where
        )
        
        # Format results
        memories = []
        if results['ids'] and results['ids'][0]:
            for i in range(len(results['ids'][0])):
                memory = {
                    'id': results['ids'][0][i],
                    'content': results['documents'][0][i],
                    'metadata': results['metadatas'][0][i],
                    'distance': results['distances'][0][i] if 'distances' in results else None
                }
                memories.append(memory)
        
        return memories
    
    def get_recent_memories(
        self,
        character_id: str,
        n_results: int = 10,
        memory_type: Optional[str] = None
    ) -> List[Dict]:
        """
        Get most recent memories for a character
        
        Args:
            character_id: ID of the character
            n_results: Number of results to return
            memory_type: Filter by memory type
        
        Returns:
            List of recent memories
        """
        # Build where clause with proper $and operator
        if memory_type:
            where = {
                "$and": [
                    {"character_id": {"$eq": character_id}},
                    {"type": {"$eq": memory_type}}
                ]
            }
        else:
            where = {"character_id": {"$eq": character_id}}
        
        # Get all memories for character
        results = self.collection.get(
            where=where,
            limit=n_results
        )
        
        # Format results
        memories = []
        if results['ids']:
            for i in range(len(results['ids'])):
                memory = {
                    'id': results['ids'][i],
                    'content': results['documents'][i],
                    'metadata': results['metadatas'][i]
                }
                memories.append(memory)
            
            # Sort by timestamp (most recent first)
            memories.sort(key=lambda x: x['metadata'].get('timestamp', ''), reverse=True)
        
        return memories[:n_results]
    
    def get_important_memories(
        self,
        character_id: str,
        n_results: int = 10,
        min_importance: float = 0.7
    ) -> List[Dict]:
        """
        Get most important memories for a character
        
        Args:
            character_id: ID of the character
            n_results: Number of results to return
            min_importance: Minimum importance threshold
        
        Returns:
            List of important memories
        """
        # ChromaDB requires $and operator for multiple conditions
        where = {
            "$and": [
                {"character_id": {"$eq": character_id}},
                {"importance": {"$gte": min_importance}}
            ]
        }
        
        # Get all important memories
        results = self.collection.get(
            where=where,
            limit=n_results
        )
        
        # Format results
        memories = []
        if results['ids']:
            for i in range(len(results['ids'])):
                memory = {
                    'id': results['ids'][i],
                    'content': results['documents'][i],
                    'metadata': results['metadatas'][i]
                }
                memories.append(memory)
            
            # Sort by importance (highest first)
            memories.sort(key=lambda x: x['metadata'].get('importance', 0), reverse=True)
        
        return memories[:n_results]
    
    def build_context(
        self,
        character_id: str,
        current_query: str,
        n_recent: int = 5,
        n_semantic: int = 5,
        n_important: int = 3
    ) -> str:
        """
        Build context from multiple memory sources
        
        Args:
            character_id: ID of the character
            current_query: Current conversation/query
            n_recent: Number of recent memories
            n_semantic: Number of semantically similar memories
            n_important: Number of important memories
        
        Returns:
            Formatted context string
        """
        context_parts = []
        
        # Get important memories
        important = self.get_important_memories(character_id, n_results=n_important)
        if important:
            context_parts.append("=== Important Memories ===")
            for mem in important:
                context_parts.append(f"- {mem['content']}")
        
        # Get semantically relevant memories
        semantic = self.query_memories(character_id, current_query, n_results=n_semantic)
        if semantic:
            context_parts.append("\n=== Relevant Memories ===")
            for mem in semantic:
                context_parts.append(f"- {mem['content']}")
        
        # Get recent memories
        recent = self.get_recent_memories(character_id, n_results=n_recent)
        if recent:
            context_parts.append("\n=== Recent Context ===")
            for mem in recent:
                context_parts.append(f"- {mem['content']}")
        
        return "\n".join(context_parts)
    
    def delete_memory(self, memory_id: str) -> bool:
        """Delete a specific memory"""
        try:
            self.collection.delete(ids=[memory_id])
            return True
        except Exception as e:
            print(f"Error deleting memory: {e}")
            return False
    
    def delete_character_memories(self, character_id: str) -> bool:
        """Delete all memories for a character"""
        try:
            self.collection.delete(where={"character_id": {"$eq": character_id}})
            return True
        except Exception as e:
            print(f"Error deleting character memories: {e}")
            return False
    
    def get_memory_count(self, character_id: Optional[str] = None) -> int:
        """Get count of memories"""
        if character_id:
            results = self.collection.get(where={"character_id": {"$eq": character_id}})
            return len(results['ids']) if results['ids'] else 0
        else:
            return self.collection.count()
    
    def reset_collection(self):
        """Reset the entire collection (use with caution!)"""
        self.client.delete_collection(name=self.collection_name)
        self.collection = self.client.create_collection(
            name=self.collection_name,
            embedding_function=self.embedding_function,
            metadata={"description": "Character memories for Virtual Companion System"}
        )


if __name__ == "__main__":
    # Test RAG memory system
    print("Testing RAG Memory System...")
    
    rag = RAGMemory()
    char_id = "test_char_001"
    
    # Add some test memories
    print("\nAdding memories...")
    rag.add_memory(
        char_id,
        "We had our first date at the Italian restaurant downtown. You ordered the carbonara.",
        memory_type="event",
        importance=0.9,
        emotion="happy"
    )
    
    rag.add_memory(
        char_id,
        "You mentioned that you love hiking and want to visit the mountains.",
        memory_type="fact",
        importance=0.7
    )
    
    rag.add_memory(
        char_id,
        "We watched a movie together last night. You fell asleep on my shoulder.",
        memory_type="event",
        importance=0.8,
        emotion="affectionate"
    )
    
    print(f"✅ Added 3 memories")
    print(f"Total memories: {rag.get_memory_count(char_id)}")
    
    # Query memories
    print("\nQuerying memories about 'date'...")
    results = rag.query_memories(char_id, "tell me about our date", n_results=2)
    for mem in results:
        print(f"  - {mem['content']}")
    
    # Get recent memories
    print("\nRecent memories:")
    recent = rag.get_recent_memories(char_id, n_results=5)
    for mem in recent:
        print(f"  - {mem['content']}")
    
    # Build context
    print("\nBuilding context for: 'What do you remember about us?'")
    context = rag.build_context(char_id, "What do you remember about us?", n_recent=3, n_semantic=2, n_important=1)
    print(context)
    
    print("\n🎉 RAG Memory System is working!")
