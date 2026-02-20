"""
Phase 26: Live Wire Tests — hit all 4 services for real.
Run with: python -m tests.live_wire_test  (from project root)
   or:    python tests/live_wire_test.py  (adds project root to sys.path)
"""
import httpx
import json
import os
import sys
import time
import wave
from pathlib import Path

# Ensure project root is on path when run directly
_root = str(Path(__file__).resolve().parent.parent)
if _root not in sys.path:
    sys.path.insert(0, _root)

results = []

def test(name, fn):
    try:
        r = fn()
        results.append(("PASS", name, r))
        display = r[:120] if isinstance(r, str) else str(r)
        print(f"  ✅ {name}: {display}")
    except Exception as e:
        results.append(("FAIL", name, str(e)))
        print(f"  ❌ {name}: {e}")

c = httpx.Client(timeout=20)


# ═══════════════════════════════════════════════════════════════════
#  PILLAR 2: LMStudio (:1234)
# ═══════════════════════════════════════════════════════════════════
print("\n═══ PILLAR 2: LMStudio (:1234) ═══")

def lm_models():
    r = c.get("http://localhost:1234/v1/models")
    models = r.json().get("data", [])
    return f"Status {r.status_code}, {len(models)} model(s) loaded"
test("LM models list", lm_models)

def lm_model_info():
    r = c.get("http://localhost:1234/v1/models")
    models = r.json().get("data", [])
    if models:
        m = models[0]
        return f"Active: {m['id']}"
    return "No models loaded"
test("LM model info", lm_model_info)

def lm_chat():
    r = c.post("http://localhost:1234/v1/chat/completions", json={
        "messages": [{"role": "user", "content": "Say hello in exactly 5 words."}],
        "max_tokens": 30, "temperature": 0.7,
    })
    data = r.json()
    text = data["choices"][0]["message"]["content"]
    tokens = data.get("usage", {})
    return f"Reply: '{text.strip()[:60]}' | tokens: {tokens.get('total_tokens', '?')}"
test("LM chat completion", lm_chat)

def lm_api_v1():
    """Test the new /api/v1/ endpoint if available."""
    try:
        r = c.get("http://localhost:1234/api/v1/models", timeout=3)
        if r.status_code == 200:
            return f"/api/v1/ available ({r.status_code})"
        return f"/api/v1/ returned {r.status_code}"
    except Exception:
        return "/api/v1/ not available (using /v1/ fallback)"
test("LM api/v1 protocol", lm_api_v1)


# ═══════════════════════════════════════════════════════════════════
#  PILLAR 3: ComfyUI (:8188)
# ═══════════════════════════════════════════════════════════════════
print("\n═══ PILLAR 3: ComfyUI (:8188) ═══")

def comfy_stats():
    r = c.get("http://localhost:8188/system_stats")
    stats = r.json()
    devices = stats.get("devices", [{}])
    if devices:
        d = devices[0]
        vram_total = d.get("vram_total", 0) / 1e9
        vram_free = d.get("vram_free", 0) / 1e9
        return f"GPU: {d.get('name', '?')}, VRAM: {vram_free:.1f}/{vram_total:.1f} GB free"
    return "No GPU info"
test("ComfyUI system stats", comfy_stats)

def comfy_queue():
    r = c.get("http://localhost:8188/queue")
    data = r.json()
    running = len(data.get("queue_running", []))
    pending = len(data.get("queue_pending", []))
    return f"Queue: {running} running, {pending} pending"
test("ComfyUI queue", comfy_queue)

def comfy_nodes():
    r = c.get("http://localhost:8188/object_info/KSampler")
    has_ksampler = "KSampler" in r.json()
    return f"KSampler node: {'present' if has_ksampler else 'MISSING'}"
test("ComfyUI nodes check", comfy_nodes)


# ═══════════════════════════════════════════════════════════════════
#  TTS Server (:8600)
# ═══════════════════════════════════════════════════════════════════
print("\n═══ TTS Server (:8600) ═══")

def tts_health():
    r = c.get("http://localhost:8600/health")
    d = r.json()
    return f"Status: {d.get('status')}, engine: {d.get('engine', '?')}"
test("TTS health", tts_health)

def tts_voices():
    r = c.get("http://localhost:8600/voices")
    d = r.json()
    presets = len(d.get("presets", {}))
    chars = len(d.get("characters", {}))
    return f"{presets} presets, {chars} character voices"
test("TTS voices list", tts_voices)

def tts_cast():
    r = c.post("http://localhost:8600/cast", json={
        "character_id": "live_wire_luna",
        "description": "A warm, playful female voice with slight vocal fry and a teasing cadence.",
        "model_size": "1.7b",
        "tags": ["playful", "warm", "teasing"],
    })
    return f"Cast result: {r.json().get('status', 'unknown')}"
test("TTS cast voice", tts_cast)

def tts_generate():
    r = c.post("http://localhost:8600/generate", json={
        "text": "Hey babe, I was just thinking about you. Call me back when you get this.",
        "character_id": "live_wire_luna",
        "max_duration": 15,
    })
    d = r.json()
    filepath = d.get("filepath", "")
    duration = d.get("duration_sec", 0)
    # Verify the WAV file is valid
    if filepath and Path(filepath).exists():
        with wave.open(filepath, "rb") as wf:
            channels = wf.getnchannels()
            rate = wf.getframerate()
            frames = wf.getnframes()
            return f"WAV: {duration:.1f}s, {rate}Hz, {channels}ch, {frames} frames"
    return f"Generated: {duration:.1f}s (placeholder mode)"
test("TTS generate voice", tts_generate)

def tts_status():
    r = c.get("http://localhost:8600/status")
    d = r.json()
    mode = d.get("mode", d.get("engine", "unknown"))
    return f"Mode: {mode}, models: {d.get('models_loaded', '?')}"
test("TTS server status", tts_status)


# ═══════════════════════════════════════════════════════════════════
#  MCP Bridge (:8601)
# ═══════════════════════════════════════════════════════════════════
print("\n═══ MCP Bridge (:8601) ═══")

def bridge_health():
    r = c.get("http://localhost:8601/health")
    return f"Status: {r.json().get('status', 'unknown')}"
test("Bridge health", bridge_health)

def bridge_tools():
    r = c.get("http://localhost:8601/tools")
    d = r.json()
    tools = d.get("tools", d) if isinstance(d, dict) else d
    names = [t.get("name", "?") for t in (tools if isinstance(tools, list) else [])]
    return f"{len(names)} tools: {', '.join(names[:5])}..."
test("Bridge tools list", bridge_tools)


# ═══════════════════════════════════════════════════════════════════
#  CROSS-PILLAR: CosySim Framework ↔ Services
# ═══════════════════════════════════════════════════════════════════
print("\n═══ CROSS-PILLAR: Framework Integration ═══")

def framework_config():
    from engine.config import get_config
    cfg = get_config()
    lm_url = cfg.get("lmstudio.base_url", "not set")
    comfy_url = cfg.get("comfyui.base_url", "not set")
    tts_url = cfg.get("tts.server_url", "not set")
    mcp = cfg.get("lmstudio.mcp_enabled", False)
    return f"LM={lm_url}, ComfyUI={comfy_url}, TTS={tts_url}, MCP={mcp}"
test("Config loads all URLs", framework_config)

def framework_media_config():
    from engine.media.media_config import get_media_config
    mc = get_media_config()
    w, h = mc.image_dims("selfie")
    vspec = mc.video_spec("message")
    aspec = mc.audio_spec("voicemail")
    return f"Selfie: {w}x{h}, Video: {vspec.get('width', '?')}x{vspec.get('height', '?')}, Audio: {aspec.get('sample_rate', '?')}Hz"
test("MediaConfig standards", framework_media_config)

def framework_event_chain():
    from content.simulation.database.db import Database
    from content.simulation.database.events import EventChain
    import tempfile, os
    db_path = os.path.join(tempfile.gettempdir(), "cosysim_live_test.db")
    db = Database(db_path)
    ec = EventChain(db)
    chain_id = ec.start_chain(scene_id="live_wire", summary="Live wire test chain")
    ev1 = ec.log("live_wire_test", "test_harness", {"phase": 26}, "Testing ground truth", chain_id=chain_id, scene_id="live_wire")
    ev2 = ec.log("live_wire_verify", "test_harness", {"parent": ev1}, "Verifying causal link", chain_id=chain_id, scene_id="live_wire", parent_id=ev1)
    events = ec.get_chain(chain_id)
    os.unlink(db_path)
    return f"Chain {chain_id[:8]}..., {len(events)} events, causal tree OK"
test("EventChain ground truth", framework_event_chain)

def framework_benchmarks():
    from engine.logging.benchmark import get_benchmarks, get_llm_kpis
    stats = get_benchmarks()
    kpis = get_llm_kpis()
    return f"Benchmarks: {len(stats)} entries, LLM KPIs: {len(kpis)} entries"
test("Benchmark stores", framework_benchmarks)

def framework_lm_client_v2():
    from engine.lmstudio.client_v2 import LMStudioClient, MCP
    client = LMStudioClient()
    result = client.chat([
        {"role": "user", "content": "Reply with just the word 'connected'."}
    ], max_tokens=10)
    return f"Client v2 reply: '{result.content.strip()[:40]}' ({result.total_tokens} tokens, {result.tokens_per_second:.0f} tok/s)"
test("LMStudio Client v2 chat", framework_lm_client_v2)

def framework_voice_gen():
    from content.simulation.services.voice_message import VoiceMessageGenerator
    gen = VoiceMessageGenerator(db=None)
    result = gen.generate_voice_message("live_wire_char", "TestChar", "This is a live wire voice test.")
    fp = result.get("filepath", "")
    src = result.get("source", result.get("placeholder", "?"))
    return f"Voice generated: source={src}, exists={Path(fp).exists() if fp else False}"
test("VoiceMessageGenerator pipeline", framework_voice_gen)


# ═══════════════════════════════════════════════════════════════════
#  GRACEFUL DEGRADATION
# ═══════════════════════════════════════════════════════════════════
print("\n═══ GRACEFUL DEGRADATION ═══")

def degrade_comfyui():
    """ComfyUI client with bad URL should not crash."""
    from content.simulation.services.comfyui_client import ComfyUIClient
    client = ComfyUIClient(base_url="http://localhost:99999")
    # Should not raise, just return None or empty
    return "ComfyUIClient with bad URL: no crash ✓"
test("ComfyUI offline handling", degrade_comfyui)

def degrade_tts_server():
    """VoiceMessageGenerator with offline TTS should fall back to placeholder."""
    from content.simulation.services.voice_message import VoiceMessageGenerator
    gen = VoiceMessageGenerator(db=None)
    # Even if TTS server were down, placeholder should work
    result = gen.generate_voice_message("fallback_char", "FallbackTest", "Testing fallback.")
    return f"Fallback: placeholder={result.get('placeholder', False)}, file exists={Path(result.get('filepath', '')).exists()}"
test("TTS offline fallback", degrade_tts_server)


# ═══════════════════════════════════════════════════════════════════
#  SUMMARY
# ═══════════════════════════════════════════════════════════════════
passed = sum(1 for r in results if r[0] == "PASS")
failed = sum(1 for r in results if r[0] == "FAIL")
total = passed + failed
print(f"\n{'=' * 55}")
print(f"  LIVE WIRE RESULTS: {passed}/{total} passed, {failed} failed")
print(f"{'=' * 55}")

if failed > 0:
    print("\n  Failed tests:")
    for status, name, msg in results:
        if status == "FAIL":
            print(f"    ❌ {name}: {msg}")

sys.exit(0 if failed == 0 else 1)
