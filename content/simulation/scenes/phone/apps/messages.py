"""
Messages App - Texting functionality
Handles message sending, receiving, and conversation management
"""
from typing import Dict, List, Optional
from datetime import datetime
import uuid


class MessagesApp:
    """
    Manages text messaging functionality
    """
    
    def __init__(self, db, rag, character_id: str):
        self.db = db
        self.rag = rag
        self.character_id = character_id
        self.current_conversation_id = None
        self.current_chain_id = None
    
    def start_conversation(self) -> str:
        """Start a new conversation"""
        self.current_chain_id = str(uuid.uuid4())
        self.current_conversation_id = self.db.create_conversation(
            self.character_id,
            self.current_chain_id,
            messages=[]
        )
        return self.current_conversation_id
    
    def send_message(self, content: str, sender: str = 'user') -> Dict:
        """
        Send a message
        
        Args:
            content: Message content
            sender: 'user' or 'assistant'
        
        Returns:
            Message dict
        """
        if not self.current_conversation_id:
            self.start_conversation()
        
        # Create message
        message = {
            'id': str(uuid.uuid4()),
            'role': sender,
            'content': content,
            'timestamp': datetime.now().isoformat(),
            'read': False
        }
        
        # Get current conversation
        conv = self.db.get_conversation(self.current_conversation_id)
        if conv:
            messages = conv['messages']
            messages.append(message)
            self.db.update_conversation(self.current_conversation_id, messages)
        
        # Log interaction
        self.db.log_interaction(
            'text_message',
            self.character_id,
            content,
            chain_id=self.current_chain_id,
            metadata={'sender': sender}
        )
        
        return message
    
    def mark_as_read(self, message_id: str) -> bool:
        """Mark message as read"""
        conv = self.db.get_conversation(self.current_conversation_id)
        if not conv:
            return False
        
        messages = conv['messages']
        for msg in messages:
            if msg.get('id') == message_id:
                msg['read'] = True
        
        return self.db.update_conversation(self.current_conversation_id, messages)
    
    def get_conversation_history(self, limit: int = 50) -> List[Dict]:
        """Get recent messages"""
        if not self.current_conversation_id:
            return []
        
        conv = self.db.get_conversation(self.current_conversation_id)
        if not conv:
            return []
        
        return conv['messages'][-limit:]
    
    def get_unread_count(self) -> int:
        """Get count of unread messages"""
        history = self.get_conversation_history()
        return sum(1 for msg in history if msg['role'] == 'assistant' and not msg.get('read', False))
