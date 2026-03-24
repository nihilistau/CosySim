#!/usr/bin/env python3
"""
Sesame AI Explorer — API Client built from ARGUS intelligence
===============================================================

Interactive CLI for exploring Sesame AI's API surface discovered via
ARGUS HAR analysis. Uses Firebase auth tokens from captured traffic.

Usage:
    python -m scripts.argus.clients.sesame_client              # Interactive menu
    python -m scripts.argus.clients.sesame_client flags         # List feature flags
    python -m scripts.argus.clients.sesame_client user          # User profile
    python -m scripts.argus.clients.sesame_client bucket        # Explore public bucket
    python -m scripts.argus.clients.sesame_client endpoints     # List all discovered endpoints
    python -m scripts.argus.clients.sesame_client staff         # Test staff flag
    python -m scripts.argus.clients.sesame_client agents        # Probe agent services
    python -m scripts.argus.clients.sesame_client full          # Run everything

Version: v1.50.0 [2026-03-25]
Author:  CosySim Team

CONNECTS: ARGUS HAR analyzer, Firebase Auth, Statsig, GCS
"""
from __future__ import annotations

import argparse
import base64
import json
import re
import sys
import time
from pathlib import Path
from typing import Any, Dict, List, Optional
from urllib.parse import urlencode

import requests

_ROOT = Path(__file__).resolve().parent.parent.parent.parent
sys.path.insert(0, str(_ROOT))


# ──── Constants from ARGUS Discovery ─────────────────────────────────────────

SESAME_APP_URL = "https://app.sesame.com"
SESAME_API_URL = "https://sesameai.app"
SESAME_WS_URL = "wss://sesameai.app/agent-service-0/v1/connect"

FIREBASE_PROJECT = "sesame-ai-demo"
FIREBASE_API_KEY = "AIzaSyDtC7Uwb5pGAsdmrH2T4Gqdk5Mga07jYPM"
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
                        choices=["menu", "flags", "user", "bucket", "endpoints",
                                 "staff", "agents", "firebase", "full"])
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
        print("    flags      Enumerate Statsig feature flags + test staff")
        print("    user       Fetch user profile")
        print("    bucket     Explore public GCS bucket")
        print("    endpoints  List all discovered endpoints")
        print("    agents     Probe agent service instances")
        print("    firebase   Firebase project config")
        print("    full       Run everything")
        print()
        print("  Usage: python -m scripts.argus.clients.sesame_client <command>")
        return

    if args.command == "endpoints":
        list_endpoints()
    elif args.command == "flags" or args.command == "staff":
        explore_feature_flags(tokens)
    elif args.command == "user":
        explore_user_profile(tokens)
    elif args.command == "bucket":
        explore_public_bucket()
    elif args.command == "agents":
        explore_agent_services(tokens)
    elif args.command == "firebase":
        explore_firebase_config()
    elif args.command == "full":
        list_endpoints()
        explore_firebase_config()
        explore_feature_flags(tokens)
        explore_user_profile(tokens)
        explore_public_bucket()
        explore_agent_services(tokens)

    print()


if __name__ == "__main__":
    main()
