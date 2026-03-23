# CosySim Advanced Assistant

Standalone AI chat interface with 38+ frontier models, file upload, conversation persistence, and OpenAI-compatible API.

## Quick Start

```bash
python apps/assistant/run.py
```

Open http://localhost:5593 in your browser.

## Features

- **38+ frontier models** via GitHub Copilot (Claude, GPT-5, Gemini, Grok)
- **Local models** via LMStudio (any loaded model)
- **NotebookLM** grounded research (Gemini with source citations)
- **File upload** — drag-drop images, PDFs, code files
- **Conversation persistence** — SQLite, survives restarts
- **Streaming responses** via SocketIO
- **OpenAI-compatible API** — connect aider, Continue, Cursor, Open Interpreter
- **Settings** — temperature, max tokens, system prompt, default model

## Connect External Tools

Point any OpenAI-compatible tool at:

```
Base URL:  http://localhost:5593/v1
API Key:   anything (not checked)
Model:     claude-opus-4.6 (or any model from /v1/models)
```

### aider
```bash
aider --openai-api-base http://localhost:5593/v1 --openai-api-key dummy --model claude-opus-4.6
```

### Continue (VS Code)
```json
{
  "models": [{
    "title": "CosySim",
    "provider": "openai",
    "model": "claude-opus-4.6",
    "apiBase": "http://localhost:5593/v1",
    "apiKey": "dummy"
  }]
}
```

## API Reference

### OpenAI-Compatible (for external tools)

```
GET  /v1/models                    → List all models
POST /v1/chat/completions          → Chat (streaming & non-streaming)
GET  /health                       → Service health
```

### Internal API (for the web UI)

```
GET    /api/conversations           → List conversations
POST   /api/conversations           → Create conversation
GET    /api/conversations/:id       → Get conversation + messages
PATCH  /api/conversations/:id       → Update title/model
DELETE /api/conversations/:id       → Delete conversation
POST   /api/chat                    → Non-streaming chat
POST   /api/upload                  → File upload
GET    /api/models                  → All models with backend info
GET    /api/providers               → Backend status (online/offline)
GET    /api/settings                → User settings
PUT    /api/settings                → Update settings
```

### SocketIO Events

```
Client → Server:
  send_message    {conversation_id, content, model}
  stop_generation {}

Server → Client:
  chat_delta      {content, conversation_id, done: false}
  chat_complete   {conversation_id, model, full_content, done: true}
  chat_error      {conversation_id, error}
  conversation_created {id, title, model}
```

## Available Models

| Vendor | Models |
|--------|--------|
| Anthropic | claude-opus-4.6, claude-sonnet-4.6, claude-haiku-4.5, claude-opus-4.5 |
| OpenAI | gpt-5.4, gpt-5.4-mini, gpt-5.3-codex, gpt-5.2, gpt-5.1 |
| Google | gemini-3.1-pro, gemini-3-flash, nlm (NotebookLM grounded) |
| xAI | grok-code-fast-1 |
| Local | Any model loaded in LMStudio |

## Configuration

| Flag | Default | Description |
|------|---------|-------------|
| `--port` | 5593 | Server port |
| `--host` | 0.0.0.0 | Bind host |
| `--debug` | false | Debug mode |

Settings are persisted in `data/conversations.db` and editable via the UI settings panel.
