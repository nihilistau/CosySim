import re, json, urllib.parse, base64
from pathlib import Path

OUT = Path("data/heap_output/gemini_aistudio_analysis")
HAR_DIR = Path("data/har_files")

# ── Full model list from otAQ7b ──────────────────────────────────────────
print("=== GEMINI MODEL LIST (otAQ7b) ===")
har = json.loads((HAR_DIR / "gemini.google.com.har").read_text(encoding="utf-8", errors="replace"))
for e in har["log"]["entries"]:
    url = e["request"]["url"]
    if "rpcids=otAQ7b" not in url: continue
    resp = e["response"].get("content", {}).get("text", "")
    if not resp or not resp.startswith(")]}'") or len(resp) < 500: continue
    lines = resp[5:].strip().split("\n")
    for line in lines:
        if line.startswith("[["):
            try:
                chunk = json.loads(line)
                for item in chunk:
                    if isinstance(item, list) and len(item) >= 3 and item[0] == "wrb.fr":
                        inner = json.loads(item[2]) if isinstance(item[2], str) else item[2]
                        print(json.dumps(inner, indent=2)[:3000])
            except: pass

# ── NXpLKc Gemini↔NLM notebook link ──────────────────────────────────────
print("\n=== GEMINI↔NLM NOTEBOOK LINK (NXpLKc) ===")
for e in har["log"]["entries"]:
    url = e["request"]["url"]
    if "rpcids=NXpLKc" not in url: continue
    resp = e["response"].get("content", {}).get("text", "")
    if not resp: continue
    lines = resp[5:].strip().split("\n") if resp.startswith(")]}") else resp.split("\n")
    for line in lines:
        if line.startswith("[["):
            try:
                chunk = json.loads(line)
                for item in chunk:
                    if isinstance(item, list) and len(item) >= 3 and item[0] == "wrb.fr":
                        print(json.dumps(json.loads(item[2]) if isinstance(item[2],str) else item[2], indent=2)[:2000])
            except: pass

# ── ProxyUnaryCall thought signature ─────────────────────────────────────
print("\n=== ProxyUnaryCall THOUGHT SIGNATURE ===")
har2 = json.loads((HAR_DIR / "aistudio.google.co43.har").read_text(encoding="utf-8", errors="replace"))
for e in har2["log"]["entries"]:
    url = e["request"]["url"]
    if "ProxyUnaryCall" not in url: continue
    resp = e["response"].get("content", {}).get("text", "")[:1500]
    if resp:
        print(resp[:800])
        # Extract thought signature
        ts_m = re.search(r'"thoughtSignature":"([A-Za-z0-9+/=]{50,})"', resp)
        if ts_m:
            print(f"\n  THOUGHT SIGNATURE: {ts_m.group(1)[:200]}")
        break

# ── ListModels full decode ────────────────────────────────────────────────
print("\n=== AI STUDIO MODEL LIST (ListModels) ===")
for e in har2["log"]["entries"]:
    url = e["request"]["url"]
    if "ListModels" not in url: continue
    resp = e["response"].get("content", {}).get("text", "")
    if not resp: continue
    try:
        data = json.loads(resp)
        # Find model entries
        def find_models(obj, depth=0):
            if depth > 5: return
            if isinstance(obj, list):
                for item in obj:
                    if isinstance(item, list) and len(item) >= 2:
                        if isinstance(item[0], str) and item[0].startswith("models/"):
                            print(f"  {item[0]}: {item[4] if len(item)>4 else '?'} | ctx={item[5] if len(item)>5 else '?'} | out={item[6] if len(item)>6 else '?'}")
                    find_models(item, depth+1)
        find_models(data)
    except Exception as ex:
        # Try text search
        for m in re.findall(r'"(models/[^"]+)"', resp):
            print(f"  {m}")
    break
