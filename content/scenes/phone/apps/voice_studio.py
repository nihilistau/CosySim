"""
Voice Studio — TTS voice creation, management, and batch generation app.

Provides:
- Voice design builder (custom descriptions + presets)
- Zero-shot voice cloning (upload WAV reference)
- Save / track / manage voices in DB
- TTS generation with voice selection
- Emotion/tone helper insertion
- Batch processing from scripts
- Recording library management
"""
from __future__ import annotations

import json
import logging
import uuid
import wave
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional
from engine.paths import VOICE_DIR

logger = logging.getLogger(__name__)

# ── Emotion/Tone helpers for the cheat sheet ─────────────────────────────

EMOTION_TAGS = {
    "emotions": {
        "happy": "Speak with warmth and a smile in the voice.",
        "sad": "A melancholic tone, slow pace, slight breathiness.",
        "angry": "Sharp, clipped delivery with intensity.",
        "excited": "High energy, faster pace, rising intonation.",
        "scared": "Trembling, whispery, breathless with urgency.",
        "flirty": "Playful, warm, with a teasing lilt.",
        "seductive": "Low, breathy, intimate, slow and deliberate.",
        "confident": "Strong, measured, authoritative delivery.",
        "shy": "Quiet, hesitant, with soft pauses between phrases.",
        "sarcastic": "Dry, flat delivery with sharp emphasis on key words.",
        "mysterious": "Hushed, deliberate, with dramatic pauses.",
        "loving": "Gentle, warm, tender with soft cadence.",
    },
    "tones": {
        "whisper": "Speak in a soft whisper, close-mic intimacy.",
        "shout": "Loud, projected voice with force.",
        "breathy": "Airy, light voice with audible breath.",
        "raspy": "Gravelly, textured voice with slight roughness.",
        "vocal_fry": "Low creaky register at the end of phrases.",
        "sing_song": "Musical, lilting cadence with pitch variation.",
        "monotone": "Flat, even delivery with minimal inflection.",
        "dramatic": "Theatrical, with exaggerated emotion and pauses.",
    },
    "styles": {
        "narrator": "Professional broadcast quality, clear enunciation.",
        "conversational": "Natural, casual, like talking to a friend.",
        "podcast": "Warm, engaging, medium pace for clarity.",
        "asmr": "Ultra-soft, close-mic, gentle and soothing.",
        "news_anchor": "Crisp, authoritative, measured delivery.",
        "storyteller": "Expressive, varied pace, character-driven.",
    },
}

# ── Premade voice collection ─────────────────────────────────────────────

PREMADE_VOICES = {
    "luna_flirty": {
        "name": "Luna (Flirty)",
        "description": (
            "A youthful female voice, mid-range pitch, characterized by a warm, "
            "playful cadence. Includes slight vocal fry at the end of sentences "
            "and a breathy, intimate quality. Speaks with a subtle smirk."
        ),
        "model_size": "1.7b",
        "tags": ["female", "young", "flirty", "playful"],
    },
    "maya_whisper": {
        "name": "Maya (Whisper)",
        "description": (
            "A soft, intimate female whisper-voice. Low volume, breathy, "
            "with close-mic warmth. Speaks slowly and deliberately, as if "
            "sharing a secret. Gentle sighs between phrases."
        ),
        "model_size": "1.7b",
        "tags": ["female", "whisper", "intimate"],
    },
    "commander": {
        "name": "Commander (Authority)",
        "description": (
            "A steady, mature male voice with a deep baritone resonance. "
            "Includes a slight gravelly rasp from years of command. "
            "The tone is authoritative, measured, and calm, with a natural "
            "weight that demands attention."
        ),
        "model_size": "1.7b",
        "tags": ["male", "mature", "authority"],
    },
    "ai_mother": {
        "name": "AI Mother (Clinical)",
        "description": (
            "A high-fidelity female voice, perfectly clear and articulate. "
            "The delivery is rhythmic and devoid of emotional inflection. "
            "Includes pristine clarity and a clinical, professional reverberation."
        ),
        "model_size": "0.6b",
        "tags": ["female", "ai", "clinical"],
    },
    "hacker_girl": {
        "name": "Hacker Girl (Cyber)",
        "description": (
            "A youthful female voice, mid-range pitch, characterized by "
            "fast-paced speech and a casual, clever cadence. Includes slight "
            "vocal fry at the end of sentences and a sharp, cynical edge."
        ),
        "model_size": "1.7b",
        "tags": ["female", "young", "fast", "cynical"],
    },
    "smooth_narrator": {
        "name": "Smooth Narrator",
        "description": (
            "A professional male narrator voice with warm baritone quality. "
            "Clear enunciation, measured pace, engaging and authoritative. "
            "Perfect for storytelling and documentary narration."
        ),
        "model_size": "1.7b",
        "tags": ["male", "narrator", "professional"],
    },
    "seductive_whisper": {
        "name": "Seductive Whisper",
        "description": (
            "A low, breathy female voice with intimate close-mic warmth. "
            "Slow, deliberate delivery with audible breath and gentle sighs. "
            "Sensual and inviting, like a late-night confession."
        ),
        "model_size": "1.7b",
        "tags": ["female", "seductive", "whisper", "intimate"],
    },
    "energetic_youth": {
        "name": "Energetic Youth",
        "description": (
            "A bright, energetic voice with fast-paced speech and enthusiasm. "
            "High pitch variation, casual cadence, sharp pronunciation. "
            "Sounds like an excited gamer or streamer."
        ),
        "model_size": "1.7b",
        "tags": ["young", "energetic", "bright"],
    },
}


class VoiceStudio:
    """
    Voice Studio app backend — create, manage, and generate voices.

    Integrates with VoiceDesigner for persistence and Qwen3-TTS for generation.
    """

    def __init__(self, db, voice_dir: Optional[str] = None, tts_url: str = "http://localhost:8600"):
        self.db = db
        self.tts_url = tts_url.rstrip("/")
        self.voice_dir = Path(voice_dir) if voice_dir else VOICE_DIR
        self.voice_dir.mkdir(parents=True, exist_ok=True)
        self.recordings_dir = self.voice_dir / "recordings"
        self.recordings_dir.mkdir(exist_ok=True)
        self.references_dir = self.voice_dir / "references"
        self.references_dir.mkdir(exist_ok=True)

        # Ensure voice_designs table exists
        self._init_db()

    # ── Database ─────────────────────────────────────────────────────

    def _init_db(self):
        """Create voice_designs table if not exists."""
        try:
            with self.db.get_connection() as conn:
                conn.execute("""
                    CREATE TABLE IF NOT EXISTS voice_designs (
                        id TEXT PRIMARY KEY,
                        name TEXT NOT NULL,
                        description TEXT NOT NULL,
                        model_size TEXT DEFAULT '1.7b',
                        reference_audio TEXT,
                        tags TEXT DEFAULT '[]',
                        character_id TEXT,
                        is_premade INTEGER DEFAULT 0,
                        created_at TEXT NOT NULL,
                        updated_at TEXT NOT NULL
                    )
                """)
                conn.execute("""
                    CREATE TABLE IF NOT EXISTS voice_recordings (
                        id TEXT PRIMARY KEY,
                        voice_id TEXT,
                        name TEXT NOT NULL,
                        text TEXT NOT NULL,
                        filepath TEXT NOT NULL,
                        duration REAL DEFAULT 0,
                        sample_rate INTEGER DEFAULT 24000,
                        emotion TEXT,
                        batch_id TEXT,
                        metadata TEXT,
                        created_at TEXT NOT NULL
                    )
                """)
                conn.commit()
        except Exception as e:
            logger.error("Failed to init voice studio tables: %s", e)

    # ── Voice management ─────────────────────────────────────────────

    def create_voice(
        self,
        name: str,
        description: str,
        model_size: str = "1.7b",
        reference_audio: Optional[str] = None,
        tags: Optional[List[str]] = None,
        character_id: Optional[str] = None,
    ) -> Dict:
        """Create and save a custom voice design."""
        voice_id = str(uuid.uuid4())
        now = datetime.now().isoformat()
        tags = tags or []

        with self.db.get_connection() as conn:
            conn.execute("""
                INSERT INTO voice_designs (id, name, description, model_size,
                    reference_audio, tags, character_id, is_premade, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, 0, ?, ?)
            """, (voice_id, name, description, model_size,
                  reference_audio, json.dumps(tags), character_id, now, now))
            conn.commit()

        # Also register with VoiceDesigner if character_id given
        if character_id:
            try:
                from engine.tts.voice_designer import get_voice_designer, VoiceDesign
                get_voice_designer().cast(character_id, VoiceDesign(
                    description=description, model_size=model_size,
                    reference_audio=reference_audio, tags=tags,
                ))
            except Exception:
                pass

        return {
            "id": voice_id, "name": name, "description": description,
            "model_size": model_size, "reference_audio": reference_audio,
            "tags": tags, "character_id": character_id, "created_at": now,
        }

    def list_voices(self, include_premade: bool = True) -> List[Dict]:
        """List all saved voice designs."""
        voices = []
        with self.db.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                SELECT id, name, description, model_size, reference_audio,
                       tags, character_id, is_premade, created_at
                FROM voice_designs ORDER BY created_at DESC
            """)
            for row in cursor.fetchall():
                voices.append({
                    "id": row[0], "name": row[1], "description": row[2],
                    "model_size": row[3], "reference_audio": row[4],
                    "tags": json.loads(row[5]) if row[5] else [],
                    "character_id": row[6], "is_premade": bool(row[7]),
                    "created_at": row[8],
                })

        # Optionally include premade voices (not in DB)
        if include_premade:
            db_ids = {v["name"] for v in voices}
            for key, preset in PREMADE_VOICES.items():
                if preset["name"] not in db_ids:
                    voices.append({
                        "id": f"premade_{key}", "name": preset["name"],
                        "description": preset["description"],
                        "model_size": preset["model_size"],
                        "reference_audio": None,
                        "tags": preset["tags"],
                        "character_id": None, "is_premade": True,
                        "created_at": None,
                    })
        return voices

    def get_voice(self, voice_id: str) -> Optional[Dict]:
        """Get a specific voice design."""
        # Check premade first
        if voice_id.startswith("premade_"):
            key = voice_id[8:]
            if key in PREMADE_VOICES:
                p = PREMADE_VOICES[key]
                return {"id": voice_id, "name": p["name"],
                        "description": p["description"],
                        "model_size": p["model_size"], "tags": p["tags"]}
            return None

        with self.db.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                SELECT id, name, description, model_size, reference_audio,
                       tags, character_id, created_at
                FROM voice_designs WHERE id = ?
            """, (voice_id,))
            row = cursor.fetchone()
            if row:
                return {
                    "id": row[0], "name": row[1], "description": row[2],
                    "model_size": row[3], "reference_audio": row[4],
                    "tags": json.loads(row[5]) if row[5] else [],
                    "character_id": row[6], "created_at": row[7],
                }
        return None

    def update_voice(self, voice_id: str, **kwargs) -> bool:
        """Update a voice design."""
        allowed = {"name", "description", "model_size", "reference_audio", "tags", "character_id"}
        updates = {k: v for k, v in kwargs.items() if k in allowed}
        if not updates:
            return False
        if "tags" in updates and isinstance(updates["tags"], list):
            updates["tags"] = json.dumps(updates["tags"])

        set_clause = ", ".join(f"{k} = ?" for k in updates)
        values = list(updates.values()) + [datetime.now().isoformat(), voice_id]

        with self.db.get_connection() as conn:
            conn.execute(
                f"UPDATE voice_designs SET {set_clause}, updated_at = ? WHERE id = ?",
                values,
            )
            conn.commit()
        return True

    def delete_voice(self, voice_id: str) -> bool:
        """Delete a voice design."""
        with self.db.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("DELETE FROM voice_designs WHERE id = ? AND is_premade = 0", (voice_id,))
            conn.commit()
            return cursor.rowcount > 0

    # ── Zero-shot cloning ────────────────────────────────────────────

    def save_reference_audio(self, filename: str, audio_data: bytes) -> str:
        """Save an uploaded WAV file as a voice reference for zero-shot cloning."""
        safe_name = filename.replace("..", "").replace("/", "_").replace("\\", "_")
        filepath = self.references_dir / safe_name
        filepath.write_bytes(audio_data)
        return str(filepath)

    # ── TTS Generation ───────────────────────────────────────────────

    def generate(
        self,
        text: str,
        voice_id: Optional[str] = None,
        voice_description: Optional[str] = None,
        name: Optional[str] = None,
        emotion: Optional[str] = None,
        model_size: str = "auto",
    ) -> Optional[Dict]:
        """
        Generate speech from text using a voice design.

        Args:
            text: Text to synthesize
            voice_id: ID of saved voice (takes priority)
            voice_description: Direct voice description (fallback)
            name: Name for the recording
            emotion: Emotion modifier to prepend
            model_size: Model override ("auto", "0.6b", "1.7b")
        """
        # Resolve voice description
        description = voice_description or "A clear, natural speaking voice."
        resolved_model = model_size

        if voice_id:
            voice = self.get_voice(voice_id)
            if voice:
                description = voice["description"]
                if resolved_model == "auto":
                    resolved_model = voice.get("model_size", "1.7b")

        # Inject emotion modifier
        if emotion and emotion in EMOTION_TAGS.get("emotions", {}):
            emotion_desc = EMOTION_TAGS["emotions"][emotion]
            description = f"{description} {emotion_desc}"

        # Call TTS server
        try:
            import requests
            resp = requests.post(
                f"{self.tts_url}/generate",
                json={
                    "text": text,
                    "voice_design": description,
                    "model_size": resolved_model if resolved_model != "auto" else "1.7b",
                    "max_duration": min(max(len(text) * 0.12, 10), 3600),
                    "sample_rate": 24000,
                },
                timeout=300,
            )
            if resp.status_code != 200:
                logger.error("TTS generation failed: %s", resp.text)
                return self._generate_placeholder(text, name)

            data = resp.json()
            filepath = data.get("filepath") or data.get("path")

            if not filepath or not Path(filepath).exists():
                return self._generate_placeholder(text, name)

            # Get audio info
            duration = self._get_wav_duration(filepath)

            # Save recording to DB
            rec_id = str(uuid.uuid4())
            rec_name = name or f"Recording {datetime.now().strftime('%H:%M:%S')}"
            now = datetime.now().isoformat()

            with self.db.get_connection() as conn:
                conn.execute("""
                    INSERT INTO voice_recordings
                        (id, voice_id, name, text, filepath, duration,
                         sample_rate, emotion, created_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """, (rec_id, voice_id, rec_name, text, filepath,
                      duration, 24000, emotion, now))
                conn.commit()

            return {
                "id": rec_id, "name": rec_name, "filepath": filepath,
                "filename": Path(filepath).name,
                "duration": duration, "text": text,
                "voice_id": voice_id, "emotion": emotion,
                "created_at": now,
            }
        except Exception as e:
            logger.error("TTS generation error: %s", e)
            return self._generate_placeholder(text, name)

    def _generate_placeholder(self, text: str, name: Optional[str] = None) -> Dict:
        """Generate a silent placeholder WAV when TTS is unavailable."""
        import struct
        rec_id = str(uuid.uuid4())
        filename = f"studio_{rec_id[:8]}.wav"
        filepath = self.recordings_dir / filename
        sample_rate = 24000
        duration = min(max(len(text) * 0.06, 1.0), 5.0)
        samples = int(duration * sample_rate)

        with wave.open(str(filepath), 'wb') as wf:
            wf.setnchannels(1)
            wf.setsampwidth(2)
            wf.setframerate(sample_rate)
            wf.writeframes(struct.pack('h' * samples, *[0] * samples))

        now = datetime.now().isoformat()
        rec_name = name or f"Placeholder {datetime.now().strftime('%H:%M:%S')}"

        with self.db.get_connection() as conn:
            conn.execute("""
                INSERT INTO voice_recordings
                    (id, voice_id, name, text, filepath, duration,
                     sample_rate, emotion, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (rec_id, None, rec_name, text, str(filepath),
                  duration, sample_rate, None, now))
            conn.commit()

        return {
            "id": rec_id, "name": rec_name, "filepath": str(filepath),
            "filename": filename, "duration": duration,
            "text": text, "placeholder": True, "created_at": now,
        }

    # ── Batch generation ─────────────────────────────────────────────

    def batch_generate(
        self,
        lines: List[Dict],
        voice_id: Optional[str] = None,
        voice_description: Optional[str] = None,
    ) -> Dict:
        """
        Batch generate multiple lines of speech.

        Args:
            lines: List of dicts with 'text', optional 'name', 'emotion', 'voice_id'
            voice_id: Default voice for all lines
            voice_description: Default description fallback
        """
        batch_id = str(uuid.uuid4())
        results = []
        errors = []

        for i, line in enumerate(lines):
            text = line.get("text", "").strip()
            if not text:
                continue

            line_voice = line.get("voice_id", voice_id)
            line_desc = line.get("voice_description", voice_description)
            line_name = line.get("name", f"Batch {i+1}")
            line_emotion = line.get("emotion")

            result = self.generate(
                text=text,
                voice_id=line_voice,
                voice_description=line_desc,
                name=line_name,
                emotion=line_emotion,
            )

            if result:
                result["batch_id"] = batch_id
                # Tag the recording with batch_id
                try:
                    with self.db.get_connection() as conn:
                        conn.execute(
                            "UPDATE voice_recordings SET batch_id = ? WHERE id = ?",
                            (batch_id, result["id"]),
                        )
                        conn.commit()
                except Exception:
                    pass
                results.append(result)
            else:
                errors.append({"line": i, "text": text[:50], "error": "Generation failed"})

        return {
            "batch_id": batch_id,
            "total": len(lines),
            "generated": len(results),
            "errors": len(errors),
            "results": results,
            "error_details": errors,
        }

    def parse_script(self, script_text: str) -> List[Dict]:
        """
        Parse a batch script into lines for generation.

        Supports formats:
            CHARACTER: "dialogue text"
            CHARACTER (emotion): "dialogue text"
            Plain text (one line = one generation)
        """
        import re
        lines = []
        for raw_line in script_text.strip().split("\n"):
            raw_line = raw_line.strip()
            if not raw_line or raw_line.startswith("#"):
                continue

            # Format: CHARACTER (emotion): "text" or CHARACTER: "text"
            match = re.match(
                r'^([A-Z_]+)\s*(?:\((\w+)\))?\s*:\s*["\']?(.+?)["\']?\s*$',
                raw_line,
            )
            if match:
                char_name = match.group(1)
                emotion = match.group(2)
                text = match.group(3)
                lines.append({
                    "name": char_name,
                    "text": text,
                    "emotion": emotion,
                    "character": char_name.lower(),
                })
            else:
                lines.append({"name": None, "text": raw_line})

        return lines

    # ── Recordings library ───────────────────────────────────────────

    def list_recordings(
        self,
        voice_id: Optional[str] = None,
        batch_id: Optional[str] = None,
        limit: int = 50,
    ) -> List[Dict]:
        """List generated recordings."""
        query = "SELECT id, voice_id, name, text, filepath, duration, emotion, batch_id, created_at FROM voice_recordings"
        conditions = []
        params = []

        if voice_id:
            conditions.append("voice_id = ?")
            params.append(voice_id)
        if batch_id:
            conditions.append("batch_id = ?")
            params.append(batch_id)

        if conditions:
            query += " WHERE " + " AND ".join(conditions)
        query += " ORDER BY created_at DESC LIMIT ?"
        params.append(limit)

        recordings = []
        with self.db.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(query, params)
            for row in cursor.fetchall():
                recordings.append({
                    "id": row[0], "voice_id": row[1], "name": row[2],
                    "text": row[3], "filepath": row[4], "duration": row[5],
                    "emotion": row[6], "batch_id": row[7], "created_at": row[8],
                    "filename": Path(row[4]).name if row[4] else None,
                })
        return recordings

    def delete_recording(self, recording_id: str) -> bool:
        """Delete a recording and its file."""
        with self.db.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT filepath FROM voice_recordings WHERE id = ?", (recording_id,))
            row = cursor.fetchone()
            if row and row[0]:
                try:
                    Path(row[0]).unlink(missing_ok=True)
                except Exception:
                    pass
            cursor.execute("DELETE FROM voice_recordings WHERE id = ?", (recording_id,))
            conn.commit()
            return cursor.rowcount > 0

    # ── Helpers ───────────────────────────────────────────────────────

    @staticmethod
    def get_emotion_tags() -> Dict:
        """Return all available emotion/tone/style tags for the cheat sheet."""
        return EMOTION_TAGS

    @staticmethod
    def get_premade_voices() -> Dict:
        """Return premade voice collection."""
        return PREMADE_VOICES

    @staticmethod
    def _get_wav_duration(filepath: str) -> float:
        """Get WAV file duration in seconds."""
        try:
            with wave.open(str(filepath), 'rb') as wf:
                frames = wf.getnframes()
                rate = wf.getframerate()
                return frames / rate if rate else 0.0
        except Exception:
            return 0.0
