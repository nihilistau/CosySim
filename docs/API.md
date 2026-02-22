# CosySim API Reference

Full reference for the HTTP REST API (Flask scenes) and WebSocket events
(Socket.IO), plus the Python Agent API and Skill Registry interface.

---

## Table of Contents

1. [Phone Scene REST API](#phone-scene-rest-api) — port 5555
2. [Bedroom Scene REST API](#bedroom-scene-rest-api) — port 5556
3. [Socket.IO Events](#socketio-events)
4. [Python Agent API](#python-agent-api)
5. [Skill Registry API](#skill-registry-api)
6. [LMStudio Manager API](#lmstudio-manager-api)
7. [EventChain API](#eventchain-api)

---

## Phone Scene REST API

Base URL: `http://localhost:5555`

### Chat

#### `POST /api/chat`

Send a user message and receive a character reply.

**Request body (JSON)**

```json
{
  "message": "Hey, how are you?",
  "character_id": "optional-override-id"
}
```

**Response**

```json
{
  "response": "I'm doing great! 😊",
  "type": "text",
  "character": "Maya",
  "timestamp": "2025-01-01T12:00:00"
}
```

---

### Character

#### `GET /api/character`

Return info about the active character.

**Response**

```json
{
  "id": "abc123",
  "name": "Maya",
  "mood": "happy",
  "relationship_level": 0.65,
  "avatar_url": "/api/character/avatar"
}
```

#### `GET /api/characters`

List all characters in the database.

---

### Messages / History

#### `GET /api/history`

Query params: `limit` (int, default 50)

Returns recent conversation history for the active character.

---

### Voice

#### `POST /api/voice/message`

Generate a voice message.

**Body**: `{"text": "Hello!", "mood": "happy", "speed": 1.0}`

**Response**: `{"filename": "voice_abc.wav", "url": "/api/voice/download/voice_abc.wav"}`

#### `GET /api/voice/download/<filename>`

Stream a voice audio file.

#### `GET /api/voice-messages/list`

Query: `?limit=50`

Returns voice message cards for the gallery screen.

---

### Video

#### `GET /api/video-messages/list`

Query: `?limit=50`

Returns video message cards for the gallery screen.

---

### Gallery (Images)

#### `GET /api/gallery/list`

Query: `?character_id=...&limit=50`

Returns image gallery cards.

---

### Skills

#### `GET /api/skills/list`

Query params: `pack` (str), `tag` (str)

Returns all registered skills filtered by pack or tag.

**Response**

```json
{
  "skills": [
    {
      "name": "search_memory",
      "pack": "memory",
      "description": "Search the character's episodic memory.",
      "tags": ["memory", "rag"]
    }
  ],
  "count": 1
}
```

#### `POST /api/skills/run`

Execute a skill by name.

**Body**

```json
{
  "skill": "generate_image",
  "kwargs": {
    "prompt": "A sunlit beach at sunset",
    "width": 512,
    "height": 512
  }
}
```

**Response**

```json
{ "result": "/media/images/output_abc123.png" }
```

---

### Anonymous Character

#### `GET /api/anon/info`

#### `POST /api/anon/message`

Body: `{"message": "Hello"}`

#### `GET /api/anon/history`

---

### Status

#### `GET /api/status`

Returns scene health, active character, and service availability.

---

## Bedroom Scene REST API

Base URL: `http://localhost:5556`

### Character

#### `GET /api/character`

Returns active character JSON.

#### `POST /api/character/load`

Body: `{"character_id": "abc123"}`

---

### Animation

#### `POST /api/character/animation`

Body: `{"animation": "wave"}` — triggers a real-time animation via Socket.IO.

---

## Socket.IO Events

All scenes use [Flask-SocketIO](https://flask-socketio.readthedocs.io/).
Connect with: `const socket = io('http://localhost:5555');`

### Phone Scene (port 5555)

| Event | Direction | Payload | Description |
|---|---|---|---|
| `connect` | Client→Server | — | Establish connection |
| `message` | Client→Server | `{content, character_id}` | Send a chat message |
| `response` | Server→Client | `{content, character, type, timestamp}` | Character reply |
| `typing` | Server→Client | `{character, is_typing}` | Typing indicator |
| `autonomous_message` | Server→Client | `{content, type, media_url, autonomous: true}` | Autonomous character message |
| `call_started` | Server→Client | `{call_id, character, type}` | Voice/video call initiated |
| `call_ended` | Server→Client | `{call_id, duration}` | Call ended |
| `error` | Server→Client | `{message}` | Error notification |

### Bedroom Scene (port 5556)

| Event | Direction | Payload | Description |
|---|---|---|---|
| `connect` | Client→Server | — | Establish connection |
| `chat` | Client→Server | `{message}` | Chat with character |
| `chat_response` | Server→Client | `{message, character}` | Character reply |
| `character_animation` | Server→Client | `{animation, type}` | Trigger 3D animation |
| `character_loaded` | Server→Client | `{character}` | Character loaded into scene |

---

## Python Agent API

### `CharacterAgent`

**Module:** `engine.agents.character_agent`

```python
from engine.agents import CharacterAgent
from content.simulation.database.db import Database
from content.simulation.character_system.character import Character

db   = Database()
char = Character.load("character-id", db)

agent = CharacterAgent(
    char,
    db=db,
    skill_packs=["memory", "comfyui"],  # skills available to this agent
    model=None,                          # None = use default loaded model
    max_context_memories=5,
)
```

#### `CharacterAgent.reply(user_message, *, chain_id=None, history=None, use_tools=True) → str`

Generate a character reply.

- `user_message` — the user's text
- `chain_id` — attach to an existing EventChain; a new chain is created if `None`
- `history` — list of `{"role": "user"/"assistant", "content": "..."}` dicts
- `use_tools` — if `True` and the character has skill packs, uses `llm.act()` (tool calls enabled)

Returns the character's reply string.

#### `CharacterAgent.cancel()`

Cancel an in-progress `reply()` call (sets a cancel flag and calls `stream.cancel()`).

---

### `SceneAgent`

**Module:** `engine.agents.scene_agent`

Lightweight one-shot agent for utility tasks (title generation, classification).

```python
from engine.agents import SceneAgent

agent = SceneAgent()

title    = agent.generate_title("She smiled and handed him the letter.", max_words=6)
summary  = agent.summarize(long_text, max_sentences=3)
label    = agent.classify("Is this message happy?", labels=["happy", "sad", "neutral"])
```

#### `get_scene_agent(model=None) → SceneAgent`

Returns the module-level singleton `SceneAgent`.

---

## Skill Registry API

**Module:** `engine.skills`

```python
from engine.skills import SKILL_REGISTRY, get_skills, get_pack_tools, mcp_skill_pack

# All packs
SKILL_REGISTRY.all_packs()           # → ["memory", "comfyui", ...]

# All skills, optionally filtered by tag
SKILL_REGISTRY.all_tools(tags=["image"])

# Callables for one pack (pass to lms.act)
tools = get_pack_tools("memory")      # → [search_memory, store_memory, ...]

# Get SkillMeta by name
meta = SKILL_REGISTRY.get_skill("generate_image")
print(meta.description)

# Human-readable summary
print(SKILL_REGISTRY.describe())

# MCP integration payload
payload = mcp_skill_pack(
    server_url="http://localhost:9000",
    allowed_tools=["generate_image"],
)
```

---

## LMStudio Manager API

**Module:** `engine.lmstudio`

```python
from engine.lmstudio import get_lmstudio_manager

mgr = get_lmstudio_manager()

# Server check
mgr.is_server_running()              # → bool

# Model management
mgr.list_loaded_models()             # → list[dict]
mgr.get_available_models()           # → list of model path strings
mgr.load_model("gemma-2-9b-instruct", gpu=0.9, ttl=3600, context_length=4096)
mgr.unload_model()

# SDK client (lmstudio package)
client = mgr.get_client()            # → lmstudio.LMStudio
llm    = mgr.get_llm()               # → lmstudio.LLMDynamicHandle

# VRAM estimation (CLI)
estimated_mb = mgr.estimate_vram_needed("gemma-2-9b-instruct")
```

---

## EventChain API

**Module:** `content.simulation.database.events`

```python
from content.simulation.database.events import EventChain
from content.simulation.database.db import Database

ec = EventChain(Database())

# Start a new chain
chain_id = ec.start_chain(scene_id="phone", character_id="abc", summary="User turn")

# Log an event
ev_id = ec.log(
    event_type="llm_request",
    actor="agent",
    payload={"model": "gemma-2-9b", "prompt_len": 512},
    summary="LLM call",
    chain_id=chain_id,
    scene_id="phone",
    character_id="abc",
)

# Log an error
ec.log_error(exception, chain_id=chain_id, scene_id="phone")

# Retrieve
events = ec.get_chain_events(chain_id)          # all events in chain
chain  = ec.get_chain_summary(chain_id)         # aggregated stats
recent = ec.get_recent_chains(scene_id="phone", limit=20)
```

### Event Types

| Type | Actor | Description |
|---|---|---|
| `scene_state_change` | system | Chain root event |
| `message_in` | user | User message received |
| `message_out` | agent | Character message sent |
| `llm_request` | agent/llm | LLM inference started |
| `llm_response` | agent | LLM reply received |
| `llm_cancelled` | agent | Stream cancelled mid-generation |
| `rag_result` | agent | RAG memory retrieval result |
| `tool_call` | agent | Skill function invoked |
| `tool_result` | skill | Skill function returned |
| `autonomous_trigger` | system | Autonomous messenger cycle fired |
| `image_generated` | comfyui | Image generation completed |
| `voice_generated` | tts | Voice synthesis completed |
| `video_generated` | video | Video generation completed |
| `memory_stored` | system | Memory written to RAG |
| `memory_compacted` | system | Chain summarised → stored in RAG |
| `character_state_update` | agent | Trait/mood/relationship changed |
| `error` | system | Exception caught in any service |
| `debug` | system | Developer trace event |

---

## Showcase Scene APIs (v3.1)

All showcase scenes share a common base pattern via `BaseScene`:

### Common Endpoints (all Flask scenes)

| Method | Path | Description |
|--------|------|-------------|
| GET | `/` | Scene index page (HTML) |
| GET | `/api/health` | Scene health + uptime |
| GET | `/api/scene_info` | Scene metadata (name, port, version, features) |

### The Realm (port 5562)

| Method | Path | Description |
|--------|------|-------------|
| GET | `/api/scene_info` | Realm state, current story, active agents |
| POST | `/api/game/new` | Start new game (director personality, story seed) |
| POST | `/api/game/action` | Player action → Director processes → response |
| GET | `/api/game/state` | Full game state (inventory, stats, story progress) |
| POST | `/api/game/mystery/start` | Start Murder Mystery sub-module |

### NeonCity (port 5563)

| Method | Path | Description |
|--------|------|-------------|
| GET | `/api/scene_info` | City grid, players, storm state |
| POST | `/api/game/new` | Generate new city + spawn players |
| POST | `/api/game/move` | Move player on grid |
| POST | `/api/game/action` | Combat, hack, or interact |
| POST | `/api/game/end_turn` | Advance turn (storm progresses) |
| GET | `/api/game/state` | Full board state |

### The Coders Room (port 5564)

| Method | Path | Description |
|--------|------|-------------|
| GET | `/api/scene_info` | Pipeline state, agent assignments |
| POST | `/api/pipeline/feature` | Add feature request to queue |
| POST | `/api/pipeline/tick` | Advance pipeline one step |
| GET | `/api/pipeline/state` | Current pipeline + code output |
| POST | `/api/sandbox/run` | Execute code in sandbox |
