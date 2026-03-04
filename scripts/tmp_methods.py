import json, datetime
from pathlib import Path

artifacts = {
    "generated": datetime.datetime.now().isoformat(),
    "version": "1.0",
    "source": "HAR analysis + V8 heap mining (gemini.google.com + aistudio.google.com, March 2026)",

    "services": {
        "gemini_bard": {
            "name": "BardChatUi (Gemini)",
            "base_url": "https://gemini.google.com",
            "batchexecute": "/_/BardChatUi/data/batchexecute",
            "build_label": "boq_assistant-bard-web-server_...",
            "streaming_grpc": "/_/BardChatUi/data/assistant.lamda.BardFrontendService/StreamGenerate",
            "auth": "cookie-based (same pattern as NLM)"
        },
        "aistudio_makersuite": {
            "name": "MakerSuiteService (AI Studio)",
            "base_url": "https://aistudio.google.com",
            "grpc_web_url": "https://alkalimakersuite-pa.clients6.google.com/$rpc/google.internal.alkali.applications.makersuite.v1.MakerSuiteService/{Method}",
            "streaming_url": "https://webchannel-alkalimakersuite-pa.clients6.google.com",
            "auth": "SAPISIDHASH + x-goog-api-key + cookies"
        }
    },

    "api_keys": {
        "aistudio_1": "REDACTED-GOOGLE-API-KEY",
        "aistudio_2": "REDACTED-GOOGLE-API-KEY",
        "aistudio_3": "REDACTED-GOOGLE-API-KEY",
        "gemini": "AIzaSyBWW50ghQ5qHpMg1gxHV7U9t0...",
        "note": "Rotate via GenerateCloudApiKey MakerSuiteService method"
    },

    "gemini_rpcids": {
        "otAQ7b": {
            "name": "GetModels",
            "desc": "Returns available Gemini models with IDs and capabilities",
            "payload": "[]",
            "response": "[[model_id, display_name, desc, [feature_ids], ...], ...]",
            "model_ids": {
                "56fdd199312815e2": "Fast (Gemini Flash)",
                "e051ce1aa80aa576": "Thinking (Gemini Thinking)",
            }
        },
        "K4WWud": {
            "name": "GetUserLocation",
            "payload": "[[1],[\"en-AU\"]]",
            "response": "[[city, SWML_key, bool, null, map_data_url]]"
        },
        "ozz5Z": {
            "name": "GetFeatureFlags",
            "payload": "[[[null,\"1\",447],[null,\"1\",448],... ]]",
            "response": "same_list_with_status_flags",
            "note": "Feature flag IDs: 447,448,702,961,960,1062"
        },
        "CNgdBe": {
            "name": "ListConversations",
            "payload": "[1,[\"en-AU\"],0]",
            "response": "[null,null,[[conv_id,[title,\"\",null,null,null,null,[\"\",null,null,theme],bool,bool,[],[],turn_count,null,bool], system_prompt]]]",
            "note": "Returns all user conversations with system prompts and theme colors"
        },
        "GPRiHf": {
            "name": "Initialize (ping)",
            "payload": "[]",
            "response": "[]"
        },
        "maGuAc": {
            "name": "Acknowledge/MarkRead",
            "payload": "[1]",
            "response": "[]"
        },
        "ESY5D": {
            "name": "GetUserSettings",
            "payload": "[[[\"bard_activity_enabled\"]]]",
            "response": "[[null,null,null,null,true]]",
            "note": "Key-value settings store"
        },
        "MaZiqc": {
            "name": "GenerateSessionToken",
            "payload": "[13,null,[0,null,1]]",
            "response": "[null,\"BASE64_TOKEN\"]",
            "note": "Returns a signed session token (long base64 string)"
        },
        "aPya6c": {
            "name": "GetConversationState",
            "payload": "[]",
            "response": "[false,0,[]]"
        },
        "cYRIkd": {
            "name": "ListExtensions",
            "payload": "[\"en-AU\"]",
            "response": "[[[[extension_id], display_name, icon_url, ...]]]",
            "known_extensions": ["google_calendar_2", "google_workspace", "youtube", "google_flights", "google_hotels", "google_maps"]
        },
        "qpEbW": {
            "name": "GetUsageQuota",
            "payload": "[[[1,4],[6,6],[1,15]]]",
            "response": "[[[[quota_type,...],1,used,[timestamp,ns],limit,remaining],...], session_id]"
        },
        "o30O0e": {
            "name": "GetUserProfile",
            "payload": "[[\"me\"],[[people_fields],null,[1,7]]]",
            "response": "[[\"me\",1,[google_user_id,...]]]",
            "note": "Uses Google People API - returns Google account ID"
        },
        "L5adhe": {
            "name": "InitConversation",
            "payload": "[null,null,null,...,null,null,null,null,null,null,null,null,4]",
            "response": "[1]"
        },
        "ku4Jyf": {
            "name": "GetStarterPrompts",
            "payload": "[\"en-AU\",null,null,null,4,null,null,[2,4,7,19],null,[]]",
            "response": "[[[title,null,full_prompt,lang,[category_ids],prompt_id,1,...]]]]"
        },
        "PCck7e": {
            "name": "DeleteConversation",
            "payload": "[\"r_CONVERSATION_ID\"]",
            "response": "[]"
        },
        "NXpLKc": {
            "name": "ListLinkedNotebooks",
            "payload": "[]",
            "response": "[[[\"notebooks/UUID\",title,[timestamp_s,timestamp_ns],source_count],...]]",
            "note": "Gemini↔NotebookLM integration - returns all NLM notebooks",
            "discovered_notebooks": {
                "3b5dbaa9-6126-47bc-8a64-013eae6cd129": {"title": "Colab Skool", "sources": 10},
                "0afe6dd5-cc1f-438d-93bc-269f7dbd5c14": {"title": "", "sources": 0},
                "603976db-40d0-4b3f-9827-a483c45a3108": {"title": "V8 Heap Forensics", "sources": 41},
                "1241f5d1-d91c-4bce-910c-6c559500e9a1": {"title": "CosySim Project Journal", "sources": 1},
                "24221492-0531-4305-bdef-33a5425f6302": {"title": "CosySim Nexus AI Research Intelligence Notebook", "sources": 1},
                "f0a6c72f-4fcb-40a1-8d32-b217a12166fe": {"title": "CosySim Nexus: Global Intelligence and Geopolitical Architecture", "sources": 1},
                "3622eae6-d105-42bb-870c-605d652b919d": {"title": "CosySim Nexus: Science and Emerging Technology Intelligence", "sources": 1},
                "9504cf8c-b111-4f53-92e0-0833ece14264": {"title": "Nexus Intelligence: Technology Signals for the CosySim Knowledge Base", "sources": 1},
                "50170774-124e-4147-a03e-dc67a02503d7": {"title": "Game Lore-Lovecraft-Egypt", "sources": 52},
                "26486368-f7ff-4f76-a4c7-28c7815d22bf": {"title": "NotebookLM Best Practices", "sources": 33},
                "311f2b2e-347d-49c5-84d7-a9236a699771": {"title": "The CosySim AI Simulation Framework Index", "sources": 7}
            }
        },
        "DYBcR": {"name": "Unknown_DYBcR", "payload": "[\"en-AU\"]", "response": "(empty)"},
    },

    "bard_frontend_service": {
        "base": "/_/BardChatUi/data/assistant.lamda.BardFrontendService",
        "methods": {
            "StreamGenerate": "Main streaming generation (POST)",
            "GetTtsStream": "TTS audio streaming",
            "ProcessFile": "File upload/processing"
        }
    },

    "makersuite_service_complete": {
        "proto_path": "google.internal.alkali.applications.makersuite.v1.MakerSuiteService",
        "grpc_web_base": "https://alkalimakersuite-pa.clients6.google.com/$rpc/",
        "total_methods": 136,
        "categories": {
            "core_ai": ["GenerateContent", "ProxyUnaryCall", "ProxyStreamedCall", "ProxyUnaryFileApiCall", "GenerateImage", "GenerateVideo", "GenerateFunctionCallAnswer", "CountTokens", "GeminiSpeechToText", "StreamExtractVideoFrames"],
            "models": ["ListModels", "GetModel", "GetModelQuota", "ListModelRateLimits", "ListQuotaModels"],
            "prompts": ["CreatePrompt", "GetPrompt", "UpdatePrompt", "DeletePrompt", "ListPrompts", "EnhancePrompt"],
            "applets": ["CreateApplet", "GetApplet", "SaveApplet", "DeleteApplet", "ListApplets", "LoadBundledApplet", "LoadDriveApplet", "LoadZipApplet", "SaveDriveApplet", "DeleteDriveApplet", "ListBundledApplets", "ListDriveApplets", "ListSharedApplets", "ListRecentApplets", "StoreRecentApplet", "ForgetRecentApplet", "GetAppletAccess", "UpdateAppletAccess", "GetAppletGalleryConfig", "GetAppletDeploymentInfo", "GetAppletDebugInfo", "GetAppletTrajectory", "SeverAppletRedirect"],
            "code_assistant": ["CodeAssistant", "CodeAssistantOffline", "StreamCodeAssistantOfflineGeneration", "CancelCodeAssistantOfflineGeneration", "LoadCodeAssistantInteractionHistory", "LoadCodeAssistantSnapshots", "GetCodeAssistantSnapshot", "ListCodeAssistantConfigurations", "ListCodeAssistantFeatures", "ListCodeAssistantOfflineGenerations", "ListCodeGenSuggestionCards", "GenerateCodeAssistantSuggestionChips", "GenerateGitHubCommitMessage", "GenerateTitle"],
            "deployment": ["ProvisionAndInitializeApplet", "CreateSharedAppletDeployment", "DeleteSharedAppletDeployment", "CheckSharedAppletDeployment", "ListSharedApplets", "CreateCloudRunService", "UpdateCloudRunService", "DeleteCloudRunService", "CheckCloudRunService", "GetAppletCloudRunServiceLogs", "DownloadBuildArtifacts"],
            "secrets": ["ListAppletSecrets", "ListUnsetAppletSecrets", "UpsertAppletSecret", "DeleteAppletSecret"],
            "github": ["GetGitHubAuthStatus", "CreateGitHubRepository", "ImportGitHubRepository", "ListGitHubRepositories", "PushNewCommit", "FetchChangelistContent", "FetchPiperFile", "ComputeStagedGitHubDiff", "QueryCodeSearch"],
            "datasets": ["CreateDataset", "GetDataset", "UpdateDataset", "DeleteDataset", "ListDatasets", "ExportDataset", "CreateInteraction"],
            "sessions": ["GetSession", "GetSessionTurn", "ListSessionTurns", "BulkDeleteSessionTurns", "CountSessionTurns", "RecordSessionTurnFeedback"],
            "cloud_infra": ["CreateCloudProject", "UpdateCloudProject", "ListCloudProjects", "RemoveProjects", "ImportProjects", "ListImportedProjects", "ListBillingAccounts", "GetPrepayEligibility", "UpgradeAndDisablePrepay", "HasFirestore", "CreateCloudApiKey", "UpdateCloudApiKey", "DeleteCloudApiKey", "GenerateCloudApiKey", "ListCloudApiKeys", "GetProjectUsageLimit", "UpdateProjectUsageLimit"],
            "auth": ["GenerateAccessToken", "AcceptTerms", "AcceptFirebaseTos", "CheckUserStatus", "GetUserPreferences", "UpdateUserPreferences", "GetUserRestrictions"],
            "observability": ["EnableTracesLogging", "DisableTracesLogging", "GetTracesLoggingStatus", "UpdateTracesStorageRetention", "FetchMetricTimeSeries", "Log", "StreamLogs", "ListIncidentsHistory"],
            "files": ["UploadScs", "ListFilesInScs", "ResolveDriveResource", "GetAppFolder"],
            "misc": ["GetLoggingContext", "GetImFeelingLuckyOptions", "GetSample", "GetEmbeddedPortalParameters", "ListPromos", "CheckImage", "GetGetcodeTemplates"]
        }
    },

    "model_registry": {
        "gemini-3.1-pro-preview": {"ctx": 1048576, "out": 65536},
        "gemini-3.1-flash-image-preview": {"ctx": 65536, "out": 65536},
        "gemini-3.1-flash-lite-preview": {"ctx": 1048576, "out": 65536},
        "gemini-3-pro-preview": {"ctx": 1048576, "out": 65536},
        "gemini-3-pro-image-preview": {"ctx": 131072, "out": 32768},
        "gemini-3-flash-preview": {"ctx": 1048576, "out": 65536, "confirmed_via": "ProxyUnaryCall response modelVersion"},
        "gemini-2.5-pro": {"ctx": 1048576, "out": 65536},
        "gemini-2.5-flash": {"ctx": 1048576, "out": 65536},
        "gemini-2.5-flash-preview-tts": {"ctx": 8192, "out": 16384},
        "gemini-2.5-pro-preview-tts": {"ctx": 8192, "out": 16384},
        "gemini-2.0-flash": {"ctx": 1048576, "out": 8192},
        "gemini-2.0-flash-lite": {"ctx": 1048576, "out": 8192},
        "gemini-robotics-er-1.5-preview": {"ctx": 1048576, "out": 65536},
        "gemini-2.5-flash-native-audio-preview": {"ctx": 131072, "out": 8192},
        "imagen-4.0-generate-001": {"ctx": 480, "out": 8192, "type": "image"},
        "imagen-4.0-ultra-generate-001": {"ctx": 480, "out": 8192, "type": "image"},
        "imagen-4.0-fast-generate-001": {"ctx": 480, "out": 8192, "type": "image"},
        "veo-3.1-generate-preview": {"ctx": 480, "out": 8192, "type": "video"},
        "veo-3.1-fast-generate-preview": {"ctx": 480, "out": 8192, "type": "video"},
        "veo-2.0-generate-001": {"ctx": 480, "out": 8192, "type": "video"},
        "nano-banana": {"ctx": "?", "out": "?", "note": "Internal codename"},
        "nano-banana-pro": {"ctx": "?", "out": "?", "note": "Internal codename"},
    },

    "thought_signature": {
        "format": "base64-encoded protobuf (opaque)",
        "example": "EqICCp8CAb4+9vv/WYWneW3VMnfUy2UaD+hxiaOdzW5zriD4F8t9ZX6C8B+dGI367plLg75wtVfETXRR...",
        "field_in_response": "candidates[0].content.parts[0].thoughtSignature",
        "token_overhead": "64 thinking tokens for 9 output tokens (gemini-3-flash-preview)",
        "usageMetadata_field": "thoughtsTokenCount"
    },

    "user_app": {
        "name": "Nexus Assistant",
        "uuid": "3d201588-286c-4a03-beb7-6edeaeaf6abf",
        "deployed_url": "https://ais-dev-4pnf35mkt3lidvc5grflhc-375946902936.asia-southeast1.run.app",
        "description": "A customizable voice and text assistant with workflow automation and reader mode."
    },

    "new_nlm_rpcid": {
        "ub2Bae": {"name": "Unknown_ub2Bae", "source": "NLM console log", "note": "Not yet decoded - appears during notebook session"}
    },

    "sapisidhash_pattern": {
        "format": "SAPISIDHASH {timestamp}_{sha1_hex} SAPISID1PHASH {timestamp}_{sha1_hex}",
        "algorithm": "SHA1(timestamp + ' ' + SAPISID + ' ' + origin)",
        "example": "SAPISIDHASH 1772648856_f0992f361993d2add04b056c74eb6b8988c38e77"
    }
}

out_path = Path("data/aistudio_artifacts.json")
out_path.write_text(json.dumps(artifacts, indent=2))
print(f"Written {out_path.stat().st_size//1024} KB to {out_path}")
print(f"MakerSuiteService methods: {artifacts['makersuite_service_complete']['total_methods']}")
print(f"Gemini rpcids: {len(artifacts['gemini_rpcids'])}")
print(f"Models in registry: {len(artifacts['model_registry'])}")
