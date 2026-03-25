#!/usr/bin/env python3
"""
Sesame AI Explorer — API Client built from ARGUS intelligence
===============================================================

Interactive CLI for exploring Sesame AI's API surface discovered via
ARGUS HAR analysis. Uses Firebase auth tokens from captured traffic.

Usage:
    python -m scripts.argus.clients.sesame_client              # Interactive menu
    python -m scripts.argus.clients.sesame_client interactive   # Interactive REPL
    python -m scripts.argus.clients.sesame_client flags         # List feature flags
    python -m scripts.argus.clients.sesame_client user          # User profile
    python -m scripts.argus.clients.sesame_client bucket        # Explore public bucket
    python -m scripts.argus.clients.sesame_client endpoints     # List all discovered endpoints
    python -m scripts.argus.clients.sesame_client staff         # Test staff flag
    python -m scripts.argus.clients.sesame_client agents        # Probe agent services
    python -m scripts.argus.clients.sesame_client export        # Export API spec to JSON
    python -m scripts.argus.clients.sesame_client full          # Run everything

Version: v1.50.0 [2026-03-25]

Change Log:
    v1.50.0 [2026-03-25] — Interactive REPL, gate trigger mapper, token refresh,
                            API spec export, call-info upload URL generation
Author:  CosySim Team

CONNECTS: ARGUS HAR analyzer, Firebase Auth, Statsig, GCS
"""
from __future__ import annotations

import argparse
import base64
import copy
import itertools
import json
import re
import shlex
import sys
import time
import traceback
from pathlib import Path
from typing import Any, Dict, List, Optional
from urllib.parse import urlencode

import requests

_ROOT = Path(__file__).resolve().parent.parent.parent.parent
sys.path.insert(0, str(_ROOT))

FIREBASE_SECURETOKEN_URL = "https://securetoken.googleapis.com/v1/token"


# ──── Constants from ARGUS Discovery ─────────────────────────────────────────

SESAME_APP_URL = "https://app.sesame.com"
SESAME_API_URL = "https://sesameai.app"
SESAME_WS_URL = "wss://sesameai.app/agent-service-0/v1/connect"

FIREBASE_PROJECT = "sesame-ai-demo"
FIREBASE_API_KEY = "REDACTED-GOOGLE-API-KEY"
FIREBASE_AUTH_URL = "https://identitytoolkit.googleapis.com/v1"
FIREBASE_APPCHECK_URL = "https://content-firebaseappcheck.googleapis.com/v1"

STATSIG_CLIENT_KEY = "client-TGCzyFkjJ0ZvNupjjxCKPpxPEO8WdmZjQhxLgJlgM6H"
STATSIG_URL = "https://featureassets.org/v1"

GCS_PUBLIC_BUCKET = "sesame-dev-public"
GCS_PROD_BUCKET = "sesame-call-assets-us-central1-prod"
GCS_API = "https://storage.googleapis.com/storage/v1"

RUDDERSTACK_WRITE_KEY = None  # Extracted at runtime from HAR if needed


# ──── Token Management ───────────────────────────────────────────────────────

class TokenStore:
    """Manages Firebase JWT tokens extracted from HAR files."""

    def __init__(self) -> None:
        self._token: Optional[str] = None
        self._decoded: Optional[Dict] = None
        self._expires: float = 0

    def load_from_har(self, har_path: Path) -> bool:
        """Extract the most recent Firebase JWT from a HAR file."""
        try:
            har = json.loads(har_path.read_text(errors="replace"))
            entries = har.get("log", {}).get("entries", [])

            for entry in reversed(entries):  # newest first
                url = entry.get("request", {}).get("url", "")
                if "id_token=" in url:
                    token = url.split("id_token=")[1].split("&")[0]
                    self._set_token(token)
                    return True

                # Also check Authorization headers
                for h in entry.get("request", {}).get("headers", []):
                    if h.get("name", "").lower() == "authorization":
                        val = h.get("value", "")
                        if val.startswith("Bearer "):
                            token = val[7:]
                            if self._is_firebase_jwt(token):
                                self._set_token(token)
                                return True
        except Exception as exc:
            print(f"  [!] Failed to load token from HAR: {exc}")
        return False

    def _set_token(self, token: str) -> None:
        self._token = token
        self._decoded = self._decode_jwt(token)
        if self._decoded:
            self._expires = self._decoded.get("exp", 0)

    def _is_firebase_jwt(self, token: str) -> bool:
        decoded = self._decode_jwt(token)
        if decoded and "firebase" in decoded.get("iss", ""):
            return True
        return False

    @staticmethod
    def _decode_jwt(token: str) -> Optional[Dict]:
        """Decode JWT payload without signature verification."""
        try:
            parts = token.split(".")
            if len(parts) < 2:
                return None
            payload = parts[1] + "=" * (4 - len(parts[1]) % 4)
            return json.loads(base64.urlsafe_b64decode(payload))
        except Exception:
            return None

    @property
    def token(self) -> Optional[str]:
        return self._token

    @property
    def user_id(self) -> str:
        return self._decoded.get("user_id", "") if self._decoded else ""

    @property
    def email(self) -> str:
        return self._decoded.get("email", "") if self._decoded else ""

    @property
    def name(self) -> str:
        return self._decoded.get("name", "") if self._decoded else ""

    @property
    def is_expired(self) -> bool:
        return time.time() > self._expires if self._expires else True

    @property
    def expires_in(self) -> str:
        if not self._expires:
            return "unknown"
        remaining = self._expires - time.time()
        if remaining < 0:
            return f"EXPIRED {abs(remaining)/60:.0f}min ago"
        return f"{remaining/60:.0f}min"

    def status(self) -> str:
        if not self._token:
            return "No token loaded"
        exp = self.expires_in
        return f"{self.name} ({self.email}) | Expires: {exp}"

    # v1.52.0 [2026-03-26] — Token refresh + HAR refresh token extraction

    def load_refresh_token_from_har(self, har_path: Path) -> bool:
        """Extract refresh_token from securetoken.googleapis.com calls in HAR."""
        try:
            har = json.loads(har_path.read_text(errors="replace"))
            for entry in har.get("log", {}).get("entries", []):
                url = entry.get("request", {}).get("url", "")
                if "securetoken.googleapis.com" not in url:
                    continue
                post = entry.get("request", {}).get("postData", {}).get("text", "")
                if not post or "refresh_token" not in post:
                    continue
                parts = dict(x.split("=", 1) for x in post.split("&") if "=" in x)
                if "refresh_token" in parts:
                    self._refresh_token = parts["refresh_token"]
                    return True
        except Exception:
            pass
        return False

    def refresh(self) -> bool:
        """Exchange refresh_token for a fresh id_token via Firebase."""
        rt = getattr(self, "_refresh_token", None)
        if not rt:
            print("  [!] No refresh token. Load from HAR first.")
            return False
        try:
            r = requests.post(
                f"{FIREBASE_SECURETOKEN_URL}?key={FIREBASE_API_KEY}",
                data={"grant_type": "refresh_token", "refresh_token": rt},
                timeout=15,
            )
            if r.status_code != 200:
                print(f"  [!] Refresh failed: {r.status_code} {r.text[:100]}")
                return False
            data = r.json()
            self._set_token(data["id_token"])
            # Update refresh token if rotated
            if "refresh_token" in data:
                self._refresh_token = data["refresh_token"]
            print(f"  [OK] Token refreshed — valid for {self.expires_in}")
            return True
        except Exception as exc:
            print(f"  [!] Refresh error: {exc}")
            return False

    def ensure_valid(self) -> bool:
        """Auto-refresh if token is expired or about to expire (<5min)."""
        if not self._token:
            return False
        remaining = self._expires - time.time() if self._expires else -1
        if remaining > 300:  # More than 5 min left
            return True
        return self.refresh()

    @property
    def auth_headers(self) -> Dict[str, str]:
        """Get Authorization headers, auto-refreshing if needed."""
        self.ensure_valid()
        return {
            "Authorization": f"Bearer {self._token}",
            "Content-Type": "application/json",
        }


# ──── Sesame API Client ─────────────────────────────────────────────────────
# v1.52.0 [2026-03-26] — Full REST + WebSocket client

class SesameClient:
    """Live API client for Sesame AI with auto-refreshing tokens."""

    def __init__(self, token_store: TokenStore):
        self.ts = token_store
        self._session_id: Optional[str] = None
        self._user_profile: Optional[Dict] = None

    @property
    def _h(self) -> Dict[str, str]:
        return self.ts.auth_headers

    # ── User Profile ─────────────────────────────────────────────

    def get_profile(self) -> Optional[Dict]:
        """Fetch user profile."""
        r = requests.get(f"{SESAME_API_URL}/api/user", headers=self._h, timeout=10)
        if r.status_code == 200:
            self._user_profile = r.json()
            return self._user_profile
        print(f"  [!] Profile: {r.status_code} {r.text[:100]}")
        return None

    def update_profile(self, **fields) -> Optional[Dict]:
        """Update writable profile fields.

        Writable: nickname, birthday, allow_training_from_calls,
                  prefer_product_news_emails
        Protected: email, roles, moderation_status, display_name
        """
        r = requests.patch(
            f"{SESAME_API_URL}/api/user", headers=self._h,
            json=fields, timeout=10,
        )
        if r.status_code == 200:
            self._user_profile = r.json()
            return self._user_profile
        print(f"  [!] Update: {r.status_code} {r.text[:100]}")
        return None

    # ── Health ───────────────────────────────────────────────────

    def health(self) -> Dict:
        """Check API and agent service health."""
        results = {}
        try:
            r = requests.get(f"{SESAME_API_URL}/api/health", timeout=5)
            results["api"] = r.status_code
        except Exception:
            results["api"] = 0
        for i in range(5):
            try:
                r = requests.get(f"{SESAME_API_URL}/agent-service-{i}/health", timeout=5)
                results[f"agent-{i}"] = r.status_code
            except Exception:
                results[f"agent-{i}"] = 0
        return results

    # ── Upload URL ───────────────────────────────────────────────

    def get_upload_url(self, call_id: int) -> Optional[str]:
        """Generate a presigned upload URL for a call recording."""
        r = requests.post(
            f"{SESAME_API_URL}/api/generate-call-file-upload-url",
            headers=self._h, json={"call_id": call_id}, timeout=10,
        )
        if r.status_code == 200:
            return r.json()
        print(f"  [!] Upload URL: {r.status_code} {r.text[:100]}")
        return None

    # ── Feature Flags ────────────────────────────────────────────

    def get_flags(self, email_override: str = "") -> Dict:
        """Get Statsig feature flags. Optionally override email for testing."""
        email = email_override or self.ts.email
        r = requests.post(
            f"{STATSIG_URL}/initialize?k={STATSIG_CLIENT_KEY}",
            json={
                "user": {"email": email, "userID": self.ts.user_id or "anon"},
                "statsigMetadata": {"sdkType": "js-client", "sdkVersion": "5.4.0"},
            },
            timeout=10,
        )
        if r.status_code == 200:
            return r.json()
        return {}

    def get_employee_flags(self) -> Dict:
        """Get flags as if you were a Sesame employee (@sesame.com)."""
        return self.get_flags(email_override="staff@sesame.com")

    def compare_flags(self) -> Dict[str, Any]:
        """Compare normal vs employee flags."""
        normal = self.get_flags()
        employee = self.get_employee_flags()
        ng = normal.get("feature_gates", {})
        eg = employee.get("feature_gates", {})
        normal_on = sum(1 for g in ng.values() if g.get("value"))
        employee_on = sum(1 for g in eg.values() if g.get("value"))
        extra = []
        for name, gate in eg.items():
            if gate.get("value") and not ng.get(name, {}).get("value"):
                extra.append(name)
        return {
            "normal_gates": normal_on,
            "employee_gates": employee_on,
            "extra_count": len(extra),
            "extra_gates": extra,
            "total": len(eg),
        }

    # ── WebSocket Session ────────────────────────────────────────

    def connect_agent(self, character: str = "Maya", timeout_secs: int = 15) -> Dict:
        """Connect to Sesame voice agent via WebSocket.

        Returns session info including session_id and ICE servers.
        Does NOT do WebRTC negotiation (no audio).
        """
        import asyncio
        try:
            import websockets
        except ImportError:
            return {"error": "websockets not installed — pip install websockets"}

        self.ts.ensure_valid()
        result: Dict[str, Any] = {"connected": False}

        async def _connect():
            uri = f"{SESAME_WS_URL}?id_token={self.ts.token}"
            try:
                async with websockets.connect(uri, additional_headers={
                    "Origin": SESAME_APP_URL,
                    "User-Agent": "CosySim-ARGUS/1.52",
                }) as ws:
                    result["connected"] = True

                    # Wait for initialize
                    msg = await asyncio.wait_for(ws.recv(), timeout=10)
                    data = json.loads(msg)
                    result["type"] = data.get("type")
                    result["session_id"] = data.get("session_id") or data.get("content", {}).get("session_id")
                    self._session_id = result["session_id"]

                    # Send location
                    await ws.send(json.dumps({
                        "type": "client_location_state",
                        "latitude": -33.87, "longitude": 151.21,
                        "address": "Sydney, Australia",
                        "timezone": "Australia/Sydney",
                    }))

                    # Collect messages
                    result["messages"] = []
                    for _ in range(5):
                        try:
                            msg = await asyncio.wait_for(ws.recv(), timeout=5)
                            data = json.loads(msg)
                            result["messages"].append({
                                "type": data.get("type"),
                                "preview": json.dumps(data)[:150],
                            })
                            if data.get("type") == "webrtc_config":
                                servers = data.get("content", {}).get("ice_servers", [])
                                result["ice_servers"] = len(servers)
                        except asyncio.TimeoutError:
                            break

                    # Disconnect gracefully
                    await ws.send(json.dumps({"type": "call_disconnect"}))
                    result["status"] = "session_created"

            except Exception as exc:
                result["error"] = str(exc)

        asyncio.run(_connect())
        return result


# ──── API Clients ────────────────────────────────────────────────────────────

def _get(url: str, headers: Dict = None, timeout: int = 10) -> Dict:
    """Safe GET request with error handling."""
    try:
        r = requests.get(url, headers=headers or {}, timeout=timeout)
        return {"status": r.status_code, "data": r.json() if r.headers.get("content-type", "").startswith("application/json") else r.text[:500]}
    except requests.exceptions.JSONDecodeError:
        return {"status": r.status_code, "data": r.text[:500]}
    except Exception as exc:
        return {"status": 0, "error": str(exc)}


def _post(url: str, data: Any = None, headers: Dict = None, timeout: int = 10) -> Dict:
    """Safe POST request."""
    try:
        r = requests.post(url, json=data, headers=headers or {}, timeout=timeout)
        return {"status": r.status_code, "data": r.json() if r.headers.get("content-type", "").startswith("application/json") else r.text[:500]}
    except requests.exceptions.JSONDecodeError:
        return {"status": r.status_code, "data": r.text[:500]}
    except Exception as exc:
        return {"status": 0, "error": str(exc)}


# ──── Exploration Modules ────────────────────────────────────────────────────

def explore_feature_flags(tokens: TokenStore) -> Dict:
    """Enumerate all Statsig feature flags."""
    print("\n=== FEATURE FLAGS (Statsig) ===\n")

    # Initialize with user context
    payload = {
        "user": {
            "userID": tokens.user_id or "anonymous",
            "email": tokens.email or "",
            "custom": {"isStaff": False},
        },
        "statsigMetadata": {
            "sdkType": "js-client",
            "sdkVersion": "3.2.0",
        },
    }

    url = f"{STATSIG_URL}/initialize?k={STATSIG_CLIENT_KEY}&st=javascript-client&sv=3.2"
    result = _post(url, payload)

    if result.get("status") != 200:
        print(f"  [!] Statsig returned {result.get('status')}: {result.get('error', result.get('data', ''))[:100]}")
        return result

    data = result.get("data", {})
    gates = data.get("feature_gates", {})
    configs = data.get("dynamic_configs", {})
    experiments = data.get("layer_configs", {})

    print(f"  Feature Gates:    {len(gates)}")
    print(f"  Dynamic Configs:  {len(configs)}")
    print(f"  Layer Configs:    {len(experiments)}")

    if gates:
        print(f"\n  -- Feature Gates --")
        enabled = {k: v for k, v in gates.items() if v.get("value") is True}
        disabled = {k: v for k, v in gates.items() if v.get("value") is False}
        print(f"  Enabled:  {len(enabled)}")
        print(f"  Disabled: {len(disabled)}")
        for name, gate in sorted(gates.items()):
            val = "ON " if gate.get("value") else "OFF"
            rule = gate.get("rule_id", "default")
            print(f"    [{val}] {name:20s}  rule={rule}")

    if configs:
        print(f"\n  -- Dynamic Configs --")
        for name, cfg in sorted(configs.items()):
            val = cfg.get("value", {})
            rule = cfg.get("rule_id", "default")
            keys = list(val.keys())[:5] if isinstance(val, dict) else []
            print(f"    {name:20s}  rule={rule}  keys={keys}")

    # Now test with isStaff: true
    print(f"\n  -- Staff Flag Test --")
    payload["user"]["custom"]["isStaff"] = True
    staff_result = _post(url, payload)
    if staff_result.get("status") == 200:
        staff_gates = staff_result.get("data", {}).get("feature_gates", {})
        diff_gates = {k: v for k, v in staff_gates.items()
                      if gates.get(k, {}).get("value") != v.get("value")}
        if diff_gates:
            print(f"  [!] {len(diff_gates)} gates CHANGED with isStaff=true:")
            for name, gate in diff_gates.items():
                old = "ON " if gates.get(name, {}).get("value") else "OFF"
                new = "ON " if gate.get("value") else "OFF"
                print(f"    {name}: {old} -> {new}")
        else:
            print(f"  No gates changed with isStaff=true (flag may be server-evaluated)")

    return {"gates": len(gates), "configs": len(configs), "experiments": len(experiments)}


def explore_user_profile(tokens: TokenStore) -> Dict:
    """Fetch user profile from Sesame API."""
    print("\n=== USER PROFILE ===\n")

    if not tokens.token:
        print("  [!] No token loaded — cannot fetch profile")
        return {}

    headers = {"Authorization": f"Bearer {tokens.token}"}
    result = _get(f"{SESAME_APP_URL}/api/user", headers)

    print(f"  Status: {result.get('status')}")
    if result.get("status") == 200:
        data = result.get("data", {})
        if isinstance(data, dict):
            for k, v in data.items():
                val = str(v)[:80]
                print(f"  {k:20s} = {val}")
        else:
            print(f"  Response: {str(data)[:200]}")
    else:
        print(f"  Error: {result.get('error', result.get('data', ''))[:200]}")

    return result


def explore_public_bucket() -> Dict:
    """Explore the public GCS bucket."""
    print("\n=== PUBLIC BUCKET (sesame-dev-public) ===\n")

    # List bucket contents
    url = f"{GCS_API}/b/{GCS_PUBLIC_BUCKET}/o?maxResults=50"
    result = _get(url)

    if result.get("status") != 200:
        print(f"  [!] Bucket access returned {result.get('status')}")
        print(f"  Note: Bucket may be public for reads but not listing")

        # Try direct object access instead
        print(f"\n  -- Known Objects (from HAR) --")
        known = [
            "images/laptop_sesame_app_background.jpg",
            "images/sesame_text.png",
            "images/maya_text.png",
            "images/miles_text.png",
            "audio/set_14_12_connect_07.mp3",
            "audio/set_14_12_disconnect.mp3",
        ]
        accessible = 0
        for obj in known:
            check = _get(f"https://storage.googleapis.com/{GCS_PUBLIC_BUCKET}/{obj}")
            status = check.get("status", 0)
            icon = "[OK]" if status == 200 else "[!!]"
            size = len(check.get("data", "")) if status == 200 else 0
            print(f"    {icon} {obj:50s} {status}")
            if status == 200:
                accessible += 1

        # Try guessing other paths
        print(f"\n  -- Path Probing --")
        probes = [
            "images/", "audio/", "video/", "config/", "data/",
            "models/", "voices/", "agents/", "internal/", "admin/",
            "debug/", "test/", "staging/",
        ]
        for probe in probes:
            check = _get(f"{GCS_API}/b/{GCS_PUBLIC_BUCKET}/o?prefix={probe}&maxResults=5")
            items = check.get("data", {}).get("items", []) if isinstance(check.get("data"), dict) else []
            if items:
                print(f"    [{len(items)}+] {probe}")
                for item in items[:3]:
                    print(f"          {item.get('name', '?')}")

        return {"accessible": accessible, "total_known": len(known)}

    # Bucket listing succeeded
    data = result.get("data", {})
    items = data.get("items", [])
    print(f"  Objects found: {len(items)}")
    for item in items:
        name = item.get("name", "?")
        size = int(item.get("size", 0))
        ct = item.get("contentType", "?")
        print(f"    {name:50s} {size:>10,} bytes  {ct}")

    return {"objects": len(items)}


def explore_agent_services(tokens: TokenStore) -> Dict:
    """Probe for numbered agent service instances."""
    print("\n=== AGENT SERVICE DISCOVERY ===\n")

    # Test different agent-service-N endpoints
    found = []
    for i in range(5):
        url = f"https://sesameai.app/agent-service-{i}/v1/health"
        result = _get(url, timeout=5)
        status = result.get("status", 0)
        if status in (200, 401, 403, 405):
            found.append(i)
            print(f"  [FOUND] agent-service-{i} (HTTP {status})")
        else:
            print(f"  [    ] agent-service-{i} (HTTP {status})")

    # Check for other service paths
    print(f"\n  -- Other Service Paths --")
    paths = [
        "/api/health", "/api/status", "/api/version",
        "/v1/health", "/v1/status", "/v1/version",
        "/api/agents", "/api/voices", "/api/models",
    ]
    for path in paths:
        result = _get(f"https://sesameai.app{path}", timeout=5)
        status = result.get("status", 0)
        if status not in (0, 404):
            data_preview = str(result.get("data", ""))[:60]
            print(f"  [{status}] {path:30s} {data_preview}")

    return {"agent_services": found}


def explore_firebase_config() -> Dict:
    """Explore Firebase project configuration."""
    print("\n=== FIREBASE CONFIGURATION ===\n")

    # Get project config
    url = f"{FIREBASE_AUTH_URL}/projects?key={FIREBASE_API_KEY}"
    result = _get(url)

    print(f"  Project: {FIREBASE_PROJECT}")
    print(f"  API Key: {FIREBASE_API_KEY}")

    if result.get("status") == 200:
        data = result.get("data", {})
        if isinstance(data, dict):
            print(f"  Auth domains: {data.get('authorizedDomains', [])}")
            providers = [p.get("providerId") for p in data.get("signInConfig", {}).get("signInMethods", data.get("providers", []))]
            if providers:
                print(f"  Sign-in providers: {providers}")
    else:
        print(f"  Config fetch: HTTP {result.get('status')}")

    # Check App Check configuration
    print(f"\n  -- App Check --")
    appcheck_url = f"{FIREBASE_APPCHECK_URL}/projects/{FIREBASE_PROJECT}/apps"
    result = _get(appcheck_url)
    print(f"  App Check endpoint: HTTP {result.get('status')}")

    return result


def explore_email_domains(tokens: TokenStore) -> Dict:
    """Test which email domains unlock additional features."""
    print("\n=== EMAIL DOMAIN GATE TESTING ===\n")

    url = f"{STATSIG_URL}/initialize?k={STATSIG_CLIENT_KEY}&st=javascript-client&sv=3.2"

    domains = [
        "gmail.com", "sesame.com", "sesameai.com", "sesame.ai",
        "google.com", "openai.com", "anthropic.com", "meta.com",
        "microsoft.com", "apple.com", "amazon.com",
    ]

    results = {}
    baseline = None

    for domain in domains:
        r = _post(url, {
            "user": {"userID": f"test-{domain}", "email": f"test@{domain}",
                     "custom": {"isStaff": True, "isAdmin": True}},
            "statsigMetadata": {"sdkType": "js-client", "sdkVersion": "3.2.0"},
        })
        if r.get("status") != 200:
            continue

        data = r.get("data", {})
        gates = data.get("feature_gates", {})
        enabled = sum(1 for v in gates.values() if v.get("value"))
        total = len(gates)
        results[domain] = enabled

        if baseline is None:
            baseline = enabled

        marker = ""
        if enabled > baseline:
            marker = f" *** +{enabled - baseline} EXTRA GATES ***"
        elif enabled == baseline:
            marker = ""

        print(f"  @{domain:20s} {enabled:2d}/{total} gates{marker}")

    # Find the employee domains
    employee_domains = [d for d, e in results.items() if e > baseline + 2]
    if employee_domains:
        print(f"\n  Employee domains: {', '.join(employee_domains)}")

    return results


def explore_dynamic_configs(tokens: TokenStore) -> Dict:
    """Show all dynamic configs with their actual values."""
    print("\n=== DYNAMIC CONFIGS (Live Values) ===\n")

    url = f"{STATSIG_URL}/initialize?k={STATSIG_CLIENT_KEY}&st=javascript-client&sv=3.2"

    # Get staff configs
    r = _post(url, {
        "user": {"userID": tokens.user_id or "anon", "email": "test@sesame.com",
                 "custom": {"isStaff": True}},
        "statsigMetadata": {"sdkType": "js-client", "sdkVersion": "3.2.0"},
    })
    if r.get("status") != 200:
        print(f"  [!] Statsig returned {r.get('status')}")
        return {}

    configs = r.get("data", {}).get("dynamic_configs", {})

    # Also get normal user configs for comparison
    r2 = _post(url, {
        "user": {"userID": "normal-user", "email": "user@gmail.com"},
        "statsigMetadata": {"sdkType": "js-client", "sdkVersion": "3.2.0"},
    })
    normal_configs = r2.get("data", {}).get("dynamic_configs", {}) if r2.get("status") == 200 else {}

    for name, cfg in sorted(configs.items()):
        val = cfg.get("value", {})
        rule = cfg.get("rule_id", "default")
        normal_val = normal_configs.get(name, {}).get("value", {})
        diff = " [STAFF-ONLY]" if val != normal_val else ""

        if isinstance(val, dict) and val:
            print(f"  Config: {name[:25]}...  rule={rule}{diff}")
            for k, v in val.items():
                nv = normal_val.get(k, v) if isinstance(normal_val, dict) else v
                changed = " <-- DIFFERENT" if v != nv else ""
                print(f"    {k:35s} = {json.dumps(v)[:50]}{changed}")
            print()

    return {"configs": len(configs)}


# ──── Token Refresh ─────────────────────────────────────────────────────────
# v1.50.0 [2026-03-25] — Firebase token refresh from HAR refresh_token

def extract_refresh_token(har_path: Path) -> Optional[str]:
    """Extract refresh_token from a HAR file's securetoken.googleapis.com calls.

    Scans HAR entries (newest first) for POST requests to the Firebase
    securetoken endpoint and extracts the refresh_token from either the
    request body (grant_type=refresh_token) or the response body.

    Args:
        har_path: Path to the HAR file.

    Returns:
        The refresh_token string if found, None otherwise.
    """
    try:
        har = json.loads(har_path.read_text(errors="replace"))
        entries = har.get("log", {}).get("entries", [])

        for entry in reversed(entries):
            url = entry.get("request", {}).get("url", "")

            # Look for securetoken.googleapis.com/v1/token responses
            if "securetoken.googleapis.com" in url and "/token" in url:
                # Try response body first — it always contains refresh_token
                resp_text = entry.get("response", {}).get("content", {}).get("text", "")
                if resp_text:
                    try:
                        resp_data = json.loads(resp_text)
                        rt = resp_data.get("refresh_token")
                        if rt:
                            return rt
                    except (json.JSONDecodeError, TypeError):
                        pass

                # Try request body — grant_type=refresh_token&refresh_token=...
                post_text = entry.get("request", {}).get("postData", {}).get("text", "")
                if "refresh_token=" in post_text:
                    for part in post_text.split("&"):
                        if part.startswith("refresh_token=") and not part.startswith("refresh_token=refresh_token"):
                            return part.split("=", 1)[1]

            # Also check identitytoolkit signInWithIdp responses for refreshToken
            if "identitytoolkit.googleapis.com" in url:
                resp_text = entry.get("response", {}).get("content", {}).get("text", "")
                if resp_text:
                    try:
                        resp_data = json.loads(resp_text)
                        rt = resp_data.get("refreshToken")
                        if rt:
                            return rt
                    except (json.JSONDecodeError, TypeError):
                        pass
    except Exception as exc:
        print(f"  [!] Failed to extract refresh token: {exc}")
    return None


def refresh_firebase_token(har_path: Path) -> Optional[str]:
    """Extract refresh_token from HAR and exchange for a new Firebase JWT.

    Uses the securetoken.googleapis.com/v1/token endpoint with
    grant_type=refresh_token to obtain a fresh id_token (JWT).

    Args:
        har_path: Path to the HAR file containing a refresh_token.

    Returns:
        New id_token (JWT string) if successful, None otherwise.

    CONNECTS: Firebase Auth, TokenStore
    """
    refresh_token = extract_refresh_token(har_path)
    if not refresh_token:
        print("  [!] No refresh_token found in HAR")
        return None

    print(f"  [+] Found refresh_token ({len(refresh_token)} chars)")
    print(f"  [*] Exchanging for new id_token...")

    payload = {
        "grant_type": "refresh_token",
        "refresh_token": refresh_token,
    }
    url = f"{FIREBASE_SECURETOKEN_URL}?key={FIREBASE_API_KEY}"

    try:
        r = requests.post(url, data=payload, timeout=15)
        if r.status_code == 200:
            data = r.json()
            new_token = data.get("id_token")
            new_refresh = data.get("refresh_token")
            expires_in = data.get("expires_in", "?")
            print(f"  [+] New id_token obtained (expires in {expires_in}s)")
            if new_refresh and new_refresh != refresh_token:
                print(f"  [+] Refresh token also rotated")
            return new_token
        else:
            err = r.json() if r.headers.get("content-type", "").startswith("application/json") else r.text[:300]
            print(f"  [!] Token refresh failed (HTTP {r.status_code}): {err}")
    except Exception as exc:
        print(f"  [!] Token refresh request failed: {exc}")
    return None


# ──── Gate Trigger Mapper ───────────────────────────────────────────────────
# v1.50.0 [2026-03-25] — Systematic gate analysis with combinatorial property testing

def _fetch_gates(user_props: Dict) -> Dict[str, bool]:
    """Fetch feature gates for a given set of user properties.

    Args:
        user_props: Dict with keys like userID, email, custom.

    Returns:
        Dict mapping gate name -> enabled (True/False).
    """
    url = f"{STATSIG_URL}/initialize?k={STATSIG_CLIENT_KEY}&st=javascript-client&sv=3.2"
    payload = {
        "user": user_props,
        "statsigMetadata": {"sdkType": "js-client", "sdkVersion": "3.2.0"},
    }
    r = _post(url, payload)
    if r.get("status") != 200:
        return {}
    gates = r.get("data", {}).get("feature_gates", {})
    return {k: bool(v.get("value")) for k, v in gates.items()}


def map_gate_triggers(gate_name: str) -> Dict:
    """Test a specific gate against many user property combinations to find what triggers it.

    Systematically varies email domain, isStaff, role, tier, and country to
    determine which user properties control a gate's state.

    Args:
        gate_name: The Statsig gate name to analyze.

    Returns:
        Dict with keys: gate_name, triggers (list of enabling combos),
        baseline (default state), tested (count), summary.

    CONNECTS: Statsig feature flags
    CALLED BY: run_interactive (toggle command), CLI
    """
    print(f"\n  Mapping triggers for gate: {gate_name}\n")

    # Define test dimensions
    # Each dimension is (property_path, [values_to_test])
    email_domains = ["gmail.com", "sesame.com", "sesameai.com", "meta.com",
                     "google.com", "anthropic.com"]
    staff_values = [False, True]
    role_values = ["user", "admin", "beta", "internal"]
    tier_values = ["free", "pro", "enterprise"]
    country_codes = ["US", "GB", "JP", "CN", "AU"]

    # Baseline: anonymous gmail user, no custom props
    baseline_props = {"userID": "mapper-baseline", "email": "test@gmail.com", "custom": {}}
    baseline_gates = _fetch_gates(baseline_props)
    baseline_val = baseline_gates.get(gate_name)

    if baseline_val is None:
        print(f"  [!] Gate '{gate_name}' not found in Statsig response")
        available = sorted(baseline_gates.keys())[:20]
        if available:
            print(f"  Available gates (first 20): {', '.join(available)}")
        return {"gate_name": gate_name, "error": "not_found"}

    print(f"  Baseline (gmail, no custom): {'ON' if baseline_val else 'OFF'}")

    triggers: List[Dict] = []
    tested = 0

    # Phase 1: Test email domains with no custom props
    print(f"\n  -- Phase 1: Email Domains --")
    for domain in email_domains:
        props = {"userID": f"mapper-{domain}", "email": f"test@{domain}", "custom": {}}
        gates = _fetch_gates(props)
        val = gates.get(gate_name)
        tested += 1
        if val != baseline_val:
            triggers.append({"email_domain": domain, "custom": {}})
            print(f"    @{domain:20s} -> {'ON' if val else 'OFF'}  ** FLIPPED **")
        else:
            print(f"    @{domain:20s} -> {'ON' if val else 'OFF'}")

    # Phase 2: Test isStaff with gmail (isolate staff effect)
    print(f"\n  -- Phase 2: isStaff Flag --")
    for staff in staff_values:
        props = {"userID": "mapper-staff", "email": "test@gmail.com",
                 "custom": {"isStaff": staff}}
        gates = _fetch_gates(props)
        val = gates.get(gate_name)
        tested += 1
        if val != baseline_val:
            triggers.append({"email_domain": "gmail.com", "custom": {"isStaff": staff}})
            print(f"    isStaff={str(staff):5s} -> {'ON' if val else 'OFF'}  ** FLIPPED **")
        else:
            print(f"    isStaff={str(staff):5s} -> {'ON' if val else 'OFF'}")

    # Phase 3: Test role values
    print(f"\n  -- Phase 3: Role Values --")
    for role in role_values:
        props = {"userID": "mapper-role", "email": "test@gmail.com",
                 "custom": {"role": role}}
        gates = _fetch_gates(props)
        val = gates.get(gate_name)
        tested += 1
        if val != baseline_val:
            triggers.append({"email_domain": "gmail.com", "custom": {"role": role}})
            print(f"    role={role:12s} -> {'ON' if val else 'OFF'}  ** FLIPPED **")
        else:
            print(f"    role={role:12s} -> {'ON' if val else 'OFF'}")

    # Phase 4: Test tier values
    print(f"\n  -- Phase 4: Tier Values --")
    for tier in tier_values:
        props = {"userID": "mapper-tier", "email": "test@gmail.com",
                 "custom": {"tier": tier}}
        gates = _fetch_gates(props)
        val = gates.get(gate_name)
        tested += 1
        if val != baseline_val:
            triggers.append({"email_domain": "gmail.com", "custom": {"tier": tier}})
            print(f"    tier={tier:12s} -> {'ON' if val else 'OFF'}  ** FLIPPED **")
        else:
            print(f"    tier={tier:12s} -> {'ON' if val else 'OFF'}")

    # Phase 5: Test country codes
    print(f"\n  -- Phase 5: Country Codes --")
    for cc in country_codes:
        props = {"userID": "mapper-country", "email": "test@gmail.com",
                 "country": cc, "custom": {}}
        gates = _fetch_gates(props)
        val = gates.get(gate_name)
        tested += 1
        if val != baseline_val:
            triggers.append({"email_domain": "gmail.com", "country": cc, "custom": {}})
            print(f"    country={cc:5s} -> {'ON' if val else 'OFF'}  ** FLIPPED **")
        else:
            print(f"    country={cc:5s} -> {'ON' if val else 'OFF'}")

    # Phase 6: Combination test — sesame.com + isStaff (strongest combo)
    print(f"\n  -- Phase 6: Combination (sesame.com + isStaff + admin) --")
    combo_props = {"userID": "mapper-combo", "email": "test@sesame.com",
                   "custom": {"isStaff": True, "role": "admin", "tier": "enterprise"}}
    combo_gates = _fetch_gates(combo_props)
    combo_val = combo_gates.get(gate_name)
    tested += 1
    if combo_val != baseline_val:
        triggers.append({"email_domain": "sesame.com",
                         "custom": {"isStaff": True, "role": "admin", "tier": "enterprise"}})
        print(f"    full combo -> {'ON' if combo_val else 'OFF'}  ** FLIPPED **")
    else:
        print(f"    full combo -> {'ON' if combo_val else 'OFF'}")

    # Summary
    print(f"\n  Summary: tested {tested} combinations, {len(triggers)} triggered a flip")
    if triggers:
        print(f"  Trigger conditions:")
        for t in triggers:
            parts = []
            if t.get("email_domain"):
                parts.append(f"email=@{t['email_domain']}")
            if t.get("country"):
                parts.append(f"country={t['country']}")
            custom = t.get("custom", {})
            for k, v in custom.items():
                parts.append(f"{k}={v}")
            print(f"    {' + '.join(parts) if parts else '(baseline change)'}")

    return {
        "gate_name": gate_name,
        "baseline": baseline_val,
        "triggers": triggers,
        "tested": tested,
        "summary": f"{len(triggers)}/{tested} combos flipped the gate",
    }


# ──── Call Info & Upload URL ────────────────────────────────────────────────
# v1.50.0 [2026-03-25] — Generate presigned upload URLs for call assets

def generate_call_upload_url(call_id: str, tokens: TokenStore) -> Dict:
    """Generate a presigned upload URL for a given call ID.

    Uses the Sesame API endpoint discovered via ARGUS to request an upload
    URL for call assets (logs, recordings).

    Args:
        call_id: The numeric call ID (e.g. "23166670").
        tokens: TokenStore with a valid Firebase JWT.

    Returns:
        Dict with upload_url, call_id, and status.

    CONNECTS: Sesame API (generate-call-file-upload-url)
    CALLED BY: run_interactive (call-info command)
    """
    print(f"\n  Call Info for ID: {call_id}\n")

    if not tokens.token:
        print("  [!] No auth token — cannot generate upload URL")
        return {"error": "no_token"}

    headers = {
        "Authorization": f"Bearer {tokens.token}",
        "Content-Type": "application/json",
    }

    # Request a presigned upload URL
    url = f"{SESAME_API_URL}/api/generate-call-file-upload-url"
    payload = {"call_id": int(call_id), "file_type": "client_logs.json"}
    result = _post(url, payload, headers)

    print(f"  Status: {result.get('status')}")
    if result.get("status") == 200:
        data = result.get("data", {})
        upload_url = data.get("upload_url", data.get("url", ""))
        if upload_url:
            print(f"  Upload URL: {upload_url[:120]}...")
            # Parse bucket/path from the upload URL
            if "storage.googleapis.com" in upload_url:
                parts = upload_url.split("storage.googleapis.com/")[1].split("?")[0] if "storage.googleapis.com/" in upload_url else ""
                print(f"  Bucket path: {parts}")
        else:
            print(f"  Response: {json.dumps(data)[:200]}")
        return {"call_id": call_id, "upload_url": upload_url, "status": "ok"}
    else:
        err = result.get("error", result.get("data", ""))
        print(f"  Error: {str(err)[:200]}")
        return {"call_id": call_id, "error": str(err)[:200], "status": "failed"}


# ──── API Spec Export ───────────────────────────────────────────────────────
# v1.50.0 [2026-03-25] — Export all discoveries as structured JSON API spec

def export_api_spec(tokens: TokenStore) -> Dict:
    """Export everything discovered as a structured API specification.

    Aggregates all known endpoints, auth schemes, feature flags, dynamic
    configs, WebSocket protocol, and bucket assets into a single JSON file
    saved to data/argus/reports/sesame_api_spec.json.

    Args:
        tokens: TokenStore for fetching live flag/config data.

    Returns:
        The full API spec dict.

    CONNECTS: All exploration modules
    CALLED BY: run_interactive (export command), CLI
    EMITS: data/argus/reports/sesame_api_spec.json
    """
    print("\n=== EXPORTING API SPECIFICATION ===\n")

    # Fetch live feature flags and configs
    url = f"{STATSIG_URL}/initialize?k={STATSIG_CLIENT_KEY}&st=javascript-client&sv=3.2"
    payload = {
        "user": {"userID": tokens.user_id or "anon", "email": tokens.email or "export@gmail.com",
                 "custom": {"isStaff": True}},
        "statsigMetadata": {"sdkType": "js-client", "sdkVersion": "3.2.0"},
    }
    live = _post(url, payload)
    live_data = live.get("data", {}) if live.get("status") == 200 else {}

    gates_raw = live_data.get("feature_gates", {})
    configs_raw = live_data.get("dynamic_configs", {})
    layers_raw = live_data.get("layer_configs", {})

    gates_spec = {}
    for name, gate in gates_raw.items():
        gates_spec[name] = {
            "enabled": bool(gate.get("value")),
            "rule_id": gate.get("rule_id", "default"),
        }

    configs_spec = {}
    for name, cfg in configs_raw.items():
        configs_spec[name] = {
            "value": cfg.get("value", {}),
            "rule_id": cfg.get("rule_id", "default"),
        }

    spec = {
        "_meta": {
            "generated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "generator": "sesame_client.py v1.50.0",
            "source": "ARGUS HAR analysis + live probing",
        },
        "base_urls": {
            "app": SESAME_APP_URL,
            "api": SESAME_API_URL,
            "websocket": SESAME_WS_URL,
            "firebase_auth": FIREBASE_AUTH_URL,
            "statsig": STATSIG_URL,
            "gcs_public": f"https://storage.googleapis.com/{GCS_PUBLIC_BUCKET}",
            "gcs_prod": f"https://storage.googleapis.com/{GCS_PROD_BUCKET}",
        },
        "auth": {
            "firebase": {
                "project": FIREBASE_PROJECT,
                "api_key": FIREBASE_API_KEY,
                "token_type": "Bearer JWT (RS256, 1hr expiry)",
                "refresh_endpoint": f"{FIREBASE_SECURETOKEN_URL}?key={FIREBASE_API_KEY}",
                "sign_in_providers": ["google.com"],
            },
            "statsig": {
                "client_key": STATSIG_CLIENT_KEY,
                "sdk_type": "js-client",
                "sdk_version": "3.2.0",
            },
        },
        "endpoints": {
            "user_profile": {
                "method": "GET",
                "url": f"{SESAME_APP_URL}/api/user",
                "auth": "Bearer JWT",
                "description": "Fetch authenticated user profile",
            },
            "generate_upload_url": {
                "method": "POST",
                "url": f"{SESAME_API_URL}/api/generate-call-file-upload-url",
                "auth": "Bearer JWT",
                "body": {"call_id": "int", "file_type": "string"},
                "description": "Generate presigned GCS upload URL for call assets",
            },
            "agent_websocket": {
                "method": "WSS",
                "url": SESAME_WS_URL,
                "auth": "JWT in query string (id_token=...)",
                "description": "Voice agent WebSocket connection",
            },
            "firebase_sign_in": {
                "method": "POST",
                "url": f"{FIREBASE_AUTH_URL}/accounts:signInWithIdp?key={FIREBASE_API_KEY}",
                "auth": "API key",
                "description": "Google OAuth sign-in via Firebase",
            },
            "firebase_lookup": {
                "method": "POST",
                "url": f"{FIREBASE_AUTH_URL}/accounts:lookup?key={FIREBASE_API_KEY}",
                "auth": "API key + idToken in body",
                "description": "Look up account details",
            },
            "statsig_initialize": {
                "method": "POST",
                "url": f"{STATSIG_URL}/initialize?k={STATSIG_CLIENT_KEY}",
                "auth": "Client key in query string",
                "description": "Initialize feature flags and configs",
            },
        },
        "feature_gates": gates_spec,
        "dynamic_configs": configs_spec,
        "layer_configs": {name: {"rule_id": lc.get("rule_id", "default")}
                         for name, lc in layers_raw.items()},
        "websocket_protocol": {
            "connection": f"{SESAME_WS_URL}?id_token=<JWT>",
            "client_messages": {
                "client_location_state": {"fields": ["latitude", "longitude", "address", "timezone"]},
                "webrtc_sdp_offer": {"fields": ["sdp", "sample_rate"]},
                "webrtc_ice_candidate": {"fields": ["sdp", "sdp_mid", "sdp_m_line_index"]},
                "call_connect": {"fields": ["sample_rate", "audio_codec", "reconnect",
                                             "is_private", "settings", "client_name",
                                             "client_metadata"]},
                "call_disconnect": {"fields": []},
                "ping": {"fields": [], "note": "keepalive ~500ms interval"},
            },
            "server_messages": {
                "initialize": {"fields": ["session_id", "webrtc_ice_servers"]},
                "webrtc_config": {"fields": ["ice_servers"]},
                "webrtc_sdp_answer": {"fields": ["sdp"]},
                "chat": {"fields": ["messages"]},
                "call_connect_response": {"fields": ["call_id"]},
                "call_disconnect_response": {"fields": []},
                "ping_response": {"fields": []},
            },
            "characters": ["Maya", "Miles"],
            "audio": {"sample_rate": 44100, "codec": "none (raw WebRTC Opus)"},
            "webrtc": {
                "stun": "stun:34.134.236.52:3478",
                "turn": "turn:34.134.236.52:3478 (UDP + TCP)",
                "credentials": "time-limited (1hr, tied to user+session)",
            },
        },
        "public_assets": {
            "bucket": GCS_PUBLIC_BUCKET,
            "known_objects": [
                "images/laptop_sesame_app_background.jpg",
                "images/sesame_text.png",
                "images/maya_text.png",
                "images/miles_text.png",
                "audio/set_14_12_connect_07.mp3",
                "audio/set_14_12_disconnect.mp3",
            ],
        },
        "analytics": {
            "rudderstack_data_plane": "sesameaihzfjvw.dataplane.rudderstack.com",
            "events": ["track", "identify"],
        },
    }

    # Save to disk
    out_path = _ROOT / "data" / "argus" / "reports" / "sesame_api_spec.json"
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(spec, indent=2, default=str), encoding="utf-8")
    print(f"  [+] Saved to {out_path}")
    print(f"  [+] {len(gates_spec)} feature gates, {len(configs_spec)} configs, "
          f"{len(spec['endpoints'])} endpoints")

    return spec


# ──── Interactive REPL ──────────────────────────────────────────────────────
# v1.50.0 [2026-03-25] — Full interactive exploration shell with session state

class _ReplState:
    """Mutable session state for the interactive REPL.

    Tracks the current email, user ID, custom properties, cached gate
    values, and HAR path so commands can mutate state and observe diffs.
    """

    def __init__(self, tokens: TokenStore, har_path: Optional[Path] = None) -> None:
        self.tokens = tokens
        self.har_path = har_path
        self.email: str = tokens.email or "user@gmail.com"
        self.user_id: str = tokens.user_id or "repl-user"
        self.custom: Dict[str, Any] = {}
        self._cached_gates: Dict[str, bool] = {}

    def user_props(self) -> Dict:
        """Build Statsig user properties from current session state."""
        return {
            "userID": self.user_id,
            "email": self.email,
            "custom": copy.deepcopy(self.custom),
        }

    def fetch_gates(self) -> Dict[str, bool]:
        """Fetch gates for current user props and cache them."""
        return _fetch_gates(self.user_props())

    def fetch_and_diff(self) -> tuple:
        """Fetch gates and compute diff against cached values.

        Returns:
            (new_gates, flipped) where flipped is a dict of
            gate_name -> (old_val, new_val) for gates that changed.
        """
        new_gates = self.fetch_gates()
        flipped = {}
        for name, val in new_gates.items():
            old_val = self._cached_gates.get(name)
            if old_val is not None and old_val != val:
                flipped[name] = (old_val, val)
        self._cached_gates = new_gates
        return new_gates, flipped

    def show_diff(self, flipped: Dict[str, tuple]) -> None:
        """Print gate diff in a readable format."""
        if not flipped:
            print("  No gates changed.")
        else:
            print(f"  {len(flipped)} gate(s) flipped:")
            for name, (old, new) in sorted(flipped.items()):
                old_s = "ON " if old else "OFF"
                new_s = "ON " if new else "OFF"
                print(f"    {name}: {old_s} -> {new_s}")


_REPL_HELP = """
  Available commands:

  SESSION:
    status                 Show token status, session, profile summary
    refresh                Refresh Firebase JWT (auto if expired)
    connect [character]    Connect to voice agent WebSocket (Maya/Miles)
    health                 Check API + agent service health

  PROFILE:
    profile                Fetch full user profile
    set-nickname <name>    Update nickname
    set-birthday <date>    Update birthday (YYYY-MM-DD)
    set-training <on|off>  Toggle training data consent
    set-news <on|off>      Toggle product news emails

  FLAGS:
    flags                  List all feature flags for current user
    employee-flags         Get flags as @sesame.com employee (19/27)
    compare                Compare normal vs employee gate counts
    toggle <gate_name>     Map what triggers a specific gate
    set-email <email>      Override email for flag testing
    set-user <user_id>     Change user ID for flag testing
    set <key> <value>      Set custom user property
    unset <key>            Remove custom user property
    props                  Show current user properties

  EXPLORE:
    configs                Show all dynamic configs
    config <name>          Show specific dynamic config
    domains                Test email domains for flag differences
    agents                 Probe agent service instances
    bucket                 Explore public GCS bucket
    endpoints              List all discovered endpoints
    protocol               Show WebSocket agent protocol spec
    call-info <call_id>    Generate upload URL for a call ID
    export                 Export full API spec to JSON

  META:
    help                   Show this help message
    exit / quit            Exit the REPL
"""


def run_interactive(tokens: TokenStore, har_path: Optional[Path] = None) -> None:
    """Interactive REPL for exploring Sesame AI APIs.

    Maintains session state (email, user_id, custom properties) and shows
    diffs when properties change. Supports all exploration commands plus
    gate toggle simulation and token refresh.

    Args:
        tokens: TokenStore with (optionally) loaded Firebase JWT.
        har_path: Path to HAR file for token refresh.

    CONNECTS: All exploration modules, _ReplState, TokenStore
    CALLED BY: main() when command is "interactive" or no args
    """
    state = _ReplState(tokens, har_path)

    # v1.52.0 — Auto-load refresh token and refresh if expired
    if har_path and tokens.is_expired:
        print("  [*] Token expired — attempting auto-refresh...")
        if tokens.load_refresh_token_from_har(har_path):
            if tokens.refresh():
                state.email = tokens.email
                state.user_id = tokens.user_id
        else:
            print("  [!] No refresh token in HAR — some commands will fail")
    elif har_path and not hasattr(tokens, "_refresh_token"):
        tokens.load_refresh_token_from_har(har_path)

    print("\n" + "=" * 60)
    print("  SESAME INTERACTIVE EXPLORER v1.52")
    print("  Type 'help' for commands, 'exit' to quit")
    print("=" * 60)
    print(f"  Token:  {tokens.status()}")
    print(f"  Email:  {state.email}")
    print(f"  UserID: {state.user_id}")
    print()

    # Pre-cache gates so first diff is meaningful
    print("  [*] Caching baseline gates...")
    state._cached_gates = state.fetch_gates()
    gate_count = len(state._cached_gates)
    enabled_count = sum(1 for v in state._cached_gates.values() if v)
    print(f"  [+] {enabled_count}/{gate_count} gates enabled\n")

    while True:
        try:
            raw = input("sesame> ").strip()
        except (EOFError, KeyboardInterrupt):
            print("\n  Goodbye.")
            break

        if not raw:
            continue

        # Parse command — handle quoted arguments
        try:
            parts = shlex.split(raw)
        except ValueError:
            parts = raw.split()

        cmd = parts[0].lower()
        args = parts[1:]

        try:
            # ── help ──
            if cmd == "help":
                print(_REPL_HELP)

            # ── exit / quit ──
            elif cmd in ("exit", "quit"):
                print("  Goodbye.")
                break

            # ── flags ──
            elif cmd == "flags":
                gates, flipped = state.fetch_and_diff()
                if flipped:
                    state.show_diff(flipped)
                    print()
                enabled = {k: v for k, v in gates.items() if v}
                disabled = {k: v for k, v in gates.items() if not v}
                print(f"  Feature Gates: {len(gates)} total, {len(enabled)} enabled, {len(disabled)} disabled")
                print()
                for name in sorted(gates.keys()):
                    val = "ON " if gates[name] else "OFF"
                    print(f"    [{val}] {name}")

            # ── toggle <gate_name> ──
            elif cmd == "toggle":
                if not args:
                    print("  Usage: toggle <gate_name>")
                    print("  Tip: use 'flags' first to see available gate names")
                else:
                    gate_name = args[0]
                    result = map_gate_triggers(gate_name)
                    if result.get("triggers"):
                        print(f"\n  Result stored. {len(result['triggers'])} trigger(s) found.")

            # ── set-email <email> ──
            elif cmd == "set-email":
                if not args:
                    print("  Usage: set-email user@domain.com")
                else:
                    old_email = state.email
                    state.email = args[0]
                    print(f"  Email: {old_email} -> {state.email}")
                    _, flipped = state.fetch_and_diff()
                    state.show_diff(flipped)

            # ── set-user <user_id> ──
            elif cmd == "set-user":
                if not args:
                    print("  Usage: set-user <user_id>")
                else:
                    old_uid = state.user_id
                    state.user_id = args[0]
                    print(f"  UserID: {old_uid} -> {state.user_id}")
                    _, flipped = state.fetch_and_diff()
                    state.show_diff(flipped)

            # ── set <key> <value> ──
            elif cmd == "set":
                if len(args) < 2:
                    print("  Usage: set <key> <value>")
                    print("  Examples: set isStaff true | set role admin | set tier pro")
                else:
                    key = args[0]
                    raw_val = " ".join(args[1:])
                    # Parse booleans and numbers
                    if raw_val.lower() == "true":
                        val: Any = True
                    elif raw_val.lower() == "false":
                        val = False
                    elif raw_val.isdigit():
                        val = int(raw_val)
                    else:
                        val = raw_val

                    old_val = state.custom.get(key, "<unset>")
                    state.custom[key] = val
                    print(f"  custom.{key}: {old_val} -> {val}")
                    _, flipped = state.fetch_and_diff()
                    state.show_diff(flipped)

            # ── unset <key> ──
            elif cmd == "unset":
                if not args:
                    print("  Usage: unset <key>")
                else:
                    key = args[0]
                    if key in state.custom:
                        old_val = state.custom.pop(key)
                        print(f"  Removed custom.{key} (was {old_val})")
                        _, flipped = state.fetch_and_diff()
                        state.show_diff(flipped)
                    else:
                        print(f"  custom.{key} not set")

            # ── props ──
            elif cmd == "props":
                print(f"  Email:  {state.email}")
                print(f"  UserID: {state.user_id}")
                print(f"  Custom properties:")
                if state.custom:
                    for k, v in sorted(state.custom.items()):
                        print(f"    {k} = {v}")
                else:
                    print("    (none)")

            # ── configs ──
            elif cmd == "configs":
                explore_dynamic_configs(tokens)

            # ── config <name> [value] ──
            elif cmd == "config":
                if not args:
                    print("  Usage: config <name_filter> [value_filter]")
                    print("  Shows dynamic configs matching the name filter")
                else:
                    name_filter = args[0].lower()
                    value_filter = args[1].lower() if len(args) > 1 else None

                    statsig_url = f"{STATSIG_URL}/initialize?k={STATSIG_CLIENT_KEY}&st=javascript-client&sv=3.2"
                    r = _post(statsig_url, {
                        "user": state.user_props(),
                        "statsigMetadata": {"sdkType": "js-client", "sdkVersion": "3.2.0"},
                    })
                    if r.get("status") != 200:
                        print(f"  [!] Statsig returned {r.get('status')}")
                    else:
                        configs = r.get("data", {}).get("dynamic_configs", {})
                        matched = {k: v for k, v in configs.items()
                                   if name_filter in k.lower()}
                        if not matched:
                            print(f"  No configs matching '{name_filter}'")
                        else:
                            for name, cfg in sorted(matched.items()):
                                val = cfg.get("value", {})
                                rule = cfg.get("rule_id", "default")
                                print(f"  Config: {name}  (rule={rule})")
                                if isinstance(val, dict):
                                    for k, v in val.items():
                                        v_str = json.dumps(v)
                                        if value_filter and value_filter not in v_str.lower() and value_filter not in k.lower():
                                            continue
                                        print(f"    {k:35s} = {v_str[:80]}")
                                else:
                                    print(f"    value = {json.dumps(val)[:120]}")
                                print()

            # ── user ──
            elif cmd == "user":
                explore_user_profile(tokens)

            # ── call-info <call_id> ──
            elif cmd == "call-info":
                if not args:
                    print("  Usage: call-info <call_id>")
                    print("  Example: call-info 23166670")
                else:
                    generate_call_upload_url(args[0], tokens)

            # ── refresh-token ──
            elif cmd == "refresh-token":
                if not state.har_path:
                    print("  [!] No HAR file loaded — cannot refresh token")
                    print("  Start with: python -m scripts.argus.clients.sesame_client interactive --har <path>")
                else:
                    new_token = refresh_firebase_token(state.har_path)
                    if new_token:
                        tokens._set_token(new_token)
                        state.email = tokens.email
                        state.user_id = tokens.user_id
                        print(f"  [+] Token refreshed: {tokens.status()}")
                        _, flipped = state.fetch_and_diff()
                        if flipped:
                            print(f"  [!] Gate changes after token refresh:")
                            state.show_diff(flipped)
                    else:
                        print("  [!] Token refresh failed")

            # ── export ──
            elif cmd == "export":
                export_api_spec(tokens)

            # ── domains ──
            elif cmd == "domains":
                explore_email_domains(tokens)

            # ── agents ──
            elif cmd == "agents":
                explore_agent_services(tokens)

            # ── bucket ──
            elif cmd == "bucket":
                explore_public_bucket()

            # ── endpoints ──
            elif cmd == "endpoints":
                list_endpoints()

            # ── protocol ──
            elif cmd == "protocol":
                show_websocket_protocol()

            # v1.52.0 — New session/profile/connect commands

            # ── status ──
            elif cmd == "status":
                print(f"  Token:     {tokens.status()}")
                print(f"  Email:     {state.email}")
                print(f"  UserID:    {state.user_id}")
                print(f"  Custom:    {state.custom or '(none)'}")
                client = SesameClient(tokens)
                profile = client.get_profile()
                if profile:
                    print(f"  Nickname:  {profile.get('nickname', '?')}")
                    print(f"  Roles:     {', '.join(profile.get('roles', []))}")
                    print(f"  Moderation:{profile.get('moderation_status', '?')}")
                    print(f"  Training:  {profile.get('allow_training_from_calls', '?')}")
                    print(f"  News:      {profile.get('prefer_product_news_emails', '?')}")
                else:
                    print(f"  Profile:   (failed to fetch)")

            # ── refresh ──
            elif cmd == "refresh":
                if hasattr(tokens, "_refresh_token") and tokens._refresh_token:
                    tokens.refresh()
                    state.email = tokens.email
                    state.user_id = tokens.user_id
                elif state.har_path:
                    tokens.load_refresh_token_from_har(state.har_path)
                    tokens.refresh()
                    state.email = tokens.email
                    state.user_id = tokens.user_id
                else:
                    print("  [!] No refresh token or HAR available")

            # ── connect [character] ──
            elif cmd == "connect":
                character = args[0] if args else "Maya"
                print(f"  Connecting to {character}...")
                client = SesameClient(tokens)
                result = client.connect_agent(character=character)
                if result.get("connected"):
                    print(f"  [OK] Session: {result.get('session_id')}")
                    print(f"  ICE servers: {result.get('ice_servers', '?')}")
                    for msg in result.get("messages", []):
                        print(f"  [{msg['type']}] {msg['preview'][:100]}")
                    print(f"  Status: {result.get('status', '?')}")
                else:
                    print(f"  [!] {result.get('error', 'Connection failed')}")

            # ── health ──
            elif cmd == "health":
                client = SesameClient(tokens)
                h = client.health()
                for svc, code in h.items():
                    status = "UP" if code == 200 else f"DOWN ({code})"
                    print(f"  {svc:15s} {status}")

            # ── profile ──
            elif cmd == "profile":
                client = SesameClient(tokens)
                profile = client.get_profile()
                if profile:
                    print(json.dumps(profile, indent=2))
                else:
                    print("  [!] Failed to fetch profile (token expired?)")

            # ── set-nickname <name> ──
            elif cmd == "set-nickname":
                if not args:
                    print("  Usage: set-nickname <name>")
                else:
                    client = SesameClient(tokens)
                    result = client.update_profile(nickname=" ".join(args))
                    if result:
                        print(f"  Nickname: {result.get('nickname')}")

            # ── set-birthday <date> ──
            elif cmd == "set-birthday":
                if not args:
                    print("  Usage: set-birthday YYYY-MM-DD")
                else:
                    client = SesameClient(tokens)
                    result = client.update_profile(birthday=f"{args[0]}T00:00:00")
                    if result:
                        print(f"  Birthday: {result.get('birthday')}")

            # ── set-training <on|off> ──
            elif cmd == "set-training":
                if not args:
                    print("  Usage: set-training on|off")
                else:
                    val = args[0].lower() in ("on", "true", "yes", "1")
                    client = SesameClient(tokens)
                    result = client.update_profile(allow_training_from_calls=val)
                    if result:
                        print(f"  Training: {result.get('allow_training_from_calls')}")

            # ── set-news <on|off> ──
            elif cmd == "set-news":
                if not args:
                    print("  Usage: set-news on|off")
                else:
                    val = args[0].lower() in ("on", "true", "yes", "1")
                    client = SesameClient(tokens)
                    result = client.update_profile(prefer_product_news_emails=val)
                    if result:
                        print(f"  News: {result.get('prefer_product_news_emails')}")

            # ── employee-flags ──
            elif cmd == "employee-flags":
                client = SesameClient(tokens)
                flags = client.get_employee_flags()
                gates = flags.get("feature_gates", {})
                enabled = sum(1 for g in gates.values() if g.get("value"))
                print(f"  Employee gates (@sesame.com): {enabled}/{len(gates)}")
                for name, gate in sorted(gates.items()):
                    val = "ON " if gate.get("value") else "OFF"
                    print(f"    [{val}] {name[:50]}")

            # ── compare ──
            elif cmd == "compare":
                client = SesameClient(tokens)
                diff = client.compare_flags()
                print(f"  Normal:   {diff['normal_gates']}/{diff['total']} gates")
                print(f"  Employee: {diff['employee_gates']}/{diff['total']} gates")
                print(f"  Extra:    +{diff['extra_count']} employee-only gates")
                if diff["extra_gates"]:
                    print()
                    for g in diff["extra_gates"]:
                        print(f"    [+] {g[:50]}")

            # ── unknown ──
            else:
                print(f"  Unknown command: {cmd}")
                print("  Type 'help' for available commands")

        except Exception as exc:
            print(f"  [!] Error: {exc}")
            traceback.print_exc()

        print()  # blank line between commands


def show_websocket_protocol() -> None:
    """Show the discovered WebSocket agent protocol specification."""
    print("\n=== SESAME AGENT WEBSOCKET PROTOCOL ===\n")

    print("  Connection: wss://sesameai.app/agent-service-0/v1/connect?id_token=<JWT>")
    print("  Auth: Firebase JWT in query string (RS256, 1hr expiry)")
    print()
    print("  -- Message Types (13) --")
    print()
    print("  CLIENT -> SERVER:")
    print("    client_location_state    {latitude, longitude, address, timezone}")
    print("    webrtc_sdp_offer         {sdp, sample_rate}")
    print("    webrtc_ice_candidate     {sdp, sdp_mid, sdp_m_line_index}")
    print("    call_connect             {sample_rate, audio_codec, reconnect,")
    print("                              is_private, settings: {character: 'Maya'},")
    print("                              client_name, client_metadata}")
    print("    call_disconnect          {}")
    print("    ping                     {} (keepalive, ~1788/session)")
    print()
    print("  SERVER -> CLIENT:")
    print("    initialize               {session_id, webrtc_ice_servers}")
    print("    webrtc_config            {ice_servers: [{urls, username, credential}]}")
    print("    webrtc_sdp_answer        {sdp}")
    print("    chat                     {messages: []}")
    print("    call_connect_response    {call_id: number}")
    print("    call_disconnect_response {}")
    print("    ping_response            {}")
    print()
    print("  -- Connection Flow --")
    print("    1. Client connects via WebSocket with JWT")
    print("    2. Server sends 'initialize' with session_id")
    print("    3. Client sends 'client_location_state' (timezone)")
    print("    4. Server sends 'webrtc_config' with TURN/STUN servers")
    print("    5. Client sends 'webrtc_sdp_offer' (44100Hz)")
    print("    6. Client sends 'call_connect' with character selection")
    print("    7. WebRTC ICE negotiation (9 candidates)")
    print("    8. Server sends 'webrtc_sdp_answer'")
    print("    9. Audio streaming via WebRTC data channel")
    print("   10. Ping/pong keepalive every ~500ms")
    print("   11. Client sends 'call_disconnect' to end")
    print()
    print("  -- Characters Available --")
    print("    Maya, Miles (discovered from call_connect payloads)")
    print()
    print("  -- WebRTC Config --")
    print("    STUN: stun:34.134.236.52:3478")
    print("    TURN: turn:34.134.236.52:3478 (UDP + TCP)")
    print("    Credentials: time-limited (1hr, tied to user+session)")
    print()
    print("  -- Audio --")
    print("    Sample rate: 44100 Hz")
    print("    Codec: 'none' (raw WebRTC Opus)")


def list_endpoints() -> None:
    """List all discovered endpoints from ARGUS analysis."""
    print("\n=== DISCOVERED API ENDPOINTS ===\n")

    endpoints = {
        "Sesame Core": [
            ("GET", "/api/user", "User profile"),
            ("POST", "sesameai.app/api/generate-call-file-upload-url", "Presigned upload URL"),
            ("WSS", "sesameai.app/agent-service-0/v1/connect", "Voice agent WebSocket"),
        ],
        "Firebase Auth": [
            ("POST", "identitytoolkit.googleapis.com/v1/accounts:signInWithIdp", "Google OAuth"),
            ("POST", "identitytoolkit.googleapis.com/v1/accounts:lookup", "Account lookup"),
            ("GET", "identitytoolkit.googleapis.com/v1/projects", "Project config"),
        ],
        "Firebase App Check": [
            ("POST", f"firebaseappcheck.googleapis.com/v1/projects/{FIREBASE_PROJECT}/apps/.../exchangeRecaptchaEnterpriseToken", "Token exchange"),
        ],
        "Feature Flags (Statsig)": [
            ("POST", f"featureassets.org/v1/initialize?k={STATSIG_CLIENT_KEY[:20]}...", "Get all flags"),
        ],
        "Cloud Storage": [
            ("GET", f"storage.googleapis.com/{GCS_PUBLIC_BUCKET}/*", "Public assets (NO AUTH)"),
            ("PUT", f"storage.googleapis.com/{GCS_PROD_BUCKET}/calls/*/client_logs.json", "Call log upload (presigned)"),
        ],
        "Analytics": [
            ("POST", "sesameaihzfjvw.dataplane.rudderstack.com/v1/track", "Event tracking"),
            ("POST", "sesameaihzfjvw.dataplane.rudderstack.com/v1/identify", "User identify"),
        ],
    }

    for group, eps in endpoints.items():
        print(f"  {group}:")
        for method, path, desc in eps:
            print(f"    {method:6s} {path[:65]:65s} {desc}")
        print()


# ──── Main ───────────────────────────────────────────────────────────────────

def main() -> None:
    parser = argparse.ArgumentParser(
        description="Sesame AI Explorer — built from ARGUS intelligence",
    )
    parser.add_argument("command", nargs="?", default="menu",
                        choices=["menu", "interactive", "flags", "user", "bucket",
                                 "endpoints", "staff", "agents", "firebase", "domains",
                                 "configs", "protocol", "export", "full"])
    parser.add_argument("--har", type=Path, help="Path to Sesame HAR file for auth tokens")
    args = parser.parse_args()

    # Auto-find HAR
    har_path = args.har
    if not har_path:
        candidates = sorted(Path("C:/Files/Models/HARS/Sesame").glob("*.har"), reverse=True)
        if candidates:
            har_path = candidates[0]

    # Load tokens
    tokens = TokenStore()
    if har_path and har_path.exists():
        tokens.load_from_har(har_path)

    print()
    print("=" * 60)
    print("  SESAME AI EXPLORER")
    print("  Built from ARGUS HAR Intelligence")
    print("=" * 60)
    print(f"  Token: {tokens.status()}")
    print(f"  HAR:   {har_path}")
    print()

    if args.command == "menu":
        print("  Commands:")
        print("    interactive  Interactive REPL with session state + diffs")
        print("    flags        Enumerate Statsig feature flags + test staff")
        print("    domains      Test email domains for flag differences")
        print("    configs      Show all dynamic configs with values")
        print("    user         Fetch user profile (roles, moderation)")
        print("    bucket       Explore public GCS bucket")
        print("    endpoints    List all discovered endpoints")
        print("    agents       Probe agent service instances (0-4)")
        print("    firebase     Firebase project config")
        print("    protocol     Show WebSocket agent protocol spec")
        print("    export       Export full API spec to JSON")
        print("    full         Run everything")
        print()
        print("  Usage: python -m scripts.argus.clients.sesame_client <command>")
        return

    if args.command == "interactive":
        run_interactive(tokens, har_path)
        return

    if args.command == "endpoints":
        list_endpoints()
    elif args.command == "flags" or args.command == "staff":
        explore_feature_flags(tokens)
    elif args.command == "domains":
        explore_email_domains(tokens)
    elif args.command == "configs":
        explore_dynamic_configs(tokens)
    elif args.command == "user":
        explore_user_profile(tokens)
    elif args.command == "bucket":
        explore_public_bucket()
    elif args.command == "agents":
        explore_agent_services(tokens)
    elif args.command == "firebase":
        explore_firebase_config()
    elif args.command == "protocol":
        show_websocket_protocol()
    elif args.command == "export":
        export_api_spec(tokens)
    elif args.command == "full":
        list_endpoints()
        explore_firebase_config()
        explore_feature_flags(tokens)
        explore_email_domains(tokens)
        explore_dynamic_configs(tokens)
        explore_user_profile(tokens)
        explore_public_bucket()
        explore_agent_services(tokens)
        show_websocket_protocol()

    print()


if __name__ == "__main__":
    main()
