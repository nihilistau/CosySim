# LMStudio Integration Guide

CosySim implements the **complete LMStudio v1 REST API** for local LLM inference. This guide covers all endpoints, MCP integration, streaming, speculative decoding, and configuration.

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

CosySim exposes its capabilities as an MCP server (`engine/mcp/cosysim_server.py`):

### Tools (actions the LLM can execute)

| Tool | Description |
|------|-------------|
| `search_memory` | RAG vector search for character memories |
| `store_memory` | Persist text to ChromaDB |
| `get_character_state` | Get mood, energy, relationships |
| `adjust_relationship` | Modify trust/attraction between characters |
| `get_chain_events` | Browse EventChain events |
| `log_event` | Inject an event into a chain |
| `list_characters` | List all characters with IDs |
| `get_benchmark_stats` | Get timing KPIs |
| `generate_image_request` | Proxy to ComfyUI |

### Resources (data the LLM can read)

| URI | Description |
|-----|-------------|
| `config://cosysim` | Current YAML config snapshot |
| `benchmark://summary` | Timing KPIs as JSON |
| `character://{id}` | Full character profile + state |
| `chain://{chain_id}` | EventChain tree |
| `scene://{name}/status` | Scene health |

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
