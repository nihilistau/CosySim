"""
Gemini / AI Studio comprehensive analyzer
- Parses console logs for API calls, errors, auth flows
- Mines all HAR files for endpoints, rpcids, request/response schemas
- Searches heap strings for service method names
- Outputs structured JSON + human-readable reports
"""
import re, json, os, urllib.parse, collections
from pathlib import Path

OUT = Path("data/heap_output/gemini_aistudio_analysis")
OUT.mkdir(parents=True, exist_ok=True)

HAR_DIR = Path("data/har_files")
HEAP_DIR = Path("data/heap_output")

# ── 1. Log file parser ──────────────────────────────────────────────────────

def parse_console_log(path: Path) -> dict:
    lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
    urls, errors, violations, navigations, fetches, rpcids = [], [], [], [], [], []
    
    for line in lines:
        if "Navigated to" in line:
            m = re.search(r"Navigated to (https?://\S+)", line)
            if m: navigations.append({"ts": line[:12].strip(), "url": m.group(1)})
        if "Violation" in line:
            violations.append(line.strip()[:200])
        if "Fetch failed" in line or "net::ERR" in line:
            m = re.search(r'(https?://[^"\'>\s]+)', line)
            if m: fetches.append({"type": "failed", "url": m.group(1)[:200], "line": line[:300]})
        
        # Extract all URLs
        for url in re.findall(r'https?://[^\s"\'>]{10,}', line):
            urls.append(url[:250])
        
        # Extract rpcids from batchexecute URLs
        for rid in re.findall(r'rpcids=([A-Za-z0-9_]+)', line):
            rpcids.append(rid)
        
        # Errors
        if "Error" in line or "error" in line or "exception" in line:
            errors.append(line.strip()[:250])
    
    return {
        "file": path.name,
        "lines": len(lines),
        "navigations": navigations,
        "rpcids": list(set(rpcids)),
        "unique_domains": list(set(re.findall(r'https?://([^/\s]+)', " ".join(urls)))),
        "errors": errors[:50],
        "fetch_failures": fetches[:30],
        "all_urls": list(set(urls))[:100],
    }

log_files = list(HAR_DIR.glob("*.log"))
log_results = [parse_console_log(f) for f in log_files]

# ── 2. HAR analyzer for Gemini/AI Studio ──────────────────────────────────

def analyze_har(path: Path) -> dict:
    print(f"  HAR: {path.name} ({path.stat().st_size//1024//1024}MB)...")
    try:
        data = json.loads(path.read_text(encoding="utf-8", errors="replace"))
    except Exception as e:
        return {"file": path.name, "error": str(e)}
    
    entries = data.get("log", {}).get("entries", [])
    rpcids = {}
    api_endpoints = []
    auth_data = {}
    cookies_found = {}
    api_keys = []
    ws_messages = []
    
    for e in entries:
        req = e.get("request", {})
        resp = e.get("response", {})
        url = req.get("url", "")
        method = req.get("method", "")
        status = resp.get("status", 0)
        
        # Skip static assets
        if any(x in url for x in ['.png','.jpg','.css','.woff','.ico','.gif']):
            continue
        
        # batchexecute rpcids
        rpc_m = re.search(r'rpcids=([A-Za-z0-9,]+)', url)
        if rpc_m:
            for rid in rpc_m.group(1).split(","):
                if rid not in rpcids:
                    body = req.get("postData", {}).get("text", "")
                    resp_text = resp.get("content", {}).get("text", "")[:500]
                    rpcids[rid] = {
                        "url": url[:200],
                        "method": method,
                        "status": status,
                        "body_snippet": body[:200],
                        "response_snippet": resp_text[:300],
                    }
        
        # API key in URL
        for key in re.findall(r'[?&]key=([A-Za-z0-9_-]{30,})', url):
            api_keys.append({"url": url[:100], "key": key})
        
        # Interesting API endpoints
        if any(x in url for x in ['generativelanguage','aiplatform','googleapis','batchexecute',
                                    'makersuite','aistudio','generate','stream','chat','models']):
            body = req.get("postData", {}).get("text", "")
            resp_text = resp.get("content", {}).get("text", "")
            api_endpoints.append({
                "url": url[:300],
                "method": method,
                "status": status,
                "body_100": body[:100],
                "response_100": resp_text[:200],
            })
        
        # Extract cookies
        for h in req.get("headers", []):
            if h.get("name", "").lower() == "cookie":
                val = h.get("value", "")
                for cookie in val.split(";"):
                    parts = cookie.strip().split("=", 1)
                    if len(parts) == 2:
                        k, v = parts
                        cookies_found[k.strip()] = v.strip()[:80]
        
        # Auth tokens in headers
        for h in req.get("headers", []):
            n = h.get("name", "").lower()
            v = h.get("value", "")
            if n in ["authorization", "x-goog-api-key", "x-api-key"]:
                auth_data[n] = v[:100]
    
    return {
        "file": path.name,
        "total_entries": len(entries),
        "rpcids": rpcids,
        "api_endpoints": api_endpoints[:50],
        "api_keys": api_keys[:20],
        "auth_headers": auth_data,
        "cookies": cookies_found,
    }

har_targets = [
    HAR_DIR / "aistudio.google.co43.har",
    HAR_DIR / "gemini.google.com.har",
    HAR_DIR / "aistudio.google.com.har",
    HAR_DIR / "aistudio.google.com3.har",
]
print("Analyzing HAR files...")
har_results = [analyze_har(p) for p in har_targets if p.exists()]

# ── 3. Heap string search for service methods ───────────────────────────────

SERVICE_PATTERNS = [
    "GenerateLive", "Generate", "StreamGenerate", "Predict", "Chat",
    "MakerSuiteService", "GenerativeLanguageService", "PalmService",
    "AIStudioService", "GeminiService", "VertexAI", "GenerateText",
    "GenerateContent", "CountTokens", "EmbedContent", "BatchEmbedContent",
    "TunedModel", "CreateTunedModel", "ListModels", "GetModel",
    "GenerateMessage", "CountMessageTokens", "EmbedText", "BatchEmbedText",
    "/google.ai.generativelanguage", "/google.cloud.aiplatform",
    "LabsTailwindUi", "MakerSuite",
]

heap_strings = {}
for heap_out in HEAP_DIR.glob("*gemini*_deep"):
    strings_file = heap_out / "strings_all.txt"
    if strings_file.exists():
        strings = strings_file.read_text(encoding="utf-8", errors="replace").splitlines()
        heap_strings[heap_out.name] = strings
        print(f"  {heap_out.name}: {len(strings)} strings")

for heap_out in HEAP_DIR.glob("*052314*_deep"):
    strings_file = heap_out / "strings_all.txt"
    if strings_file.exists():
        strings = strings_file.read_text(encoding="utf-8", errors="replace").splitlines()
        heap_strings[heap_out.name] = strings
        print(f"  {heap_out.name}: {len(strings)} strings")

for heap_out in HEAP_DIR.glob("*aistudio*_deep"):
    strings_file = heap_out / "strings_all.txt"
    if strings_file.exists():
        strings = strings_file.read_text(encoding="utf-8", errors="replace").splitlines()
        heap_strings[heap_out.name] = strings
        print(f"  {heap_out.name}: {len(strings)} strings")

service_hits = {}
for heap_name, strings in heap_strings.items():
    service_hits[heap_name] = {}
    all_text = "\n".join(strings)
    for pattern in SERVICE_PATTERNS:
        matches = [s for s in strings if pattern in s and len(s) < 300]
        if matches:
            service_hits[heap_name][pattern] = matches[:10]
    
    # Also look for rpcid patterns in Kz form
    kz_hits = [s for s in strings if "new _.Kz" in s or '/google.ai.' in s or '/google.cloud.' in s or 'GenerativeLang' in s]
    if kz_hits:
        service_hits[heap_name]["__kz_patterns"] = kz_hits[:20]

# ── 4. Write reports ─────────────────────────────────────────────────────────

# Master JSON
master = {
    "log_analysis": log_results,
    "har_analysis": har_results,
    "heap_service_methods": service_hits,
}
(OUT / "master_analysis.json").write_text(json.dumps(master, indent=2))

# Human-readable summary
lines = ["=" * 70, "GEMINI / AI STUDIO ANALYSIS REPORT", "=" * 70, ""]

# Log files
lines.append("## CONSOLE LOGS")
for r in log_results:
    lines += [f"\n### {r['file']} ({r['lines']} lines)"]
    lines += [f"  Navigations: {[n['url'] for n in r.get('navigations',[])]}"]
    lines += [f"  rpcids found: {r.get('rpcids',[])}"]
    lines += [f"  Domains: {r.get('unique_domains',[])}"]
    if r.get('errors'):
        lines.append(f"  Errors ({len(r['errors'])}):")
        for e in r['errors'][:5]:
            lines.append(f"    {e[:150]}")

# HAR analysis
lines += ["", "## HAR API ENDPOINTS"]
for r in har_results:
    if "error" in r: 
        lines.append(f"\n### {r['file']}: ERROR {r['error']}")
        continue
    lines += [f"\n### {r['file']} ({r['total_entries']} entries)"]
    lines += [f"  rpcids: {list(r['rpcids'].keys())}"]
    if r.get('api_keys'):
        lines.append(f"  API KEYS FOUND: {[k['key'][:30] for k in r['api_keys']]}")
    if r.get('auth_headers'):
        lines.append(f"  Auth headers: {list(r['auth_headers'].keys())}")
    if r.get('cookies'):
        lines.append(f"  Cookies: {list(r['cookies'].keys())}")
    lines.append(f"  API endpoints ({len(r.get('api_endpoints',[]))}):")
    for ep in r.get('api_endpoints', [])[:15]:
        lines.append(f"    [{ep['status']}] {ep['method']} {ep['url'][:120]}")
        if ep['response_100']:
            lines.append(f"          resp: {ep['response_100'][:100]}")

# Heap service methods
lines += ["", "## HEAP SERVICE METHOD DISCOVERIES"]
for heap, patterns in service_hits.items():
    lines.append(f"\n### {heap}")
    for pat, hits in patterns.items():
        lines.append(f"  [{pat}]:")
        for h in hits[:5]:
            lines.append(f"    {h[:150]}")

report = "\n".join(lines)
(OUT / "report.txt").write_text(report)
print(f"\nDone. Written to {OUT}/")
print(f"  master_analysis.json: {(OUT/'master_analysis.json').stat().st_size//1024} KB")
print(report[:3000])
