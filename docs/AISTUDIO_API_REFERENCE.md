# AI Studio API Reference (MakerSuiteService — Reverse Engineered)

> Derived from V8 heap snapshot analysis + HAR network capture (March 2026).
> 136 methods fully extracted from AI Studio (`aistudio.google.com`).

---

## Protocol: gRPC-web (NOT batchexecute)

AI Studio uses a different protocol from Gemini and NotebookLM:

```
POST https://alkalimakersuite-pa.clients6.google.com/$rpc/
     google.internal.alkali.applications.makersuite.v1.MakerSuiteService/{METHOD}
Content-Type: application/json
Authorization: SAPISIDHASH {timestamp}_{sha1}
X-Goog-Api-Key: AIzaSy...
X-Goog-Authuser: 0
Origin: https://aistudio.google.com
Cookie: [full Google cookie set]
```

**Streaming:** `https://webchannel-alkalimakersuite-pa.clients6.google.com`

---

## Auth

```python
import hashlib, time

def build_sapisidhash(sapisid: str, origin: str) -> str:
    ts = int(time.time())
    hash_src = f"{ts} {sapisid} {origin}"
    digest = hashlib.sha1(hash_src.encode()).hexdigest()
    return f"SAPISIDHASH {ts}_{digest}"

# Headers
headers = {
    "Authorization": build_sapisidhash(cookies["SAPISID"], "https://aistudio.google.com"),
    "X-Goog-Api-Key": "AIzaSyCB6OnnfuitFnaYWu4BvtGKaoLFk4cm-GE",
    "X-Goog-Authuser": "0",
    "Content-Type": "application/json",
    "Origin": "https://aistudio.google.com",
}
```

**Confirmed API Keys:**
- `AIzaSyCB6OnnfuitFnaYWu4BvtGKaoLFk4cm-GE`
- `AIzaSyDdP816MREB3SkjZO04QXbjsigfcI0GWOs`
- `AIzaSyDHAQL7kdN6lNBcBok1eNB8dG7wwo6E6io`

Rotate via `GenerateCloudApiKey` method.

---

## Complete Method Registry (136 methods)

### Core AI Generation

| Method | Purpose | Notes |
|--------|---------|-------|
| `GenerateContent` | Text/multimodal generation | Main inference |
| `ProxyUnaryCall` | Proxy Gemini generation | Returns thoughtSignature |
| `ProxyStreamedCall` | Streaming Gemini proxy | SSE stream |
| `ProxyUnaryFileApiCall` | File-aware generation proxy | Multimodal |
| `GenerateImage` | Image generation | Imagen 4.0 |
| `GenerateVideo` | Video generation | Veo 3.1 |
| `GetGenerateVideoOperation` | Check async video job | Long-running op |
| `GenerateFunctionCallAnswer` | Tool call response | Function calling |
| `CountTokens` | Count tokens for prompt | Pre-generation |
| `GeminiSpeechToText` | Speech → text | STT via Gemini |
| `StreamExtractVideoFrames` | Extract frames from video | Streaming |
| `BidiGenerateContent` | Bidirectional streaming | Real-time |

---

### Models

| Method | Purpose |
|--------|---------|
| `ListModels` | All available models |
| `GetModel` | Single model details |
| `GetModelQuota` | Quota for a model |
| `ListModelRateLimits` | Rate limit info |
| `ListQuotaModels` | Models with quota info |

---

### Prompts

| Method | Purpose |
|--------|---------|
| `CreatePrompt` | Create prompt template |
| `GetPrompt` | Get prompt by ID |
| `UpdatePrompt` | Update prompt |
| `DeletePrompt` | Delete prompt |
| `ListPrompts` | List all prompts |
| `EnhancePrompt` | AI-assisted prompt improvement |
| `GetImFeelingLuckyOptions` | Suggest prompt variations |

---

### Applets (AI Studio Apps)

| Method | Purpose | Notes |
|--------|---------|-------|
| `CreateApplet` | Create new AI app | Returns applet UUID |
| `GetApplet` | Get app by UUID | Full app config |
| `SaveApplet` | Save/update app | |
| `DeleteApplet` | Delete app | |
| `ListApplets` | List user's apps | |
| `ListBundledApplets` | List built-in templates | |
| `ListSharedApplets` | Apps shared with user | |
| `ListDriveApplets` | Apps stored in Drive | |
| `ListRecentApplets` | Recently used apps | |
| `StoreRecentApplet` | Mark as recently used | |
| `ForgetRecentApplet` | Remove from recent | |
| `LoadBundledApplet` | Load a built-in template | |
| `LoadDriveApplet` | Load from Drive | |
| `LoadZipApplet` | Load from ZIP file | |
| `SaveDriveApplet` | Save to Drive | |
| `DeleteDriveApplet` | Delete from Drive | |
| `GetAppletAccess` | Get sharing config | |
| `UpdateAppletAccess` | Change sharing/access | |
| `GetAppletGalleryConfig` | Gallery metadata | |
| `GetAppletDeploymentInfo` | Deployment status | |
| `GetAppletDebugInfo` | Debugging info | |
| `GetAppletTrajectory` | Execution trace | |
| `SeverAppletRedirect` | Remove redirect | |

---

### Deployment

| Method | Purpose | Notes |
|--------|---------|-------|
| `ProvisionAndInitializeApplet` | Deploy app → Cloud Run | Returns deployed URL |
| `CreateSharedAppletDeployment` | Create shared deployment | |
| `DeleteSharedAppletDeployment` | Delete deployment | |
| `CheckSharedAppletDeployment` | Health check | |
| `CreateCloudRunService` | Create Cloud Run service | |
| `UpdateCloudRunService` | Update service | |
| `DeleteCloudRunService` | Delete service | |
| `CheckCloudRunService` | Service health | |
| `GetAppletCloudRunServiceLogs` | Service logs | |
| `DownloadBuildArtifacts` | Build output | |

**`ProvisionAndInitializeApplet` — Deploy an AI Studio app:**

```python
resp = client.post("ProvisionAndInitializeApplet", {
    "appletId": "3d201588-286c-4a03-beb7-6edeaeaf6abf"
})
# Returns: {"deploymentUrl": "https://ais-dev-...run.app", "serviceId": "..."}
```

---

### App Secrets (Environment Variables)

| Method | Purpose |
|--------|---------|
| `ListAppletSecrets` | List app secrets/env vars |
| `ListUnsetAppletSecrets` | List required but unset secrets |
| `UpsertAppletSecret` | Create/update secret |
| `DeleteAppletSecret` | Delete secret |

---

### Code Assistant

| Method | Purpose |
|--------|---------|
| `CodeAssistant` | Synchronous code assistance |
| `CodeAssistantOffline` | Offline code generation |
| `StreamCodeAssistantOfflineGeneration` | Streaming offline gen |
| `CancelCodeAssistantOfflineGeneration` | Cancel offline job |
| `LoadCodeAssistantInteractionHistory` | Load code history |
| `LoadCodeAssistantSnapshots` | Load saved snapshots |
| `GetCodeAssistantSnapshot` | Get specific snapshot |
| `ListCodeAssistantConfigurations` | List configs |
| `ListCodeAssistantFeatures` | Available features |
| `ListCodeAssistantOfflineGenerations` | List offline jobs |
| `ListCodeGenSuggestionCards` | Suggestion cards |
| `GenerateCodeAssistantSuggestionChips` | Quick suggestions |
| `GenerateGitHubCommitMessage` | AI commit message |

---

### GitHub Integration

| Method | Purpose |
|--------|---------|
| `GetGitHubAuthStatus` | Check GitHub OAuth |
| `CreateGitHubRepository` | Create repo from AI Studio |
| `ImportGitHubRepository` | Import existing repo |
| `ListGitHubRepositories` | List accessible repos |
| `PushNewCommit` | Push changes to repo |
| `FetchChangelistContent` | Piper CL content |
| `FetchPiperFile` | Google internal VCS |
| `ComputeStagedGitHubDiff` | Compute diff |
| `QueryCodeSearch` | Code search |

---

### Sessions / Conversation

| Method | Purpose |
|--------|---------|
| `GetSession` | Get session by ID |
| `GetSessionTurn` | Get specific turn |
| `ListSessionTurns` | List all turns |
| `BulkDeleteSessionTurns` | Bulk delete |
| `CountSessionTurns` | Turn count |
| `RecordSessionTurnFeedback` | Thumbs up/down |

---

### Datasets (Fine-tuning)

| Method | Purpose |
|--------|---------|
| `CreateDataset` | Create tuning dataset |
| `GetDataset` | Get dataset |
| `UpdateDataset` | Update dataset |
| `DeleteDataset` | Delete dataset |
| `ListDatasets` | List datasets |
| `ExportDataset` | Export to Drive/GCS |
| `CreateInteraction` | Add training example |

---

### Cloud Infrastructure

| Method | Purpose |
|--------|---------|
| `CreateCloudProject` | Create GCP project |
| `UpdateCloudProject` | Update project |
| `ListCloudProjects` | List GCP projects |
| `ImportProjects` | Import existing projects |
| `ListImportedProjects` | List imported |
| `RemoveProjects` | Detach projects |
| `ListBillingAccounts` | Billing accounts |
| `GetPrepayEligibility` | Prepay check |
| `UpgradeAndDisablePrepay` | Billing upgrade |
| `HasFirestore` | Check Firestore status |
| `CreateCloudApiKey` | Create API key |
| `UpdateCloudApiKey` | Update API key |
| `DeleteCloudApiKey` | Delete API key |
| `GenerateCloudApiKey` | Generate new key |
| `ListCloudApiKeys` | List all API keys |
| `GetProjectUsageLimit` | Usage limits |
| `UpdateProjectUsageLimit` | Update limits |

---

### Auth

| Method | Purpose |
|--------|---------|
| `GenerateAccessToken` | Get OAuth2 `ya29.` token |
| `AcceptTerms` | Accept ToS |
| `AcceptFirebaseTos` | Firebase ToS |
| `CheckUserStatus` | Account status check |
| `GetUserPreferences` | User preferences |
| `UpdateUserPreferences` | Update preferences |
| `GetUserRestrictions` | Restrictions/SafeSearch |

**`GenerateAccessToken`** — Get a fresh OAuth2 bearer token:

```python
resp = client.post("GenerateAccessToken", {})
# Returns: {"accessToken": "ya29.a0AfH6SM...", "expiry": "..."}
# Token works on any Google API requiring OAuth2
```

---

### Observability

| Method | Purpose |
|--------|---------|
| `EnableTracesLogging` | Turn on tracing |
| `DisableTracesLogging` | Turn off tracing |
| `GetTracesLoggingStatus` | Current status |
| `UpdateTracesStorageRetention` | Retention policy |
| `FetchMetricTimeSeries` | App metrics |
| `Log` | Write a log entry |
| `StreamLogs` | Stream log output |
| `ListIncidentsHistory` | Incident history |

---

### File Operations

| Method | Purpose |
|--------|---------|
| `UploadScs` | Upload file to SCS |
| `ListFilesInScs` | List uploaded files |
| `ResolveDriveResource` | Resolve Drive file ID |
| `GetAppFolder` | Get app's Drive folder |

---

### Misc

| Method | Purpose |
|--------|---------|
| `GetLoggingContext` | Logging config |
| `GetImFeelingLuckyOptions` | Prompt suggestion |
| `GetSample` | Get code sample |
| `GetEmbeddedPortalParameters` | Embed config |
| `ListPromos` | Promotional offers |
| `CheckImage` | Image content moderation |
| `GetGetcodeTemplates` | Code templates |

---

## User App Discovery

```python
# Your deployed app: "Nexus Assistant"
# UUID: 3d201588-286c-4a03-beb7-6edeaeaf6abf
# URL: https://ais-dev-4pnf35mkt3lidvc5grflhc-375946902936.asia-southeast1.run.app

resp = client.post("GetApplet", {"appletId": "3d201588-286c-4a03-beb7-6edeaeaf6abf"})
```

---

## ProxyUnaryCall — Production Example

```python
resp = client.post("ProxyUnaryCall", {
    "model": "models/gemini-3-flash-preview",
    "contents": [{"role": "user", "parts": [{"text": "Hello"}]}],
    "generationConfig": {
        "maxOutputTokens": 1024,
        "temperature": 0.7
    }
})
# Returns Gemini response with thoughtSignature for thinking tokens
# Response structure mirrors GenerateContent API response
```

---

## CosySim Integration

See `engine/integrations/aistudio_client.py` for the Python client.

Key workflows:
1. `GenerateAccessToken` → fresh OAuth2 for any Google API
2. `ListModels` → enumerate ALL available Gemini models
3. `ProxyUnaryCall` → run Gemini generation through AI Studio session
4. `ProvisionAndInitializeApplet` → deploy/redeploy Nexus Assistant
5. `GenerateCloudApiKey` → rotate API keys automatically
6. `CreateDataset` + `CreateInteraction` → build fine-tuning datasets
7. `GetAppletCloudRunServiceLogs` → monitor Nexus Assistant health

See also: `docs/GEMINI_API_REFERENCE.md`, `docs/NLM_API_REFERENCE.md`
