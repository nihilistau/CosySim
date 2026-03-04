"""Deep mine the 4.9MB AI Studio JS bundle — extract everything."""
import re, json
from pathlib import Path

JS = Path("data/heap_output/gemini_aistudio_analysis/js_bundles/makersuite_b.js")
text = JS.read_text(encoding="utf-8", errors="replace")
print(f"Bundle size: {len(text)//1024}KB")

findings = {}

# 1. ALL string literals that look like endpoints/paths
endpoint_patterns = [
    r'"(/[a-zA-Z_/\-]{5,80})"',
    r"'(/[a-zA-Z_/\-]{5,80})'",
    r'"(https?://[^"]{10,150})"',
]
endpoints = set()
for pat in endpoint_patterns:
    for m in re.findall(pat, text):
        if any(x in m for x in ["/api/","/v1/","/v2/","$rpc","batchexecute",
                                  "clients6","gstatic","googleapis","/data/",
                                  "/_/","alkalimakersuite","colab","notebooklm"]):
            endpoints.add(m)
findings["endpoints"] = sorted(endpoints)
print(f"\n=== ENDPOINTS ({len(endpoints)}) ===")
for e in sorted(endpoints)[:40]:
    print(f"  {e}")

# 2. Proto3 field number patterns — reveals message structure
# Pattern: fieldname:protobuf_field_number
field_defs = re.findall(r'\b([a-zA-Z][a-zA-Z0-9_]{2,40})\s*:\s*(\d{1,4})\b', text)
# Filter to likely proto fields (small numbers, camelCase names)
proto_fields = [(name, int(num)) for name, num in field_defs 
                if 1 <= int(num) <= 200 and name[0].islower() and len(name) > 3]
# Group by context window
findings["proto_fields_sample"] = proto_fields[:100]
print(f"\n=== PROTO FIELD DEFS (sample of {len(proto_fields)}) ===")
for name, num in sorted(set(proto_fields), key=lambda x: x[1])[:30]:
    print(f"  {name}: {num}")
