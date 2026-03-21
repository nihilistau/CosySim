# External APIs Reference

> Consolidated reference for all Google service APIs used by CosySim.
> Auto-generated catalog data from ARGUS on 2026-03-19.

---

## Table of Contents

- [Overview](#overview)
- [Authentication](#authentication)
- [ARGUS Catalog Summary](#argus-catalog-summary)
- [AI Studio (MakerSuite)](#ai-studio-makersuite)
- [Gemini (BardChatUi)](#gemini-bardchatui)
- [Google Colab](#google-colab)
- [Apps Script](#apps-script)
- [Google Workspace](#google-workspace)
- [Google Ecosystem SDK](#google-ecosystem-sdk)

---

## Overview

CosySim's external API layer is built on a single insight: every Google service
accepts the same browser session cookies.  One HAR capture from a logged-in
account yields all the credentials needed to talk to Drive, Sheets, Colab,
NotebookLM, AI Studio, and Apps Script programmatically — no OAuth dance, no
service account, no API key quota.

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

## Authentication

### SAPISIDHASH (all Google services)

Every Google property uses the same SAPISID cookie pattern:

```python
import hashlib, time

ts = str(int(time.time()))
origin = "https://aistudio.google.com"  # or drive.google.com, docs.google.com, etc.
digest = hashlib.sha1(f"{ts} {sapisid} {origin}".encode()).hexdigest()
auth = f"SAPISIDHASH {ts}_{digest}"
# Plus SAPISID1PHASH and SAPISID3PHASH if those cookies are present
```

### Account Tiers

| Account | Tier | Notes |
|---------|------|-------|
| nihilistcod | Free | Can set `[2]` tier marker (client-side gating) |
| knack112358 | Pro | Full Pro tier access |

---

## ARGUS Catalog Summary

**Total baseline operations:** 184 | **Observed in crawls:** 200 | **New discoveries:** 152

| Service | Baseline | Seen | New | Coverage |
|---------|----------|------|-----|----------|
| NotebookLM (batchexecute) | 49 | 33 | 2 | 67% |
| Gemini (BardChatUi) | 36 | 17 | 0 | 47% |
| AI Studio (MakerSuite gRPC) | 0 | 150 | 150 | -- |
| Google Colab (gRPC) | 10 | 0 | 0 | 0% |
| Apps Script (batchexecute) | 14 | 0 | 0 | 0% |
| Workspace Gemini (mixed) | 49 | 0 | 0 | 0% |
| NLM gRPC (proto) | 2 | 0 | 0 | 0% |
| Heap-Discovered (unconfirmed) | 24 | 0 | 0 | 0% |

### gRPC Service Paths

```
AI Studio:  google.internal.alkali.applications.makersuite.v1.MakerSuiteService/{Method}
Applets:    google.alkali.boq.makersuite.makersuiteappletcontrol.proto.MakersuiteAppletControlService/{Method}
Colab AI:   google.internal.colab.v1.AIService/{Method}
Colab RT:   google.internal.colab.v1.RuntimeService/{Method}
NLM gRPC:   google.internal.labs.tailwind.orchestration.v1.LabsTailwindOrchestrationService/{Method}
```

### Cross-References

- [NLM API Reference](NLM_API_REFERENCE.md) — NotebookLM is documented separately (49 rpcids, production use)

---

## AI Studio (MakerSuite)

**Coverage:** 150/251 methods observed

### Protocol

**Endpoint:** `https://alkalimakersuite-pa.clients6.google.com/$rpc/google.internal.alkali.applications.makersuite.v1.MakerSuiteService/{Method}`

**Auth:** `Authorization: SAPISIDHASH <ts>_<sha1>` + session cookies

**Format:** gRPC-web with binary proto encoding OR JSON mode

### Methods — Cancel

| Method | Status | Observed | Last Seen |
|--------|--------|----------|-----------|
| `CancelCodeAssistantOfflineGeneration` | -- | 0 | never |
| `CancelTuningJob` | -- | 0 | never |

### Methods — Check

| Method | Status | Observed | Last Seen |
|--------|--------|----------|-----------|
| `CheckCloudProjectForTermsOfService` | -- | 0 | never |
| `CheckCloudRunService` | -- | 0 | never |
| `CheckImage` | -- | 0 | never |

### Methods — Count

| Method | Status | Observed | Last Seen |
|--------|--------|----------|-----------|
| `CountSessionTurns` | -- | 0 | never |
| `CountTokens` | active | 21 | 2026-03-05 |

### Methods — Create

| Method | Status | Observed | Last Seen |
|--------|--------|----------|-----------|
| `CreateApplet` | -- | 0 | never |
| `CreateCloudApiKey` | -- | 0 | never |
| `CreateCloudProject` | -- | 0 | never |
| `CreateCloudRunService` | -- | 0 | never |
| `CreateContextCache` | -- | 0 | never |
| `CreateDataset` | -- | 0 | never |
| `CreateGitHubRepository` | -- | 0 | never |
| `CreateInteraction` | -- | 0 | never |
| `CreatePrompt` | active | 5 | 2026-03-05 |
| `CreateSession` | -- | 0 | never |
| `CreateTunedModel` | -- | 0 | never |

### Methods — Delete

| Method | Status | Observed | Last Seen |
|--------|--------|----------|-----------|
| `DeleteApplet` | -- | 0 | never |
| `DeleteCloudApiKey` | -- | 0 | never |
| `DeleteCloudRunService` | -- | 0 | never |
| `DeleteContextCache` | -- | 0 | never |
| `DeleteDataset` | -- | 0 | never |
| `DeletePrompt` | -- | 0 | never |
| `DeleteSession` | -- | 0 | never |
| `DeleteTunedModel` | -- | 0 | never |
| `DeleteUploadedFile` | -- | 0 | never |

### Methods — Export / Fetch

| Method | Status | Observed | Last Seen |
|--------|--------|----------|-----------|
| `ExportDataset` | -- | 0 | never |
| `FetchMetricTimeSeries` | active | 37 | 2026-03-08 |

### Methods — Generate

| Method | Status | Observed | Last Seen |
|--------|--------|----------|-----------|
| `GenerateAccessToken` | active | 142 | 2026-03-17 |
| `GenerateCodeAssistantSuggestionChips` | active | 34 | 2026-03-05 |
| `GenerateContent` | active | 7 | 2026-03-05 |
| `GenerateFunctionCallAnswer` | -- | 0 | never |
| `GenerateGitHubCommitMessage` | -- | 0 | never |
| `GenerateImage` | -- | 0 | never |
| `GenerateTitle` | active | 5 | 2026-03-05 |
| `GenerateVideo` | -- | 0 | never |

### Methods — Get

| Method | Status | Observed | Last Seen |
|--------|--------|----------|-----------|
| `GetAnnouncementBanner` | -- | 0 | never |
| `GetApplet` | active | 18 | 2026-03-08 |
| `GetAppletCloudRunServiceLogs` | -- | 0 | never |
| `GetAppletOutputMetadata` | -- | 0 | never |
| `GetCodeAssistantSnapshot` | active | 10 | 2026-03-05 |
| `GetDataset` | -- | 0 | never |
| `GetExtension` | -- | 0 | never |
| `GetFeatureFlags` | -- | 0 | never |
| `GetGenerateVideoOperation` | -- | 0 | never |
| `GetGitHubAuthStatus` | -- | 0 | never |
| `GetGitHubSettings` | -- | 0 | never |
| `GetGitHubStatus` | -- | 0 | never |
| `GetGroundingPassage` | -- | 0 | never |
| `GetImFeelingLuckyOptions` | -- | 0 | never |
| `GetLoggingContext` | active | 62 | 2026-03-08 |
| `GetModel` | -- | 0 | never |
| `GetPrepayEligibility` | -- | 0 | never |
| `GetProjectUsageLimit` | -- | 0 | never |
| `GetPrompt` | -- | 0 | never |
| `GetSample` | -- | 0 | never |
| `GetSession` | -- | 0 | never |
| `GetSessionTurn` | -- | 0 | never |
| `GetSharedPrompt` | -- | 0 | never |
| `GetStarterPrompts` | -- | 0 | never |
| `GetSurvey` | -- | 0 | never |
| `GetTunedModel` | -- | 0 | never |
| `GetTuningJob` | -- | 0 | never |
| `GetUploadedFile` | -- | 0 | never |
| `GetUserPreferences` | active | 62 | 2026-03-08 |
| `GetUserRestrictions` | active | 15 | 2026-03-08 |
| `GetVersionInfo` | -- | 0 | never |

### Methods — Import

| Method | Status | Observed | Last Seen |
|--------|--------|----------|-----------|
| `ImportGitHubRepository` | -- | 0 | never |
| `ImportProject` | -- | 0 | never |

### Methods — List

| Method | Status | Observed | Last Seen |
|--------|--------|----------|-----------|
| `ListAppletRunConfigurations` | -- | 0 | never |
| `ListAppletTemplates` | -- | 0 | never |
| `ListApplets` | active | 4 | 2026-03-05 |
| `ListBillingAccounts` | -- | 0 | never |
| `ListCloudApiKeys` | active | 8 | 2026-03-05 |
| `ListCloudProjects` | active | 12 | 2026-03-08 |
| `ListCodeAssistantConfigurations` | active | 62 | 2026-03-08 |
| `ListCodeAssistantFeatures` | active | 36 | 2026-03-08 |
| `ListCodeAssistantOfflineGenerations` | active | 18 | 2026-03-08 |
| `ListCodeGenSuggestionCards` | active | 10 | 2026-03-05 |
| `ListContextCaches` | -- | 0 | never |
| `ListDatasets` | -- | 0 | never |
| `ListDriveApplets` | -- | 0 | never |
| `ListExtensions` | -- | 0 | never |
| `ListGitHubRepositories` | -- | 0 | never |
| `ListImportedProjects` | active | 9 | 2026-03-08 |
| `ListModels` | active | 78 | 2026-03-08 |
| `ListPromos` | active | 4 | 2026-03-05 |
| `ListPrompts` | active | 125 | 2026-03-08 |
| `ListRecentApplets` | active | 74 | 2026-03-08 |
| `ListSessionTurns` | -- | 0 | never |
| `ListSessions` | -- | 0 | never |
| `ListTunedModels` | -- | 0 | never |
| `ListTuningJobs` | -- | 0 | never |
| `ListUnsetAppletSecrets` | active | 44 | 2026-03-08 |
| `ListUploadedFiles` | -- | 0 | never |

### Methods — Stream

| Method | Status | Observed | Last Seen |
|--------|--------|----------|-----------|
| `StreamBidiGenerateContent` | -- | 0 | never |
| `StreamCodeAssistantOfflineGeneration` | active | 26 | 2026-03-05 |
| `StreamExtractVideoFrames` | -- | 0 | never |
| `StreamGenerateContent` | -- | 0 | never |

### Methods — Update

| Method | Status | Observed | Last Seen |
|--------|--------|----------|-----------|
| `UpdateCloudProject` | -- | 0 | never |
| `UpdateCloudRunService` | -- | 0 | never |
| `UpdateDataset` | -- | 0 | never |
| `UpdateProjectUsageLimit` | -- | 0 | never |
| `UpdatePrompt` | -- | 0 | never |

### Methods — Other

| Method | Status | Observed | Last Seen |
|--------|--------|----------|-----------|
| `AuthenticateGitHub` | -- | 0 | never |
| `BidiGenerateContent` | -- | 0 | never |
| `BulkDeleteSessionTurns` | -- | 0 | never |
| `CodeAssistant` | -- | 0 | never |
| `CodeAssistantOffline` | active | 28 | 2026-03-05 |
| `ComputeStagedGitHubDiff` | -- | 0 | never |
| `ConnectApplet` | -- | 0 | never |
| `DisconnectApplet` | -- | 0 | never |
| `EmbedContent` | -- | 0 | never |
| `EnhancePrompt` | -- | 0 | never |
| `GeminiSpeechToText` | -- | 0 | never |
| `GoogleSearch` | -- | 0 | never |
| `LoadBundledApplet` | -- | 0 | never |
| `LoadCodeAssistantInteractionHistory` | active | 18 | 2026-03-08 |
| `LoadCodeAssistantSnapshots` | -- | 0 | never |
| `LoadDriveApplet` | -- | 0 | never |
| `Log` | active | 26 | 2026-03-05 |
| `ProvisionAndInitializeApplet` | active | 28 | 2026-03-05 |
| `ProxyStreamedCall` | -- | 0 | never |
| `ProxyUnaryCall` | active | 4 | 2026-03-05 |
| `ProxyUnaryFileApiCall` | -- | 0 | never |
| `PushNewCommit` | -- | 0 | never |
| `QueryCodeSearch` | -- | 0 | never |
| `RecordSessionTurnFeedback` | -- | 0 | never |
| `RecordSurveyResponse` | -- | 0 | never |
| `RerunTuningJob` | -- | 0 | never |
| `SaveApplet` | active | 26 | 2026-03-05 |
| `SaveDriveApplet` | -- | 0 | never |
| `SharePrompt` | -- | 0 | never |
| `StoreRecentApplet` | active | 41 | 2026-03-08 |
| `UpgradeAndDisablePrepay` | -- | 0 | never |
| `UploadScs` | -- | 0 | never |
| `batchGenerateContent` | -- | 0 | never |

---

## Gemini (BardChatUi)

**Coverage:** 17/31 rpcids observed

### Protocol

**Endpoint:** `https://gemini.google.com/_/BardFrontendService/data/batchexecute`

**Format:** Same as NLM batchexecute

**Special:** `NXpLKc` bridges to NLM ListLinkedNotebooks

### RPC Methods

| rpcid | Description | Status | Observed | Last Seen |
|-------|-------------|--------|----------|-----------|
| `ku4Jyf` | Code execution request | active | 11 | 2026-03-08 |
| `K4WWud` | Conversation management — list, create, delete | active | 7 | 2026-03-08 |
| `mMEAEd` | CountTokens | -- | 0 | -- |
| `VUBhEd` | CreateCachedContent | -- | 0 | -- |
| `BgXnQc` | CreateFile | -- | 0 | -- |
| `sPOurf` | DeleteCachedContent | -- | 0 | -- |
| `qVSQ5c` | DeleteFile | -- | 0 | -- |
| `L5adhe` | Draft / edit message — large state initialization | active | 97 | 2026-03-08 |
| `MaZiqc` | Extension/plugin interaction | active | 14 | 2026-03-08 |
| `ozz5Z` | Feature flags / account state (shared with NLM) | active | 7 | 2026-03-08 |
| `jKHnxe` | GenerateContent | -- | 0 | -- |
| `ESY5D` | Get conversation history / feature flags list | active | 72 | 2026-03-08 |
| `NXpLKc` | Get linked notebooks (cross-product bridge) | active | 2 | 2026-03-05 |
| `XqA3Ic` | Get storybook detail — fetch specific gem by ID | -- | 0 | never |
| `sJBwce` | Get subscription tiers — Pro/Free tier info | -- | 0 | never |
| `jPv1oc` | GetCachedContent | -- | 0 | -- |
| `ozVbQb` | GetFile | -- | 0 | -- |
| `XqsOBb` | GetModel | -- | 0 | -- |
| `jGArJ` | List my content — filtered /mystuff | -- | 0 | never |
| `ZKcapf` | List saved info — paginated saved content | -- | 0 | never |
| `HcT8bb` | List storybook gems | -- | 0 | never |
| `dXH9nb` | ListCachedContents | -- | 0 | -- |
| `mfvMVb` | ListFiles | -- | 0 | -- |
| `k9yDXd` | ListModels | -- | 0 | -- |
| `DYBcR` | Locale / language preferences (shared with NLM) | active | 7 | 2026-03-08 |
| `otAQ7b` | Main chat generation — send message, get response | active | 7 | 2026-03-08 |
| `CNgdBe` | Model selection / configuration | active | 7 | 2026-03-08 |
| `boaYGb` | ProxyUnaryCall | -- | 0 | -- |
| `GPRiHf` | Response rating / feedback | active | 7 | 2026-03-08 |
| `qpEbW` | Search conversation history | active | 11 | 2026-03-08 |
| `aPya6c` | Session initialization / heartbeat | active | 70 | 2026-03-08 |
| `PCck7e` | Share conversation / gem | active | 20 | 2026-03-08 |
| `r7Bvze` | StreamGenerateContent | -- | 0 | -- |
| `maGuAc` | Upload attachment / file | active | 14 | 2026-03-08 |
| `cYRIkd` | User preferences / settings | active | 7 | 2026-03-08 |
| `o30O0e` | User profile fetch (contacts/identity) | active | 7 | 2026-03-08 |

---

## Google Colab

**Coverage:** 0/10 methods observed

### Protocol

**Endpoint:** `https://colab.research.google.com/$rpc/google.internal.colab.v1.{Service}/{Method}`

**Auth:** Session cookies + `X-Goog-AuthUser` header

**Format:** gRPC-web binary proto

### ColabService Methods

| Method | Status | Observed | Last Seen |
|--------|--------|----------|-----------|
| `AgentCreateTask` | -- | 0 | never |
| `AgentQuerySuggestions` | -- | 0 | never |
| `AgentQueryTask` | -- | 0 | never |
| `AgentUpdateTask` | -- | 0 | never |
| `CompleteCode` | -- | 0 | never |
| `ExecuteCell` | -- | 0 | never |
| `GetRuntimeProxyToken` | -- | 0 | never |
| `GetUserInfo` | -- | 0 | never |
| `ListAssignments` | -- | 0 | never |
| `SmartPaste` | -- | 0 | never |

### Colab Runtime Client

**File:** `engine/integrations/colab_client.py`

**Auth:** SAPISIDHASH with `origin = "https://colab.research.google.com"`.
All RPC calls go to `colab.clients6.google.com/$rpc/google.internal.colab.v1.*`.

#### AI Agent API (Gemini 3.1 Pro)

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

response = colab.ask(
    prompt="Write a cell that downloads MNIST and trains a 3-layer MLP",
    context="Runtime: T4 GPU. Install torch if needed.",
    timeout=120,
)
print(response)  # returns fenced code blocks
```

Internally: `create_task()` -> `update_task(task_id, full_context)` -> poll
`query_task()` with exponential backoff (2s -> 10s cap) until response arrives
or `timeout` is exceeded.

#### Kernel Execution

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

#### Additional Services

```python
info = colab.get_user_info()
# {"free_tiers": {1: ["T4"]}, "pro_tiers": {1: ["V5E1"]}, "compute_units": "6000", ...}

assignments = colab.list_assignments()
# [{"runtime_id": "...", "proxy_token": "jwt...", "runtime_url": "https://...", "ttl": "3600"}]

completions = colab.complete_code("import pan", cursor_pos=10)
suggestions = colab.get_suggestions("I just trained a model...")
```

### Colab Notebook Builder

**File:** `engine/integrations/colab_notebook_builder.py`

#### `build_and_run()` — Cell-by-Cell with Context

Full pipeline:

1. Get/assign Colab runtime
2. Create Jupyter kernel session
3. Optional: prepend a cell that loads a Drive file as input data
4. Ask AI agent to create cells for `task_description`
5. Execute cells with self-repair (up to 3 retries per failing cell)
6. For each `chain_prompt`: ask AI for follow-up cells with prior outputs injected
7. Save notebook JSON to Drive
8. Store output summary in Nexus

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
    data_file_id="1xABC...",
    chain_prompts=[
        "Evaluate perplexity on the validation split",
        "Save adapter weights to /content/drive/MyDrive/CosySim/adapters/",
    ],
    save_to_drive=True,
    save_to_nexus=True,
)
```

#### `one_shot_build()` — Mega-Prompt

Send one large brief (up to 10,000 words) to the Colab AI Agent and receive
all cells back in a single response.

```python
result = builder.one_shot_build(
    brief="...",
    gpu_type="L4",
    packages=["auto-gptq", "autoawq", "bitsandbytes", "datasets"],
)
```

#### `_repair_cell()` — Automatic Self-Repair

When a cell fails, the builder sends the failing source, its error/traceback,
and the last 3 prior cell sources to the AI agent with a strict repair prompt.
Up to 3 repair attempts before skipping.

#### Specialised Pipelines

```python
execution = builder.training_notebook(
    dataset_jsonl_path="data/training/qa_pairs.jsonl",
    model_name="unsloth/Qwen2.5-1.5B-Instruct",
    epochs=3, lora_r=16,
)

execution = builder.research_to_notebook(nlm_answer_text)

execution = builder.data_analysis_notebook(
    data=df,
    questions=["What is the distribution of scores?", "Which model performs best?"],
)
```

### Colab GPU Manager

**File:** `engine/integrations/colab_gpu_manager.py`

#### GPUTier Enum

```python
class GPUTier(str, Enum):
    T4   = "T4"    # free tier / cheap
    L4   = "L4"    # Pro — best price/perf
    A100 = "A100"  # Pro — heavy LoRA
    H100 = "H100"  # Pro — largest models
    FREE = "FREE"  # CPU only
```

#### CU Rates

| Tier | CU/hour | VRAM (GB) | RAM (GB) | Best For |
|------|---------|-----------|---------|----------|
| FREE | 0.0 | 0 | 12.7 | CPU-only tasks |
| T4 | 0.5 | 16 | 12.7 | Inference, embeddings, <3B LoRA |
| L4 | 1.2 | 22.5 | 53.0 | 3-13B LoRA, vLLM server, video gen |
| A100 | 6.0 | 40 | 83.5 | 7-34B LoRA, image fine-tune |
| H100 | 7.0 | 80 | 83.5 | 34B+ LoRA, full fine-tune |

190 CU available: T4 = 380h, L4 = 158h, A100 = 31h, H100 = 27h

#### Task -> GPU Map

| Task Key | Default Tier |
|----------|-------------|
| `inference` | T4 |
| `inference_large` | L4 |
| `finetune_mini` (<3B LoRA) | T4 |
| `finetune_small` (3-7B LoRA) | L4 |
| `finetune_medium` (7-34B LoRA) | A100 |
| `finetune_large` (34B+ / full) | H100 |
| `vllm_server` | L4 |
| `video_generation` | L4 |
| `comfyui` | T4 |
| `whisper` | T4 |

```python
from engine.integrations.colab_gpu_manager import get_gpu_manager, GPUTier

mgr = get_gpu_manager()
tier = mgr.select_gpu("finetune_small")                          # -> L4
tier = mgr.select_gpu("inference", model_size="13b")             # -> L4
ok = mgr.check_budget(GPUTier.A100, estimated_hours=2.0)         # True if 12+ CU remain
mgr.record_usage(GPUTier.L4, actual_hours=0.75, task_description="7B LoRA run")
summary = mgr.get_usage_summary()
```

Budget state persists to `data/accounts/cu_budget.json`.

### Colab Venv Manager

**File:** `engine/integrations/colab_venv_manager.py`

Drive-backed venv pattern: packages installed once (~3 GB), stored on Drive,
activated by prepending site-packages to `sys.path` at notebook start.

#### Constants

```python
DRIVE_MOUNT_PATH  = "/content/drive"
COSYSIM_DRIVE_ROOT = "/content/drive/MyDrive/CosySim"
VENV_PATH    = "/content/drive/MyDrive/CosySim/.venv"
OUTPUTS_PATH = "/content/drive/MyDrive/CosySim/outputs"
MODELS_PATH  = "/content/drive/MyDrive/CosySim/models"
DATASETS_PATH = "/content/drive/MyDrive/CosySim/datasets"
```

```python
from engine.integrations.colab_venv_manager import get_venv_manager

mgr = get_venv_manager()
cells = mgr.get_setup_cells(extra_packages=["vllm>=0.4.0"])
# Returns [mount_drive_cell, activate_venv_cell]
```

Other cell generators: `install_packages_cell()`, `setup_ngrok_cell(port)`,
`save_outputs_cell(paths)`, `progress_header_cell(title, steps)`.

---

## Apps Script

**Coverage:** 0/14 rpcids observed

### Protocol

**Endpoint:** `https://script.google.com/_/AppsMakerFrontendUi/data/batchexecute`

**Format:** Same batchexecute f.req encoding as NLM/Gemini

**Auth:** Session cookies + SAPISID hash

### RPC Methods

| rpcid | Description | Status | Observed |
|-------|-------------|--------|----------|
| `pEig0e` | Execute a named function in the script project | -- | 0 |
| `OQOG2e` | Get all files in the script project | -- | 0 |
| `LuHlxe` | Get current editor state/mode | -- | 0 |
| `AvwHP` | Get extended project metadata with container info | -- | 0 |
| `NFMk7c` | Get project metadata (name, dates, owner) | -- | 0 |
| `yFXSbd` | Get project revision history with tour hints | -- | 0 |
| `UvGaob` | Get project settings and configuration | -- | 0 |
| `AJ6bre` | Initialize page/view state | -- | 0 |
| `zzomTc` | List project version history with pagination | -- | 0 |
| `OOPYjd` | List script execution history with status filters | -- | 0 |
| `KKLVD` | List script triggers (time-driven, event-driven) | -- | 0 |
| `toGAmc` | Save code content to a script file | -- | 0 |
| `GXx9jd` | Save/update project with full metadata | -- | 0 |
| `ivJzse` | Update cursor position in code editor | -- | 0 |

### Apps Script as Serverless Compute

Google Apps Script (GAS) is a serverless JavaScript runtime built into every
Google account.  Key properties:

- **Free** — unlimited execution time for personal use, 6-minute max per
  execution (30 min for Workspace accounts)
- **Native Workspace access** — `SpreadsheetApp`, `DriveApp`, `GmailApp`,
  `CalendarApp` work without OAuth, without credentials
- **Web App deployment** — any script deployed as public HTTPS endpoint
- **Time triggers** — `ScriptApp.newTrigger().timeBased().everyHours(4)` is cron, for free
- **UrlFetchApp** — outbound HTTP with custom headers including `Cookie` and
  `Authorization`

**Every Google account = another GAS environment.**  An account pool of 10
accounts is 10 independent scheduled runtimes.

### Architecture: GAS as Webhook Receiver

```
CosySim task scheduler
  -> POST /api/execute
      -> GAS Web App (public HTTPS URL)
          -> SpreadsheetApp.openById(id).getSheetByName("tasks").appendRow([...])
          -> DriveApp.createFile(name, content)
          -> UrlFetchApp.fetch(NLM_ENDPOINT, {method: "POST", headers: {Cookie: ...}, payload: ...})
          -> UrlFetchApp.fetch(COSYSIM_WEBHOOK, {method: "POST", payload: JSON.stringify(result)})
```

Example entry point:

```javascript
function doPost(e) {
  const payload = JSON.parse(e.postData.contents);
  const task = payload.task;
  const notebookId = payload.notebook_id;
  const question = payload.question;

  const nlmResponse = callNLM(notebookId, question);

  const sheet = SpreadsheetApp.openById(SHEET_ID).getSheetByName("results");
  sheet.appendRow([new Date(), question, nlmResponse]);

  UrlFetchApp.fetch(COSYSIM_CALLBACK_URL, {
    method: "post",
    contentType: "application/json",
    payload: JSON.stringify({ task, answer: nlmResponse, status: "ok" }),
  });

  return ContentService.createTextOutput("ok");
}
```

### Architecture: GAS as Scheduled Intelligence

A time trigger runs on Google's servers every 4 hours autonomously:

```javascript
function runKnowledgeIngestion() {
  const folder = DriveApp.getFolderById(COSYSIM_DRIVE_FOLDER);
  const lastRun = PropertiesService.getScriptProperties().getProperty("last_run") || "0";
  const files = folder.getFiles();

  const newQA = [];
  while (files.hasNext()) {
    const file = files.next();
    if (file.getDateCreated().getTime() <= parseInt(lastRun)) continue;

    const content = file.getBlob().getDataAsString();
    const answer = callNLM(NOTEBOOK_ID, `Summarise this document in 3 Q&A pairs: ${content.slice(0, 2000)}`);
    newQA.push({ file: file.getName(), answer, timestamp: new Date().toISOString() });
  }

  if (newQA.length > 0) {
    UrlFetchApp.fetch(COSYSIM_NEXUS_INGEST_URL, {
      method: "post",
      contentType: "application/json",
      payload: JSON.stringify(newQA),
    });
  }

  PropertiesService.getScriptProperties().setProperty("last_run", Date.now().toString());
}
```

### NLM Caller (GAS Template)

Calls the NLM batchexecute endpoint directly from GAS using session cookies
stored in Script Properties:

```javascript
const NLM_ENDPOINT = "https://notebooklm.google.com/_/LabsTailwindUi/data/batchexecute";

function callNLM(notebookId, question) {
  const cookies = PropertiesService.getScriptProperties().getProperty("NLM_COOKIES");
  const bl = PropertiesService.getScriptProperties().getProperty("NLM_BL");
  const fSid = PropertiesService.getScriptProperties().getProperty("NLM_FSID");

  const sourceIds = getSourceIds(notebookId);
  const sourceList = sourceIds.map(id => [[[id]]]);
  const inner = [sourceList, null, question, notebookId, null, null, null, null, null];
  const innerJson = JSON.stringify(inner);
  const outer = JSON.stringify([null, innerJson]);
  const fReq = "f.req=" + encodeURIComponent(outer);

  const reqId = Math.floor(Math.random() * 900000) + 100000;
  const url = `${NLM_ENDPOINT}?bl=${encodeURIComponent(bl)}&f.sid=${fSid}&hl=en-US&_reqid=${reqId}&rt=c`;

  const options = {
    method: "post",
    contentType: "application/x-www-form-urlencoded;charset=UTF-8",
    headers: {
      "Cookie": cookies,
      "Origin": "https://notebooklm.google.com",
      "X-Same-Domain": "1",
    },
    payload: fReq,
    muteHttpExceptions: true,
  };

  const response = UrlFetchApp.fetch(url, options);
  return parseNLMResponse(response.getContentText());
}
```

### Planned SDK: `engine/integrations/gas_client.py`

```python
class GASClient:
    def create_script(self, title: str, source_js: Optional[str] = None) -> str: ...
    def update_script(self, script_id: str, source_js: str) -> None: ...
    def deploy_as_webapp(self, script_id: str, access: str = "ANYONE_ANONYMOUS", execute_as: str = "USER_DEPLOYING") -> str: ...
    def run_function(self, script_id: str, function_name: str, args: Optional[Dict[str, Any]] = None) -> Any: ...
    def get_executions(self, script_id: str) -> List[Dict[str, Any]]: ...

def get_gas_client(account_name: Optional[str] = None) -> Optional[GASClient]: ...
```

### GAS Template Library (planned `templates/gas/`)

| Template | Purpose |
|----------|---------|
| `webhook_receiver.js` | Receives POST from CosySim scheduler, dispatches actions, POSTs results back |
| `nlm_caller.js` | Calls NLM batchexecute with session cookies from Script Properties |
| `drive_processor.js` | Processes Drive folder files on schedule, calls NLM, tracks in Sheet |
| `nexus_ingestor.js` | Reads Q&A pairs from Sheet, POSTs to CosySim Nexus API |

### Client-Side Research Targets

| Target | Value |
|--------|-------|
| NLM Quota Counter (`remainingQueries` in heap) | Rotate accounts before 429s |
| Model Override in batchexecute payload | Force Gemini 2.5 Pro for specific operations |
| AI Studio Model ID Override | Switch frontier models without UI |
| Feature Flag IDs 400-1200 | Gate premium generation capabilities on free accounts |

---

## Google Workspace

**Coverage:** 0/49 operations observed

### Protocol

**Hosts:** `appsgenaiserver-pa.clients6.google.com`, `docs.google.com`, `sheets.google.com`, `drive.google.com`

**Auth:** API key + session cookies OR SAPISIDHASH

**Format:** REST JSON, gRPC-JSON transcoding, or batchexecute

### Cloud Search

| Method | Description |
|--------|-------------|
| `query_search` | Cross-workspace semantic search query |

### Docs Gemini

| Method | Description |
|--------|-------------|
| `help_me_create` | Generate document content from a prompt |
| `match_style` | Match generated content style to existing document |

### Drive Gemini

| Method | Description |
|--------|-------------|
| `ai_overview_search` | Semantic search across Drive files using AI Overviews |
| `ask_gemini` | Ask Gemini a question about Drive files |

### Drive V2Internal

| Method | Description |
|--------|-------------|
| `copy_file` | Copy a file in Drive (template duplication) |
| `export_file` | Export a Workspace file in a specified format |
| `get_file` | Get file metadata from Drive |
| `get_permissions` | List permissions on a Drive file |
| `insert_permission` | Add/modify sharing permissions |
| `list_files` | List/search files in Drive |
| `trash_file` | Move file to trash |
| `update_file` | Update file metadata (title, description, parents) |
| `upload_file` | Upload file to Drive with metadata (multipart) |

### People Stack

| Method | Description |
|--------|-------------|
| `autocomplete` | Autocomplete people/contacts for sharing and @mentions |
| `autocomplete_alt` | Alternative API key for people autocomplete (load balancing) |
| `warmup` | Pre-warm people autocomplete service |

### Sheets BigQuery

| Method | Description |
|--------|-------------|
| `createDataSourcePivotTableOnNewSheet` | Create a pivot table backed by a data source on a new sheet |
| `enableAllDataSourcesExecution` | Enable execution for all data source connections |
| `getBigQueryProjects` | List BigQuery projects accessible from Sheets |
| `insertDataSourceSheet` | Insert a new sheet backed by a data source |
| `newDataSourceSpec` | Create a new data source specification (BigQuery, Looker) |
| `refreshAllDataSources` | Refresh all connected data sources |

### Sheets Extended

| Method | Description |
|--------|-------------|
| `external_data_batch` | Batch fetch external data for multiple cell ranges |
| `get_prefs` | Get/set session preferences for spreadsheet editing |
| `get_revision_history` | Get version history/revisions for a spreadsheet |
| `save` | Save spreadsheet changes with commands bundle |

### Sheets Gemini

| Method | Description |
|--------|-------------|
| `columnsmith_execute` | AI-driven column transformation via Gemini on cell ranges |
| `external_data_fetch` | Fetch and inject external data into sheet cells |

### Sheets REST

| Method | Description |
|--------|-------------|
| `save` | Save document changes (internal Sheets RPC) |
| `scripts_getitems` | Get Apps Script items bound to the spreadsheet |
| `scripts_uiready` | Signal that the Apps Script UI is loaded and ready |

### Workspace Analytics

| Method | Description |
|--------|-------------|
| `create` | Create a new analytics session/event |
| `ping` | Lightweight activity heartbeat ping |

### Workspace Gemini

| Method | Description |
|--------|-------------|
| `get_settings` | Get current Gemini settings for the user |
| `list_gems` | List available Gemini models and capabilities |
| `quota_summary` | Get Gemini API usage quota summary |
| `stream_generate` | Stream-based Gemini text generation for Workspace apps |
| `update_settings` | Update user Gemini preferences |

### Workspace Support

| Method | Description |
|--------|-------------|
| `addons_list` | List installed Workspace add-ons and extensions |
| `async_data` | Fetch async data for Workspace integrations |
| `doc_sync` | Real-time document collaboration sync |
| `fetch_recommendation` | Fetch AI-powered feature recommendations |
| `fetch_recommendations_batch` | Batch fetch multiple AI recommendations |
| `peoplestack_autocomplete` | People autocomplete for sharing and collaboration |
| `prewarm` | Pre-warm Gemini AI models before generation |
| `scripts_ui` | Apps Script UI integration for document automation |
| `waa_ping` | Workspace analytics and activity tracking ping |
| `workspace_batch` | Batch multiple Workspace UI operations |

---

## Google Ecosystem SDK

### Google Drive Client

**File:** `engine/integrations/google_drive_client.py`

**Auth:** SAPISIDHASH with `origin = "https://drive.google.com"`.
All requests target `clients6.google.com`.

#### Methods

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

```python
from engine.integrations.google_drive_client import get_drive_client

drive = get_drive_client()                    # round-robin from pool
drive = get_drive_client("nihilistcod")       # specific account

result = drive.upload_text_to_cosysim_folder(
    name="experiment_results.json",
    content=json.dumps(data),
    subfolder="nexus",
)

# NLM integration: make file readable then add as source
drive.make_file_accessible_to_notebooklm(file_id)
url = drive.get_shareable_link(file_id)
source_id = nlm_client.add_source_url(notebook_id, url)
```

### Google Sheets Client

**File:** `engine/integrations/gsheets_client.py`

**Auth:** SAPISIDHASH with `origin = "https://docs.google.com"`.
Sheets v4 at `sheets.googleapis.com` + Drive v3 at `clients6.google.com`.

#### Methods

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

```python
from engine.integrations.gsheets_client import get_sheets_client

sheets = get_sheets_client()

result = sheets.create_from_data(
    title="Q&A Cache Export",
    rows=[{"question": q, "answer": a, "confidence": 0.9} for q, a in pairs],
)

rows = sheets.read_rows(result["id"])
sheets.append_rows(result["id"], [{"question": "new Q", "answer": "new A"}])
csv_text = sheets.export_as_csv(result["id"])
```

#### The NLM Read-Write Loop

Sheets acts as the structured data layer in the NLM pipeline:

```
NLM flashcards  -> export_to_sheets() (Krh3pd rpc)
                -> Google Sheet with Q&A pairs
                -> add_source_url(sheet_url)  <- Gemini reads the spreadsheet
                -> next NLM question builds on the structured data
                -> updated answers -> append_rows() -> Sheet updated
                -> add_source_url() again -> Gemini reads the updates
```

### NLM Direct Client

**File:** `engine/integrations/nlm_direct_client.py`

See [NLM API Reference](NLM_API_REFERENCE.md) for full rpcid catalog.

#### Two-Endpoint Architecture

| Endpoint | Purpose | Auth |
|----------|---------|------|
| `GenerateFreeFormStreamed` | Multi-turn notebook Q&A (ask / streaming ask) | cookies + f.req |
| `batchexecute` | All studio ops: create, generate, export, manage | cookies + rpcids |

Both require a `bl` (build label) and `f.sid` (session fingerprint) extracted
from the NLM homepage HTML.

#### Key rpcids

| rpcid | Operation | Notes |
|-------|-----------|-------|
| `izAoDd` | Add URL/text source | URL, YouTube, Sheets, image, text paste |
| `o4cbdc` | Register file upload | Returns upload URL + source ID |
| `rLM1Ne` | Poll source processing | Returns pending source IDs |
| `hPTbtc` | List sources | All source IDs in a notebook |
| `LBwxtb` | Delete source / blog post | Multipurpose by payload shape |
| `CYK0Xb` | Create note (report) | ~10k word prompt -> full document |
| `QA9ei` | Generate audio podcast | 30-min deep dive / brief / critique / debate |
| `gArtLc` | Poll / list artifacts | Get download URL when COMPLETE |
| `ciyUvf` | Generate flashcards | Instant Q&A pairs from sources |
| `R7cb6c` | Generate quiz | Multiple choice or true/false |
| `yyryJe` | Generate mind map | Nested concept JSON tree |
| `Krh3pd` | Export to Sheets | Returns live Google Sheet URL |
| `tr032e` | Source summary | Gemini summary of one source |
| `ub2Bae` | List notebooks | All notebooks in account |
| `s0tc2d` | Rename notebook | Update display name |

```python
from engine.integrations.nlm_direct_client import get_nlm_direct_client

client = get_nlm_direct_client()

source_id = client.add_source_url(nb_id, "https://arxiv.org/abs/2312.11805")
answer = client.ask(nb_id, source_ids=[source_id], question="What are the key findings?")

for chunk in client.ask_streaming(nb_id, source_ids, "Summarise chapter 3"):
    print(chunk, end="", flush=True)

flashcards = client.generate_flashcards(nb_id)
report = client.create_note(nb_id, "Write a detailed analysis of all training curves")
job_id, artifact_id = client.generate_audio(nb_id, "Focus on the novel contributions")
sheet_url = client.export_to_sheets(artifact_id="...", title="Q&A Data")
```

Audio types: `AUDIO_DEEP_DIVE=1` (30 min), `AUDIO_BRIEF=2` (5 min),
`AUDIO_CRITIQUE=3`, `AUDIO_DEBATE=4`.

#### The Self-Referential Audio Loop

Each audio generation is ~30 minutes of dense Gemini conversation.  Feeding
that back as a source makes the next generation deeper:

```python
_, art_id = client.generate_audio(nb_id, "Explain the architecture in depth")
art = client.poll_artifact(nb_id, art_id)
audio_path = client.download_audio(art, "data/nlm_audio/round1.mp3")
client.add_source_file(nb_id, audio_path, "audio/mpeg")  # feed back as source

# Round 2 builds on everything the first podcast covered
_, art_id2 = client.generate_audio(nb_id, "Now cover everything the first podcast missed")
# Round 3 -> typically 300+ total Q&A pairs when all three are distilled
```

#### The Knowledge Flywheel

Two-call compound: `create_note()` (CYK0Xb) generates a full analysis,
then `ask()` (GenerateFreeFormStreamed) extracts 60 structured Q&A pairs:

```python
report, qa_pairs = client.run_knowledge_flywheel(
    notebook_id=nb_id,
    analysis_prompt="Perform a comprehensive analysis of all training runs...",
)

from engine.nexus.client import get_nexus_client
nexus = get_nexus_client()
for pair in qa_pairs:
    nexus.add_qa(pair["question"], pair["answer"], category="ml_experiments")
```

### Artifact Bus

**File:** `engine/integrations/artifact_bus.py`

The bus abstracts all transport logic between services.

#### Service Enum

```python
class ArtifactService(str, Enum):
    LOCAL  = "local"
    DRIVE  = "drive"
    COLAB  = "colab"
    NLM    = "nlm"
    SHEETS = "sheets"
    NEXUS  = "nexus"
```

#### Route Matrix

| From -> To | Transport |
|-----------|-----------|
| LOCAL -> DRIVE | multipart upload |
| LOCAL -> NLM | via Drive (make_public + add_source_url) |
| LOCAL -> NEXUS | read text + add_entry |
| DRIVE -> NLM | make_public + add_source_url |
| DRIVE -> COLAB | kernel cell that mounts Drive + copies file |
| DRIVE -> NEXUS | download_text + add_entry |
| DRIVE -> SHEETS | download JSON/CSV + create_sheet + append_rows |
| COLAB -> DRIVE | kernel reads file via base64 + upload |
| COLAB -> NLM | via Drive intermediary |
| COLAB -> SHEETS | Colab -> Drive then Drive -> Sheets |
| COLAB -> NEXUS | kernel reads text + add_entry |
| NLM -> COLAB | inject content as Python variable in kernel |
| NLM -> DRIVE | local audio download + upload |
| NLM -> NEXUS | generate_flashcards + add_qa (or add_entry) |
| SHEETS -> NLM | add spreadsheet URL as source |
| SHEETS -> NEXUS | read_rows + JSON + add_entry |

#### `handoff()` — Single Hop

```python
from engine.integrations.artifact_bus import get_artifact_bus, Artifact, ArtifactService

bus = get_artifact_bus("nihilistcod")

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

#### `pipeline()` — Multi-Hop

```python
history = bus.pipeline(
    audio_art,
    route=[ArtifactService.DRIVE, ArtifactService.NLM, ArtifactService.NEXUS],
    kwargs_per_hop=[
        {"make_public": True, "subfolder": "nlm_audio"},
        {"notebook_id": "abc-123"},
        {"title": "Round 2 Audio Distillation", "category": "knowledge"},
    ],
)
```

#### `full_knowledge_loop()` — Compound Workflow

```python
results = bus.full_knowledge_loop(
    notebook_id="abc-123",
    colab_output_path="/content/benchmark_results.json",
    runtime_url=runtime_url,
    kernel_id=kernel_id,
    proxy_token=proxy_token,
    nexus_category="benchmarks",
)
# Steps: colab->drive->nlm, nlm->nexus (flashcards)
# {"steps": [...], "nexus_ref": "...", "qa_count": 42}
```

#### Factory

```python
bus = get_artifact_bus("nihilistcod")
# Wires up: drive_client, nlm_client, colab_client, sheets_client, nexus_client
```
