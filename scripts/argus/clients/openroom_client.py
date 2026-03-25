#!/usr/bin/env python3
"""
OpenRoom.ai Explorer — Comprehensive Interactive Exploration Tool
==================================================================

Interactive CLI and REPL for exploring OpenRoom.ai's Weaver API, character
system, chatrooms, UGC creation, storage filesystem, credits/wallet, hidden
conversation APIs, live danmaku viewer, and full API spec export.

Usage (argparse):
    python -m scripts.argus.clients.openroom_client              # Menu
    python -m scripts.argus.clients.openroom_client sessions     # List chat sessions
    python -m scripts.argus.clients.openroom_client characters   # List available characters
    python -m scripts.argus.clients.openroom_client chat <sid>   # Chat in a session
    python -m scripts.argus.clients.openroom_client rooms        # List chatrooms
    python -m scripts.argus.clients.openroom_client messages <rid> # Get room messages
    python -m scripts.argus.clients.openroom_client danmaku <rid>  # Watch live danmaku
    python -m scripts.argus.clients.openroom_client credits      # Check credits/wallet
    python -m scripts.argus.clients.openroom_client conversations  # Hidden conversation API
    python -m scripts.argus.clients.openroom_client view <rid>   # Full room viewer
    python -m scripts.argus.clients.openroom_client apps <sid>   # List available apps
    python -m scripts.argus.clients.openroom_client files <sid>  # Browse storage filesystem
    python -m scripts.argus.clients.openroom_client create       # Create a new AI character
    python -m scripts.argus.clients.openroom_client generate     # AI-generate a character
    python -m scripts.argus.clients.openroom_client template     # Create character from template
    python -m scripts.argus.clients.openroom_client models       # Test available LLM models
    python -m scripts.argus.clients.openroom_client export       # Export API spec as JSON
    python -m scripts.argus.clients.openroom_client repl         # Interactive REPL
    python -m scripts.argus.clients.openroom_client full         # Run everything

Version: v1.50.1 [2026-03-25]
Author:  CosySim Team

Change Log:
    v1.50.1 [2026-03-25] — Comprehensive expansion: danmaku viewer, credits/wallet,
                            hidden conversation API, character-from-template, room viewer,
                            interactive REPL, API spec export, livestream feature constants
    v1.50.0 [2026-03-25] — Initial explorer: sessions, characters, chat, rooms, apps,
                            files, create, generate, models, endpoints

CONNECTS: ARGUS HAR analyzer, OpenRoom Weaver API, heap analysis discoveries
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

import datetime
import traceback

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

# v1.50.1 [2026-03-25] — Hidden API endpoints discovered via heap analysis
HIDDEN_APIS = {
    "poll_message": "/weaver/api/v1/connection/poll_message",
    "query_conversations": "/weaver/api/v1/conversation/page_query_sorted_conversation",
    "query_messages": "/weaver/api/v1/conversation/page_query_all_message",
    "restart_conversation": "/weaver/api/v1/conversation/restart_conversation",
    "accept_msg": "/weaver/api/v1/conversation/accept_msg",
    "delete_conversation": "/weaver/api/v1/conversation/delete_conversation",
}

# v1.50.1 [2026-03-25] — Credits/wallet endpoints discovered via heap analysis
CREDITS_APIS = {
    "balance": "credits/fetchBalance",
    "products": "credits/fetchProductList",
    "history": "credits/fetchHistory",
    "create_order": "credits/createPreOrder",
    "order_status": "credits/fetchOrderStatus",
}

# v1.50.1 [2026-03-25] — Livestream features discovered via heap analysis
LIVESTREAM_FEATURES = [
    "os_livestream_add_agent",
    "os_livestream_gift_send",
    "os_livestream_stage_index",
    "os_livestream_next_stage",
    "os_livestream_play_voice",
    "os_livestream_task_completed",
    "send_agent_message",
    "receive_agent_message",
]

# v1.50.1 [2026-03-25] — Live room stats snapshot (room 5050)
ROOM_5050_STATS = {
    "viewers": 9970,
    "likes": 3600608,
    "comments": 284110,
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


# ──── Danmaku / Live Comments ─────────────────────────────────────────────
# v1.50.1 [2026-03-25] — Live danmaku viewer polling room bullet comments

def get_room_messages(auth: OpenRoomAuth, room_id: int = 5050,
                      msg_type: int = 0, limit: int = 30) -> List[Dict]:
    """Fetch recent messages/comments from a chatroom.

    Args:
        auth: Authenticated session.
        room_id: Chatroom ID to query.
        msg_type: Message type filter (0=all).
        limit: Max messages to return.

    Returns:
        List of message dicts from the API.

    CONNECTS: list_rooms, watch_danmaku, view_room
    """
    result = _post(f"{WEAVER_API}/chatroom/message/list", {
        "room_id": room_id,
        "type": msg_type,
        "limit": limit,
    }, auth)
    if result.get("status") != 200:
        return []
    return result.get("data", {}).get("messages", [])


def get_room_comments(auth: OpenRoomAuth, room_id: int = 5050,
                      sort: str = "newest", limit: int = 30) -> List[Dict]:
    """Fetch comments (danmaku) from a chatroom.

    Args:
        auth: Authenticated session.
        room_id: Chatroom ID.
        sort: Sort order — "newest" or "popular".
        limit: Max comments to return.

    Returns:
        List of comment dicts.

    CONNECTS: watch_danmaku, view_room
    """
    result = _post(f"{WEAVER_API}/chatroom/comment/list", {
        "room_id": room_id,
        "sort": sort,
        "limit": limit,
    }, auth)
    if result.get("status") != 200:
        return []
    return result.get("data", {}).get("comments", [])


def watch_danmaku(auth: OpenRoomAuth, room_id: int = 5050, interval: int = 5) -> None:
    """Poll danmaku every N seconds and display new ones.

    Continuously polls the chatroom comment/message endpoints and prints
    any new bullet comments as they appear. Press Ctrl+C to stop.

    Args:
        auth: Authenticated session.
        room_id: Chatroom ID to watch (default 5050).
        interval: Seconds between polls (default 5).

    CONNECTS: get_room_messages, get_room_comments
    CALLED BY: main dispatch, REPL danmaku command
    """
    print(f"\n=== LIVE DANMAKU — Room {room_id} (poll every {interval}s) ===")
    print("  Press Ctrl+C to stop\n")

    # Track seen message IDs to only show new ones
    seen_ids: set = set()
    poll_count = 0

    try:
        while True:
            poll_count += 1
            timestamp = datetime.datetime.now().strftime("%H:%M:%S")

            # Fetch both messages and comments
            messages = get_room_messages(auth, room_id, limit=50)
            comments = get_room_comments(auth, room_id, limit=50)

            # Merge into a single feed, dedup by ID
            new_count = 0
            for msg in messages:
                mid = msg.get("message_id") or msg.get("id") or id(msg)
                if mid not in seen_ids:
                    seen_ids.add(mid)
                    user = msg.get("user_name") or msg.get("nickname") or "anon"
                    text = msg.get("content") or msg.get("text") or ""
                    mtype = msg.get("type", "")
                    if text:
                        print(f"  [{timestamp}] [{mtype}] {user}: {text[:120]}")
                        new_count += 1

            for cmt in comments:
                cid = cmt.get("comment_id") or cmt.get("id") or id(cmt)
                if cid not in seen_ids:
                    seen_ids.add(cid)
                    user = cmt.get("user_name") or cmt.get("nickname") or "anon"
                    text = cmt.get("content") or cmt.get("text") or ""
                    likes = cmt.get("like_count", 0)
                    if text:
                        print(f"  [{timestamp}] [CMT] {user} ({likes} likes): {text[:120]}")
                        new_count += 1

            if new_count == 0 and poll_count % 6 == 0:
                # Every 30s (6 polls at 5s), show heartbeat so user knows it's alive
                print(f"  [{timestamp}] ... watching (seen {len(seen_ids)} total)")

            time.sleep(interval)
    except KeyboardInterrupt:
        print(f"\n  Stopped. Saw {len(seen_ids)} unique items across {poll_count} polls.")


def show_room_messages(auth: OpenRoomAuth, room_id: int = 5050) -> None:
    """Display recent messages from a chatroom.

    Args:
        auth: Authenticated session.
        room_id: Chatroom to query.

    CALLED BY: main dispatch, REPL messages command
    """
    print(f"\n=== ROOM MESSAGES — Room {room_id} ===\n")
    messages = get_room_messages(auth, room_id, limit=30)
    if not messages:
        print("  No messages found (or API returned empty)")
        return

    print(f"  {len(messages)} messages:\n")
    for msg in messages:
        user = msg.get("user_name") or msg.get("nickname") or "anon"
        text = msg.get("content") or msg.get("text") or ""
        mtype = msg.get("type", "?")
        ts = msg.get("created_at") or msg.get("timestamp") or ""
        print(f"  [{mtype}] {user}: {text[:150]}")
        if ts:
            print(f"         @ {ts}")


# ──── Credits / Wallet System ────────────────────────────────────────────
# v1.50.1 [2026-03-25] — Credits endpoints discovered via heap analysis

def explore_credits(auth: OpenRoomAuth) -> None:
    """Probe credits/wallet endpoints discovered in heap.

    Tests balance, product list, and transaction history endpoints.

    CONNECTS: CREDITS_APIS constant
    CALLED BY: main dispatch, REPL credits command
    """
    print("\n=== CREDITS / WALLET ===\n")

    # The credits endpoints may be under a different API prefix — try multiple
    # base paths since the heap showed them as RPC-style names
    prefixes = [
        f"{OPENROOM_URL}/weaver/api/v1/",
        f"{OPENROOM_URL}/api/v1/",
        f"{OPENROOM_URL}/",
    ]

    for name, endpoint in CREDITS_APIS.items():
        print(f"  --- {name} ({endpoint}) ---")
        found = False
        for prefix in prefixes:
            url = f"{prefix}{endpoint}"
            result = _post(url, {}, auth)
            status = result.get("status", 0)
            if status == 200:
                data = result.get("data", {})
                print(f"    [OK]  {url}")
                # Pretty-print the response, truncated
                pretty = json.dumps(data, indent=2, ensure_ascii=False)
                for line in pretty.split("\n")[:15]:
                    print(f"    {line}")
                if len(pretty.split("\n")) > 15:
                    print(f"    ... ({len(pretty)} chars total)")
                found = True
                break
            elif status == 404:
                continue  # Try next prefix
            else:
                # Non-404 error is informative — show it
                print(f"    [{status}] {url} -> {str(result.get('data', ''))[:100]}")
                found = True
                break
        if not found:
            print(f"    [404] Not found under any known prefix")
        print()


# ──── Hidden Conversation API ─────────────────────────────────────────────
# v1.50.1 [2026-03-25] — Conversation endpoints from heap analysis

def explore_conversations(auth: OpenRoomAuth) -> None:
    """Test hidden conversation endpoints from heap analysis.

    Probes the conversation management API that isn't exposed in the
    public UI — includes sorted query, all messages, and restart.

    CONNECTS: HIDDEN_APIS constant
    CALLED BY: main dispatch, REPL conversations command
    """
    print("\n=== HIDDEN CONVERSATION API ===\n")

    # Query sorted conversations — paginated list
    print("  --- Sorted Conversations ---")
    result = _post(f"{OPENROOM_URL}{HIDDEN_APIS['query_conversations']}", {
        "page": 1,
        "page_size": 20,
        "sort_by": "updated_at",
    }, auth)
    status = result.get("status", 0)
    data = result.get("data", {})
    print(f"    Status: {status}")
    if status == 200:
        convos = data.get("conversations", data.get("list", []))
        if isinstance(convos, list):
            print(f"    Found {len(convos)} conversations")
            for c in convos[:10]:
                cid = c.get("conversation_id") or c.get("id") or "?"
                title = c.get("title") or c.get("name") or "untitled"
                updated = c.get("updated_at") or ""
                msg_count = c.get("message_count") or c.get("msg_count") or "?"
                print(f"    [{cid}] {title} (msgs: {msg_count}) {updated}")
        else:
            pretty = json.dumps(data, indent=2, ensure_ascii=False)
            for line in pretty.split("\n")[:12]:
                print(f"    {line}")
    else:
        print(f"    Response: {json.dumps(data, indent=2, ensure_ascii=False)[:300]}")
    print()

    # Query all messages from first conversation found
    print("  --- All Messages (first conversation) ---")
    result = _post(f"{OPENROOM_URL}{HIDDEN_APIS['query_messages']}", {
        "page": 1,
        "page_size": 10,
    }, auth)
    status = result.get("status", 0)
    data = result.get("data", {})
    print(f"    Status: {status}")
    if status == 200:
        msgs = data.get("messages", data.get("list", []))
        if isinstance(msgs, list):
            print(f"    Found {len(msgs)} messages")
            for m in msgs[:5]:
                role = m.get("role") or m.get("sender") or "?"
                text = (m.get("text") or m.get("content") or "")[:100]
                print(f"    [{role}] {text}")
        else:
            pretty = json.dumps(data, indent=2, ensure_ascii=False)
            for line in pretty.split("\n")[:10]:
                print(f"    {line}")
    else:
        print(f"    Response: {json.dumps(data, indent=2, ensure_ascii=False)[:300]}")
    print()

    # Poll message endpoint — may reveal real-time message queue
    print("  --- Poll Message ---")
    result = _post(f"{OPENROOM_URL}{HIDDEN_APIS['poll_message']}", {}, auth)
    status = result.get("status", 0)
    data = result.get("data", {})
    print(f"    Status: {status}")
    pretty = json.dumps(data, indent=2, ensure_ascii=False)
    for line in pretty.split("\n")[:8]:
        print(f"    {line}")
    print()

    # Show remaining hidden endpoints for reference
    print("  --- Other Hidden Endpoints (not probed to avoid side-effects) ---")
    for name, path in HIDDEN_APIS.items():
        if name in ("query_conversations", "query_messages", "poll_message"):
            continue
        print(f"    {name:25s} {path}")


# ──── Character Creation from Template ────────────────────────────────────
# v1.50.1 [2026-03-25] — Template-based character creation using extracted master prompt

def create_character_from_template(auth: OpenRoomAuth, description: str = "") -> None:
    """Use OpenRoom's AI to generate a full character mod from description.

    Two-step process:
    1. POST /ugc/api/mod/generate — AI generates character spec from description
    2. POST /ugc/api/mod/create — creates the character mod from the spec

    Args:
        auth: Authenticated session.
        description: Character description (prompted interactively if empty).

    CONNECTS: generate_character, create_character, UGC_API
    CALLED BY: main dispatch, REPL create command
    """
    print("\n=== CHARACTER FROM TEMPLATE ===\n")

    if not description:
        description = input("  Describe your character: ").strip()
    if not description:
        print("  [!] Description required")
        return

    # Step 1: Get the default system prompt template
    print("  [1/3] Fetching default system prompt template...")
    result = _post(f"{UGC_API}/mod/default-system-prompt", {}, auth)
    default_prompt = ""
    if result.get("status") == 200:
        default_prompt = result.get("data", {}).get("system_prompt", "")
        print(f"    Template loaded ({len(default_prompt)} chars)")
    else:
        print(f"    [!] Could not fetch template: {result.get('status')}")
        print("    Continuing without template...")

    # Step 2: AI-generate the character from description + template
    print(f"  [2/3] AI-generating character from: '{description[:60]}...'")
    gen_result = _post(f"{UGC_API}/mod/generate", {
        "description": description,
        "system_prompt": default_prompt,
    }, auth, timeout=30)

    if gen_result.get("status") != 200:
        print(f"    [!] Generation failed: {gen_result}")
        return

    gen_data = gen_result.get("data", {})
    print(f"    Generated data keys: {list(gen_data.keys()) if isinstance(gen_data, dict) else type(gen_data)}")
    pretty = json.dumps(gen_data, indent=2, ensure_ascii=False)
    for line in pretty.split("\n")[:20]:
        print(f"    {line}")
    if len(pretty.split("\n")) > 20:
        print(f"    ... ({len(pretty)} chars total)")

    # Step 3: Create the mod from generated data
    confirm = input("\n  Create this character? (y/N): ").strip().lower()
    if confirm != "y":
        print("  Cancelled.")
        return

    print("  [3/3] Creating character mod...")
    # Build the create payload from the generation output
    mod_payload = gen_data.get("mod", gen_data)
    if isinstance(mod_payload, dict):
        # Ensure required fields exist
        mod_payload.setdefault("name", description[:30])
        mod_payload.setdefault("identifier", description[:20].lower().replace(" ", "_"))
        mod_payload.setdefault("description", description)

    create_result = _post(f"{UGC_API}/mod/create", {
        "mod": mod_payload,
        "author_id": auth.user_id,
        "published": False,
    }, auth)

    print(f"    Status: {create_result.get('status')}")
    print(f"    Response: {json.dumps(create_result.get('data', {}), indent=2, ensure_ascii=False)[:400]}")


# ──── Room Viewer ─────────────────────────────────────────────────────────
# v1.50.1 [2026-03-25] — Combined room info + messages + danmaku + stats

def view_room(auth: OpenRoomAuth, room_id: int = 5050) -> None:
    """Full room view: info, messages, danmaku, stats.

    Combines chatroom info, recent messages, recent comments, and
    known stats into a single comprehensive view.

    Args:
        auth: Authenticated session.
        room_id: Room to view (default 5050).

    CONNECTS: get_room_messages, get_room_comments, list_rooms
    CALLED BY: main dispatch, REPL view command
    """
    print(f"\n{'=' * 60}")
    print(f"  ROOM VIEWER — Room {room_id}")
    print(f"{'=' * 60}\n")

    # Room info
    print("  --- Room Info ---")
    info_result = _post(f"{WEAVER_API}/chatroom/get_chatroom_info", {
        "room_id": room_id,
    }, auth)
    if info_result.get("status") == 200:
        info = info_result.get("data", {})
        room_name = info.get("room_name") or info.get("name") or "?"
        desc = info.get("description") or ""
        online = info.get("online_count", "?")
        host = info.get("host_name") or info.get("host", {}).get("name", "?")
        print(f"    Name:    {room_name}")
        print(f"    Host:    {host}")
        print(f"    Online:  {online}")
        if desc:
            print(f"    Desc:    {desc[:120]}")
        # Dump extra fields
        for k, v in info.items():
            if k not in ("room_name", "name", "description", "online_count",
                         "host_name", "host") and v:
                print(f"    {k}: {str(v)[:80]}")
    else:
        print(f"    [!] Could not fetch info: {info_result.get('status')}")
    print()

    # Known stats for room 5050
    if room_id == 5050:
        print("  --- Known Stats (snapshot) ---")
        for k, v in ROOM_5050_STATS.items():
            print(f"    {k:12s}: {v:>12,}")
        print()

    # Recent messages
    print("  --- Recent Messages ---")
    messages = get_room_messages(auth, room_id, limit=10)
    if messages:
        for msg in messages:
            user = msg.get("user_name") or msg.get("nickname") or "anon"
            text = msg.get("content") or msg.get("text") or ""
            print(f"    {user}: {text[:100]}")
    else:
        print("    (no messages)")
    print()

    # Recent comments/danmaku
    print("  --- Recent Comments (Danmaku) ---")
    comments = get_room_comments(auth, room_id, limit=10)
    if comments:
        for cmt in comments:
            user = cmt.get("user_name") or cmt.get("nickname") or "anon"
            text = cmt.get("content") or cmt.get("text") or ""
            likes = cmt.get("like_count", 0)
            print(f"    {user} ({likes} likes): {text[:100]}")
    else:
        print("    (no comments)")
    print()

    # Livestream features reference
    print("  --- Known Livestream Features ---")
    for feat in LIVESTREAM_FEATURES:
        print(f"    {feat}")


# ──── API Spec Export ─────────────────────────────────────────────────────
# v1.50.1 [2026-03-25] — Export full discovered API spec as structured JSON

def export_api_spec(auth: OpenRoomAuth) -> None:
    """Export everything discovered as structured JSON spec.

    Writes a comprehensive API specification file including all known
    endpoints, hidden APIs, credits system, livestream features, and
    connection details.

    Args:
        auth: Authenticated session (used for user context in export).

    CALLED BY: main dispatch, REPL export command
    EMITS: openroom_api_spec.json file
    """
    print("\n=== EXPORT API SPEC ===\n")

    spec = {
        "meta": {
            "title": "OpenRoom.ai API Specification",
            "source": "ARGUS HAR analysis + heap analysis + live probing",
            "exported_at": datetime.datetime.now().isoformat(),
            "version": "v1.50.1",
            "user_id": auth.user_id or "unknown",
        },
        "base_urls": {
            "web": OPENROOM_URL,
            "cdn": OPENROOM_CDN,
            "websocket": OPENROOM_WS,
            "weaver_api": WEAVER_API,
            "ugc_api": UGC_API,
            "storage_api": STORAGE_API,
        },
        "models": KNOWN_MODELS,
        "characters": {str(k): v for k, v in KNOWN_CHARACTERS.items()},
        "endpoints": {
            "character_chat": {
                "list_sessions": {
                    "method": "POST",
                    "path": "/weaver/api/v1/character/list_sessions",
                    "body": {"size": "int"},
                },
                "start_session": {
                    "method": "POST",
                    "path": "/weaver/api/v1/character/start_session",
                    "body": {"mod_id": "int", "character_id": "int"},
                },
                "send_msg": {
                    "method": "POST",
                    "path": "/weaver/api/v1/character/send_msg",
                    "body": {"text": "str", "session_id": "int", "model": "str"},
                },
                "get_chat_history": {
                    "method": "POST",
                    "path": "/weaver/api/v1/character/get_chat_history",
                    "body": {"session_id": "int", "cursor": "int", "size": "int",
                             "is_asc": "bool", "start_time": "int", "end_time": "int"},
                },
                "get_app_list": {
                    "method": "POST",
                    "path": "/weaver/api/v1/character/get_app_list",
                    "body": {"mod_id": "int", "session_id": "int"},
                },
                "get_mod_list": {
                    "method": "POST",
                    "path": "/weaver/api/v1/character/get_mod_list",
                    "body": {},
                },
                "report_os_event": {
                    "method": "POST",
                    "path": "/weaver/api/v1/character/report_os_event",
                    "body": {"session_id": "int", "model": "str", "os_events": "list"},
                },
            },
            "chatrooms": {
                "list": {
                    "method": "POST",
                    "path": "/weaver/api/v1/chatroom/room/list",
                    "body": {"limit": "int"},
                },
                "message_list": {
                    "method": "POST",
                    "path": "/weaver/api/v1/chatroom/message/list",
                    "body": {"room_id": "int", "type": "int", "limit": "int"},
                },
                "comment_list": {
                    "method": "POST",
                    "path": "/weaver/api/v1/chatroom/comment/list",
                    "body": {"room_id": "int", "sort": "str", "limit": "int"},
                },
                "get_info": {
                    "method": "POST",
                    "path": "/weaver/api/v1/chatroom/get_chatroom_info",
                    "body": {"room_id": "int"},
                },
            },
            "ugc_creation": {
                "create_mod": {
                    "method": "POST",
                    "path": "/ugc/api/mod/create",
                    "body": {"mod": "object", "author_id": "str", "published": "bool"},
                },
                "generate_mod": {
                    "method": "POST",
                    "path": "/ugc/api/mod/generate",
                    "body": {"description": "str", "system_prompt": "str"},
                },
                "default_system_prompt": {
                    "method": "POST",
                    "path": "/ugc/api/mod/default-system-prompt",
                    "body": {},
                },
            },
            "storage": {
                "list_files": {
                    "method": "POST",
                    "path": "/weaver_storage/api/v1/storage/list_files",
                    "body": {"path": "str", "session_id": "int"},
                    "query": {"user_id": "str", "device_id": "str"},
                },
                "get_file": {
                    "method": "POST",
                    "path": "/weaver_storage/api/v1/storage/get_file",
                    "body": {"session_id": "int", "file_path": "str"},
                },
                "put_text_files": {
                    "method": "POST",
                    "path": "/weaver_storage/api/v1/storage/put_text_files_by_json",
                    "body": {"files": "list", "session_id": "int"},
                },
                "delete_files": {
                    "method": "POST",
                    "path": "/weaver_storage/api/v1/storage/delete_files_by_paths",
                    "body": {"file_paths": "list", "session_id": "int"},
                },
            },
            "account": {
                "get_user_status": {
                    "method": "POST",
                    "path": "/weaver/api/v1/account/get_user_status",
                    "body": {},
                },
                "report_events": {
                    "method": "POST",
                    "path": "/weaver/api/v1/event/report",
                    "body": {"events": "list"},
                },
            },
            "hidden_conversation": {
                name: {
                    "method": "POST",
                    "path": path,
                    "source": "heap_analysis",
                }
                for name, path in HIDDEN_APIS.items()
            },
            "credits": {
                name: {
                    "rpc_name": endpoint,
                    "source": "heap_analysis",
                }
                for name, endpoint in CREDITS_APIS.items()
            },
        },
        "websocket": {
            "url": OPENROOM_WS,
            "auth": "HS256 JWT in query param ?token=",
            "os_param": "?os=3 (web client)",
        },
        "livestream_features": LIVESTREAM_FEATURES,
        "known_room_stats": {
            "room_5050": ROOM_5050_STATS,
        },
    }

    # Write to file
    out_dir = _ROOT / "data"
    out_dir.mkdir(exist_ok=True)
    out_path = out_dir / "openroom_api_spec.json"
    out_path.write_text(json.dumps(spec, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"  Exported to: {out_path}")
    print(f"  Size: {out_path.stat().st_size:,} bytes")
    print(f"  Endpoints: {sum(len(v) for v in spec['endpoints'].values())} total")


# ──── Interactive REPL ────────────────────────────────────────────────────
# v1.50.1 [2026-03-25] — Full interactive exploration shell

REPL_HELP = """
  OpenRoom.ai Interactive Explorer
  ================================

  rooms                     List chatrooms
  sessions                  List chat sessions
  characters                List character mods
  messages <room_id>        Get messages from room (default 5050)
  danmaku [room_id]         Watch live danmaku (default 5050, Ctrl+C to stop)
  chat <session_id>         Get chat history for session
  credits                   Check credits/wallet endpoints
  conversations             List conversations (hidden API)
  create "description"      Create character from template
  apps <session_id>         List apps for session
  files <session_id> [path] Browse session filesystem
  view [room_id]            Full room viewer (default 5050)
  models                    Test available LLM models
  start                     Start a new chat session
  endpoints                 Show all API endpoints
  export                    Export full API spec as JSON
  status                    Show auth status
  help                      Show this help
  exit / quit               Exit REPL
"""


def run_repl(auth: OpenRoomAuth) -> None:
    """Interactive REPL for exploring OpenRoom.ai APIs.

    Provides a command loop with all exploration commands available
    as simple typed commands.

    Args:
        auth: Authenticated session.

    CONNECTS: All exploration functions
    CALLED BY: main dispatch
    """
    print("\n" + "=" * 60)
    print("  OPENROOM.AI INTERACTIVE EXPLORER")
    print("  Type 'help' for commands, 'exit' to quit")
    print("=" * 60)
    print(f"  Auth: {auth.status()}")
    print()

    while True:
        try:
            raw = input("openroom> ").strip()
        except (EOFError, KeyboardInterrupt):
            print("\n  Goodbye.")
            break

        if not raw:
            continue

        # Parse command and arguments
        parts = raw.split(None, 1)
        cmd = parts[0].lower()
        arg_str = parts[1] if len(parts) > 1 else ""

        try:
            if cmd in ("exit", "quit", "q"):
                print("  Goodbye.")
                break

            elif cmd == "help":
                print(REPL_HELP)

            elif cmd == "status":
                print(f"  Auth: {auth.status()}")

            elif cmd == "rooms":
                list_rooms(auth)

            elif cmd == "sessions":
                list_sessions(auth)

            elif cmd == "characters":
                list_characters(auth)

            elif cmd == "messages":
                rid = int(arg_str) if arg_str else 5050
                show_room_messages(auth, rid)

            elif cmd == "danmaku":
                rid = int(arg_str) if arg_str else 5050
                watch_danmaku(auth, rid)

            elif cmd == "chat":
                if not arg_str:
                    print("  Usage: chat <session_id>")
                else:
                    get_chat_history(auth, int(arg_str))

            elif cmd == "credits":
                explore_credits(auth)

            elif cmd == "conversations":
                explore_conversations(auth)

            elif cmd == "create":
                # Accept quoted or unquoted description
                desc = arg_str.strip("\"'")
                create_character_from_template(auth, desc)

            elif cmd == "apps":
                if not arg_str:
                    print("  Usage: apps <session_id>")
                else:
                    list_apps(auth, int(arg_str))

            elif cmd == "files":
                file_parts = arg_str.split(None, 1)
                if not file_parts:
                    print("  Usage: files <session_id> [path]")
                else:
                    sid = int(file_parts[0])
                    path = file_parts[1] if len(file_parts) > 1 else ""
                    browse_files(auth, sid, path)

            elif cmd == "view":
                rid = int(arg_str) if arg_str else 5050
                view_room(auth, rid)

            elif cmd == "models":
                test_models(auth)

            elif cmd == "start":
                start_session(auth)

            elif cmd == "endpoints":
                show_endpoints()

            elif cmd == "export":
                export_api_spec(auth)

            elif cmd == "generate":
                generate_character(auth)

            elif cmd == "full":
                show_endpoints()
                list_sessions(auth)
                list_rooms(auth)
                list_characters(auth)
                explore_credits(auth)
                explore_conversations(auth)

            else:
                print(f"  Unknown command: {cmd}")
                print("  Type 'help' for available commands")

        except ValueError as exc:
            print(f"  [!] Invalid argument: {exc}")
        except KeyboardInterrupt:
            print()  # Clean line after Ctrl+C in danmaku etc.
        except Exception as exc:
            print(f"  [!] Error: {exc}")
            traceback.print_exc()


# ──── Character Creation (Original) ──────────────────────────────────────

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
        # v1.50.1 [2026-03-25] — Hidden endpoints from heap analysis
        "Hidden — Conversations (heap)": [
            ("POST", path, name.replace("_", " ").title(), "heap_analysis")
            for name, path in HIDDEN_APIS.items()
        ],
        "Hidden — Credits (heap)": [
            ("RPC", endpoint, name.replace("_", " ").title(), "heap_analysis")
            for name, endpoint in CREDITS_APIS.items()
        ],
        "Hidden — Livestream Features (heap)": [
            ("EVT", feat, "Livestream event", "heap_analysis")
            for feat in LIVESTREAM_FEATURES
        ],
    }

    for group, eps in endpoints.items():
        print(f"  {group}:")
        for method, path, desc, body in eps:
            print(f"    {method:5s} {path[:65]:65s} {desc}")
        print()


# ──── Main ───────────────────────────────────────────────────────────────────

# v1.50.1 [2026-03-25] — Expanded main with all new commands + REPL
def main() -> None:
    parser = argparse.ArgumentParser(description="OpenRoom.ai Explorer v1.50.1")
    parser.add_argument("command", nargs="?", default="menu",
                        choices=["menu", "sessions", "characters", "chat", "rooms",
                                 "messages", "danmaku", "credits", "conversations",
                                 "view", "template", "apps", "files", "create",
                                 "generate", "models", "start", "endpoints",
                                 "export", "repl", "full"])
    parser.add_argument("session_id", nargs="?", type=int,
                        help="Session/Room ID for chat/apps/files/messages/danmaku/view")
    parser.add_argument("--har", type=Path, help="HAR file for auth tokens")
    parser.add_argument("--model", default="Modern", help="LLM model name")
    parser.add_argument("--path", default="", help="File path for browse")
    parser.add_argument("--interval", type=int, default=5,
                        help="Poll interval for danmaku (seconds)")
    parser.add_argument("--description", default="",
                        help="Character description for template command")
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
    print("  OPENROOM.AI EXPLORER v1.50.1")
    print("  Built from ARGUS HAR + Heap Intelligence")
    print("=" * 60)
    print(f"  Auth: {auth.status()}")
    print(f"  HAR:  {har_path}")
    print()

    if args.command == "menu":
        print("  Commands:")
        print("    sessions          List all chat sessions")
        print("    characters        List character mods")
        print("    chat <sid>        Get chat history for a session")
        print("    rooms             List chatrooms")
        print("    messages [rid]    Get messages from room (default 5050)")
        print("    danmaku [rid]     Watch live danmaku (default 5050)")
        print("    view [rid]        Full room viewer (default 5050)")
        print("    credits           Check credits/wallet endpoints")
        print("    conversations     Explore hidden conversation API")
        print("    template          Create character from AI template")
        print("    apps <sid>        List apps for a session")
        print("    files <sid>       Browse session filesystem")
        print("    create            Create a new AI character (interactive)")
        print("    generate          AI-generate a character")
        print("    models            Test available LLM models")
        print("    start             Start a new session")
        print("    endpoints         Show all API endpoints")
        print("    export            Export full API spec as JSON")
        print("    repl              Interactive exploration shell")
        print("    full              Run everything")
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
    # v1.50.1 [2026-03-25] — New command dispatch entries
    elif args.command == "messages":
        rid = args.session_id if args.session_id else 5050
        show_room_messages(auth, rid)
    elif args.command == "danmaku":
        rid = args.session_id if args.session_id else 5050
        watch_danmaku(auth, rid, interval=args.interval)
    elif args.command == "view":
        rid = args.session_id if args.session_id else 5050
        view_room(auth, rid)
    elif args.command == "credits":
        explore_credits(auth)
    elif args.command == "conversations":
        explore_conversations(auth)
    elif args.command == "template":
        create_character_from_template(auth, args.description)
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
    elif args.command == "export":
        export_api_spec(auth)
    elif args.command == "repl":
        run_repl(auth)
    elif args.command == "full":
        show_endpoints()
        list_sessions(auth)
        list_rooms(auth)
        list_characters(auth)
        explore_credits(auth)
        explore_conversations(auth)


if __name__ == "__main__":
    main()
