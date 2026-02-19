"""
Video Call Handler
Real-time video calls with generated character faces and lip sync
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
from content.simulation.services.media_generator import MediaGenerator
from content.simulation.services.voice_call import VoiceCallHandler


class VideoCallHandler:
    """
    Handle real-time video calls with character
    Combines voice call functionality with generated video frames
    """
    
    def __init__(
        self,
        media_gen: MediaGenerator = None,
        voice_handler: VoiceCallHandler = None,
        db: Database = None,
        socketio=None
    ):
        self.media_gen = media_gen or MediaGenerator()
        self.voice_handler = voice_handler or VoiceCallHandler(db=db, socketio=socketio)
        self.db = db
        self.socketio = socketio
        
        # Video state
        self.active_video_call = None
        self.video_active = False
        self.frame_queue = queue.Queue()
        
        # Thread management
        self.video_thread = None
        
        # Video settings
        self.fps = 15  # Lower FPS for streaming
        self.resolution = (480, 640)  # Portrait orientation
        
        # Character appearance cache
        self.character_images = {}
        
        # Face states for animation
        self.face_states = ["neutral", "talking", "smiling", "blinking"]
    
    def start_video_call(
        self,
        character_id: str,
        character_name: str,
        character_description: str,
        call_type: str = "incoming"
    ) -> str:
        """
        Start a video call
        
        Args:
            character_id: Character ID
            character_name: Character name
            character_description: Physical description for face generation
            call_type: "incoming" or "outgoing"
        
        Returns:
            Call ID
        """
        # Start voice call first
        call_id = self.voice_handler.start_call(
            character_id=character_id,
            character_name=character_name,
            call_type=call_type
        )
        
        self.active_video_call = {
            "call_id": call_id,
            "character_id": character_id,
            "character_name": character_name,
            "character_description": character_description,
            "type": call_type,
            "started_at": datetime.now().isoformat(),
            "ended_at": None,
            "video_enabled": True
        }
        
        self.video_active = False  # Not answered yet
        
        print(f"📹 Video call started: {call_id}")
        
        return call_id
    
    def answer_video_call(self, call_id: str):
        """Answer an incoming video call"""
        if not self.active_video_call or self.active_video_call["call_id"] != call_id:
            print(f"❌ No active video call with ID {call_id}")
            return False
        
        # Answer voice call
        self.voice_handler.answer_call(call_id)
        
        self.video_active = True
        
        # Pre-generate character face states
        self._generate_character_faces()
        
        # Start video streaming thread
        self.video_thread = threading.Thread(target=self._video_stream_loop, daemon=True)
        self.video_thread.start()
        
        print(f"✅ Video call answered: {call_id}")
        
        return True
    
    def end_video_call(self, call_id: str = None):
        """End the active video call"""
        if not self.active_video_call:
            return False
        
        if call_id and self.active_video_call["call_id"] != call_id:
            return False
        
        self.video_active = False
        
        # Stop video thread
        self._stop_video_thread()
        
        # End voice call
        call_info = self.voice_handler.end_call(call_id)
        
        if call_info:
            self.active_video_call["ended_at"] = call_info["ended_at"]
            self.active_video_call["duration"] = call_info["duration"]
        
        # Store video call log
        if self.db:
            self._store_video_call_log(self.active_video_call)
        
        # Clear state
        video_call_info = self.active_video_call
        self.active_video_call = None
        self.character_images = {}
        
        print(f"📹 Video call ended: {call_id}")
        
        return video_call_info
    
    def _stop_video_thread(self):
        """Stop and clean up video streaming thread"""
        # Signal thread to stop (video_active = False already set)
        
        # Clear frame queue to unblock any waiting operations
        while not self.frame_queue.empty():
            try:
                self.frame_queue.get_nowait()
            except queue.Empty:
                break
        
        # Join thread with timeout
        if self.video_thread and self.video_thread.is_alive():
            self.video_thread.join(timeout=5.0)
            if self.video_thread.is_alive():
                print("⚠️ Warning: Video thread did not stop cleanly")
        
        # Clear thread reference
        self.video_thread = None
    
    def _generate_character_faces(self):
        """Pre-generate different face states for animation"""
        print("🎨 Generating character face states...")
        
        char_desc = self.active_video_call["character_description"]
        char_name = self.active_video_call["character_name"]
        
        # Generate face for each state
        for state in ["neutral", "talking", "smiling"]:
            try:
                mood_map = {
                    "neutral": "neutral",
                    "talking": "happy",
                    "smiling": "happy"
                }
                
                face_path = self.media_gen.generate_selfie(
                    character_name=char_name,
                    character_description=char_desc,
                    mood=mood_map[state],
                    setting="video_call",
                    style="realistic"
                )
                
                if face_path:
                    self.character_images[state] = face_path
                    print(f"  ✅ Generated {state} face")
            
            except Exception as e:
                print(f"  ❌ Error generating {state} face: {e}")
        
        # Use neutral for missing states
        if "neutral" in self.character_images:
            for state in self.face_states:
                if state not in self.character_images:
                    self.character_images[state] = self.character_images["neutral"]
    
    def _video_stream_loop(self):
        """Background loop to stream video frames"""
        frame_interval = 1.0 / self.fps
        current_state = "neutral"
        state_counter = 0
        
        while self.video_active:
            try:
                start_time = time.time()
                
                # Determine face state based on whether character is speaking
                # Simple animation: alternate between neutral and talking
                if self.voice_handler.call_active:
                    # Animate talking
                    state_counter += 1
                    if state_counter % 4 < 2:
                        current_state = "neutral"
                    else:
                        current_state = "talking"
                else:
                    current_state = "neutral"
                
                # Get frame for current state
                frame_path = self.character_images.get(current_state)
                
                if frame_path:
                    # Send frame via SocketIO
                    self._send_video_frame(frame_path)
                
                # Sleep to maintain FPS
                elapsed = time.time() - start_time
                sleep_time = max(0, frame_interval - elapsed)
                time.sleep(sleep_time)
            
            except Exception as e:
                print(f"Error in video stream loop: {e}")
                time.sleep(frame_interval)
    
    def _send_video_frame(self, frame_path: str):
        """Send video frame to client"""
        try:
            import base64
            
            # Read image file
            with open(frame_path, 'rb') as f:
                image_data = f.read()
            
            # Encode as base64
            image_b64 = base64.b64encode(image_data).decode('utf-8')
            
            # Send via SocketIO
            if self.socketio:
                self.socketio.emit('video_frame', {
                    "frame": image_b64,
                    "format": "image/png",
                    "timestamp": time.time()
                }, broadcast=True)
        
        except Exception as e:
            print(f"Error sending video frame: {e}")
    
    def toggle_video(self, enabled: bool):
        """Toggle video on/off during call"""
        if self.active_video_call:
            self.active_video_call["video_enabled"] = enabled
            
            if self.socketio:
                self.socketio.emit('video_toggled', {
                    "enabled": enabled
                }, broadcast=True)
    
    def _store_video_call_log(self, call_info: Dict):
        """Store video call log in database"""
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
                    "video_call",
                    f"Video call ({call_info['type']})",
                    f'{{"call_id": "{call_info["call_id"]}", "duration": {call_info.get("duration", 0)}, '
                    f'"started_at": "{call_info["started_at"]}", "ended_at": "{call_info.get("ended_at", "")}"}}'
                ))
                conn.commit()
                
                print(f"✅ Video call log stored in database")
        
        except Exception as e:
            print(f"Error storing video call log: {e}")
    
    def get_video_call_status(self) -> Dict:
        """Get current video call status"""
        if self.active_video_call:
            # Get voice call status
            voice_status = self.voice_handler.get_call_status()
            
            return {
                **self.active_video_call,
                "is_active": self.video_active,
                "voice_status": voice_status
            }
        else:
            return {
                "status": "no_active_call"
            }
    
    def get_video_call_history(
        self,
        character_id: str = None,
        limit: int = 10
    ) -> list:
        """Get video call history from database"""
        if not self.db:
            return []
        
        query = """
            SELECT id, character_id, content, metadata, timestamp
            FROM interactions
            WHERE type = 'video_call'
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
            print(f"Error fetching video call history: {e}")
        
        return history


# Quick test
if __name__ == "__main__":
    from content.simulation.database.db import Database
    
    db = Database()
    handler = VideoCallHandler(db=db)
    
    # Start test video call
    call_id = handler.start_video_call(
        character_id="test_char_123",
        character_name="Emma",
        character_description="long brown hair, green eyes, 25 years old",
        call_type="incoming"
    )
    
    print(f"\nVideo Call ID: {call_id}")
    print("Simulating video call...")
    
    # Simulate answering
    time.sleep(1)
    handler.answer_video_call(call_id)
    
    # Simulate call duration
    time.sleep(10)
    
    # End call
    call_info = handler.end_video_call(call_id)
    print(f"\nVideo call ended:")
    print(f"  Duration: {call_info.get('duration', 0):.1f}s")
