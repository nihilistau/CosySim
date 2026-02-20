"""
Autonomous Messenger Service
Background service for character-initiated messaging.

Every autonomous send cycle is recorded as an EventChain starting with an
``autonomous_trigger`` root event so that the diagnostics panel can trace
exactly when and why a character reached out.
"""

import time
import random
from datetime import datetime
from typing import Optional, Dict, List
from pathlib import Path
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.interval import IntervalTrigger
from apscheduler.triggers.cron import CronTrigger
import sys

project_root = Path(__file__).parent.parent.parent
sys.path.insert(0, str(project_root))

from content.simulation.database.db import Database
from content.simulation.database.events import EventChain
from content.simulation.character_system.character import Character
from content.simulation.services.media_generator import MediaGenerator


def _float_safe(val, default=0.5):
    """Safely convert a value to float, returning default if it's a non-numeric string."""
    try:
        return float(val)
    except (TypeError, ValueError):
        return default


class AutonomousMessenger:
    """
    Background service that makes characters send messages autonomously.

    Characters registered with :meth:`register_character` will have messages
    generated and delivered on a schedule controlled by their frequency setting.
    Each send cycle is logged to the EventChain for full audit-trail visibility.
    """
    
    def __init__(self, db: Database, socketio=None):
        self.db = db
        self.socketio = socketio  # For real-time push
        self.scheduler = BackgroundScheduler()
        self.media_gen = MediaGenerator()
        self.event_chain = EventChain(self.db)  # Shared diagnostics log
        # Voice message generator for autonomous voice sends
        from content.simulation.services.voice_message import VoiceMessageGenerator
        self.voice_gen = VoiceMessageGenerator(db=self.db)

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
        if config["last_message_time"] is not None:
            last = config["last_message_time"]
            if not isinstance(last, datetime):
                try:
                    last = datetime.fromisoformat(str(last))
                except Exception:
                    last = None
            if last is not None:
                time_since_last = (datetime.now() - last).total_seconds()
                min_interval = float(config["min_interval"])
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
        """Send an autonomous message from character with full EventChain logging."""
        # Start a diagnostics chain so every part of this cycle is traceable
        chain_id = self.event_chain.start_chain(
            scene_id='autonomous_messenger',
            character_id=character_id,
            summary=f'Autonomous cycle for {character_id}',
        )
        trigger_ev = self.event_chain.log(
            event_type='autonomous_trigger',
            actor='system',
            payload={
                'character_id': character_id,
                'frequency': self.active_characters.get(character_id, {}).get('frequency', 'unknown'),
            },
            summary=f'Autonomous trigger fired for {character_id}',
            chain_id=chain_id,
            scene_id='autonomous_messenger',
            character_id=character_id,
        )

        try:
            # Load character
            character = Character.load(character_id, self.db)
            if not character:
                self.event_chain.log(
                    event_type='error',
                    actor='system',
                    payload={'reason': 'character_not_found', 'character_id': character_id},
                    summary=f'Character {character_id} not found — skipping cycle',
                    chain_id=chain_id,
                    scene_id='autonomous_messenger',
                    character_id=character_id,
                    parent_id=trigger_ev,
                )
                return

            config = self.active_characters[character_id]

            # Decide message type
            message_type = self._choose_message_type(character, config)

            # Log the decision
            decide_ev = self.event_chain.log(
                event_type='tool_call',
                actor='system',
                payload={'message_type': message_type, 'enable_photos': config.get('enable_photos'), 'enable_voice': config.get('enable_voice')},
                summary=f'Chose message type: {message_type}',
                chain_id=chain_id,
                scene_id='autonomous_messenger',
                character_id=character_id,
                parent_id=trigger_ev,
            )

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
                text = self._generate_voice_text(character)
                voice_msg = self.voice_gen.generate_voice_message(
                    character_id=character_id,
                    character_name=character.name,
                    text=text,
                    emotion=getattr(character, 'mood', 'neutral'),
                    chain_id=chain_id,
                    scene_id='autonomous_messenger',
                )
                if voice_msg:
                    self._send_message(character, f"[Voice message: {text}]",
                                       type="voice", media_path=voice_msg.get('filepath'))

            # Log successful send
            self.event_chain.log(
                event_type='message_out',
                actor='agent',
                payload={'message_type': message_type, 'character': character.name},
                summary=f'{character.name} sent autonomous {message_type}',
                chain_id=chain_id,
                scene_id='autonomous_messenger',
                character_id=character_id,
                parent_id=decide_ev,
            )

            # Update last message time
            config["last_message_time"] = datetime.now()

            # MCP: publish to ActivityBus
            try:
                from engine.services.activity_bus import get_activity_bus
                get_activity_bus().publish(
                    activity_type="autonomous_message",
                    description=f"{character.name} sent autonomous {message_type}",
                    agent_id=character_id,
                    scene="autonomous_messenger",
                    data={
                        "message_type": message_type,
                        "character_name": character.name,
                        "chain_id": chain_id,
                    },
                )
            except Exception:
                pass

            print(f"📱 {character.name} sent autonomous {message_type} message")

        except Exception as e:
            self.event_chain.log_error(
                e,
                chain_id=chain_id,
                scene_id='autonomous_messenger',
                character_id=character_id,
                parent_id=trigger_ev,
            )
            print(f"Error sending autonomous message: {e}")
    
    def _choose_message_type(self, character: Character, config: Dict) -> str:
        """Choose what type of message to send"""
        options = ["text"]
        
        if config["enable_photos"] and float(character.relationship_level) > 0.3:
            options.extend(["photo"] * 2)  # Twice the weight
        
        if config["enable_voice"]:
            options.append("voice")
        
        return random.choice(options)
    
    def _generate_autonomous_text(self, character: Character) -> str:
        """Generate autonomous text message — content escalates with relationship + arousal."""
        hour = datetime.now().hour
        rel     = _float_safe(character.relationship_level)
        arousal = _float_safe(getattr(character, 'arousal', 0.0), 0.0)
        
        # ── High intimacy tier (rel > 0.7 AND arousal > 0.5) ───────────
        if rel > 0.7 and arousal > 0.5:
            if 22 <= hour or hour < 6:
                templates = [
                    "Can't stop thinking about last time... 🥵",
                    "Lying in bed wishing you were here 💋",
                    "I'm wearing something you'd like right now 😈",
                    "Come over... I can't sleep without you",
                    "Want to see what I'm wearing? 🔥",
                    "I'm so turned on right now... help me 😏",
                ]
            else:
                templates = [
                    "Thinking naughty thoughts about you at work 🙈",
                    "I need you... like, right now 🥵",
                    "Remember what we talked about? I can't focus 😈",
                    "You drive me crazy, you know that? 💋",
                    "Just saw something that reminded me of you... in a very good way 🔥",
                    "When are you coming over? I have plans for us 😏",
                ]
            return random.choice(templates)

        # ── Flirty tier (rel > 0.5 OR arousal > 0.3) ───────────────────
        if rel > 0.5 or arousal > 0.3:
            if 22 <= hour or hour < 6:
                templates = [
                    "Hey you... can't sleep 🌙",
                    "Late night and thinking of you 😘",
                    "Wish we could cuddle right now 💕",
                    "You up? I'm feeling... restless 😏",
                ]
            else:
                templates = [
                    "Been thinking about you all day 😘",
                    "You make me smile so much 💕",
                    "Miss your face... and everything else 😉",
                    "Counting down until I see you again 💋",
                    "You looked so good last time... just saying 🔥",
                ]
            return random.choice(templates)

        # ── Standard tier — time-of-day templates ───────────────────────
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
        """Generate caption for autonomous photo — escalates with intimacy."""
        rel     = _float_safe(character.relationship_level)
        arousal = _float_safe(getattr(character, 'arousal', 0.0), 0.0)

        if rel > 0.7 and arousal > 0.5:
            captions = [
                "This is just for you... 🔥",
                "Do you like what you see? 😈",
                "Thinking of you while I took this 💋",
                "Want more? 😏",
                "I dare you to come over after seeing this 🥵",
                "Been saving this one for you 💦",
            ]
        elif rel > 0.5:
            captions = [
                "Just for you 😉",
                "How do I look? 😘",
                "Been waiting to send you this...",
                "You like? 💋",
                "Rate me? 🔥",
                "Felt cute, might delete later 💕",
            ]
        else:
            captions = [
                "Just took this, what do you think? 📸",
                "Thought you'd like this 😊",
                "For you 💕",
                "Missing you right now",
                "How do I look?",
            ]
        
        return random.choice(captions)

    def _generate_voice_text(self, character: Character) -> str:
        """Generate text for voice messages — escalates with intimacy."""
        rel = _float_safe(character.relationship_level)
        arousal = _float_safe(getattr(character, 'arousal', 0.0), 0.0)
        hour = datetime.now().hour

        if rel > 0.7 and arousal > 0.5:
            texts = [
                "Hey... I just wanted to hear your voice. I'm lying in bed thinking about you.",
                "I can't stop thinking about last night. Call me back when you get this...",
                "You know that thing you do that drives me crazy? Yeah... thinking about that.",
                "I miss you so much right now. Come over... please?",
            ]
        elif rel > 0.5:
            texts = [
                "Hey! Just wanted to leave you a little message. I miss you!",
                "Hi babe, just thinking about you. Call me when you're free?",
                f"It's {hour}:00 and I'm still thinking about our last conversation.",
                "Hey you... I had something funny to tell you but I forgot. Call me!",
            ]
        else:
            texts = [
                "Hey! Just wanted to say hi and see how you're doing.",
                "Hi! Hope you're having a good day. Talk soon!",
                "Just leaving you a quick voice note. Call me when you can!",
                "Hey! Thought I'd leave you a message instead of texting for once.",
            ]
        return random.choice(texts)
    
    def _send_morning_message(self, character_id: str):
        """Send morning message — flirty at high relationship."""
        try:
            character = Character.load(character_id, self.db)
            if not character:
                return
            
            rel     = _float_safe(character.relationship_level)
            arousal = _float_safe(getattr(character, 'arousal', 0.0), 0.0)
            
            if rel > 0.7 and arousal > 0.4:
                messages = [
                    "Good morning sexy 😘 I had the best dream about you...",
                    "Woke up thinking about you... in the best way 🥵",
                    "Morning babe 💋 wish I woke up next to you",
                    "Good morning handsome... I'm still in bed if you want to join me 😏",
                ]
            elif rel > 0.5:
                messages = [
                    "Good morning cutie! 😘 Have an amazing day!",
                    "Morning! I dreamt about you 💭💕",
                    "Rise and shine beautiful! ☀️❤️",
                    "Hey! Just wanted to be the first to say good morning 😊",
                ]
            else:
                messages = [
                    "Good morning! ☀️ Hope you slept well!",
                    "Morning sunshine! Have a great day! 😊",
                    "Good morning! ❤️",
                    "Hey! Ready for the day?",
                ]
            
            self._send_message(character, random.choice(messages), type="text")
            
            if character_id in self.active_characters:
                self.active_characters[character_id]["last_message_time"] = datetime.now()
        
        except Exception as e:
            print(f"Error sending morning message: {e}")
    
    def _send_evening_message(self, character_id: str):
        """Send evening message — intimate at high relationship."""
        try:
            character = Character.load(character_id, self.db)
            if not character:
                return
            
            rel     = _float_safe(character.relationship_level)
            arousal = _float_safe(getattr(character, 'arousal', 0.0), 0.0)
            
            if rel > 0.7 and arousal > 0.4:
                messages = [
                    "Hey... I'm home alone tonight. Wanna keep me company? 😏",
                    "Just got in the bath... thinking of you 🛁💋",
                    "Evening babe... I miss your touch 🥵",
                    "What are you wearing right now? 😈",
                    "Come over... I'll make it worth your while 🔥",
                ]
            elif rel > 0.5:
                messages = [
                    "Hey gorgeous! How was your day? 😘",
                    "Evening! Can't stop thinking about you 💕",
                    "Hey cutie, wanna talk? 💋",
                    "Just snuggled up on the couch... wish you were here ❤️",
                ]
            else:
                messages = [
                    "Hey! How was your day? 😊",
                    "Evening! Wanna talk?",
                    "Hope you had a good day! ❤️",
                    "Hey! Free to chat?",
                ]
            
            self._send_message(character, random.choice(messages), type="text")
            
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
            self.socketio.emit('autonomous_message', {
                "role": "assistant",
                "content": content,
                "timestamp": datetime.now().isoformat(),
                "type": type,
                "media_url": f"/api/media/download/{media_path}" if media_path else None,
                "autonomous": True
            })


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
