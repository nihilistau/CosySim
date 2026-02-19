"""
Video Message Service
Handles video message generation (async video clips with character)
"""

import os
import uuid
import subprocess
from datetime import datetime
from pathlib import Path
from typing import Optional, Dict, List
import sys

project_root = Path(__file__).parent.parent.parent
sys.path.insert(0, str(project_root))

from content.simulation.database.db import Database
from content.simulation.services.media_generator import MediaGenerator
from content.simulation.services.voice_message import VoiceMessageGenerator
from engine.assets import AssetManager, VideoAsset


class VideoMessageGenerator:
    """
    Generate video messages - short video clips with character talking
    Like Instagram/TikTok video messages
    """
    
    def __init__(
        self,
        media_gen: MediaGenerator = None,
        voice_gen: VoiceMessageGenerator = None,
        db: Database = None
    ):
        self.media_gen = media_gen or MediaGenerator()
        self.voice_gen = voice_gen or VoiceMessageGenerator(db=db)
        self.db = db
        self.asset_manager = AssetManager()
        
        self.video_dir = Path(__file__).parent.parent / "media" / "video"
        self.video_dir.mkdir(parents=True, exist_ok=True)
        
        # Video settings
        self.fps = 30
        self.resolution = (512, 512)  # Square video like social media
    
    def generate_video_message(
        self,
        character_id: str,
        character_name: str,
        character_description: str,
        text: str,
        mood: str = "happy",
        duration: float = 5.0
    ) -> Optional[Dict]:
        """
        Generate a video message with character speaking
        
        Args:
            character_id: Character ID
            character_name: Character name
            character_description: Physical description for image gen
            text: What character says
            mood: Mood/emotion (happy, flirty, sad, excited, etc.)
            duration: Target duration in seconds
        
        Returns:
            Dict with filepath, duration, metadata
        """
        try:
            print(f"🎬 Generating video message from {character_name}...")
            
            # Step 1: Generate character face image
            print("  1️⃣ Generating face image...")
            face_image = self._generate_face_image(
                character_name, character_description, mood
            )
            
            if not face_image:
                print("  ❌ Failed to generate face image")
                return None
            
            # Step 2: Generate voice audio
            print("  2️⃣ Generating voice audio...")
            audio_data = self.voice_gen.generate_voice_message(
                character_id, character_name, text, emotion=mood
            )
            
            if not audio_data:
                print("  ❌ Failed to generate voice")
                return None
            
            # Step 3: Create video with face + lip sync animation
            print("  3️⃣ Creating video with lip sync...")
            video_path = self._create_video_with_lipsync(
                face_image=face_image,
                audio_path=audio_data["filepath"],
                character_name=character_name,
                duration=audio_data["duration"]
            )
            
            if not video_path:
                print("  ❌ Failed to create video")
                return None
            
            # Get video info
            import cv2
            cap = cv2.VideoCapture(video_path)
            width = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
            height = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
            fps = int(cap.get(cv2.CAP_PROP_FPS))
            cap.release()
            
            # Create VideoAsset
            video_asset = VideoAsset.create(
                filepath=video_path,
                duration=audio_data["duration"],
                width=width,
                height=height,
                fps=fps,
                codec="h264",
                tags=[character_id, character_name, mood, "video_message"]
            )
            
            # Save to asset manager
            self.asset_manager.save(video_asset)
            
            # Store in database (legacy support)
            if self.db:
                self._store_video_message(
                    character_id=character_id,
                    filepath=video_path,
                    text=text,
                    duration=audio_data["duration"],
                    mood=mood
                )
            
            print(f"  ✅ Video message created: {Path(video_path).name}")
            
            return {
                "asset_id": video_asset.id,
                "filepath": video_path,
                "filename": Path(video_path).name,
                "duration": audio_data["duration"],
                "text": text,
                "mood": mood,
                "resolution": (width, height),
                "fps": fps,
                "timestamp": datetime.now().isoformat()
            }
        
        except Exception as e:
            print(f"❌ Error generating video message: {e}")
            return None
    
    def _generate_face_image(
        self,
        character_name: str,
        character_description: str,
        mood: str
    ) -> Optional[str]:
        """Generate character face image using ComfyUI"""
        try:
            # Generate face with appropriate expression
            face_path = self.media_gen.generate_selfie(
                character_name=character_name,
                character_description=character_description,
                mood=mood,
                setting="video_call",  # Close-up, well-lit
                style="realistic"
            )
            
            return face_path
        
        except Exception as e:
            print(f"Error generating face: {e}")
            return None
    
    def _create_video_with_lipsync(
        self,
        face_image: str,
        audio_path: str,
        character_name: str,
        duration: float
    ) -> Optional[str]:
        """
        Create video from face image + audio with basic lip sync
        Uses FFmpeg for video creation with simple talking animation
        """
        try:
            # Output video path
            filename = f"{character_name}_video_{uuid.uuid4().hex[:8]}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.mp4"
            output_path = self.video_dir / filename
            
            # Validate paths to prevent command injection
            face_path = Path(face_image).resolve()
            audio_file = Path(audio_path).resolve()
            
            # Ensure face image is in a safe directory
            if not str(face_path).startswith(str(self.faces_dir.resolve())):
                raise ValueError("Face image path is outside allowed directory")
            
            # Ensure audio is in a safe directory
            if not str(audio_file).startswith(str(self.audio_dir.resolve())):
                raise ValueError("Audio file path is outside allowed directory")
            
            # Verify files exist
            if not face_path.exists():
                raise FileNotFoundError(f"Face image not found: {face_path}")
            if not audio_file.exists():
                raise FileNotFoundError(f"Audio file not found: {audio_file}")
            
            # For now, create simple video: static image + audio
            # TODO: Add real lip sync with face animation library
            
            # Basic approach: Create video from image + audio using FFmpeg
            cmd = [
                'ffmpeg',
                '-loop', '1',  # Loop the image
                '-i', str(face_path),  # Input image (validated)
                '-i', str(audio_file),  # Input audio (validated)
                '-c:v', 'libx264',  # Video codec
                '-tune', 'stillimage',  # Optimize for still image
                '-c:a', 'aac',  # Audio codec
                '-b:a', '192k',  # Audio bitrate
                '-pix_fmt', 'yuv420p',  # Pixel format for compatibility
                '-shortest',  # End when audio ends
                '-y',  # Overwrite output
                str(output_path)
            ]
            
            # Run FFmpeg
            result = subprocess.run(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                timeout=60
            )
            
            if result.returncode == 0 and output_path.exists():
                return str(output_path)
            else:
                print(f"FFmpeg error: {result.stderr.decode()}")
                return None
        
        except subprocess.TimeoutExpired:
            print("FFmpeg timeout")
            return None
        except FileNotFoundError:
            print("FFmpeg not found - install FFmpeg to generate videos")
            return None
        except Exception as e:
            print(f"Error creating video: {e}")
            return None
    
    def _store_video_message(
        self,
        character_id: str,
        filepath: str,
        text: str,
        duration: float,
        mood: str
    ):
        """Store video message in database"""
        if not self.db:
            return
        
        try:
            import json
            with self.db.get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute("""
                    INSERT INTO media (character_id, type, filepath, metadata)
                    VALUES (?, ?, ?, ?)
                """, (
                    character_id,
                    "video_message",
                    filepath,
                    json.dumps({"text": text, "duration": duration, "mood": mood})
                ))
                conn.commit()
        except Exception as e:
            print(f"Error storing video message: {e}")
    
    def generate_random_video_message(
        self,
        character_id: str,
        character_name: str,
        character_description: str
    ) -> Optional[Dict]:
        """Generate a random video message from character"""
        import random
        
        messages = [
            ("Hey! Just wanted to see your face! 😊", "happy"),
            ("Missing you so much right now... 💕", "loving"),
            ("Look at me! Don't I look cute today? 😘", "flirty"),
            ("Thinking about you! Call me later! 📞", "excited"),
            ("Hope you're having a good day! ❤️", "happy"),
            ("Can't stop thinking about you... 😍", "loving"),
            ("Guess what I'm doing right now? 😏", "playful"),
            ("Wish you were here with me... 💭", "sad")
        ]
        
        text, mood = random.choice(messages)
        
        return self.generate_video_message(
            character_id=character_id,
            character_name=character_name,
            character_description=character_description,
            text=text,
            mood=mood
        )
    
    def get_video_message_info(self, filepath: str) -> Dict:
        """Get information about a video message file"""
        path = Path(filepath)
        
        if not path.exists():
            return {"error": "File not found"}
        
        try:
            # Use ffprobe to get video info
            cmd = [
                'ffprobe',
                '-v', 'error',
                '-show_entries', 'format=duration,size',
                '-show_entries', 'stream=width,height,codec_name',
                '-of', 'json',
                str(path)
            ]
            
            result = subprocess.run(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                timeout=10
            )
            
            if result.returncode == 0:
                import json
                info = json.loads(result.stdout.decode())
                
                format_info = info.get('format', {})
                stream_info = info.get('streams', [{}])[0]
                
                return {
                    "filename": path.name,
                    "duration": float(format_info.get('duration', 0)),
                    "size": int(format_info.get('size', 0)),
                    "width": stream_info.get('width', 0),
                    "height": stream_info.get('height', 0),
                    "codec": stream_info.get('codec_name', 'unknown'),
                    "exists": True
                }
            
        except Exception as e:
            print(f"Error getting video info: {e}")
        
        # Fallback: basic file info
        stat = path.stat()
        return {
            "filename": path.name,
            "size": stat.st_size,
            "created": datetime.fromtimestamp(stat.st_ctime).isoformat(),
            "exists": True
        }


class VideoMailBox:
    """Manage video message inbox"""
    
    def __init__(self, db: Database):
        self.db = db
    
    def add_video_message(
        self,
        character_id: str,
        video_filepath: str,
        text: str = None,
        duration: float = 0.0
    ) -> str:
        """Add video message to inbox"""
        with self.db.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                INSERT INTO interactions (character_id, type, content, metadata)
                VALUES (?, ?, ?, ?)
            """, (
                character_id,
                "video_message",
                text or "Video message",
                f'{{"filepath": "{video_filepath}", "duration": {duration}, "watched": false}}'
            ))
            conn.commit()
            return str(cursor.lastrowid)
    
    def get_video_messages(
        self,
        character_id: str,
        unwatched_only: bool = False
    ) -> List[Dict]:
        """Get video messages for character"""
        query = """
            SELECT id, content, metadata, timestamp
            FROM interactions
            WHERE character_id = ? AND type = 'video_message'
        """
        
        if unwatched_only:
            query += " AND json_extract(metadata, '$.watched') = 'false'"
        
        query += " ORDER BY timestamp DESC"
        
        messages = []
        with self.db.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(query, (character_id,))
            
            for row in cursor.fetchall():
                messages.append({
                    "id": row[0],
                    "text": row[1],
                    "metadata": row[2],
                    "timestamp": row[3]
                })
        
        return messages
    
    def mark_as_watched(self, message_id: str):
        """Mark video message as watched"""
        # Update metadata JSON to set watched: true
        pass


# Quick test
if __name__ == "__main__":
    from content.simulation.database.db import Database
    
    db = Database()
    
    # Test video message generation
    video_gen = VideoMessageGenerator(db=db)
    
    print("Generating test video message...")
    result = video_gen.generate_video_message(
        character_id="test_char_123",
        character_name="Emma",
        character_description="long brown hair, green eyes, 25 years old",
        text="Hey! Just wanted to say hi and see how you're doing!",
        mood="happy"
    )
    
    if result:
        print(f"✅ Generated: {result['filename']}")
        print(f"   Duration: {result['duration']:.2f}s")
        print(f"   Text: {result['text']}")
    else:
        print("❌ Generation failed")
