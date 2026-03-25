# TTS — Voice Generation

> CosySim Documentation — v1.51.0 [2026-03-25]
>
> Qwen3-TTS server, voice design system, presets, and agent integration.

## Architecture

```
┌─────────────────┐    POST /generate    ┌──────────────┐    WAV files
│ CosySim Agents  │ ───────────────────▶ │  TTS Server  │ ──────────▶ media/voice/
│ (skills/MCP)    │ ◀─── job status ──── │  (FastAPI)   │
└─────────────────┘                      │  port :8600  │
                                         └──────────────┘
```

## Quick Start

```bash
# Start the TTS server
python launcher.py tts    # port 8600

# Generate a voice message
curl -X POST http://localhost:8600/generate \
  -H "Content-Type: application/json" \
  -d '{"text": "Hey, just wanted to say hi!", "voice_design": "A warm female voice"}'

# List voice presets
curl http://localhost:8600/voices

# Check status
curl http://localhost:8600/status
```

## Voice Design System

Each character gets a `VoiceDesign` that describes their vocal identity. Qwen3-TTS uses these natural-language descriptions to generate consistent, characterful speech.

### Voice Design Strings

```python
# Pitch, pace, rasp, warmth, vocal fry, reverb, etc.
"A youthful female voice, mid-range pitch, with a warm playful cadence.
 Slight vocal fry at end of sentences and a breathy, intimate quality."

"A steady, mature male voice with deep baritone resonance.
 Confident and warm, with natural weight and smooth delivery."

"A high-fidelity female voice, perfectly clear and articulate.
 Rhythmic delivery, measured and professional."
```

### Built-in Presets

| Preset | Model | Description |
|--------|-------|-------------|
| `flirty_female` | 1.7b | Warm, playful, vocal fry, breathy |
| `confident_male` | 1.7b | Deep baritone, confident, smooth |
| `ai_narrator` | 0.6b | Clear, articulate, professional |
| `whispery_female` | 1.7b | Soft whisper, intimate, close-mic |
| `energetic_young` | 1.7b | Fast-paced, bright, enthusiastic |
| `zero_shot` | 1.7b | Uses reference audio for cloning |

### Casting a Character

```python
from engine.tts.voice_designer import get_voice_designer, VoiceDesign

designer = get_voice_designer()

# Cast from preset
designer.cast_from_preset("luna", "flirty_female")

# Custom voice design
designer.cast("alex", VoiceDesign(
    description="A confident young male voice with slight roughness...",
    model_size="1.7b",
    tags=["male", "young", "confident"],
))

# Zero-shot cloning
designer.cast("clone_char", VoiceDesign(
    description="Zero-shot voice from reference",
    reference_audio="/path/to/sample.wav",
))
```

Voice designs persist to `config/voices.yaml`.

## Model Selection

| Model | Best For | Speed | Quality |
|-------|----------|-------|---------|
| **0.6b** | Simple voices (AI, narrator, system) | Fast | Good |
| **1.7b** | Complex emotional voices (characters) | Slower | Excellent |

Auto-selection: short text (<100 chars) → 0.6b, longer/emotional → 1.7b.

## API Endpoints

| Method | Path | Description |
|--------|------|-------------|
| POST | `/generate` | Generate speech → WAV file |
| GET | `/jobs/{id}` | Check async job status |
| GET | `/download/{filename}` | Download WAV file |
| GET | `/voices` | List presets + character casts |
| POST | `/cast` | Save voice design for character |
| GET | `/status` | Engine status + queue depth |
| GET | `/health` | Health check |

### Generate Request

```json
{
  "text": "Hello, this is a test.",
  "voice_design": "A warm female voice.",
  "character_id": "luna",
  "model_size": "auto",
  "max_duration": 60,
  "sample_rate": 24000,
  "chain_id": "optional-chain-id"
}
```

### Generate Response

```json
{
  "job_id": "abc123",
  "status": "completed",
  "filepath": "/path/to/voice.wav",
  "filename": "tts_abc123_20260220.wav",
  "duration": 3.2,
  "download_url": "/download/tts_abc123_20260220.wav"
}
```

## Agent Skills

The `tts` skill pack lets agents generate voice autonomously:

```python
# In agent's skill packs
agent = CharacterAgent(character, skill_packs=["tts"])

# Available skills:
# - generate_voice_message(text, character_id, max_duration)
# - cast_voice(character_id, description, model_size)
# - list_voice_presets()
# - list_voicemails(character_id, limit)
```

## MCP Tools

The TTS server also exposes MCP tools at `/mcp`:

- `generate_voice` — Generate speech with voice design
- `cast_character_voice` — Save/update voice design

## Duration Support

| Use Case | Duration |
|----------|----------|
| Voice message | 10–60 seconds |
| Voicemail | 30 seconds – 5 minutes |
| Story narration | 5–60 minutes |

Long generations (>30s estimated) run async — poll via `/jobs/{id}`.

## File Storage

Generated WAV files are saved to:
```
content/simulation/media/voice/
  tts_abc123_20260220_143022.wav
  tts_def456_20260220_143055.wav
```

---

## See Also

- [Asset Studio](ASSET_STUDIO.md) — image/video generation
- [Scenes](SCENES.md) — scene catalog (TTS integration per scene)

---

## Change Log

| Version | Date | Changes |
|---------|------|---------|
| v1.50 | 2026-03-22 | Doc overhaul — unified versioning, health check endpoint, cross-references |
| v1.42 | 2026-03-21 | Initial TTS documentation |
