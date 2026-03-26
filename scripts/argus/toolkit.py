"""
ARGUS Toolkit — Reusable techniques for web application analysis
================================================================

Generic tools for analyzing any web application:
- Bundle decompilation (download, extract enums, routes, env vars)
- Feature flag manipulation (Statsig/LaunchDarkly localStorage injection)
- CDP scripting (Chrome DevTools Protocol JS execution)
- WebSocket interception (message modification via CDP)
- Token management (Firebase JWT refresh)
- Deep heap mining (V8 heap snapshot credential extraction)
- Agent message stream extraction (multi-agent orchestration traces)
- Chain-of-thought extraction (leaked model reasoning)
- App schema extraction (tool definitions from YAML configs)

These tools are application-agnostic. Use them from any ARGUS client.

Version: v1.52.1 [2026-03-26]
Author:  CosySim Team

Change Log:
    v1.52.1 [2026-03-26] — Added agent message stream extraction, chain-of-thought
                            extraction, app schema extraction from heap strings
    v1.52.0 [2026-03-26] — Initial: bundle analysis, statsig injection,
                            CDP eval, WebSocket intercept, Firebase refresh

Usage:
    from scripts.argus.toolkit import (
        download_bundle, decompile_bundle,
        inject_statsig_gates, inject_websocket_intercept,
        cdp_eval, cdp_find_tab, refresh_firebase_token,
        extract_agent_messages, extract_chain_of_thought,
        extract_app_schemas, extract_protobuf_definitions,
    )
"""
from __future__ import annotations

import json
import logging
import re
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import requests

logger = logging.getLogger(__name__)


# ──── Bundle Decompilation ───────────────────────────────────────────────────

def download_bundle(url: str, output_dir: str = "data/argus/bundles") -> Path:
    """Download a JS bundle for analysis.

    Args:
        url: Full URL to the JS bundle.
        output_dir: Directory to save the bundle.

    Returns:
        Path to the downloaded file.
    """
    out = Path(output_dir)
    out.mkdir(parents=True, exist_ok=True)
    filename = url.split("/")[-1].split("?")[0]
    filepath = out / filename

    r = requests.get(url, timeout=30)
    r.raise_for_status()
    filepath.write_bytes(r.content)

    logger.info("[Toolkit] Downloaded %s (%d KB)", filename, len(r.content) // 1024)
    return filepath


def decompile_bundle(filepath: Path) -> Dict[str, Any]:
    """Extract intelligence from a minified JS bundle.

    Searches for: feature gate enums, dynamic config enums, API routes,
    environment variables, CI/CD paths, package references, model/character
    names, monitoring DSNs.

    Args:
        filepath: Path to the JS bundle file.

    Returns:
        Dict with extracted intelligence.
    """
    code = filepath.read_text(encoding="utf-8", errors="replace")
    result: Dict[str, Any] = {
        "file": str(filepath),
        "size_bytes": len(code),
    }

    # Feature gate enums: t.SOMETHING="something_value"
    gate_enums = re.findall(r't\.([A-Z_]{3,})="([a-z_]+)"', code)
    if gate_enums:
        result["gate_enums"] = {name: val for name, val in gate_enums}

    # API routes
    routes = re.findall(r'["\'`](/[a-z][a-zA-Z0-9_\-/]+)["\'`]', code)
    api_routes = sorted(set(r for r in routes if len(r) > 3 and not r.startswith("/node")))
    result["routes"] = api_routes
    result["route_count"] = len(api_routes)

    # Environment variables (Vite, Next.js, React)
    env_vars = re.findall(
        r'((?:VITE_|NEXT_PUBLIC_|REACT_APP_|process\.env\.)[A-Z_]+)', code
    )
    result["env_vars"] = sorted(set(env_vars))

    # CI/CD paths
    runner_paths = re.findall(r'/home/runner[^\s"\'`\]]+', code)
    if runner_paths:
        result["cicd_paths"] = sorted(set(runner_paths))

    # Sentry DSN
    sentry = re.findall(r'["\'](https://[a-f0-9]+@[^"\']+sentry[^"\']+)["\']', code)
    if sentry:
        result["sentry_dsn"] = list(set(sentry))

    # Google Analytics
    ga_ids = re.findall(r'G-[A-Z0-9]{8,}', code)
    if ga_ids:
        result["ga_ids"] = list(set(ga_ids))

    # Feature-like strings
    features = re.findall(
        r'["\'`]((?:enable|disable|show|hide|allow|block|is_|has_|can_|use_|'
        r'gate_|flag_|feature_|exp_)[a-z_]+)["\'`]',
        code, re.IGNORECASE,
    )
    result["feature_strings"] = sorted(set(features))

    # WebSocket URLs
    ws_urls = re.findall(r'["\'`](wss?://[^"\'`\s]+)["\'`]', code)
    if ws_urls:
        result["websocket_urls"] = list(set(ws_urls))

    # Character/model names (customize per app)
    models = re.findall(
        r'["\'`]([A-Z][a-z]+(?:-[A-Z][a-z]+)*(?:-(?:Alpha|Beta|Preview|Dev))?)["\'`]',
        code,
    )
    if models:
        result["model_names"] = sorted(set(m for m in models if len(m) > 2))

    # Package manager
    if "pnpm" in code:
        result["pkg_manager"] = "pnpm"
    elif "yarn" in code:
        result["pkg_manager"] = "yarn"
    elif "npm" in code:
        result["pkg_manager"] = "npm"

    # Build tool
    if "vite" in code.lower():
        vite_ver = re.findall(r'vite@([\d.]+)', code)
        result["build_tool"] = f"vite {vite_ver[0]}" if vite_ver else "vite"
    elif "webpack" in code.lower():
        result["build_tool"] = "webpack"

    return result


def find_bundle_urls_in_page(page_html: str) -> List[str]:
    """Extract JS bundle URLs from HTML page source."""
    scripts = re.findall(r'<script[^>]+src="([^"]+)"', page_html)
    return [s for s in scripts if any(x in s for x in ["index-", "chunk-", "app.", "main."])]


# ──── Feature Flag Manipulation ──────────────────────────────────────────────

def inject_statsig_gates(
    mode: str = "all",
    cdp_port: int = 9223,
    tab_filter: str = "",
) -> str:
    """Inject Statsig gate overrides into localStorage via CDP.

    Args:
        mode: "all" (flip everything ON), "normal" (clear caches)
        cdp_port: Chrome CDP port.
        tab_filter: Substring to match in tab URL.

    Returns:
        Result message.
    """
    if mode == "all":
        js = """
        (function() {
            const keys = Object.keys(localStorage).filter(k => k.includes('statsig.cached.evaluations'));
            let total = 0;
            for (const k of keys) {
                const outer = JSON.parse(localStorage.getItem(k));
                const inner = JSON.parse(outer.data);
                for (const gate of Object.values(inner.feature_gates || {})) {
                    if (!gate.value) { gate.value = true; gate.rule_id = 'argus'; total++; }
                }
                outer.data = JSON.stringify(inner);
                localStorage.setItem(k, JSON.stringify(outer));
            }
            return 'Flipped ' + total + ' gates across ' + keys.length + ' caches';
        })()
        """
    elif mode == "normal":
        js = """
        (function() {
            const keys = Object.keys(localStorage).filter(k => k.includes('statsig.cached.evaluations'));
            for (const k of keys) { localStorage.removeItem(k); }
            return 'Cleared ' + keys.length + ' Statsig caches';
        })()
        """
    else:
        return f"Unknown mode: {mode}"

    return cdp_eval(js, cdp_port=cdp_port, tab_filter=tab_filter) or "No response"


# ──── CDP Scripting ──────────────────────────────────────────────────────────

def cdp_eval(
    js_code: str,
    cdp_port: int = 9223,
    tab_filter: str = "",
) -> Optional[str]:
    """Execute JavaScript in a Chrome tab via CDP.

    Args:
        js_code: JavaScript expression to evaluate.
        cdp_port: Chrome DevTools Protocol port.
        tab_filter: Substring to match in tab URL. Empty = first tab.

    Returns:
        The result value as string, or None on error.
    """
    try:
        import websockets
        import asyncio

        async def _run():
            r = requests.get(f"http://localhost:{cdp_port}/json", timeout=3)
            tabs = r.json()

            if tab_filter:
                tab = next((t for t in tabs if tab_filter in t.get("url", "")), None)
            else:
                tab = tabs[0] if tabs else None

            if not tab:
                return f"No tab found (filter: {tab_filter})"

            ws_url = tab.get("webSocketDebuggerUrl")
            if not ws_url:
                return "No debugger URL"

            async with websockets.connect(ws_url) as ws:
                await ws.send(json.dumps({
                    "id": 1,
                    "method": "Runtime.evaluate",
                    "params": {"expression": js_code, "returnByValue": True},
                }))
                resp = json.loads(await asyncio.wait_for(ws.recv(), timeout=10))
                result = resp.get("result", {}).get("result", {})
                return result.get("value", json.dumps(result))

        return asyncio.run(_run())
    except Exception as exc:
        return f"CDP error: {exc}"


def cdp_find_tab(cdp_port: int = 9223, url_filter: str = "") -> Optional[Dict]:
    """Find a Chrome tab by URL substring."""
    try:
        r = requests.get(f"http://localhost:{cdp_port}/json", timeout=3)
        tabs = r.json()
        if url_filter:
            return next((t for t in tabs if url_filter in t.get("url", "")), None)
        return tabs[0] if tabs else None
    except Exception:
        return None


def cdp_inject_before_load(
    js_code: str,
    url: str,
    cdp_port: int = 9223,
) -> str:
    """Create a new tab with init script that runs before the page loads.

    Args:
        js_code: JavaScript to run on document start.
        url: URL to navigate to.
        cdp_port: Chrome CDP port.

    Returns:
        Result message.
    """
    try:
        import websockets
        import asyncio

        async def _run():
            r = requests.get(f"http://localhost:{cdp_port}/json/version", timeout=3)
            ws_url = r.json().get("webSocketDebuggerUrl")
            if not ws_url:
                return "No browser debugger URL"

            async with websockets.connect(ws_url) as ws:
                # Create tab
                await ws.send(json.dumps({
                    "id": 1, "method": "Target.createTarget",
                    "params": {"url": "about:blank"},
                }))
                resp = json.loads(await asyncio.wait_for(ws.recv(), timeout=5))
                target_id = resp.get("result", {}).get("targetId")
                if not target_id:
                    return "Failed to create tab"

                # Find tab's WS URL
                r2 = requests.get(f"http://localhost:{cdp_port}/json", timeout=3)
                tab_ws = None
                for tab in r2.json():
                    if tab.get("id") == target_id:
                        tab_ws = tab.get("webSocketDebuggerUrl")
                        break

                if not tab_ws:
                    return "Tab debugger URL not found"

                # Connect and inject
                async with websockets.connect(tab_ws) as tab:
                    await tab.send(json.dumps({
                        "id": 2, "method": "Page.addScriptToEvaluateOnNewDocument",
                        "params": {"source": js_code},
                    }))
                    await asyncio.wait_for(tab.recv(), timeout=5)

                    await tab.send(json.dumps({
                        "id": 3, "method": "Page.navigate",
                        "params": {"url": url},
                    }))
                    await asyncio.wait_for(tab.recv(), timeout=10)

                return f"Tab created with init script, navigating to {url}"

        return asyncio.run(_run())
    except Exception as exc:
        return f"CDP error: {exc}"


# ──── WebSocket Interception ─────────────────────────────────────────────────

def inject_websocket_intercept(
    field_path: str,
    new_value: str,
    message_type: str = "",
    cdp_port: int = 9223,
    tab_filter: str = "",
) -> str:
    """Inject a WebSocket send interceptor that modifies a field in outgoing messages.

    Args:
        field_path: Dot-notation path to the field (e.g., "settings.character").
        new_value: Value to set.
        message_type: Only intercept messages of this type (e.g., "call_connect").
        cdp_port: Chrome CDP port.
        tab_filter: Tab URL filter.

    Returns:
        Result message.
    """
    parts = field_path.split(".")
    # Build nested access: p.settings.character
    accessor = "p"
    for part in parts[:-1]:
        accessor += f'["{part}"]'
    final_key = parts[-1]

    type_check = f'p.type === "{message_type}" && ' if message_type else ""

    js = f"""
    (function() {{
        const _orig = WebSocket.prototype.send;
        WebSocket.prototype.send = function(data) {{
            if (typeof data === 'string') {{
                try {{
                    const p = JSON.parse(data);
                    if ({type_check}{accessor}) {{
                        const old = {accessor}["{final_key}"];
                        {accessor}["{final_key}"] = "{new_value}";
                        data = JSON.stringify(p);
                        console.log('[ARGUS] ' + old + ' -> {new_value}');
                    }}
                }} catch(e) {{}}
            }}
            return _orig.call(this, data);
        }};
        return 'WebSocket intercept active: {field_path} -> {new_value}';
    }})()
    """
    return cdp_eval(js, cdp_port=cdp_port, tab_filter=tab_filter) or "No response"


# ──── Firebase Token Management ──────────────────────────────────────────────

def refresh_firebase_token(
    refresh_token: str,
    api_key: str,
) -> Optional[Dict[str, str]]:
    """Exchange a Firebase refresh_token for a fresh id_token.

    Args:
        refresh_token: The Firebase refresh token.
        api_key: Firebase API key.

    Returns:
        Dict with id_token, refresh_token, expires_in, or None on failure.
    """
    try:
        r = requests.post(
            f"https://securetoken.googleapis.com/v1/token?key={api_key}",
            data={"grant_type": "refresh_token", "refresh_token": refresh_token},
            timeout=15,
        )
        if r.status_code == 200:
            data = r.json()
            return {
                "id_token": data.get("id_token", ""),
                "refresh_token": data.get("refresh_token", ""),
                "expires_in": data.get("expires_in", ""),
            }
        logger.warning("[Toolkit] Token refresh failed: %d %s", r.status_code, r.text[:100])
    except Exception as exc:
        logger.error("[Toolkit] Token refresh error: %s", exc)
    return None


def extract_refresh_token_from_har(har_path: Path) -> Optional[str]:
    """Extract a Firebase refresh_token from a HAR file."""
    try:
        har = json.loads(har_path.read_text(errors="replace"))
        for entry in har.get("log", {}).get("entries", []):
            url = entry.get("request", {}).get("url", "")
            if "securetoken.googleapis.com" not in url:
                continue
            post = entry.get("request", {}).get("postData", {}).get("text", "")
            if "refresh_token" in post:
                parts = dict(x.split("=", 1) for x in post.split("&") if "=" in x)
                if "refresh_token" in parts:
                    return parts["refresh_token"]
    except Exception:
        pass
    return None


# ──── Deep Heap Mining ───────────────────────────────────────────────────────

def mine_heap(
    heap_path: str,
    output_dir: str = "data/heap_output",
    tail_mb: int = 30,
    nexus: bool = False,
) -> Dict[str, Any]:
    """Run the full heap miner on a V8 heap snapshot.

    Uses scripts/heap_miner.py which has 100+ regex patterns for:
    - Google auth cookies (SAPISID, SID, HSID, etc.)
    - Firebase/OAuth tokens
    - API keys (AIza*)
    - JWTs
    - NLM/Colab/GitHub/AI Studio credentials
    - Email addresses, user IDs
    - Internal API endpoints

    Args:
        heap_path: Path to .heapsnapshot file.
        output_dir: Directory for findings output.
        tail_mb: MB from end of file to read (strings are at the end).
        nexus: Store findings in Nexus KMS.

    Returns:
        Dict with findings summary.
    """
    import subprocess
    import sys

    root = Path(__file__).resolve().parents[2]
    miner = root / "scripts" / "heap_miner.py"

    if not miner.exists():
        return {"error": f"heap_miner.py not found at {miner}"}

    cmd = [
        sys.executable, str(miner),
        str(heap_path),
        "--tail", str(tail_mb),
        "--out", str(output_dir),
    ]
    if nexus:
        cmd.append("--nexus")

    result = subprocess.run(cmd, capture_output=True, text=True, cwd=str(root))

    # Read the output JSON
    heap_name = Path(heap_path).stem
    findings_json = Path(output_dir) / f"{heap_name}_findings.json"
    if findings_json.exists():
        findings = json.loads(findings_json.read_text())
        total = sum(len(v) for v in findings.values())
        return {
            "file": str(heap_path),
            "findings": total,
            "categories": len(findings),
            "category_counts": {k: len(v) for k, v in findings.items()},
            "output": str(findings_json),
        }

    return {"file": str(heap_path), "error": result.stderr[:500] if result.returncode else "no output"}


def mine_heap_deep(
    heap_path: str,
    output_dir: str = "data/heap_output",
    strings_only: bool = True,
) -> Dict[str, Any]:
    """Run the deep V8 graph parser on a heap snapshot.

    This walks the entire V8 node/edge graph (not just regex). Extracts:
    - All unique strings (sorted by length)
    - Script source code
    - Reconstructed JS objects
    - DOM content
    - Full API surface (function names)

    Args:
        heap_path: Path to .heapsnapshot file.
        output_dir: Directory for output.
        strings_only: Fast mode — skip graph walk, just extract strings.

    Returns:
        Dict with output paths.
    """
    import subprocess
    import sys

    root = Path(__file__).resolve().parents[2]
    parser = root / "scripts" / "heap_deep_parser.py"

    if not parser.exists():
        return {"error": f"heap_deep_parser.py not found at {parser}"}

    cmd = [sys.executable, str(parser), str(heap_path)]
    if strings_only:
        cmd.append("--strings-only")

    result = subprocess.run(cmd, capture_output=True, text=True, cwd=str(root))

    heap_name = Path(heap_path).stem
    deep_dir = Path(output_dir) / f"{heap_name}_deep"
    if deep_dir.exists():
        files = list(deep_dir.iterdir())
        return {
            "file": str(heap_path),
            "output_dir": str(deep_dir),
            "output_files": [f.name for f in files],
            "total_files": len(files),
        }

    return {"file": str(heap_path), "error": result.stderr[:500] if result.returncode else "no output"}


def decode_jwts_from_findings(findings_json_path: str) -> List[Dict[str, Any]]:
    """Decode all JWTs found in a heap miner findings JSON file.

    Args:
        findings_json_path: Path to *_findings.json from heap_miner.

    Returns:
        List of decoded JWT dicts with header, payload, expiry status.
    """
    import base64
    import time

    path = Path(findings_json_path)
    if not path.exists():
        return []

    data = json.loads(path.read_text())
    jwts = data.get("jwt", [])
    decoded = []

    for item in jwts:
        token = item["value"]
        parts = token.split(".")
        if len(parts) < 2:
            continue
        try:
            header = json.loads(base64.b64decode(parts[0] + "=="))
            payload = json.loads(base64.b64decode(parts[1] + "=="))
            exp = payload.get("exp", 0)
            remaining = exp - time.time() if exp else -1
            decoded.append({
                "algorithm": header.get("alg"),
                "kid": header.get("kid", "none"),
                "issuer": payload.get("iss", "?"),
                "subject": payload.get("sub", payload.get("user_id", "?")),
                "email": payload.get("email", ""),
                "audience": str(payload.get("aud", "?"))[:60],
                "expired": remaining < 0,
                "remaining_minutes": int(remaining / 60) if remaining > 0 else int(-remaining / 60),
                "status": f"VALID ({int(remaining/60)}min)" if remaining > 0 else f"EXPIRED ({int(-remaining/60)}min ago)",
            })
        except Exception:
            pass

    return decoded


# ──── Agent Message Stream Extraction ─────────────────────────────────────

# v1.52.1 [2026-03-26] — Extract multi-agent orchestration traces from heap strings
def extract_agent_messages(strings_file: str) -> Dict[str, Any]:
    """Extract multi-agent orchestration messages from a deep-parsed heap strings file.

    Parses `onReceiveAgentMessage` events to reconstruct the full agent dispatch
    trace — which sub-agents were called, what tools they used, and the content
    they produced. Works with OpenRoom/Talkie/MiniMax-style agent protocols.

    Args:
        strings_file: Path to strings_all.txt from heap_deep_parser.

    Returns:
        Dict with agents, tool_calls, messages, and timeline.
    """
    path = Path(strings_file)
    if not path.exists():
        return {"error": f"File not found: {strings_file}"}

    agents: Dict[str, int] = {}
    tool_calls: List[Dict] = []
    messages: List[Dict] = []
    raw_count = 0

    for line in path.read_text(errors="replace").splitlines():
        if "onReceiveAgentMessage" not in line:
            continue
        raw_count += 1

        # Extract the JSON payload
        json_start = line.find("{")
        if json_start < 0:
            continue

        # Trim trailing timestamp
        json_str = line[json_start:].strip()
        # Remove trailing non-JSON (timestamp after closing brace)
        brace_depth = 0
        json_end = 0
        for i, ch in enumerate(json_str):
            if ch == "{":
                brace_depth += 1
            elif ch == "}":
                brace_depth -= 1
                if brace_depth == 0:
                    json_end = i + 1
                    break

        if json_end == 0:
            continue

        try:
            data = json.loads(json_str[:json_end])
        except json.JSONDecodeError:
            continue

        chunk = data.get("agent_message_chunk", {})
        agent_name = chunk.get("sub_agent_name", "unknown")
        agents[agent_name] = agents.get(agent_name, 0) + 1

        content = chunk.get("msg_content", "")
        for tc in chunk.get("tool_calls", []):
            tool_calls.append({
                "agent": agent_name,
                "tool": tc.get("tool_call_display_name", "?"),
                "id": tc.get("tool_call_id", "?"),
                "status": tc.get("tool_call_status"),  # 1=running, 2=done, 3=failed
                "data": tc.get("tool_call_display_data", ""),
            })

        # Capture messages with any content (even short tool responses)
        if content:
            messages.append({
                "agent": agent_name,
                "msg_id": chunk.get("msg_id"),
                "msg_type": chunk.get("msg_type"),
                "content_preview": content[:300],
                "finish": chunk.get("finish", False),
                "timestamp": chunk.get("timestamp"),
            })

    return {
        "total_events": raw_count,
        "agents": agents,
        "tool_calls_count": len(tool_calls),
        "tool_calls": tool_calls,
        "messages_count": len(messages),
        "messages": messages[:50],  # Cap output
    }


# ──── Chain-of-Thought Extraction ─────────────────────────────────────────

# v1.52.1 [2026-03-26] — Extract leaked model reasoning from heap strings
def extract_chain_of_thought(strings_file: str) -> List[Dict[str, str]]:
    """Extract leaked model chain-of-thought reasoning from heap strings.

    Searches for patterns that indicate model internal reasoning:
    - "I need to respond as..."
    - "I should..."
    - "The user is asking..."
    - "Let me re-read the context..."
    - "All tasks completed..."
    - Lines containing stage/objective/character reasoning

    Args:
        strings_file: Path to strings_all.txt from heap_deep_parser.

    Returns:
        List of dicts with line_number, content, and pattern_matched.
    """
    import re

    patterns = [
        (re.compile(r"^(The user is asking|I need to respond|I should|Let me)", re.IGNORECASE), "reasoning"),
        (re.compile(r"^(All tasks completed|Now I need to|The current stage)", re.IGNORECASE), "planning"),
        (re.compile(r"respond as (Aoi|Vex|Nyx|Maya|the character)", re.IGNORECASE), "character_switch"),
        (re.compile(r"stage \d+|stage objectives|move the (scene|narrative|story)", re.IGNORECASE), "stage_logic"),
        (re.compile(r"</think", re.IGNORECASE), "think_tag"),
    ]

    path = Path(strings_file)
    if not path.exists():
        return []

    findings = []
    for i, line in enumerate(path.read_text(errors="replace").splitlines(), 1):
        stripped = line.strip()
        if len(stripped) < 20 or len(stripped) > 2000:
            continue
        for pat, label in patterns:
            if pat.search(stripped):
                findings.append({
                    "line": i,
                    "pattern": label,
                    "content": stripped[:500],
                })
                break

    return findings


# ──── App Schema Extraction ──────────────────────────────────────────────

# v1.52.1 [2026-03-26] — Extract app tool definitions from heap strings
def extract_app_schemas(strings_file: str) -> List[Dict[str, Any]]:
    """Extract app meta.yaml schemas from heap strings (OpenRoom/Talkie-style).

    Searches for YAML-formatted app definitions that contain:
    - app_id, app_name, app_display_name
    - description
    - actions (tool definitions with type, name, description, params)

    Args:
        strings_file: Path to strings_all.txt from heap_deep_parser.

    Returns:
        List of dicts with app_id, app_name, description, and actions.
    """
    path = Path(strings_file)
    if not path.exists():
        return []

    apps = []
    lines = path.read_text(errors="replace").splitlines()
    i = 0
    while i < len(lines):
        line = lines[i].strip()
        # Look for app_id: N pattern (tab-prefixed from meta.yaml reads)
        if "app_id:" in line and "app_name:" in (lines[i + 1].strip() if i + 1 < len(lines) else ""):
            app: Dict[str, Any] = {}
            # Parse the YAML block
            block_lines = []
            j = i
            while j < len(lines) and j < i + 50:
                bl = lines[j].strip()
                # Stop at empty line or non-YAML content
                if not bl or (bl[0] not in " \t" and ":" not in bl and "-" not in bl[0:5]):
                    # Check if this is a numbered line (from agent output)
                    if bl and bl[0].isdigit() and "\t" in bl:
                        bl = bl.split("\t", 1)[-1]  # Strip line number prefix
                    else:
                        break
                block_lines.append(bl)
                j += 1

            yaml_text = "\n".join(block_lines)
            # Extract key fields via regex
            import re
            app_id_m = re.search(r"app_id:\s*(\d+)", yaml_text)
            app_name_m = re.search(r"app_name:\s*(\w+)", yaml_text)
            display_m = re.search(r"app_display_name:\s*(.+)", yaml_text)
            desc_m = re.search(r"description:\s*(.+?)(?:\n\s{6}|\nactions:)", yaml_text, re.DOTALL)

            if app_id_m and app_name_m:
                app["app_id"] = int(app_id_m.group(1))
                app["app_name"] = app_name_m.group(1)
                app["display_name"] = display_m.group(1).strip() if display_m else ""
                app["description"] = desc_m.group(1).strip().replace("\n", " ") if desc_m else ""

                # Extract action types
                actions = re.findall(r"type:\s*(\w+)", yaml_text)
                app["actions"] = actions
                apps.append(app)
            i = j
        else:
            i += 1

    # Deduplicate by app_id
    seen = set()
    unique = []
    for a in apps:
        if a["app_id"] not in seen:
            seen.add(a["app_id"])
            unique.append(a)

    return unique


# ──── Protobuf Definition Extraction ─────────────────────────────────────

# v1.52.1 [2026-03-26] — Extract proto3 definitions from heap strings
def extract_protobuf_definitions(strings_file: str) -> List[str]:
    """Extract protobuf schema definitions from heap strings.

    Searches for proto3 syntax blocks including enum and message definitions.

    Args:
        strings_file: Path to strings_all.txt from heap_deep_parser.

    Returns:
        List of proto definition strings.
    """
    path = Path(strings_file)
    if not path.exists():
        return []

    definitions = []
    lines = path.read_text(errors="replace").splitlines()
    i = 0
    while i < len(lines):
        stripped = lines[i].strip()
        if stripped == 'syntax = "proto3";':
            # Collect the proto block
            block = [stripped]
            j = i + 1
            while j < len(lines) and j < i + 50:
                bl = lines[j].strip()
                if bl == "}" or bl.startswith("}"):
                    block.append(bl)
                    # Check if there's another enum/message after
                    if j + 1 < len(lines) and lines[j + 1].strip() in ("", "enum", "message"):
                        j += 1
                        continue
                    break
                if bl and not bl.startswith("M") and len(bl) < 200:
                    block.append(bl)
                else:
                    break
                j += 1
            definitions.append("\n".join(block))
            i = j + 1
        else:
            i += 1

    return definitions


# ──── Auto-Discovery Pipeline ────────────────────────────────────────────

# v1.52.1 [2026-03-26] — Full automated analysis pipeline
def auto_analyze(
    input_path: str,
    output_dir: str = "data/heap_output",
    report_dir: str = "data/argus/reports",
) -> Dict[str, Any]:
    """Run the full ARGUS analysis pipeline automatically.

    Detects file types and runs appropriate analysis:
    - .heapsnapshot → mine_heap() + mine_heap_deep() + all extractors
    - .har → HAR analysis + extract refresh tokens
    - directory → scan for all .heapsnapshot and .har files, process each

    This is the main entry point for automated ARGUS analysis.
    Agents should call this whenever they encounter capture files.

    Args:
        input_path: Path to file or directory to analyze.
        output_dir: Base directory for heap output.
        report_dir: Directory for generated reports.

    Returns:
        Dict with all findings aggregated.
    """
    import time

    path = Path(input_path)
    results: Dict[str, Any] = {
        "input": str(path),
        "timestamp": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "heaps_processed": 0,
        "hars_processed": 0,
        "findings": {},
    }

    # Collect files to process
    files: List[Path] = []
    if path.is_dir():
        files.extend(path.glob("**/*.heapsnapshot"))
        files.extend(path.glob("**/*.har"))
    elif path.is_file():
        files.append(path)

    for f in files:
        name = f.stem
        logger.info("[ARGUS] Processing %s (%s)", f.name, _human_size(f.stat().st_size))

        if f.suffix == ".heapsnapshot":
            results["heaps_processed"] += 1
            heap_results: Dict[str, Any] = {"file": str(f)}

            # Phase 1: Regex scan
            logger.info("[ARGUS] Phase 1: Regex scan (100+ patterns)")
            regex_result = mine_heap(str(f), output_dir)
            heap_results["regex"] = regex_result

            # Phase 2: Deep parse (V8 graph walk)
            logger.info("[ARGUS] Phase 2: Deep parse (V8 graph walk)")
            deep_result = mine_heap_deep(str(f), output_dir)
            heap_results["deep"] = deep_result

            # Phase 3: Extract intelligence from deep parse
            deep_dir = deep_result.get("output_dir", "")
            strings_file = str(Path(deep_dir) / "strings_all.txt") if deep_dir else ""

            if strings_file and Path(strings_file).exists():
                logger.info("[ARGUS] Phase 3: Intelligence extraction")

                agents = extract_agent_messages(strings_file)
                heap_results["agents"] = {
                    "total_events": agents.get("total_events", 0),
                    "agents_found": agents.get("agents", {}),
                    "tool_calls": agents.get("tool_calls_count", 0),
                }

                cot = extract_chain_of_thought(strings_file)
                heap_results["chain_of_thought"] = len(cot)

                apps = extract_app_schemas(strings_file)
                heap_results["app_schemas"] = len(apps)

                protos = extract_protobuf_definitions(strings_file)
                heap_results["protobuf_definitions"] = len(protos)

            # Phase 4: Decode JWTs
            findings_json = regex_result.get("output", "")
            if findings_json and Path(findings_json).exists():
                logger.info("[ARGUS] Phase 4: JWT decoding")
                jwts = decode_jwts_from_findings(findings_json)
                heap_results["jwts"] = len(jwts)
                for jwt in jwts:
                    logger.info(
                        "[ARGUS] JWT: %s (%s) — %s",
                        jwt.get("issuer", "?"),
                        jwt.get("algorithm", "?"),
                        jwt.get("status", "?"),
                    )

            results["findings"][name] = heap_results

        elif f.suffix == ".har":
            results["hars_processed"] += 1
            har_results: Dict[str, Any] = {"file": str(f)}

            # Extract refresh tokens
            token = extract_refresh_token_from_har(f)
            if token:
                har_results["refresh_token_found"] = True
                logger.info("[ARGUS] Found refresh_token in %s", f.name)

            results["findings"][name] = har_results

    # Save summary report
    report_path = Path(report_dir) / "auto_analysis_report.json"
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(json.dumps(results, indent=2, default=str))
    logger.info("[ARGUS] Report saved to %s", report_path)

    results["report"] = str(report_path)
    return results


def _human_size(size_bytes: int) -> str:
    """Convert bytes to human-readable size."""
    for unit in ("B", "KB", "MB", "GB"):
        if size_bytes < 1024:
            return f"{size_bytes:.1f}{unit}"
        size_bytes /= 1024
    return f"{size_bytes:.1f}TB"
