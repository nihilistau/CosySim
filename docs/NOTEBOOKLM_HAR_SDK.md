# NotebookLM HAR Extraction — Complete SDK/API Reference

> **Version:** 1.0.0  
> **Author:** Ray Daniels + Copilot  
> **Date:** 2026-02-26  
> **Status:** Production-ready extraction methodology  
> **HAR Source:** Google NotebookLM (`notebooklm.google.com`)

---

## Table of Contents

1. [Overview](#1-overview)
2. [Why HAR? Authentication Problem Space](#2-why-har-authentication-problem-space)
3. [Capturing a HAR File](#3-capturing-a-har-file)
4. [HAR File Anatomy](#4-har-file-anatomy)
5. [Google Batchexecute Protocol](#5-google-batchexecute-protocol)
6. [Response Encoding Pipeline](#6-response-encoding-pipeline)
7. [RPC Endpoint Reference](#7-rpc-endpoint-reference)
8. [Data Structure Reference](#8-data-structure-reference)
9. [Streaming Responses](#9-streaming-responses)
10. [Complete Extraction Script](#10-complete-extraction-script)
11. [Working with Extracted Data](#11-working-with-extracted-data)
12. [Modification Guide](#12-modification-guide)
13. [Troubleshooting](#13-troubleshooting)
14. [Appendix: Raw Protocol Examples](#14-appendix-raw-protocol-examples)

---

## 1. Overview

### What This Is

A complete reverse-engineered SDK for extracting **all content** from Google NotebookLM
notebooks using HTTP Archive (HAR) files captured from browser DevTools. This bypasses
all authentication challenges by using the browser's own authenticated session.

### What You Can Extract

| Content Type | RPC Endpoint | Description |
|:---|:---|:---|
| **Notebook metadata** | `VfAZjd` | Name, ID, summary, guide text |
| **Source documents** | `wXbhsf` | All uploaded sources with titles, UUIDs, URLs, word counts |
| **Source content** | `e3bVqc` | Full text of every source document in the notebook |
| **Notes/Blueprints** | `gArtLc` | User-created and AI-generated notes with source attributions |
| **Q&A conversations** | `cFji9` | All chat history — questions and AI responses |
| **Conversation threads** | `khqZz` | Full conversation with pagination |
| **Generated reports** | `GenerateFreeFormStreamed` | Tailored reports, deep dives, summaries |
| **Notebook list** | `ub2Bae` | All notebooks visible to the account |
| **User preferences** | `rLM1Ne` | Notebook-level settings and configuration |
| **Audio overview** | `ozz5Z` | Audio overview metadata (podcast-style) |

### Discovery Story

This methodology was discovered during Sprint 14 of CosySim when attempting to extract
content from a NotebookLM notebook (ID: `04168cf3-04a0-46bb-ba58-fec66458aab9`) titled
"Finetune Gemma3 270m". Multiple authentication approaches failed:

1. **NLM MCP HTTP server** (`@roomi-fields/notebooklm-mcp@1.5.3`) — required browser auth
2. **Patchright Chromium** — doesn't support WebAuthn/FIDO2 passkeys
3. **Chrome cookie copy** — Chrome encrypts cookies with per-instance DPAPI keys
4. **Archived Python skill** (`channel="chrome"`) — conflicts with running Chrome instances

The HAR approach was discovered when the user captured network traffic from their
authenticated browser session, providing a complete snapshot of all notebook data
without any authentication requirements.

---

## 2. Why HAR? Authentication Problem Space

### The NotebookLM Authentication Wall

NotebookLM is a Google-authenticated web application with no public API. To access
notebook data programmatically, you must either:

1. Automate a browser with valid Google credentials (blocked by passkeys/2FA)
2. Inject authenticated cookies (blocked by Chrome's DPAPI encryption)
3. Use an already-authenticated session (HAR capture)

### Why Other Methods Fail

| Method | Failure Point |
|:---|:---|
| `@roomi-fields/notebooklm-mcp` | Uses Patchright Chromium which lacks WebAuthn support |
| Cookie copy while Chrome running | Chrome holds exclusive lock on SQLite Cookies DB |
| Cookie copy after closing Chrome | Chrome encrypts cookie values with DPAPI per-instance keys |
| `esentutl /y` (VSS copy) | JET_errFileAccessDenied on Windows |
| Win32 `CreateFileW` with `FILE_SHARE_ALL` | Error 32 — sharing violation |
| Patchright `channel="chrome"` | Conflicts with existing Chrome process tree |

### Why HAR Works

A HAR file is a complete record of HTTP transactions captured by the browser's own
DevTools Network panel. It contains:

- All request/response headers (including auth cookies)
- All response bodies (the actual data)
- Timing information

Since the browser was already authenticated, the HAR contains the full authenticated
responses — no cookies, tokens, or login flow needed.

---

## 3. Capturing a HAR File

### Step-by-Step

1. **Open Chrome DevTools**: `F12` or `Ctrl+Shift+I`
2. **Go to Network tab**
3. **Navigate to your notebook**: `https://notebooklm.google.com/notebook/{id}`
4. **Wait for full page load** — watch the network waterfall complete
5. **Interact with the notebook** — open notes, run queries, generate reports
   (every interaction captures more data)
6. **Right-click in the Network panel** → "Save all as HAR with content"
7. **Save the `.har` file** — it will be large (10–100MB+)

### Maximizing Data Capture

To capture the most content in a single HAR:

- **Open the notebook** — captures source listing, summary, notes
- **Click each note** — loads full note content
- **Ask a question in chat** — captures Q&A response
- **Generate a report** — captures full generated content
- **Scroll through chat history** — loads paginated conversations
- **Switch between notebooks** — captures notebook list

### HAR File Sizes (Typical)

| Notebook Size | Sources | HAR Size |
|:---|:---|:---|
| Small (5 sources) | Short articles | 10–20 MB |
| Medium (20 sources) | Mixed docs | 30–60 MB |
| Large (50+ sources) | Long technical docs | 60–150 MB |

The HAR from our reference notebook (78 sources, "Finetune Gemma3 270m") was **55.9 MB**
with 223 HTTP entries.

---

## 4. HAR File Anatomy

### Top-Level Structure

```json
{
  "log": {
    "version": "1.2",
    "creator": { "name": "WebInspector", "version": "537.36" },
    "pages": [...],
    "entries": [
      {
        "startedDateTime": "2026-02-26T12:00:00.000Z",
        "request": {
          "method": "POST",
          "url": "https://notebooklm.google.com/_/LabsTailwindUi/data/batchexecute?...",
          "headers": [...],
          "postData": { "mimeType": "application/x-www-form-urlencoded", "text": "f.req=..." }
        },
        "response": {
          "status": 200,
          "content": {
            "size": 211184,
            "mimeType": "application/json",
            "text": "...",          // ← The payload
            "encoding": "base64"    // ← May be base64-encoded by HAR export
          }
        }
      }
    ]
  }
}
```

### Entry Categories

In a typical NotebookLM HAR (223 entries), the breakdown is:

| Category | Count | Description |
|:---|:---|:---|
| **Batchexecute RPCs** | 17 | Actual notebook data (THE GOOD STUFF) |
| **Favicon requests** | ~120 | Source website favicons (ignore) |
| **Static assets** | ~30 | JS, CSS, animations (ignore) |
| **Analytics** | ~10 | Google Analytics, GTM (ignore) |
| **Signaler/push** | ~5 | Real-time notification channels (ignore) |
| **Fonts** | ~5 | Google Fonts (ignore) |

**You only care about the 17 batchexecute entries.** Filter by URL containing
`batchexecute` or `google.internal.labs.tailwind`.

---

## 5. Google Batchexecute Protocol

### Overview

Google uses a proprietary RPC protocol called **batchexecute** for all NotebookLM
data operations. It's the same protocol used across Google products (Maps, Drive,
Photos, etc.).

### Endpoint URL

```
POST https://notebooklm.google.com/_/LabsTailwindUi/data/batchexecute?rpcids={RPC_ID}&source-path=/notebook/{NOTEBOOK_ID}&...
```

For streaming responses (generated reports):
```
POST https://notebooklm.google.com/_/LabsTailwindUi/data/google.internal.labs.tailwind.orchestration.v1.LabsTailwindService/GenerateFreeFormStreamed?...
```

### Request Format

The request body is `application/x-www-form-urlencoded` with a single parameter `f.req`
containing a JSON array:

```
f.req=[["RPC_ID","ESCAPED_JSON_ARGS",null,"generic"]]
```

Example (fetch notebook summary):
```
f.req=[[["VfAZjd","[\"04168cf3-04a0-46bb-ba58-fec66458aab9\",[2]]",null,"generic"]]]
```

**Structure breakdown:**

```
[
  [                           // ← Batch array (can contain multiple RPCs)
    [
      "VfAZjd",              // ← RPC ID (function name)
      "[\"notebook_id\",[2]]", // ← Arguments (JSON string, escaped)
      null,                   // ← Reserved
      "generic"               // ← Response format hint
    ]
  ]
]
```

### Response Format — The Decoding Pipeline

Responses go through up to **4 layers** of encoding:

```
Layer 1: HAR base64 encoding (optional — depends on content size)
    ↓
Layer 2: XSSI prefix stripping  →  )]}'\n\n
    ↓
Layer 3: Length-prefixed chunks  →  LENGTH\nJSON_LINE\nLENGTH\nJSON_LINE\n...
    ↓
Layer 4: wrb.fr envelope        →  [["wrb.fr","RPC_ID","INNER_JSON",...]]
    ↓
Layer 5: Inner JSON parsing     →  json.loads(inner_string)
```

**This is the critical insight.** Each response is wrapped in 4–5 layers of
encoding. You must unwrap them in order.

---

## 6. Response Encoding Pipeline

### Layer 1: HAR Base64 Encoding

The HAR file format may base64-encode large response bodies. Check the
`encoding` field:

```python
entry = har['log']['entries'][idx]
text = entry['response']['content']['text']
encoding = entry['response']['content'].get('encoding', '')

if encoding == 'base64':
    text = base64.b64decode(text).decode('utf-8', errors='replace')
```

**When is base64 used?** Generally for responses > ~100KB. Smaller responses
are stored as plain text in the HAR.

| Entry | Size | Base64? |
|:---|:---|:---|
| `VfAZjd` (summary, 2.4KB) | Small | No |
| `gArtLc` (notes, 163KB) | Medium | No |
| `wXbhsf` (sources, 211KB) | Large | Yes |
| `e3bVqc` (content, 5.2MB) | Very large | Yes |

### Layer 2: XSSI Prefix

Google prepends `)]}'\n\n` to all JSON responses as a Cross-Site Script Inclusion
(XSSI) protection. Strip it:

```python
text = text.lstrip(")]}'").lstrip('\n')
```

### Layer 3: Length-Prefixed Chunks

The response body contains one or more chunks, each preceded by its byte length:

```
2353                              ← Length of next chunk
[["wrb.fr","VfAZjd","...",null,null,null,"generic"]]   ← JSON chunk
59                                ← Length of next chunk  
[["di",8699],["af.httprm",8699,"7156853674736947968",25]]  ← Metadata chunk
26                                ← Length of next chunk
[["e",4,null,null,2452]]          ← Envelope metadata
```

**Critical:** Each chunk is on a SINGLE LINE. The length prefix is on the line
before it. Parse by splitting on `\n` and checking if each line is a pure integer:

```python
def parse_chunks(body):
    """Parse length-prefixed chunks from batchexecute response."""
    lines = body.split('\n')
    chunks = []
    i = 0
    while i < len(lines):
        line = lines[i].strip()
        if line.isdigit():
            # Next line is the JSON chunk
            if i + 1 < len(lines):
                json_line = lines[i + 1]
                try:
                    chunks.append(json.loads(json_line))
                except json.JSONDecodeError:
                    pass
            i += 2
        else:
            i += 1
    return chunks
```

### Layer 4: wrb.fr Envelope

The first chunk (and the only one that matters) is a `wrb.fr` envelope:

```json
[
  [
    "wrb.fr",       // Protocol marker
    "VfAZjd",       // RPC ID
    "[[\"...\"]],",  // Inner JSON (as escaped string!)
    null,            // Reserved
    null,            // Reserved
    null,            // Reserved
    "generic"        // Format hint
  ]
]
```

**The payload is at index `[0][2]`** — and it's a **JSON string that needs
another `json.loads()` call**:

```python
outer = chunks[0]        # First chunk
row = outer[0]           # First (only) row
rpc_id = row[1]          # "VfAZjd"
inner = json.loads(row[2])  # Parse the inner JSON string → actual data
```

### Layer 5: Inner Data Structures

After all unwrapping, `inner` is a nested Python list/dict containing the
actual notebook data. Structure varies by RPC endpoint — see
[Section 8](#8-data-structure-reference).

### Complete Unwrap Function

```python
import json, base64

def unwrap_batchexecute(entry):
    """Full decode pipeline: HAR entry → (rpc_id, data).
    
    Handles all 5 encoding layers:
    1. HAR base64
    2. XSSI prefix
    3. Length-prefixed chunks
    4. wrb.fr envelope
    5. Inner JSON
    
    Args:
        entry: A single HAR log entry dict.
    
    Returns:
        Tuple of (rpc_id: str, data: Any) or (None, None) on failure.
    """
    # Layer 1: HAR base64
    text = entry['response']['content'].get('text', '')
    if entry['response']['content'].get('encoding') == 'base64':
        text = base64.b64decode(text).decode('utf-8', errors='replace')
    
    # Layer 2: XSSI prefix
    text = text.lstrip(")]}'").lstrip('\n')
    
    # Layer 3: Length-prefixed chunks → find first JSON line
    for line in text.split('\n'):
        line = line.strip()
        if line.startswith('[["wrb.fr"'):
            # Layer 4: wrb.fr envelope
            outer = json.loads(line)
            row = outer[0]
            rpc_id = row[1]
            # Layer 5: Inner JSON
            inner = json.loads(row[2])
            return rpc_id, inner
    
    return None, None
```

---

## 7. RPC Endpoint Reference

### Endpoint Inventory

13 unique RPC endpoints identified from NotebookLM traffic:

| RPC ID | Purpose | Notebook-scoped? | Typical Size | Base64? |
|:---|:---|:---|:---|:---|
| `wXbhsf` | **Source listing** — all sources with metadata | Yes (via page context) | 211 KB | Yes |
| `ub2Bae` | **Notebook list** — all visible notebooks | No (account-wide) | 340 KB | Yes |
| `e3bVqc` | **Full source content** — text of all sources | Yes | 5.2 MB | Yes |
| `gArtLc` | **Notes listing** — all notes/artifacts | Yes | 163 KB | No |
| `VfAZjd` | **Notebook summary** — AI-generated guide | Yes | 2.4 KB | No |
| `cFji9` | **Q&A conversations** — chat history | Yes | 47 KB | No |
| `khqZz` | **Conversation thread** — full paginated thread | Yes (via session ID) | 783 KB | Yes |
| `rLM1Ne` | **Notebook config** — settings, preferences | Yes | 31 KB | Yes |
| `hPTbtc` | **Activity feed** — recent actions | Yes | 186 B | No |
| `JFMDGd` | **Sharing/permissions** — access control | Yes | 313 B | No |
| `sqTeoe` | **Feature flags** — UI feature toggles | No | 1 KB | No |
| `ZwVcOc` | **User profile** — account info | No | 232 B | No |
| `ozz5Z` | **Audio overview** — podcast metadata | No | 1 KB | No |

Plus one non-batchexecute streaming endpoint:

| Endpoint | Purpose |
|:---|:---|
| `GenerateFreeFormStreamed` | Streaming generated report (SSE-like) |

---

### 7.1 `wXbhsf` — Source Listing

**Purpose:** Returns all sources uploaded to the current notebook.

**Request:**
```json
[["wXbhsf", "[null,1,null,[2]]", null, "generic"]]
```
No notebook ID in request — scoped by the page URL context.

**Response structure:**
```
inner[0][0] = "Notebook Name"
inner[0][1] = [source_1, source_2, ...]  // Array of sources
```

Each source:
```
source[0] = [UUID]           // e.g. ["4de8365a-8611-40b0-8177-aa7615e8b8df"]
source[1] = "Title"          // e.g. "Gemma 3 Technical Report - arXiv.org"
source[2] = [metadata]       // See below
source[3] = [null, type_id]  // Type indicator
```

Metadata array (`source[2]`):
```
[2][0] = null
[2][1] = word_count          // Integer, e.g. 10909
[2][2] = [timestamp_seconds, timestamp_nanos]  // Upload time
[2][3] = [version_uuid, [timestamp]]           // Version info
[2][4] = processing_status   // 5 = processed
[2][5] = null
[2][6] = source_type         // 1 = URL, 2 = uploaded file, 3 = pasted text
[2][7] = [URL]               // Source URL (if from web)
```

**Extraction:**
```python
rpc, data = unwrap_batchexecute(entry)
notebook_name = data[0][0]
sources = []
for src in data[0][1]:
    sources.append({
        'id': src[0][0],
        'title': src[1],
        'word_count': src[2][1] if src[2] and len(src[2]) > 1 else 0,
        'url': src[2][7][0] if src[2] and len(src[2]) > 7 and src[2][7] else '',
        'source_type': src[2][6] if src[2] and len(src[2]) > 6 else None
    })
```

---

### 7.2 `e3bVqc` — Full Source Content

**Purpose:** Returns the complete text content of all sources in the notebook.
This is the **largest** response, often 3–5 MB.

**Request:**
```json
[["e3bVqc", "[null,null,\"NOTEBOOK_ID\"]", null, "generic"]]
```

**Response structure:**
```
inner[0] = [source_entry_1, source_entry_2, ...]

Each source_entry:
  [0] = source_uuid
  [1] = [notebook_id, [source_text, ...metadata...]]
```

The source text is deeply nested. Use recursive string extraction:

```python
def extract_strings(obj, min_len=80):
    """Recursively pull all readable strings from nested structure."""
    results = []
    if isinstance(obj, str) and len(obj) >= min_len:
        if not re.match(r'^[a-f0-9-]{30,}$', obj.strip()):
            results.append(obj)
    elif isinstance(obj, list):
        for item in obj:
            results.extend(extract_strings(item, min_len))
    return results
```

---

### 7.3 `VfAZjd` — Notebook Summary

**Purpose:** AI-generated summary/guide text for the notebook.

**Request:**
```json
[["VfAZjd", "[\"NOTEBOOK_ID\",[2]]", null, "generic"]]
```

**Response:** Clean text strings describing the notebook's content. Usually
1–3 KB of readable prose.

```python
rpc, data = unwrap_batchexecute(entry)
summary_parts = extract_strings(data, min_len=50)
summary = '\n\n'.join(summary_parts)
```

---

### 7.4 `gArtLc` — Notes Listing

**Purpose:** Returns all user-created and AI-generated notes (artifacts).

**Request:**
```json
[["gArtLc", "[[2,...],\"NOTEBOOK_ID\",\"NOT artifact.status = \\\"ARTIFACT_STATUS_SUGGESTED\\\"\"]", null, "generic"]]
```

Note the filter query: `NOT artifact.status = "ARTIFACT_STATUS_SUGGESTED"` excludes
auto-suggested notes.

**Response structure:**
```
inner = [note_1, note_2, ...]

Each note:
  [0] = note_uuid
  [1] = "Note Title"
  [2] = note_type  // 8 = standard note
  [3] = [[source_refs], ...]  // Source attributions
  ... (variable length)
  [N] = "Note content text"  // The actual content (find via string extraction)
```

Notes contain the richest AI-generated content — blueprints, analysis documents,
implementation guides. Use recursive string extraction.

---

### 7.5 `cFji9` — Q&A Conversations

**Purpose:** Chat history — questions asked and AI responses.

**Request:**
```json
[["cFji9", "[\"NOTEBOOK_ID\",null,null,[2]]", null, "generic"]]
```

With pagination (after a timestamp):
```json
[["cFji9", "[\"NOTEBOOK_ID\",null,[TIMESTAMP_SEC,TIMESTAMP_NANO],[2]]", null, "generic"]]
```

**Response:** Contains question-answer pairs with timestamps and source citations.

---

### 7.6 `khqZz` — Conversation Thread

**Purpose:** Full paginated conversation thread for a specific session.

**Request:**
```json
[["khqZz", "[[],null,null,\"SESSION_UUID\",20]", null, "generic"]]
```

The last argument (`20`) is the page size.

**Response:** Rich conversation data including generated reports, citations,
and formatting. Often 500KB–1MB for active sessions.

---

### 7.7 `ub2Bae` — Notebook List

**Purpose:** Lists ALL notebooks visible to the authenticated account.

**Request:**
```json
[["ub2Bae", "[[2]]", null, "generic"]]
```

**Response:** Array of notebook entries, each with name, description,
and configuration. Useful for discovering notebook IDs.

---

### 7.8 `rLM1Ne` — Notebook Configuration

**Purpose:** Notebook-specific settings and user preferences.

**Request:**
```json
[["rLM1Ne", "[\"NOTEBOOK_ID\",null,[2],null,0]", null, "generic"]]
```

---

### 7.9 Streaming: `GenerateFreeFormStreamed`

**Purpose:** Real-time streaming of generated reports/deep dives.

**URL pattern:**
```
POST /_/LabsTailwindUi/data/google.internal.labs.tailwind.orchestration.v1.LabsTailwindService/GenerateFreeFormStreamed
```

**Response format:** Same length-prefixed chunk format, but with **multiple
wrb.fr chunks** (one per streaming update). In our reference HAR, entry 206
contained **47 streaming chunks**.

Each chunk has `rpc_id = null` (unlike standard RPCs) and contains incremental
content updates with character offsets:

```json
[["wrb.fr", null, "[[\"chunk_text\",...]]", ...]]
```

The streaming chunks contain `[start_offset, end_offset, [content_parts]]`
for incremental rendering.

---

## 8. Data Structure Reference

### Notebook ID

UUID v4 format: `04168cf3-04a0-46bb-ba58-fec66458aab9`

Found in:
- Page URL: `https://notebooklm.google.com/notebook/{ID}`
- Request parameters: `f.req` JSON arguments
- Response data: nested in source/note/conversation structures

### Source Object

```python
{
    'id': 'UUID',           # e.g. "4de8365a-8611-40b0-8177-aa7615e8b8df"
    'title': 'str',         # e.g. "Gemma 3 Technical Report - arXiv.org"
    'url': 'str',           # Original source URL (if web-based)
    'word_count': int,      # e.g. 10909
    'source_type': int,     # 1=URL, 2=uploaded, 3=pasted
    'upload_time': [sec, nano],  # Unix timestamp with nanoseconds
    'processing_status': int     # 5 = fully processed
}
```

### Timestamp Format

Google uses `[seconds, nanoseconds]` arrays:
```python
[1771917066, 501496000]  # → Unix timestamp 1771917066.501496
```

Convert to datetime:
```python
import datetime
ts = datetime.datetime.fromtimestamp(1771917066 + 501496000/1e9)
```

### Session/Thread ID

Conversations and generated content are grouped by session UUIDs:
```
"278dce36-057b-445e-a9ef-c0aa1ae04bb0"  # Session
"4e84a03a-d0d7-4c6d-b975-a4c49f824c1a"  # Turn within session
```

---

## 9. Streaming Responses

### How Streaming Works

When NotebookLM generates a report or deep dive, it uses a streaming endpoint
that returns **multiple wrb.fr chunks** in a single HTTP response.

The chunks are length-prefixed like standard responses, but there are many of
them (typically 20–50+), each containing an incremental text update.

### Streaming Chunk Structure

```python
# Each chunk in a streaming response:
[["wrb.fr", null, "INNER_JSON", ...]]
#                  ^^ rpc_id is null for streaming chunks

# Inner JSON contains:
[
    [
        "chunk_text",
        null,
        ["session_id", "turn_id", sequence_number],
        null,
        [
            [
                [
                    [start_offset, end_offset, [
                        [start, end, ["visible_text", [formatting]]]
                    ]]
                ]
            ]
        ]
    ],
    ...
]
```

### Extracting Streamed Content

For streaming responses, concatenate all text fragments:

```python
def extract_streaming(entry):
    """Extract full text from a streaming response."""
    text = get_decoded_text(entry)
    body = text.lstrip(")]}'").lstrip('\n')
    
    all_text = []
    for line in body.split('\n'):
        line = line.strip()
        if line.startswith('[["wrb.fr"'):
            try:
                outer = json.loads(line)
                inner_str = outer[0][2]
                if inner_str:
                    inner = json.loads(inner_str)
                    strings = extract_strings(inner, min_len=50)
                    all_text.extend(strings)
            except:
                pass
    
    return dedup(all_text)
```

---

## 10. Complete Extraction Script

### `extract_notebooklm_har.py`

```python
#!/usr/bin/env python3
"""NotebookLM HAR Extractor — Complete extraction of notebook content from HAR files.

Usage:
    python extract_notebooklm_har.py <har_file> [--output notebook.json]

Extracts:
    - Notebook metadata (name, ID, summary)
    - All sources (titles, URLs, word counts)
    - Full source document content
    - Notes and blueprints
    - Q&A conversations
    - Generated reports

Output: Structured JSON file with all extracted content.
"""
from __future__ import annotations

import argparse
import base64
import json
import logging
import re
import sys
from pathlib import Path
from typing import Any, Optional

logger = logging.getLogger(__name__)


# ──── Core Decode Functions ────

def get_response_text(entry: dict) -> str:
    """Decode HAR entry response, handling base64 encoding.
    
    Args:
        entry: A single HAR log entry.
    
    Returns:
        Decoded response text.
    """
    content = entry['response']['content']
    text = content.get('text', '')
    if content.get('encoding') == 'base64':
        text = base64.b64decode(text).decode('utf-8', errors='replace')
    return text


def parse_batchexecute(raw: str) -> tuple[Optional[str], Any]:
    """Parse Google batchexecute response through all encoding layers.
    
    Handles: XSSI prefix → length-prefixed chunks → wrb.fr envelope → inner JSON.
    
    Args:
        raw: Decoded response text.
    
    Returns:
        Tuple of (rpc_id, parsed_data) or (None, None) on failure.
    """
    body = raw.lstrip(")]}'").lstrip('\n')
    for line in body.split('\n'):
        line = line.strip()
        if line.startswith('[["wrb.fr"'):
            try:
                outer = json.loads(line)
                rpc_id = outer[0][1]
                inner = json.loads(outer[0][2]) if isinstance(outer[0][2], str) else outer[0][2]
                return rpc_id, inner
            except (json.JSONDecodeError, IndexError, TypeError):
                continue
    return None, None


def unwrap(entry: dict) -> tuple[Optional[str], Any]:
    """Full HAR entry → (rpc_id, data) pipeline.
    
    Args:
        entry: HAR log entry dict.
    
    Returns:
        Tuple of (rpc_id, parsed_inner_data).
    """
    return parse_batchexecute(get_response_text(entry))


# ──── Content Extraction Functions ────

def extract_strings(obj: Any, min_len: int = 80) -> list[str]:
    """Recursively extract all meaningful text strings from nested data.
    
    Filters out UUIDs, short strings, and JSON artifacts.
    
    Args:
        obj: Nested list/dict/str structure from parsed response.
        min_len: Minimum string length to include.
    
    Returns:
        List of extracted text strings.
    """
    results = []
    if isinstance(obj, str):
        s = obj.strip()
        if len(s) >= min_len and not re.match(r'^[a-f0-9-]{30,}$', s):
            results.append(s)
    elif isinstance(obj, list):
        for item in obj:
            results.extend(extract_strings(item, min_len))
    elif isinstance(obj, dict):
        for v in obj.values():
            results.extend(extract_strings(v, min_len))
    return results


def dedup(texts: list[str], key_len: int = 120) -> list[str]:
    """Deduplicate text blocks by prefix.
    
    Args:
        texts: List of text strings.
        key_len: Number of prefix characters to use as dedup key.
    
    Returns:
        Deduplicated list preserving order.
    """
    seen: set[str] = set()
    return [t for t in texts if t[:key_len] not in seen and not seen.add(t[:key_len])]


def extract_sources(data: Any) -> tuple[str, list[dict]]:
    """Extract source listing from wXbhsf response.
    
    Args:
        data: Parsed inner data from wXbhsf RPC.
    
    Returns:
        Tuple of (notebook_name, list_of_source_dicts).
    """
    notebook_name = ''
    sources = []
    
    try:
        nb_core = data[0][0]
        notebook_name = nb_core[0] if isinstance(nb_core[0], str) else ''
        src_list = nb_core[1] if len(nb_core) > 1 and isinstance(nb_core[1], list) else []
        
        for src in src_list:
            if not isinstance(src, list) or len(src) < 2:
                continue
            try:
                uuid = src[0][0] if isinstance(src[0], list) and src[0] else ''
                title = src[1] if isinstance(src[1], str) else ''
                url = ''
                word_count = 0
                source_type = None
                
                if len(src) > 2 and isinstance(src[2], list):
                    meta = src[2]
                    word_count = meta[1] if len(meta) > 1 and isinstance(meta[1], int) else 0
                    source_type = meta[6] if len(meta) > 6 else None
                    if len(meta) > 7 and isinstance(meta[7], list) and meta[7]:
                        url = meta[7][0] if isinstance(meta[7][0], str) else ''
                
                sources.append({
                    'id': uuid,
                    'title': title,
                    'url': url,
                    'word_count': word_count,
                    'source_type': source_type
                })
            except (IndexError, TypeError):
                continue
    except (IndexError, TypeError) as e:
        logger.warning("Failed to parse sources: %s", e)
    
    return notebook_name, sources


# ──── Main Extraction Pipeline ────

def extract_notebook(har_path: str, output_path: str = 'notebook.json') -> dict:
    """Extract all content from a NotebookLM HAR file.
    
    Args:
        har_path: Path to the .har file.
        output_path: Path for the output JSON file.
    
    Returns:
        The extracted notebook dict.
    """
    with open(har_path, 'r', encoding='utf-8', errors='replace') as f:
        har = json.load(f)
    
    entries = har['log']['entries']
    
    # Index all batchexecute entries by RPC ID
    rpc_entries: dict[str, list[int]] = {}
    for i, e in enumerate(entries):
        url = e['request']['url']
        if 'batchexecute' not in url and 'GenerateFreeForm' not in url:
            continue
        
        rpc_id, _ = unwrap(e)
        if rpc_id:
            rpc_entries.setdefault(rpc_id, []).append(i)
        elif 'GenerateFreeForm' in url:
            rpc_entries.setdefault('GenerateFreeForm', []).append(i)
    
    logger.info("Found RPC endpoints: %s", {k: len(v) for k, v in rpc_entries.items()})
    
    notebook = {
        'notebook_id': '',
        'notebook_name': '',
        'summary': '',
        'sources': [],
        'content': {
            'documents': [],
            'notes': [],
            'conversations': []
        },
        'stats': {}
    }
    
    # Extract notebook ID from page URL
    for e in entries:
        match = re.search(r'/notebook/([a-f0-9-]{36})', e['request']['url'])
        if match:
            notebook['notebook_id'] = match.group(1)
            break
    
    # Sources (wXbhsf)
    if 'wXbhsf' in rpc_entries:
        _, data = unwrap(entries[rpc_entries['wXbhsf'][0]])
        if data:
            name, sources = extract_sources(data)
            notebook['notebook_name'] = name
            notebook['sources'] = sources
    
    # Summary (VfAZjd)
    if 'VfAZjd' in rpc_entries:
        _, data = unwrap(entries[rpc_entries['VfAZjd'][0]])
        if data:
            notebook['summary'] = '\n\n'.join(extract_strings(data, 50))
    
    # Full source content (e3bVqc)
    if 'e3bVqc' in rpc_entries:
        _, data = unwrap(entries[rpc_entries['e3bVqc'][0]])
        if data:
            docs = dedup(extract_strings(data, 100))
            notebook['content']['documents'] = [d for d in docs if len(d) > 200]
    
    # Notes (gArtLc)
    if 'gArtLc' in rpc_entries:
        for idx in rpc_entries['gArtLc']:
            _, data = unwrap(entries[idx])
            if data:
                notes = dedup(extract_strings(data, 80))
                notebook['content']['notes'].extend([n for n in notes if len(n) > 100])
    
    # Conversations (cFji9 + khqZz)
    for rpc in ['cFji9', 'khqZz']:
        if rpc in rpc_entries:
            for idx in rpc_entries[rpc]:
                _, data = unwrap(entries[idx])
                if data:
                    convos = extract_strings(data, 80)
                    notebook['content']['conversations'].extend(
                        [c for c in convos if len(c) > 100]
                    )
    notebook['content']['conversations'] = dedup(notebook['content']['conversations'])
    
    # Streaming reports (GenerateFreeForm)
    if 'GenerateFreeForm' in rpc_entries:
        for idx in rpc_entries['GenerateFreeForm']:
            text = get_response_text(entries[idx])
            body = text.lstrip(")]}'").lstrip('\n')
            for line in body.split('\n'):
                line = line.strip()
                if line.startswith('[["wrb.fr"'):
                    try:
                        outer = json.loads(line)
                        inner_str = outer[0][2]
                        if inner_str:
                            inner = json.loads(inner_str)
                            for s in extract_strings(inner, 100):
                                notebook['content']['documents'].append(s)
                    except:
                        pass
        notebook['content']['documents'] = dedup(notebook['content']['documents'])
    
    # Stats
    notebook['stats'] = {
        'sources': len(notebook['sources']),
        'documents': len(notebook['content']['documents']),
        'notes': len(notebook['content']['notes']),
        'conversations': len(notebook['content']['conversations']),
        'total_chars': (
            len(notebook['summary'])
            + sum(len(d) for d in notebook['content']['documents'])
            + sum(len(n) for n in notebook['content']['notes'])
            + sum(len(c) for c in notebook['content']['conversations'])
        )
    }
    
    # Save
    with open(output_path, 'w', encoding='utf-8') as f:
        json.dump(notebook, f, indent=2, ensure_ascii=False)
    
    logger.info(
        "Extracted: %d sources, %d docs, %d notes, %d conversations (%s chars)",
        notebook['stats']['sources'],
        notebook['stats']['documents'],
        notebook['stats']['notes'],
        notebook['stats']['conversations'],
        f"{notebook['stats']['total_chars']:,}"
    )
    
    return notebook


if __name__ == '__main__':
    logging.basicConfig(level=logging.INFO, format='%(message)s')
    
    parser = argparse.ArgumentParser(description='Extract NotebookLM content from HAR files')
    parser.add_argument('har_file', help='Path to the .har file')
    parser.add_argument('--output', '-o', default='notebook.json', help='Output JSON path')
    args = parser.parse_args()
    
    result = extract_notebook(args.har_file, args.output)
    
    print(f"\n{'='*60}")
    print(f"Notebook: {result['notebook_name']}")
    print(f"ID:       {result['notebook_id']}")
    print(f"Sources:  {result['stats']['sources']}")
    print(f"Docs:     {result['stats']['documents']}")
    print(f"Notes:    {result['stats']['notes']}")
    print(f"Convos:   {result['stats']['conversations']}")
    print(f"Total:    {result['stats']['total_chars']:,} chars")
    print(f"Output:   {args.output}")
    print(f"{'='*60}")
```

---

## 11. Working with Extracted Data

### Output JSON Structure

```json
{
  "notebook_id": "04168cf3-04a0-46bb-ba58-fec66458aab9",
  "notebook_name": "Finetune Gemma3 270m",
  "summary": "These sources provide a comprehensive look at...",
  "sources": [
    {
      "id": "4de8365a-8611-40b0-8177-aa7615e8b8df",
      "title": "Gemma 3 Technical Report - arXiv.org",
      "url": "https://arxiv.org/html/2503.19786v1",
      "word_count": 10909,
      "source_type": 2
    }
  ],
  "content": {
    "documents": ["Full text of source documents..."],
    "notes": ["AI-generated notes and blueprints..."],
    "conversations": ["Q&A chat exchanges..."]
  },
  "stats": {
    "sources": 78,
    "documents": 164,
    "notes": 152,
    "conversations": 274,
    "total_chars": 3978726
  }
}
```

### Ingesting into Nexus KMS

```python
from engine.nexus.client import get_nexus_client
import json

client = get_nexus_client()

with open('notebook.json', 'r') as f:
    nb = json.load(f)

# Store notebook summary
client.add_entry(
    title=f"NotebookLM: {nb['notebook_name']}",
    content=nb['summary'],
    content_type="document",
    category="research"
)

# Store each source as a reference
for src in nb['sources']:
    client.add_entry(
        title=src['title'],
        content=f"Source URL: {src['url']}\nWord count: {src['word_count']}",
        content_type="note",
        category="reference"
    )

# Store key documents
for doc in nb['content']['documents']:
    if len(doc) > 1000:  # Only substantial documents
        title = doc[:80].replace('\n', ' ')
        client.add_entry(
            title=title,
            content=doc,
            content_type="document",
            category="research"
        )

# Store Q&A pairs
for conv in nb['content']['conversations']:
    if len(conv) > 200:
        client.add_qa(
            question=conv[:100],
            answer=conv,
            category="research"
        )
```

### Loading for Training Data

```python
import json

with open('notebook.json', 'r') as f:
    nb = json.load(f)

# Convert documents to instruction-format training data
training_data = []
for doc in nb['content']['documents']:
    if len(doc) > 500:
        training_data.append({
            'instruction': 'Summarize the following technical document.',
            'input': doc[:4000],
            'output': doc[:500]  # Use summary as output
        })

# Convert Q&A to training pairs
for conv in nb['content']['conversations']:
    if '?' in conv[:200]:
        parts = conv.split('?', 1)
        if len(parts) == 2 and len(parts[1]) > 100:
            training_data.append({
                'instruction': parts[0].strip() + '?',
                'input': '',
                'output': parts[1].strip()[:2000]
            })
```

---

## 12. Modification Guide

### Targeting Specific Notebooks

The notebook ID appears in the page URL. To extract a specific notebook:

1. Navigate to `https://notebooklm.google.com/notebook/{NOTEBOOK_ID}`
2. Capture HAR
3. The extraction script auto-detects the notebook ID from URL patterns

### Extracting Multiple Notebooks

If your HAR contains visits to multiple notebooks, the `ub2Bae` RPC returns
the full notebook list. You can then filter entries by notebook ID in the
request parameters:

```python
# Find all notebook IDs in the HAR
notebook_ids = set()
for entry in har['log']['entries']:
    match = re.search(r'/notebook/([a-f0-9-]{36})', entry['request']['url'])
    if match:
        notebook_ids.add(match.group(1))

# Filter entries by notebook
for nb_id in notebook_ids:
    nb_entries = [e for e in entries if nb_id in e['request'].get('postData', {}).get('text', '')]
```

### Extracting Only Sources

If you only need the source list (no content):

```python
# Just parse wXbhsf entries
for entry in entries:
    rpc, data = unwrap(entry)
    if rpc == 'wXbhsf':
        name, sources = extract_sources(data)
        for src in sources:
            print(f"{src['title']} → {src['url']}")
```

### Extracting Only Conversations

```python
# Parse cFji9 and khqZz entries
for entry in entries:
    rpc, data = unwrap(entry)
    if rpc in ('cFji9', 'khqZz'):
        conversations = extract_strings(data, min_len=100)
        for conv in conversations:
            print(conv[:200])
```

### Adding New RPC Handlers

When Google adds new features, new RPC IDs will appear. To identify them:

```python
# Scan for unknown RPCs
known_rpcs = {'wXbhsf', 'ub2Bae', 'e3bVqc', 'gArtLc', 'VfAZjd', 
              'cFji9', 'khqZz', 'rLM1Ne', 'hPTbtc', 'JFMDGd',
              'sqTeoe', 'ZwVcOc', 'ozz5Z'}

for entry in entries:
    rpc, data = unwrap(entry)
    if rpc and rpc not in known_rpcs:
        print(f"NEW RPC: {rpc} — {len(str(data))} chars")
```

### Reading the Raw Stream

To see exactly what flows over the wire (useful for debugging):

```python
for i, entry in enumerate(entries):
    url = entry['request']['url']
    if 'batchexecute' not in url:
        continue
    
    text = get_response_text(entry)
    body = text.lstrip(")]}'").lstrip('\n')
    
    # Show all chunks
    for line in body.split('\n'):
        line = line.strip()
        if line.isdigit():
            print(f"[{i}] CHUNK LENGTH: {line}")
        elif line.startswith('[["wrb.fr"'):
            outer = json.loads(line)
            rpc = outer[0][1]
            inner_len = len(outer[0][2]) if outer[0][2] else 0
            print(f"[{i}] RPC: {rpc}, inner: {inner_len} chars")
        elif line.startswith('[["di"') or line.startswith('[["e"'):
            print(f"[{i}] META: {line[:80]}")
```

---

## 13. Troubleshooting

### Common Issues

| Problem | Cause | Solution |
|:---|:---|:---|
| `json.JSONDecodeError` on chunk | Multi-line JSON in chunk | Split on `\n`, take first line only |
| Empty extraction | HAR captured too early | Wait for full page load before saving HAR |
| Missing conversations | Not scrolled in UI | Scroll through chat history to trigger loading |
| `KeyError` on source metadata | Source still processing | Check `processing_status != 5` |
| Huge HAR file (>200MB) | Many favicons/assets | Filter entries by `batchexecute` URL |
| Base64 decode error | Corrupted HAR export | Re-export HAR from Chrome DevTools |

### Verifying Extraction Quality

```python
# Quick validation
with open('notebook.json', 'r') as f:
    nb = json.load(f)

assert nb['notebook_id'], "Missing notebook ID"
assert nb['notebook_name'], "Missing notebook name"
assert len(nb['sources']) > 0, "No sources extracted"
assert nb['stats']['total_chars'] > 1000, "Too little content extracted"

# Check for JSON noise in content
for doc in nb['content']['documents'][:5]:
    assert not doc.startswith('[["'), f"JSON artifact in document: {doc[:50]}"
    assert not doc.startswith('wrb.fr'), f"Protocol artifact in document"
```

### HAR Sensitive Data Warning

HAR files contain **full authentication cookies and tokens**. The response
bodies contain your notebook content. Handle with care:

- **Never commit HAR files** to version control
- **Never share HAR files** publicly
- **Delete after extraction** if sensitive
- **Strip cookies** if archiving: `for e in har['log']['entries']: e['request']['cookies'] = []`

---

## 14. Appendix: Raw Protocol Examples

### Complete Request/Response Cycle for `VfAZjd` (Summary)

**Request:**
```http
POST /_/LabsTailwindUi/data/batchexecute?rpcids=VfAZjd&source-path=/notebook/04168cf3-04a0-46bb-ba58-fec66458aab9 HTTP/1.1
Host: notebooklm.google.com
Content-Type: application/x-www-form-urlencoded

f.req=[[["VfAZjd","[\"04168cf3-04a0-46bb-ba58-fec66458aab9\",[2]]",null,"generic"]]]
```

**Raw Response:**
```
)]}'

2353
[["wrb.fr","VfAZjd","[[\"These sources provide a comprehensive look at the **Gemma 3** family of open-source models...\"]]",null,null,null,"generic"]]
59
[["di",8699],["af.httprm",8699,"7156853674736947968",25]]
26
[["e",4,null,null,2452]]
```

**After full unwrap:**
```python
rpc_id = "VfAZjd"
data = [["These sources provide a comprehensive look at the **Gemma 3** family..."]]
```

### Metadata Chunk Types

The non-wrb.fr chunks contain protocol metadata:

| Prefix | Purpose |
|:---|:---|
| `["di", N]` | Data integrity — total response size |
| `["af.httprm", ...]` | HTTP request metadata — request ID, sequence |
| `["e", N, ...]` | Envelope — chunk count, total response bytes |

These can be safely ignored during content extraction.

### Source Type Enumeration

| Value | Meaning |
|:---|:---|
| `1` | URL (web page) |
| `2` | Uploaded file (PDF, DOCX, etc.) |
| `3` | Pasted text |
| `5` | Google Drive document |
| `8` | YouTube video |

### Processing Status Enumeration

| Value | Meaning |
|:---|:---|
| `1` | Queued |
| `2` | Processing |
| `3` | Indexing |
| `5` | Complete |
| `6` | Failed |

---

## Reference Implementation

The extraction script is available at:
- **Script:** `docs/NOTEBOOKLM_HAR_SDK.md` (this document, Section 10)
- **Extracted data:** `C:\Files\Nexus\data\notebooks\finetune_gemma3_270m.json`
- **Raw HAR:** `%USERPROFILE%\Downloads\notebooklm.google.com.har`

### Verified Against

- **NotebookLM version:** February 2026
- **HAR format:** HAR 1.2 (Chrome DevTools export)
- **Notebook:** "Finetune Gemma3 270m" (78 sources, ~4M chars extracted)
- **Python:** 3.10+
- **Dependencies:** None (stdlib only: `json`, `base64`, `re`, `argparse`)

---

*This document is part of the CosySim documentation suite. See `docs/INDEX.md` for the full index.*
