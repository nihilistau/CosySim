# CosySim Colab Pipeline

End-to-end integration: **NotebookLM → Google Drive → Colab → Drive → Nexus**

---

## Architecture

```
┌──────────────┐     research      ┌─────────────────┐
│  NotebookLM  │ ─────────────────▶│  nlm_direct_    │
│  (Gemini 2)  │ ◀─── grounded ─── │  client.py      │
└──────────────┘      answers      └────────┬────────┘
                                            │ nlm_answer text
                                            ▼
                                   ┌─────────────────┐
                                   │  Google Drive   │  upload_text_to_cosysim_folder()
                                   │  (clients6.g.c) │  CosySim/research/nlm_*.txt
                                   └────────┬────────┘
                                            │ file_id
                                            ▼
┌──────────────┐  AgentCreateTask  ┌─────────────────┐
│  Colab AI    │ ◀─────────────── │  Colab          │
│  (Gemini 3.1 │  AgentUpdateTask  │  Notebook       │
│   Pro)       │ ─── cells ──────▶ │  Builder        │
└──────────────┘                   └────────┬────────┘
                                            │ cells
                                            ▼
┌──────────────┐  execute_code     ┌─────────────────┐
│  Colab       │ ◀─────────────── │  Jupyter        │
│  Runtime     │ ─── output ─────▶ │  Kernel         │
│  (T4/A100)   │   (WebSocket)     │  (WebSocket)    │
└──────────────┘                   └────────┬────────┘
                                            │ outputs
                                            ▼
                                   ┌─────────────────┐
                                   │  Google Drive   │  CosySim/notebooks/*.ipynb
                                   └────────┬────────┘
                                            │ summary
                                            ▼
                                   ┌─────────────────┐
                                   │     Nexus       │  category="system", content_type="note"
                                   └─────────────────┘
```

---

## Components

### `engine/integrations/google_drive_client.py`

Drive API via `clients6.google.com`. Uses the same Google session cookies and
SAPISIDHASH auth as the Colab client.

Key methods:

| Method | Description |
|--------|-------------|
| `list_files(folder_id, query, page_size)` | List files matching a query |
| `get_file_metadata(file_id)` | Fetch metadata for a file |
| `download_file(file_id)` → `bytes` | Download raw bytes |
| `download_text(file_id)` → `str` | Download and decode UTF-8 |
| `upload_file(name, content, mime_type, folder_id, file_id)` | Create or update file |
| `create_folder(name, parent_id)` | Create a Drive folder |
| `delete_file(file_id)` | Delete file or folder |
| `find_or_create_folder(name, parent_id)` → `str` | Idempotent folder lookup |
| `upload_text_to_cosysim_folder(name, content, subfolder)` | Upload to CosySim/subfolder/ |
| `get_shareable_link(file_id)` → `str` | Build shareable URL |
| `make_file_accessible_to_notebooklm(file_id)` | Set "anyone with link can read" |

```python
from engine.integrations.google_drive_client import get_drive_client

drive = get_drive_client()
meta = drive.upload_text_to_cosysim_folder("report.txt", content, subfolder="nexus")
print(meta["shareable_link"])  # https://drive.google.com/file/d/.../view
```

### `engine/integrations/colab_notebook_builder.py`

The crown jewel. Builds Colab notebooks from natural language using the Colab AI
Agent (Gemini 3.1 Pro), then executes them via the Jupyter kernel protocol.

```
ColabNotebookBuilder
├── ask_agent_to_create_cell(prompt, context, previous_cells)
│     Calls ColabClient.ask() with structured prompt
│     Extracts ```python ... ``` fenced blocks as NotebookCell objects
│
├── execute_cells(cells, runtime_url, kernel_id, proxy_token)
│     Calls ColabClient.execute_code() for each code cell
│     Populates cell.outputs and cell.error
│
└── build_and_run(task_description, ...) -> NotebookExecution
      1. get_or_assign_runtime()
      2. create_kernel_session()
      3. [optional] data load cell
      4. ask_agent_to_create_cell(task_description)
      5. execute_cells()
      6. for each chain_prompt: create + execute cells
      7. [optional] save .ipynb to Drive
      8. [optional] store summary in Nexus
      9. close_session()
```

### `engine/skills/builtin/colab_skills.py` (extended)

New @skill tools available to LLM agents:

| Skill | Description |
|-------|-------------|
| `colab_build_notebook(task, context, chain_prompts)` | Build + run a notebook |
| `drive_upload(name, content, subfolder)` | Upload to Drive |
| `drive_download(file_id)` | Download from Drive |
| `drive_list(subfolder)` | List CosySim folder |
| `nlm_to_colab_pipeline(nlm_answer, analysis_prompt)` | Full research pipeline |
| `colab_finetune(dataset_path, model_name, epochs)` | Offload LoRA training |

---

## Adding Accounts via HAR

1. Open Chrome DevTools → Network tab
2. Navigate to `colab.research.google.com` and log in
3. Right-click any request → Save as HAR with content
4. Import into the account pool:

```python
from engine.integrations.google_account_pool import get_account_pool

pool = get_account_pool()
pool.import_from_har(
    har_path="path/to/colab.har",
    account_name="my-account",
    services=["colab", "drive", "notebooklm"],
)
pool.save()
```

The same account credentials work for Colab, Drive, and NotebookLM — they all
use the same Google session cookies (`SAPISID`, `__Secure-1PAPISID`, etc.).

---

## Available Gemini Models

Colab AI Agent routes to these models based on task complexity:

| Model | Use case |
|-------|----------|
| Gemini 2.0 Flash Lite | Fast, lightweight queries |
| Gemini 2.5 Flash | Balanced speed/quality |
| Gemini 2.5 Pro | Complex reasoning, code gen |
| Gemini 3.1 Pro | Deep analysis, notebook generation |

The model is selected by the Colab AI service — you send the prompt and get the
best available response. `ColabClient.ask()` uses `[25, 5]` as the model hint
(Gemini 3.1 Pro tier) in the `AgentCreateTask` payload.

---

## Scheduler Task

Task `colab-pipeline-sync` (ID 46) runs daily at 04:00:

```
For each Nexus entry with category="improvement" (up to 10):
  1. Ask NLM for improvement suggestions
  2. Upload suggestions to Drive
  3. Build Colab analysis notebook
  4. Store Colab output in Nexus as category="training"
```

To run manually:
```powershell
python -m engine.nexus.scheduler_daemon run colab-pipeline-sync
```

---

## Example: Training Pipeline Offload

```python
from engine.integrations.colab_notebook_builder import get_notebook_builder

builder = get_notebook_builder()
if builder:
    execution = builder.training_notebook(
        dataset_jsonl_path="data/training/router_v2.jsonl",
        model_name="unsloth/Qwen2.5-1.5B-Instruct",
        epochs=3,
        lora_r=16,
    )
    print(f"Status: {execution.status}")
    print(f"Notebook: {execution.drive_url}")
    print(f"Output:\n{execution.total_output[:500]}")
```

The builder chains three AI-generated cells:
1. Install unsloth, configure LoRA, run training
2. Evaluate model perplexity
3. Save adapter weights to Drive

---

## Example: NLM Research → Analysis Notebook

```python
from engine.integrations.nlm_direct_client import get_nlm_direct_client
from engine.integrations.colab_notebook_builder import get_notebook_builder

# Step 1: get research from NotebookLM
nlm = get_nlm_direct_client()
answer = nlm.ask(
    notebook_id="your-notebook-uuid",
    source_ids=["source-uuid-1", "source-uuid-2"],
    question="What are the key trends in LLM inference optimization?",
)

# Step 2: build analysis notebook
builder = get_notebook_builder()
if builder:
    execution = builder.research_to_notebook(
        nlm_answer=answer,
        analysis_prompt="Create visualization cells showing the key metrics and trends",
    )
    print(f"Notebook: {execution.drive_url}")
```

Or via the skill:
```python
result = nlm_to_colab_pipeline(
    nlm_answer=answer,
    analysis_prompt="Visualize the data and produce a summary table",
)
print(result)
```

---

## File Organisation in Drive

```
CosySim/
├── notebooks/      # Generated .ipynb files
├── research/       # NLM research text exports
├── training/       # Training JSONL datasets
├── data/           # Analysis CSV files
├── adapters/       # LoRA adapter weights (from Colab)
└── nexus/          # General Nexus exports
```

All files are uploaded with `make_file_accessible_to_notebooklm()` when they
are intended as NotebookLM sources, making them accessible via shareable link.
