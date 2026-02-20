# LMStudio Integration Guide

CosySim integrates deeply with LMStudio for local LLM inference. This guide covers the REST client, MCP bridge, streaming, and configuration.

## Architecture

```
┌──────────────┐     REST /v1/chat/completions     ┌──────────────┐
│  CosySim     │ ──────────────────────────────────▶│  LMStudio    │
│  client_v2   │◀────────────── SSE stream ─────────│  Server      │
├──────────────┤                                    ├──────────────┤
│  MCP Server  │◀─── tool calls (integrations) ─────│  MCP Host    │
│  (FastMCP)   │ ──── tool results ────────────────▶│              │
└──────────────┘                                    └──────────────┘
```

## Client v2 (REST)

The REST client (`engine/lmstudio/client_v2.py`) talks directly to LMStudio's `/v1/chat/completions` endpoint:

```python
from engine.lmstudio.client_v2 import LMStudioClient, MCP

client = LMStudioClient()

# Simple chat
reply = client.chat([
    {"role": "system", "content": "You are helpful."},
    {"role": "user", "content": "Hello!"},
])
print(reply.content)       # "Hi there!"
print(reply.tokens_per_second)  # 42.5
print(reply.latency_ms)         # 350.2

# Chat with MCP tools attached
reply = client.chat(messages, integrations=[
    MCP.plugin("mcp/cosysim"),               # pre-registered in mcp.json
    MCP.ephemeral("http://localhost:8600/mcp/sse"),  # on-the-fly
])

# Streaming
for chunk in client.chat_stream(messages):
    print(chunk.delta, end="", flush=True)
```

### Why REST instead of SDK?

The LMStudio Python SDK (`lmstudio` package) uses WebSockets and does **not** support the `integrations` field needed for per-request MCP. The REST client gives us:

- **Per-request MCP** via `integrations` field
- **SSE streaming** with first-token timing
- **Abort support** (close connection → stop generation)
- **Token counting** in responses

The original `LMStudioManager` (SDK-based) is still used for model lifecycle (load/unload/VRAM).

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

### Running the MCP Server

```bash
# Stdio mode (for mcp.json registration)
python -m engine.mcp.cosysim_server

# HTTP/SSE mode (for web bridge)
python -m engine.mcp.cosysim_server --http
```

## Web Bridge

The web bridge (`engine/mcp/web_bridge.py`) is a FastAPI server that:

1. **Proxies** LMStudio chat requests with SSE streaming
2. **Mounts** the CosySim MCP server at `/mcp`
3. Handles **file uploads** for MCP resource exposure
4. Supports **abort** (client disconnect stops generation)

```bash
python launcher.py --mode bridge  # port 8601
```

### Endpoints

| Method | Path | Description |
|--------|------|-------------|
| GET | `/api/health` | Bridge + LMStudio status |
| POST | `/api/chat` | Non-streaming proxy |
| POST | `/api/chat/stream` | SSE streaming proxy |
| POST | `/api/upload` | File upload |

## CharacterAgent MCP Mode

The `CharacterAgent` supports dual-path inference:

```python
from engine.agents.character_agent import CharacterAgent

# SDK path (default)
agent = CharacterAgent(character)

# REST + MCP path
agent = CharacterAgent(
    character,
    use_mcp=True,
    mcp_servers=[MCP.plugin("mcp/cosysim")],
)
```

When `use_mcp=True`:
- Uses REST client v2 instead of SDK
- Attaches MCP integrations to each request
- Logs `mcp_tool_call` events to EventChain
- Falls back to SDK on connection failure

## Configuration

In `config/default.yaml`:

```yaml
lmstudio:
  host: "127.0.0.1"
  port: 1234
  api_version: "v1"
  mcp_enabled: false          # Enable per-request MCP
  cosysim_mcp_url: ""         # CosySim MCP server URL
  mcp_json_path: ""           # LMStudio mcp.json path
```

### LMStudio Settings Required

Enable these in LMStudio:
1. **Allow per-request MCPs** — Settings → MCP
2. **Allow calling servers from mcp.json** — Settings → MCP
3. **Enable CORS** — Settings → Network
