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
```
