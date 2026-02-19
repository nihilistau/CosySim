"""
Autonomous Messenger Service
Background service for character-initiated messaging
"""

import time
import random
from datetime import datetime, timedelta
from typing import Optional, Dict, List
from pathlib import Path
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.interval import IntervalTrigger
from apscheduler.triggers.cron import CronTrigger
import sys

sys.path.append(str(Path(__file__).parent.parent.parent))

from simulation.database.db import Database
from simulation.character_system.character import Character
from simulation.services.media_generator import MediaGenerator


class AutonomousMessenger:
    """
    Background service that makes characters send messages autonomously
    """
    
    def __init__(self, db: Database, socketio=None):
        self.db = db
        self.socketio = socketio  # For real-time push
        self.scheduler = BackgroundScheduler()
        self.media_gen = MediaGenerator()
        
        # Configuration
        self.enabled = False
        self.active_characters: Dict[str, Dict] = {}  # character_id -> config
        
    def enable(self):
        """Enable autonomous messaging"""
        if not self.enabled:
            self.scheduler.start()
            self.enabled = True
            print("✅ Autonomous messaging enabled")
    
    def disable(self):
        """Disable autonomous messaging"""
        if self.enabled:
            self.scheduler.shutdown()
            self.enabled = False
            print("❌ Autonomous messaging disabled")
    
    def register_character(
        self,
        character_id: str,
        frequency: str = "moderate",  # low, moderate, high
        time_range: tuple = (8, 23),  # Active hours (8am to 11pm)
        enable_photos: bool = True,
        enable_voice: bool = False
    ):
        """
        Register a character for autonomous messaging
        
        Args:
            character_id: Character ID
            frequency: How often to message (low=rare, moderate=normal, high=frequent)
            time_range: Hours when character is active (start, end)
            enable_photos: Can send photos autonomously
            enable_voice: Can send voice messages
        """
        # Calculate interval based on frequency
        intervals = {
            "low": (3600, 7200),      # 1-2 hours
            "moderate": (1800, 3600),  # 30min-1hour
            "high": (600, 1800)        # 10-30 minutes
        }
        
        min_interval, max_interval = intervals.get(frequency, intervals["moderate"])
        
        config = {
            "character_id": character_id,
            "frequency": frequency,
            "time_range": time_range,
            "enable_photos": enable_photos,
            "enable_voice": enable_voice,
            "min_interval": min_interval,
            "max_interval": max_interval,
            "last_message_time": None,
            "next_message_time": None
        }
        
        self.active_characters[character_id] = config
        
        # Schedule checks
        self._schedule_character_checks(character_id)
        
        print(f"✅ Registered {character_id} for autonomous messaging ({frequency})")
    
    def unregister_character(self, character_id: str):
        """Unregister character from autonomous messaging"""
        if character_id in self.active_characters:
            # Remove scheduled jobs
            for job in self.scheduler.get_jobs():
                if character_id in job.id:
                    job.remove()
            
            del self.active_characters[character_id]
            print(f"❌ Unregistered {character_id} from autonomous messaging")
    
    def _schedule_character_checks(self, character_id: str):
        """Schedule periodic checks for a character"""
        # Check every 5 minutes if character should send message
        self.scheduler.add_job(
            self._check_and_send,
            IntervalTrigger(minutes=5),
            args=[character_id],
            id=f"check_{character_id}",
            replace_existing=True
        )
        
        # Morning message (random time between 7-9am)
        self.scheduler.add_job(
            self._send_morning_message,
            CronTrigger(hour=random.randint(7, 8), minute=random.randint(0, 59)),
            args=[character_id],
            id=f"morning_{character_id}",
            replace_existing=True
        )
        
        # Evening message (random time between 7-10pm)
        self.scheduler.add_job(
            self._send_evening_message,
            CronTrigger(hour=random.randint(19, 21), minute=random.randint(0, 59)),
            args=[character_id],
            id=f"evening_{character_id}",
            replace_existing=True
        )
    
    def _check_and_send(self, character_id: str):
        """Check if character should send a message"""
        if character_id not in self.active_characters:
            return
        
        config = self.active_characters[character_id]
        
        # Check if within active hours
        current_hour = datetime.now().hour
        start_hour, end_hour = config["time_range"]
        
        if not (start_hour <= current_hour < end_hour):
            return  # Outside active hours
        
        # Check if enough time has passed since last message
        if config["last_message_time"]:
            time_since_last = (datetime.now() - config["last_message_time"]).total_seconds()
            min_interval = config["min_interval"]
            
            if time_since_last < min_interval:
                return  # Too soon
        
        # Random chance based on frequency
        chance = {
            "low": 0.1,
            "moderate": 0.3,
            "high": 0.6
        }[config["frequency"]]
        
        if random.random() < chance:
            self._send_autonomous_message(character_id)
    
    def _send_autonomous_message(self, character_id: str):
        """Send an autonomous message from character"""
        try:
            # Load character
            character = Character.load(character_id, self.db)
            if not character:
                return
            
            config = self.active_characters[character_id]
            
            # Decide message type
            message_type = self._choose_message_type(character, config)
            
            if message_type == "text":
                content = self._generate_autonomous_text(character)
                self._send_message(character, content, type="text")
            
            elif message_type == "photo":
                # Generate and send photo
                photo_path = self._generate_autonomous_photo(character)
                if photo_path:
                    caption = self._generate_photo_caption(character)
                    self._send_message(character, caption, type="photo", media_path=photo_path)
            
            elif message_type == "voice":
                # TODO: Implement voice message generation
                pass
            
            # Update last message time
            config["last_message_time"] = datetime.now()
            
            print(f"📱 {character.name} sent autonomous {message_type} message")
        
        except Exception as e:
            print(f"Error sending autonomous message: {e}")
    
    def _choose_message_type(self, character: Character, config: Dict) -> str:
        """Choose what type of message to send"""
        options = ["text"]
        
        if config["enable_photos"] and character.relationship_level > 0.3:
            options.extend(["photo"] * 2)  # Twice the weight
        
        if config["enable_voice"]:
            options.append("voice")
        
        return random.choice(options)
    
    def _generate_autonomous_text(self, character: Character) -> str:
        """Generate autonomous text message based on character and context"""
        # Time-based messages
        hour = datetime.now().hour
        
        if 6 <= hour < 12:
            templates = [
                "Good morning! ☀️",
                "Hey, just thinking about you 💭",
                "Morning! Hope you have a great day!",
                "Just woke up, what are you up to?"
            ]
        elif 12 <= hour < 17:
            templates = [
                "Hey! How's your day going?",
                "Been thinking about you ❤️",
                "What are you up to right now?",
                "Miss you! When can we talk?"
            ]
        elif 17 <= hour < 22:
            templates = [
                "Hey! How was your day?",
                "Evening! Wanna chat?",
                "Just got home, what are you doing?",
                "Thinking about you 💭"
            ]
        else:
            templates = [
                "Can't sleep... you up?",
                "Late night thoughts of you 🌙",
                "Hey night owl 🦉",
                "Missing you right now"
            ]
        
        # Modify based on mood and relationship
        if character.mood > 0.7:
            templates.extend([
                "I'm in such a good mood! 😊",
                "Feeling amazing today!",
                "You always make me smile"
            ])
        
        if character.relationship_level > 0.7:
            templates.extend([
                "I love talking to you ❤️",
                "You're always on my mind",
                "Can't wait to see you again"
            ])
        
        return random.choice(templates)
    
    def _generate_autonomous_photo(self, character: Character) -> Optional[str]:
        """Generate photo for autonomous message"""
        try:
            # Get character description
            char_desc = f"{character.hair_color} hair, {character.eye_color} eyes"
            
            # Choose context based on relationship and time
            relationship = character.relationship_level
            context = self.media_gen.get_random_selfie_context(relationship)
            
            # Generate selfie
            photo_path = self.media_gen.generate_selfie(
                character_name=character.name,
                character_description=char_desc,
                mood=context["mood"],
                setting=context["setting"],
                nsfw=context["nsfw"]
            )
            
            return photo_path
        
        except Exception as e:
            print(f"Error generating autonomous photo: {e}")
            return None
    
    def _generate_photo_caption(self, character: Character) -> str:
        """Generate caption for autonomous photo"""
        captions = [
            "Just took this, what do you think? 📸",
            "Thought you'd like this 😊",
            "For you 💕",
            "Missing you right now",
            "How do I look? 😘",
            "Thinking of you...",
        ]
        
        if character.relationship_level > 0.7:
            captions.extend([
                "Just for you 😉",
                "Been waiting to send you this...",
                "You like? 💋"
            ])
        
        return random.choice(captions)
    
    def _send_morning_message(self, character_id: str):
        """Send morning message"""
        try:
            character = Character.load(character_id, self.db)
            if not character:
                return
            
            messages = [
                "Good morning! ☀️ Hope you slept well!",
                "Morning sunshine! Have a great day! 😊",
                "Just woke up thinking about you 💭",
                "Good morning! ❤️",
                "Hey! Ready for the day?"
            ]
            
            self._send_message(character, random.choice(messages), type="text")
            
            # Update config
            if character_id in self.active_characters:
                self.active_characters[character_id]["last_message_time"] = datetime.now()
        
        except Exception as e:
            print(f"Error sending morning message: {e}")
    
    def _send_evening_message(self, character_id: str):
        """Send evening message"""
        try:
            character = Character.load(character_id, self.db)
            if not character:
                return
            
            messages = [
                "Hey! How was your day? 😊",
                "Evening! Wanna talk?",
                "Hope you had a good day! ❤️",
                "Hey! Free to chat?",
                "Thinking about you tonight 💭"
            ]
            
            self._send_message(character, random.choice(messages), type="text")
            
            # Update config
            if character_id in self.active_characters:
                self.active_characters[character_id]["last_message_time"] = datetime.now()
        
        except Exception as e:
            print(f"Error sending evening message: {e}")
    
    def _send_message(
        self,
        character: Character,
        content: str,
        type: str = "text",
        media_path: str = None
    ):
        """Send message through database and optionally through SocketIO"""
        # Store in database
        interaction_data = {
            "role": "assistant",
            "content": content,
            "timestamp": datetime.now().isoformat(),
            "type": type,
            "autonomous": True
        }
        
        if media_path:
            interaction_data["media_path"] = media_path
        
        character.add_interaction("message", interaction_data)
        
        # Send via SocketIO if available
        if self.socketio:
            self.socketio.emit('message_received', {
                "role": "assistant",
                "content": content,
                "timestamp": datetime.now().isoformat(),
                "type": type,
                "media_url": f"/api/media/download/{media_path}" if media_path else None,
                "autonomous": True
            }, broadcast=True)


# Quick test
if __name__ == "__main__":
    db = Database()
    messenger = AutonomousMessenger(db)
    
    # Enable service
    messenger.enable()
    
    # Register test character
    # messenger.register_character("test_character_id", frequency="high")
    
    print("Autonomous messenger running... Press Ctrl+C to stop")
    
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        messenger.disable()
        print("\nStopped")
