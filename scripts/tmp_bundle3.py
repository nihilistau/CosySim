import re, json
from pathlib import Path
from collections import defaultdict

JS = Path("data/heap_output/gemini_aistudio_analysis/js_bundles/makersuite_b.js")
text = JS.read_text(encoding="utf-8", errors="replace")

findings = {}

# 3. Find Kz() Angular gRPC stub registrations (the pattern that gave us NLM methods)
kz_stubs = re.findall(r'Kz\(([^)]{10,200})\)', text)
print(f"=== Kz() GRPC STUBS: {len(kz_stubs)} ===")
for s in kz_stubs[:30]:
    print(f"  Kz({s[:120]})")
findings["kz_stubs"] = kz_stubs[:100]

# 4. Feature flag module — find __module_featureFlags and all flag names
flag_blocks = re.findall(r'__module_featureFlags\s*=\s*\{([^}]{0,2000})\}', text)
print(f"\n=== FEATURE FLAG BLOCKS: {len(flag_blocks)} ===")
for blk in flag_blocks[:3]:
    print(blk[:600])
    
# 5. Also find individual flag registrations
flag_names = re.findall(r'["\']((?:enable|disable|show|hide|allow|block|use|is_)[a-z_]{3,60})["\']', text)
print(f"\n=== FLAG NAMES ({len(set(flag_names))}) ===")
for n in sorted(set(flag_names))[:50]:
    print(f"  {n}")

# 6. Error code maps — reveals internal error taxonomy
error_maps = re.findall(r'(\w+)\s*:\s*"([A-Z_]{5,60}(?:_ERROR|_FAILURE|_DENIED|_QUOTA|_INVALID)[A-Z_]*)"', text)
print(f"\n=== ERROR CODES ({len(error_maps)}) ===")
for code, name in sorted(set(error_maps))[:30]:
    print(f"  {code}: {name}")

# 7. Internal service names / namespaces
services = re.findall(r'google\.internal\.[a-z.]+', text)
print(f"\n=== INTERNAL SERVICES ===")
for s in sorted(set(services)):
    print(f"  {s}")

# 8. Regex for config/settings objects
config_keys = re.findall(r'"((?:max|min|limit|quota|timeout|retry|batch|chunk|pool|cache|buffer)[A-Za-z0-9_]{2,40})"', text)
print(f"\n=== CONFIG KEYS ({len(set(config_keys))}) ===")
for k in sorted(set(config_keys))[:40]:
    print(f"  {k}")

json.dump(findings, open("data/heap_output/gemini_aistudio_analysis/bundle_findings.json","w"), indent=2)
