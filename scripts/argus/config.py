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

# ──── Known API keys (rotatable via GenerateCloudApiKey) ────
AISTUDIO_API_KEYS: List[str] = [
    "AIzaSyCB6OnnfuitFnaYWu4BvtGKaoLFk4cm-GE",
    "AIzaSyDdP816MREB3SkjZO04XQbjsigfcI0GWOs",
    "AIzaSyDHAQL7kdN6lNBcBok1eNB8dG7wwo6E6io",
]

# ──── Crawl timeouts ────
NAV_TIMEOUT_MS   = 30_000
ACTION_TIMEOUT_MS = 10_000
NETWORK_IDLE_MS  = 2_000

# ──── Scheduler ────
WEEKLY_SCAN_TASK = "argus-weekly-scan"
DIFF_REPORT_TASK = "argus-diff-report"
