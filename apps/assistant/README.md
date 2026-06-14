# CosySim Advanced Assistant

Standalone AI chat interface with 80+ models, conversation branching, model comparison, prompt playground, prompt caching, user authentication, and training dashboard.

## Quick Start

```bash
python apps/assistant/run.py
```

Open http://localhost:5593 in your browser.

## Features

### Core
- **80+ models** — 19 via GitHub Copilot (Claude, GPT-5, Gemini, Grok), 60+ local via LMStudio, NotebookLM grounded research
- **Token-by-token streaming** — real-time responses via SocketIO (Copilot + LMStudio)
- **File upload** — drag-drop images, PDFs, code files with text extraction
- **Conversation persistence** — SQLite, survives restarts
- **OpenAI-compatible API** — connect aider, Continue, Cursor, Open Interpreter

### Advanced
- **Conversation branching** — fork from any message to explore alternate paths
- **Side-by-side model comparison** — send same prompt to 2 models, compare responses
- **Prompt playground** — direct model testing without saving (adjustable system prompt, temperature)
- **Prompt caching** — SQLite-backed response cache with TTL, avoids redundant LLM calls
- **User authentication** — session-based login/register with PBKDF2 password hashing (optional)
- **Training dashboard** — monitor datasets, model registry, benchmarks, fine-tune jobs

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
GET  /v1/models                    → List all models (80+)
POST /v1/chat/completions          → Chat (streaming & non-streaming)
GET  /health                       → Service health
```

### Internal API (for the web UI)

```
Conversations:
GET    /api/conversations           → List conversations
POST   /api/conversations           → Create conversation
GET    /api/conversations/:id       → Get conversation + messages
PATCH  /api/conversations/:id       → Update title/model
DELETE /api/conversations/:id       → Delete conversation
POST   /api/conversations/:id/fork  → Fork from a message (branching)

Chat:
POST   /api/chat                    → Non-streaming chat
POST   /api/compare                 → Side-by-side model comparison

Models & Providers:
GET    /api/models                  → All models with backend info
GET    /api/providers               → Backend status (online/offline)

Files:
POST   /api/upload                  → File upload (images, PDF, text)

Settings:
GET    /api/settings                → User settings
PUT    /api/settings                → Update settings

Cache:
GET    /api/cache/stats             → Cache hit/miss statistics
POST   /api/cache/clear             → Clear cached responses

Training:
GET    /api/training/status         → Auto-train daemon status + dataset counts
GET    /api/training/models         → Model registry (all trained versions)
GET    /api/training/benchmarks     → Latest benchmark scores
GET    /api/training/jobs           → Fine-tune job history
GET    /api/training/datasets       → Detailed dataset info with sizes

Auth:
GET    /auth/login                  → Login page
POST   /auth/login                  → Submit login
GET    /auth/register               → Register page
POST   /auth/register               → Submit registration
GET    /auth/logout                 → Logout
GET    /auth/me                     → Current user info
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

| Vendor | Models | Backend |
|--------|--------|---------|
| Anthropic | claude-opus-4.6, claude-sonnet-4.6, claude-haiku-4.5, claude-opus-4.5 | Copilot |
| OpenAI | gpt-5.4, gpt-5.4-mini, gpt-5.3-codex, gpt-5.2, gpt-5.1 | Copilot |
| Google | gemini-3.1-pro, gemini-3-flash | Copilot |
| Google | nlm (NotebookLM grounded research) | NLM SDK |
| xAI | grok-code-fast-1 | Copilot |
| Local | Any model loaded in LMStudio (60+ available) | LMStudio |

## Configuration

| Flag | Default | Description |
|------|---------|-------------|
| `--port` | 5593 | Server port |
| `--host` | 0.0.0.0 | Bind host |
| `--debug` | false | Debug mode |

Settings are persisted in `data/conversations.db` and editable via the UI settings panel.

## Architecture

```
apps/assistant/
├── run.py                         ← python apps/assistant/run.py
├── app.py                         ← Flask + SocketIO factory
├── config.py                      ← Port 5593, defaults, model registry
├── models.py                      ← SQLite (conversations, messages, settings, users)
├── routes/
│   ├── views.py                   ← GET / → index.html
│   ├── api.py                     ← /api/* + SocketIO streaming
│   ├── openai_compat.py           ← /v1/chat/completions, /v1/models
│   ├── auth.py                    ← Login/register/logout
│   └── training.py                ← Training dashboard API
├── services/
│   ├── router.py                  ← Model resolution + 3-backend dispatch
│   ├── streaming.py               ← SocketIO + SSE format converters
│   ├── cache.py                   ← Prompt response cache (SQLite + TTL)
│   └── file_handler.py            ← Upload processing
├── templates/
│   └── index.html                 ← SPA with chat, compare, playground modals
├── static/
│   ├── css/assistant.css          ← Neon theme on CosySim design tokens
│   └── js/assistant.js            ← Vanilla JS (600+ lines)
└── data/
    ├── conversations.db           ← SQLite persistence
    └── uploads/                   ← Uploaded files
```
