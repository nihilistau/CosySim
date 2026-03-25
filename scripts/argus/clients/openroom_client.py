#!/usr/bin/env python3
"""
OpenRoom.ai Explorer — API Client built from ARGUS intelligence
=================================================================

Interactive CLI for exploring OpenRoom.ai's Weaver API, character system,
chatrooms, UGC creation, and storage filesystem.

Usage:
    python -m scripts.argus.clients.openroom_client              # Menu
    python -m scripts.argus.clients.openroom_client sessions     # List chat sessions
    python -m scripts.argus.clients.openroom_client characters   # List available characters
    python -m scripts.argus.clients.openroom_client chat <sid>   # Chat in a session
    python -m scripts.argus.clients.openroom_client rooms        # List chatrooms
    python -m scripts.argus.clients.openroom_client apps <sid>   # List available apps
    python -m scripts.argus.clients.openroom_client files <sid>  # Browse storage filesystem
    python -m scripts.argus.clients.openroom_client create       # Create a new AI character
    python -m scripts.argus.clients.openroom_client generate     # AI-generate a character
    python -m scripts.argus.clients.openroom_client models       # Test available LLM models
    python -m scripts.argus.clients.openroom_client full         # Run everything

Version: v1.50.0 [2026-03-25]
Author:  CosySim Team

CONNECTS: ARGUS HAR analyzer, OpenRoom Weaver API
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

import requests

_ROOT = Path(__file__).resolve().parent.parent.parent.parent
sys.path.insert(0, str(_ROOT))

# ──── Constants from ARGUS Discovery ─────────────────────────────────────────

OPENROOM_URL = "https://www.openroom.ai"
OPENROOM_CDN = "https://cdn.openroom.ai"
OPENROOM_WS = "wss://connection.openroom.ai/connection/ws"

WEAVER_API = f"{OPENROOM_URL}/weaver/api/v1"
UGC_API = f"{OPENROOM_URL}/ugc/api"
STORAGE_API = f"{OPENROOM_URL}/weaver_storage/api/v1/storage"

# Known LLM models from HAR
KNOWN_MODELS = ["Modern", "MiniMax-M2.5"]

# Known character IDs
KNOWN_CHARACTERS = {
    6: "Aoi — Silver-haired bounty hunter, cryo survivor, dangerous smile",
}


# ──── Auth ───────────────────────────────────────────────────────────────────

class OpenRoomAuth:
    """Cookie-based auth extracted from HAR files."""

    def __init__(self) -> None:
        self.auth_token: str = ""
        self.refresh_token: str = ""
        self.user_id: str = ""
        self.device_id: str = ""
        self.cookies: Dict[str, str] = {}

    def load_from_har(self, har_path: Path) -> bool:
        """Extract auth cookies from HAR."""
        try:
            har = json.loads(har_path.read_text(errors="replace"))
            for entry in har.get("log", {}).get("entries", []):
                if "openroom.ai" not in entry.get("request", {}).get("url", ""):
                    continue
                for h in entry.get("request", {}).get("headers", []):
                    if h.get("name", "").lower() == "cookie":
                        for c in h["value"].split(";"):
                            if "=" in c:
                                k, v = c.strip().split("=", 1)
                                self.cookies[k] = v
                        self.auth_token = self.cookies.get("auth_token", "")
                        self.refresh_token = self.cookies.get("refresh_token", "")
                        self.user_id = self.cookies.get("user_id", "")
                        self.device_id = self.cookies.get("device_id", "")
                        if self.auth_token:
                            return True
        except Exception as exc:
            print(f"  [!] Failed to load auth from HAR: {exc}")
        return False

    @property
    def cookie_header(self) -> str:
        return "; ".join(f"{k}={v}" for k, v in self.cookies.items())

    def headers(self) -> Dict[str, str]:
        return {
            "Cookie": self.cookie_header,
            "Content-Type": "application/json",
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/146.0.0.0",
            "Origin": OPENROOM_URL,
            "Referer": f"{OPENROOM_URL}/",
        }

    def storage_url(self, path: str) -> str:
        return f"{STORAGE_API}/{path}?user_id={self.user_id}&device_id={self.device_id}"

    def status(self) -> str:
        if not self.auth_token:
            return "No auth loaded"
        return f"user_id={self.user_id} | token={self.auth_token[:15]}..."


# ──── API Calls ──────────────────────────────────────────────────────────────

def _post(url: str, data: Any, auth: OpenRoomAuth, timeout: int = 15) -> Dict:
    try:
        r = requests.post(url, json=data, headers=auth.headers(), timeout=timeout)
        try:
            return {"status": r.status_code, "data": r.json()}
        except Exception:
            return {"status": r.status_code, "data": r.text[:500]}
    except Exception as exc:
        return {"status": 0, "error": str(exc)}


# ──── Exploration Commands ───────────────────────────────────────────────────

def list_sessions(auth: OpenRoomAuth) -> None:
    """List all chat sessions."""
    print("\n=== CHAT SESSIONS ===\n")
    result = _post(f"{WEAVER_API}/character/list_sessions", {"size": 50}, auth)
    if result.get("status") != 200:
        print(f"  [!] Failed: {result}")
        return

    data = result.get("data", {})
    sessions = data.get("sessions", [])
    print(f"  Found {len(sessions)} sessions")
    print()
    for s in sessions:
        sid = s.get("session_id", "?")
        char = s.get("character", {})
        char_name = char.get("name", "?")
        char_desc = char.get("desc", "")[:60]
        mod = s.get("mod", {})
        mod_name = mod.get("name", "?")
        print(f"  [{sid}] {char_name} — {mod_name}")
        if char_desc:
            print(f"      {char_desc}...")
        print()


def list_characters(auth: OpenRoomAuth) -> None:
    """List available character mods."""
    print("\n=== CHARACTER MODS ===\n")
    result = _post(f"{WEAVER_API}/character/get_mod_list", {}, auth)
    if result.get("status") != 200:
        print(f"  [!] Failed: {result}")
        return

    data = result.get("data", {})
    mods = data.get("mods", data.get("mod_list", []))
    if isinstance(data, dict):
        for key, val in data.items():
            if isinstance(val, list) and val:
                mods = val
                break

    print(f"  Response keys: {list(data.keys()) if isinstance(data, dict) else type(data)}")
    print(f"  {json.dumps(data, indent=2)[:600]}")


def send_message(auth: OpenRoomAuth, session_id: int, text: str, model: str = "Modern") -> None:
    """Send a message in a chat session."""
    result = _post(f"{WEAVER_API}/character/send_msg", {
        "text": text,
        "session_id": session_id,
        "model": model,
    }, auth, timeout=30)

    if result.get("status") == 200:
        data = result.get("data", {})
        msg_id = data.get("msg_id", "?")
        print(f"  [sent] msg_id={msg_id}")
    else:
        print(f"  [!] Send failed: {result}")


def get_chat_history(auth: OpenRoomAuth, session_id: int, size: int = 20) -> None:
    """Get chat history for a session."""
    print(f"\n=== CHAT HISTORY (session {session_id}) ===\n")
    result = _post(f"{WEAVER_API}/character/get_chat_history", {
        "session_id": session_id,
        "cursor": 0,
        "size": size,
        "is_asc": True,
        "start_time": 0,
        "end_time": 0,
    }, auth)

    if result.get("status") != 200:
        print(f"  [!] Failed: {result}")
        return

    data = result.get("data", {})
    prologue = data.get("prologue", "")
    if prologue:
        print(f"  [PROLOGUE] {prologue[:200]}")
        print()

    replies = data.get("opening_rec_replies", [])
    if replies:
        print(f"  Suggested replies:")
        for r in replies:
            print(f"    > {r.get('reply_text', '?')}")
        print()

    messages = data.get("messages", [])
    for msg in messages:
        role = "YOU" if msg.get("role") == "user" else "AI"
        text = msg.get("text", msg.get("content", ""))[:200]
        print(f"  [{role}] {text}")


def list_rooms(auth: OpenRoomAuth) -> None:
    """List available chatrooms."""
    print("\n=== CHATROOMS ===\n")
    result = _post(f"{WEAVER_API}/chatroom/room/list", {"limit": 20}, auth)
    if result.get("status") != 200:
        print(f"  [!] Failed: {result}")
        return

    rooms = result.get("data", {}).get("rooms", [])
    print(f"  Found {len(rooms)} rooms")
    for room in rooms:
        rid = room.get("room_id", "?")
        name = room.get("room_name", "?")
        desc = room.get("description", "")[:80]
        online = room.get("online_count", 0)
        print(f"  [{rid}] {name} (online: {online})")
        if desc:
            print(f"      {desc}")
        print()


def list_apps(auth: OpenRoomAuth, session_id: int) -> None:
    """List available apps for a session."""
    print(f"\n=== APPS (session {session_id}) ===\n")
    result = _post(f"{WEAVER_API}/character/get_app_list", {
        "mod_id": 62,
        "session_id": session_id,
    }, auth)

    if result.get("status") != 200:
        print(f"  [!] Failed: {result}")
        return

    apps = result.get("data", {}).get("app_metas", [])
    print(f"  Found {len(apps)} apps")
    for app in apps:
        aid = app.get("app_id", "?")
        name = app.get("app_name", "?")
        desc = app.get("description", "")[:60]
        schema = app.get("schema", "")
        print(f"  [{aid}] {name:20s} {desc}")
        if schema:
            print(f"       schema: {schema}")


def browse_files(auth: OpenRoomAuth, session_id: int, path: str = "") -> None:
    """Browse the session filesystem."""
    print(f"\n=== FILES (session {session_id}, path='{path}') ===\n")
    result = _post(auth.storage_url("list_files"), {
        "path": path or ".",
        "session_id": session_id,
    }, auth)

    if result.get("status") != 200:
        print(f"  [!] Failed: {result}")
        return

    data = result.get("data", {})
    files = data.get("files", [])
    exists = not data.get("not_exists", False)

    if not exists:
        print(f"  Path does not exist")
        return

    print(f"  {len(files)} items")
    for f in files:
        ftype = "DIR " if f.get("type") == 1 else "FILE"
        size = f.get("size", "")
        fpath = f.get("path", "?")
        print(f"  [{ftype}] {fpath:60s} {size}")


def create_character(auth: OpenRoomAuth) -> None:
    """Create a new AI character (interactive)."""
    print("\n=== CREATE CHARACTER ===\n")
    name = input("  Character name: ").strip()
    desc = input("  Description/system prompt: ").strip()
    identifier = name.lower().replace(" ", "_")

    if not name or not desc:
        print("  [!] Name and description required")
        return

    result = _post(f"{UGC_API}/mod/create", {
        "mod": {
            "name": name,
            "identifier": identifier,
            "description": desc,
        },
        "author_id": auth.user_id,
        "published": False,
    }, auth)

    print(f"  Status: {result.get('status')}")
    print(f"  Response: {json.dumps(result.get('data', {}), indent=2)[:300]}")


def generate_character(auth: OpenRoomAuth) -> None:
    """Use AI to generate a character from a description."""
    print("\n=== AI CHARACTER GENERATOR ===\n")
    desc = input("  Describe your character: ").strip()
    if not desc:
        print("  [!] Description required")
        return

    # First get default system prompt
    result = _post(f"{UGC_API}/mod/default-system-prompt", {}, auth)
    default_prompt = ""
    if result.get("status") == 200:
        default_prompt = result.get("data", {}).get("system_prompt", "")

    print(f"  Generating character...")
    result = _post(f"{UGC_API}/mod/generate", {
        "description": desc,
        "system_prompt": default_prompt,
    }, auth, timeout=30)

    print(f"  Status: {result.get('status')}")
    data = result.get("data", {})
    print(f"  Response: {json.dumps(data, indent=2)[:800]}")


def test_models(auth: OpenRoomAuth) -> None:
    """Test sending messages with different models."""
    print("\n=== LLM MODEL TESTING ===\n")

    # Get a session to test with
    result = _post(f"{WEAVER_API}/character/list_sessions", {"size": 1}, auth)
    sessions = result.get("data", {}).get("sessions", [])
    if not sessions:
        print("  [!] No sessions available")
        return

    sid = sessions[0].get("session_id")
    print(f"  Testing on session {sid}")
    print()

    for model in KNOWN_MODELS + ["GPT-4", "Claude", "Gemini", "Llama", "DeepSeek"]:
        result = _post(f"{WEAVER_API}/character/send_msg", {
            "text": "Hello, what model are you?",
            "session_id": sid,
            "model": model,
        }, auth, timeout=15)
        status = result.get("status")
        if status == 200:
            msg_id = result.get("data", {}).get("msg_id", "?")
            print(f"  [OK]  {model:20s} -> msg_id={msg_id}")
        else:
            err = str(result.get("data", ""))[:60]
            print(f"  [ERR] {model:20s} -> {status} {err}")


def start_session(auth: OpenRoomAuth, mod_id: int = 62, char_id: int = 6) -> None:
    """Start a new chat session with a character."""
    print(f"\n=== START SESSION (mod={mod_id}, char={char_id}) ===\n")
    result = _post(f"{WEAVER_API}/character/start_session", {
        "mod_id": mod_id,
        "character_id": char_id,
    }, auth)

    if result.get("status") == 200:
        data = result.get("data", {})
        sid = data.get("session_id")
        is_new = data.get("is_new")
        print(f"  Session ID: {sid}")
        print(f"  Is new: {is_new}")
    else:
        print(f"  [!] Failed: {result}")


def show_endpoints() -> None:
    """Show all discovered API endpoints."""
    print("\n=== OPENROOM.AI API MAP ===\n")

    endpoints = {
        "Weaver — Character Chat": [
            ("POST", "/weaver/api/v1/character/list_sessions", "List all sessions", "{size}"),
            ("POST", "/weaver/api/v1/character/start_session", "Start session", "{mod_id, character_id}"),
            ("POST", "/weaver/api/v1/character/send_msg", "Send message", "{text, session_id, model}"),
            ("POST", "/weaver/api/v1/character/get_chat_history", "Get history", "{session_id, cursor, size}"),
            ("POST", "/weaver/api/v1/character/get_app_list", "List apps", "{mod_id, session_id}"),
            ("POST", "/weaver/api/v1/character/get_mod_list", "List character mods", "{}"),
            ("POST", "/weaver/api/v1/character/report_os_event", "Report app event", "{session_id, model, os_events}"),
        ],
        "Weaver — Chatrooms": [
            ("POST", "/weaver/api/v1/chatroom/room/list", "List rooms", "{limit}"),
            ("POST", "/weaver/api/v1/chatroom/message/list", "Room messages", "{room_id, type, limit}"),
            ("POST", "/weaver/api/v1/chatroom/comment/list", "Room comments", "{room_id, sort, limit}"),
            ("POST", "/weaver/api/v1/chatroom/get_chatroom_info", "Room info", "{room_id}"),
        ],
        "UGC — Character Creation": [
            ("POST", "/ugc/api/mod/create", "Create character", "{mod, author_id}"),
            ("POST", "/ugc/api/mod/generate", "AI-generate character", "{description, system_prompt}"),
            ("POST", "/ugc/api/mod/default-system-prompt", "Get default prompt", "{}"),
        ],
        "Weaver Storage — Filesystem": [
            ("POST", "/weaver_storage/api/v1/storage/list_files", "List files", "{path, session_id}"),
            ("POST", "/weaver_storage/api/v1/storage/get_file", "Get file", "{session_id, file_path}"),
            ("POST", "/weaver_storage/api/v1/storage/put_text_files_by_json", "Write files", "{files, session_id}"),
            ("POST", "/weaver_storage/api/v1/storage/delete_files_by_paths", "Delete files", "{file_paths, session_id}"),
        ],
        "Account & Events": [
            ("POST", "/weaver/api/v1/account/get_user_status", "User status", "{}"),
            ("POST", "/weaver/api/v1/event/report", "Report events", "{events}"),
        ],
        "WebSocket": [
            ("WSS", "connection.openroom.ai/connection/ws?os=3&token=<JWT>", "Real-time connection", "HS256 JWT"),
        ],
    }

    for group, eps in endpoints.items():
        print(f"  {group}:")
        for method, path, desc, body in eps:
            print(f"    {method:5s} {path[:65]:65s} {desc}")
        print()


# ──── Main ───────────────────────────────────────────────────────────────────

def main() -> None:
    parser = argparse.ArgumentParser(description="OpenRoom.ai Explorer")
    parser.add_argument("command", nargs="?", default="menu",
                        choices=["menu", "sessions", "characters", "chat", "rooms",
                                 "apps", "files", "create", "generate", "models",
                                 "start", "endpoints", "full"])
    parser.add_argument("session_id", nargs="?", type=int, help="Session ID for chat/apps/files")
    parser.add_argument("--har", type=Path, help="HAR file for auth tokens")
    parser.add_argument("--model", default="Modern", help="LLM model name")
    parser.add_argument("--path", default="", help="File path for browse")
    args = parser.parse_args()

    # Auto-find HAR
    har_path = args.har
    if not har_path:
        candidates = sorted(Path("C:/Files/Models/HARS/openroom").glob("*.har"), reverse=True)
        # Skip broken files
        for c in candidates:
            if c.stat().st_size > 1000:
                har_path = c
                break

    auth = OpenRoomAuth()
    if har_path and har_path.exists():
        auth.load_from_har(har_path)

    print()
    print("=" * 60)
    print("  OPENROOM.AI EXPLORER")
    print("  Built from ARGUS HAR Intelligence")
    print("=" * 60)
    print(f"  Auth: {auth.status()}")
    print(f"  HAR:  {har_path}")
    print()

    if args.command == "menu":
        print("  Commands:")
        print("    sessions     List all chat sessions")
        print("    characters   List character mods")
        print("    chat <sid>   Get chat history for a session")
        print("    rooms        List chatrooms")
        print("    apps <sid>   List apps for a session")
        print("    files <sid>  Browse session filesystem")
        print("    create       Create a new AI character (interactive)")
        print("    generate     AI-generate a character")
        print("    models       Test available LLM models")
        print("    start        Start a new session")
        print("    endpoints    Show all API endpoints")
        print("    full         Run everything")
        return

    if args.command == "sessions":
        list_sessions(auth)
    elif args.command == "characters":
        list_characters(auth)
    elif args.command == "chat":
        if args.session_id:
            get_chat_history(auth, args.session_id)
        else:
            print("  Usage: openroom_client chat <session_id>")
    elif args.command == "rooms":
        list_rooms(auth)
    elif args.command == "apps":
        if args.session_id:
            list_apps(auth, args.session_id)
        else:
            print("  Usage: openroom_client apps <session_id>")
    elif args.command == "files":
        if args.session_id:
            browse_files(auth, args.session_id, args.path)
        else:
            print("  Usage: openroom_client files <session_id>")
    elif args.command == "create":
        create_character(auth)
    elif args.command == "generate":
        generate_character(auth)
    elif args.command == "models":
        test_models(auth)
    elif args.command == "start":
        start_session(auth)
    elif args.command == "endpoints":
        show_endpoints()
    elif args.command == "full":
        show_endpoints()
        list_sessions(auth)
        list_rooms(auth)
        list_characters(auth)


if __name__ == "__main__":
    main()
