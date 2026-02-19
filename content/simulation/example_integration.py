"""
Example: Complete Integration with LM Studio
Shows how to integrate the Virtual Companion with LM Studio for AI responses
"""
import sys
from pathlib import Path
import requests
from typing import Dict, Optional

project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from content.simulation.character_system.character import Character
from content.simulation.character_system.personality import Personality
from content.simulation.database.db import Database


class AICompanion:
    """
    Complete AI Companion with LM Studio integration
    """
    
    def __init__(self, character: Character, lm_studio_url: str = "http://localhost:1234"):
        self.character = character
        self.lm_studio_url = lm_studio_url
        self.conversation_history = []
    
    def generate_response(self, user_message: str, temperature: float = 0.8, max_tokens: int = 200) -> str:
        """
        Generate AI response using LM Studio
        
        Args:
            user_message: User's input message
            temperature: Creativity (0.0-1.0)
            max_tokens: Max response length
        
        Returns:
            AI-generated response
        """
        # Build context from memories
        context = self.character.build_context(user_message)
        
        # Get character's system prompt
        system_prompt = self.character.get_system_prompt()
        
        # Add recent conversation history
        history_context = self._build_history_context()
        
        # Combine all context
        full_system = f"{system_prompt}\n\n{context}\n\n{history_context}"
        
        # Prepare messages for LM Studio
        messages = [
            {"role": "system", "content": full_system},
            {"role": "user", "content": user_message}
        ]
        
        try:
            # Call LM Studio API
            response = requests.post(
                f"{self.lm_studio_url}/v1/chat/completions",
                json={
                    "messages": messages,
                    "temperature": temperature,
                    "max_tokens": max_tokens,
                    "stream": False
                },
                timeout=30
            )
            
            response.raise_for_status()
            result = response.json()
            
            ai_response = result["choices"][0]["message"]["content"]
            
            # Store in conversation history
            self.conversation_history.append({
                "user": user_message,
                "assistant": ai_response
            })
            
            # Add to character's conversation
            self.character.add_message("user", user_message)
            self.character.add_message("assistant", ai_response, metadata={"important": True})
            
            # Add important exchanges to memory
            if self._is_important_exchange(user_message, ai_response):
                memory_content = f"User: {user_message}\nMe: {ai_response}"
                self.character.add_memory(memory_content, importance=0.7)
            
            # Update character state based on conversation
            self._update_state_from_conversation(user_message, ai_response)
            
            return ai_response
            
        except requests.exceptions.RequestException as e:
            print(f"Error calling LM Studio: {e}")
            return "Sorry, I'm having trouble responding right now. Can you try again?"
    
    def _build_history_context(self, limit: int = 5) -> str:
        """Build context from recent conversation history"""
        if not self.conversation_history:
            return ""
        
        recent = self.conversation_history[-limit:]
        lines = ["=== Recent Conversation ==="]
        
        for exchange in recent:
            lines.append(f"User: {exchange['user']}")
            lines.append(f"You: {exchange['assistant']}")
        
        return "\n".join(lines)
    
    def _is_important_exchange(self, user_msg: str, ai_msg: str) -> bool:
        """Determine if exchange should be saved to long-term memory"""
        # Simple heuristic - can be made more sophisticated
        important_keywords = [
            "love", "remember", "first", "never forget", "always",
            "promise", "special", "important", "favorite", "best"
        ]
        
        combined = (user_msg + " " + ai_msg).lower()
        return any(keyword in combined for keyword in important_keywords)
    
    def _update_state_from_conversation(self, user_msg: str, ai_msg: str):
        """Update character state based on conversation sentiment"""
        combined = (user_msg + " " + ai_msg).lower()
        
        # Simple sentiment analysis
        if any(word in combined for word in ["love", "miss", "beautiful", "amazing"]):
            self.character.adjust_relationship(0.01)
        
        if any(word in combined for word in ["angry", "upset", "mad", "annoying"]):
            self.character.adjust_relationship(-0.02)
        
        # Detect flirty/romantic mood
        if any(word in combined for word in ["flirt", "sexy", "kiss", "date", "romantic"]):
            self.character.set_mood("romantic")
            self.character.adjust_arousal(0.05)
    
    def chat(self):
        """Interactive chat loop"""
        print(f"💬 Chatting with {self.character.name}")
        print(f"📊 Relationship: {self.character.relationship_level:.0%} | Mood: {self.character.mood}")
        print("Type 'quit' to exit, 'status' for character status\n")
        
        # Start conversation
        if not self.character._current_conversation_id:
            self.character.start_conversation()
        
        while True:
            try:
                user_input = input("You: ").strip()
                
                if not user_input:
                    continue
                
                if user_input.lower() == 'quit':
                    print(f"\n👋 Goodbye! Final relationship level: {self.character.relationship_level:.0%}")
                    break
                
                if user_input.lower() == 'status':
                    self._print_status()
                    continue
                
                # Generate response
                print(f"{self.character.name}: ", end="", flush=True)
                response = self.generate_response(user_input)
                print(response)
                print()
                
            except KeyboardInterrupt:
                print("\n\n👋 Chat ended.")
                break
            except Exception as e:
                print(f"\n❌ Error: {e}")
                continue
    
    def _print_status(self):
        """Print character status"""
        print("\n" + "="*50)
        print(f"📊 {self.character.name}'s Status")
        print("="*50)
        print(f"Mood: {self.character.mood}")
        print(f"Relationship Level: {self.character.relationship_level:.0%}")
        print(f"Arousal: {self.character.arousal:.0%}")
        print(f"Energy: {self.character.energy:.0%}")
        print(f"Memories: {len(self.character.get_recent_memories())}")
        print("="*50 + "\n")


def example_basic_chat():
    """Example: Basic chat with a character"""
    print("\n" + "="*60)
    print("Example: Basic Chat with AI Companion")
    print("="*60 + "\n")
    
    # Get or create character
    db = Database()
    pers_mgr = Personality()
    
    # Get playful personality
    playful = pers_mgr.get_by_name("Playful Girlfriend")
    if not playful:
        pers_mgr.initialize_defaults()
        playful = pers_mgr.get_by_name("Playful Girlfriend")
    
    # Create character
    char = Character.create(
        name="Luna",
        personality_id=playful['id'],
        age=24,
        sex="female",
        hair_color="brunette",
        eye_color="hazel",
        tags=["girlfriend", "playful", "fun"],
        db=db
    )
    
    print(f"✅ Created character: {char.name}")
    print(f"   Personality: {playful['name']}")
    print(f"   Mood: {char.mood}")
    print()
    
    # Create AI companion
    companion = AICompanion(char)
    
    # Start interactive chat
    companion.chat()


def example_programmatic():
    """Example: Programmatic conversation"""
    print("\n" + "="*60)
    print("Example: Programmatic Conversation")
    print("="*60 + "\n")
    
    # Load existing character
    char = Character.load_by_name("Luna")
    if not char:
        print("❌ Character 'Luna' not found. Run example_basic_chat() first.")
        return
    
    companion = AICompanion(char)
    
    # Predefined conversation
    exchanges = [
        "Hey, how was your day?",
        "I was thinking about you today",
        "Want to do something fun this weekend?",
    ]
    
    for user_msg in exchanges:
        print(f"You: {user_msg}")
        response = companion.generate_response(user_msg)
        print(f"{char.name}: {response}")
        print()
    
    # Show final stats
    companion._print_status()


if __name__ == "__main__":
    import sys
    
    print("\n" + "="*60)
    print("🎮 Virtual Companion - LM Studio Integration Example")
    print("="*60)
    print("\n⚠️  Make sure LM Studio is running on http://localhost:1234")
    print("   with a model loaded!\n")
    
    print("Select example:")
    print("1. Interactive Chat")
    print("2. Programmatic Conversation")
    print()
    
    choice = input("Enter choice (1-2): ").strip()
    
    if choice == "1":
        example_basic_chat()
    elif choice == "2":
        example_programmatic()
    else:
        print("Invalid choice.")
        sys.exit(1)
