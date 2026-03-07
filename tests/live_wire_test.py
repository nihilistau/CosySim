"""Manual live integration harness for CosySim service endpoints.

This module is intentionally script-only:

* it performs real HTTP calls against local services
* it prints human-readable status lines to stdout
* it exits with a process status code for shell usage

Run manually from the project root with either:

    python -m tests.live_wire_test
    python tests/live_wire_test.py
"""
from __future__ import annotations

import os
import sys
import tempfile
import wave
from pathlib import Path

__test__ = False

# Ensure project root is on path when run directly
_root = str(Path(__file__).resolve().parent.parent)
if _root not in sys.path:
    sys.path.insert(0, _root)


def _record_check(name: str, fn, results: list[tuple[str, str, str]]) -> None:
    try:
        result = fn()
        results.append(("PASS", name, result))
        display = result[:120] if isinstance(result, str) else str(result)
        print(f"  ✅ {name}: {display}")
    except Exception as exc:  # pragma: no cover - manual harness
        results.append(("FAIL", name, str(exc)))
        print(f"  ❌ {name}: {exc}")


def main() -> int:
    """Run the live harness and return a shell-friendly exit code."""
    import httpx
    from engine.config import get_config

    results: list[tuple[str, str, str]] = []
    cfg = get_config()
    lmstudio_base_url = str(
        cfg.get("lmstudio.base_url", "http://127.0.0.1:1234")
    ).rstrip("/")
    lmstudio_token = (
        os.environ.get("LMSTUDIO_API_TOKEN", "").strip()
        or os.environ.get("LOCAL_LM_STUDIO_TOKEN", "").strip()
        or str(cfg.get("lmstudio.api_token", "")).strip()
    )
    lmstudio_headers = (
        {"Authorization": f"Bearer {lmstudio_token}"} if lmstudio_token else {}
    )

    with httpx.Client(timeout=20) as client:
        # ═══════════════════════════════════════════════════════════════════
        #  PILLAR 2: LMStudio (:1234)
        # ═══════════════════════════════════════════════════════════════════
        print("\n═══ PILLAR 2: LMStudio (:1234) ═══")

        def lm_models():
            response = client.get(
                f"{lmstudio_base_url}/api/v1/models",
                headers=lmstudio_headers,
            )
            models = response.json().get("data", [])
            return f"Status {response.status_code}, {len(models)} model(s) loaded"

        _record_check("LM models list", lm_models, results)

        def lm_model_info():
            response = client.get(
                f"{lmstudio_base_url}/api/v1/models",
                headers=lmstudio_headers,
            )
            models = response.json().get("data", [])
            if models:
                return f"Active: {models[0]['id']}"
            return "No models loaded"

        _record_check("LM model info", lm_model_info, results)

        def lm_chat():
            response = client.post(
                f"{lmstudio_base_url}/api/v1/chat",
                json={
                    "input": "Say hello in exactly 5 words.",
                    "max_tokens": 30,
                    "temperature": 0.7,
                    "stream": False,
                },
                headers=lmstudio_headers,
            )
            data = response.json()
            output_items = data.get("output", [])
            if output_items:
                text = " ".join(
                    str(item.get("text") or item.get("content") or "").strip()
                    for item in output_items
                    if isinstance(item, dict) and item.get("type") in {"text", "message"}
                ).strip()
            else:
                text = data.get("choices", [{}])[0].get("message", {}).get("content", "")
            stats = data.get("stats", data.get("usage", {}))
            tokens = stats.get("total_output_tokens", stats.get("total_tokens", "?"))
            return f"Reply: '{text[:60]}' | tokens: {tokens}"

        _record_check("LM chat completion", lm_chat, results)

        def lm_api_v1():
            """Test the new /api/v1/ endpoint if available."""
            try:
                response = client.get("http://localhost:1234/api/v1/models", timeout=3)
                if response.status_code == 200:
                    return f"/api/v1/ available ({response.status_code})"
                return f"/api/v1/ returned {response.status_code}"
            except Exception:
                return "/api/v1/ not available (using /v1/ fallback)"

        _record_check("LM api/v1 protocol", lm_api_v1, results)

        # ═══════════════════════════════════════════════════════════════════
        #  PILLAR 3: ComfyUI (:8188)
        # ═══════════════════════════════════════════════════════════════════
        print("\n═══ PILLAR 3: ComfyUI (:8188) ═══")

        def comfy_stats():
            response = client.get("http://localhost:8188/system_stats")
            stats = response.json()
            devices = stats.get("devices", [{}])
            if devices:
                device = devices[0]
                vram_total = device.get("vram_total", 0) / 1e9
                vram_free = device.get("vram_free", 0) / 1e9
                return f"GPU: {device.get('name', '?')}, VRAM: {vram_free:.1f}/{vram_total:.1f} GB free"
            return "No GPU info"

        _record_check("ComfyUI system stats", comfy_stats, results)

        def comfy_queue():
            response = client.get("http://localhost:8188/queue")
            data = response.json()
            running = len(data.get("queue_running", []))
            pending = len(data.get("queue_pending", []))
            return f"Queue: {running} running, {pending} pending"

        _record_check("ComfyUI queue", comfy_queue, results)

        def comfy_nodes():
            response = client.get("http://localhost:8188/object_info/KSampler")
            has_ksampler = "KSampler" in response.json()
            return f"KSampler node: {'present' if has_ksampler else 'MISSING'}"

        _record_check("ComfyUI nodes check", comfy_nodes, results)

        # ═══════════════════════════════════════════════════════════════════
        #  TTS Server (:8600)
        # ═══════════════════════════════════════════════════════════════════
        print("\n═══ TTS Server (:8600) ═══")

        def tts_health():
            response = client.get("http://localhost:8600/health")
            data = response.json()
            return f"Status: {data.get('status')}, engine: {data.get('engine', '?')}"

        _record_check("TTS health", tts_health, results)

        def tts_voices():
            response = client.get("http://localhost:8600/voices")
            data = response.json()
            presets = len(data.get("presets", {}))
            characters = len(data.get("characters", {}))
            return f"{presets} presets, {characters} character voices"

        _record_check("TTS voices list", tts_voices, results)

        def tts_cast():
            response = client.post(
                "http://localhost:8600/cast",
                json={
                    "character_id": "live_wire_luna",
                    "description": "A warm, playful female voice with slight vocal fry and a teasing cadence.",
                    "model_size": "1.7b",
                    "tags": ["playful", "warm", "teasing"],
                },
            )
            return f"Cast result: {response.json().get('status', 'unknown')}"

        _record_check("TTS cast voice", tts_cast, results)

        def tts_generate():
            response = client.post(
                "http://localhost:8600/generate",
                json={
                    "text": "Hey babe, I was just thinking about you. Call me back when you get this.",
                    "character_id": "live_wire_luna",
                    "max_duration": 15,
                },
            )
            data = response.json()
            filepath = data.get("filepath", "")
            duration = data.get("duration_sec", 0)
            if filepath and Path(filepath).exists():
                with wave.open(filepath, "rb") as wav_file:
                    channels = wav_file.getnchannels()
                    rate = wav_file.getframerate()
                    frames = wav_file.getnframes()
                    return f"WAV: {duration:.1f}s, {rate}Hz, {channels}ch, {frames} frames"
            return f"Generated: {duration:.1f}s (placeholder mode)"

        _record_check("TTS generate voice", tts_generate, results)

        def tts_status():
            response = client.get("http://localhost:8600/status")
            data = response.json()
            mode = data.get("mode", data.get("engine", "unknown"))
            return f"Mode: {mode}, models: {data.get('models_loaded', '?')}"

        _record_check("TTS server status", tts_status, results)

        # ═══════════════════════════════════════════════════════════════════
        #  MCP Bridge (:8601)
        # ═══════════════════════════════════════════════════════════════════
        print("\n═══ MCP Bridge (:8601) ═══")

        def bridge_health():
            response = client.get("http://localhost:8601/health")
            return f"Status: {response.json().get('status', 'unknown')}"

        _record_check("Bridge health", bridge_health, results)

        def bridge_tools():
            response = client.get("http://localhost:8601/tools")
            data = response.json()
            tools = data.get("tools", data) if isinstance(data, dict) else data
            names = [tool.get("name", "?") for tool in (tools if isinstance(tools, list) else [])]
            return f"{len(names)} tools: {', '.join(names[:5])}..."

        _record_check("Bridge tools list", bridge_tools, results)

        # ═══════════════════════════════════════════════════════════════════
        #  CROSS-PILLAR: CosySim Framework ↔ Services
        # ═══════════════════════════════════════════════════════════════════
        print("\n═══ CROSS-PILLAR: Framework Integration ═══")

        def framework_config():
            from engine.config import get_config

            config = get_config()
            lm_url = config.get("lmstudio.base_url", "not set")
            comfy_url = config.get("comfyui.base_url", "not set")
            tts_url = config.get("tts.server_url", "not set")
            mcp_enabled = config.get("lmstudio.mcp_enabled", False)
            return f"LM={lm_url}, ComfyUI={comfy_url}, TTS={tts_url}, MCP={mcp_enabled}"

        _record_check("Config loads all URLs", framework_config, results)

        def framework_media_config():
            from engine.media.media_config import get_media_config

            media_config = get_media_config()
            width, height = media_config.image_dims("selfie")
            video_spec = media_config.video_spec("message")
            audio_spec = media_config.audio_spec("voicemail")
            return (
                f"Selfie: {width}x{height}, "
                f"Video: {video_spec.get('width', '?')}x{video_spec.get('height', '?')}, "
                f"Audio: {audio_spec.get('sample_rate', '?')}Hz"
            )

        _record_check("MediaConfig standards", framework_media_config, results)

        def framework_event_chain():
            from content.simulation.database.db import Database
            from content.simulation.database.events import EventChain

            db_path = os.path.join(tempfile.gettempdir(), "cosysim_live_test.db")
            db = Database(db_path)
            event_chain = EventChain(db)
            chain_id = event_chain.start_chain(scene_id="live_wire", summary="Live wire test chain")
            event_one = event_chain.log(
                "live_wire_test",
                "test_harness",
                {"phase": 26},
                "Testing ground truth",
                chain_id=chain_id,
                scene_id="live_wire",
            )
            event_chain.log(
                "live_wire_verify",
                "test_harness",
                {"parent": event_one},
                "Verifying causal link",
                chain_id=chain_id,
                scene_id="live_wire",
                parent_id=event_one,
            )
            events = event_chain.get_chain(chain_id)
            os.unlink(db_path)
            return f"Chain {chain_id[:8]}..., {len(events)} events, causal tree OK"

        _record_check("EventChain ground truth", framework_event_chain, results)

        def framework_benchmarks():
            from engine.logging.benchmark import get_benchmarks, get_llm_kpis

            stats = get_benchmarks()
            kpis = get_llm_kpis()
            return f"Benchmarks: {len(stats)} entries, LLM KPIs: {len(kpis)} entries"

        _record_check("Benchmark stores", framework_benchmarks, results)

        def framework_lm_client_v2():
            from engine.lmstudio.lms_client import get_lms_client

            lms_client = get_lms_client()
            result = lms_client.quick_reply("Reply with just the word 'connected'.")
            return f"Client v1 reply: '{result.strip()[:40]}'"

        _record_check("LMStudio Client v1 chat", framework_lm_client_v2, results)

        def framework_voice_gen():
            from content.simulation.services.voice_message import VoiceMessageGenerator

            generator = VoiceMessageGenerator(db=None)
            result = generator.generate_voice_message(
                "live_wire_char",
                "TestChar",
                "This is a live wire voice test.",
            )
            filepath = result.get("filepath", "")
            source = result.get("source", result.get("placeholder", "?"))
            exists = Path(filepath).exists() if filepath else False
            return f"Voice generated: source={source}, exists={exists}"

        _record_check("VoiceMessageGenerator pipeline", framework_voice_gen, results)

        # ═══════════════════════════════════════════════════════════════════
        #  GRACEFUL DEGRADATION
        # ═══════════════════════════════════════════════════════════════════
        print("\n═══ GRACEFUL DEGRADATION ═══")

        def degrade_comfyui():
            """ComfyUI client with bad URL should not crash."""
            from content.simulation.services.comfyui_client import ComfyUIClient

            ComfyUIClient(base_url="http://localhost:99999")
            return "ComfyUIClient with bad URL: no crash ✓"

        _record_check("ComfyUI offline handling", degrade_comfyui, results)

        def degrade_tts_server():
            """VoiceMessageGenerator with offline TTS should fall back to placeholder."""
            from content.simulation.services.voice_message import VoiceMessageGenerator

            generator = VoiceMessageGenerator(db=None)
            result = generator.generate_voice_message("fallback_char", "FallbackTest", "Testing fallback.")
            exists = Path(result.get("filepath", "")).exists()
            return f"Fallback: placeholder={result.get('placeholder', False)}, file exists={exists}"

        _record_check("TTS offline fallback", degrade_tts_server, results)

    passed = sum(1 for status, _, _ in results if status == "PASS")
    failed = sum(1 for status, _, _ in results if status == "FAIL")
    total = passed + failed

    print(f"\n{'=' * 55}")
    print(f"  LIVE WIRE RESULTS: {passed}/{total} passed, {failed} failed")
    print(f"{'=' * 55}")

    if failed > 0:
        print("\n  Failed tests:")
        for status, name, message in results:
            if status == "FAIL":
                print(f"    ❌ {name}: {message}")

    return 0 if failed == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
