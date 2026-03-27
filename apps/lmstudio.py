#!/usr/bin/env python3
"""
LMStudio CLI - Local LLM Management
=======================================

Check LMStudio status, list models, run quick inference, benchmark,
and manage the model proxy.

Version: v1.57.2 [2026-03-27]
Author:  CosySim Team

Change Log:
    v1.57.2 [2026-03-27] - Initial standalone CLI

Usage:
    python apps/lmstudio.py status             # Check LMStudio health + loaded models
    python apps/lmstudio.py models             # List available models
    python apps/lmstudio.py chat "prompt"      # Quick one-shot inference
    python apps/lmstudio.py bench              # Run latency benchmark
    python apps/lmstudio.py proxy              # Start OpenAI-compatible proxy (:5800)
"""
from __future__ import annotations

import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _bootstrap import bootstrap, run, SCRIPTS, ROOT
bootstrap()


def main() -> int:
    if not sys.argv[1:] or sys.argv[1] in ("-h", "--help"):
        print("""
  LMStudio - Local LLM Management v1.57.2
  =========================================

  Usage: python apps/lmstudio.py <command> [args...]

  Commands:
    status              Check LMStudio health + loaded models
    models              List available models
    chat "prompt"       Quick one-shot inference
    bench               Run latency benchmark (5 prompts)
    proxy               Start OpenAI-compatible proxy server (:5800)
""")
        return 0

    cmd = sys.argv[1]
    rest = sys.argv[2:]

    if cmd == "status":
        return _cmd_status()
    elif cmd == "models":
        return _cmd_models()
    elif cmd == "chat":
        return _cmd_chat(rest)
    elif cmd == "bench":
        return _cmd_bench()
    elif cmd == "proxy":
        return run(SCRIPTS / "model_proxy.py", rest)
    else:
        print(f"Unknown command: {cmd}")
        return 1


def _cmd_status() -> int:
    """Check LMStudio health and loaded models."""
    try:
        from engine.lmstudio.lms_client import get_lms_client
        client = get_lms_client()

        if not client.is_ready():
            print("  LMStudio: OFFLINE (port 1234)")
            return 1

        models = client.list_models()
        print(f"  LMStudio: ONLINE (port 1234)")
        print(f"  Models loaded: {len(models)}")
        for m in models:
            mid = m.get("id", "unknown")
            print(f"    - {mid}")
        return 0

    except Exception as e:
        print(f"  LMStudio: ERROR - {e}")
        return 1


def _cmd_models() -> int:
    """List available models."""
    try:
        from engine.lmstudio.lms_client import get_lms_client
        client = get_lms_client()
        models = client.list_models()
        if not models:
            print("  No models loaded.")
            return 0
        print(f"\n  Available Models ({len(models)})")
        print(f"  {'-' * 50}")
        for m in models:
            print(f"  {m.get('id', 'unknown')}")
        print()
        return 0
    except Exception as e:
        print(f"ERROR: {e}")
        return 1


def _cmd_chat(args: list[str]) -> int:
    """Quick one-shot inference."""
    if not args:
        print("Usage: lmstudio chat \"your prompt here\"")
        return 1

    prompt = " ".join(args)
    try:
        from engine.lmstudio.chat import chat
        t0 = time.time()
        reply = chat([{"role": "user", "content": prompt}])
        elapsed = time.time() - t0
        print(reply)
        print(f"\n  [{elapsed:.1f}s]")
        return 0
    except Exception as e:
        print(f"ERROR: {e}")
        return 1


def _cmd_bench() -> int:
    """Run a quick latency benchmark."""
    prompts = [
        "Say hello in one word.",
        "What is 2+2?",
        "Name one color.",
        "Count to 3.",
        "Say yes or no.",
    ]

    try:
        from engine.lmstudio.chat import chat
        print("  LMStudio Benchmark (5 prompts)")
        print(f"  {'-' * 40}")

        times = []
        for p in prompts:
            t0 = time.time()
            reply = chat([{"role": "user", "content": p}], max_tokens=20)
            elapsed = (time.time() - t0) * 1000
            times.append(elapsed)
            print(f"  {elapsed:>7.0f}ms  {p[:30]}")

        avg = sum(times) / len(times)
        p95 = sorted(times)[int(len(times) * 0.95)]
        print(f"  {'-' * 40}")
        print(f"  avg: {avg:.0f}ms  p95: {p95:.0f}ms")
        return 0

    except Exception as e:
        print(f"ERROR: {e}")
        return 1


if __name__ == "__main__":
    sys.exit(main())
