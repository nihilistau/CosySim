# LMStudio v1 API — CosySim Integration Reference

> **Generated:** Phase 4 — v2 Framework (v1-Only Migration)

---

## 1. Overview

CosySim uses **LMStudio** as its local LLM inference backend.  The v2 framework
uses **exclusively** the native v1 REST API (`/api/v1/*`).  OpenAI-compatible
endpoints are no longer used.  A **ConversationManager** provides client-side
state mirroring for stateful chats with edit/fork capabilities.

### API Layer

| Layer | Endpoint(s) | When Used |
|-------|-------------|-----------|
| **Native v1 REST** | `/api/v1/chat`, `/api/v1/models/*` | All chat, model lifecycle |
| **Python SDK** | `lmstudio` package (WebSocket) | `act()` multi-round tool loops, `complete()`, model info |

Tools are accessed via **ephemeral MCP** (`integrations` field), not a `tools` parameter.

---

## 2. Architecture

```
                ┌──────────────────────────────────────────┐
                │         config/default.yaml              │
                │   inference_defaults / load_defaults      │
                └──────────────┬───────────────────────────┘
                               │
                ┌──────────────▼───────────────────────────┐
                │         InferenceConfig / LoadConfig      │
                │      (engine/lmstudio/inference_config.py)│
                └──────────────┬───────────────────────────┘
                               │
        ┌──────────────────────┼──────────────────────┐
        │                      │                      │
        ▼                      ▼                      ▼
  ┌──────────┐         ┌──────────────┐       ┌────────────┐
  │ LMSClient│         │ LMSSDKWrapper│       │ResourceMgr │
  │  (REST)  │         │   (SDK)      │       │ (lifecycle)│
  └────┬─────┘         └──────┬───────┘       └─────┬──────┘
       │                      │                     │
       ▼                      ▼                     ▼
  ┌──────────────────────────────────────────────────┐
  │          LMStudio Server (localhost:1234)         │
  │   /api/v1/*  ·  /v1/*  ·  WebSocket (SDK)        │
  └──────────────────────────────────────────────────┘
```

### Key Files

| File | Role |
|------|------|
| `engine/lmstudio/inference_config.py` | `InferenceConfig` + `LoadConfig` dataclasses |
| `engine/lmstudio/lms_client.py` | `LMSClient` — primary REST inference client |
| `engine/lmstudio/lms_sdk.py` | `LMSSDKWrapper` — Python SDK for `act()`/`complete()` |
| `engine/lmstudio/resource_manager.py` | `ResourceManager` — model lifecycle, GPU budget |
| `engine/lmstudio/__init__.py` | Package exports |
| `engine/lmstudio/client_v2.py` | **DEPRECATED** — Legacy client (emits DeprecationWarning) |
| `engine/lmstudio/conversation.py` | `ConversationManager` — client-side state mirroring |
| `config/default.yaml` | Default inference, load, resource manager config |

---

## 3. InferenceConfig

All inference parameters are captured in a single typed dataclass that flows through
the entire stack:

```
YAML config → AgentProfile → InferenceConfig → LMSClient → /api/v1/chat
```

### Fields

| Field | Type | LMS Native v1 | OpenAI Compat | Description |
|-------|------|---------------|---------------|-------------|
| `temperature` | float | ✅ | ✅ | Sampling temperature (0.0–2.0) |
| `top_p` | float | ✅ | ✅ | Nucleus sampling threshold |
| `top_k` | int | ✅ | ❌ | Top-k sampling (native only) |
| `min_p` | float | ✅ | ❌ | Minimum probability threshold |
| `repeat_penalty` | float | ✅ | ❌ | Penalise repeated tokens |
| `max_output_tokens` | int | ✅ max_output_tokens | ✅ max_tokens | Max generation length |
| `reasoning` | bool | ✅ | ❌ | Enable thinking/CoT mode |
| `stop_strings` | list[str] | ✅ stop | ✅ stop | Early termination strings |
| `response_format` | dict | ✅ | ✅ | Structured output (JSON schema) |
| `draft_model` | str | ✅ | ❌ | Speculative decoding draft model |
| `integrations` | list[dict] | ✅ | ✅* | Ephemeral MCP servers |
| `previous_response_id` | str | ✅ | ❌ | Stateful chat continuation |
| `images` | list[str] | ✅ | ✅ | Image URLs/base64 for VLMs |
| `model` | str | ✅ | ✅ | Override model for this request |

### Factories

```python
from engine.lmstudio.inference_config import InferenceConfig

# From YAML defaults
cfg = InferenceConfig.from_yaml()

# From agent profile
cfg = InferenceConfig.from_agent_profile("big")

# Manual
cfg = InferenceConfig(temperature=0.3, max_output_tokens=4000)

# Merge (base + overrides)
final = InferenceConfig.merge(base, override)

# Convert to API payload
native_fields = cfg.to_native_v1()     # for /api/v1/chat
```

---

## 4. LMSClient (REST)

The primary inference client.  Singleton access via `get_lms_client()`.
Uses **only** native v1 (`/api/v1/chat`).

### Routing Logic (v2 Framework)

```python
client.chat(messages)
#  → ALWAYS /api/v1/chat (no fallback, no OpenAI compat)
#  → Tools: use integrations=[{"type":"ephemeral_mcp","server_url":"..."}]
#  → Raises error if native v1 unavailable
```

### Core Methods

```python
from engine.lmstudio.lms_client import get_lms_client, LMSResponse

client = get_lms_client()

# ── Basic chat ──
resp: LMSResponse = client.chat(messages)
resp: LMSResponse = client.chat(messages, config=InferenceConfig(temperature=0.3))
resp: LMSResponse = client.chat(messages, temperature=0.3, max_tokens=2000)

# ── Stateful chat (server-managed context) ──
resp = client.chat_stateful("Hello!", system="You are a friend.")
resp2 = client.chat_stateful("Tell me more", previous_response_id=resp.response_id)
# Server remembers the conversation — no need to resend history!

# ── Streaming ──
gen = client.chat_stream(messages, on_event=my_callback)
for chunk in gen:
    print(chunk, end="")

# ── With MCP tools (ephemeral) ──
resp = client.chat_with_mcp(messages)  # uses CosySim's MCP server

# ── Structured output (JSON schema) ──
schema = {"type": "object", "properties": {"action": {"type": "string"}}}
resp = client.chat_structured(messages, schema, schema_name="action")

# ── Vision (image input) ──
resp = client.chat_with_images("Describe this", ["data:image/png;base64,..."])

# ── Quick one-shot ──
reply = client.quick_reply("What is 2+2?", system="You are a calculator")

# ── Model lifecycle ──
client.load_model("model-id", config=LoadConfig(context_length=8192))
client.unload_model("model-id")

# ── Utilities ──
models = client.get_models()
info = client.get_model_info()
tokens = client.count_tokens("Hello world")
ctx_len = client.get_context_length()
```

### LMSResponse

```python
@dataclass
class LMSResponse:
    content: str           # Generated text
    model: str             # Model used
    finish_reason: str     # "stop", "length", "tool_calls"
    input_tokens: int      # Prompt tokens
    output_tokens: int     # Completion tokens
    total_tokens: int
    latency_ms: float      # End-to-end latency
    request_id: str        # Local request ID
    response_id: str       # Server response ID (for stateful chats)
    reasoning_content: str # Chain-of-thought (thinking models)
    tool_calls: list       # Tool call requests

    # Properties
    tokens_per_second: float
    has_tool_calls: bool
```

---

## 5. LMSSDKWrapper (Python SDK)

For features not available via REST — multi-round tool calling, raw completion, etc.

```python
from engine.lmstudio.lms_sdk import get_lms_sdk

sdk = get_lms_sdk()

# Respond (single-round chat)
reply = sdk.respond("Hello!", system="Be friendly")

# Act (multi-round tool calling — SDK handles the loop)
result = sdk.act("Search and summarise", tools=[my_tool_fn])

# Complete (raw text completion, no chat template)
text = sdk.complete("Once upon a time")

# Model info
info = sdk.get_model_info()
ctx = sdk.get_context_length()

# Load/unload
sdk.load_model("model-id", config=LoadConfig(context_length=4096))
sdk.unload_model("model-id")
```

### When to Use SDK vs REST

| Feature | REST (LMSClient) | SDK (LMSSDKWrapper) |
|---------|-------------------|---------------------|
| Simple chat | ✅ Preferred | Works |
| Streaming | ✅ SSE | ✅ WebSocket |
| Stateful chats | ✅ | ❌ |
| Custom tools field | ❌ (removed in v2) | ❌ |
| MCP integrations | ✅ (ephemeral) | ❌ |
| `act()` (multi-round) | ❌ | ✅ Preferred |
| `complete()` (raw) | ❌ | ✅ Only option |
| Structured output | ✅ | ❌ |
| Token counting | ✅ (via SDK fallback) | ✅ |
| Model lifecycle | ✅ | ✅ |

---

## 6. LoadConfig

Parameters for loading models into LMStudio:

```python
from engine.lmstudio.inference_config import LoadConfig

cfg = LoadConfig(
    context_length=8192,       # Context window size
    gpu_offload=0.9,           # Fraction (0.0–1.0), "max", or "off"
    flash_attention=True,      # Enable flash attention
    eval_batch_size=512,       # Batch size for prompt evaluation
    keep_kv_cache_on_gpu=True, # KV cache on GPU (faster, uses VRAM)
    num_experts=None,          # MoE: number of experts to use
    ttl=3600,                  # Auto-unload after N seconds idle (0=never)
)

# Use with client
client.load_model("model-id", config=cfg)

# Or YAML defaults: config/default.yaml → lmstudio.load_defaults
cfg = LoadConfig.from_yaml()
```

---

## 7. ResourceManager

Orchestrates model lifecycle across 6 hardware strategies:

### Strategies

| Strategy | Models | VRAM | Best For |
|----------|--------|------|----------|
| **SINGLE_BIG** | 1× large (30B) | ~8 GB | Deep single-agent conversation |
| **CONCURRENT** | 1× medium, N parallel | ~5 GB | Multi-agent, same model |
| **MULTI_SMALL** | 2-3× small (1-3B) | ~6 GB | Many specialist agents |
| **JIT_SWAP** | Load/unload per request | Variable | Sequential workflows |
| **SPECULATIVE** | Main + draft | ~5.5 GB | Fast single agent (2-3× throughput) |
| **HYBRID** | 1× GPU + 1× CPU | GPU ~5 GB | Background + interactive |

### Usage

```python
from engine.lmstudio.resource_manager import get_resource_manager, Strategy

rm = get_resource_manager()

# Set strategy
rm.set_strategy(Strategy.CONCURRENT)

# Acquire a model for an agent (loads if needed)
model_id = rm.acquire("agent_name", role="big")
# ... inference ...
rm.release("agent_name")

# Queue background work (runs on CPU pool)
rm.queue_background_task("gen_images", image_gen_fn, args=(...,))

# Status
status = rm.get_status()
# Returns: {strategy, gpu_vram_used/cap, slots, background_tasks, ...}

# Runtime config update
rm.update_config(strategy="jit_swap", default_ttl=600)
```

### TTL & Auto-Eviction

- Models track `last_used` timestamp
- Background reaper thread checks every 30s
- Idle models exceeding their TTL are automatically unloaded
- Default TTL configurable: `config/default.yaml → lmstudio.resource_manager.default_ttl`

### Background Task Queue

- ThreadPoolExecutor (default 2 workers)
- For CPU-bound work: TTS generation, image generation, batch processing
- Tasks can specify preferred device ("cpu" or "gpu")
- Queue supports priority ordering

---

## 8. Stateful Chats

LMStudio's native v1 API supports **stateful conversations** where the server
maintains the conversation context:

```python
# First message — server creates a new thread
resp1 = client.chat_stateful("Hello!", system="You are a companion.")
print(resp1.response_id)  # e.g. "abc123"

# Continuation — no need to resend history
resp2 = client.chat_stateful("What was I saying?",
                              previous_response_id=resp1.response_id)

# Server remembers everything — token usage is minimal
```

**Benefits:**
- Dramatic token reduction — only send new messages
- Server manages KV cache efficiently
- Perfect for long phone conversations

**Limitations (solved by v2 framework):**
- Only available via native v1 (`/api/v1/chat`) → **solved**: we use v1 exclusively
- State is lost when model is unloaded → **solved**: `ConversationManager` mirrors state client-side and replays history automatically
- No way to edit/fork server-side → **solved**: `ConversationManager.edit_message()` and `fork()` modify client-side history, then clear + replay to server

---

## 9. Ephemeral MCP Integration

LMStudio's native v1 supports per-request MCP server attachment via `integrations`:

```python
# Attach CosySim's MCP server for one request
resp = client.chat_with_mcp(messages)

# Or specify custom MCP servers
resp = client.chat(messages, integrations=[
    {"type": "ephemeral_mcp", "server_url": "http://localhost:8700/sse"}
])
```

This lets the LLM call CosySim skills as tools during inference — without
permanently registering MCP servers in LMStudio's config.

**Note:** `integrations` field works on native v1 API (`/api/v1/chat`).

---

## 10. Structured Output

Force the model to produce JSON matching a schema:

```python
schema = {
    "type": "object",
    "properties": {
        "action": {"type": "string", "enum": ["speak", "move", "emote"]},
        "target": {"type": "string"},
        "text": {"type": "string"},
    },
    "required": ["action"]
}

resp = client.chat_structured(messages, schema, schema_name="character_action")
import json
action = json.loads(resp.content)
```

Uses LMStudio's built-in JSON schema enforcement — **not** post-hoc parsing.
The model is constrained at the logit level to produce valid JSON.

---

## 11. ConversationManager (v2 Framework)

Client-side state mirror for stateful chats. Solves server state loss on model
unload and enables edit/fork of conversation history.

```python
from engine.lmstudio import get_conversation_manager, get_lms_client

mgr = get_conversation_manager()
client = get_lms_client()

# Create a conversation
conv = mgr.create("phone-luna-1", model="gemma-3-4b")

# Send (uses previous_response_id when server has state)
resp = conv.send(client, [{"role": "user", "content": "Hey"}])

# Edit message at index 2 and replay
conv.edit_message(2, {"role": "user", "content": "Actually..."})

# Fork for branching dialog
alt = conv.fork("phone-luna-1-alt")

# Model unloaded → auto-invalidated → next send() replays full history
mgr.invalidate_model("gemma-3-4b")

# Stats for overlay
stats = mgr.stats()  # {"total": 5, "active": 3, "invalidated": 2}
```

---

## 12. Speculative Decoding

Use a small draft model for 2-3× throughput:

```yaml
# config/default.yaml
lmstudio:
  speculative:
    enabled: true
    draft_model: "qwen2.5-0.5b"  # tiny draft model
```

```python
# Or per-request
resp = client.chat(messages, config=InferenceConfig(draft_model="qwen2.5-0.5b"))
```

Requires both the main model and draft model to be loaded simultaneously.
ResourceManager's `SPECULATIVE` strategy handles this automatically.

---

## 12. Configuration Reference

### `config/default.yaml` — LMStudio Section

```yaml
lmstudio:
  host: "127.0.0.1"
  port: 1234
  mcp_enabled: true
  cosysim_mcp_url: "http://localhost:8700/sse"
  vram_cap_mb: 11500
  concurrent_slots: 4
  jit_ttl_seconds: 300

  resource_manager:
    strategy: "concurrent"       # single_big|concurrent|multi_small|jit_swap|speculative|hybrid
    default_ttl: 300             # seconds before idle eviction
    bg_workers: 2                # background thread pool size

  inference_defaults:
    temperature: 0.7
    top_p: 0.9
    top_k: 40
    min_p: 0.05
    repeat_penalty: 1.1
    max_output_tokens: 2000
    reasoning: false

  load_defaults:
    context_length: 4096
    gpu_offload: 0.9
    flash_attention: true
    eval_batch_size: 512
    keep_kv_cache_on_gpu: true
    ttl: 3600

  speculative:
    enabled: false
    draft_model: ""
```

### Environment Variable Overrides

Any YAML key can be overridden by environment variable:
```
COSYSIM_LMSTUDIO__PORT=5678        → lmstudio.port = 5678
COSYSIM_LMSTUDIO__INFERENCE_DEFAULTS__TEMPERATURE=0.5
```

---

## 13. LMStudio REST API Quick Reference

### Native v1 Endpoints

| Method | Path | Description |
|--------|------|-------------|
| `POST` | `/api/v1/chat` | Chat inference (supports stateful, MCP, streaming) |
| `GET` | `/api/v1/models` | List loaded models |
| `POST` | `/api/v1/models/load` | Load a model |
| `POST` | `/api/v1/models/unload` | Unload a model |

### Legacy OpenAI Compatible Endpoints (NOT USED in v2)

> **Deprecated.** These endpoints are no longer used by CosySim.

| Method | Path | Description |
|--------|------|-------------|
| `POST` | `/v1/chat/completions` | Chat completions (supports tools) |
| `GET` | `/v1/models` | List models |

### Native v1 Chat Request Body

```json
{
  "model": "model-identifier",
  "messages": [
    {"role": "system", "content": "..."},
    {"role": "user", "content": "..."}
  ],
  "stream": false,
  "temperature": 0.7,
  "top_p": 0.9,
  "top_k": 40,
  "min_p": 0.05,
  "repeat_penalty": 1.1,
  "max_output_tokens": 2000,
  "reasoning": false,
  "stop": ["\\n###"],
  "response_format": {"type": "json_schema", "json_schema": {"name": "...", "schema": {...}}},
  "previous_response_id": "resp_abc123",
  "integrations": [{"type": "ephemeral_mcp", "server_url": "http://localhost:8700/sse"}]
}
```

### Streaming Events (SSE)

When `"stream": true`, the response is a series of Server-Sent Events:

| Event Type | Description |
|------------|-------------|
| `model_load` | Model is being loaded (JIT) |
| `prompt_processing` | Tokenising and processing prompt |
| `content` | Content delta (the actual tokens) |
| `tool_call` | Model is calling a tool |
| `reasoning` | Reasoning/thinking tokens |
| `done` | Generation complete, includes stats |
| `error` | An error occurred |

---

## 14. Integration Points in CosySim

### CharacterAgent

`engine/agents/character_agent.py` uses `LMSClient` for all LLM calls:
- `quick_query()` → `client.chat()`
- `_reply_via_rest()` → `client.chat()` with full `InferenceConfig`
- Inference params come from the agent's profile → `InferenceConfig.from_agent_profile()`

### Tool Factory

`engine/lmstudio/tool_factory.py` — `run_with_tools()` uses `LMSClient`:
- Tools accessed via **ephemeral MCP** integrations (not `tools` field)
- Extracts `tool_calls` from `LMSResponse.tool_calls`
- Supports `InferenceConfig` passthrough

### AgentLoop

`engine/agents/agent_loop.py` — `_decide()` fallback uses `LMSClient`:
- Builds `InferenceConfig.from_yaml()` with agent-specific overrides
- Uses for perceive→decide→act cycle when main path fails

### Scenes

All scenes expose admin API routes for runtime config:
- `GET /api/mcp/resources` — ResourceManager status
- `POST /api/mcp/resources/config` — Update strategy/TTL
- `GET/POST /api/mcp/inference-defaults` — View/update inference defaults

### Control Overlay

Mounted on every scene at `/overlay/`:
- Real-time inference stats display
- Model load/unload controls
- Inference config editing
- Live event stream from `ActivityBus`

---

## 15. Hardware Considerations

**Target:** i9 NUC Beast Canyon, 32 GB RAM, RTX 2060 12 GB (11,500 MB usable)

### VRAM Budget Planning

| Component | VRAM |
|-----------|------|
| 8B Q4 model | ~5 GB |
| 3B Q4 model | ~2 GB |
| 0.5B draft model | ~0.5 GB |
| KV cache (4096 ctx) | ~0.5–1 GB |
| ComfyUI (when active) | ~3–4 GB |
| **Remaining for models** | **~7–8 GB** |

### Recommended Configurations

1. **Single scene, deep conversation:** SINGLE_BIG + 30B MoE model
2. **Multi-agent phone scene:** CONCURRENT + 8B model, 4 parallel slots
3. **Background generation + chat:** HYBRID + GPU model + CPU offload for TTS/images
4. **Fast responses needed:** SPECULATIVE + 7B main + 0.5B draft

### CPU Offload

- Models can be partially offloaded to RAM: `gpu_offload: 0.5` (50% GPU, 50% CPU)
- Background tasks (TTS, image gen) can run entirely on CPU via ResourceManager
- Some models can run fully on CPU: `gpu_offload: "off"` — slow but frees VRAM
