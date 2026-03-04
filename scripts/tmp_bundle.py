"""Download and deep-mine the gstatic JS bundles for hidden endpoints, feature flags, secrets."""
import re, json, requests
from pathlib import Path

OUT = Path("data/heap_output/gemini_aistudio_analysis/js_bundles")
OUT.mkdir(parents=True, exist_ok=True)

# Try fetching without auth - these are CDN-served public bundles
BUNDLE_URLS = [
    # AI Studio bundles - two versions
    "https://www.gstatic.com/_/mss/boq-makersuite/_/js/k=boq-makersuite.MakerSuite.en_US.0f5MW4Z780o.2018.O/am=BgI/d=1/excm=_b/ed=1/dg=0/br=1/wt=2/ujg=1/rs=AMOXD289jtQDQAFD0CbKodoycfMkjXaAqg/dti=1/m=_b",
    # Try fetching the full bundle (d=1 param = minified, excm excludes modules)
    "https://www.gstatic.com/_/mss/boq-notebooklm/_/js/k=boq-notebooklm.NotebookLm.en_US",
]

headers = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
    "Accept": "*/*",
    "Accept-Encoding": "gzip, deflate, br",
    "Referer": "https://aistudio.google.com/",
}

# Try the base URL pattern for the boq bundle
base_url = "https://www.gstatic.com/_/mss/boq-makersuite/_/js/k=boq-makersuite.MakerSuite.en_US.0f5MW4Z780o.2018.O/am=BgI/d=1/excm=_b/ed=1/dg=0/br=1/wt=2/ujg=1/rs=AMOXD289jtQDQAFD0CbKodoycfMkjXaAqg/dti=1/m=_b"
print(f"Trying: {base_url[:100]}...")
try:
    r = requests.get(base_url, headers=headers, timeout=15)
    print(f"  Status: {r.status_code}, Size: {len(r.content)//1024}KB")
    if r.status_code == 200:
        (OUT / "makersuite_b.js").write_bytes(r.content)
        print("  Saved!")
except Exception as e:
    print(f"  Error: {e}")

# Also try to get the main bundle (m=main or similar)
main_url = "https://www.gstatic.com/_/mss/boq-makersuite/_/js/k=boq-makersuite.MakerSuite.en_US.0f5MW4Z780o.2018.O/ck=boq-makersuite.MakerSuite.PaHJsS8M-OA.L.B1.O/am=BgI/d=1/exm=XVDWwe,_b,nLooQd/excm=_b/ed=1/br=1"
print(f"\nTrying main bundle: {main_url[:100]}...")
try:
    r = requests.get(main_url, headers=headers, timeout=15)
    print(f"  Status: {r.status_code}, Size: {len(r.content)//1024}KB")
    if r.status_code == 200:
        (OUT / "makersuite_main.js").write_bytes(r.content)
        print("  Saved!")
except Exception as e:
    print(f"  Error: {e}")

# Check if we got anything and mine it
for f in OUT.glob("*.js"):
    text = f.read_text(encoding="utf-8", errors="replace")
    print(f"\n=== Mining {f.name} ({len(text)//1024}KB) ===")
    
    # Proto paths
    protos = re.findall(r"google\.[a-z.]+(?:Service|Api|Handler)[/.]", text)
    print(f"  Proto services: {set(protos)}")
    
    # Feature flags
    flags = re.findall(r"featureFlag[s]?\s*[=:]\s*\{[^}]{0,500}", text)
    print(f"  Feature flag blocks: {len(flags)}")
    
    # API endpoints
    endpoints = re.findall(r'"/[a-z_/]+/v\d+/[^"]{5,80}"', text)
    print(f"  API endpoints: {endpoints[:10]}")
