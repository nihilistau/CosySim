"""
OpenRoom Config Loader — Config-driven endpoint registry
=========================================================

Loads OpenRoom API configuration from config/argus_openroom.yaml
with Python fallback defaults. All endpoints, apps, models, and
paths are configurable without touching client code.

Version: v1.51.1 [2026-03-25]
Author:  CosySim Team

Change Log:
    v1.51.1 [2026-03-25] — Initial: extracted from openroom_client.py constants

CONNECTS: config/argus_openroom.yaml
CALLED BY: openroom_client.py
"""
from __future__ import annotations

import logging
from pathlib import Path
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

_ROOT = Path(__file__).resolve().parents[3]  # CosySim root
_CONFIG_PATH = _ROOT / "config" / "argus_openroom.yaml"

# ──── Fallback Defaults ──────────────────────────────────────────────────
# Used if YAML can't be loaded (missing file, no pyyaml, etc.)

_DEFAULTS: Dict[str, Any] = {
    "base_url": "https://www.openroom.ai",
    "cdn_url": "https://cdn.openroom.ai",
    "talkie_cdn": "https://cdn.talkie-ai.com",
    "ws_url": "wss://connection.openroom.ai/connection/ws",
    "apis": {
        "weaver": "/weaver/api/v1",
        "ugc": "/ugc/api",
        "storage": "/weaver_storage/api/v1/storage",
    },
    "endpoints": {
        "character": {
            "list_sessions": "/character/list_sessions",
            "start_session": "/character/start_session",
            "send_msg": "/character/send_msg",
            "get_chat_history": "/character/get_chat_history",
            "get_app_list": "/character/get_app_list",
            "report_os_event": "/character/report_os_event",
            "get_mod_list": "/character/get_mod_list",
            "query_credits": "/character/query_credits",
        },
        "chatroom": {
            "get_info": "/chatroom/get_chatroom_info",
            "room_list": "/chatroom/room/list",
        },
        "account": {
            "get_user_status": "/account/get_user_status",
        },
        "conversation": {
            "poll_message": "/connection/poll_message",
            "query_sorted": "/conversation/page_query_sorted_conversation",
            "query_all_messages": "/conversation/page_query_all_message",
            "restart": "/conversation/restart_conversation",
            "accept_msg": "/conversation/accept_msg",
            "delete": "/conversation/delete_conversation",
        },
        "storage": {
            "list_files": "/list_files",
            "get_file": "/get_file",
            "put_text_files": "/put_text_files_by_json",
        },
        "ugc": {
            "mod_gen": "/mod/gen",
            "create_mod": "/create",
            "get_default_template": "/get_default_system_prompt_template",
            "ai_generate": "/generate_character",
        },
        "events": {
            "report": "/event/report",
        },
    },
    "apps": {
        1: {"name": "OS", "description": "Desktop OS", "schema": "os"},
        2: {"name": "Twitter", "description": "Social media", "schema": "twitter"},
        3: {"name": "Music Player", "description": "Songs + playlists", "schema": "musicPlayer"},
        4: {"name": "Diary", "description": "Personal diary", "schema": "diary"},
        8: {"name": "Album", "description": "Photo album", "schema": "album"},
        11: {"name": "Email", "description": "Email client", "schema": "email"},
        13: {"name": "Evidence Vault", "description": "Evidence display", "schema": "evidencevault"},
        100: {"name": "ChatRoom", "description": "Live streaming", "schema": "chatroom"},
    },
    "models": ["Modern", "MiniMax-M2.5"],
    "characters": {6: {"name": "Aoi", "description": "Silver-haired bounty hunter"}},
    "playlists": ["ambient", "horror", "lyrical", "playful", "suspense", "tension", "urban chill"],
    "known_paths": [
        "apps/musicPlayer/data/songs/",
        "apps/musicPlayer/data/playlists/",
        "apps/email/data/emails/",
        "apps/diary/data/",
        "apps/twitter/data/tweets/",
    ],
    "har_directory": "C:/Files/Models/HARS/openroom",
    "default_room_id": 5050,
    "default_character_id": 6,
}


# ──── Config Singleton ───────────────────────────────────────────────────

_config: Optional[Dict[str, Any]] = None


def _load_yaml() -> Dict[str, Any]:
    """Load config from YAML file."""
    try:
        import yaml
        if _CONFIG_PATH.exists():
            with open(_CONFIG_PATH, "r", encoding="utf-8") as f:
                data = yaml.safe_load(f)
            return data.get("openroom", data) if isinstance(data, dict) else {}
    except ImportError:
        logger.debug("[OpenRoomConfig] PyYAML not available, using defaults")
    except Exception as exc:
        logger.debug("[OpenRoomConfig] Failed to load YAML: %s", exc)
    return {}


def _deep_merge(base: Dict, override: Dict) -> Dict:
    """Recursively merge override into base."""
    result = dict(base)
    for key, val in override.items():
        if key in result and isinstance(result[key], dict) and isinstance(val, dict):
            result[key] = _deep_merge(result[key], val)
        else:
            result[key] = val
    return result


def get_config() -> Dict[str, Any]:
    """Get the OpenRoom configuration (singleton, lazy-loaded)."""
    global _config
    if _config is None:
        yaml_config = _load_yaml()
        _config = _deep_merge(_DEFAULTS, yaml_config)
    return _config


def reload_config() -> Dict[str, Any]:
    """Force-reload configuration from YAML."""
    global _config
    _config = None
    return get_config()


# ──── Convenience Accessors ──────────────────────────────────────────────

def get_base_url() -> str:
    return get_config()["base_url"]


def get_cdn_url() -> str:
    return get_config()["cdn_url"]


def get_ws_url() -> str:
    return get_config()["ws_url"]


def get_weaver_url() -> str:
    """Full weaver API base URL."""
    cfg = get_config()
    return cfg["base_url"] + cfg["apis"]["weaver"]


def get_storage_url() -> str:
    """Full storage API base URL."""
    cfg = get_config()
    return cfg["base_url"] + cfg["apis"]["storage"]


def get_ugc_url() -> str:
    """Full UGC API base URL."""
    cfg = get_config()
    return cfg["base_url"] + cfg["apis"]["ugc"]


def get_endpoint(domain: str, name: str) -> str:
    """Get a full endpoint URL by domain and name.

    Args:
        domain: Endpoint group (character, chatroom, storage, ugc, etc.)
        name: Endpoint name within the group.

    Returns:
        Full URL string.

    Example:
        get_endpoint("character", "send_msg")
        → "https://www.openroom.ai/weaver/api/v1/character/send_msg"
    """
    cfg = get_config()
    endpoints = cfg.get("endpoints", {})
    group = endpoints.get(domain, {})
    path = group.get(name, "")

    if domain == "storage":
        return get_storage_url() + path
    elif domain == "ugc":
        return get_ugc_url() + path
    else:
        return get_weaver_url() + path


def get_apps() -> Dict[int, Dict[str, str]]:
    """Get the app registry {app_id: {name, description, schema}}."""
    return get_config().get("apps", {})


def get_models() -> List[str]:
    """Get known LLM model names."""
    return get_config().get("models", [])


def get_characters() -> Dict[int, Dict[str, str]]:
    """Get known characters {id: {name, description}}."""
    return get_config().get("characters", {})


def get_known_paths() -> List[str]:
    """Get known filesystem paths for storage browsing."""
    return get_config().get("known_paths", [])


def get_playlists() -> List[str]:
    """Get known music playlist names."""
    return get_config().get("playlists", [])


def get_har_directory() -> str:
    """Get the HAR file directory path."""
    return get_config().get("har_directory", "")


def get_default_room_id() -> int:
    """Get the default chatroom ID."""
    return get_config().get("default_room_id", 5050)


def get_default_character_id() -> int:
    """Get the default character ID."""
    return get_config().get("default_character_id", 6)


def list_all_endpoints() -> Dict[str, Dict[str, str]]:
    """Get all endpoints as {domain: {name: full_url}}."""
    cfg = get_config()
    result = {}
    for domain, endpoints in cfg.get("endpoints", {}).items():
        result[domain] = {}
        for name in endpoints:
            result[domain][name] = get_endpoint(domain, name)
    return result
