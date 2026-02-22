# LMStudio Integration Guide

CosySim integrates deeply with LMStudio for local LLM inference. This guide covers the REST client, MCP bridge, streaming, and configuration.

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

## LMSClient (v1 Native API)

The main client (`engine/lmstudio/lms_client.py`) uses LMStudio's native `/api/v1/chat` endpoint:

```python
from engine.lmstudio.lms_client import LMSClient

client = LMSClient()

# Stateful chat (server-side KV cache)
result = client.chat_stateful(
    messages=[{"role": "user", "content": "Hello!"}],
    system_prompt="You are helpful.",
    store=True,  # persist conversation server-side
)
print(result.text)
print(result.response_id)       # for threading
print(result.stats)             # tokens, timing

# Stateless one-off query
result = client.send_stateless(
    messages=[{"role": "user", "content": "What is 2+2?"}],
    system_prompt="Answer briefly.",
)

# Streaming with SSE events
for event in client.chat_stream(messages, system_prompt="..."):
    if event.type == "message.delta":
        print(event.data.get("content", ""), end="")
```

### v1 API Format

LMStudio v1 uses `input` + `system_prompt`, NOT OpenAI's `messages` array:

```json
{
  "input": "Hello!",
  "system_prompt": "You are helpful.",
  "model": "loaded-model-id",
  "store": true,
  "previous_response_id": "resp_abc123"
}
```

The client handles conversion from standard `messages` format to v1 `input` automatically.

### Stateful Conversations

```python
from engine.lmstudio.conversation import Conversation

conv = Conversation(client)

# First message
resp1 = conv.send("Hello!")
# resp1.response_id is tracked automatically

# Continuation (uses previous_response_id for KV cache reuse)
resp2 = conv.send("Tell me more.")

# Branch at a previous turn
conv.branch_at(turn=1)  # fork from resp1
resp3 = conv.send("Actually, tell me something different.")

# Stateless side-query (doesn't affect conversation history)
result = conv.send_stateless("Quick question: what time is it?")
```

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

The `CharacterAgent` routes all inference through `VirtualAgentManager`, which
uses `LMSClient` (v1 native API) with MCP tool integration:

```python
from engine.agents.character_agent import CharacterAgent

agent = CharacterAgent(character)
reply = agent.reply("Hello!")
# → VirtualAgentManager → LMSClient.chat_stateful() → LMStudio /api/v1/chat
```

Skills are attached as tools automatically based on the agent's skill packs.
The `AgentGovernor` wraps inference with pre/post interceptors for content
filtering, mood sync, and stat updates.

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
