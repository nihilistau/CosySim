"""
Model Proxy — Multi-Protocol AI Gateway
=========================================

Serves OpenAI, Anthropic, and Gemini protocols simultaneously on one port.
Routes to GitHub Copilot (38 frontier models), local LMStudio, or NotebookLM.
Tool/function calling via emulation (Copilot) or native passthrough (LMStudio).

All three protocols coexist on different URL paths — no conflicts:
    OpenAI:    POST /v1/chat/completions
    Anthropic: POST /v1/messages
    Gemini:    POST /v1beta/models/{model}:generateContent

Works with: OpenCode, aider, Cursor, Continue, open-interpreter, Claude SDK,
google-genai SDK, and any tool that speaks OpenAI/Anthropic/Gemini protocols.

Version: v1.57.2 [2026-03-27]
Author:  CosySim Team

Change Log:
    v1.57.2 [2026-03-27] — Multi-protocol: OpenAI + Anthropic + Gemini on one port,
                            tool calling emulation, full CLI args for all models,
                            LMStudio native passthrough, proper streaming
    v1.50.1 [2026-03-23] — Initial proxy with basic chat completions

Usage:
    python scripts/model_proxy.py                           # All protocols on :5800
    python scripts/model_proxy.py --port 8080               # Custom port
    python scripts/model_proxy.py --default opus            # Default to Claude Opus
    python scripts/model_proxy.py --account nihilistcod     # Copilot account
    python scripts/model_proxy.py --lmstudio-url http://host:1234/v1
    python scripts/model_proxy.py --list-models             # Print model catalog
"""
from __future__ import annotations

import asyncio
import json
import logging
import re
import sys
import time
import uuid
from pathlib import Path
from typing import Any, Dict, Generator, List, Optional, Tuple

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("model_proxy")


# ──── Model Catalog ──────────────────────────────────────────────────────────
# v1.57.2 [2026-03-27] — Full catalog with aliases for all three protocols

COPILOT_MODELS = [
    # Anthropic
    {"id": "claude-opus-4.6",      "vendor": "Anthropic", "tier": "reasoning"},
    {"id": "claude-sonnet-4.6",    "vendor": "Anthropic", "tier": "balanced"},
    {"id": "claude-sonnet-4.5",    "vendor": "Anthropic", "tier": "balanced"},
    {"id": "claude-sonnet-4",      "vendor": "Anthropic", "tier": "balanced"},
    {"id": "claude-opus-4.5",      "vendor": "Anthropic", "tier": "reasoning"},
    {"id": "claude-haiku-4.5",     "vendor": "Anthropic", "tier": "fast"},
    # OpenAI
    {"id": "gpt-5.4",             "vendor": "OpenAI",    "tier": "balanced"},
    {"id": "gpt-5.4-mini",        "vendor": "OpenAI",    "tier": "fast"},
    {"id": "gpt-5.3-codex",       "vendor": "OpenAI",    "tier": "code"},
    {"id": "gpt-5.2-codex",       "vendor": "OpenAI",    "tier": "code"},
    {"id": "gpt-5.2",             "vendor": "OpenAI",    "tier": "balanced"},
    {"id": "gpt-5.1",             "vendor": "OpenAI",    "tier": "balanced"},
    {"id": "gpt-5.1-codex-max",   "vendor": "OpenAI",    "tier": "code"},
    {"id": "gpt-5-mini",          "vendor": "OpenAI",    "tier": "fast"},
    # Google
    {"id": "gemini-3.1-pro",      "vendor": "Google",    "tier": "reasoning"},
    {"id": "gemini-3-pro",        "vendor": "Google",    "tier": "balanced"},
    {"id": "gemini-3-flash",      "vendor": "Google",    "tier": "fast"},
    {"id": "gemini-2.5-pro",      "vendor": "Google",    "tier": "balanced"},
    # xAI
    {"id": "grok-code-fast-1",    "vendor": "xAI",       "tier": "code"},
    # Special
    {"id": "nlm",                 "vendor": "Google (NotebookLM)", "tier": "research"},
    {"id": "lmstudio",            "vendor": "Local",     "tier": "local"},
]

# Alias map — maps any incoming model string to a real model ID
ALIASES: Dict[str, str] = {
    # Short names
    "opus": "claude-opus-4.6", "sonnet": "claude-sonnet-4.6", "haiku": "claude-haiku-4.5",
    "gpt5": "gpt-5.4", "gpt": "gpt-5.4", "codex": "gpt-5.3-codex",
    "gemini": "gemini-3.1-pro", "flash": "gemini-3-flash", "grok": "grok-code-fast-1",
    "local": "lmstudio",
    # OpenAI legacy aliases (tools send these)
    "gpt-4": "gpt-5.4", "gpt-4o": "gpt-5.4", "gpt-4o-mini": "gpt-5.4-mini",
    "gpt-4-turbo": "gpt-5.4", "gpt-3.5-turbo": "gpt-5.4",
    # Anthropic legacy aliases
    "claude-3-opus": "claude-opus-4.6", "claude-3-opus-20240229": "claude-opus-4.6",
    "claude-3-sonnet": "claude-sonnet-4.6", "claude-3-sonnet-20240229": "claude-sonnet-4.6",
    "claude-3-haiku": "claude-haiku-4.5", "claude-3-haiku-20240307": "claude-haiku-4.5",
    "claude-3.5-sonnet": "claude-sonnet-4.6",
    "claude-3-5-sonnet-20241022": "claude-sonnet-4.6", "claude-3-5-sonnet-latest": "claude-sonnet-4.6",
    "claude-3-5-haiku-20241022": "claude-haiku-4.5", "claude-3-5-haiku-latest": "claude-haiku-4.5",
    # Gemini aliases
    "gemini-1.5-pro": "gemini-3.1-pro", "gemini-1.5-flash": "gemini-3-flash",
    "gemini-pro": "gemini-3-pro",
    "models/gemini-1.5-pro": "gemini-3.1-pro", "models/gemini-1.5-flash": "gemini-3-flash",
}


def resolve_model(model: str) -> str:
    """Resolve aliases and partial matches to actual model ID."""
    if not model:
        return "claude-sonnet-4.6"
    # Strip Gemini-style prefix
    clean = model.replace("models/", "")
    if clean in ALIASES:
        return ALIASES[clean]
    for m in COPILOT_MODELS:
        if clean.lower() == m["id"].lower():
            return m["id"]
    for m in COPILOT_MODELS:
        if clean.lower() in m["id"].lower():
            return m["id"]
    return clean


# ──── Tool Calling Emulation ─────────────────────────────────────────────────
# v1.57.2 [2026-03-27] — System prompt injection + response parsing
# CONNECTS: GithubCopilotClient (no native tool support)

TOOL_CALL_INSTRUCTION = """

## Tool Use

You have access to tools. When you need to use a tool, you MUST output a JSON block wrapped in <tool_call> tags. You may call multiple tools. Each tool call must be a separate tagged block.

Format for calling a tool:
<tool_call>
{"name": "tool_name", "arguments": {"param1": "value1", "param2": "value2"}}
</tool_call>

After outputting tool call(s), STOP. Do not add any text after the tool calls. Wait for the tool results before continuing.

If you do NOT need to use a tool, respond normally with text only — no <tool_call> tags.

Available tools:
"""

_TOOL_CALL_RE = re.compile(r"<tool_call>\s*(\{.*?\})\s*</tool_call>", re.DOTALL)


def build_tools_system_prompt(tools: List[Dict[str, Any]]) -> str:
    """Convert OpenAI/Anthropic tool definitions into a system prompt section."""
    if not tools:
        return ""
    lines = [TOOL_CALL_INSTRUCTION]
    for tool in tools:
        func = tool.get("function", tool)
        name = func.get("name", "unknown")
        desc = func.get("description", "")
        params = func.get("parameters", func.get("input_schema", {}))
        lines.append(f"### {name}")
        if desc:
            lines.append(f"{desc}")
        props = params.get("properties", {})
        required = set(params.get("required", []))
        if props:
            lines.append("Parameters:")
            for pname, pdef in props.items():
                ptype = pdef.get("type", "string")
                pdesc = pdef.get("description", "")
                req = " (required)" if pname in required else " (optional)"
                lines.append(f"  - {pname}: {ptype}{req} -- {pdesc}")
        lines.append("")
    return "\n".join(lines)


def parse_tool_calls(text: str) -> Tuple[str, List[Dict[str, Any]]]:
    """Parse <tool_call> markers from model text, return OpenAI-format tool_calls."""
    matches = _TOOL_CALL_RE.findall(text)
    if not matches:
        return text, []
    tool_calls = []
    for match in matches:
        try:
            call_data = json.loads(match)
            arguments = call_data.get("arguments", {})
            tool_calls.append({
                "id": f"call_{uuid.uuid4().hex[:12]}",
                "type": "function",
                "function": {
                    "name": call_data.get("name", ""),
                    "arguments": json.dumps(arguments) if isinstance(arguments, dict) else str(arguments),
                },
            })
        except json.JSONDecodeError:
            logger.warning("Failed to parse tool call: %s", match[:100])
    remaining = _TOOL_CALL_RE.sub("", text).strip()
    return remaining, tool_calls


# ──── Message Normalization ──────────────────────────────────────────────────
# v1.57.2 [2026-03-27] — Convert any protocol's messages to internal format,
#   then to Copilot single-prompt

def normalize_anthropic_messages(body: Dict) -> Tuple[List[Dict], List[Dict] | None]:
    """Convert Anthropic /v1/messages request to OpenAI-format messages + tools.

    Args:
        body: Anthropic request body.

    Returns:
        Tuple of (openai_messages, openai_tools).
    """
    messages: List[Dict] = []

    # System message (Anthropic puts it as a top-level field)
    system = body.get("system", "")
    if system:
        if isinstance(system, list):
            system = "\n".join(b.get("text", "") for b in system if b.get("type") == "text")
        messages.append({"role": "system", "content": system})

    # Convert messages
    for msg in body.get("messages", []):
        role = msg.get("role", "user")
        content = msg.get("content", "")

        if isinstance(content, str):
            messages.append({"role": role, "content": content})
        elif isinstance(content, list):
            # Anthropic content blocks
            text_parts = []
            tool_use_blocks = []
            tool_result_blocks = []

            for block in content:
                btype = block.get("type", "text")
                if btype == "text":
                    text_parts.append(block.get("text", ""))
                elif btype == "tool_use":
                    tool_use_blocks.append(block)
                elif btype == "tool_result":
                    tool_result_blocks.append(block)

            if tool_result_blocks:
                # Tool results → role: tool messages
                for tr in tool_result_blocks:
                    result_content = tr.get("content", "")
                    if isinstance(result_content, list):
                        result_content = "\n".join(
                            b.get("text", "") for b in result_content if b.get("type") == "text"
                        )
                    messages.append({
                        "role": "tool",
                        "tool_call_id": tr.get("tool_use_id", ""),
                        "name": "",
                        "content": result_content,
                    })
            elif tool_use_blocks:
                # Assistant with tool_use → role: assistant with tool_calls
                tc_list = []
                for tu in tool_use_blocks:
                    tc_list.append({
                        "id": tu.get("id", f"toolu_{uuid.uuid4().hex[:12]}"),
                        "type": "function",
                        "function": {
                            "name": tu.get("name", ""),
                            "arguments": json.dumps(tu.get("input", {})),
                        },
                    })
                messages.append({
                    "role": "assistant",
                    "content": "\n".join(text_parts) if text_parts else "",
                    "tool_calls": tc_list,
                })
            else:
                messages.append({"role": role, "content": "\n".join(text_parts)})

    # Convert Anthropic tools to OpenAI format
    tools = None
    raw_tools = body.get("tools", [])
    if raw_tools:
        tools = []
        for t in raw_tools:
            tools.append({
                "type": "function",
                "function": {
                    "name": t.get("name", ""),
                    "description": t.get("description", ""),
                    "parameters": t.get("input_schema", {}),
                },
            })

    return messages, tools


def normalize_gemini_messages(body: Dict) -> Tuple[List[Dict], List[Dict] | None]:
    """Convert Gemini generateContent request to OpenAI-format messages + tools.

    Args:
        body: Gemini request body.

    Returns:
        Tuple of (openai_messages, openai_tools).
    """
    messages: List[Dict] = []

    # System instruction
    sys_inst = body.get("system_instruction", {})
    if sys_inst:
        parts = sys_inst.get("parts", [])
        sys_text = "\n".join(p.get("text", "") for p in parts if "text" in p)
        if sys_text:
            messages.append({"role": "system", "content": sys_text})

    # Contents
    for content in body.get("contents", []):
        role = content.get("role", "user")
        parts = content.get("parts", [])
        text = "\n".join(p.get("text", "") for p in parts if "text" in p)

        # Map Gemini roles to OpenAI
        oai_role = "assistant" if role == "model" else "user"
        if text:
            messages.append({"role": oai_role, "content": text})

        # Function call parts
        for part in parts:
            if "functionCall" in part:
                fc = part["functionCall"]
                messages.append({
                    "role": "assistant",
                    "content": "",
                    "tool_calls": [{
                        "id": f"call_{uuid.uuid4().hex[:12]}",
                        "type": "function",
                        "function": {
                            "name": fc.get("name", ""),
                            "arguments": json.dumps(fc.get("args", {})),
                        },
                    }],
                })
            if "functionResponse" in part:
                fr = part["functionResponse"]
                messages.append({
                    "role": "tool",
                    "name": fr.get("name", ""),
                    "tool_call_id": "",
                    "content": json.dumps(fr.get("response", {})),
                })

    # Convert Gemini tools
    tools = None
    raw_tools = body.get("tools", [])
    for tool_group in raw_tools:
        for fd in tool_group.get("function_declarations", tool_group.get("functionDeclarations", [])):
            if tools is None:
                tools = []
            tools.append({
                "type": "function",
                "function": {
                    "name": fd.get("name", ""),
                    "description": fd.get("description", ""),
                    "parameters": fd.get("parameters", {}),
                },
            })

    return messages, tools


def serialize_messages(messages: List[Dict], tools_prompt: str = "") -> Tuple[str, str]:
    """Convert OpenAI messages array to system + user prompt for Copilot."""
    system_parts: List[str] = []
    conversation_parts: List[str] = []

    for msg in messages:
        role = msg.get("role", "user")
        content = msg.get("content", "") or ""

        if role == "system":
            system_parts.append(content)
        elif role == "user":
            conversation_parts.append(f"User: {content}")
        elif role == "assistant":
            tool_calls = msg.get("tool_calls", [])
            if tool_calls:
                calls_text = []
                for tc in tool_calls:
                    func = tc.get("function", {})
                    calls_text.append(
                        f'<tool_call>\n{{"name": "{func.get("name", "")}", '
                        f'"arguments": {func.get("arguments", "{}")}}}\n</tool_call>'
                    )
                prefix = f"Assistant: {content}\n" if content else "Assistant:\n"
                conversation_parts.append(prefix + "\n".join(calls_text))
            elif content:
                conversation_parts.append(f"Assistant: {content}")
        elif role == "tool":
            name = msg.get("name", "tool")
            conversation_parts.append(f"Tool result ({name}):\n{content}")

    system_text = "\n\n".join(system_parts)
    if tools_prompt:
        system_text = (system_text + "\n" + tools_prompt) if system_text else tools_prompt

    return system_text, "\n\n".join(conversation_parts)


# ──── Thread Manager ─────────────────────────────────────────────────────────

class ThreadManager:
    """Create fresh Copilot thread per request (stateless like OpenAI)."""

    def get_thread(self, client: Any, messages: List[Dict]) -> Tuple[str, str]:
        return client.create_thread(), "root"


_thread_mgr = ThreadManager()


# ──── Backend Calls ──────────────────────────────────────────────────────────
# v1.57.2 [2026-03-27] — Unified backend interface

# Module-level config (set from CLI args at startup)
_config: Dict[str, Any] = {
    "account": "nihilistcod",
    "lmstudio_url": "http://localhost:1234/v1",
    "cdp_port": 9223,
    "default_model": "claude-sonnet-4.6",
}


def call_copilot(
    messages: List[Dict], model: str,
    tools: List[Dict] | None = None,
    temperature: float | None = None,
    max_tokens: int | None = None,
) -> Tuple[str, List[Dict]]:
    """Route to Copilot with tool calling emulation."""
    from engine.integrations.github_copilot_client import GithubCopilotClient

    tools_prompt = build_tools_system_prompt(tools) if tools else ""
    system_text, user_prompt = serialize_messages(messages, tools_prompt)

    full_prompt = f"System Instructions:\n{system_text}\n\n{user_prompt}" if system_text else user_prompt

    client = GithubCopilotClient(_config["account"])
    thread_id, parent_id = _thread_mgr.get_thread(client, messages)
    text, _ = client.send_message(thread_id, full_prompt, model=model, parent_message_id=parent_id)

    if tools:
        return parse_tool_calls(text)
    return text, []


def call_copilot_stream(
    messages: List[Dict], model: str,
    tools: List[Dict] | None = None,
) -> Generator[str, None, None]:
    """Stream from Copilot, yielding text chunks."""
    from engine.integrations.github_copilot_client import GithubCopilotClient

    tools_prompt = build_tools_system_prompt(tools) if tools else ""
    system_text, user_prompt = serialize_messages(messages, tools_prompt)
    full_prompt = f"System Instructions:\n{system_text}\n\n{user_prompt}" if system_text else user_prompt

    client = GithubCopilotClient(_config["account"])
    thread_id, parent_id = _thread_mgr.get_thread(client, messages)
    yield from client.send_message_stream(thread_id, full_prompt, model=model, parent_message_id=parent_id)


def call_lmstudio(
    messages: List[Dict], model: str | None = None,
    tools: List[Dict] | None = None,
    temperature: float | None = None, max_tokens: int | None = None,
    stream: bool = False,
) -> Dict[str, Any]:
    """Route to LMStudio — full OpenAI passthrough (native tool support)."""
    import requests

    payload: Dict[str, Any] = {"messages": messages, "stream": stream}
    if model and model != "lmstudio":
        payload["model"] = model
    if tools:
        payload["tools"] = tools
    if temperature is not None:
        payload["temperature"] = temperature
    if max_tokens is not None:
        payload["max_tokens"] = max_tokens

    resp = requests.post(
        f"{_config['lmstudio_url']}/chat/completions",
        json=payload, timeout=120, stream=stream,
    )
    resp.raise_for_status()
    return {"_stream_response": resp} if stream else resp.json()


def call_nlm(messages: List[Dict]) -> str:
    """Route to NotebookLM via CDP. Text only."""
    from scripts.nlm_ask import ask
    prompt = ""
    for msg in reversed(messages):
        if msg.get("role") == "user":
            prompt = msg.get("content", "")
            break
    if not prompt and messages:
        prompt = messages[-1].get("content", "")
    return asyncio.run(ask(prompt, _config["cdp_port"]))


def _clean(text: str) -> str:
    """Fix encoding artifacts."""
    return (text.replace("\u00e2\u0080\u0099", "'").replace("\u00e2\u0080\u009c", '"')
            .replace("\u00e2\u0080\u009d", '"').replace("\u00e2\u0080\u0094", "-"))


# ──── Core Dispatch ──────────────────────────────────────────────────────────
# v1.57.2 [2026-03-27] — Shared logic for all three protocols

def dispatch(
    messages: List[Dict], model: str,
    tools: List[Dict] | None = None,
    stream: bool = False,
    temperature: float | None = None,
    max_tokens: int | None = None,
) -> Dict[str, Any]:
    """Route to the right backend and return a normalized result.

    Returns:
        Dict with keys: content, tool_calls, model, stream_response (if streaming).
    """
    t0 = time.time()

    # LMStudio: full passthrough
    if model == "lmstudio":
        result = call_lmstudio(messages, tools=tools, temperature=temperature,
                               max_tokens=max_tokens, stream=stream)
        if stream:
            return {"stream_response": result.get("_stream_response"), "model": model}
        # Extract from OpenAI response
        choice = result.get("choices", [{}])[0]
        msg = choice.get("message", {})
        return {
            "content": msg.get("content", ""),
            "tool_calls": msg.get("tool_calls", []),
            "model": model,
            "usage": result.get("usage", {}),
        }

    # NLM: text only
    if model == "nlm":
        content = _clean(call_nlm(messages))
        return {"content": content, "tool_calls": [], "model": model}

    # Copilot: tool calling emulated
    if stream and not tools:
        return {"stream_generator": call_copilot_stream(messages, model), "model": model}

    content, tool_calls = call_copilot(messages, model, tools=tools,
                                        temperature=temperature, max_tokens=max_tokens)
    content = _clean(content)
    elapsed = time.time() - t0
    logger.info("Response: %d chars, %d tools in %.1fs via %s",
                len(content), len(tool_calls), elapsed, model)
    return {"content": content, "tool_calls": tool_calls, "model": model}


# ──── FastAPI Server ─────────────────────────────────────────────────────────
# v1.57.2 [2026-03-27] — All three protocols on one server

def create_app():
    """Create FastAPI app serving OpenAI, Anthropic, and Gemini protocols."""
    from fastapi import FastAPI, Body, Request
    from fastapi.middleware.cors import CORSMiddleware
    from fastapi.responses import JSONResponse, StreamingResponse

    app = FastAPI(title="CosySim Model Proxy", version="1.57.2")
    app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])

    default = _config["default_model"]

    # ── Health ─────────────────────────────────────────────────────

    @app.get("/health")
    async def health():
        return {
            "status": "ok", "version": "1.57.2",
            "protocols": ["openai", "anthropic", "gemini"],
            "models": len(COPILOT_MODELS), "default": default,
        }

    # ── OpenAI Protocol ────────────────────────────────────────────

    @app.get("/v1/models")
    async def openai_list_models():
        return {"object": "list", "data": [
            {"id": m["id"], "object": "model", "created": 1700000000, "owned_by": m["vendor"]}
            for m in COPILOT_MODELS
        ]}

    @app.post("/v1/chat/completions")
    async def openai_chat(body: Dict[str, Any] = Body(...)):
        messages = body.get("messages", [])
        model = resolve_model(body.get("model", default))
        stream = body.get("stream", False)
        tools = body.get("tools")
        temp = body.get("temperature")
        max_tok = body.get("max_tokens")

        logger.info("[OpenAI] model=%s msgs=%d tools=%s stream=%s",
                     model, len(messages), len(tools) if tools else 0, stream)

        try:
            result = dispatch(messages, model, tools=tools, stream=stream,
                              temperature=temp, max_tokens=max_tok)

            # LMStudio streaming passthrough
            if "stream_response" in result:
                raw = result["stream_response"]
                async def fwd():
                    for line in raw.iter_lines(decode_unicode=True):
                        if line:
                            yield line + "\n\n"
                return StreamingResponse(fwd(), media_type="text/event-stream")

            # Copilot text streaming
            if "stream_generator" in result:
                cid = f"chatcmpl-{uuid.uuid4().hex[:12]}"
                async def gen():
                    for chunk in result["stream_generator"]:
                        yield f"data: {json.dumps({'id': cid, 'object': 'chat.completion.chunk', 'created': int(time.time()), 'model': model, 'choices': [{'index': 0, 'delta': {'content': chunk}, 'finish_reason': None}]})}\n\n"
                    yield f"data: {json.dumps({'id': cid, 'object': 'chat.completion.chunk', 'created': int(time.time()), 'model': model, 'choices': [{'index': 0, 'delta': {}, 'finish_reason': 'stop'}]})}\n\n"
                    yield "data: [DONE]\n\n"
                return StreamingResponse(gen(), media_type="text/event-stream")

            # Build response
            content = result.get("content", "")
            tool_calls = result.get("tool_calls", [])
            msg: Dict[str, Any] = {"role": "assistant", "content": content or None}
            if tool_calls:
                msg["tool_calls"] = tool_calls
            finish = "tool_calls" if tool_calls else "stop"

            if stream:
                cid = f"chatcmpl-{uuid.uuid4().hex[:12]}"
                async def stream_result():
                    if tool_calls:
                        yield f"data: {json.dumps({'id': cid, 'object': 'chat.completion.chunk', 'created': int(time.time()), 'model': model, 'choices': [{'index': 0, 'delta': {'role': 'assistant', 'content': None}, 'finish_reason': None}]})}\n\n"
                        for i, tc in enumerate(tool_calls):
                            yield f"data: {json.dumps({'id': cid, 'object': 'chat.completion.chunk', 'created': int(time.time()), 'model': model, 'choices': [{'index': 0, 'delta': {'tool_calls': [{'index': i, 'id': tc['id'], 'type': 'function', 'function': tc['function']}]}, 'finish_reason': None}]})}\n\n"
                    else:
                        yield f"data: {json.dumps({'id': cid, 'object': 'chat.completion.chunk', 'created': int(time.time()), 'model': model, 'choices': [{'index': 0, 'delta': {'role': 'assistant', 'content': content}, 'finish_reason': None}]})}\n\n"
                    yield f"data: {json.dumps({'id': cid, 'object': 'chat.completion.chunk', 'created': int(time.time()), 'model': model, 'choices': [{'index': 0, 'delta': {}, 'finish_reason': finish}]})}\n\n"
                    yield "data: [DONE]\n\n"
                return StreamingResponse(stream_result(), media_type="text/event-stream")

            ptok = sum(len(str(m.get("content", ""))) // 4 for m in messages)
            ctok = len(content or "") // 4
            return {
                "id": f"chatcmpl-{uuid.uuid4().hex[:12]}", "object": "chat.completion",
                "created": int(time.time()), "model": model,
                "choices": [{"index": 0, "message": msg, "finish_reason": finish}],
                "usage": {"prompt_tokens": ptok, "completion_tokens": ctok, "total_tokens": ptok + ctok},
            }

        except Exception as exc:
            logger.error("[OpenAI] %s", exc, exc_info=True)
            return JSONResponse(502, {"error": {"message": str(exc), "type": "backend_error"}})

    # ── Anthropic Protocol ─────────────────────────────────────────

    @app.post("/v1/messages")
    async def anthropic_messages(body: Dict[str, Any] = Body(...)):
        model = resolve_model(body.get("model", default))
        max_tok = body.get("max_tokens", 4096)
        stream = body.get("stream", False)

        messages, tools = normalize_anthropic_messages(body)
        logger.info("[Anthropic] model=%s msgs=%d tools=%s stream=%s",
                     model, len(messages), len(tools) if tools else 0, stream)

        try:
            result = dispatch(messages, model, tools=tools, stream=False,
                              temperature=body.get("temperature"),
                              max_tokens=max_tok)

            content_text = result.get("content", "") or ""
            tool_calls = result.get("tool_calls", [])

            # Build Anthropic response
            content_blocks: List[Dict] = []
            if content_text:
                content_blocks.append({"type": "text", "text": content_text})
            for tc in tool_calls:
                func = tc.get("function", {})
                args = func.get("arguments", "{}")
                content_blocks.append({
                    "type": "tool_use",
                    "id": tc.get("id", f"toolu_{uuid.uuid4().hex[:12]}"),
                    "name": func.get("name", ""),
                    "input": json.loads(args) if isinstance(args, str) else args,
                })

            if not content_blocks:
                content_blocks.append({"type": "text", "text": ""})

            stop_reason = "tool_use" if tool_calls else "end_turn"
            ptok = sum(len(str(m.get("content", ""))) // 4 for m in messages)
            ctok = len(content_text) // 4

            resp = {
                "id": f"msg_{uuid.uuid4().hex[:16]}",
                "type": "message",
                "role": "assistant",
                "model": model,
                "content": content_blocks,
                "stop_reason": stop_reason,
                "stop_sequence": None,
                "usage": {"input_tokens": ptok, "output_tokens": ctok},
            }

            if stream:
                async def anthropic_stream():
                    yield f"event: message_start\ndata: {json.dumps({'type': 'message_start', 'message': resp})}\n\n"
                    for i, block in enumerate(content_blocks):
                        yield f"event: content_block_start\ndata: {json.dumps({'type': 'content_block_start', 'index': i, 'content_block': block})}\n\n"
                        yield f"event: content_block_stop\ndata: {json.dumps({'type': 'content_block_stop', 'index': i})}\n\n"
                    yield f"event: message_delta\ndata: {json.dumps({'type': 'message_delta', 'delta': {'stop_reason': stop_reason}, 'usage': {'output_tokens': ctok}})}\n\n"
                    yield f"event: message_stop\ndata: {json.dumps({'type': 'message_stop'})}\n\n"
                return StreamingResponse(anthropic_stream(), media_type="text/event-stream")

            return resp

        except Exception as exc:
            logger.error("[Anthropic] %s", exc, exc_info=True)
            return JSONResponse(502, {"type": "error", "error": {"type": "api_error", "message": str(exc)}})

    # ── Gemini Protocol ────────────────────────────────────────────

    @app.post("/v1beta/models/{model_id}:generateContent")
    async def gemini_generate(model_id: str, body: Dict[str, Any] = Body(...)):
        model = resolve_model(model_id)
        messages, tools = normalize_gemini_messages(body)

        logger.info("[Gemini] model=%s msgs=%d tools=%s", model, len(messages), len(tools) if tools else 0)

        try:
            result = dispatch(messages, model, tools=tools,
                              temperature=body.get("generationConfig", {}).get("temperature"),
                              max_tokens=body.get("generationConfig", {}).get("maxOutputTokens"))

            content_text = result.get("content", "") or ""
            tool_calls = result.get("tool_calls", [])

            parts: List[Dict] = []
            if content_text:
                parts.append({"text": content_text})
            for tc in tool_calls:
                func = tc.get("function", {})
                args = func.get("arguments", "{}")
                parts.append({
                    "functionCall": {
                        "name": func.get("name", ""),
                        "args": json.loads(args) if isinstance(args, str) else args,
                    }
                })

            if not parts:
                parts.append({"text": ""})

            ptok = sum(len(str(m.get("content", ""))) // 4 for m in messages)
            ctok = len(content_text) // 4

            return {
                "candidates": [{
                    "content": {"role": "model", "parts": parts},
                    "finishReason": "STOP",
                    "index": 0,
                }],
                "usageMetadata": {
                    "promptTokenCount": ptok,
                    "candidatesTokenCount": ctok,
                    "totalTokenCount": ptok + ctok,
                },
                "modelVersion": model,
            }

        except Exception as exc:
            logger.error("[Gemini] %s", exc, exc_info=True)
            return JSONResponse(502, {"error": {"code": 502, "message": str(exc), "status": "INTERNAL"}})

    @app.post("/v1beta/models/{model_id}:streamGenerateContent")
    async def gemini_stream(model_id: str, body: Dict[str, Any] = Body(...)):
        """Gemini streaming — returns array of chunks (non-SSE)."""
        # Gemini streaming is NDJSON, not SSE. For simplicity, return full response.
        return await gemini_generate(model_id, body)

    return app


# ──── Main ───────────────────────────────────────────────────────────────────
# v1.57.2 [2026-03-27] — Full CLI with model args and protocol info

def main():
    import argparse
    import uvicorn

    parser = argparse.ArgumentParser(
        description="Model Proxy v1.57.2 -- Multi-Protocol AI Gateway (OpenAI + Anthropic + Gemini)",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Protocols (all served simultaneously):
  OpenAI:    POST /v1/chat/completions     (tool calling supported)
  Anthropic: POST /v1/messages             (tool_use supported)
  Gemini:    POST /v1beta/models/M:generateContent

Model shortcuts:
  opus, sonnet, haiku, gpt5, codex, gemini, flash, grok, nlm, lmstudio

Examples:
  %(prog)s                                     # Default on :5800
  %(prog)s --port 8080 --default opus          # Custom port + model
  %(prog)s --account nihilistcod               # Copilot account
  %(prog)s --lmstudio-url http://beast:1234/v1 # Remote LMStudio
  %(prog)s --list-models                       # Print model catalog
        """,
    )
    parser.add_argument("--port", type=int, default=5800, help="Server port (default: 5800)")
    parser.add_argument("--default", default="claude-sonnet-4.6", help="Default model ID or alias")
    parser.add_argument("--account", default="nihilistcod", help="GitHub Copilot account")
    parser.add_argument("--lmstudio-url", default="http://localhost:1234/v1", help="LMStudio base URL")
    parser.add_argument("--cdp-port", type=int, default=9223, help="Chrome CDP port for NLM")
    parser.add_argument("--list-models", action="store_true", help="Print model catalog and exit")
    args = parser.parse_args()

    if args.list_models:
        print(f"\n  Model Catalog ({len(COPILOT_MODELS)} models)")
        print(f"  {'-' * 55}")
        print(f"  {'ID':<25} {'Vendor':<20} {'Tier':<10}")
        print(f"  {'-' * 55}")
        for m in COPILOT_MODELS:
            print(f"  {m['id']:<25} {m['vendor']:<20} {m['tier']:<10}")
        print(f"\n  Aliases: {', '.join(sorted(set(k for k in ALIASES if len(k) < 10)))}")
        print()
        return

    # Apply config
    _config["account"] = args.account
    _config["lmstudio_url"] = args.lmstudio_url
    _config["cdp_port"] = args.cdp_port
    _config["default_model"] = resolve_model(args.default)

    app = create_app()

    print(f"\n{'='*62}")
    print(f"  CosySim Model Proxy v1.57.2 -- Multi-Protocol AI Gateway")
    print(f"{'='*62}")
    print(f"\n  Port: {args.port}    Default: {_config['default_model']}")
    print(f"  Account: {args.account}    LMStudio: {args.lmstudio_url}")
    print(f"\n  Protocols (all active):")
    print(f"    OpenAI:    http://localhost:{args.port}/v1/chat/completions")
    print(f"    Anthropic: http://localhost:{args.port}/v1/messages")
    print(f"    Gemini:    http://localhost:{args.port}/v1beta/models/MODEL:generateContent")
    print(f"\n  Configure your tool:")
    print(f"    Base URL:  http://localhost:{args.port}/v1")
    print(f"    API Key:   anything (not checked)")
    print(f"\n  Models: opus, sonnet, haiku, gpt5, codex, gemini, flash, grok, nlm, lmstudio")
    print()

    uvicorn.run(app, host="0.0.0.0", port=args.port, log_level="info")


if __name__ == "__main__":
    main()
