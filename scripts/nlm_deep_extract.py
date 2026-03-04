"""
nlm_deep_extract.py — Deep extraction from all heap outputs.

Mines:
  - strings_credentials.txt (pre-filtered high-value strings)
  - storage.json (localStorage/sessionStorage/cookies in JS)
  - objects.json (named JS objects with properties)
  - scripts.js (extracted JS code for API patterns, hardcoded values)
  - api_surface.txt (cross-heap API surface diff and new endpoint discovery)

Run:
    python scripts/nlm_deep_extract.py
    python scripts/nlm_deep_extract.py --heap data/heap_output/Heap-20260305T040304_deep
"""

import json
import re
import argparse
from pathlib import Path
from collections import defaultdict

HEAP_OUTPUT_DIR = Path("data/heap_output")

# Patterns for extracting high-value data from scripts
PATTERNS = {
    "api_key": re.compile(r"AIza[A-Za-z0-9_\-]{35}"),
    "oauth_client": re.compile(r"\d{12}-[a-z0-9]+\.apps\.googleusercontent\.com"),
    "notebook_uuid": re.compile(r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}", re.I),
    "rpcid": re.compile(r"\"([A-Za-z0-9_]{6,8})\",\s*\"(\[\[)"),
    "build_label": re.compile(r"boq[_\-][a-z\-]+\.[A-Za-z0-9_\.]+"),
    "grpc_endpoint": re.compile(r"/\$rpc/[a-z\.]+/[A-Za-z]+"),
    "proto_service": re.compile(r"google\.internal\.[a-z\.]+v\d+\.[A-Za-z]+Service"),
    "proto_method": re.compile(r"(?:google\.internal\.[a-z\.]+v\d+\.[A-Za-z]+Service)/([A-Z][A-Za-z]+)"),
    "internal_endpoint": re.compile(r"https?://[a-z\-]+\.(clients6|corp|internal)\.google\.com[/A-Za-z0-9\-_\.]*"),
    "ya29_token": re.compile(r"ya29\.[A-Za-z0-9_\-]{30,}"),
    "bearer_token": re.compile(r"Bearer\s+([A-Za-z0-9_\-\.]{20,})"),
    "hpke_key": re.compile(r"[A-Za-z0-9+/]{40,}={0,2}"),
    "firebase_config": re.compile(r'"apiKey":\s*"([^"]+)".*?"projectId":\s*"([^"]+)"', re.DOTALL),
    "tailwind_constant": re.compile(r"LabsTailwind[A-Za-z]+"),
    "proto_enum": re.compile(r"ARTIFACT_STATUS_[A-Z_]+|SOURCE_TYPE_[A-Z_]+|NOTEBOOK_[A-Z_]+"),
    "json_config": re.compile(r'\{"[a-z_]+"\s*:\s*(?:true|false|null|\d+|"[^"]{3,}")(?:,\s*"[a-z_]+"[^}]{0,100})\}'),
}


def mine_scripts(scripts_js: Path) -> dict:
    """Extract all patterns from scripts.js."""
    findings = defaultdict(set)
    try:
        text = scripts_js.read_text(encoding="utf-8", errors="replace")
    except Exception:
        return {}

    for name, pattern in PATTERNS.items():
        if name == "hpke_key":
            continue  # Too many false positives in JS
        matches = pattern.findall(text)
        for m in matches:
            val = m[0] if isinstance(m, tuple) else m
            if len(val) > 5:
                findings[name].add(val[:200])

    # Special: extract rpcid->method mappings
    # Look for patterns like: ["rpcid","method_name"] or similar
    rpc_patterns = [
        re.compile(r'"([A-Za-z0-9]{6,8})"\s*,\s*"([A-Z][a-z][A-Za-z]{5,})"'),  # ["abc123","MethodName"]
        re.compile(r'rpcid["\s:=]+([A-Za-z0-9]{6,8})'),
        re.compile(r'\"([A-Za-z0-9]{6,8})\",function\('),
    ]
    rpc_ids = set()
    for p in rpc_patterns:
        for m in p.finditer(text):
            rpcid = m.group(1)
            if len(rpcid) == 6 or len(rpcid) == 7:
                rpc_ids.add(rpcid)
    if rpc_ids:
        findings["rpcid_candidates"] = rpc_ids

    # Extract tailwind/NLM-specific constants
    tailwind_blocks = re.findall(r"Tailwind[A-Za-z]*\.[A-Za-z_]+\s*[=:]\s*[\"'][^\"']{3,60}[\"']", text)
    if tailwind_blocks:
        findings["tailwind_constants"] = set(tailwind_blocks[:50])

    # Extract error messages (useful for understanding what operations exist)
    error_msgs = re.findall(r'"(Error[^"]{5,60}|Failed[^"]{5,60}|Cannot[^"]{5,60}|Invalid[^"]{5,60})"', text)
    if error_msgs:
        findings["error_messages"] = set(error_msgs[:30])

    # Extract URL templates
    url_templates = re.findall(r'"(https?://[a-z\.\-]+/[A-Za-z0-9_\-/\$\{\}]{10,80})"', text)
    if url_templates:
        findings["url_templates"] = set(url_templates[:50])

    return {k: sorted(v) for k, v in findings.items()}


def mine_storage(storage_json: Path) -> dict:
    """Extract interesting values from storage.json."""
    try:
        with open(storage_json) as f:
            data = json.load(f)
    except Exception:
        return {}

    findings = {}
    for store_type, store_data in data.items():
        if not isinstance(store_data, dict):
            continue
        for key, val in store_data.items():
            val_str = str(val)
            # Flag interesting keys
            interesting = any(x in key.lower() for x in [
                "token", "auth", "cookie", "session", "key", "secret",
                "notebook", "source", "user", "account", "id", "uid",
            ])
            if interesting or len(val_str) > 50:
                findings[f"{store_type}.{key}"] = val_str[:300]
    return findings


def mine_objects(objects_json: Path) -> dict:
    """Extract interesting patterns from JS objects."""
    try:
        with open(objects_json) as f:
            objs = json.load(f)
    except Exception:
        return {}

    interesting = {}
    for obj in objs:
        obj_type = obj.get("type", "?")
        props = obj.get("properties", {})
        if not props:
            continue
        # Flag objects with interesting properties
        for k, v in props.items():
            if any(x in str(k).lower() for x in ["uuid", "id", "token", "auth", "key", "endpoint", "url", "secret"]):
                key = f"{obj_type}.{k}"
                interesting[key] = str(v)[:200]
    return interesting


def mine_credentials_txt(creds_txt: Path) -> dict:
    """Extract and categorize strings from strings_credentials.txt."""
    findings = defaultdict(list)
    try:
        lines = creds_txt.read_text(encoding="utf-8", errors="replace").splitlines()
    except Exception:
        return {}

    for line in lines:
        line = line.strip()
        if not line:
            continue
        # Categorize
        for name, pattern in PATTERNS.items():
            if name in ("json_config", "hpke_key"):
                continue
            if pattern.search(line):
                findings[name].append(line[:300])
                break
        else:
            # Uncategorized but might be interesting
            if len(line) > 30:
                findings["_other"].append(line[:200])

    return {k: list(set(v))[:20] for k, v in findings.items()}


def mine_strings_large(strings_large: Path, context_chars: int = 200) -> dict:
    """Extract patterns from large strings (high-value targets)."""
    findings = defaultdict(list)
    try:
        lines = strings_large.read_text(encoding="utf-8", errors="replace").splitlines()
    except Exception:
        return {}

    for line in lines:
        for name, pattern in PATTERNS.items():
            if name == "hpke_key":
                continue
            m = pattern.search(line)
            if m:
                val = m.group(0)
                if val not in findings[name]:
                    findings[name].append(val[:300])

    return {k: list(set(v))[:20] for k, v in findings.items()}


def deep_mine_heap(heap_dir: Path) -> dict:
    """Run all mining operations on a heap output directory."""
    name = heap_dir.name
    print(f"\n{'='*65}")
    print(f"Deep mining: {name}")
    print(f"{'='*65}")

    results = {"heap": str(heap_dir)}

    # Load existing findings
    findings_file = heap_dir / "findings.json"
    if findings_file.exists():
        with open(findings_file) as f:
            existing = json.load(f)
        results["existing_findings"] = existing.get("findings", {})
        results["summary"] = existing.get("summary", {})
        print(f"  Existing: {existing.get('summary', {}).get('total_findings', 0)} findings")

    # Mine scripts
    scripts_file = heap_dir / "scripts.js"
    if scripts_file.exists():
        print(f"  Mining scripts.js ({scripts_file.stat().st_size / 1024:.0f} KB)...")
        scripts_findings = mine_scripts(scripts_file)
        results["scripts"] = scripts_findings
        for k, v in scripts_findings.items():
            if v:
                print(f"    [{k}]: {len(v)} items")
                for item in sorted(v)[:3]:
                    print(f"      {item[:100]}")

    # Mine storage
    storage_file = heap_dir / "storage.json"
    if storage_file.exists():
        storage_data = mine_storage(storage_file)
        if storage_data:
            results["storage"] = storage_data
            print(f"\n  Storage items ({len(storage_data)}):")
            for k, v in sorted(storage_data.items())[:10]:
                print(f"    {k}: {v[:80]}")

    # Mine objects
    objects_file = heap_dir / "objects.json"
    if objects_file.exists():
        obj_data = mine_objects(objects_file)
        if obj_data:
            results["objects"] = obj_data
            print(f"\n  Interesting object properties ({len(obj_data)}):")
            for k, v in sorted(obj_data.items())[:10]:
                print(f"    {k}: {v[:80]}")

    # Mine credentials txt
    creds_file = heap_dir / "strings_credentials.txt"
    if creds_file.exists():
        print(f"\n  Mining strings_credentials.txt ({creds_file.stat().st_size / 1024:.0f} KB)...")
        creds_data = mine_credentials_txt(creds_file)
        results["credentials_txt"] = creds_data
        for k, v in sorted(creds_data.items()):
            if v and k != "_other":
                print(f"    [{k}]: {len(v)} items")
                for item in v[:3]:
                    print(f"      {item[:120]}")

    # Mine large strings
    large_file = heap_dir / "strings_large.txt"
    if large_file.exists():
        print(f"\n  Mining strings_large.txt ({large_file.stat().st_size / 1024:.0f} KB)...")
        large_data = mine_strings_large(large_file)
        results["large_strings"] = large_data
        for k, v in sorted(large_data.items()):
            if v and k not in ("notebook_uuid", "_other"):
                print(f"    [{k}]: {len(v)} items")
                for item in v[:3]:
                    print(f"      {item[:120]}")

    return results


def cross_heap_diff(heap_dirs: list[Path]) -> dict:
    """Compare API surfaces across heaps to find unique endpoints per heap."""
    surfaces: dict[str, set] = {}
    for d in heap_dirs:
        api_file = d / "api_surface.txt"
        if api_file.exists():
            lines = set(api_file.read_text(encoding="utf-8", errors="replace").splitlines())
            surfaces[d.name] = lines

    if not surfaces:
        return {}

    # Common to all
    common = set.intersection(*surfaces.values()) if len(surfaces) > 1 else set()
    # Unique per heap
    unique: dict[str, list] = {}
    for name, entries in surfaces.items():
        uniq = entries - common
        unique[name] = sorted(uniq)

    print(f"\n{'='*65}")
    print("CROSS-HEAP API SURFACE DIFF")
    print(f"{'='*65}")
    print(f"  Common across all heaps: {len(common)} entries")
    for name, uniq in sorted(unique.items()):
        print(f"  Unique to {name}: {len(uniq)} entries")
        # Show first 5 interesting ones
        interesting = [e for e in uniq if any(
            x in e.lower() for x in ["rpc", "endpoint", "service", "api", "grpc", "internal", "google"]
        )]
        for e in interesting[:5]:
            print(f"    {e[:100]}")

    return {"common": sorted(common), "unique": {k: v[:100] for k, v in unique.items()}}


def run_all() -> None:
    """Mine all available heap output directories."""
    heap_dirs = sorted(HEAP_OUTPUT_DIR.glob("*_deep"))
    if not heap_dirs:
        print(f"No heap output dirs found in {HEAP_OUTPUT_DIR}")
        return

    print(f"Found {len(heap_dirs)} heap output dirs:")
    for d in heap_dirs:
        print(f"  {d.name}")

    all_results = {}
    global_scripts: dict[str, set] = defaultdict(set)

    for heap_dir in heap_dirs:
        r = deep_mine_heap(heap_dir)
        all_results[heap_dir.name] = r

        # Aggregate script findings
        for k, v in r.get("scripts", {}).items():
            global_scripts[k].update(v)

    # Cross-heap diff
    diff = cross_heap_diff(heap_dirs)

    # Global summary
    print(f"\n{'='*65}")
    print("GLOBAL SCRIPT MINING SUMMARY (all heaps)")
    print(f"{'='*65}")
    for k, v in sorted(global_scripts.items()):
        if v and k not in ("notebook_uuid",):
            print(f"\n  [{k}] ({len(v)} unique):")
            for item in sorted(v)[:8]:
                print(f"    {item[:120]}")

    # Save full results
    out = HEAP_OUTPUT_DIR / "deep_mine_results.json"

    def default(o):
        if isinstance(o, set):
            return sorted(o)
        return str(o)

    with open(out, "w") as f:
        json.dump({
            "heaps": all_results,
            "cross_diff": diff,
            "global_scripts": {k: sorted(v) for k, v in global_scripts.items()},
        }, f, indent=2, default=default)
    print(f"\n\nFull results saved: {out} ({out.stat().st_size / 1024:.0f} KB)")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Deep extract from heap outputs")
    parser.add_argument("--heap", help="Single heap dir to mine (default: all)")
    args = parser.parse_args()

    if args.heap:
        deep_mine_heap(Path(args.heap))
    else:
        run_all()
