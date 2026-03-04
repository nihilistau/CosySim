"""Read and display all credential findings from heap outputs."""
import json
from pathlib import Path

DIRS = [
    "data/heap_output/Heap-20260305T033221-notebooklm_deep",
    "data/heap_output/Heap-20260305T034628-notebook2_deep",
    "data/heap_output/Heap-20260305T034351-sheets_deep",
]

all_notebooks = set()
all_emails = set()
all_cookies = {}
all_api_keys = set()
all_tokens = set()
all_endpoints = set()
all_oauth_clients = set()

for d in DIRS:
    p = Path(d)
    name = p.name.replace("_deep", "")
    print(f"\n{'='*60}")
    print(f" {name}")
    print(f"{'='*60}")

    findings_file = p / "findings.json"
    with open(findings_file) as f:
        data = json.load(f)

    summary = data.get("summary", {})
    findings = data.get("findings", {})
    print(f"  Nodes: {data.get('node_count',0):,} | Strings: {data.get('string_count',0):,}")
    print(f"  Findings: {summary.get('total_findings',0):,} | API fns: {summary.get('api_functions',0):,}")

    for cat, items in sorted(findings.items()):
        if not items:
            continue
        items_list = list(items) if not isinstance(items, list) else items
        print(f"\n  [{cat}] {len(items_list)} hits:")
        for item in items_list[:8]:
            s = str(item)
            trunc = s[:120] + "..." if len(s) > 120 else s
            print(f"    {trunc}")
            if "notebook" in cat:
                all_notebooks.add(s)
            if "email" in cat:
                all_emails.add(s)
            if "sapisid" in cat:
                if "=" in s:
                    k, _, v = s.partition("=")
                    all_cookies[k.strip()] = v.strip()
            if "api_key" in cat:
                all_api_keys.add(s)
            if "oauth_client" in cat:
                all_oauth_clients.add(s)
            if "endpoint" in cat or "grpc" in cat:
                all_endpoints.add(s)

    strings_large = p / "strings_large.txt"
    if strings_large.exists():
        lines = strings_large.read_text(encoding="utf-8", errors="replace").splitlines()
        hv = [l for l in lines if any(x in l for x in ["SAPISID","Bearer ","ya29.","AIza","hpke","access_token","SID="])]
        if hv:
            print(f"\n  HIGH-VALUE large strings ({len(hv)}):")
            for line in hv[:8]:
                print(f"    {line[:130]}")

    objs_file = p / "objects.json"
    if objs_file.exists():
        with open(objs_file) as f:
            objs = json.load(f)
        named = [o for o in objs if o.get("type","?") not in ("?","(number:smi number)")]
        if named:
            print(f"\n  Named objects ({len(named)}):")
            for obj in named[:5]:
                t = obj.get("type","?")
                props = list(obj.get("properties",{}).keys())[:6]
                print(f"    {t}: {props}")

print("\n"+"="*60)
print("AGGREGATED ACROSS ALL HEAPS")
print("="*60)
print(f"\nNLM Notebook UUIDs ({len(all_notebooks)}):")
for nb in sorted(all_notebooks): print(f"  {nb}")
print(f"\nEmails ({len(all_emails)}): {sorted(all_emails)}")
print(f"\nGoogle cookies ({len(all_cookies)}):")
for k, v in sorted(all_cookies.items()):
    print(f"  {k} = {v[:60]}{'...' if len(v)>60 else ''}")
print(f"\nGoogle API keys ({len(all_api_keys)}):")
for k in sorted(all_api_keys): print(f"  {k}")
print(f"\nOAuth clients ({len(all_oauth_clients)}):")
for c in sorted(all_oauth_clients): print(f"  {c}")
print(f"\nEndpoints/gRPC ({len(all_endpoints)}):")
for e in sorted(all_endpoints)[:20]: print(f"  {e}")
