# API Reference

> CosySim Documentation -- v1.50 [2026-03-22]
>
> REST endpoints, Socket.IO events, and MCP tools across all scenes and services.

---

## Table of Contents

1. [Overview](#overview)
2. [Common Patterns](#common-patterns)
3. [Phone Scene API (port 5555)](#phone-scene-api-port-5555)
4. [Penthouse Scene API (port 5556)](#penthouse-scene-api-port-5556)
5. [Casino Scene API (port 5559)](#casino-scene-api-port-5559)
6. [Realm Scene API (port 5562)](#realm-scene-api-port-5562)
7. [Command Center API (port 5566)](#command-center-api-port-5566)
8. [Overlay Admin API](#overlay-admin-api)
9. [TTS API (port 8600)](#tts-api-port-8600)
10. [Socket.IO Events](#socketio-events)
11. [MCP Tools](#mcp-tools)
12. [Cross-References](#cross-references)
13. [Change Log](#change-log)

---

## Overview

Every CosySim scene runs as a Flask + Flask-SocketIO server on a
dedicated port. The TTS server uses FastAPI. All servers expose REST
endpoints for state management and actions, plus Socket.IO (or WebSocket)
channels for real-time updates.

| Service | Port | Framework |
|---------|------|-----------|
| Phone | 5555 | Flask + SocketIO |
| Penthouse | 5556 | Flask + SocketIO |
| Casino | 5559 | Flask + SocketIO |
| Realm | 5562 | Flask + SocketIO |
| NeonCity | 5563 | Flask + SocketIO |
| Coders Room | 5564 | Flask + SocketIO |
| Heist | 5565 | Flask + SocketIO |
| Command Center | 5566 | Flask + SocketIO |
| TTS Server | 8600 | FastAPI |
| Overlay | `/overlay/` prefix on any scene | Flask Blueprint |

---

## Common Patterns

**Response envelope** -- most endpoints return:

```json
{"ok": true, ...}
```

**Error format:**

```json
{"ok": false, "error": "human-readable message"}
```

Some older Penthouse endpoints use `{"success": true}` / `{"error": "..."}`.

**Base URL:** `http://localhost:<port>`

**Content-Type:** All POST bodies are `application/json`.

---

## Phone Scene API (port 5555)

Base URL: `http://localhost:5555`

### Threads & Messaging

| Method | Endpoint | Description | Body / Params |
|--------|----------|-------------|---------------|
| GET | `/api/threads` | List all conversation threads | -- |
| POST | `/api/threads/dm` | Open or get a DM thread with a character | `{character_id}` |
| POST | `/api/threads/group` | Create a group chat thread | `{name, member_ids[]}` |
| GET | `/api/thread/<thread_id>/messages` | Get messages in a thread | `?limit=50&before=<msg_id>` |
| POST | `/api/thread/<thread_id>/send` | Send a message (triggers AI reply) | `{content, type?}` |

### Contacts

| Method | Endpoint | Description | Body / Params |
|--------|----------|-------------|---------------|
| GET | `/api/contacts` | List all characters as phone contacts | -- |

### Gallery & Media

| Method | Endpoint | Description | Body / Params |
|--------|----------|-------------|---------------|
| GET | `/api/gallery` | List all images + videos from media dirs | -- |
| DELETE | `/api/gallery/<filename>` | Delete an image or video | -- |
| GET | `/api/voice-messages` | List voice message files | -- |
| GET | `/api/video-messages` | List video message files | -- |
| GET | `/api/video-message/download/<filename>` | Download a video file | -- |
| GET | `/media/voice/<filename>` | Serve a voice file | -- |
| GET | `/media/video/<filename>` | Serve a video file | -- |
| GET | `/media/photo/<filename>` | Serve a photo file | -- |
| GET | `/media/images/<filename>` | Serve a generated image | -- |

### Image Generation

| Method | Endpoint | Description | Body / Params |
|--------|----------|-------------|---------------|
| POST | `/api/generate-image` | Generate image via ComfyUI | `{prompt}` |

### Games (Truth or Dare)

| Method | Endpoint | Description | Body / Params |
|--------|----------|-------------|---------------|
| POST | `/api/games/start` | Start a game session in a thread | `{thread_id, character_id}` |
| POST | `/api/games/action` | Pick truth or dare | `{thread_id, choice: "truth"\|"dare"}` |
| POST | `/api/games/end` | End an active game | `{thread_id}` |

### Hacker App

| Method | Endpoint | Description | Body / Params |
|--------|----------|-------------|---------------|
| GET | `/api/hacker/targets` | List all characters with state summary | -- |
| GET | `/api/hacker/<char_id>/profile` | Full character state + personality data | -- |
| GET | `/api/hacker/<char_id>/messages` | Get DM messages for a character | `?limit=100` |
| POST | `/api/hacker/<char_id>/intercept` | Inject a directive into character state | `{directive}` |

### Research (NotebookLM)

| Method | Endpoint | Description | Body / Params |
|--------|----------|-------------|---------------|
| POST | `/api/research/search` | Ask a question to NotebookLM | `{question, notebook_id?}` |
| POST | `/api/research/add_source` | Add a source to a notebook | `{notebook_id, source_type, source_value}` |
| POST | `/api/research/audio` | Generate audio overview for notebook | `{notebook_id, customization?}` |
| GET | `/api/research/notebooks` | List all notebooks | -- |

### Voice Studio

| Method | Endpoint | Description | Body / Params |
|--------|----------|-------------|---------------|
| GET | `/api/voice-studio/premade` | List premade voice designs | -- |

### Arcade

| Method | Endpoint | Description | Body / Params |
|--------|----------|-------------|---------------|
| POST | `/api/arcade/highscore` | Submit an arcade game score | `{game, score}` |

### Admin

| Method | Endpoint | Description | Body / Params |
|--------|----------|-------------|---------------|
| POST | `/api/admin/autotxt-mute` | Toggle autonomous messaging mute | `{muted?}` |
| GET | `/api/admin/autotxt-mute` | Check autonomous messaging mute status | -- |
| POST | `/api/admin/wipe-messages` | Delete all messages + media files | -- |
| GET | `/api/admin/stats` | Get unread count, thread count | -- |

### MCP Framework (Phone)

| Method | Endpoint | Description | Body / Params |
|--------|----------|-------------|---------------|
| GET | `/api/mcp/status` | MCP framework status | -- |
| GET | `/api/mcp/agent-profiles` | List all agent profiles | -- |
| GET | `/api/mcp/event-log` | Recent MCP events | `?limit=50&type=<event_type>` |
| GET | `/api/mcp/timers` | Active framework timers | -- |
| GET | `/api/mcp/consequences` | Pending consequences for phone scene | -- |
| GET | `/api/mcp/lmstudio` | LMStudio config & status | -- |
| GET | `/api/mcp/resources` | Resource manager status | -- |
| POST | `/api/mcp/resources/config` | Update resource manager config | `{...config}` |
| GET | `/api/mcp/inference-defaults` | Inference config defaults | -- |

---

## Penthouse Scene API (port 5556)

Base URL: `http://localhost:5556`

### Scene State

| Method | Endpoint | Description | Body / Params |
|--------|----------|-------------|---------------|
| GET | `/api/scene/state` | Full scene state snapshot | -- |
| POST | `/api/scene/time` | Set time of day + lighting | `{time: "evening"\|"night"\|...}` |
| GET | `/api/scene/lighting_presets` | Available lighting presets | -- |

### Characters

| Method | Endpoint | Description | Body / Params |
|--------|----------|-------------|---------------|
| GET | `/api/characters/list` | List all characters (DB + loaded status) | -- |
| POST | `/api/character/load` | Load a character into the scene (max 2) | `{character_id, personality?}` |
| POST | `/api/character/remove` | Remove a character from the scene | `{character_id}` |
| GET | `/api/characters/loaded` | Get currently loaded characters' state | -- |

### Character Stats & Appearance

| Method | Endpoint | Description | Body / Params |
|--------|----------|-------------|---------------|
| POST | `/api/character/stats/adjust` | Adjust a stat by delta | `{character_id, stat, delta}` |
| POST | `/api/character/stats/set` | Set a stat to absolute value | `{character_id, stat, value}` |
| POST | `/api/character/outfit` | Change character's outfit | `{character_id, outfit}` |
| POST | `/api/character/position` | Change character's position | `{character_id, position}` |
| POST | `/api/character/personality` | Swap personality profile | `{character_id, personality_key}` |

### Spatial & Props

| Method | Endpoint | Description | Body / Params |
|--------|----------|-------------|---------------|
| POST | `/api/location/move` | Move character to a location | `{character_id, location_id\|location}` |
| GET | `/api/locations` | List all locations and positions | -- |
| GET | `/api/props/list` | Available props + props in room | -- |
| POST | `/api/props/add` | Add a prop to the room | `{prop_id}` |
| POST | `/api/props/remove` | Remove a prop from the room | `{prop_id}` |
| POST | `/api/props/give` | Give a prop to a character | `{character_id, prop_id}` |

### Director Controls

| Method | Endpoint | Description | Body / Params |
|--------|----------|-------------|---------------|
| POST | `/api/director/whisper` | Whisper instruction to a character | `{character_id, message}` |
| POST | `/api/director/give_line` | Feed a scripted line to a character | `{character_id, line}` |
| POST | `/api/director/give_action` | Direct an action for a character | `{character_id?, action}` |
| POST | `/api/director/broadcast` | Broadcast a director message to all | `{message}` |
| POST | `/api/director/enter_scene` | Director enters/exits the scene | `{in_scene, name?}` |
| POST | `/api/director/mount` | Mount character at position/location | `{character_id, position?, location_id?}` |
| POST | `/api/director/interact` | Initiate interaction between characters | `{actor_id, target_id, interaction}` |
| GET | `/api/interactions` | List available interaction types | -- |

### Bed Game

| Method | Endpoint | Description | Body / Params |
|--------|----------|-------------|---------------|
| POST | `/api/bedgame/start` | Start the bed game (2-3 players) | `{players[], max_rounds?}` |
| POST | `/api/bedgame/action` | Perform a game action | `{action, target?, custom?, player_id?}` |
| POST | `/api/bedgame/end` | End the bed game | `{reason?}` |
| GET | `/api/bedgame/state` | Current bed game state | -- |
| GET | `/api/bedgame/actions` | List available game actions | -- |

### Scenarios & Story

| Method | Endpoint | Description | Body / Params |
|--------|----------|-------------|---------------|
| GET | `/api/scenario/list` | List premade scenarios | -- |
| POST | `/api/scenario/set` | Activate a premade scenario | `{scenario_key}` |
| POST | `/api/scenario/clear` | Clear active scenario | -- |
| POST | `/api/story/beat` | Add a story beat | `{beat}` |
| GET | `/api/story/beats` | Get current story beats | -- |
| POST | `/api/story/clear_beat` | Remove a story beat by index | `{index}` |

### Conversation & Events

| Method | Endpoint | Description | Body / Params |
|--------|----------|-------------|---------------|
| POST | `/api/conversation/start` | Start a themed conversation | `{type: "flirt"\|"dare"\|"fantasy"\|...}` |
| POST | `/api/event/fire` | Fire a scene event | `{type, custom?}` |
| POST | `/api/menace` | Legacy event injection (alias) | `{type}` |

### Agent Loop

| Method | Endpoint | Description | Body / Params |
|--------|----------|-------------|---------------|
| POST | `/api/agents/start` | Start autonomous agent loop | `{interval?}` |
| POST | `/api/agents/stop` | Stop agent loop | -- |
| POST | `/api/agents/tick` | Manual single-tick agent step | -- |
| POST | `/api/agents/whisper` | Legacy whisper endpoint | `{character_id, message}` |
| POST | `/api/agents/model` | Set model for a character | `{character_id, model, mode?}` |
| GET | `/api/agents/model` | Get model config per character | -- |

### Models & Misc

| Method | Endpoint | Description | Body / Params |
|--------|----------|-------------|---------------|
| GET | `/api/models/available` | List loaded + available LLM models | -- |
| POST | `/api/mode` | Set scene mode | `{mode: "observe"\|...}` |
| GET | `/api/history` | Agent loop conversation history | -- |
| GET | `/api/ambient/tracks` | List ambient audio tracks | -- |
| GET | `/api/meta/constants` | All constants (positions, outfits, props, etc.) | -- |

### MCP Framework (Penthouse)

| Method | Endpoint | Description | Body / Params |
|--------|----------|-------------|---------------|
| GET | `/api/mcp/status` | Framework status | -- |
| GET | `/api/mcp/scene-state` | Penthouse MCP scene node state | -- |
| GET | `/api/mcp/event-log` | Recent events | `?limit=50` |
| GET | `/api/mcp/lmstudio` | LMStudio config & status | -- |
| GET | `/api/mcp/resources` | Resource manager status | -- |
| POST | `/api/mcp/resources/config` | Update resource manager config | `{...config}` |
| GET | `/api/mcp/inference-defaults` | Inference defaults | -- |
| GET/POST | `/api/mcp/config` | Read or update MCP config | `{key: value, ...}` (POST) |

---

## Casino Scene API (port 5559)

Base URL: `http://localhost:5559`

| Method | Endpoint | Description | Body / Params |
|--------|----------|-------------|---------------|
| GET | `/api/health` | Scene health check | -- |
| GET | `/api/state` | Full game state (hands, chips, pot, stats) | -- |
| POST | `/api/new-hand` | Deal a new hand | -- |
| POST | `/api/bet` | Place a bet | `{amount}` |
| POST | `/api/bluff` | Attempt to bluff | -- |
| POST | `/api/showdown` | Reveal cards and resolve | -- |
| POST | `/api/fold` | Fold current hand | -- |
| POST | `/api/drink` | Order a cocktail (stat effects) | `{drink_id}` |
| POST | `/api/random-event` | Trigger a random casino event | -- |
| GET | `/api/framework-status` | Full MCP framework introspection | -- |

---

## Realm Scene API (port 5562)

Base URL: `http://localhost:5562`

### Game Core

| Method | Endpoint | Description | Body / Params |
|--------|----------|-------------|---------------|
| GET | `/api/scene/info` | Scene metadata + plugin info | -- |
| GET | `/api/game/state` | Full game state (stats, inventory, story) | -- |
| POST | `/api/game/new` | Start a new adventure | `{personality?, time_limit?}` |
| POST | `/api/game/choice` | Make a player choice | `{choice_id?\|custom_text?}` |
| POST | `/api/game/desperation` | Roll the desperation dice | -- |
| POST | `/api/game/mutiny` | Trigger assistant mutiny (requires low patience) | -- |
| POST | `/api/game/steal` | Assistant steals a fourth-wall item | `{item_name?}` |
| POST | `/api/game/use_item` | Use an inventory item | `{item_id}` |

### Murder Mystery

| Method | Endpoint | Description | Body / Params |
|--------|----------|-------------|---------------|
| POST | `/api/murder/start` | Start a murder mystery party | -- |
| POST | `/api/murder/investigate` | Investigate a target/room | `{target}` |
| POST | `/api/murder/interrogate` | Interrogate an NPC | `{npc_id, question?}` |
| POST | `/api/murder/accuse` | Accuse a suspect | `{suspect_id, weapon, room}` |

### Combat

| Method | Endpoint | Description | Body / Params |
|--------|----------|-------------|---------------|
| POST | `/api/combat/start` | Start combat with an enemy | `{enemy?}` |
| POST | `/api/combat/attack` | Attack the enemy | -- |
| POST | `/api/combat/flee` | Attempt to flee | -- |
| POST | `/api/combat/defend` | Defend / brace for attack | -- |
| POST | `/api/combat/use_item` | Use an item in combat | `{item_id}` |

### Location & Travel

| Method | Endpoint | Description | Body / Params |
|--------|----------|-------------|---------------|
| GET | `/api/location/current` | Current location info | -- |
| POST | `/api/location/move` | Travel to a destination | `{destination}` |

### Quests

| Method | Endpoint | Description | Body / Params |
|--------|----------|-------------|---------------|
| GET | `/api/quests` | List available, active, completed quests | -- |
| POST | `/api/quests/accept` | Accept a quest | `{quest}` |

### Equipment & Inventory

| Method | Endpoint | Description | Body / Params |
|--------|----------|-------------|---------------|
| GET | `/api/equipment` | Current equipment + total stats | -- |
| POST | `/api/equipment/equip` | Equip an item from inventory | `{item_id}` |
| POST | `/api/equipment/unequip` | Unequip a slot | `{slot}` |
| GET | `/api/inventory` | Full inventory + gold | -- |

### Shop & Economy

| Method | Endpoint | Description | Body / Params |
|--------|----------|-------------|---------------|
| GET | `/api/shop/catalog` | Browse shop catalog | -- |
| POST | `/api/shop/buy` | Buy an item | `{item_id}` |
| POST | `/api/shop/sell` | Sell an item | `{item_id}` |

---

## Command Center API (port 5566)

Base URL: `http://localhost:5566`

### Dashboard & System

| Method | Endpoint | Description | Body / Params |
|--------|----------|-------------|---------------|
| GET | `/api/dashboard` | Full dashboard snapshot | -- |
| GET | `/api/system` | System snapshot (CPU, memory, GPU) | -- |
| GET | `/api/pipeline` | Inference pipeline snapshot | -- |
| GET | `/api/alerts` | Alert status + history | -- |
| GET | `/api/activity` | Activity snapshot | -- |
| GET | `/api/pipeline/history` | Pipeline history over time | `?seconds=60&limit=100` |
| GET | `/api/system/history` | System metrics history | `?seconds=60` |
| GET | `/api/benchmarks` | Benchmark statistics | -- |

### Training

| Method | Endpoint | Description | Body / Params |
|--------|----------|-------------|---------------|
| GET | `/api/training` | Training stats | -- |
| GET | `/api/training/candidates` | List training candidates | `?dataset=&min_quality=0.0&limit=50` |
| POST | `/api/training/export` | Export training candidates to JSONL | `{dataset, min_quality?}` |

### Scene Monitoring (Cross-Scene)

| Method | Endpoint | Description | Body / Params |
|--------|----------|-------------|---------------|
| GET | `/api/scenes` | List all active scenes with summaries | -- |
| GET | `/api/scenes/<scene_id>` | Detailed state for a scene | -- |
| GET | `/api/scenes/<scene_id>/feed` | Recent messages/events from a scene | `?limit=20` |
| GET | `/api/scenes/<scene_id>/characters` | Characters in a scene with state | -- |
| GET | `/api/characters/<char_id>` | Detailed character state | -- |
| GET | `/api/characters/<char_id>/conversations` | Conversation history | `?limit=30` |
| POST | `/api/scenes/<scene_id>/inject` | Inject event into a scene | `{type: "narrative"\|"directive"\|"broadcast", content}` |
| POST | `/api/characters/<char_id>/edit_stats` | Live-edit character stats | `{stat_key: value, ...}` |

### Live Feed

| Method | Endpoint | Description | Body / Params |
|--------|----------|-------------|---------------|
| GET | `/api/live_feed` | List running scenes for feed selector | -- |
| GET | `/api/live_feed/<scene_name>` | Recent messages from a scene feed | `?limit=20` |

### Scene Status

| Method | Endpoint | Description | Body / Params |
|--------|----------|-------------|---------------|
| GET | `/api/scene_status` | Status cards for all active scenes | -- |

### Character State Viewer

| Method | Endpoint | Description | Body / Params |
|--------|----------|-------------|---------------|
| GET | `/api/character_state/<character_id>` | Stats, buffs, tags, relationships, scene | -- |

### System Metrics

| Method | Endpoint | Description | Body / Params |
|--------|----------|-------------|---------------|
| GET | `/api/system_metrics` | Framework status, totals, memory estimates | -- |

### Scene Control

| Method | Endpoint | Description | Body / Params |
|--------|----------|-------------|---------------|
| POST | `/api/scene_control/directive` | Inject dialog directive into a character | `{scene_id, character_id, directive, turns?}` |
| POST | `/api/scene_control/broadcast` | Broadcast message to all characters in a scene | `{scene_id, message, sender?}` |
| GET | `/api/scene_control/characters/<scene_name>` | List characters in a scene with state | -- |
| POST | `/api/scene_control/transfer` | Transfer a character between scenes | `{character_id, from_scene, to_scene}` |

---

## Overlay Admin API

Real-time system monitoring and control panel. Mounted as a Flask
Blueprint under the `/overlay/` prefix on whichever scene app calls
`mount_overlay(app, socketio)`.

**Module:** `engine.overlay.overlay_bp`

All paths below are relative to the Overlay host
(e.g. `http://localhost:5555/overlay/api/status`).

### Core

| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/overlay/` | Admin panel SPA (HTML/JS/CSS) |
| GET | `/overlay/api/status` | Combined system status (LMStudio, VRAM, framework, skills) |
| GET | `/overlay/api/events` | SSE stream of real-time ActivityBus events |

### Agents

| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/overlay/api/agents` | List all registered agents |
| GET | `/overlay/api/agent/<id>` | Agent detail + MCP node data |
| POST | `/overlay/api/agent/<id>` | Update agent state -- body: `{state: {...}}` |

### Config & Models

| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/overlay/api/config` | Config sections (llm, lmstudio, hardware, mcp, tts, comfyui) |
| POST | `/overlay/api/config` | Set config values -- body: `{"key.path": value}` |
| GET | `/overlay/api/models` | Loaded models + ModelManager status |
| POST | `/overlay/api/models/load` | Load a model -- body: `{model_id, context_length?, gpu_offload?, ttl?}` |
| POST | `/overlay/api/models/unload` | Unload a model -- body: `{model_id}` |
| GET | `/overlay/api/pipeline` | Interceptor pipeline configuration |

### Resources & Inference

| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/overlay/api/resources` | VRAM, GPU utilisation, quotas |
| POST | `/overlay/api/resources` | Update resource manager config |
| GET | `/overlay/api/inference` | Inference defaults (temperature, top_p, max_tokens) |
| POST | `/overlay/api/inference` | Override inference defaults -- body: `{temperature?, max_tokens?}` |
| GET | `/overlay/api/router` | InferenceRouter metrics (queue, throughput, tiers) |
| POST | `/overlay/api/router` | Update router config -- body: `{max_queue_depth?, tiers?}` |
| GET | `/overlay/api/router/tiers` | Per-tier config and live slot usage |
| GET | `/overlay/api/streaming` | Streaming stats (active agents, conversations, StreamProcessor) |

### Character State

| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/overlay/api/character/<id>/state` | Unified state (mood, energy, inhibition, arousal, happiness) |
| POST | `/overlay/api/character/<id>/state` | Update state -- body: `{mood?, energy?, mode?, source?, persist?}` |
| GET | `/overlay/api/characters/<id>/buffs` | Active buffs for a character |
| POST | `/overlay/api/characters/<id>/buffs` | Add a buff -- body: `{buff_id?, deltas, duration?}` |
| GET | `/overlay/api/characters/<id>/attraction/<other_id>` | Calculate attraction between two characters |
| GET | `/overlay/api/characters/<id>/tags` | Get behavioral tags + top tags |
| POST | `/overlay/api/characters/<id>/tags` | Add/reinforce a tag -- body: `{tag, strength?}` |

### Conversation & Directives

| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/overlay/api/heat` | Conversation heat levels -- query: `?key=<conv_key>` |
| POST | `/overlay/api/directive` | Issue a dialog directive -- body: `{character_id, scene, type, value, turns?}` |
| GET | `/overlay/api/directive/<character_id>` | Check active directive -- query: `?scene=` |

Directive types: `force_response`, `must_include`, `style_lock`,
`topic_steer`, `mood_set`, `refuse`.

### Simulation Interaction

| Method | Endpoint | Description |
|--------|----------|-------------|
| POST | `/overlay/api/act` | Inject message or event -- body: `{action, agent_id, message, scene, ...}` |
| GET | `/overlay/api/memory/<agent_id>` | Browse RAG memories -- query: `?q=&limit=10` |
| GET | `/overlay/api/skills` | List all registered skills |

### Shared Boards

| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/overlay/api/boards` | List all shared boards |
| GET | `/overlay/api/boards/<id>/scores` | Get highscores -- query: `?limit=10` |
| GET | `/overlay/api/boards/<id>/messages` | Get board messages -- query: `?limit=50` |
| POST | `/overlay/api/boards/<id>/messages` | Post to a board -- body: `{author_id, author_name, content}` |

### Training & NotebookLM

| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/overlay/api/training/config` | Training pipeline configuration |
| GET | `/overlay/api/training/status` | Training jobs status |
| GET | `/overlay/api/training/datasets` | List dataset files with sizes |
| GET | `/overlay/api/notebooklm/status` | NotebookLM proxy status + config |

---

## TTS API (port 8600)

Base URL: `http://localhost:8600`

FastAPI server using Qwen3-TTS models (0.6B fast, 1.7B complex/emotional).

### Generation

| Method | Endpoint | Description | Body / Params |
|--------|----------|-------------|---------------|
| POST | `/generate` | Generate speech from text | `{text, voice_design?, character_id?, model_size?, sample_rate?, max_duration?}` |
| POST | `/generate_stream` | Stream audio as SSE (base64 WAV chunks) | `{text, voice_design?, character_id?, model_size?, sample_rate?, max_duration?}` |
| WS | `/ws/stream` | Real-time audio push over WebSocket | Send JSON: `{text, voice_design?, character_id?, model_size?}` |
| POST | `/batch` | Multi-line generation + optional stitching | `{lines[{text, voice_design?, ...}], stitch?, gap_ms?, post_process?}` |

**`POST /generate` response:**

```json
{
  "job_id": "abc123",
  "status": "completed",
  "filename": "tts_abc123.wav",
  "duration": 3.2,
  "download_url": "/download/tts_abc123.wav"
}
```

Long texts return `{"job_id": "...", "status": "queued"}` -- poll via
`GET /jobs/{job_id}`.

**`POST /generate_stream` SSE events:**

```
data: {"chunk": "<base64-wav>", "duration": 1.5, "index": 0}
data: {"done": true, "total_duration": 3.2, "chunks": 2}
```

**`WS /ws/stream` protocol:**
Client sends JSON text frame, server replies with binary WAV frames,
final JSON text frame `{"done": true, "total_duration": 3.2, "chunks": 2}`.

### Jobs & Files

| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/jobs/{job_id}` | Poll async generation status |
| GET | `/download/{filename}` | Download a generated WAV file |

### Voices

| Method | Endpoint | Description | Body / Params |
|--------|----------|-------------|---------------|
| GET | `/voices` | List all voice designs (presets + character casts) | -- |
| POST | `/cast` | Save a voice design for a character | `{character_id, description, model_size?, reference_audio?, tags?}` |

### Health & Status

| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/health` | Quick health check |
| GET | `/status` | Server status: model loaded, queue depth, totals |

---

## Socket.IO Events

All Flask scenes use [Flask-SocketIO](https://flask-socketio.readthedocs.io/).
Connect: `const socket = io('http://localhost:<port>');`

### Phone Scene (port 5555)

| Event | Direction | Payload | Description |
|-------|-----------|---------|-------------|
| `message_new` | Server->Client | `{thread_id, message, char_name?, mood?}` | New message in a thread |
| `thread_updated` | Server->Client | `{thread_id}` | Thread metadata changed |
| `typing` | Server->Client | `{thread_id, char_id, active}` | Character typing indicator |
| `game_event` | Server->Client | `{thread_id, event, ...}` | Game started/challenge/ended |
| `mood_update` | Server->Client | `{...payload}` | Character mood changed |
| `story_beat` | Server->Client | `{...payload}` | Story beat triggered |
| `admin_wipe` | Server->Client | `{messages, media}` | Admin wipe completed |

### Penthouse Scene (port 5556)

| Event | Direction | Payload | Description |
|-------|-----------|---------|-------------|
| `connect` | Client->Server | -- | Server sends `scene_state` + `constants` |
| `request_state` | Client->Server | -- | Request full state broadcast |
| `chat_message` | Bidirectional | `{name, message, timestamp}` | Chat in the scene |
| `quick_stat` | Client->Server | `{character_id, stat, delta}` | Adjust a stat quickly |
| `scene_state` | Server->Client | `{...full state}` | Full scene state broadcast |
| `time_changed` | Server->Client | `{time, lighting}` | Time of day changed |
| `scene_event` | Server->Client | `{type, message}` | Environment event fired |
| `menace_event` | Server->Client | `{type, message}` | Legacy event (alias) |
| `director_speaks` | Server->Client | `{name, message, timestamp}` | Director broadcast |
| `conversation_started` | Server->Client | `{type, line, speaker}` | Themed conversation began |
| `bedgame_started` | Server->Client | `{...game state}` | Bed game started |
| `bedgame_action` | Server->Client | `{...record, next_player, game_over}` | Bed game turn |
| `bedgame_ended` | Server->Client | `{reason}` | Bed game ended |
| `environment_update` | Server->Client | `{...payload}` | Environment state update |
| `mood_update` | Server->Client | `{...payload}` | Character mood change |
| `story_beat` | Server->Client | `{...payload}` | Story beat triggered |

### Casino Scene (port 5559)

| Event | Direction | Payload | Description |
|-------|-----------|---------|-------------|
| `game_update` | Server->Client | `{...game state}` | Hand/bet/fold/showdown result |
| `casino_event` | Server->Client | `{...event}` | Random casino event |

### Realm Scene (port 5562)

| Event | Direction | Payload | Description |
|-------|-----------|---------|-------------|
| `game_started` | Server->Client | `{...game state}` | New game started |
| `turn_update` | Server->Client | `{...game state}` | Turn resolved |
| `desperation` | Server->Client | `{success, ...}` | Desperation dice result |
| `mutiny_started` | Server->Client | `{duration}` | Mutiny mode activated |
| `item_stolen` | Server->Client | `{...item}` | Assistant stole an item |
| `murder_started` | Server->Client | `{...result, narration}` | Murder mystery started |
| `accusation_result` | Server->Client | `{won?, remaining?}` | Accusation outcome |
| `combat_started` | Server->Client | `{enemy_name, enemy_hp, ...}` | Combat initiated |
| `combat_turn` | Server->Client | `{player_damage, enemy_hp, ...}` | Combat round |
| `combat_victory` | Server->Client | `{defeated, xp_gained, loot?}` | Enemy defeated |
| `combat_flee` | Server->Client | `{fled, enemy_damage?}` | Flee attempt result |
| `combat_defend` | Server->Client | `{enemy_damage, player_hp}` | Defend result |
| `combat_item_used` | Server->Client | `{healed?, item_damage?, ...}` | Item used in combat |
| `location_changed` | Server->Client | `{from_name, to_name, ...}` | Player moved |
| `quest_accepted` | Server->Client | `{title, description, ...}` | Quest accepted |
| `equipment_changed` | Server->Client | `{...equipment}` | Equipment changed |
| `gold_changed` | Server->Client | `{gold}` | Gold amount changed |

### Overlay (namespace `/overlay`)

| Event | Direction | Payload | Description |
|-------|-----------|---------|-------------|
| `connect` | Client->Server | -- | Server sends `overlay_activity` snapshot |
| `overlay_refresh` | Client->Server | -- | Request full state refresh |
| `overlay_activity` | Server->Client | `{...snapshot}` | ActivityBus snapshot |

---

## MCP Tools

50+ tools are available via the MCP (Model Context Protocol) integration,
enabling LLM agents to interact with the simulation programmatically.

Tool categories include: memory, image generation (ComfyUI), voice (TTS),
video, character state, scene control, training, and research.

See **[MCP Framework](MCP_FRAMEWORK.md)** for the full MCP tool
reference, protocol details, and integration guide.

---

## Cross-References

- [Architecture](ARCHITECTURE.md) -- system design, layers, data flow, interceptor pipeline
- [Scenes](SCENES.md) -- scene descriptions, ports, and capabilities
- [MCP Framework](MCP_FRAMEWORK.md) -- skill dispatch, governance, state coordination
- [ARGUS](ARGUS.md) -- browser automation, API surface discovery, LiveDebugger

---

## Change Log

| Version | Date | Description |
|---------|------|-------------|
| v1.50 | 2026-03-22 | Updated header to v1.50; added cross-references and change log; removed stale doc references |
| v1.49 | 2026-03-19 | Added NeonCity, Coders Room, Heist ports to overview table |
| v1.45 | 2026-03-15 | Added Overlay Admin API section with full endpoint catalog |
| v1.42 | 2026-03-10 | Added TTS API section (FastAPI, Qwen3-TTS, batch, streaming) |
| v1.40 | 2026-03-05 | Initial API reference with Phone, Penthouse, Casino, Realm, Command Center, Socket.IO events |
