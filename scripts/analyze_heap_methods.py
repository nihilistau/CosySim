import re, json
from pathlib import Path

HEAP_DIR = Path("data/heap_output")
OUT = Path("data/heap_output/gemini_aistudio_analysis")

# Search all three new heaps for MakerSuiteService method names and Gemini service patterns
SEARCHES = [
    "MakerSuiteService", "BardChatUi", "GenerativeLang", "makersuite",
    "alkalimakersuite", "ListModels", "GenerateContent", "StreamGenerate",
    "/google.ai.", "/google.internal.alkali", "BardService", "ChatService",
    "nano-banana", "thoughtSignature", "modelVersion", "ProxyUnaryCall",
    "ProvisionAndInitialize", "CodeAssistant", "AppletService",
]

all_hits = {}
for heap_out in sorted(HEAP_DIR.glob("*_deep")):
    strings_file = heap_out / "strings_all.txt"
    if not strings_file.exists(): continue
    name = heap_out.name
    if not any(x in name for x in ["gemini","052314","aistudio"]): continue
    strings = strings_file.read_text(encoding="utf-8", errors="replace").splitlines()
    print(f"\n=== {name} ({len(strings)} strings) ===")
    all_hits[name] = {}
    for search in SEARCHES:
        hits = [s for s in strings if search in s and len(s) < 500]
        if hits:
            all_hits[name][search] = hits[:8]
            print(f"  [{search}]: {len(hits)} hits")
            for h in hits[:3]:
                print(f"    {h[:180]}")

# Save
(OUT / "heap_service_methods.json").write_text(json.dumps(all_hits, indent=2))
print(f"\nSaved to {OUT}/heap_service_methods.json")
