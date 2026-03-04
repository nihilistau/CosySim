"""Deep decode of Gemini BardChatUi rpcids + AI Studio MakerSuiteService endpoints"""
import re, json, urllib.parse
from pathlib import Path

OUT = Path("data/heap_output/gemini_aistudio_analysis")
HAR_DIR = Path("data/har_files")

# ── Gemini full decode ─────────────────────────────────────────────────────
print("=== GEMINI BardChatUi rpcid FULL DECODE ===\n")
har = json.loads((HAR_DIR / "gemini.google.com.har").read_text(encoding="utf-8", errors="replace"))
entries = har["log"]["entries"]

gemini_rpcids = {}
for e in entries:
    url = e["request"]["url"]
    m = re.search(r"rpcids=([A-Za-z0-9,]+)", url)
    if not m: continue
    for rid in m.group(1).split(","):
        body = e["request"].get("postData", {}).get("text", "")
        resp = e["response"].get("content", {}).get("text", "")
        
        # decode f.req payload
        payload = ""
        fm = re.search(r"f\.req=(.+?)(?:&|$)", body)
        if fm:
            try:
                decoded = urllib.parse.unquote(fm.group(1))
                inner = json.loads(decoded)
                if isinstance(inner, list) and inner:
                    first = inner[0]
                    if isinstance(first, list) and first:
                        p = first[0]
                        if isinstance(p, list) and len(p) >= 2:
                            payload = p[1][:300] if isinstance(p[1], str) else str(p[1])[:300]
            except: pass
        
        # decode response
        resp_decoded = ""
        if resp and resp.startswith(")]}"):
            stripped = resp[5:]
            lines = stripped.strip().split("\n")
            for i, line in enumerate(lines):
                if line.startswith("[["):
                    try:
                        chunk = json.loads(line)
                        for item in chunk:
                            if isinstance(item, list) and len(item) >= 3 and item[0] == "wrb.fr":
                                resp_decoded = str(item[2])[:400] if item[2] else "(empty)"
                    except: pass
                    break
        
        if rid not in gemini_rpcids or resp_decoded:
            gemini_rpcids[rid] = {
                "payload": payload[:200],
                "response": resp_decoded[:350],
                "source_path": re.search(r"source-path=([^&]+)", url).group(1) if re.search(r"source-path=([^&]+)", url) else "",
            }

for rid, info in gemini_rpcids.items():
    print(f"rpcid: {rid}")
    print(f"  source-path: {urllib.parse.unquote(info['source_path'])}")
    print(f"  payload: {info['payload'][:120]}")
    print(f"  response: {info['response'][:200]}")
    print()

# ── AI Studio MakerSuiteService deep scan ─────────────────────────────────
print("\n=== AI STUDIO MakerSuiteService ENDPOINTS ===\n")
har2 = json.loads((HAR_DIR / "aistudio.google.co43.har").read_text(encoding="utf-8", errors="replace"))
entries2 = har2["log"]["entries"]

maker_methods = {}
api_keys_found = set()
auth_tokens = set()

for e in entries2:
    url = e["request"]["url"]
    
    # API key extraction (full)
    for key in re.findall(r"[?&]key=([A-Za-z0-9_\-]{35,})", url):
        api_keys_found.add(key)
    
    # Auth header
    for h in e["request"].get("headers", []):
        if h["name"].lower() in ("authorization", "x-goog-api-key"):
            auth_tokens.add(f"{h['name']}: {h['value'][:80]}")
    
    # MakerSuite gRPC methods
    if "alkalimakersuite-pa" in url or "MakerSuiteService" in url:
        method = url.split("/")[-1].split("?")[0]
        body = e["request"].get("postData", {}).get("text", "")
        resp = e["response"].get("content", {}).get("text", "")[:400]
        status = e["response"]["status"]
        if method not in maker_methods:
            maker_methods[method] = {"url": url[:200], "status": status, "resp": resp}
    
    # generativelanguage API
    if "generativelanguage" in url:
        method = re.search(r"/v\w+/models/([^:]+):(\w+)", url)
        if method:
            key = f"{method.group(1)}:{method.group(2)}"
            resp = e["response"].get("content", {}).get("text", "")[:300]
            body = e["request"].get("postData", {}).get("text", "")[:200]
            print(f"  generativelanguage: {url[:150]}")
            print(f"  body: {body[:100]}")
            print(f"  resp: {resp[:150]}\n")

print("MakerSuiteService methods found:")
for method, info in maker_methods.items():
    print(f"\n  Method: {method}")
    print(f"  Status: {info['status']}")
    print(f"  Response: {info['resp'][:250]}")

print(f"\nAPI Keys: {list(api_keys_found)}")
print(f"\nAuth tokens:")
for t in list(auth_tokens)[:10]:
    print(f"  {t}")
