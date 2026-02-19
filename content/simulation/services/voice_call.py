"""
Voice Call Handler
Real-time voice call system using CosyVoice TTS and Whisper STT
"""

import os
import time
import queue
import threading
from datetime import datetime
from pathlib import Path
from typing import Optional, Dict, Callable
import sys

project_root = Path(__file__).parent.parent.parent
sys.path.insert(0, str(project_root))

from content.simulation.database.db import Database


class VoiceCallHandler:
    """
    Handle real-time voice calls between user and character
    Uses CosyVoice for character speech and Whisper for user speech recognition
    """
    
    def __init__(
        self,
        cosyvoice_model=None,
        whisper_model=None,
        db: Database = None,
        socketio=None
    ):
        self.cosyvoice = cosyvoice_model
        self.whisper = whisper_model
        self.db = db
        self.socketio = socketio
        
        # Call state
        self.active_call = None
        self.call_active = False
        self.audio_queue = queue.Queue()
        self.response_queue = queue.Queue()
        
        # Voice settings
        self.sample_rate = 22050
        self.prompt_wav = None
        self.prompt_text = "Hello, this is my voice."
        
        # LLM callback for conversation
        self.llm_callback = None
    
    def set_character_voice(self, prompt_wav_path: str, prompt_text: str = None):
        """Set the character's voice sample"""
        if os.path.exists(prompt_wav_path):
            self.prompt_wav = prompt_wav_path
            if prompt_text:
                self.prompt_text = prompt_text
            print(f"✅ Character voice set from {prompt_wav_path}")
        else:
            print(f"⚠️ Voice sample not found: {prompt_wav_path}")
    
    def set_llm_callback(self, callback: Callable):
        """
        Set callback function for LLM conversation
        
        Args:
            callback: Function that takes (character, user_text) and returns response text
        """
        self.llm_callback = callback
    
    def start_call(
        self,
        character_id: str,
        character_name: str,
        call_type: str = "incoming"
    ) -> str:
        """
        Start a voice call
        
        Args:
            character_id: ID of character
            character_name: Name of character
            call_type: "incoming" or "outgoing"
        
        Returns:
            Call ID
        """
        call_id = f"call_{datetime.now().strftime('%Y%m%d_%H%M%S')}_{character_id[:8]}"
        
        self.active_call = {
            "id": call_id,
            "character_id": character_id,
            "character_name": character_name,
            "type": call_type,
            "started_at": datetime.now().isoformat(),
            "ended_at": None,
            "duration": 0,
            "status": "ringing"
        }
        
        self.call_active = False  # Not answered yet
        
        # Emit call event via SocketIO
        if self.socketio:
            self.socketio.emit('incoming_call', {
                "call_id": call_id,
                "character_name": character_name,
                "type": call_type
            }, broadcast=True)
        
        print(f"📞 Call started: {call_id} ({call_type})")
        
        return call_id
    
    def answer_call(self, call_id: str):
        """Answer an incoming call"""
        if not self.active_call or self.active_call["id"] != call_id:
            print(f"❌ No active call with ID {call_id}")
            return False
        
        self.call_active = True
        self.active_call["status"] = "active"
        
        # Start audio processing threads
        self._start_audio_threads()
        
        # Emit call answered event
        if self.socketio:
            self.socketio.emit('call_answered', {
                "call_id": call_id
            }, broadcast=True)
        
        # Character greeting
        greeting = self._get_call_greeting()
        self._speak(greeting)
        
        print(f"✅ Call answered: {call_id}")
        
        return True
    
    def end_call(self, call_id: str = None):
        """End the active call"""
        if not self.active_call:
            return False
        
        if call_id and self.active_call["id"] != call_id:
            return False
        
        self.call_active = False
        
        # Stop and clean up threads
        self._stop_audio_threads()
        
        # Calculate duration
        start_time = datetime.fromisoformat(self.active_call["started_at"])
        duration = (datetime.now() - start_time).total_seconds()
        
        self.active_call["ended_at"] = datetime.now().isoformat()
        self.active_call["duration"] = duration
        self.active_call["status"] = "ended"
        
        # Store call log in database
        if self.db:
            self._store_call_log(self.active_call)
        
        # Emit call ended event
        if self.socketio:
            self.socketio.emit('call_ended', {
                "call_id": self.active_call["id"],
                "duration": duration
            }, broadcast=True)
        
        print(f"📞 Call ended: {self.active_call['id']} (duration: {duration:.1f}s)")
        
        # Clear state
        call_info = self.active_call
        self.active_call = None
        
        return call_info
    
    def _start_audio_threads(self):
        """Start background threads for audio processing"""
        # Thread 1: Listen to user speech (STT)
        self.listen_thread = threading.Thread(target=self._listen_loop, daemon=True)
        self.listen_thread.start()
        
        # Thread 2: Generate character responses (TTS)
        self.speak_thread = threading.Thread(target=self._speak_loop, daemon=True)
        self.speak_thread.start()
    
    def _stop_audio_threads(self):
        """Stop and clean up audio processing threads"""
        # Signal threads to stop (call_active = False already set)
        
        # Clear queues to unblock any waiting threads
        while not self.audio_queue.empty():
            try:
                self.audio_queue.get_nowait()
            except queue.Empty:
                break
        
        while not self.response_queue.empty():
            try:
                self.response_queue.get_nowait()
            except queue.Empty:
                break
        
        # Join threads with timeout
        if self.listen_thread and self.listen_thread.is_alive():
            self.listen_thread.join(timeout=5.0)
            if self.listen_thread.is_alive():
                print("⚠️ Warning: Listen thread did not stop cleanly")
        
        if self.speak_thread and self.speak_thread.is_alive():
            self.speak_thread.join(timeout=5.0)
            if self.speak_thread.is_alive():
                print("⚠️ Warning: Speak thread did not stop cleanly")
        
        # Clear thread references
        self.listen_thread = None
        self.speak_thread = None
    
    def _listen_loop(self):
        """Background loop to listen to user speech"""
        while self.call_active:
            try:
                # Get audio from queue (sent from frontend)
                audio_data = self.audio_queue.get(timeout=1.0)
                
                # Transcribe with Whisper
                if self.whisper:
                    text = self._transcribe_audio(audio_data)
                    
                    if text:
                        print(f"👤 User: {text}")
                        
                        # Get character response
                        if self.llm_callback:
                            response = self.llm_callback(
                                self.active_call["character_id"],
                                text
                            )
                            
                            if response:
                                # Queue response for TTS
                                self.response_queue.put(response)
                
            except queue.Empty:
                continue
            except Exception as e:
                print(f"Error in listen loop: {e}")
    
    def _speak_loop(self):
        """Background loop to generate character speech"""
        while self.call_active:
            try:
                # Get response text from queue
                text = self.response_queue.get(timeout=1.0)
                
                # Generate audio with CosyVoice
                self._speak(text)
                
            except queue.Empty:
                continue
            except Exception as e:
                print(f"Error in speak loop: {e}")
    
    def _speak(self, text: str):
        """Generate and stream character speech"""
        if not self.cosyvoice:
            print(f"🤖 Character (no TTS): {text}")
            # Send text-only response if no TTS
            if self.socketio:
                self.socketio.emit('call_audio', {
                    "type": "text",
                    "text": text
                }, broadcast=True)
            return
        
        try:
            print(f"🤖 Character: {text}")
            
            # Generate audio with CosyVoice
            if self.prompt_wav:
                audio_generator = self.cosyvoice.inference_zero_shot(
                    tts_text=text,
                    prompt_text=self.prompt_text,
                    prompt_wav=self.prompt_wav,
                    stream=True  # Stream for real-time
                )
            else:
                audio_generator = self.cosyvoice.inference_sft(
                    tts_text=text,
                    stream=True
                )
            
            # Stream audio chunks to client
            for chunk in audio_generator:
                if not self.call_active:
                    break
                
                if 'tts_speech' in chunk:
                    # Convert to bytes and send via SocketIO
                    audio_bytes = self._audio_to_bytes(chunk['tts_speech'])
                    
                    if self.socketio:
                        self.socketio.emit('call_audio', {
                            "type": "audio",
                            "data": audio_bytes,
                            "sample_rate": self.sample_rate
                        }, broadcast=True)
        
        except Exception as e:
            print(f"Error generating speech: {e}")
    
    def _transcribe_audio(self, audio_data) -> Optional[str]:
        """Transcribe user audio with Whisper"""
        if not self.whisper:
            return None
        
        try:
            # Transcribe with Whisper
            result = self.whisper.transcribe(audio_data)
            text = result.get("text", "").strip()
            
            return text if text else None
        
        except Exception as e:
            print(f"Error transcribing audio: {e}")
            return None
    
    def _audio_to_bytes(self, audio_tensor):
        """Convert audio tensor to bytes for transmission"""
        import torch
        import numpy as np
        
        # Convert to numpy
        audio_np = audio_tensor.cpu().numpy()
        
        # Normalize and convert to int16
        audio_np = np.clip(audio_np, -1.0, 1.0)
        audio_int16 = (audio_np * 32767).astype(np.int16)
        
        return audio_int16.tobytes()
    
    def receive_audio(self, audio_data):
        """Receive audio from client (user speaking)"""
        if self.call_active:
            self.audio_queue.put(audio_data)
    
    def _get_call_greeting(self) -> str:
        """Get greeting message for call start"""
        import random
        
        greetings = [
            "Hey! How are you?",
            "Hi! Good to hear from you!",
            "Hello! What's up?",
            "Hey there! Miss me?",
            "Hi! I was just thinking about you!",
            "Hey! Perfect timing, I was hoping you'd call!"
        ]
        
        return random.choice(greetings)
    
    def _store_call_log(self, call_info: Dict):
        """Store call log in database"""
        if not self.db:
            return
        
        try:
            with self.db.get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute("""
                    INSERT INTO interactions (character_id, type, content, metadata)
                    VALUES (?, ?, ?, ?)
                """, (
                    call_info["character_id"],
                    "voice_call",
                    f"Voice call ({call_info['type']})",
                    f'{{"call_id": "{call_info["id"]}", "duration": {call_info["duration"]}, '
                    f'"started_at": "{call_info["started_at"]}", "ended_at": "{call_info["ended_at"]}"}}'
                ))
                conn.commit()
                
                print(f"✅ Call log stored in database")
        
        except Exception as e:
            print(f"Error storing call log: {e}")
    
    def get_call_status(self) -> Dict:
        """Get current call status"""
        if self.active_call:
            # Calculate current duration
            start_time = datetime.fromisoformat(self.active_call["started_at"])
            current_duration = (datetime.now() - start_time).total_seconds()
            
            return {
                **self.active_call,
                "current_duration": current_duration,
                "is_active": self.call_active
            }
        else:
            return {
                "status": "no_active_call"
            }
    
    def get_call_history(self, character_id: str = None, limit: int = 10) -> list:
        """Get call history from database"""
        if not self.db:
            return []
        
        query = """
            SELECT id, character_id, content, metadata, timestamp
            FROM interactions
            WHERE type = 'voice_call'
        """
        params = []
        
        if character_id:
            query += " AND character_id = ?"
            params.append(character_id)
        
        query += " ORDER BY timestamp DESC LIMIT ?"
        params.append(limit)
        
        history = []
        try:
            with self.db.get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute(query, params)
                
                for row in cursor.fetchall():
                    history.append({
                        "id": row[0],
                        "character_id": row[1],
                        "description": row[2],
                        "metadata": row[3],
                        "timestamp": row[4]
                    })
        
        except Exception as e:
            print(f"Error fetching call history: {e}")
        
        return history


# Quick test
if __name__ == "__main__":
    from content.simulation.database.db import Database
    
    db = Database()
    handler = VoiceCallHandler(db=db)
    
    # Start test call
    call_id = handler.start_call(
        character_id="test_char_123",
        character_name="Emma",
        call_type="incoming"
    )
    
    print(f"\nCall ID: {call_id}")
    print("Simulating call...")
    
    # Simulate answering
    time.sleep(1)
    handler.answer_call(call_id)
    
    # Simulate conversation
    time.sleep(5)
    
    # End call
    call_info = handler.end_call(call_id)
    print(f"\nCall ended:")
    print(f"  Duration: {call_info['duration']:.1f}s")
    print(f"  Started: {call_info['started_at']}")
    print(f"  Ended: {call_info['ended_at']}")
