# NotebookLM API Reference
## Complete batchexecute Protocol Documentation

> **Source:** V8 heap analysis + HAR reverse engineering, March 2026  
> **Coverage:** 24 decoded rpcids, 61 total service methods

---

## Base URL & Transport

```
Base:     https://notebooklm.google.com
Service:  /_/LabsTailwindUi/data/batchexecute
```

All calls are **HTTP POST** with `Content-Type: application/x-www-form-urlencoded;charset=UTF-8`.

### URL Parameters

| Param | Example | Required |
|-------|---------|----------|
| `rpcids` | `rLM1Ne` | Yes |
| `source-path` | `/notebook/{UUID}` | Yes |
| `bl` | `boq_labs-tailwind-frontend_20260302.14_p0` | Yes |
| `f.sid` | `-5975008709367091728` | Yes |
| `hl` | `en` | Recommended |
| `_reqid` | `123456` | Recommended |
| `rt` | `c` | Yes (chunked) |

### Request Body

```
f.req=URL_ENCODED([[["RPCID","JSON_PAYLOAD",null,"generic"]]])
```

Or for multiple calls in one request:
```
f.req=URL_ENCODED([[["RPCID1","..."],["RPCID2","..."]]])
```

### Required Headers

```http
x-goog-ext-353267353-jspb: [null,null,null,282611]
x-same-domain: 1
x-browser-year: 2026
x-browser-channel: stable
origin: https://notebooklm.google.com
referer: https://notebooklm.google.com/notebook/{UUID}
Content-Type: application/x-www-form-urlencoded;charset=UTF-8
Cookie: SAPISID=...; SID=...; APISID=...; [13 total cookies]
```

**No Authorization header** — NLM uses cookie-based session auth only.

### Response Format

Responses start with a security prefix followed by chunked JSON:

```
)]}'\n
DECIMAL_CHUNK_SIZE\n
[["wrb.fr","RPCID","RESPONSE_JSON",null,null,null,"generic"],
 ["di",304],
 ["af.httprm",303,"TRACE_ID",17]]\n
HEX_CHUNK_SIZE\n
[["e",4,null,null,188]]\n
0\n
```

Parse by: strip `)]}'`, split on newlines, every 2 lines = (decimal length, JSON data).

---

## Auth Tokens

### at Token (CSRF)
Required as query parameter `at=`. Structure:
```
at=AIXQIk{BASE64_HASH}:{UNIX_TIMESTAMP_MS}
```
Generated from SAPISID cookie using SHA-1 hash. **Expires in minutes.** Must refresh per-session.

### f.sid (Session ID)
A large negative integer from WIZ_global_data. Example: `-5975008709367091728`.  
Obtained from the NLM page source or stored in session.

### Cookie Set
13 cookies required (from `data/accounts/pool.json`):
```
SAPISID, SID, APISID, HSID, SSID, NID, SIDCC, 
__Secure-1PSID, __Secure-1PAPISID, __Secure-1PSIDCC, 
__Secure-3PSID, __Secure-3PAPISID, SOCS
```

---

## Complete rpcid Reference

### Core Streaming

#### `rLM1Ne` — WatchNotebook
The server-sent event stream. Called once per page load; receives real-time updates.

```python
payload = [notebookUUID, None, [2], None, 0]
```

Response: continuous stream of state updates (source processing, artifact ready, etc.)

---

#### `R7cb6c` — CreateConversationTurn  
**The main Q&A API.** Send a question, receive AI-generated answer grounded in sources.

```python
payload = [
    [[field_mask_fields]],  # response field selection
    notebookUUID,
    [None, None, turn_number, [[sourceUUID1], [sourceUUID2], ...]]
    # Omit sources array to use ALL notebook sources
]
```

Response:
```json
[null, null, [turnUUID, null, [null, null, null, null, [null, answerText], ...]]]
```

**Key:** `answerText` is at nested position `[2][0][4][0][4]` in response.

---

#### `yyryJe` — GenerateFreeFormStreamed (batch mode)
Streaming generation. Used for longer artifact generation.

```python
payload = [[[[sourceUUID1]], [[sourceUUID2]]]]
```

---

### Notebook Management

#### `wXbhsf` — ListNotebooks
Returns all notebooks for the authenticated user.

```python
payload = [None, 1, None, [2]]
```

Response: list of `[notebookUUID, null, [[null, title, null, null, timestamp], ...]]`

---

#### `e3bVqc` — GetNotebookInfo
Get metadata for a specific notebook.

```python
payload = [None, None, notebookUUID]
```

---

#### `s0tc2d` — RenameNotebook
Rename a notebook.

```python
payload = [notebookUUID, [[None, None, None, [None, newTitle]]]]
```

---

#### `hPTbtc` — ListRecentNotebooks
Get recently viewed notebooks.

```python
payload = [[], None, notebookUUID, 20]  # 20 = page size
```

---

#### `VfAZjd` — GetNotebookAnalysis  
Get an AI-generated analysis of all sources in a notebook.

```python
payload = [notebookUUID, [2]]
```

Response: `[[[formatted_analysis_text, ...]]]`  
Returns structured summaries like "These sources investigate the integration of AI in digital forensics, focusing on..."

---

#### `CYK0Xb` — GenerateNotebookSummary  
Generate/update the notebook's auto-summary.

```python
payload = [notebookUUID, existingSummaryMarkdown]
```

---

### Source Management

#### `ciyUvf` — GetNotebookSources
List all sources in a notebook.

```python
payload = [notebookUUID, None, [2]]
```

Response: list of source objects with `[sourceUUID, type, status, title, ...]`

---

#### `tGMBJ` — GetSourceDetails
Get detailed metadata about specific sources.

```python
payload = [[[sourceUUID1], [sourceUUID2]], [2]]
```

---

#### `tr032e` — GetSourceContent
Get the raw text content of a source.

```python
payload = [[[[sourceUUID]]]]
```

---

#### `o4cbdc` — UploadSources
Upload new sources (files or text).

```python
payload = [[[filename1], [filename2]], ...]
```

---

### Conversation & Notes

#### `cFji9` — GetConversation
Get the conversation history for a notebook.

```python
payload = [notebookUUID, None, None, [2]]
```

---

#### `otmP3b` — GetConversationTurns
Get specific conversation turns.

```python
payload = [[[field_mask]], notebookUUID, [[sourceUUID1], [sourceUUID2]]]
```

---

#### `cYAfTb` — CreateNote
Create a pinned note in the notebook.

```python
payload = [notebookUUID, noteUUID, [[[htmlContent, title, [], 0]]], [2]]
```

---

### Artifacts (Audio, Video, Study Guides, etc.)

#### `gArtLc` — ListArtifacts
List all artifacts in a notebook.

```python
payload = [[[field_mask_fields]], notebookUUID, filter_string]
# filter_string: "" for all, or specific type filter
```

Response: list of `[artifactUUID, type, status, title, createdAt, ...]`

**Artifact types:** `STUDY_GUIDE`, `FAQ`, `BRIEFING_DOC`, `TIMELINE`, `TABLE_OF_CONTENTS`, `NOTE`, `AUDIO_OVERVIEW`, `VIDEO_OVERVIEW`

---

#### `LBwxtb` — CreateArtifact
Generate a new artifact from notebook sources.

```python
payload = [None, [1], artifactUUID, notebookUUID, [[None, [title, contentHint]]]]
```

The artifactUUID can be pre-generated (UUID4).

---

#### `sqTeoe` — GetAudioOverviewOptions
Get available audio overview format options.

```python
payload = [[2, None, None, [1, None, None, None, None, None, None, None, None, None, [1]], [[2, 1, 3]]], None, 1]
```

Response:
```json
[[[[
    [1, "Deep dive", "A lively conversation between two hosts, unpacking and connecting topics in your sources"],
    [2, "Brief", "A bite-sized overview to help you grasp the highlights"]
]]]]
```

---

#### `QA9ei` — GetSuggestedQuestions
Get AI-suggested questions to ask about the notebook sources.

```python
payload = [None, [1], [queryHint, 1], count, notebookUUID]
```

---

### Account & Auth

#### `MI613e` — GetAccountInfo
Get account information and session data.

```python
payload = [None, email, None, ..., [session_id, ...]]
```

---

### WebRTC Methods (via gRPC Kz pattern)

These use the gRPC stub system, not batchexecute:

#### `Of0kDd` — GetIceConfig
Retrieve WebRTC ICE configuration for peer-to-peer audio/video.

```javascript
// Angular gRPC stub:
new _.Kz("Of0kDd", class extends _.r {...},
    [_.Dz, !0, _.Fz, "/LabsTailwindOrchestrationService.GetIceConfig"])
```

#### `eyWvXc` — SendSdpOffer
Send a WebRTC SDP offer for audio overview streaming.

```javascript
new _.Kz("eyWvXc", class extends _.r {...},
    [_.Dz, !0, _.Fz, "/LabsTailwindOrchestrationService.SendSdpOffer"])
```

---

## Complete Service Method Catalogue

### LabsTailwindOrchestrationService (58 methods)

Methods mapped to known rpcids are marked **✓**. Others have rpcids to discover.

| Method | rpcid | Notes |
|--------|-------|-------|
| ActOnSources | ? | Batch actions on sources |
| AddSources | ? | Add sources to notebook |
| AddTentativeSources | ? | Pre-validate sources |
| CancelDiscoverSourcesJob | ? | Cancel async discovery |
| CheckSourceFreshness | ? | Verify URL source still accessible |
| CreateArtifact | `LBwxtb` ✓ | Generate study guide, FAQ, etc. |
| CreateNote | `cYAfTb` ✓ | Create pinned note |
| CreateProject | ? | Create new notebook (project) |
| DeleteArtifact | ? | Remove an artifact |
| DeleteChatTurns | ? | Delete conversation turns |
| DeleteNotes | ? | Delete pinned notes |
| DeleteProjects | ? | Delete notebooks |
| DeleteSources | ? | Remove sources from notebook |
| DeriveArtifact | ? | Derive artifact from another |
| DiscoverSources | ? | **Auto-discover web sources for topic** |
| DiscoverSourcesAsync | ? | Async version |
| DiscoverSourcesManifold | ? | Batch discovery |
| ExecuteWritingFunction | ? | AI writing/editing operations |
| ExportToDrive | ? | Export artifacts to Google Drive |
| FinishDiscoverSourcesRun | ? | Complete discovery job |
| GenerateAccessToken | ? | Generate sharing access token |
| GenerateArtifact | ? | Generate artifact (streaming) |
| GenerateDocumentGuides | ? | Create document reading guides |
| GenerateFreeFormStreamed | `yyryJe` ✓ | Main chat/generation (streaming) |
| GenerateMagicView | ? | AI-powered view generation |
| GenerateNotebookGuide | `CYK0Xb` ✓ | Generate notebook summary |
| GeneratePromptSuggestions | `QA9ei` ✓ | Suggest questions to ask |
| GenerateReportSuggestions | ? | Suggest report structure |
| GetArtifact | ? | Get specific artifact content |
| GetArtifactCustomizationChoices | ? | Customization options for artifact |
| GetArtifactUserState | ? | Per-user artifact interaction state |
| GetIceConfig | `Of0kDd` ✓ | WebRTC ICE configuration |
| GetMagicIndex | ? | Get Magic View index |
| GetMagicView | ? | Get Magic View content |
| GetNotes | ? | Get pinned notes |
| GetOrCreateAccount | ? | Account initialization |
| GetProject | `e3bVqc` ✓ | Get notebook info |
| GetProjectAnalytics | `VfAZjd` ✓ | AI analysis of notebook sources |
| ListArtifacts | `gArtLc` ✓ | List all artifacts |
| ListChatSessions | ? | List conversation sessions |
| ListChatTurns | `otmP3b` ✓ | Get conversation turns |
| ListDiscoverSourcesJob | ? | List discovery jobs |
| ListFeaturedProjects | ? | Featured/public notebooks |
| ListModelOptions | ? | Available AI models |
| ListRecentlyViewedProjects | `hPTbtc` ✓ | Recent notebooks |
| LoadSource | `tr032e` ✓ | Get source content |
| MutateAccount | ? | Update account settings |
| MutateNote | ? | Update note content |
| MutateProject | ? | Update notebook metadata |
| MutateSource | ? | Update source metadata |
| RefreshSource | ? | Re-fetch URL source |
| RemoveRecentlyViewedProject | ? | Remove from recents |
| ReportContent | ? | Report problematic content |
| SendSdpOffer | `eyWvXc` ✓ | WebRTC SDP offer |
| SubmitFeedback | ? | Submit feedback on response |
| UpdateArtifact | ? | Update existing artifact |
| UpdateFeaturedNotebookStatus | ? | Publish/unpublish notebook |
| UpsertArtifactUserState | ? | Update per-user artifact state |

### LabsTailwindSharingService (3 methods)

| Method | rpcid | Notes |
|--------|-------|-------|
| CreateAccessRequest | ? | Request access to shared notebook |
| GetProjectDetails | ? | Get public notebook details |
| ShareProject | ? | Share notebook with others |

---

## Proto Enums

```python
class ArtifactType:
    STUDY_GUIDE = 1
    FAQ = 2
    BRIEFING_DOC = 3
    TIMELINE = 4
    TABLE_OF_CONTENTS = 5
    NOTE = 6
    AUDIO_OVERVIEW = 7
    VIDEO_OVERVIEW = 8

class SourceType:
    DRIVE = 1
    UPLOAD = 2
    URL = 3
    TEXT = 4
    YOUTUBE = 5

class VideoStyle:
    AUTOSELECT = "autoselect"
    CLASSIC = "classic"
    WHITEBOARD = "whiteboard"
    KAWAII = "kawaii"
    ANIME = "anime"
    WATERCOLOR = "watercolor"
    RETRO_PRINT = "retroprint"
    HERITAGE = "heritage"
    PAPER_CRAFT = "papercraft"
    CUSTOM = "custom"

class AudioFormat:
    DEEP_DIVE = 1    # "A lively conversation between two hosts..."
    BRIEF = 2        # "A bite-sized overview..."
```

---

## Error Responses

Known error strings from heap:
- `"GenerateFreeFormStreamedResponse is missing field 'answer'"` — malformed response
- `"NotesEffects: Unable to dispatch createNoteRequest"` — note creation failed
- Rate limit: HTTP 429 with retry-after header

---

## Rate Limits

| Tier | Queries/Day | Notebooks | Sources/Notebook |
|------|------------|-----------|-----------------|
| Free | 50 | 100 | 50 |
| Pro | 500 | 500 | 300 |
| Ultra | 5000 | 500 | 600 |

With `data/accounts/pool.json` multi-account rotation: effectively unlimited.

---

## Python Quick Reference

```python
from engine.integrations.nlm_direct_client import get_nlm_direct_client

client = get_nlm_direct_client()

# Chat with a notebook
answer = client.ask_question(notebook_uuid, "What are the key findings?")

# Create a study guide artifact  
artifact_id = client.create_artifact(notebook_uuid, "STUDY_GUIDE")

# Get notebook analysis
analysis = client.get_notebook_analysis(notebook_uuid)

# List all sources
sources = client.list_sources(notebook_uuid)

# Watch for real-time updates
for event in client.watch_notebook(notebook_uuid):
    print(event)
```

See `engine/integrations/nlm_direct_client.py` for full implementation.
