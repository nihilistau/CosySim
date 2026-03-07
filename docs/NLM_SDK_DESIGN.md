# NLM SDK Design
## NLMClient Architecture & Usage Guide

> CosySim's programmatic NotebookLM interface  
> Client: `engine/integrations/nlm_direct_client.py`

---

## Architecture Overview

```
CosySim Agents / Skills
        │
        ▼
┌─────────────────────────────┐
│     nlm_ask skill           │  @skill decorator — exposes to LLM agents
│     nlm_create_notebook     │
│     nlm_distill             │
└─────────────┬───────────────┘
              │
        ┌─────▼──────┐
        │ NexusRouter │  4-tier pipeline: cache → FTS → NLM → LLM
        └─────┬──────┘
              │ (on cache miss)
        ┌─────▼──────────────┐
        │ NLMDirectClient    │  engine/integrations/nlm_direct_client.py
        │                    │
        │  batchexecute()    │──→ POST /_/LabsTailwindUi/data/batchexecute
        │  _build_headers()  │
        │  _parse_response() │
        └─────┬──────────────┘
              │
        ┌─────▼─────────────┐
        │ GoogleAccountPool  │  engine/integrations/google_account_pool.py
        │                    │
        │  get_cookies()     │──→ data/accounts/pool.json
        │  rotate_account()  │
        │  is_stale()        │
        └────────────────────┘
```

---

## NLMDirectClient

### Initialization

```python
from engine.integrations.nlm_direct_client import get_nlm_direct_client

client = get_nlm_direct_client()  # Singleton, uses pool.json cookies
```

### Core Methods

#### `ask_question(notebook_uuid, question, source_uuids=None)`
Ask a question and get a Gemini-grounded answer.

```python
answer = client.ask_question(
    "3b5dbaa9-6126-47bc-8a64-013eae6cd129",
    "What is the most important finding about V8 heap forensics?"
)
# Returns: str — Gemini's answer grounded in notebook sources
```

Parameters:
- `notebook_uuid` — target notebook
- `question` — natural language question
- `source_uuids` — list of specific source UUIDs to query (None = all sources)

Returns: `str` — the answer text  
Raises: `NLMAuthError`, `NLMRateLimitError`, `NLMNotFoundError`

---

#### `ask_question_stream(notebook_uuid, question)`
Streaming version — yields text chunks as they arrive.

```python
for chunk in client.ask_question_stream(uuid, "Explain the architecture"):
    print(chunk, end="", flush=True)
```

---

#### `list_notebooks()`
Get all notebooks for the authenticated account.

```python
notebooks = client.list_notebooks()
# Returns: List[dict] with keys: uuid, title, created_at, source_count, artifact_count
```

---

#### `get_notebook_info(notebook_uuid)`
Get metadata for a notebook.

```python
info = client.get_notebook_info("3b5dbaa9-...")
# Returns: dict with: uuid, title, description, created_at, updated_at
```

---

#### `list_sources(notebook_uuid)`
Get all sources in a notebook.

```python
sources = client.list_sources(uuid)
# Returns: List[dict] with: source_uuid, type, status, title, created_at
```

---

#### `get_source_content(notebook_uuid, source_uuid)`
Get the text content of a source.

```python
text = client.get_source_content(nb_uuid, src_uuid)
# Returns: str — the source's text content
```

---

#### `get_notebook_analysis(notebook_uuid)`
Get AI-generated analysis of all notebook sources.

```python
analysis = client.get_notebook_analysis(uuid)
# Returns: str — structured markdown analysis
```

---

#### `list_artifacts(notebook_uuid)`
Get all generated artifacts.

```python
artifacts = client.list_artifacts(uuid)
# Returns: List[dict] with: artifact_uuid, type, title, status, created_at
```

---

#### `create_artifact(notebook_uuid, artifact_type)`
Trigger generation of a new artifact.

```python
artifact_uuid = client.create_artifact(uuid, "STUDY_GUIDE")
# Returns: str — the new artifact's UUID
# Note: generation is async, poll list_artifacts for SAVED status
```

---

#### `get_suggested_questions(notebook_uuid, hint="", count=5)`
Get AI-suggested questions for the notebook.

```python
questions = client.get_suggested_questions(uuid, hint="architecture", count=10)
# Returns: List[str] — suggested questions
```

---

#### `get_audio_overview_options(notebook_uuid)`
Get available audio format options.

```python
formats = client.get_audio_overview_options(uuid)
# Returns: [{"id": 1, "name": "Deep dive", "description": "..."}, ...]
```

---

#### `create_note(notebook_uuid, title, content_html)`
Create a pinned note.

```python
client.create_note(uuid, "Key Finding", "<p>The V8 heap contains all proto stubs.</p>")
# Returns: str — note UUID
```

---

#### `rename_notebook(notebook_uuid, new_title)`
Rename a notebook.

```python
client.rename_notebook(uuid, "V8 Heap Forensics Research")
```

---

#### `watch_notebook(notebook_uuid)`
Server-sent event stream for real-time updates.

```python
for event in client.watch_notebook(uuid):
    print(f"Event: {event['type']} — {event['data']}")
```

---

### Low-Level: `batchexecute(rpcid, payload, notebook_uuid)`

Direct access to any batchexecute endpoint:

```python
response = client.batchexecute(
    rpcid="VfAZjd",
    payload=[notebook_uuid, [2]],
    notebook_uuid=notebook_uuid
)
# Returns: parsed response JSON (after stripping )]}' prefix and wrb.fr unwrapping)
```

---

## GoogleAccountPool

### Usage

```python
from engine.integrations.google_account_pool import get_account_pool

pool = get_account_pool()

# Get cookies for an account
cookies = pool.get_cookies("knack112358")

# Check if cookies are stale
if pool.is_stale("knack112358", max_age_hours=48):
    pool.refresh_via_cdp("knack112358")

# Auto-rotate on rate limit
pool.mark_rate_limited("knack112358")  # Sets cooldown
next_account = pool.get_available_account()  # Returns non-limited account

# Import fresh cookies from HAR
pool.import_from_har("artifacts/argus/har/fresh.har", "knack112358", ["notebooklm"])
pool.save()
```

### Cookie File Format (`data/accounts/pool.json`)

```json
{
  "knack112358": {
    "notebooklm": {
      "cookies": {
        "SAPISID": "value",
        "SID": "value",
        "APISID": "value",
        "HSID": "value",
        "SSID": "value",
        "NID": "value",
        "SIDCC": "value",
        "__Secure-1PSID": "value",
        "__Secure-1PAPISID": "value",
        "__Secure-1PSIDCC": "value",
        "__Secure-3PSID": "value",
        "__Secure-3PAPISID": "value",
        "SOCS": "value"
      },
      "extracted_at": "2026-03-05T04:07:19",
      "source": "har"
    }
  }
}
```

---

## Error Handling

```python
from engine.integrations.nlm_direct_client import (
    NLMAuthError,       # Cookies expired/invalid
    NLMRateLimitError,  # 50 queries/day exceeded
    NLMNotFoundError,   # Notebook UUID not found
    NLMTimeoutError,    # Request timed out
    NLMResponseError,   # Malformed response
)

try:
    answer = client.ask_question(uuid, question)
except NLMRateLimitError:
    # Auto-rotate to next account
    pool.mark_rate_limited(client.current_account)
    client.switch_account(pool.get_available_account())
    answer = client.ask_question(uuid, question)
except NLMAuthError:
    # Cookies expired — refresh via CDP
    scripts/har_capture.py
```

---

## Response Parsing

The batchexecute response format requires multi-step parsing:

```python
def parse_batchexecute_response(raw: str) -> dict:
    # 1. Strip security prefix
    if raw.startswith(")]}'"):
        raw = raw[5:]
    
    # 2. Parse chunked transfer
    chunks = []
    lines = raw.strip().split("\n")
    i = 0
    while i < len(lines):
        # Skip chunk size lines (decimal or hex)
        try:
            int(lines[i], 16)  # hex chunk size
            i += 1
            continue
        except ValueError:
            pass
        
        if lines[i].startswith("[["):
            try:
                chunk = json.loads(lines[i])
                chunks.extend(chunk)
            except json.JSONDecodeError:
                pass
        i += 1
    
    # 3. Find wrb.fr response
    for item in chunks:
        if isinstance(item, list) and len(item) >= 3 and item[0] == "wrb.fr":
            rpcid = item[1]
            payload = json.loads(item[2]) if isinstance(item[2], str) else item[2]
            return {"rpcid": rpcid, "payload": payload}
    
    return {}
```

---

## NLM Distillation Pattern

The highest-value use of NLM is generating Q&A pairs from notebooks (distillation):

```python
from engine.nexus.client import get_nexus_client

def distill_notebook(notebook_uuid: str, topic: str, count: int = 20) -> list[dict]:
    """Distill Q&A pairs from a notebook into Nexus."""
    nexus = get_nexus_client()
    client = get_nlm_direct_client()
    
    # Get suggested questions
    questions = client.get_suggested_questions(notebook_uuid, hint=topic, count=count)
    
    qa_pairs = []
    for question in questions:
        answer = client.ask_question(notebook_uuid, question)
        
        # Store in Nexus Q&A cache (tier 1 for future queries)
        nexus.add_qa(question, answer, category=topic)
        qa_pairs.append({"q": question, "a": answer})
    
    return qa_pairs
```

This is the core of the compound effect: every distillation session adds to the Nexus Q&A cache, reducing future LLM calls.

---

## Scheduler Integration

| Task | Schedule | What it does |
|------|----------|-------------|
| `news-distill-nlm` | 1x/day | Distill 20 Q&A from each news notebook |
| `nlm-batch-ask` | Weekly | Batch-ask questions across all notebooks |
| `cookie-auto-refresh` | 72h | CDP cookie refresh for all accounts |
| `cookie-health-check` | Daily | Verify cookie freshness |

---

## Testing

```python
# Mock client for tests
from unittest.mock import MagicMock, patch

@patch("engine.integrations.nlm_direct_client.get_nlm_direct_client")
def test_nlm_distillation(mock_client):
    mock_client.return_value.ask_question.return_value = "Test answer"
    mock_client.return_value.get_suggested_questions.return_value = ["Q1?", "Q2?"]
    
    pairs = distill_notebook("test-uuid", "testing", count=2)
    assert len(pairs) == 2
    assert pairs[0]["a"] == "Test answer"
```

Never make real NLM calls in tests — mock at `get_nlm_direct_client()`.
