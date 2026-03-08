---
description: 'CosySim LMStudio integration patterns — v1 API, stateful conversations, SSE streaming, model routing'
applyTo: 'engine/lmstudio/**/*.py'
---

# LMStudio Integration Patterns

## API Version
- LMStudio v1 API at `http://localhost:1234`
- Use `/api/v1/chat` endpoint for inference

## Input Format (CRITICAL)
Input items MUST use: `{"type": "text", "text": "..."}` or `{"type": "image", "data_url": "..."}`
NOT `{"type": "message", "content": "..."}` — input/output formats are asymmetric.

## Stateful Conversations
- `store: true` + `previous_response_id` for conversation threading
- Track `_response_id_history` for branching support
- `branch_at(turn)` forks using recorded response_id
- `send_stateless()` uses `store: false` for one-off queries

## SSE Streaming
LMStudio v1 uses `event: <type>\ndata: <json>` format (NOT OpenAI-style).
Parse `event:` line first for type, then `data:` line for JSON.

Event types: `chat.start`, `chat.end`, `model_load.*`, `reasoning.delta`,
`message.delta`, `tool_call.*`, `error`

## Model Profiles (from config)
- `big` — 70B models for complex reasoning (high context, high tokens)
- `small` — 9B models for fast responses
- `router` — 270M model for request classification
- `draft` — speculative decoding draft model

## Conversation Management
- `infer_stream()` creates conversations via `conv_mgr.create()` on first call
- Updates `response_id` after streaming completes
- `infer_processed()` captures generator return via StopIteration pattern

## LMLink (Multi-Instance Federation)
LMLink connects multiple LMStudio instances (local or remote via Tailscale).
The "client" instance can load and use remote models as if they were local.

```yaml
lmstudio:
  lmlink:
    enabled: true
    peers:
      - name: nuc
        host: 100.x.x.x    # Tailscale IP
        port: 1234
        capabilities: [inference]
        max_models: 2
```

- Remote models appear in `GET /api/v1/models` alongside local ones
- Use `model` field in chat requests to target specific remote models
- Failover: if remote peer is down, skip gracefully

## Vision Models
LMStudio supports vision models (Qwen2-VL, LLaVA, etc.) for image understanding.

```python
# Vision inference with image
response = requests.post(f"{base_url}/api/v1/chat", json={
    "model": "qwen2-vl-7b",
    "input": [
        {"type": "text", "text": "What do you see in this screenshot?"},
        {"type": "image", "data_url": f"data:image/png;base64,{b64_image}"}
    ],
    "max_tokens": 1000
})
```

Use cases: screen-to-text, UI analysis, automated browser task verification,
document understanding, screenshot-based debugging.

## Bearer Authentication
LMStudio requires a bearer token for API access:
```python
headers = {"Authorization": f"Bearer {config.get('lmstudio.api_token')}"}
```
Token stored in config, never hardcoded.

## Task Delegation
```python
from engine.nexus.lms_task_bridge import LMSTaskBridge
bridge = LMSTaskBridge()

# Quick inference
result = bridge.run_prompt("Summarize this", model="qwen3-0.6b")

# Batch evaluation
results = bridge.run_batch([
    {"prompt": "Variation 1", "temperature": 0.3},
    {"prompt": "Variation 2", "temperature": 0.9},
], store_results=True)

# Structured task
result = bridge.run_task("evaluate", "Rate this dialog", store_result=True)
```

## Configuration Keys
```yaml
lmstudio:
  host: localhost
  port: 1234
  vram_cap_mb: 11500
  concurrent_slots: 2
  load_mode: jit          # jit | preload | manual
  mcp_enabled: true
  mcp_json_path: config/mcp.json
  lmlink:
    enabled: false
    peers: []
```
