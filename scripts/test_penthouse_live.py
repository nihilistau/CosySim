"""Live penthouse endpoint tests — verifies character loading, listing, models, and chat."""
import logging
import sys
import threading
import time

logging.basicConfig(level=logging.WARNING, stream=sys.stderr)

import requests
from content.scenes.penthouse.penthouse_scene import PenthouseScene


def main():
    # Kill any stale penthouse on the same port
    scene = PenthouseScene()
    base = f"http://127.0.0.1:{scene.port}"
    
    # Pre-flight: make sure port is free
    try:
        r = requests.get(f"{base}/api/health", timeout=2)
        print(f"WARNING: Port {scene.port} already in use — stale process? Aborting.", flush=True)
        sys.exit(1)
    except requests.ConnectionError:
        pass  # Good — port is free
    
    # Start server in background thread
    t = threading.Thread(target=scene.start, daemon=True)
    t.start()
    time.sleep(4)

    passed, failed = 0, 0

    def check(name: str, ok: bool, detail: str = ""):
        nonlocal passed, failed
        if ok:
            passed += 1
            print(f"  ✓ {name}", flush=True)
        else:
            failed += 1
            print(f"  ✗ {name}: {detail}", flush=True)

    # ── Health ──
    print("\n[1] Health check", flush=True)
    try:
        r = requests.get(f"{base}/api/health", timeout=5)
        check("GET /api/health", r.status_code == 200, f"status={r.status_code}")
    except Exception as e:
        check("GET /api/health", False, str(e))

    # ── Character list (before loading) ──
    print("\n[2] Character list (empty scene)", flush=True)
    try:
        r = requests.get(f"{base}/api/characters/list", timeout=5)
        data = r.json()
        check("GET /api/characters/list returns 200", r.status_code == 200)
        check("Has 5 seeded characters", data.get("count", 0) == 5, f"count={data.get('count')}")
        check("None loaded yet", all(not c.get("loaded") for c in data.get("characters", [])))
    except Exception as e:
        check("GET /api/characters/list", False, str(e))

    # ── Load character (lola) ──
    print("\n[3] Load character: lola", flush=True)
    try:
        r = requests.post(f"{base}/api/character/load", json={"character_id": "lola"}, timeout=10)
        data = r.json()
        check("POST /api/character/load returns 200", r.status_code == 200, f"status={r.status_code} body={data}")
        check("success=True", data.get("success") is True)
        check("Character name is Lola Voss", data.get("character", {}).get("name") == "Lola Voss", 
              f"name={data.get('character', {}).get('name')}")
    except Exception as e:
        check("POST /api/character/load lola", False, str(e))

    # ── Load second character (aria) ──
    print("\n[4] Load character: aria", flush=True)
    try:
        r = requests.post(f"{base}/api/character/load", json={"character_id": "aria"}, timeout=10)
        data = r.json()
        check("POST /api/character/load aria returns 200", r.status_code == 200, f"status={r.status_code} body={data}")
        check("success=True", data.get("success") is True)
    except Exception as e:
        check("POST /api/character/load aria", False, str(e))

    # ── Reject third character (max 2) ──
    print("\n[5] Reject third character", flush=True)
    try:
        r = requests.post(f"{base}/api/character/load", json={"character_id": "mira"}, timeout=10)
        check("Third character rejected with 400", r.status_code == 400, f"status={r.status_code}")
    except Exception as e:
        check("Reject third character", False, str(e))

    # ── Loaded characters list ──
    print("\n[6] Loaded characters", flush=True)
    try:
        r = requests.get(f"{base}/api/characters/loaded", timeout=5)
        data = r.json()
        check("GET /api/characters/loaded returns 200", r.status_code == 200)
        chars = data.get("characters", {})
        check("lola in loaded", "lola" in chars, f"loaded={list(chars.keys())}")
        check("aria in loaded", "aria" in chars, f"loaded={list(chars.keys())}")
    except Exception as e:
        check("GET /api/characters/loaded", False, str(e))

    # ── Models available ──
    print("\n[7] Models endpoint", flush=True)
    try:
        r = requests.get(f"{base}/api/models/available", timeout=10)
        check("GET /api/models/available returns 200", r.status_code == 200, f"status={r.status_code}")
    except Exception as e:
        check("GET /api/models/available", False, str(e))

    # ── Remove character ──
    print("\n[8] Remove character: aria", flush=True)
    try:
        r = requests.post(f"{base}/api/character/remove", json={"character_id": "aria"}, timeout=5)
        check("POST /api/character/remove returns 200", r.status_code == 200)
        check("Only lola remains", list(scene.characters.keys()) == ["lola"], 
              f"chars={list(scene.characters.keys())}")
    except Exception as e:
        check("POST /api/character/remove", False, str(e))

    # ── Reload lola (idempotent) ──
    print("\n[9] Reload lola (idempotent)", flush=True)
    try:
        r = requests.post(f"{base}/api/character/load", json={"character_id": "lola"}, timeout=10)
        check("Reloading existing char returns 200", r.status_code == 200, f"status={r.status_code}")
    except Exception as e:
        check("Reload lola", False, str(e))

    # ── Summary ──
    total = passed + failed
    print(f"\n{'='*40}", flush=True)
    print(f"Results: {passed}/{total} passed, {failed} failed", flush=True)
    print(f"{'='*40}", flush=True)

    scene.stop()
    sys.exit(1 if failed > 0 else 0)


if __name__ == "__main__":
    main()
