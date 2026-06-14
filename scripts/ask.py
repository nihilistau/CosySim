"""Unified AI CLI — prompt any model from one command.

Routes to GitHub Copilot (38 frontier models), NotebookLM (Gemini via CDP),
or local LMStudio. All free, all from one interface.

Usage:
    python scripts/ask.py "your prompt here"                      # default: gpt-5.4
    python scripts/ask.py "your prompt" --model claude-opus-4.6   # Anthropic
    python scripts/ask.py "your prompt" --model gemini-3.1-pro    # Google
    python scripts/ask.py "your prompt" --model gpt-5.2-codex     # OpenAI
    python scripts/ask.py "your prompt" --model grok-code-fast-1  # xAI
    python scripts/ask.py "your prompt" --nlm                     # NotebookLM (grounded)
    python scripts/ask.py "your prompt" --local                   # LMStudio
    python scripts/ask.py --models                                # list all models
    python scripts/ask.py --models --vendor anthropic             # filter by vendor

Version: v1.50.1 [2026-03-23]
Author:  CosySim Team
"""
from __future__ import annotations

import argparse
import asyncio
import json
import sys
import time
from pathlib import Path
from typing import Optional

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))


# ──── Backends ────────────────────────────────────────────────────────────────

def ask_copilot(prompt: str, model: str = "gpt-5.4", account: str = "nihilistcod") -> str:
    """Send prompt to GitHub Copilot."""
    from engine.integrations.github_copilot_client import GithubCopilotClient

    client = GithubCopilotClient(account)
    thread_id = client.create_thread()
    response = client.send_message(thread_id, prompt, model=model)
    if isinstance(response, tuple):
        return response[0] if response[0] else str(response)
    return str(response)


def ask_nlm(prompt: str, port: int = 9223) -> str:
    """Send prompt to NotebookLM via CDP browser fetch."""
    from scripts.nlm_ask import ask
    return asyncio.run(ask(prompt, port))


def ask_local(prompt: str, model: Optional[str] = None) -> str:
    """Send prompt to local LMStudio."""
    from engine.lmstudio.lms_client import get_lms_client

    client = get_lms_client()
    kwargs = {}
    if model:
        kwargs["model"] = model
    response = client.quick_reply(prompt, **kwargs)
    return str(response)


def list_models(vendor_filter: Optional[str] = None) -> None:
    """List all available models across backends."""
    # Copilot models
    try:
        from engine.integrations.github_copilot_client import GithubCopilotClient
        client = GithubCopilotClient("nihilistcod")
        models = client.list_models()
        seen = set()
        print("=== GitHub Copilot ===")
        for m in models:
            name = m.get("name", "")
            vendor = m.get("vendor", "")
            mid = m.get("id", name).lower().replace(" ", "-")
            if name in seen:
                continue
            seen.add(name)
            if vendor_filter and vendor_filter.lower() not in vendor.lower():
                continue
            print(f"  {mid:<35} {vendor}")
    except Exception as exc:
        print(f"  Copilot unavailable: {exc}")

    # NLM
    if not vendor_filter or "google" in vendor_filter.lower() or "nlm" in vendor_filter.lower():
        try:
            import urllib.request
            tabs = json.loads(urllib.request.urlopen("http://localhost:9223/json", timeout=2).read())
            nlm_live = any("notebooklm" in t.get("url", "") for t in tabs)
            print(f"\n=== NotebookLM (CDP) ===")
            print(f"  nlm{' ':31} {'LIVE' if nlm_live else 'OFFLINE'}")
        except Exception:
            print(f"\n=== NotebookLM (CDP) ===")
            print(f"  nlm{' ':31} OFFLINE")

    # Local LMStudio
    if not vendor_filter or "local" in vendor_filter.lower() or "lm" in vendor_filter.lower():
        try:
            from engine.lmstudio.lms_client import get_lms_client
            client = get_lms_client()
            if client.is_available():
                models = client.get_models()
                print(f"\n=== LMStudio (Local) ===")
                for m in models:
                    name = m.key if hasattr(m, "key") else str(m)
                    loaded = "(loaded)" if hasattr(m, "is_loaded") and m.is_loaded else ""
                    print(f"  {str(name)[:35]:<35} {loaded}")
            else:
                print(f"\n=== LMStudio (Local) ===")
                print(f"  offline")
        except Exception:
            print(f"\n=== LMStudio (Local) ===")
            print(f"  offline")


# ──── Model routing ───────────────────────────────────────────────────────────

# Models that map to Copilot backends
COPILOT_MODELS = {
    "claude-opus-4.6", "claude-sonnet-4.6", "claude-sonnet-4.5", "claude-sonnet-4",
    "claude-opus-4.5", "claude-haiku-4.5",
    "gpt-5.4", "gpt-5.4-mini", "gpt-5.3-codex", "gpt-5.2-codex", "gpt-5.2",
    "gpt-5.1", "gpt-5.1-codex-max", "gpt-5-mini",
    "gpt-4o", "gpt-4o-mini", "gpt-4.1", "gpt-4", "gpt-3.5-turbo",
    "gemini-3.1-pro", "gemini-3-pro", "gemini-3-flash", "gemini-2.5-pro",
    "grok-code-fast-1",
}

# Shortcuts for convenience
ALIASES = {
    "opus": "claude-opus-4.6",
    "sonnet": "claude-sonnet-4.6",
    "haiku": "claude-haiku-4.5",
    "gpt5": "gpt-5.4",
    "gpt": "gpt-5.4",
    "codex": "gpt-5.3-codex",
    "gemini": "gemini-3.1-pro",
    "flash": "gemini-3-flash",
    "grok": "grok-code-fast-1",
}


def resolve_model(model: str) -> str:
    """Resolve aliases and partial matches."""
    if model in ALIASES:
        return ALIASES[model]
    # Partial match
    for m in COPILOT_MODELS:
        if model.lower() in m.lower():
            return m
    return model


# ──── CLI ─────────────────────────────────────────────────────────────────────

def main() -> None:
    parser = argparse.ArgumentParser(
        description="Unified AI CLI — prompt any frontier model for free",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "Examples:\n"
            "  ask.py 'explain quicksort'                  # GPT-5.4 (default)\n"
            "  ask.py 'explain quicksort' -m opus          # Claude Opus 4.6\n"
            "  ask.py 'explain quicksort' -m gemini        # Gemini 3.1 Pro\n"
            "  ask.py 'explain quicksort' -m grok          # Grok Code Fast\n"
            "  ask.py 'explain quicksort' --nlm            # NotebookLM (grounded)\n"
            "  ask.py 'explain quicksort' --local          # LMStudio\n"
            "  ask.py --models                             # list everything\n"
        ),
    )
    parser.add_argument("prompt", nargs="?", help="The prompt to send")
    parser.add_argument("-m", "--model", default="gpt-5.4", help="Model name or alias")
    parser.add_argument("--nlm", action="store_true", help="Use NotebookLM (grounded in notebook sources)")
    parser.add_argument("--local", action="store_true", help="Use local LMStudio")
    parser.add_argument("--models", action="store_true", help="List all available models")
    parser.add_argument("--vendor", help="Filter models by vendor (with --models)")
    parser.add_argument("--account", default="nihilistcod", help="GitHub account for Copilot")
    parser.add_argument("--cdp-port", type=int, default=9223, help="CDP port for NLM")
    args = parser.parse_args()

    if args.models:
        list_models(args.vendor)
        return

    if not args.prompt:
        parser.print_help()
        return

    t0 = time.time()

    if args.nlm:
        backend = "NotebookLM (Gemini, grounded)"
        answer = ask_nlm(args.prompt, args.cdp_port)
    elif args.local:
        backend = f"LMStudio (local)"
        answer = ask_local(args.prompt, args.model if args.model != "gpt-5.4" else None)
    else:
        model = resolve_model(args.model)
        backend = f"Copilot ({model})"
        answer = ask_copilot(args.prompt, model=model, account=args.account)

    elapsed = time.time() - t0

    # Clean up encoding artifacts
    if isinstance(answer, str):
        answer = (answer
                  .replace("\u00e2\u0080\u0099", "'")
                  .replace("\u00e2\u0080\u009c", '"')
                  .replace("\u00e2\u0080\u009d", '"')
                  .replace("\u00e2\u0080\u0094", "—"))

    # Windows cp1252 safe output
    import sys
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    print(answer)
    print(f"\n--- {backend} | {elapsed:.1f}s ---")


if __name__ == "__main__":
    main()
