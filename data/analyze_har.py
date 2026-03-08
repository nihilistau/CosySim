import json, re
from pathlib import Path
from urllib.parse import urlparse, parse_qs, unquote

HAR = r"C:\Users\Knack\Downloads\notebooklm_manual_har_test.har"
har = json.loads(Path(HAR).read_text(encoding="utf-8", errors="replace"))
entries = har["log"]["entries"]

rpc_data = {}
for e in entries:
    req = e.get("request", {})
    url = req.get("url", "")
    if "batchexecute" not in url and "GenerateFreeForm" not in url:
        continue
    qs = parse_qs(urlparse(url).query)
    rpc_id = qs.get("rpcids", [None])[0]
    if not rpc_id:
        rpc_id = "GenerateFreeForm" if "GenerateFreeForm" in url else "unknown"
    body = (req.get("postData") or {}).get("text", "") or ""
    freq_match = re.search(r"f\.req=([^&]+)", body)
    freq = None
    if freq_match:
        try:
            freq = json.loads(unquote(freq_match.group(1)))
        except Exception:
            pass
    source_path = qs.get("source-path", ["?"])[0]
    if rpc_id not in rpc_data:
        rpc_data[rpc_id] = {"count": 0, "paths": set(), "sample": freq}
    rpc_data[rpc_id]["count"] += 1
    rpc_data[rpc_id]["paths"].add(source_path)

print(f"Found {len(rpc_data)} unique RPCs:\n")
for rpc_id in sorted(rpc_data.keys()):
    info = rpc_data[rpc_id]
    paths = ", ".join(sorted(info["paths"]))[:70]
    count = info["count"]
    print(f"  {rpc_id:12} x{count:2}  {paths}")
    sample = info["sample"]
    if sample:
        try:
            inner = sample[0][0]
            payload = json.dumps(inner[1])[:120]
            print(f"               payload={payload}")
        except Exception:
            pass
