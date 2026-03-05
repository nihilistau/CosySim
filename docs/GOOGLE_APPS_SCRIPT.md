# Google Apps Script

> GAS as a free serverless execution layer — every Google account is another
> compute node, with native access to all Workspace APIs and a public HTTPS
> webhook out of the box.

---

## What Is Google Apps Script

Google Apps Script (GAS) is a serverless JavaScript runtime hosted on Google's
infrastructure, built directly into every Google account.  Key properties:

- **Free** — unlimited execution time for personal use, 6-minute max per
  execution (30 min for Workspace accounts)
- **Native Workspace access** — `SpreadsheetApp`, `DriveApp`, `GmailApp`,
  `CalendarApp` work without OAuth, without credentials
- **Web App deployment** — any script can be deployed as a public HTTPS
  endpoint in two clicks (or one RPC call once we have `gas_client.py`)
- **Time triggers** — `ScriptApp.newTrigger().timeBased().everyHours(4)` is
  cron, for free
- **UrlFetchApp** — outbound HTTP with custom headers, including `Cookie` and
  `Authorization` — enough to call NLM batchexecute, CosySim REST endpoints,
  or any external API

---

## Why It Matters for CosySim

| Capability | What it enables |
|-----------|-----------------|
| Free serverless compute | Run scheduled intelligence on Google's servers — zero infrastructure cost |
| SpreadsheetApp (no auth) | Read/write Sheets without any API key — same account as our Sheets SDK |
| DriveApp (no auth) | Create, list, read Drive files without credentials |
| UrlFetchApp | Call NLM batchexecute with session cookies — same requests our Python SDK makes |
| Web App URL | Public HTTPS webhook for CosySim scheduler to POST tasks to |
| Time triggers | Autonomous scheduled loops that run even when CosySim is offline |

**Every Google account we have = another GAS environment.**  An account pool
of 10 accounts is 10 independent scheduled runtimes, each capable of running
NLM queries, writing to Sheets, and POSTing results back to CosySim.

The 39MB `script.google.com` HAR from the `nihilistcod` account contains the
full RPC pattern for creating, saving, running, and deploying scripts
programmatically.  Once ARGUS parses that HAR, we get `gas_client.py` and can
provision GAS environments from Python.

---

## Architecture: GAS as Webhook Receiver

CosySim sends a task to GAS and GAS executes it using its native Workspace
access, then POSTs the result back:

```
CosySim task scheduler
  → POST /api/execute
      → GAS Web App (public HTTPS URL, no auth required for our own requests)
          → SpreadsheetApp.openById(id).getSheetByName("tasks").appendRow([...])
          → DriveApp.createFile(name, content)
          → UrlFetchApp.fetch(NLM_ENDPOINT, {method: "POST", headers: {Cookie: ...}, payload: ...})
          → UrlFetchApp.fetch(COSYSIM_WEBHOOK, {method: "POST", payload: JSON.stringify(result)})
```

Example GAS Web App entry point:

```javascript
function doPost(e) {
  const payload = JSON.parse(e.postData.contents);
  const task = payload.task;
  const notebookId = payload.notebook_id;
  const question = payload.question;

  // Call NLM via UrlFetchApp — same request our Python client makes
  const nlmResponse = callNLM(notebookId, question);

  // Write result to Sheets (no OAuth — SpreadsheetApp is native)
  const sheet = SpreadsheetApp.openById(SHEET_ID).getSheetByName("results");
  sheet.appendRow([new Date(), question, nlmResponse]);

  // POST result back to CosySim
  UrlFetchApp.fetch(COSYSIM_CALLBACK_URL, {
    method: "post",
    contentType: "application/json",
    payload: JSON.stringify({ task, answer: nlmResponse, status: "ok" }),
  });

  return ContentService.createTextOutput("ok");
}
```

---

## Architecture: GAS as Scheduled Intelligence

A time trigger runs on Google's servers every 4 hours, completely
autonomously:

```
GAS time trigger (every 4h):
  → DriveApp.getFolderById(COSYSIM_FOLDER_ID).getFiles()
      → list new files since last run
  → for each new file:
      → UrlFetchApp → NLM batchexecute (ask question about the file)
      → parse answer from response
  → SpreadsheetApp.openById(QA_SHEET_ID).appendRow([timestamp, filename, q, a])
  → UrlFetchApp.fetch(COSYSIM_INGEST_URL, {method: "post", payload: JSON.stringify(qa_rows)})
```

This means knowledge from new Drive files propagates to the CosySim Nexus
automatically, even when the local workstation is off.

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

---

## The script.google.com HAR

The `script.google.com` HAR from the `nihilistcod` account is 39MB and has
not yet been parsed by ARGUS.  It contains the full browser-side RPC traffic
for the Apps Script IDE, including:

| Operation | Where in HAR | What we need |
|-----------|-------------|--------------|
| Create project | `ScriptService/CreateProject` batchexecute call | `rpcid` + payload shape |
| Save script source | `ScriptService/UpdateContent` batchexecute call | file structure format |
| Run function | `ScriptService/RunFunction` batchexecute call | execution trigger format |
| Deploy as Web App | `WebAppService/CreateDeployment` | deployment config structure |
| List deployments | `WebAppService/ListDeployments` | response parse pattern |
| Get execution log | `ScriptService/GetExecutionLog` | log format |

Once ARGUS extracts these rpcids, we can build `gas_client.py`:

```python
# Planned flow after ARGUS parses the HAR:
from engine.integrations.gas_client import get_gas_client

gas = get_gas_client("nihilistcod")

# Create a new Apps Script project
project_id = gas.create_script("CosySim NLM Caller")

# Push JavaScript source
gas.update_script(project_id, webhook_receiver_source_js)

# Deploy as public Web App
url = gas.deploy_as_webapp(project_id)
# → https://script.google.com/macros/s/{deployment_id}/exec

# Execute a specific function
result = gas.run_function(project_id, "runKnowledgeIngestion", args={})

# Check execution log
log = gas.get_executions(project_id)
```

**ARGUS priority:** parse `script.google.com` HAR → extract all batchexecute
rpcids → build `gas_client.py` SDK → test against a throwaway script project.

---

## Planned SDK: `engine/integrations/gas_client.py`

```python
"""Google Apps Script client — reverse-engineered from script.google.com HAR.

Provides programmatic creation, editing, deployment, and execution of
Google Apps Script projects.

All endpoints use the same batchexecute/SAPISIDHASH pattern as the other
Google SDK clients.
"""

class GASClient:
    def create_script(self, title: str, source_js: Optional[str] = None) -> str:
        """Create a new Apps Script project.

        Args:
            title: Display name for the project.
            source_js: Optional initial JavaScript source.

        Returns:
            Script project ID string.
        """
        ...

    def update_script(self, script_id: str, source_js: str) -> None:
        """Push new JavaScript source to an existing project.

        Args:
            script_id: Script project ID.
            source_js: Full JavaScript source code.
        """
        ...

    def deploy_as_webapp(
        self,
        script_id: str,
        access: str = "ANYONE_ANONYMOUS",
        execute_as: str = "USER_DEPLOYING",
    ) -> str:
        """Deploy a script as a public Web App.

        Args:
            script_id: Script project ID.
            access: Who can access: ANYONE_ANONYMOUS | ANYONE | DOMAIN | MYSELF.
            execute_as: Which account runs the code: USER_DEPLOYING | USER_ACCESSING.

        Returns:
            Public Web App URL (exec endpoint).
        """
        ...

    def run_function(
        self,
        script_id: str,
        function_name: str,
        args: Optional[Dict[str, Any]] = None,
    ) -> Any:
        """Execute a named function in the script.

        Args:
            script_id: Script project ID.
            function_name: Name of the function to call.
            args: Optional arguments to pass.

        Returns:
            Function return value.
        """
        ...

    def get_executions(self, script_id: str) -> List[Dict[str, Any]]:
        """Retrieve recent execution log entries.

        Args:
            script_id: Script project ID.

        Returns:
            List of execution records with timestamp, function, status, log.
        """
        ...


def get_gas_client(account_name: Optional[str] = None) -> Optional[GASClient]:
    """Get a GASClient for the named account or the next available one."""
    ...
```

---

## GAS Template Library (planned)

Location: `templates/gas/` — JavaScript templates for common GAS patterns.

### `webhook_receiver.js`

Receives POST requests from the CosySim scheduler, performs the requested
action using native Workspace APIs, and POSTs results back.

```javascript
const COSYSIM_SECRET = "{{secret}}";
const SHEET_ID = "{{sheet_id}}";
const COSYSIM_CALLBACK = "{{callback_url}}";

function doPost(e) {
  try {
    const data = JSON.parse(e.postData.contents);
    if (data.secret !== COSYSIM_SECRET) throw new Error("Unauthorized");

    let result;
    switch (data.action) {
      case "write_sheet":
        result = writeToSheet(data.sheet_name, data.rows);
        break;
      case "create_file":
        result = createDriveFile(data.filename, data.content);
        break;
      case "nlm_ask":
        result = callNLM(data.notebook_id, data.question);
        break;
      default:
        throw new Error(`Unknown action: ${data.action}`);
    }

    notifyCosySim({ task_id: data.task_id, result, status: "ok" });
    return ContentService.createTextOutput(JSON.stringify({ ok: true }))
      .setMimeType(ContentService.MimeType.JSON);
  } catch (err) {
    notifyCosySim({ task_id: data?.task_id, error: err.message, status: "error" });
    return ContentService.createTextOutput(JSON.stringify({ ok: false, error: err.message }))
      .setMimeType(ContentService.MimeType.JSON);
  }
}

function notifyCosySim(payload) {
  UrlFetchApp.fetch(COSYSIM_CALLBACK, {
    method: "post",
    contentType: "application/json",
    payload: JSON.stringify(payload),
    muteHttpExceptions: true,
  });
}
```

### `nlm_caller.js`

Calls the NLM batchexecute endpoint directly from GAS using session cookies
stored in Script Properties.

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

### `drive_processor.js`

Processes files in a Drive folder on a schedule — calls NLM on each new
file and appends results to a tracking Sheet.

```javascript
function processDriveFolder() {
  const folder = DriveApp.getFolderById(FOLDER_ID);
  const sheet = SpreadsheetApp.openById(TRACKER_SHEET_ID).getSheetByName("processed");
  const processedIds = new Set(
    sheet.getDataRange().getValues().map(row => row[0])
  );

  const files = folder.getFiles();
  while (files.hasNext()) {
    const file = files.next();
    if (processedIds.has(file.getId())) continue;

    const content = file.getBlob().getDataAsString().slice(0, 3000);
    const summary = callNLM(NOTEBOOK_ID, `Extract 5 key facts from: ${content}`);

    sheet.appendRow([
      file.getId(),
      file.getName(),
      new Date(),
      summary,
    ]);
  }
}
```

### `nexus_ingestor.js`

Reads Q&A pairs from a Sheet and POSTs them to the CosySim Nexus API.

```javascript
function ingestToNexus() {
  const sheet = SpreadsheetApp.openById(QA_SHEET_ID).getSheetByName("qa");
  const rows = sheet.getDataRange().getValues().slice(1); // skip header
  const unsynced = rows.filter(row => !row[4]); // col 4 = synced flag

  if (unsynced.length === 0) return;

  const payload = unsynced.map(row => ({
    question: row[0],
    answer: row[1],
    category: row[2] || "general",
    source: row[3] || "gas",
  }));

  const response = UrlFetchApp.fetch(`${COSYSIM_URL}/api/nexus/ingest`, {
    method: "post",
    contentType: "application/json",
    payload: JSON.stringify({ qa_pairs: payload }),
  });

  if (response.getResponseCode() === 200) {
    // Mark rows as synced
    unsynced.forEach((_, i) => {
      sheet.getRange(i + 2, 5).setValue("synced");
    });
  }
}
```

---

## Client-Side Research Targets (ARGUS + Heap)

These are open questions about the NLM client-side that heap analysis and
HAR parsing may answer.  Each has significant value once resolved.

### NLM Quota Counter

**Target:** `remainingQueries` or similar field in the NLM heap snapshot.
**Value:** Know exactly when an account hits the daily query limit so the
account pool can rotate to a fresh account rather than getting 429s.

```python
# Once found: check before each call
if nlm_client.get_remaining_quota() < 5:
    pool.rotate_account("notebooklm")
```

### Model Override in batchexecute

**Target:** The `model` or `modelVersion` field in the GenerateFreeFormStreamed
or batchexecute payload.
**Value:** Force Gemini 2.5 Pro instead of the default model for specific
notebook operations — potentially higher quality answers for key flywheel calls.

Current payload for `CYK0Xb` (create_note):
```
[notebook_id, prompt]
```

If a model field exists:
```
[notebook_id, prompt, {"model": "gemini-2.5-pro-exp"}]
```

### AI Studio Model ID Override

**Target:** The model identifier in AI Studio's inference request.
**Value:** Try frontier models for one-shot notebook generation without changing
the Colab AI Agent path.

The `aistudio_client.py` and `gemini_direct_client.py` in `engine/integrations/`
already talk to the AI Studio inference endpoint.  The model field is
client-side and confirmed overridable — identifying the exact payload position
lets us switch models without a UI.

### Feature Flag IDs (GetFeatureFlags rpcid)

**Target:** Feature flag IDs 400–1200 in the NLM batchexecute
`GetFeatureFlags` RPC.
**Value:** Some flags gate premium generation capabilities (higher audio quality,
longer outputs, extended context window, video overviews).  If they can be
set in the request, free accounts can access premium output quality.

```python
# Planned: scan flag range and test each one
flags = nlm_client.get_feature_flags()
for flag_id in range(400, 1200):
    if flags.get(str(flag_id)) == 0:
        # try enabling it
        result = nlm_client.set_feature_flag(flag_id, 1)
        # measure quality difference
```

**Research owner:** ARGUS heap parser → `heap_deep_parser.py`.
This is the same parser that found the 61 methods from `V8` heap snapshots
documented in `NLM_JOURNEY.md`.

---

## Integration with CosySim Scheduler

When `gas_client.py` is available, the CosySim scheduler (`engine/scheduler/`)
can provision, update, and trigger GAS scripts as scheduled tasks:

```python
# Hypothetical scheduler task definition
{
    "task_id": "gas_nlm_daily_distill",
    "type": "gas_trigger",
    "schedule": "0 */4 * * *",          # every 4 hours
    "script_template": "nlm_caller.js",
    "params": {
        "notebook_id": "{{active_notebook}}",
        "question": "{{daily_question}}",
        "output_sheet_id": "{{qa_sheet_id}}",
    }
}
```

The scheduler provisions the script on first run, updates params on each
execution, and receives results via the CosySim webhook at
`/api/scheduler/gas_callback`.

This closes the loop: CosySim intelligence runs autonomously on Google's
servers, feeds results back into Nexus, and the local system wakes up to
a richer knowledge base — even after days offline.
