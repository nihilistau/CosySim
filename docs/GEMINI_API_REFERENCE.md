# Gemini API Reference (BardChatUi — Reverse Engineered)

> Derived from V8 heap snapshot analysis + HAR network capture (March 2026).
> Service: `BardChatUi` at `https://gemini.google.com`

---

## Protocol

Same batchexecute protocol as NotebookLM:

```
POST https://gemini.google.com/_/BardChatUi/data/batchexecute
Content-Type: application/x-www-form-urlencoded

f.req=[[["RPCID","[[PAYLOAD]]",null,"generic"]]]&bl=boq_assistant-bard-web-server_...
```

Response prefix is `)]}'\n` then streaming JSON frames (`wrb.fr` with `n` field).

---

## Auth

Requires Google session cookies:
- `__Secure-1PSID`, `__Secure-3PSID`, `SAPISID`, `SID`, `HSID`, `SSID`, `APISID`, `OSID`
- Same cookie pool as NLM and AI Studio

No API key needed for batchexecute. API key used for gRPC-web calls.

---

## Streaming API (BardFrontendService)

```
POST /_/BardChatUi/data/assistant.lamda.BardFrontendService/StreamGenerate
```

Methods:
| Method | Purpose |
|--------|---------|
| `StreamGenerate` | Main streaming conversation generation |
| `GetTtsStream` | TTS audio output stream |
| `ProcessFile` | File upload + processing |

---

## batchexecute rpcids (17 confirmed)

### `otAQ7b` — GetModels

Returns available Gemini models with internal IDs.

```python
payload = "[]"
# Response: [[["56fdd199312815e2","Fast",...],["e051ce1aa80aa576","Thinking",...],...]]
```

Known model internal IDs:
| ID | Name |
|----|------|
| `56fdd199312815e2` | Gemini Fast (Flash) |
| `e051ce1aa80aa576` | Gemini Thinking |

---

### `K4WWud` — GetUserLocation

```python
payload = '[[1],["en-AU"]]'
# Response: [[city, SWML_key, bool, null, google_maps_tile_data_url]]
```

---

### `ozz5Z` — GetFeatureFlags

```python
payload = "[[[null,\"1\",447],[null,\"1\",448],[null,\"1\",702],...]]"
# Returns same list with enabled/disabled status per feature ID
# Known IDs: 447, 448, 702, 961, 960, 1062
```

---

### `CNgdBe` — ListConversations

Returns all user chat history with system prompts and theme data.

```python
payload = '[1,["en-AU"],0]'
# Response:
# [null, null, [[
#   conv_id,
#   [title, "", null, null, null, null, ["", null, null, theme_id], bool, bool, [], [], turn_count, null, bool],
#   system_prompt
# ], ...]]
```

---

### `GPRiHf` — Initialize (ping)

```python
payload = "[]"
# Response: []
```

---

### `maGuAc` — Acknowledge / MarkRead

```python
payload = "[1]"
# Response: []
```

---

### `ESY5D` — GetUserSettings

```python
payload = '[[[\"bard_activity_enabled\"]]]'
# Response: [[null, null, null, null, true]]
# Settings are keyed by string name
```

---

### `MaZiqc` — GenerateSessionToken

```python
payload = "[13,null,[0,null,1]]"
# Response: [null, "LONG_BASE64_SESSION_TOKEN"]
```

---

### `aPya6c` — GetConversationState

```python
payload = "[]"
# Response: [false, 0, []]
```

---

### `cYRIkd` — ListExtensions

```python
payload = '["en-AU"]'
# Response: [[[[ext_id], display_name, icon_url, ...]]]
# Known extensions: google_calendar_2, google_workspace, youtube,
#                   google_flights, google_hotels, google_maps
```

---

### `qpEbW` — GetUsageQuota

```python
payload = "[[[1,4],[6,6],[1,15]]]"
# Response:
# [[[[quota_type,...], 1, used_count, [timestamp_s, timestamp_ns], limit, remaining], ...], session_id]
```

---

### `o30O0e` — GetUserProfile

Proxy to Google People API. Returns Google account ID.

```python
payload = '[[\"me\"],[[people_fields], null, [1, 7]]]'
# Response: [["me", 1, [google_user_id, ...]]]
# google_user_id example: "101377838414306824456"
```

---

### `DYBcR` — Unknown

```python
payload = '["en-AU"]'
# Response: (empty) — purpose not confirmed
```

---

### `L5adhe` — InitConversation

```python
payload = "[null, null, null, ..., null, null, null, null, null, null, null, null, 4]"
# Response: [1]
```

---

### `ku4Jyf` — GetStarterPrompts

Returns localized example prompts shown in the UI.

```python
payload = '["en-AU", null, null, null, 4, null, null, [2,4,7,19], null, []]'
# Response: [[[[title, null, full_prompt, lang, [category_ids], prompt_id, 1, ...]]]]
```

---

### `PCck7e` — DeleteConversation

```python
payload = '["r_CONVERSATION_ID"]'
# Response: []
```

---

### `NXpLKc` — ListLinkedNotebooks ⭐

**This is the Gemini↔NotebookLM bridge.** Returns ALL NLM notebooks associated with the account.

```python
payload = "[]"
# Response:
# [[["notebooks/UUID", title, [timestamp_s, timestamp_ns], source_count], ...]]
```

Example notebooks discovered:
| UUID | Title | Sources |
|------|-------|---------|
| `603976db-...` | V8 Heap Forensics | 41 |
| `50170774-...` | Game Lore-Lovecraft-Egypt | 52 |
| `26486368-...` | NotebookLM Best Practices | 33 |
| `311f2b2e-...` | CosySim AI Simulation Framework Index | 7 |
| `3b5dbaa9-...` | Colab Skool | 10 |

---

## Model Registry (from AI Studio ListModels)

Confirmed Gemini models (March 2026):

| Model | Context | Output | Notes |
|-------|---------|--------|-------|
| `gemini-3.1-pro-preview` | 1M | 65K | Latest unreleased |
| `gemini-3.1-flash-image-preview` | 65K | 65K | Multimodal |
| `gemini-3.1-flash-lite-preview` | 1M | 65K | Lite variant |
| `gemini-3-pro-preview` | 1M | 65K | — |
| `gemini-3-pro-image-preview` | 131K | 32K | Image-capable |
| `gemini-3-flash-preview` | 1M | 65K | Used in ProxyUnaryCall |
| `gemini-2.5-pro` | 1M | 65K | — |
| `gemini-2.5-flash` | 1M | 65K | — |
| `gemini-2.5-flash-preview-tts` | 8K | 16K | TTS |
| `gemini-2.5-pro-preview-tts` | 8K | 16K | TTS |
| `gemini-2.0-flash` | 1M | 8K | — |
| `gemini-robotics-er-1.5-preview` | 1M | 65K | Robotics |
| `nano-banana` | — | — | Internal codename |
| `nano-banana-pro` | — | — | Internal codename |
| `imagen-4.0-generate-001` | 480 | 8K | Image generation |
| `imagen-4.0-ultra-generate-001` | 480 | 8K | HQ image |
| `imagen-4.0-fast-generate-001` | 480 | 8K | Fast image |
| `veo-3.1-generate-preview` | 480 | 8K | Video generation |
| `veo-3.1-fast-generate-preview` | 480 | 8K | Fast video |
| `veo-2.0-generate-001` | 480 | 8K | Stable video |

---

## Thought Signatures

The `gemini-3-flash-preview` ProxyUnaryCall response confirmed the extended thinking feature:

```json
{
  "candidates": [{
    "content": {
      "parts": [{
        "text": "response...",
        "thoughtSignature": "EqICCp8CAb4+9vv/WY..."
      }]
    }
  }],
  "usageMetadata": {
    "promptTokenCount": 2,
    "candidatesTokenCount": 9,
    "thoughtsTokenCount": 64,
    "totalTokenCount": 75
  },
  "modelVersion": "gemini-3-flash-preview"
}
```

`thoughtSignature` is an opaque base64-encoded protobuf blob. Encoded reasoning tokens.

---

## CosySim Integration

See `engine/integrations/gemini_direct_client.py` for the Python client.

Key use cases via `NXpLKc`:
1. List all NLM notebooks from Gemini session — no NLM HAR needed
2. Route queries to the correct NLM notebook by content type
3. Monitor notebook source counts for drift detection

See also: `docs/NLM_API_REFERENCE.md`, `docs/AISTUDIO_API_REFERENCE.md`
