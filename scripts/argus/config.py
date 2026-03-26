"""ARGUS configuration — all known baselines, targets, and constants.

Baselines (NLM_RPCIDS, GEMINI_RPCIDS, AISTUDIO_METHODS, etc.) are derived
dynamically from config/nlm_rpcids.yaml at import time. Hardcoded fallbacks
are kept inline for graceful degradation if the YAML is missing or corrupt.

Version: v1.57.0 [2026-03-26]

Change Log:
    v1.57.0 [2026-03-26] — Add Gemini File Search API endpoints for reconnaissance
"""
from __future__ import annotations

import logging
from pathlib import Path
from typing import Any, Dict, List, Optional

import yaml

from scripts.argus.paths import (
    CAPTURES_DIR,
    DATA_DIR,
    HAR_DIR,
    HEAP_DIR,
    REGISTRY_PATH,
    REPORTS_DIR,
    ROOT,
    SSLKEYS_PATH,
)

_logger = logging.getLogger(__name__)
_YAML_PATH = Path(__file__).resolve().parents[2] / "config" / "nlm_rpcids.yaml"


def _load_yaml_registry() -> Optional[Dict[str, Any]]:
    """Load the YAML registry, returning None on failure."""
    try:
        with open(_YAML_PATH, encoding="utf-8") as f:
            return yaml.safe_load(f)
    except Exception as exc:
        _logger.warning("ARGUS config: failed to load YAML registry: %s", exc)
        return None


def _derive_nlm_rpcids(data: Dict[str, Any]) -> Dict[str, str]:
    """Extract {rpcid: method_name} from YAML NLM operations."""
    result: Dict[str, str] = {}
    for op_name, op_def in data.get("operations", {}).items():
        if not isinstance(op_def, dict):
            continue
        rpcid = op_def.get("rpcid")
        if rpcid:
            name = op_def.get("service_method") or op_def.get("description", op_name)
            result[rpcid] = name
    return result


def _derive_gemini_rpcids(data: Dict[str, Any]) -> Dict[str, str]:
    """Extract {rpcid: name} from YAML Gemini section."""
    result: Dict[str, str] = {}
    for rpcid, info in data.get("gemini", {}).get("rpcids", {}).items():
        if isinstance(info, dict):
            name = info.get("name") or info.get("description", rpcid)
        elif info is None:
            name = rpcid
        else:
            name = str(info)
        result[rpcid] = name
    return result


def _derive_aistudio_methods(data: Dict[str, Any]) -> List[str]:
    """Extract method name list from YAML AI Studio section."""
    methods = data.get("aistudio", {}).get("methods", {})
    return sorted(methods.keys())


def _derive_colab_methods(data: Dict[str, Any]) -> Dict[str, str]:
    """Extract {method: service} from YAML Colab section."""
    result: Dict[str, str] = {}
    for method, info in data.get("colab", {}).get("methods", {}).items():
        service = "Unknown"
        if isinstance(info, dict):
            service = info.get("service", "ColabService")
        result[method] = service
    return result


def _derive_appscript_rpcids(data: Dict[str, Any]) -> Dict[str, str]:
    """Extract {rpcid: method_name} from YAML Apps Script section."""
    result: Dict[str, str] = {}
    for op_name, op_def in data.get("appscript", {}).get("operations", {}).items():
        if not isinstance(op_def, dict):
            continue
        rpcid = op_def.get("rpcid")
        if rpcid:
            name = op_def.get("service_method") or op_def.get("description", op_name)
            result[rpcid] = name
    return result


def _derive_workspace_services(data: Dict[str, Any]) -> Dict[str, Dict[str, Any]]:
    """Extract all workspace service sections as {section: {op_name: op_def}}."""
    ws_prefixes = (
        "workspace_", "sheets_", "docs_", "drive_", "cloud_", "people_",
    )
    result: Dict[str, Dict[str, Any]] = {}
    for key in data:
        if any(key.startswith(p) for p in ws_prefixes):
            section = data[key]
            if isinstance(section, dict):
                for ops_key in ("operations", "methods", "rpcids", "endpoints"):
                    if ops_key in section and isinstance(section[ops_key], dict):
                        result[key] = section[ops_key]
                        break
    return result


def _derive_nlm_grpc(data: Dict[str, Any]) -> Dict[str, str]:
    """Extract NLM gRPC methods from YAML."""
    result: Dict[str, str] = {}
    for method, info in data.get("nlm_grpc", {}).get("methods", {}).items():
        service = "LabsTailwindOrchestrationService"
        if isinstance(info, dict):
            service = info.get("service", service)
        result[method] = service
    return result


def _derive_heap_discovered(data: Dict[str, Any]) -> Dict[str, str]:
    """Extract heap-discovered methods from YAML."""
    result: Dict[str, str] = {}
    for method, info in data.get("nlm_heap_discovered", {}).get("methods", {}).items():
        service = "Unknown"
        if isinstance(info, dict):
            service = info.get("service", service)
        result[method] = service
    return result

# ──── Chrome CDP ────
CDP_HOST = "localhost"
CDP_PORT = 9223
CDP_URL  = f"http://{CDP_HOST}:{CDP_PORT}"

# ──── tshark ────
TSHARK_PATH   = r"C:\Program Files\Wireshark\tshark.exe"
DUMPCAP_PATH  = r"C:\Program Files\Wireshark\dumpcap.exe"

# ──── Targets ────
TARGETS: Dict[str, Dict] = {
    "google_aim": {
        "base_url":      "https://www.google.com",
        "search_url":    "https://www.google.com/search",
        "folif_url":     "https://www.google.com/async/folif",
        "service_url":   "https://www.google.com/httpservice/web/AimThreadsService",
        "service":       "AimThreadsService",
        "notes": "Google AI Mode (udm=50). Canvas feature released 2026-03-05.",
    },
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
        "url_aliases": ["ai.google.dev/studio", "aistudio.google.com"],
        "grpc_url":   "https://alkalimakersuite-pa.clients6.google.com/$rpc/google.internal.alkali.applications.makersuite.v1.MakerSuiteService",
        "webchannel": "https://webchannel-alkalimakersuite-pa.clients6.google.com",
        "service":    "MakerSuiteService",
    },
}

# v1.57.0 [2026-03-26] — Gemini File Search (managed RAG) API endpoints
# These are the REST endpoints for the Gemini File Search stores, which provide
# server-managed document retrieval with grounded citations.
# Docs: https://ai.google.dev/gemini-api/docs/file-search
FILE_SEARCH_ENDPOINTS: Dict[str, str] = {
    "stores": "https://generativelanguage.googleapis.com/v1beta/fileSearchStores",
    "documents": "https://generativelanguage.googleapis.com/v1beta/fileSearchStores/{store}/documents",
    "query": "https://generativelanguage.googleapis.com/v1beta/fileSearchStores/{store}:query",
    "create_store": "https://generativelanguage.googleapis.com/v1beta/fileSearchStores",
    "delete_store": "https://generativelanguage.googleapis.com/v1beta/fileSearchStores/{store}",
}

# ──── Load YAML registry and derive baselines ────
_yaml_data = _load_yaml_registry()

# Hardcoded fallbacks used when YAML is missing/corrupt
_NLM_RPCIDS_FALLBACK: Dict[str, str] = {
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
    "ub2Bae": "ListNotebooks",
    "DYBcR":  "GetLocalePreferences",
}

_GEMINI_RPCIDS_FALLBACK: Dict[str, str] = {
    "boaYGb": "ProxyUnaryCall",
    "NXpLKc": "GetLinkedNotebooks",
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
    "DYBcR":  "GetLocalePreferences",
    "MaZiqc": "Unknown",
    "maGuAc": "Unknown",
    "o30O0e": "Unknown",
    "qpEbW":  "Unknown",
    "L5adhe": "Unknown",
    "aPya6c": "Unknown",
    "CNgdBe": "Unknown",
    "ku4Jyf": "Unknown",
}

# Derive from YAML, fall back to hardcoded
NLM_RPCIDS: Dict[str, str] = _derive_nlm_rpcids(_yaml_data) if _yaml_data else _NLM_RPCIDS_FALLBACK
GEMINI_RPCIDS: Dict[str, str] = _derive_gemini_rpcids(_yaml_data) if _yaml_data else _GEMINI_RPCIDS_FALLBACK
AISTUDIO_METHODS: List[str] = _derive_aistudio_methods(_yaml_data) if _yaml_data else []
COLAB_METHODS: Dict[str, str] = _derive_colab_methods(_yaml_data) if _yaml_data else {}
APPSCRIPT_RPCIDS: Dict[str, str] = _derive_appscript_rpcids(_yaml_data) if _yaml_data else {}
WORKSPACE_OPERATIONS: Dict[str, Dict[str, Any]] = _derive_workspace_services(_yaml_data) if _yaml_data else {}
NLM_GRPC_METHODS: Dict[str, str] = _derive_nlm_grpc(_yaml_data) if _yaml_data else {}
HEAP_DISCOVERED_METHODS: Dict[str, str] = _derive_heap_discovered(_yaml_data) if _yaml_data else {}

# Merge hardcoded fallback into YAML-derived to catch any rpcids that
# appear in HAR captures but haven't been added to YAML yet
if _yaml_data:
    for rpcid, name in _NLM_RPCIDS_FALLBACK.items():
        NLM_RPCIDS.setdefault(rpcid, name)
    for rpcid, name in _GEMINI_RPCIDS_FALLBACK.items():
        GEMINI_RPCIDS.setdefault(rpcid, name)

if not AISTUDIO_METHODS:
    AISTUDIO_METHODS = [
        "GenerateContent", "StreamGenerateContent", "BidiGenerateContent",
        "CountTokens", "EmbedContent", "BatchEmbedContents",
        "CreateApplet", "GetApplet", "ListApplets", "UpdateApplet", "DeleteApplet",
        "DeployApplet", "UndeployApplet", "UpsertAppletSecret", "CloneApplet",
        "CreateDataset", "GetDataset", "ListDatasets", "UpdateDataset", "DeleteDataset",
        "ImportDatasetItems", "ExportDatasetItems", "AnnotateDataset",
        "CreateGitHubRepository", "SyncGitHubRepository", "GetGitHubRepository",
        "GenerateImage", "GenerateVideo", "StreamExtractVideoFrames",
        "UpscaleImage", "EditImage", "GenerateImageFromText",
        "GeminiSpeechToText", "TextToSpeech", "StreamSpeechToText",
        "DownloadBuildArtifacts", "StreamCodeAssistantOfflineGeneration",
        "FetchPiperFile", "StreamLogs",
        "GenerateCloudApiKey", "CreateCloudProject", "ListCloudProjects",
        "GetBillingInfo", "CheckQuota",
        "CreateTunedModel", "GetTunedModel", "ListTunedModels",
        "UpdateTunedModel", "DeleteTunedModel", "GenerateTunedContent",
        "GetModel", "ListModels", "GetModelCard", "ListModelCards", "GetModelCapabilities",
        "CreateFile", "GetFile", "ListFiles", "DeleteFile", "DownloadFile",
        "CreateCachedContent", "GetCachedContent", "ListCachedContents",
        "UpdateCachedContent", "DeleteCachedContent",
        "CreatePrompt", "GetPrompt", "ListPrompts", "UpdatePrompt", "DeletePrompt",
        "CreateApp", "GetApp", "ListApps", "UpdateApp", "DeleteApp",
        "CreateCorpus", "GetCorpus", "ListCorpora", "UpdateCorpus", "DeleteCorpus",
        "CreateDocument", "GetDocument", "ListDocuments", "DeleteDocument",
        "CreateChunk", "GetChunk", "ListChunks", "UpdateChunk", "DeleteChunk",
        "QueryCorpus", "QueryDocument",
        "GetOperation", "ListOperations", "CancelOperation", "DeleteOperation",
        "GetUserSettings", "UpdateUserSettings", "GetUsageMetadata",
        "ListNotifications", "MarkNotificationRead", "DismissNotification",
        "SharePrompt", "GetSharedPrompt", "ListSharedPrompts",
        "CreateBatchJob", "GetBatchJob", "ListBatchJobs", "CancelBatchJob",
        "CheckSafety", "GetSafetySettings", "UpdateSafetySettings",
        "CodeAssistantOffline", "StreamCodeAssistantOfflineGenerationUpload",
        "GetCodeAssistantSnapshot", "LoadCodeAssistantInteractionHistory",
        "ListCodeAssistantConfigurations", "ListCodeAssistantFeatures",
        "ListCodeAssistantOfflineGenerations", "ListCodeGenSuggestionCards",
        "GenerateCodeAssistantSuggestionChips",
        "GenerateAccessToken", "GetLoggingContext", "GetUserPreferences",
        "ListCloudApiKeys", "ListPromos", "ListUnsetAppletSecrets",
        "ListRecentApplets", "StoreRecentApplet",
        "ListImportedProjects", "ProvisionAndInitializeApplet",
        "FetchMetricTimeSeries", "Log", "SaveApplet",
    ]

_logger.debug(
    "ARGUS baselines loaded: NLM=%d, Gemini=%d, AIS=%d, Colab=%d, AppScript=%d, Workspace=%d sections, gRPC=%d, Heap=%d",
    len(NLM_RPCIDS), len(GEMINI_RPCIDS), len(AISTUDIO_METHODS),
    len(COLAB_METHODS), len(APPSCRIPT_RPCIDS), len(WORKSPACE_OPERATIONS),
    len(NLM_GRPC_METHODS), len(HEAP_DISCOVERED_METHODS),
)

# ──── Feature flag probe range ────
FLAG_ID_RANGE = range(300, 1500)   # enumerate these via ozz5Z (GetFeatureFlags)

# ──── Google Apps Script target ────
TARGETS["apps_script"] = {
    "base_url":   "https://script.google.com",
    "batch_url":  "https://script.google.com/_/AppsPlatformConsoleUi/data/batchexecute",
    "service":    "AppsPlatformConsoleUi",
    "har_path":   str(HAR_DIR / "nihilistcod" / "script.google.com.har"),
    "notes":      "25 rpcids mapped by ARGUS. Full ArtifactService proto interface reconstructed from V8 heap.",
}

# ──── Google Cloud Console target ────
TARGETS["cloud_console"] = {
    "base_url":   "https://console.cloud.google.com",
    "entity_api": "https://cloudconsole-pa.clients6.google.com/v3/entityServices",
    "service":    "cloudconsole-pa",
    "har_path":   str(HAR_DIR / "users_dump_folder" / "gold" / "console.cloud.google.com.har"),
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

# ──── Known AIM (Google AI Mode) endpoints — discovered 2026-03-05 from HAR + heap ────
# Entry point: GET /search?q=...&udm=50&aep=10
# Canvas identifier: "aim/canvas" in folif response HTML
AIM_ENDPOINTS: Dict[str, str] = {
    # Conversation (GET requests via /async/)
    "/async/folif":                            "FollowUpInFlow",        # GET — conversation turn (folif = follow-up in flow)
    "/async/folwr":                            "FollowWithRewrite",     # GET — canvas rewrite/edit mode (folwr = follow with rewrite)
    "/async/imgv":                             "ImageViewer",           # GET — inline image viewer within AI Mode (udm=50+aep=10)
    # AimThreadsService methods (POST /httpservice/web/AimThreadsService/{method})
    "AimThreadsService/ListThreads":           "ListThreads",           # list saved AI Mode threads
    "AimThreadsService/ListSharedThreads":     "ListSharedThreads",     # list shared threads
    "AimThreadsService/SearchThreads":         "SearchThreads",         # search threads by keyword
    "AimThreadsService/GetThreadContext":      "GetThreadContext",      # get thread detail/history
    "AimThreadsService/ExportThread":          "ExportThread",          # export canvas as JSPB HTML
    "AimThreadsService/UpdateThread":          "UpdateThread",          # rename/update thread
    "AimThreadsService/DeleteThreads":         "DeleteThreads",         # delete threads
    "AimThreadsService/DeleteSharedThreads":   "DeleteSharedThreads",   # un-share threads
    "AimThreadsService/InitiateShare":         "InitiateShare",         # create share link
    "AimThreadsService/CreateJourney":         "CreateJourney",         # create project/journey
    "AimThreadsService/UpdateJourneys":        "UpdateJourneys",        # update journey
    "AimThreadsService/DeleteJourneys":        "DeleteJourneys",        # delete journeys
}

# Key parameters observed in AIM requests (from HAR + heap, 2026-03-05)
AIM_PARAMS_REFERENCE: Dict[str, str] = {
    "udm":      "50 = AI Mode; required on all AIM requests",
    "aep":      "10 = AI Exploration Panel; required on all AIM requests",
    "fmt":      "jspb = JSON-PB response (response starts with )]}')",
    "msc":      "gwsclient = Google Web Services client identifier",
    "opi":      "89978449 = opaque ID; consistent across all requests",
    "stkp":     "session token per conversation turn (from initial search page)",
    "mstk":     "secondary session token (data-mstk from folif response HTML)",
    "elrc":     "encoded conversation context (base64 proto) for threading turns",
    "xsrf":     "XSRF token from __Secure-1PSIDTS cookie or SAPISIDHASH",
    "csui":     "3 = AI Mode context UI; sent on follow-up turns",
    "csuir":    "1 = context UI request flag",
    "cs":       "1 = content safety flag",
    "ei":       "experiment ID / thread ID extracted from initial page response",
    "canvasid": "load a specific canvas by ID in a new search (URL param)",
    "aim_sxs":  "side-by-side mode (AI response alongside classic search)",
    "aim_padt": "prompt/add-text flag (appears in URL param enum list)",
    "aim_folif":"follow in flow mode flag",
    "aim_folwr":"follow with rewrite mode flag",
    # imgv-specific
    "tbnid":    "thumbnail ID for imgv image viewer",
    "imgdii":   "same as tbnid — image display item identifier",
    "docid":    "document/image document ID for imgv",
    "yv":       "3 = image viewer version",
}

# Canvas DOM element attributes (from heap heap jsaction analysis)
AIM_CANVAS_DOM: Dict[str, str] = {
    "jscontroller":       "AwlxTd",     # canvas component controller class
    "data-suuid":         "<uuid>||",   # canvas session UUID (format: alphanum + ||)
    "data-component-xid": "Z9Ie4d",    # canvas component identifier
    "folwr-token":        "XSRF:ts",   # separate auth token for /async/folwr ops
}

# Canvas DOM events with obfuscated handler function names (from heap jsaction chain)
AIM_CANVAS_EVENTS: Dict[str, str] = {
    "aimMstkAvailable":             "OxNw6c",  # new mstk token ready → use for next turn
    "aimRenderComplete":            "iuwyKd",  # full render complete
    "aimBodyComplete":              "C6rCke",  # response body complete
    "aimModelResponseStarted":      "R5LEBf",  # model started generating
    "aimOpenShareManagementView":   "dfHbI",   # open share UI
    "aimOpenStatefulJourneyCreation": "eA5Ajf", # create journey UI
    "aimOpenStatefulJourneyHub":    "zAaRWc",  # open journey hub
    "aimNavigateToZeroState":       "CFLK0e",  # navigate to empty state
    # Canvas render pipeline (no handlers — dispatched for observability)
    "aimCanvasBeforeFirstContentPaint": "",
    "aimCanvasDiffsAvailable":      "",        # incremental diff patches ready
    "aimCanvasPatchStart":          "",
    "aimCanvasPatchFinished":       "",
    "aimCanvasRenderStarted":       "",
    "aimCanvasRenderFinished":      "",
    "aimCanvasTitleAvailable":      "",
    "aimCanvasContainerResize":     "",
    # Input plate events
    "aimInputPlateDrag":            "",
    "aimInputPlateLockInput":       "",
    "aimInputPlateRequestEdit":     "",
    "aimInputPlateRequestHide":     "",
    "aimInputPlateRequestRestore":  "",
    "aimInputPlateUnlockInput":     "",
    "aimInputPlateUpdateState":     "",
    "aimInterrupt":                 "",        # cancel in-flight generation
}

# ExportThread body format (JSPB array, POST body as JSON string):
# [null, [mstk_token], thread_ei_id, [export_type], null, 2]
# export_type 1 = default HTML canvas
AIM_EXPORT_BODY_FORMAT = "[null,[{mstk}],{thread_ei},[{export_type}],null,2]"

# imgv ID format observed: imgv__1:{n}:async:1:{tbnid}-{docid}-1-__h
AIM_IMGV_ID_FORMAT = "imgv__1:{counter}:async:1:{tbnid}-{docid}-1-__h"

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
