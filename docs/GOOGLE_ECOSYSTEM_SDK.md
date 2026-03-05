# Google Ecosystem SDK

> CosySim's cookie-authenticated layer over every Google service we use.
> Each client is standalone, zero cross-deps — then the Artifact Bus and skills
> compose them into compound workflows.

---

## Overview

The Google Ecosystem SDK is built on a single insight: every Google service
accepts the same browser session cookies.  One HAR capture from a logged-in
account yields all the credentials needed to talk to Drive, Sheets, Colab,
and NotebookLM programmatically — no OAuth dance, no service account, no API
key quota.

The architecture has three layers:

1. **SDK clients** — standalone, auth-encapsulated HTTP clients for each service
2. **Artifact Bus** — a unified routing layer that moves artifacts between services
3. **Skills** — `@skill`-decorated wrappers that expose every bus operation to LLM agents

```
┌─────────────────────────────────────────────────────────────────┐
│  LLM Agents / CosySim Skills                                    │
└──────────────────────────────┬──────────────────────────────────┘
                               │
              ┌────────────────▼────────────────┐
              │         Artifact Bus             │
              │  engine/integrations/artifact_bus.py │
              └──┬─────┬─────┬─────┬────────────┘
                 │     │     │     │
    ┌────────────▼┐ ┌──▼───┐ │ ┌──▼──────┐
    │ Drive SDK   │ │Sheets│ │ │ NLM SDK │
    │             │ │ SDK  │ │ │         │
    └─────────────┘ └──────┘ │ └─────────┘
                             │
              ┌──────────────┴──────────────────┐
              │         Colab SDK               │
              │  ColabClient · NotebookBuilder  │
              │  GPUManager  · VenvManager      │
              └─────────────────────────────────┘
                             │
              ┌──────────────▼──────────────────┐
              │      GoogleAccountPool          │
              │  data/accounts/pool.json        │
              └─────────────────────────────────┘
```

Account credentials live in `data/accounts/pool.json`.  Import an account
with:

```python
from engine.integrations.google_account_pool import get_account_pool
pool = get_account_pool()
pool.import_from_har("path/to/capture.har", name="nihilistcod", services=["colab", "drive", "notebooklm"])
```

---

## Google Drive Client

**File:** `engine/integrations/google_drive_client.py`

### Auth: SAPISIDHASH

Drive uses the same SAPISID cookie pattern as every other Google property.
The `Authorization` header carries up to three hashes (SAPISID, 1P, 3P) built
from the current timestamp and origin:

```python
import hashlib, time

ts = str(int(time.time()))
origin = "https://drive.google.com"
digest = hashlib.sha1(f"{ts} {sapisid} {origin}".encode()).hexdigest()
auth = f"SAPISIDHASH {ts}_{digest}"
# Plus SAPISID1PHASH and SAPISID3PHASH if those cookies are present
```

All requests target `clients6.google.com` rather than `www.googleapis.com`,
matching what the browser sends when you open drive.google.com.

### Key Methods

| Method | Purpose | Endpoint |
|--------|---------|----------|
| `list_files(folder_id, query)` | List files, optionally filtered | `GET /drive/v3/files` |
| `get_file_metadata(file_id)` | Get metadata for one file | `GET /drive/v2beta/files/{id}` |
| `download_file(file_id)` | Download raw bytes | `GET /drive/v3/files/{id}?alt=media` |
| `download_text(file_id)` | Download and decode UTF-8 | same |
| `upload_file(name, content, mime_type, folder_id)` | Create or update a file | `POST /upload/drive/v3/files?uploadType=multipart` |
| `create_folder(name, parent_id)` | Create a folder | `POST /drive/v3/files` |
| `find_or_create_folder(name, parent_id)` | Idempotent folder upsert | list + create |
| `delete_file(file_id)` | Delete file or folder | `DELETE /drive/v3/files/{id}` |
| `upload_text_to_cosysim_folder(name, content, subfolder)` | Upload to `CosySim/{subfolder}/` | multipart create |
| `make_file_accessible_to_notebooklm(file_id)` | Grant anyone-reader | `POST /drive/v3/files/{id}/permissions` |
| `get_shareable_link(file_id)` | Build shareable URL | (string build) |

### Upload/Download Flow

```python
from engine.integrations.google_drive_client import get_drive_client

drive = get_drive_client()  # uses first available account

# Upload text
result = drive.upload_text_to_cosysim_folder(
    name="experiment_results.json",
    content=json.dumps(data),
    subfolder="nexus",
)
print(result["id"], result["shareable_link"])

# Download back
raw = drive.download_text(result["id"])

# Update in place
drive.upload_file("experiment_results.json", new_content, file_id=result["id"])
```

Multipart upload format (`uploadType=multipart`) sends a single POST with a
`multipart/related` body — metadata JSON first, then file bytes, separated by
a `cosysim_boundary_{timestamp}` delimiter.

### `make_file_accessible_to_notebooklm()`

NotebookLM can only ingest Drive files that have `reader` permission set for
`type: "anyone"`.  This method posts that permission in one call:

```python
# After uploading any file that NLM needs to read:
drive.make_file_accessible_to_notebooklm(file_id)

# Then in NLM:
url = drive.get_shareable_link(file_id)
source_id = nlm_client.add_source_url(notebook_id, url)
```

The Artifact Bus calls this automatically on `_drive_to_nlm()` routes.

### Factory

```python
from engine.integrations.google_drive_client import get_drive_client

drive = get_drive_client()                    # round-robin from pool
drive = get_drive_client("nihilistcod")       # specific account
```

---

## Google Sheets Client

**File:** `engine/integrations/gsheets_client.py`

### Auth

Identical SAPISIDHASH pattern, with `origin = "https://docs.google.com"`.
Sheets v4 API at `sheets.googleapis.com` plus Drive v3 at `clients6.google.com`
for file-level operations (create, share).

### Key Methods

| Method | Purpose |
|--------|---------|
| `create_sheet(title, folder_id)` | Create new spreadsheet |
| `get_metadata(sheet_id)` | Get tabs list and properties |
| `read_rows(sheet_id, range_, include_headers)` | Read as list of dicts |
| `read_raw(sheet_id, range_)` | Read as list of lists |
| `append_rows(sheet_id, rows, sheet_name)` | Append rows, auto-header |
| `write_rows(sheet_id, rows, sheet_name, start_row)` | Overwrite from row N |
| `clear_sheet(sheet_id, sheet_name)` | Clear all values |
| `create_from_data(title, rows, folder_id)` | Create + populate in one call |
| `export_as_csv(sheet_id, sheet_name)` | Export to CSV string |
| `list_sheets(sheet_id)` | List tab names |
| `add_sheet_tab(sheet_id, tab_name)` | Add new tab |
| `make_public(sheet_id)` | Grant anyone-reader |
| `get_shareable_url(sheet_id)` | Build `?usp=sharing` URL |

### Usage Examples

```python
from engine.integrations.gsheets_client import get_sheets_client

sheets = get_sheets_client()

# Create and populate in one call
result = sheets.create_from_data(
    title="Q&A Cache Export",
    rows=[{"question": q, "answer": a, "confidence": 0.9} for q, a in pairs],
)
print(result["url"])  # https://docs.google.com/spreadsheets/d/{id}/edit

# Read back as dicts
rows = sheets.read_rows(result["id"])  # [{"question": ..., "answer": ..., ...}, ...]

# Append new rows
sheets.append_rows(result["id"], [{"question": "new Q", "answer": "new A"}])

# Export as CSV
csv_text = sheets.export_as_csv(result["id"])
```

### The NLM Read-Write Loop

Sheets acts as the structured data layer in the NLM pipeline.  The full loop:

```
NLM flashcards  → export_to_sheets() (Krh3pd rpc)
                → Google Sheet with Q&A pairs
                → add_source_url(sheet_url)  ← Gemini reads the spreadsheet
                → next NLM question builds on the structured data
                → updated answers → append_rows() → Sheet updated
                → add_source_url() again → Gemini reads the updates
```

The Sheet URL passed to `add_source_url()` gives Gemini live read access to
structured data without any intermediate file conversion.

### Factory

```python
sheets = get_sheets_client()                  # round-robin from pool
sheets = get_sheets_client("nihilistcod")     # specific account
```

---

## Colab Runtime Client

**File:** `engine/integrations/colab_client.py`

### Auth

SAPISIDHASH with `origin = "https://colab.research.google.com"`.
All RPC calls go to `colab.clients6.google.com/$rpc/google.internal.colab.v1.*`.

### AI Agent API (Gemini 3.1 Pro)

Three-call cycle for any AI task:

| Method | RPC Endpoint | Purpose |
|--------|-------------|---------|
| `create_task()` | `AIService/AgentCreateTask` | Allocate a task UUID |
| `update_task(task_id, context)` | `AIService/AgentUpdateTask` | Load context (notebook content, code) |
| `query_task(task_id)` | `AIService/AgentQueryTask` | Poll for the response |

The `ask(prompt, context, timeout)` method wraps the full cycle:

```python
from engine.integrations.colab_client import get_colab_client

colab = get_colab_client()

# Single-call AI interaction
response = colab.ask(
    prompt="Write a cell that downloads MNIST and trains a 3-layer MLP",
    context="Runtime: T4 GPU. Install torch if needed.",
    timeout=120,
)
print(response)  # returns fenced code blocks
```

Internally: `create_task()` → `update_task(task_id, full_context)` → poll
`query_task()` with exponential backoff (2s → 10s cap) until response arrives
or `timeout` is exceeded.

### Kernel Execution

WebSocket-based cell execution using the Jupyter messaging protocol over
`wss://{runtime_url}/api/kernels/{kernel_id}/channels`.

```python
# Get runtime credentials
runtime_url, proxy_token = colab.get_or_assign_runtime()
session_id, kernel_id = colab.create_kernel_session(runtime_url, proxy_token)

# Execute Python code
result = colab.execute_code(
    runtime_url=runtime_url,
    kernel_id=kernel_id,
    proxy_token=proxy_token,
    code="import torch; print(torch.cuda.get_device_name(0))",
    timeout=30,
)
print(result["output"])  # "Tesla T4"
print(result["error"])   # None
print(result["status"])  # "ok"

# High-level convenience
result = colab.run_python("print('hello')")

# Clean up
colab.close_session(runtime_url, session_id, proxy_token)
```

Messages follow Jupyter's ZMQ-over-WebSocket spec: `execute_request` sent,
then stream/execute_result/error/status messages received until `execution_state == "idle"`.

### Additional Services

```python
# Check hardware quota
info = colab.get_user_info()
# {"free_tiers": {1: ["T4"]}, "pro_tiers": {1: ["V5E1"]}, "compute_units": "6000", ...}

# List active runtimes
assignments = colab.list_assignments()
# [{"runtime_id": "...", "proxy_token": "jwt...", "runtime_url": "https://...", "ttl": "3600"}]

# Code completion
completions = colab.complete_code("import pan", cursor_pos=10)

# Follow-up suggestions
suggestions = colab.get_suggestions("I just trained a model...")
```

---

## Colab Notebook Builder

**File:** `engine/integrations/colab_notebook_builder.py`

The builder turns natural language into executed Colab notebooks.  Two
primary build paths:

### `build_and_run()` — Cell-by-Cell with Context

Full pipeline:

1. Get/assign Colab runtime
2. Create Jupyter kernel session
3. Optional: prepend a cell that loads a Drive file as input data
4. Ask AI agent to create cells for `task_description`
5. Execute cells with self-repair (up to 3 retries per failing cell)
6. For each `chain_prompt`: ask AI for follow-up cells with prior outputs injected
7. Save notebook JSON to Drive
8. Store output summary in Nexus

The self-feeding loop: prior cell **code and outputs** are appended to the
context for each subsequent AI call.  The agent sees what executed and
adjusts its next generation accordingly.

```python
from engine.integrations.colab_notebook_builder import ColabNotebookBuilder
from engine.integrations.colab_client import get_colab_client
from engine.integrations.google_drive_client import get_drive_client

builder = ColabNotebookBuilder(
    colab_client=get_colab_client(),
    drive_client=get_drive_client(),
)

execution = builder.build_and_run(
    task_description="Fine-tune Qwen2.5-1.5B on the uploaded JSONL dataset with LoRA",
    data_file_id="1xABC...",          # Drive file ID of the training data
    chain_prompts=[
        "Evaluate perplexity on the validation split",
        "Save adapter weights to /content/drive/MyDrive/CosySim/adapters/",
    ],
    save_to_drive=True,
    save_to_nexus=True,
)

print(execution.status)       # "complete"
print(execution.drive_url)    # https://drive.google.com/file/d/.../view
print(execution.total_output) # all stdout from all cells
```

### `one_shot_build()` — Mega-Prompt

Send one large brief (up to 10,000 words) to the Colab AI Agent and receive
all cells back in a single response.  Standard Drive/venv setup cells are
prepended automatically.  The assembled `.ipynb` is saved to Drive.

```python
result = builder.one_shot_build(
    brief="""
    This notebook benchmarks three quantization strategies (GPTQ-4bit, AWQ-4bit,
    BNB-4bit) on Qwen2.5-7B against a 500-sample MMLU subset.  For each:
    - Load with the appropriate library
    - Run greedy decoding on the sample set
    - Record accuracy, tokens/sec, peak VRAM
    Print a comparison table.  Save results to /content/drive/MyDrive/CosySim/outputs/benchmark.json.
    """,
    gpu_type="L4",
    packages=["auto-gptq", "autoawq", "bitsandbytes", "datasets"],
)

print(result["cells_count"])   # e.g. 12
print(result["drive_path"])    # shareable Drive URL
```

### `_repair_cell()` — Automatic Self-Repair

When a cell fails, the builder sends the failing source, its error/traceback,
and the last 3 prior cell sources to the AI agent with a strict repair prompt:

```
ORIGINAL CELL: ```python ... ```
ERROR: NameError: name 'df' is not defined
PREVIOUS CELLS (context): ... import code ... data loading code ...
RULES:
- Return ONLY the fixed cell as a single ```python ... ``` fenced block
- Do not explain anything
Fixed cell:
```

Returns only fixed source — unchanged source if the agent can't help.
Up to 3 repair attempts before skipping the cell and continuing.

### Specialised Pipelines

```python
# Fine-tune from local JSONL
execution = builder.training_notebook(
    dataset_jsonl_path="data/training/qa_pairs.jsonl",
    model_name="unsloth/Qwen2.5-1.5B-Instruct",
    epochs=3,
    lora_r=16,
)

# Research NLM answer → data analysis
execution = builder.research_to_notebook(nlm_answer_text)

# Answer questions about a CSV/DataFrame
execution = builder.data_analysis_notebook(
    data=df,
    questions=["What is the distribution of scores?", "Which model performs best?"],
)
```

---

## Colab GPU Manager

**File:** `engine/integrations/colab_gpu_manager.py`

### GPUTier Enum

```python
class GPUTier(str, Enum):
    T4   = "T4"    # free tier / cheap
    L4   = "L4"    # Pro — best price/perf
    A100 = "A100"  # Pro — heavy LoRA
    H100 = "H100"  # Pro — largest models
    FREE = "FREE"  # CPU only
```

### CU Rates

| Tier | CU/hour | VRAM (GB) | RAM (GB) | Best For |
|------|---------|-----------|---------|----------|
| FREE | 0.0 | 0 | 12.7 | CPU-only tasks |
| T4 | 0.5 | 16 | 12.7 | Inference, embeddings, <3B LoRA |
| L4 | 1.2 | 22.5 | 53.0 | 3–13B LoRA, vLLM server, video gen |
| A100 | 6.0 | 40 | 83.5 | 7–34B LoRA, image fine-tune |
| H100 | 7.0 | 80 | 83.5 | 34B+ LoRA, full fine-tune |

190 CU available: T4 = 380h · L4 = 158h · A100 = 31h · H100 = 27h

### `select_gpu(task_type, model_size)` — Automatic Selection

```python
from engine.integrations.colab_gpu_manager import get_gpu_manager, GPUTier

mgr = get_gpu_manager()

# Task-based selection
tier = mgr.select_gpu("finetune_small")      # → L4
tier = mgr.select_gpu("inference")           # → T4
tier = mgr.select_gpu("finetune_large")      # → H100

# Model-size override
tier = mgr.select_gpu("inference", model_size="13b")  # → L4 (needs 22.5GB VRAM)
tier = mgr.select_gpu("inference", model_size="7b")   # → T4 (fits in 16GB)

# Budget-aware selection
tier = mgr.select_gpu("finetune_medium", prefer_cheap=True)  # cheapest viable tier

# Budget check before starting
ok = mgr.check_budget(GPUTier.A100, estimated_hours=2.0)  # True if 12+ CU remain

# Record usage after a session
mgr.record_usage(GPUTier.L4, actual_hours=0.75, task_description="7B LoRA run")

# Summary
summary = mgr.get_usage_summary()
# {"total_budget": 190.0, "used": 12.5, "remaining": 177.5, "by_tier": {"L4": 0.9}, ...}
```

### Task → GPU Map (excerpt)

| Task Key | Default Tier |
|----------|-------------|
| `inference` | T4 |
| `inference_large` | L4 |
| `finetune_mini` (<3B LoRA) | T4 |
| `finetune_small` (3–7B LoRA) | L4 |
| `finetune_medium` (7–34B LoRA) | A100 |
| `finetune_large` (34B+ / full) | H100 |
| `vllm_server` | L4 |
| `video_generation` | L4 |
| `comfyui` | T4 |
| `whisper` | T4 |

Budget state persists to `data/accounts/cu_budget.json` and survives restarts.

---

## Colab Venv Manager

**File:** `engine/integrations/colab_venv_manager.py`

### The Drive-Backed Venv Pattern

Colab runtimes are ephemeral — packages installed in one session are gone in
the next.  Storing a full Python venv on Google Drive and activating it at
the top of every notebook saves 5–10 minutes of install time per session.

The venv is created once (`~3 GB`), uploaded to Drive, and then every
subsequent runtime just mounts Drive and prepends the site-packages to `sys.path`.

### Constants

```python
DRIVE_MOUNT_PATH = "/content/drive"
COSYSIM_DRIVE_ROOT = "/content/drive/MyDrive/CosySim"
VENV_PATH   = "/content/drive/MyDrive/CosySim/.venv"
OUTPUTS_PATH = "/content/drive/MyDrive/CosySim/outputs"
MODELS_PATH  = "/content/drive/MyDrive/CosySim/models"
DATASETS_PATH = "/content/drive/MyDrive/CosySim/datasets"
```

### `get_setup_cells()` — Standard Two-Cell Setup

```python
from engine.integrations.colab_venv_manager import get_venv_manager

mgr = get_venv_manager()
cells = mgr.get_setup_cells(extra_packages=["vllm>=0.4.0"])
# Returns [mount_drive_cell, activate_venv_cell]

# Cell 1 source (mount Drive + create dirs):
# from google.colab import drive
# drive.mount("/content/drive")
# import os
# for path in ["/content/drive/MyDrive/CosySim/outputs", ...]:
#     os.makedirs(path, exist_ok=True)
# print("[SETUP] Drive mounted, directories ready")

# Cell 2 source (activate or create venv):
# if os.path.exists(_VENV_PYTHON):
#     sys.path.insert(0, _VENV_SITE)   # activate existing
# else:
#     subprocess.run([sys.executable, "-m", "venv", _VENV_ROOT], check=True)
#     subprocess.run([_VENV_PYTHON, "-m", "pip", "install"] + packages, check=True)
```

### `cells_to_ipynb()` — Convert to `.ipynb` Format

```python
from engine.integrations.colab_venv_manager import ColabVenvManager, NotebookCell

cells = [
    NotebookCell("markdown", "## My Notebook"),
    NotebookCell("code", "print('hello')"),
]

mgr = ColabVenvManager()
nb = mgr.cells_to_ipynb(cells)
# {"nbformat": 4, "nbformat_minor": 5, "metadata": {...}, "cells": [...]}

import json
Path("notebook.ipynb").write_text(json.dumps(nb, indent=2))
```

Other cell generators: `install_packages_cell()`, `setup_ngrok_cell(port)`,
`save_outputs_cell(paths)`, `progress_header_cell(title, steps)`.

---

## NLM Direct Client

**File:** `engine/integrations/nlm_direct_client.py`

### Two-Endpoint Architecture

| Endpoint | Purpose | Auth |
|----------|---------|------|
| `GenerateFreeFormStreamed` | Multi-turn notebook Q&A (ask / streaming ask) | cookies + f.req |
| `batchexecute` | All studio ops: create, generate, export, manage | cookies + rpcids |

Both require a `bl` (build label) and `f.sid` (session fingerprint) extracted
from the NLM homepage HTML on first use and cached for the session lifetime.

### Key rpcids

| rpcid | Operation | Notes |
|-------|-----------|-------|
| `izAoDd` | Add URL/text source | URL, YouTube, Sheets, image, text paste |
| `o4cbdc` | Register file upload | Returns upload URL + source ID |
| `rLM1Ne` | Poll source processing | Returns pending source IDs |
| `hPTbtc` | List sources | All source IDs in a notebook |
| `LBwxtb` | Delete source / blog post | Multipurpose by payload shape |
| `CYK0Xb` | Create note (report) | ~10k word prompt → full document |
| `QA9ei` | Generate audio podcast | 30-min deep dive / brief / critique / debate |
| `gArtLc` | Poll / list artifacts | Get download URL when COMPLETE |
| `ciyUvf` | Generate flashcards | Instant Q&A pairs from sources |
| `R7cb6c` | Generate quiz | Multiple choice or true/false |
| `yyryJe` | Generate mind map | Nested concept JSON tree |
| `Krh3pd` | Export to Sheets | Returns live Google Sheet URL |
| `tr032e` | Source summary | Gemini summary of one source |
| `ub2Bae` | List notebooks | All notebooks in account |
| `s0tc2d` | Rename notebook | Update display name |

### Core Usage

```python
from engine.integrations.nlm_direct_client import get_nlm_direct_client

client = get_nlm_direct_client()  # singleton, uses pool.json

# Add sources
source_id = client.add_source_url(nb_id, "https://arxiv.org/abs/2312.11805")
source_id = client.add_source_text(nb_id, "My Document", long_text)
source_id = client.add_source_file(nb_id, "data/chart.png")  # multimodal

# Ask questions
answer = client.ask(nb_id, source_ids=[source_id], question="What are the key findings?")

# Streaming
for chunk in client.ask_streaming(nb_id, source_ids, "Summarise chapter 3"):
    print(chunk, end="", flush=True)

# Studio operations
flashcards = client.generate_flashcards(nb_id)
# [{"question": "What is...", "answer": "..."}, ...]

report = client.create_note(nb_id, "Write a detailed analysis of all training curves")
# {"id": "...", "title": "Analysis", "content": "## Training Curves\n..."}

job_id, artifact_id = client.generate_audio(nb_id, "Focus on the novel contributions")
artifact = client.poll_artifact(nb_id, artifact_id, max_wait=600)
path = client.download_audio(artifact, "data/nlm_audio/podcast.mp3")

sheet_url = client.export_to_sheets(artifact_id="...", title="Q&A Data")
```

### The Self-Referential Audio Loop

Each audio generation is ~30 minutes of dense Gemini conversation —
12,000–15,000 words when transcribed.  Feeding that back as a source makes
the next generation deeper:

```python
# Round 1: first podcast
_, art_id = client.generate_audio(nb_id, "Explain the architecture in depth")
art = client.poll_artifact(nb_id, art_id)
audio_path = client.download_audio(art, "data/nlm_audio/round1.mp3")

# Add the podcast back as a source (Gemini will LISTEN to it)
client.add_source_file(nb_id, audio_path, "audio/mpeg")

# Round 2: builds on everything the first podcast covered
_, art_id2 = client.generate_audio(nb_id, "Now cover everything the first podcast missed")
art2 = client.poll_artifact(nb_id, art_id2)
audio_path2 = client.download_audio(art2, "data/nlm_audio/round2.mp3")
client.add_source_file(nb_id, audio_path2, "audio/mpeg")

# Round 3 → typically 300+ total Q&A pairs when all three are distilled
```

### The Knowledge Flywheel

Two-call compound: `create_note()` (CYK0Xb) generates a full analysis
document, then `ask()` (GenerateFreeFormStreamed) extracts 60 structured
Q&A pairs from it in JSON format:

```python
report, qa_pairs = client.run_knowledge_flywheel(
    notebook_id=nb_id,
    analysis_prompt="""
    Perform a comprehensive analysis of all training runs.  Cover:
    - Hyperparameter sensitivity
    - Loss curves and overfitting signals
    - Comparison to baseline
    ...
    """,
)

# Store pairs in Nexus
from engine.nexus.client import get_nexus_client
nexus = get_nexus_client()
for pair in qa_pairs:
    nexus.add_qa(pair["question"], pair["answer"], category="ml_experiments")
```

Supported audio types: `AUDIO_DEEP_DIVE=1` (30 min) · `AUDIO_BRIEF=2` (5 min)
· `AUDIO_CRITIQUE=3` · `AUDIO_DEBATE=4`.

---

## Artifact Bus

**File:** `engine/integrations/artifact_bus.py`

The bus abstracts away all transport logic between services.  Every service
can route to every other service through `handoff()` or `pipeline()`.

### Service Enum

```python
class ArtifactService(str, Enum):
    LOCAL  = "local"
    DRIVE  = "drive"
    COLAB  = "colab"
    NLM    = "nlm"
    SHEETS = "sheets"
    NEXUS  = "nexus"
```

### Route Matrix

| From → To | Transport |
|-----------|-----------|
| LOCAL → DRIVE | multipart upload |
| LOCAL → NLM | via Drive (make_public + add_source_url) |
| LOCAL → NEXUS | read text + add_entry |
| DRIVE → NLM | make_public + add_source_url |
| DRIVE → COLAB | kernel cell that mounts Drive + copies file |
| DRIVE → NEXUS | download_text + add_entry |
| DRIVE → SHEETS | download JSON/CSV + create_sheet + append_rows |
| COLAB → DRIVE | kernel reads file via base64 + upload |
| COLAB → NLM | via Drive intermediary |
| COLAB → SHEETS | Colab→Drive then Drive→Sheets |
| COLAB → NEXUS | kernel reads text + add_entry |
| NLM → COLAB | inject content as Python variable in kernel |
| NLM → DRIVE | local audio download + upload |
| NLM → NEXUS | generate_flashcards + add_qa (or add_entry) |
| SHEETS → NLM | add spreadsheet URL as source |
| SHEETS → NEXUS | read_rows + JSON + add_entry |

### `handoff()` Usage

```python
from engine.integrations.artifact_bus import get_artifact_bus, Artifact, ArtifactService

bus = get_artifact_bus("nihilistcod")

# Upload local file to Drive, then add to NLM notebook
local = Artifact(
    service=ArtifactService.LOCAL,
    ref="data/charts/loss_curve.png",
    artifact_type="image",
    local_path="data/charts/loss_curve.png",
    metadata={"name": "loss_curve.png"},
)

drive_art = bus.handoff(local, ArtifactService.DRIVE, make_public=True)
nlm_art = bus.handoff(drive_art, ArtifactService.NLM, notebook_id="abc-123")
```

### `pipeline()` — Multi-Hop

```python
# Audio file: local → Drive → NLM → Nexus
audio_art = Artifact(
    service=ArtifactService.LOCAL,
    ref="data/nlm_audio/round2.mp3",
    artifact_type="audio",
    local_path="data/nlm_audio/round2.mp3",
    metadata={"name": "round2.mp3"},
)

history = bus.pipeline(
    audio_art,
    route=[ArtifactService.DRIVE, ArtifactService.NLM, ArtifactService.NEXUS],
    kwargs_per_hop=[
        {"make_public": True, "subfolder": "nlm_audio"},
        {"notebook_id": "abc-123"},
        {"title": "Round 2 Audio Distillation", "category": "knowledge"},
    ],
)
# history[0] = original local artifact
# history[1] = Drive artifact
# history[2] = NLM source artifact
# history[3] = Nexus artifact
```

### `full_knowledge_loop()` — Compound Workflow

```python
results = bus.full_knowledge_loop(
    notebook_id="abc-123",
    colab_output_path="/content/benchmark_results.json",
    runtime_url=runtime_url,
    kernel_id=kernel_id,
    proxy_token=proxy_token,
    nexus_category="benchmarks",
)
# Steps: colab→drive→nlm, nlm→nexus (flashcards)
# {"steps": [...], "nexus_ref": "...", "qa_count": 42}
```

### Factory

```python
bus = get_artifact_bus("nihilistcod")
# Wires up: drive_client, nlm_client, colab_client, sheets_client, nexus_client
# All from the named account in pool.json
```
