# LMStudio Integration Guide

CosySim implements the **complete LMStudio v1 REST API** for local LLM inference. This guide covers all endpoints, MCP integration, streaming, speculative decoding, and configuration.

> **Input/output format asymmetry:** LMStudio v1 accepts `input` + `system_prompt` (not OpenAI-style messages array) but returns standard `output[]` message objects. CosySim's `LMSClient` handles this translation — callers pass standard `messages` lists and `InferenceConfig.to_native_v1()` converts them automatically.

## Architecture

```
┌──────────────┐     REST /api/v1/chat              ┌──────────────┐
│  CosySim     │ ──────────────────────────────────▶│  LMStudio    │
│  LMSClient   │◀────────────── SSE stream ─────────│  Server      │
├──────────────┤                                    ├──────────────┤
│  MCP Server  │◀─── tool calls (integrations) ─────│  MCP Host    │
│  (FastMCP)   │ ──── tool results ────────────────▶│              │
└──────────────┘                                    └──────────────┘
```

## API Coverage

| Endpoint | Method | Client Method |
|---|---|---|
| `/api/v1/chat` | POST | `chat()`, `chat_stateful()`, `chat_stream()`, `chat_stream_stateful()` |
| `/api/v1/models` | GET | `get_models()` → `List[LMSModel]` |
| `/api/v1/models/load` | POST | `load_model()` → `LMSLoadResult` |
| `/api/v1/models/unload` | POST | `unload_model()` |
| `/api/v1/models/download` | POST | `download_model()` → `LMSDownloadJob` |
| `/api/v1/models/download/status` | GET | `download_status()` → `LMSDownloadStatus` |

## LMSClient (v1 Native API)

The main client (`engine/lmstudio/lms_client.py`) uses LMStudio's native v1 endpoints:

```python
from engine.lmstudio import get_lms_client, InferenceConfig, MCP

client = get_lms_client()

# Simple chat
resp = client.quick_reply("Hello!")

# With full config control
cfg = InferenceConfig(temperature=0.3, max_output_tokens=2000, reasoning="on")
resp = client.chat(messages, config=cfg)

# Structured JSON output
resp = client.chat_structured(messages, {"type": "object", "properties": {...}})

# Streaming with typed events
for chunk in client.chat_stream(messages, on_event=my_handler):
    print(chunk, end="")
```

### Authentication

```python
# Via config (config/default.yaml → lmstudio.api_token)
client = get_lms_client()  # reads token from config

# Or explicit
client = LMSClient(api_token="lms-abc123...")
```

Bearer token is injected into all HTTP requests automatically.

### Stateful Conversations

```python
# Direct stateful API
resp1 = client.chat_stateful("Hello!", system="You are helpful.")
resp2 = client.chat_stateful("Tell me more.", previous_response_id=resp1.response_id)

# Via ConversationManager (recommended for scenes)
from engine.lmstudio import get_conversation_manager
conv = get_conversation_manager().create("aria_chat", system="You are Aria.")
resp = conv.send("Hello!")           # auto-tracks response_id
resp2 = conv.send("Tell me more.")   # reuses KV cache

# Branch at a previous turn
conv.branch_at(turn=1)
resp3 = conv.send("Actually, tell me something different.")
```

### Rich Model Listing

```python
models = client.get_models()  # List[LMSModel]
for m in models:
    print(f"{m.display_name} ({m.params_string})")
    print(f"  Publisher: {m.publisher}, Format: {m.format}")
    print(f"  Quantization: {m.quantization.name} ({m.quantization.bits_per_weight} bpw)")
    print(f"  Vision: {m.capabilities.vision}, Tool Use: {m.capabilities.trained_for_tool_use}")
    print(f"  Max context: {m.max_context_length}, Size: {m.size_bytes / 1e9:.1f} GB")

# Backward-compatible dict format
raw = client.get_models(raw=True)
```

### Model Lifecycle

```python
# Load with config
from engine.lmstudio import LoadConfig
result = client.load_model("qwen/qwen2.5-7b-instruct",
    config=LoadConfig(context_length=8192, flash_attention=True),
    echo_load_config=True)
print(f"Loaded in {result.load_time_seconds}s, config: {result.load_config}")

# Unload
client.unload_model("qwen/qwen2.5-7b-instruct")

# Download from catalog
job = client.download_model("ibm/granite-4-micro")
status = client.download_status(job.job_id)
print(f"Progress: {status.progress:.0%}, Speed: {status.bytes_per_second / 1e6:.1f} MB/s")
```

### Speculative Decoding

Load a main + draft model pair for 2-3x throughput:

```python
# Enable (loads both models)
main_r, draft_r = client.enable_speculative("qwen2.5-7b-instruct", "qwen2.5-0.5b-instruct")

# All subsequent chat calls automatically benefit from speculative decoding
resp = client.chat(messages)

# Or pass draft_model per-request via InferenceConfig
cfg = InferenceConfig(draft_model="qwen2.5-0.5b-instruct")
resp = client.chat(messages, config=cfg)

# Disable
client.disable_speculative("qwen2.5-0.5b-instruct")
```

### MCP Integrations

```python
# Ephemeral MCP server (defined per-request)
resp = client.chat(messages, integrations=[
    MCP.ephemeral("http://localhost:8700/mcp/sse",
        server_label="cosysim",
        allowed_tools=["get_state", "update_state"],
        headers={"X-Api-Key": "secret"}),
])

# Plugin from mcp.json
resp = client.chat(messages, integrations=[
    MCP.plugin("mcp/playwright", allowed_tools=["navigate", "click"]),
])
```

### Streaming Events

All 19 SSE event types are parsed:

| Category | Events |
|---|---|
| Chat lifecycle | `chat.start`, `chat.end` |
| Model loading | `model_load.start`, `model_load.progress`, `model_load.end` |
| Prompt processing | `prompt_processing.start`, `prompt_processing.progress`, `prompt_processing.end` |
| Reasoning | `reasoning.start`, `reasoning.delta`, `reasoning.end` |
| Tool calls | `tool_call.start`, `tool_call.arguments`, `tool_call.success`, `tool_call.failure` |
| Messages | `message.start`, `message.delta`, `message.end` |
| Errors | `error` |

## MCP Server

CosySim exposes its capabilities as an MCP server. Tool logic lives in `engine/mcp/tools/` (8 domain modules, 67 functions); wrappers in `engine/mcp/cosysim_server.py`:

### Tools (actions the LLM can execute)

| Tool | Description |
|------|-------------|
| `search_memory` | RAG vector search for character memories |
| `store_memory` | Persist text to ChromaDB |
| `get_character_state` | Get mood, energy, relationships |
| `adjust_relationship` | Modify trust/attraction between characters |
| `list_characters` | List all characters with IDs |
| `get_chain_events` | Browse EventChain events |
| `log_event` | Inject an event into a chain |
| `get_benchmark_stats` | Get timing KPIs |
| `generate_image_request` | Proxy to ComfyUI |
| `send_selfie` | ComfyUI image generation with display_hint |
| `send_voice_message` | TTS generation with structured response |
| `query_stateless` | Disposable store=False utility queries |
| `get_conversation_info` | Conversation state + forkable response_ids |
| `fork_conversation` | Create conversation branch at specific turn |

### Resources (data the LLM can read)

| URI | Description |
|-----|-------------|
| `config://cosysim` | Current YAML config snapshot |
| `benchmark://summary` | Timing KPIs as JSON |
| `character://{id}` | Full character profile + state |
| `chain://{chain_id}` | EventChain tree |
| `scene://{name}/status` | Scene health |

## Model Manager

The `ModelManager` (`engine/lmstudio/model_manager.py`) handles model lifecycle with three loading strategies:

| Strategy | Description | Best For |
|----------|-------------|----------|
| `CONCURRENT` | One model always loaded, N parallel requests | Multi-agent same-model |
| `JIT` | Load on demand, evict previous on next load | Sequential specialist workflows |
| `JIT_TTL` | Load on demand, auto-unload after idle timeout | Sporadic specialist calls |

```python
from engine.lmstudio.model_manager import get_model_manager, LoadMode

mgr = get_model_manager()
mgr.set_mode(LoadMode.JIT_TTL, ttl_seconds=300)
model_id = mgr.ensure_loaded("qwen3-8b")
# ... use model ...
mgr.release("qwen3-8b")
```

## Resource Manager

The `ResourceManager` (`engine/lmstudio/resource_manager.py`) extends ModelManager with six hardware-aware strategies tuned for the target platform (i9 NUC, RTX 2060 12GB):

| Strategy | GPU Models | CPU Models | Use Case |
|----------|-----------|------------|----------|
| `SINGLE_BIG` | 1 large (30B+) | 0 | Deep single-agent conversation |
| `CONCURRENT` | 1 medium (8B) | 0 | Multi-agent same-model |
| `MULTI_SMALL` | 2-3 small (3B) | 0 | Each agent gets own model |
| `JIT_SWAP` | 1 at a time | 0 | Sequential specialist |
| `SPECULATIVE` | 1 main + 1 draft | 0 | 2-3x speedup via spec decode |
| `HYBRID` | 1 interactive | 1 background | GPU for dialogue, CPU for batch |

## Inference Router

The `InferenceRouter` (`engine/lmstudio/router.py`) provides a three-tier priority queue:

```
submit(request) → Priority Queue → Tier Selection → Channel → Model
                   (heapq)         T1/T2/T3         SDK/REST
```

| Tier | Device | Model | Tasks |
|------|--------|-------|-------|
| T1 GPU Primary | GPU | Qwen3-8B | Dialogue, .act() tool calling, narration |
| T2 CPU Utility | CPU | Ministral-3B | Auto-texts, decisions, JSON output |
| T3 CPU Router | CPU | Gemma-270M (fine-tuned) | Tag extraction, routing, classification |

Priority levels: `REALTIME(0)` > `INTERACTIVE(1)` > `BACKGROUND(2)` > `BATCH(3)`

## Speculative Decoding

Use a small draft model to generate candidate tokens verified by the main model (1.5-2.5x speedup):

```python
client = get_lms_client()
client.enable_speculative("qwen3-8b", "qwen3-0.5b")

# For TTS: Qwen3-TTS 0.6B as draft for 1.7B (same-family, same tokenizer)
# Config: tts.speculative.enabled: true, tts.speculative.draft_model: "0.6b"
```

Monitor acceptance ratio via pipeline metrics: `accepted_draft_tokens_count` / `rejected_draft_tokens_count`.

## Conversation Branching

Response IDs enable server-side KV cache reuse and conversation branching:

```python
conv = get_conversation_manager().create("chat", system="You are helpful.")
resp1 = conv.send("Hello!")           # response_id = "r1"
resp2 = conv.send("Tell me more.")    # previous_response_id = "r1", response_id = "r2"

# Branch at turn 1 (reuses KV cache up to "r1")
conv.branch_at(turn=1)
resp3 = conv.send("Something else.")  # previous_response_id = "r1", new branch

# Fork creates an independent conversation copy
forked = conv.fork()

# Stateless query (no response_id tracking, store=False)
resp = conv.send_stateless("Quick question?")
```

Each `response_id` is tracked in `Conversation._response_id_history` for replay and undo.

## Configuration

In `config/default.yaml`:

```yaml
lmstudio:
  host: "127.0.0.1"
  port: 1234
  api_token: ""               # Bearer token (optional)
  mcp_enabled: true
  cosysim_mcp_url: "http://localhost:8700/mcp/sse"

  inference_defaults:
    temperature: 0.7
    top_p: 0.9
    top_k: 40
    min_p: 0.05
    repeat_penalty: 1.1
    max_output_tokens: 4000
    reasoning: false
    # draft_model: ""         # speculative decoding

  load_defaults:
    context_length: 4096
    gpu_offload: 0.9
    flash_attention: true
    eval_batch_size: 512
    keep_kv_cache_on_gpu: true

  speculative:
    enabled: false
    draft_model: ""           # small fast model for draft tokens
```

### LMStudio Settings Required

Enable these in LMStudio:
1. **Allow per-request MCPs** — Settings → MCP
2. **Allow calling servers from mcp.json** — Settings → MCP
3. **Enable CORS** — Settings → Network
