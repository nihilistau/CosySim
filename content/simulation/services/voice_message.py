"""
Voice Message Service
Handles voice message generation and playback (async audio messages)
"""

import os
import uuid
import wave
import struct
import logging
from datetime import datetime
from pathlib import Path
from typing import Optional, Dict, List
import sys

from engine.paths import CONTENT_DIR as project_root
sys.path.insert(0, str(project_root))

logger = logging.getLogger(__name__)

from content.simulation.database.db import Database
from engine.assets import AssetManager, AudioAsset


class VoiceMessageGenerator:
    """
    Generate voice messages using CosyVoice TTS
    Pre-generated audio messages (like WhatsApp voice notes)
    """
    
    def __init__(self, cosyvoice_model=None, db: Database = None):
        self.cosyvoice = cosyvoice_model
        self.db = db
        self.asset_manager = AssetManager()
        self.voice_dir = Path(__file__).parent.parent / "media" / "voice"
        self.voice_dir.mkdir(parents=True, exist_ok=True)
        
        # Voice settings from centralised MediaConfig
        try:
            from engine.media.media_config import get_media_config
            spec = get_media_config().audio_spec("voice_message")
            self.sample_rate = spec.get("sample_rate", 22050)
        except Exception as e:
            logger.debug("[VoiceMessage] MediaConfig unavailable, using defaults (operation=init): %s", e)
            self.sample_rate = 22050
        self.prompt_wav = None  # Character's voice sample
        self.prompt_text = "Hello, this is my voice."

        # Qwen3-TTS server URL (fallback when CosyVoice unavailable)
        try:
            from engine.config import get_config
            self._tts_url = get_config().get("tts.server_url", "")
            if not self._tts_url:
                from engine.port_registry import get_service_url
                self._tts_url = get_service_url("tts")
        except Exception as e:
            logger.debug("[VoiceMessage] Config unavailable, using default TTS URL (operation=init): %s", e)
            from engine.port_registry import get_service_url
            self._tts_url = get_service_url("tts")
    
    def set_character_voice(self, prompt_wav_path: str, prompt_text: str = None):
        """
        Set the character's voice from a sample
        
        Args:
            prompt_wav_path: Path to voice sample WAV file
            prompt_text: Text of the voice sample
        """
        if os.path.exists(prompt_wav_path):
            self.prompt_wav = prompt_wav_path
            if prompt_text:
                self.prompt_text = prompt_text
            print(f"✅ Character voice set from {prompt_wav_path}")
        else:
            print(f"⚠️ Voice sample not found: {prompt_wav_path}")
    
    def generate_voice_message(
        self,
        character_id: str,
        character_name: str,
        text: str,
        emotion: str = "neutral",
        chain_id: Optional[str] = None,
        scene_id: str = "unknown",
    ) -> Optional[Dict]:
        """
        Generate a voice message from text
        
        Args:
            character_id: ID of character
            character_name: Name of character
            text: Text to synthesize
            emotion: Emotion/tone (neutral, happy, sad, flirty, etc.)
        
        Returns:
            Dict with filepath, duration, metadata
        """
        if not self.cosyvoice:
            # Try Qwen3-TTS server before falling back to placeholder
            result = self._try_qwen3_tts(character_id, character_name, text, emotion,
                                          chain_id, scene_id)
            if result:
                return result
            print("⚠️ CosyVoice and Qwen3-TTS unavailable, generating placeholder")
            return self._generate_placeholder(character_name, text)
        
        try:
            # Generate audio with CosyVoice
            # NOTE: This uses zero-shot voice cloning if prompt_wav is set
            if self.prompt_wav:
                audio_generator = self.cosyvoice.inference_zero_shot(
                    tts_text=text,
                    prompt_text=self.prompt_text,
                    prompt_wav=self.prompt_wav,
                    stream=False
                )
            else:
                # Fallback to basic inference
                audio_generator = self.cosyvoice.inference_sft(
                    tts_text=text,
                    stream=False
                )
            
            # Collect audio chunks
            audio_chunks = []
            for chunk in audio_generator:
                if 'tts_speech' in chunk:
                    audio_chunks.append(chunk['tts_speech'])
            
            if not audio_chunks:
                print("❌ No audio generated")
                return None
            
            # Concatenate audio
            import torch
            audio_data = torch.cat(audio_chunks, dim=-1)
            
            # Save to file
            filename = f"{character_name}_voice_{uuid.uuid4().hex[:8]}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.wav"
            filepath = self.voice_dir / filename
            
            # Convert to numpy and save as WAV
            audio_np = audio_data.cpu().numpy()
            self._save_wav(str(filepath), audio_np, self.sample_rate)
            
            # Calculate duration
            duration = len(audio_np) / self.sample_rate
            
            # Create AudioAsset
            audio_asset = AudioAsset.create(
                filepath=str(filepath),
                duration=duration,
                sample_rate=self.sample_rate,
                channels=1,
                tags=[character_id, character_name, emotion, "voice_message"]
            )
            
            # Save to asset manager
            self.asset_manager.save(audio_asset)
            
            # Store in database if available (legacy support)
            if self.db:
                self._store_voice_message(
                    character_id=character_id,
                    filepath=str(filepath),
                    text=text,
                    duration=duration,
                    emotion=emotion
                )
            
            result = {
                "asset_id": audio_asset.id,
                "filepath": str(filepath),
                "filename": filename,
                "duration": duration,
                "text": text,
                "emotion": emotion,
                "sample_rate": self.sample_rate,
                "timestamp": datetime.now().isoformat()
            }

            # Log to EventChain
            try:
                from content.simulation.database.events import EventChain
                ec = EventChain()
                if chain_id:
                    ec.log(
                        'media_generated', actor='voice_generator',
                        payload={'type': 'voice', 'path': str(filepath),
                                 'character': character_name, 'emotion': emotion,
                                 'duration': duration, 'text': text[:100]},
                        summary=f'Voice generated: {character_name} ({emotion}, {duration:.1f}s)',
                        chain_id=chain_id, scene_id=scene_id,
                        character_id=character_id,
                    )
            except Exception as e:
                logger.debug("[VoiceMessage] EventChain log failed (operation=generate): %s", e)

            # MCP: publish to ActivityBus
            try:
                from engine.services.activity_bus import get_activity_bus
                get_activity_bus().publish(
                    activity_type="voice_generated",
                    description=f"{character_name}: {duration:.1f}s voice ({emotion})",
                    agent_id=character_id,
                    scene=scene_id,
                    data={"filename": filename, "duration": duration, "emotion": emotion, "chain_id": chain_id},
                )
            except Exception as e:
                logger.debug("[VoiceMessage] ActivityBus publish failed (operation=generate): %s", e)

            return result

        except Exception as e:
            print(f"Error generating voice message: {e}")
            return None
    
    def _save_wav(self, filepath: str, audio_data, sample_rate: int):
        """Save audio data as WAV file"""
        import numpy as np
        
        # Normalize audio
        audio_data = np.clip(audio_data, -1.0, 1.0)
        audio_int16 = (audio_data * 32767).astype(np.int16)
        
        # Write WAV file
        with wave.open(filepath, 'wb') as wav_file:
            wav_file.setnchannels(1)  # Mono
            wav_file.setsampwidth(2)  # 16-bit
            wav_file.setframerate(sample_rate)
            wav_file.writeframes(audio_int16.tobytes())
    
    def _generate_placeholder(self, character_name: str, text: str) -> Dict:
        """Generate a placeholder voice message (for testing without CosyVoice)"""
        filename = f"{character_name}_placeholder_{uuid.uuid4().hex[:8]}.wav"
        filepath = self.voice_dir / filename
        
        # Generate 2 seconds of silence as placeholder
        sample_rate = 22050
        duration = 2.0
        samples = int(duration * sample_rate)
        
        with wave.open(str(filepath), 'wb') as wav_file:
            wav_file.setnchannels(1)
            wav_file.setsampwidth(2)
            wav_file.setframerate(sample_rate)
            # Write silence
            silence = struct.pack('h' * samples, *[0] * samples)
            wav_file.writeframes(silence)
        
        return {
            "filepath": str(filepath),
            "filename": filename,
            "duration": duration,
            "text": text,
            "placeholder": True,
            "sample_rate": sample_rate,
            "timestamp": datetime.now().isoformat()
        }

    def _try_qwen3_tts(
        self, character_id: str, character_name: str, text: str,
        emotion: str, chain_id: Optional[str], scene_id: str,
    ) -> Optional[Dict]:
        """Try generating via the Qwen3-TTS FastAPI server."""
        try:
            import requests
            resp = requests.post(
                f"{self._tts_url}/generate",
                json={
                    "text": text,
                    "voice_design": f"A warm {emotion} voice for {character_name}",
                    "character_id": character_id,
                    "max_duration": min(max(len(text) * 0.1, 10), 300),
                },
                timeout=120,
            )
            if resp.status_code != 200:
                return None
            data = resp.json()
            filepath = data.get("filepath") or data.get("path")
            if not filepath:
                return None
            resolved = Path(filepath).resolve()
            if ".." in str(filepath) or not resolved.exists():
                return None
            info = self.get_voice_message_info(filepath)
            result = {
                "filepath": filepath,
                "filename": Path(filepath).name,
                "duration": info.get("duration", 0),
                "text": text,
                "emotion": emotion,
                "sample_rate": info.get("sample_rate", self.sample_rate),
                "timestamp": datetime.now().isoformat(),
                "source": "qwen3_tts",
            }
            if self.db:
                self._store_voice_message(character_id, filepath, text,
                                          result["duration"], emotion)
            # Log to EventChain
            try:
                from content.simulation.database.events import EventChain
                ec = EventChain()
                if chain_id:
                    ec.log(
                        'media_generated', actor='qwen3_tts',
                        payload={'type': 'voice', 'path': filepath,
                                 'character': character_name, 'emotion': emotion},
                        summary=f'TTS voice: {character_name} ({emotion})',
                        chain_id=chain_id, scene_id=scene_id,
                        character_id=character_id,
                    )
            except Exception as e:
                logger.debug("[VoiceMessage] EventChain log failed (operation=qwen3_tts): %s", e)
            return result
        except Exception as e:
            logger.debug("Qwen3-TTS server unavailable: %s", e)
            return None
    
    def _store_voice_message(
        self,
        character_id: str,
        filepath: str,
        text: str,
        duration: float,
        emotion: str
    ):
        """Store voice message in database"""
        if not self.db:
            return
        
        try:
            with self.db.get_connection() as conn:
                cursor = conn.cursor()
                import json as _json
                cursor.execute("""
                    INSERT INTO media (id, character_id, type, filepath, metadata, created_at)
                    VALUES (?, ?, ?, ?, ?, ?)
                """, (
                    str(uuid.uuid4()),
                    character_id,
                    "voice",
                    filepath,
                    _json.dumps({"text": text, "duration": duration, "emotion": emotion}),
                    datetime.now().isoformat()
                ))
        except Exception as e:
            print(f"Error storing voice message: {e}")
    
    def get_voice_message_info(self, filepath: str) -> Dict:
        """Get information about a voice message file"""
        path = Path(filepath)
        
        if not path.exists():
            return {"error": "File not found"}
        
        try:
            with wave.open(str(path), 'rb') as wav_file:
                channels = wav_file.getnchannels()
                sample_width = wav_file.getsampwidth()
                sample_rate = wav_file.getframerate()
                n_frames = wav_file.getnframes()
                duration = n_frames / sample_rate
            
            stat = path.stat()
            
            return {
                "filename": path.name,
                "duration": duration,
                "sample_rate": sample_rate,
                "channels": channels,
                "size": stat.st_size,
                "created": datetime.fromtimestamp(stat.st_ctime).isoformat(),
                "exists": True
            }
        except Exception as e:
            return {"error": str(e)}
    
    def generate_random_voice_message(self, character_id: str, character_name: str) -> Optional[Dict]:
        """Generate a random voice message from character"""
        messages = [
            "Hey! Just wanted to say hi!",
            "Missing you right now...",
            "Call me when you get this!",
            "Thinking about you!",
            "Hope you're having a good day!",
            "Can't wait to talk to you!",
            "Just heard something funny and thought of you!",
            "Love you! Talk soon!"
        ]
        
        import random
        text = random.choice(messages)
        
        return self.generate_voice_message(
            character_id=character_id,
            character_name=character_name,
            text=text
        )


class VoiceMailBox:
    """Manage voicemail inbox"""
    
    def __init__(self, db: Database):
        self.db = db
    
    def add_voicemail(
        self,
        character_id: str,
        voice_filepath: str,
        text: str = None,
        duration: float = 0.0
    ) -> str:
        """Add voicemail to inbox"""
        import uuid as _uuid
        from datetime import datetime as _dt
        with self.db.get_connection() as conn:
            cursor = conn.cursor()
            import json as _json_mod
            interaction_id = str(_uuid.uuid4())
            cursor.execute("""
                INSERT INTO interactions (id, character_id, type, content, metadata, timestamp)
                VALUES (?, ?, ?, ?, ?, ?)
            """, (
                interaction_id,
                character_id,
                "voicemail",
                text or "Voice message",
                _json_mod.dumps({"filepath": voice_filepath, "duration": duration, "listened": False}),
                _dt.now().isoformat()
            ))
            return interaction_id
    
    def get_voicemails(self, character_id: str, unheard_only: bool = False) -> List[Dict]:
        """Get voicemails for character"""
        query = """
            SELECT id, content, metadata, timestamp
            FROM interactions
            WHERE character_id = ? AND type = 'voicemail'
        """
        
        if unheard_only:
            query += " AND json_extract(metadata, '$.listened') = 'false'"
        
        query += " ORDER BY timestamp DESC"
        
        voicemails = []
        with self.db.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(query, (character_id,))
            
            for row in cursor.fetchall():
                voicemails.append({
                    "id": row[0],
                    "text": row[1],
                    "metadata": row[2],
                    "timestamp": row[3]
                })
        
        return voicemails
    
    def mark_as_listened(self, voicemail_id: str):
        """Mark voicemail as listened"""
        # This would update the metadata JSON to set listened: true
        # SQLite JSON functions can be used for this
        pass


# Quick test
if __name__ == "__main__":
    from content.simulation.database.db import Database
    
    db = Database()
    
    # Test voice message generation
    vm_gen = VoiceMessageGenerator(db=db)
    
    print("Generating test voice message...")
    result = vm_gen.generate_voice_message(
        character_id="test_char_123",
        character_name="Emma",
        text="Hey! Just wanted to say hi and see how you're doing!"
    )
    
    if result:
        print(f"✅ Generated: {result['filename']}")
        print(f"   Duration: {result['duration']:.2f}s")
        print(f"   Text: {result['text']}")
    else:
        print("❌ Generation failed")
