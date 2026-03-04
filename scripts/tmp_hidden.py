from pathlib import Path
import re, json

bundle_urls = set()
webchannel_urls = set()
grpc_paths = set()
flag_lines = []
config_lines = []

for heap_out in sorted(Path("data/heap_output").glob("*_deep")):
    sf = heap_out / "strings_all.txt"
    if not sf.exists(): continue
    for line in sf.read_text(encoding="utf-8", errors="replace").splitlines():
        for url in re.findall(r"https://www\.gstatic\.com/_/mss/boq-\w+/_/js/k=[^\s\"'<>]+", line):
            bundle_urls.add(url[:280])
        for url in re.findall(r"https://webchannel-[^\s\"'<>]+", line):
            webchannel_urls.add(url[:200])
        for path in re.findall(r"/\$rpc/[^\s\"']+", line):
            grpc_paths.add(path[:200])
        if any(x in line for x in ["featureFlag","feature_flag","FeatureFlag","FEATURE_FLAG"]):
            flag_lines.append(line[:250])
        if any(x in line for x in ["secrets.json","config.json","/api/v1/","internal_api",".well-known","apiKey","API_KEY"]):
            config_lines.append(line[:250])

print(f"Bundle URLs: {len(bundle_urls)}")
print(f"Webchannel URLs: {len(webchannel_urls)}")
print(f"gRPC paths: {len(grpc_paths)}")
print()
print("=== BUNDLE URLS (downloadable JS) ===")
for u in sorted(bundle_urls)[:8]:
    print(f"  {u[:200]}")
print()
print("=== WEBCHANNEL URLS ===")
for u in sorted(webchannel_urls)[:5]:
    print(f"  {u}")
print()
print("=== GRPC PATHS ===")
for p in sorted(grpc_paths)[:20]:
    print(f"  {p}")
print()
print(f"=== FLAG HITS: {len(flag_lines)} ===")
for l in flag_lines[:5]:
    print(f"  {l[:220]}")
print()
print(f"=== CONFIG HITS: {len(config_lines)} ===")
for l in config_lines[:8]:
    print(f"  {l[:220]}")

# Save
out = {"bundle_urls": list(bundle_urls), "webchannel_urls": list(webchannel_urls),
       "grpc_paths": list(grpc_paths), "flag_lines": flag_lines[:50], "config_lines": config_lines[:50]}
Path("data/heap_output/gemini_aistudio_analysis/hidden_endpoints.json").write_text(json.dumps(out, indent=2))
