"""ARGUS configuration — all known baselines, targets, and constants."""
from __future__ import annotations

from pathlib import Path
from typing import Dict, List

# ──── Paths ────
ROOT = Path(__file__).resolve().parents[2]          # CosySim root
DATA_DIR = ROOT / "data" / "argus"
DATA_DIR.mkdir(parents=True, exist_ok=True)

REGISTRY_PATH   = DATA_DIR / "registry.json"
SSLKEYS_PATH    = DATA_DIR / "sslkeys.log"
CAPTURES_DIR    = DATA_DIR / "captures"
HEAP_DIR        = DATA_DIR / "heaps"
REPORTS_DIR     = DATA_DIR / "reports"

for _d in (CAPTURES_DIR, HEAP_DIR, REPORTS_DIR):
    _d.mkdir(parents=True, exist_ok=True)

# ──── Chrome CDP ────
CDP_HOST = "localhost"
CDP_PORT = 9222
CDP_URL  = f"http://{CDP_HOST}:{CDP_PORT}"

# ──── tshark ────
TSHARK_PATH   = r"C:\Program Files\Wireshark\tshark.exe"
DUMPCAP_PATH  = r"C:\Program Files\Wireshark\dumpcap.exe"

# ──── Targets ────
TARGETS: Dict[str, Dict] = {
    "notebooklm": {
        "base_url":   "https://notebooklm.google.com",
        "batch_url":  "https://notebooklm.google.com/_/LabsTailwindUi/data/batchexecute",
        "service":    "LabsTailwindUi",
    },
    "gemini": {
        "base_url":   "https://gemini.google.com",
        "batch_url":  "https://gemini.google.com/_/BardChatUi/data/batchexecute",
        "service":    "BardChatUi",
        "grpc_url":   "https://gemini.google.com/$rpc/google.internal.bard.BardFrontendService",
    },
    "aistudio": {
        "base_url":   "https://aistudio.google.com",
        "grpc_url":   "https://alkalimakersuite-pa.clients6.google.com/$rpc/google.internal.alkali.applications.makersuite.v1.MakerSuiteService",
        "webchannel": "https://webchannel-alkalimakersuite-pa.clients6.google.com",
        "service":    "MakerSuiteService",
    },
}

# ──── Known NLM rpcids (24 decoded) ────
NLM_RPCIDS: Dict[str, str] = {
    "wIlBFe": "ListNotebooks",
    "VqhFhd": "CreateNotebook",
    "kVoZqc": "DeleteNotebook",
    "sM6gLf": "UpdateNotebook",
    "mFtdI":  "GetNotebook",
    "PoHVkb": "AddSource",
    "VSSXud": "DeleteSource",
    "K4YCPe": "GetSource",
    "jtGGne": "ListSources",
    "bfEAsb": "ProcessSource",
    "tJHFsf": "SendChatMessage",
    "GzgSEd": "GetChatHistory",
    "GfmCOc": "DeleteChatHistory",
    "xqEXEf": "GenerateGuide",
    "sqTeoe": "GetAudioOverview",
    "VfAZjd": "GetNotebookAnalysis",
    "dI5Y8":  "ShareNotebook",
    "jzEKsc": "GetSharedNotebook",
    "Of0kDd": "GetIceConfig",
    "eyWvXc": "SendSdpOffer",
    "ozz5Z":  "GetFeatureFlags",
    "ub2Bae": "UNKNOWN_1",
    "DYBcR":  "UNKNOWN_2",
    "sqTeoe": "GetAudioOverviewOptions",
}

# ──── Known Gemini rpcids (17 decoded) ────
GEMINI_RPCIDS: Dict[str, str] = {
    "boaYGb": "ProxyUnaryCall",           # returns thoughtSignature
    "NXpLKc": "ListLinkedNotebooks",      # Gemini-NLM bridge
    "jKHnxe": "GenerateContent",
    "r7Bvze": "StreamGenerateContent",
    "mMEAEd": "CountTokens",
    "k9yDXd": "ListModels",
    "XqsOBb": "GetModel",
    "BgXnQc": "CreateFile",
    "mfvMVb": "ListFiles",
    "qVSQ5c": "DeleteFile",
    "ozVbQb": "GetFile",
    "VUBhEd": "CreateCachedContent",
    "dXH9nb": "ListCachedContents",
    "sPOurf": "DeleteCachedContent",
    "jPv1oc": "GetCachedContent",
    "ozz5Z":  "GetFeatureFlags",
    "DYBcR":  "UNKNOWN_locale",
}

# ──── Known AI Studio methods (136 decoded) ────
AISTUDIO_METHODS: List[str] = [
    # Content generation
    "GenerateContent", "StreamGenerateContent", "BidiGenerateContent",
    "CountTokens", "EmbedContent", "BatchEmbedContents",
    # Applets
    "CreateApplet", "GetApplet", "ListApplets", "UpdateApplet", "DeleteApplet",
    "DeployApplet", "UndeployApplet", "UpsertAppletSecret", "CloneApplet",
    # Datasets (undocumented)
    "CreateDataset", "GetDataset", "ListDatasets", "UpdateDataset", "DeleteDataset",
    "ImportDatasetItems", "ExportDatasetItems", "AnnotateDataset",
    # GitHub integration (undocumented)
    "CreateGitHubRepository", "SyncGitHubRepository", "GetGitHubRepository",
    # Image/Video (undocumented)
    "GenerateImage", "GenerateVideo", "StreamExtractVideoFrames",
    "UpscaleImage", "EditImage", "GenerateImageFromText",
    # Speech (undocumented)
    "GeminiSpeechToText", "TextToSpeech", "StreamSpeechToText",
    # Code/Build (undocumented)
    "DownloadBuildArtifacts", "StreamCodeAssistantOfflineGeneration",
    "FetchPiperFile", "StreamLogs",
    # Cloud infra (undocumented)
    "GenerateCloudApiKey", "CreateCloudProject", "ListCloudProjects",
    "GetBillingInfo", "CheckQuota",
    # Tuning
    "CreateTunedModel", "GetTunedModel", "ListTunedModels",
    "UpdateTunedModel", "DeleteTunedModel", "GenerateTunedContent",
    # Models
    "GetModel", "ListModels", "GetModelCard", "ListModelCards", "GetModelCapabilities",
    # Files
    "CreateFile", "GetFile", "ListFiles", "DeleteFile", "DownloadFile",
    # Cached content
    "CreateCachedContent", "GetCachedContent", "ListCachedContents",
    "UpdateCachedContent", "DeleteCachedContent",
    # Prompts / apps
    "CreatePrompt", "GetPrompt", "ListPrompts", "UpdatePrompt", "DeletePrompt",
    "CreateApp", "GetApp", "ListApps", "UpdateApp", "DeleteApp",
    # Corpus / retrieval
    "CreateCorpus", "GetCorpus", "ListCorpora", "UpdateCorpus", "DeleteCorpus",
    "CreateDocument", "GetDocument", "ListDocuments", "DeleteDocument",
    "CreateChunk", "GetChunk", "ListChunks", "UpdateChunk", "DeleteChunk",
    "QueryCorpus", "QueryDocument",
    # Operations
    "GetOperation", "ListOperations", "CancelOperation", "DeleteOperation",
    # User/settings
    "GetUserSettings", "UpdateUserSettings", "GetUsageMetadata",
    # Notifications
    "ListNotifications", "MarkNotificationRead", "DismissNotification",
    # Collaboration
    "SharePrompt", "GetSharedPrompt", "ListSharedPrompts",
    # Batch
    "CreateBatchJob", "GetBatchJob", "ListBatchJobs", "CancelBatchJob",
    # Safety
    "CheckSafety", "GetSafetySettings", "UpdateSafetySettings",
]

# ──── Feature flag probe range ────
FLAG_ID_RANGE = range(300, 1500)   # enumerate these via ozz5Z (GetFeatureFlags)

# ──── Google Apps Script target ────
TARGETS["apps_script"] = {
    "base_url":   "https://script.google.com",
    "batch_url":  "https://script.google.com/_/AppsPlatformConsoleUi/data/batchexecute",
    "service":    "AppsPlatformConsoleUi",
    "har_path":   str(ROOT / "data" / "har_files" / "nihilistcod" / "script.google.com.har"),
    "notes":      "25 rpcids mapped by ARGUS. Full ArtifactService proto interface reconstructed from V8 heap.",
}

# ──── Google Cloud Console target ────
TARGETS["cloud_console"] = {
    "base_url":   "https://console.cloud.google.com",
    "entity_api": "https://cloudconsole-pa.clients6.google.com/v3/entityServices",
    "service":    "cloudconsole-pa",
    "har_path":   str(ROOT / "data" / "har_files" / "users_dump_folder" / "gold" / "console.cloud.google.com.har"),
    "notes":      "Cloud Console entity service API. /v3/entityServices/{Service}/schema for proto info.",
}

# ──── Complete ArtifactService proto interface (39 methods) — reconstructed from V8 heap ────
# Source: Heap-app-script-20260305T105838.heapsnapshot, 110,645 strings analysed by ARGUS
# All strings match /ArtifactService.MethodName pattern in heap
GAS_ARTIFACT_SERVICE_METHODS: List[str] = [
    "CopyProject", "ListTemplates", "GetProjectDeployments", "GetProjectType",
    "SetProjectContent", "GetAppsPlatformFile", "GetScriptProperties",
    "GetAppsPlatformFileStatus", "CancelProcess", "ListDeployments",
    "ListAppsPlatformFiles", "ListTriggers", "GetAggregateMetrics",
    "SetProjectType", "UpdateAppsPlatformFile", "SetDeploymentEnvironment",
    "GetPublishDialogPreference", "ListVersions", "GetDeploymentEnvironment",
    "SetPublishDialogPreference", "SetGcpProject", "SetScriptProperties",
    "GetProjectContent", "GetActiveAccountPopupInfo", "ListScriptPermissions",
    "DeleteAppsPlatformFile", "ListProcesses", "UpsertProjectDeployment",
]

# Additional services discovered in heap
GAS_OTHER_SERVICE_METHODS: Dict[str, List[str]] = {
    "AppsPlatformConsoleUserService": [
        "GetDthreeInfo", "UpdateUserPreferences", "LogClientMetrics",
        "GetUserPreferences", "GetNascentExperimentStatus",
    ],
    "WidgetService": [
        "GetAccountMenuModel", "GetExpressAccountPickerModel",
        "GetAppWidgetModel", "GetCalloutModel",
    ],
    "TriggersService": ["DeleteTrigger"],
    "StorageProjectService": ["GetCloudProjectPermissions"],
}

# ──── Known GAS rpcids (25 mapped — V1 from nihilistcod HAR, V2 from gold HAR + heap analysis) ────
GAS_RPCIDS: Dict[str, str] = {
    # === ORIGINAL 15 — source-path inference from nihilistcod 39MB HAR ===
    # Confidence: HEAP_CONFIRMED = heap dist < 10; PAYLOAD = inferred from payload shape;
    #             SOURCE_PATH = inferred from source-path URL patterns
    "OOPYjd": "GetProjectContent",       # 26 calls — every page; project file content loader
    "OQOG2e": "ListAppsPlatformFiles",   # 5 calls  — editor+settings+history; file listing
    "AJ6bre":  "GetDeployments",         # 5 calls  — editor+history+triggers; deployment list
    "pEig0e":  "RunFunction",            # 1 call   — editor; executes a script function
    "ivJzse":  "ListTriggers",           # 2 calls  — editor; (heap: ArtifactService.ListTriggers dist=153)
    "toGAmc":  "SaveScript",             # 1 call   — editor; save script files
    "LuHlxe":  "CompileScript",          # 1 call   — editor; compile/syntax check
    "UvGaob":  "GetScriptProperties",    # 1 call   — settings; (heap: CopyProject dist=104 — low confidence, overridden by context)
    "KKLVD":   "SetPublishDialogPreference",  # 1 call — triggers; (heap: SetPublishDialogPreference dist=126)
    "qqL5ld":  "GetScriptProperties",   # 1 call   — history + settings; (heap: SetPublishDialogPreference dist=208)
    "zzomTc":  "GetExpressAccountPickerModel",  # 1 call — editor; (heap: WidgetService.GetExpressAccountPickerModel dist=141)
    "yFXSbd":  "ListVersions",           # 1 call   — home+editor; (heap: ArtifactService.ListVersions dist=314)
    "NFMk7c":  "CreateProject",          # 1 call   — project root; creates new GAS project
    "GXx9jd":  "GetProjectMetadata",     # 2 calls  — project root; metadata/info
    "AvwHP":   "GetDeploymentEnvironment",  # HEAP_CONFIRMED dist=4 — ArtifactService.GetDeploymentEnvironment

    # === NEW 10 — discovered from gold 44MB HAR (script.google.com) ===
    # Payload analysis provides high confidence mappings
    "kGFage":  "ListProjects",           # PAYLOAD: [['', None, 3, 1, 0, None, [1, 2]], 50] — pagination params, /home/
    "gckeOc":  "GetProjectByUrl",        # PAYLOAD: [project_id] from /home/ — project preview/lookup
    "FoxP1d":  "GetProjectDeployments",  # PAYLOAD: [project_id] from project page
    "Wy5Y7":   "GetProjectType",         # PAYLOAD: [full_url] — type lookup by URL
    "qejt0e":  "GetEditorState",         # called with OQOG2e on /edit — editor initialization
    "C0veKb":  "GetAppsPlatformFileStatus",  # /edit — file status check
    "iP35l":   "GetProjectContent",      # PAYLOAD: [project_id] on /edit — loads editor files (NEW rpcid for same function?)
    "KhxE6":   "UpdateAppsPlatformFile", # PAYLOAD: [project_id, [['appsscript', 3, '{manifest_json}']]] — saves manifest
    "L650eb":  "SetUserPreferences",     # PAYLOAD: [1] on /edit — preference toggle
}

# ──── Client-side override research targets (heap diff priorities) ────
HEAP_OVERRIDE_TARGETS: Dict[str, Dict] = {
    "nlm_query_quota": {
        "target": "notebooklm",
        "fields_to_find": ["remainingQueries", "queryLimit", "dailyQuota", "queryCount"],
        "method": "heap_diff_before_after_query",
        "notes": "Likely client-side counter — decrement may not be server-enforced",
    },
    "nlm_model_field": {
        "target": "notebooklm",
        "fields_to_find": ["model", "modelVersion", "backendModel", "generationConfig"],
        "method": "heap_diff_before_after_canvas_prompt",
        "notes": "CYK0Xb payload — swap to gemini-2.5-pro or gemini-2.0-flash-thinking",
        "candidate_overrides": ["gemini-2.5-pro", "gemini-2.5-pro-exp-03-25", "gemini-exp-1206"],
    },
    "nlm_notebook_limit": {
        "target": "notebooklm",
        "fields_to_find": ["notebookCount", "notebookLimit", "maxNotebooks"],
        "method": "heap_snapshot_on_load",
        "notes": "Free tier = 100. Counter lives somewhere in initial page state.",
    },
    "aistudio_model_list": {
        "target": "aistudio",
        "fields_to_find": ["allowedModels", "modelTier", "availableModels"],
        "method": "intercept_ListModels_response",
        "notes": "AI Studio model ID is passed client-side — confirmed overridable",
    },
    "feature_flags": {
        "target": "notebooklm",
        "rpcid": "ozz5Z",   # GetFeatureFlags — same rpcid in NLM and Gemini
        "probe_range": FLAG_ID_RANGE,
        "notes": "Flags 400-1200. Some gate longer notebooks, premium models, higher quotas.",
    },
}

# ──── Feature flag probe range (defined above, kept here for context) ────
# FLAG_ID_RANGE = range(300, 1500) — moved above HEAP_OVERRIDE_TARGETS

# ──── Known API keys (rotatable via GenerateCloudApiKey) ────
AISTUDIO_API_KEYS: List[str] = [
    "REDACTED-GOOGLE-API-KEY",
    "REDACTED-GOOGLE-API-KEY",
    "REDACTED-GOOGLE-API-KEY",
]

# ──── Crawl timeouts ────
NAV_TIMEOUT_MS   = 30_000
ACTION_TIMEOUT_MS = 10_000
NETWORK_IDLE_MS  = 2_000

# ──── Scheduler ────
WEEKLY_SCAN_TASK = "argus-weekly-scan"
DIFF_REPORT_TASK = "argus-diff-report"
