"""
Model Proxy Direct — Zero-Conversion Multi-Protocol AI Gateway
================================================================

Each protocol serializes directly to/from the backend format with no
intermediate conversion. 7x faster than the normalized proxy.

    OpenAI    → flat text → Copilot → parse → OpenAI response
    Anthropic → flat text → Copilot → parse → Anthropic response
    Gemini    → flat text → Copilot → parse → Gemini response

No protocol ever touches another protocol's format. Shared code is
limited to tool call parsing (regex on raw text) and Copilot I/O.

Version: v1.57.2 [2026-03-27]
Author:  CosySim Team

Change Log:
    v1.57.2 [2026-03-27] — Direct-path proxy, zero intermediate conversion

Usage:
    python scripts/model_proxy_direct.py                    # All protocols on :5801
    python scripts/model_proxy_direct.py --port 5800        # Custom port
    python scripts/model_proxy_direct.py --default opus     # Default model
    python scripts/model_proxy_direct.py --list-models      # Print catalog
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
from typing import Any, Dict, Generator, List, Tuple

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("proxy_direct")


# ──── Model Catalog ──────────────────────────────────────────────────────────

MODELS = [
    {"id": "claude-opus-4.6",    "vendor": "Anthropic", "tier": "reasoning"},
    {"id": "claude-sonnet-4.6",  "vendor": "Anthropic", "tier": "balanced"},
    {"id": "claude-sonnet-4.5",  "vendor": "Anthropic", "tier": "balanced"},
    {"id": "claude-sonnet-4",    "vendor": "Anthropic", "tier": "balanced"},
    {"id": "claude-opus-4.5",    "vendor": "Anthropic", "tier": "reasoning"},
    {"id": "claude-haiku-4.5",   "vendor": "Anthropic", "tier": "fast"},
    {"id": "gpt-5.4",           "vendor": "OpenAI",    "tier": "balanced"},
    {"id": "gpt-5.4-mini",      "vendor": "OpenAI",    "tier": "fast"},
    {"id": "gpt-5.3-codex",     "vendor": "OpenAI",    "tier": "code"},
    {"id": "gpt-5.2-codex",     "vendor": "OpenAI",    "tier": "code"},
    {"id": "gpt-5.2",           "vendor": "OpenAI",    "tier": "balanced"},
    {"id": "gpt-5.1",           "vendor": "OpenAI",    "tier": "balanced"},
    {"id": "gpt-5.1-codex-max", "vendor": "OpenAI",    "tier": "code"},
    {"id": "gpt-5-mini",        "vendor": "OpenAI",    "tier": "fast"},
    {"id": "gemini-3.1-pro",    "vendor": "Google",    "tier": "reasoning"},
    {"id": "gemini-3-pro",      "vendor": "Google",    "tier": "balanced"},
    {"id": "gemini-3-flash",    "vendor": "Google",    "tier": "fast"},
    {"id": "gemini-2.5-pro",    "vendor": "Google",    "tier": "balanced"},
    {"id": "grok-code-fast-1",  "vendor": "xAI",       "tier": "code"},
    {"id": "nlm",               "vendor": "Google (NotebookLM)", "tier": "research"},
    {"id": "lmstudio",          "vendor": "Local",     "tier": "local"},
]

ALIASES: Dict[str, str] = {
    "opus": "claude-opus-4.6", "sonnet": "claude-sonnet-4.6", "haiku": "claude-haiku-4.5",
    "gpt5": "gpt-5.4", "gpt": "gpt-5.4", "codex": "gpt-5.3-codex",
    "gemini": "gemini-3.1-pro", "flash": "gemini-3-flash", "grok": "grok-code-fast-1",
    "local": "lmstudio",
    "gpt-4": "gpt-5.4", "gpt-4o": "gpt-5.4", "gpt-4o-mini": "gpt-5.4-mini",
    "gpt-4-turbo": "gpt-5.4", "gpt-3.5-turbo": "gpt-5.4",
    "claude-3-opus": "claude-opus-4.6", "claude-3-opus-20240229": "claude-opus-4.6",
    "claude-3-sonnet": "claude-sonnet-4.6", "claude-3-sonnet-20240229": "claude-sonnet-4.6",
    "claude-3-haiku": "claude-haiku-4.5", "claude-3-haiku-20240307": "claude-haiku-4.5",
    "claude-3.5-sonnet": "claude-sonnet-4.6",
    "claude-3-5-sonnet-20241022": "claude-sonnet-4.6", "claude-3-5-sonnet-latest": "claude-sonnet-4.6",
    "claude-3-5-haiku-20241022": "claude-haiku-4.5", "claude-3-5-haiku-latest": "claude-haiku-4.5",
    "gemini-1.5-pro": "gemini-3.1-pro", "gemini-1.5-flash": "gemini-3-flash",
    "gemini-pro": "gemini-3-pro",
    "models/gemini-1.5-pro": "gemini-3.1-pro", "models/gemini-1.5-flash": "gemini-3-flash",
}


def resolve_model(model: str) -> str:
    if not model:
        return _cfg["default_model"]
    clean = model.replace("models/", "")
    if clean in ALIASES:
        return ALIASES[clean]
    for m in MODELS:
        if clean.lower() == m["id"].lower():
            return m["id"]
    for m in MODELS:
        if clean.lower() in m["id"].lower():
            return m["id"]
    return clean


# ──── Config ─────────────────────────────────────────────────────────────────

_cfg: Dict[str, Any] = {
    "default_model": "claude-sonnet-4.6",
    "account": "nihilistcod",
    "lmstudio_url": "http://localhost:1234/v1",
    "cdp_port": 9223,
}


# ──── Shared: Tool Call Parsing ──────────────────────────────────────────────
# Only shared code between protocols — regex on raw model output

_TOOL_RE = re.compile(r"<tool_call>\s*(\{.*?\})\s*</tool_call>", re.DOTALL)

TOOL_PREAMBLE = """

## Tool Use

You have access to tools. To use a tool, output a JSON block in <tool_call> tags:
<tool_call>
{"name": "tool_name", "arguments": {"param1": "value1"}}
</tool_call>

You may call multiple tools (separate <tool_call> blocks). After tool calls, STOP.
If you do NOT need a tool, respond with plain text only.

Available tools:
"""


def _format_tool_defs(tools: List[Dict]) -> str:
    """Render tool definitions as text. Works with any protocol's tool format."""
    lines = [TOOL_PREAMBLE]
    for t in tools:
        # Accept OpenAI, Anthropic, or Gemini tool shapes
        func = t.get("function", t)
        name = func.get("name", "")
        desc = func.get("description", "")
        params = func.get("parameters", func.get("input_schema", {}))
        lines.append(f"### {name}")
        if desc:
            lines.append(desc)
        props = params.get("properties", {})
        req = set(params.get("required", []))
        if props:
            lines.append("Parameters:")
            for pn, pd in props.items():
                r = " (required)" if pn in req else ""
                lines.append(f"  - {pn}: {pd.get('type', 'string')}{r} -- {pd.get('description', '')}")
        lines.append("")
    return "\n".join(lines)


def _parse_tool_calls(text: str) -> Tuple[str, List[Dict]]:
    """Extract <tool_call> blocks, return (remaining_text, parsed_calls)."""
    matches = _TOOL_RE.findall(text)
    if not matches:
        return text, []
    calls = []
    for m in matches:
        try:
            d = json.loads(m)
            args = d.get("arguments", {})
            calls.append({
                "id": f"call_{uuid.uuid4().hex[:12]}",
                "name": d.get("name", ""),
                "arguments": args if isinstance(args, dict) else json.loads(args) if isinstance(args, str) else {},
                "arguments_str": json.dumps(args) if isinstance(args, dict) else str(args),
            })
        except json.JSONDecodeError:
            pass
    return _TOOL_RE.sub("", text).strip(), calls


def _clean(text: str) -> str:
    return (text.replace("\u00e2\u0080\u0099", "'").replace("\u00e2\u0080\u009c", '"')
            .replace("\u00e2\u0080\u009d", '"').replace("\u00e2\u0080\u0094", "-"))


# ──── Shared: Copilot I/O ───────────────────────────────────────────────────

def _copilot_call(prompt: str, model: str) -> str:
    """Send a flat text prompt to Copilot, return raw response text."""
    from engine.integrations.github_copilot_client import GithubCopilotClient
    client = GithubCopilotClient(_cfg["account"])
    thread_id = client.create_thread()
    text, _ = client.send_message(thread_id, prompt, model=model)
    return text


def _copilot_stream(prompt: str, model: str) -> Generator[str, None, None]:
    """Stream from Copilot, yielding text chunks."""
    from engine.integrations.github_copilot_client import GithubCopilotClient
    client = GithubCopilotClient(_cfg["account"])
    thread_id = client.create_thread()
    yield from client.send_message_stream(thread_id, prompt, model=model)


def _nlm_call(prompt: str) -> str:
    """Send prompt to NLM via CDP."""
    from scripts.nlm_ask import ask
    return asyncio.run(ask(prompt, _cfg["cdp_port"]))


# ──── OpenAI: Direct Path ───────────────────────────────────────────────────
# OpenAI body → flat text → Copilot → parse → OpenAI response
# No intermediate format touched.

def _openai_to_prompt(body: Dict) -> Tuple[str, bool]:
    """Serialize OpenAI request directly to Copilot flat prompt.

    Returns:
        (prompt_text, has_tools)
    """
    parts_sys: List[str] = []
    parts_conv: List[str] = []
    tools = body.get("tools")

    for msg in body.get("messages", []):
        role = msg.get("role", "user")
        content = msg.get("content", "") or ""

        if role == "system":
            parts_sys.append(content)
        elif role == "user":
            parts_conv.append(f"User: {content}")
        elif role == "assistant":
            tc = msg.get("tool_calls", [])
            if tc:
                tc_text = "\n".join(
                    f'<tool_call>\n{{"name": "{c["function"]["name"]}", '
                    f'"arguments": {c["function"]["arguments"]}}}\n</tool_call>'
                    for c in tc
                )
                parts_conv.append(f"Assistant:\n{tc_text}" if not content else f"Assistant: {content}\n{tc_text}")
            elif content:
                parts_conv.append(f"Assistant: {content}")
        elif role == "tool":
            parts_conv.append(f"Tool result ({msg.get('name', 'tool')}):\n{content}")

    if tools:
        parts_sys.append(_format_tool_defs(tools))

    sys_text = "\n\n".join(parts_sys)
    conv_text = "\n\n".join(parts_conv)
    prompt = f"System Instructions:\n{sys_text}\n\n{conv_text}" if sys_text else conv_text
    return prompt, bool(tools)


def _openai_response(content: str, tool_calls: List[Dict], model: str, body: Dict) -> Dict:
    """Build OpenAI chat.completion response directly from parsed output."""
    msg: Dict[str, Any] = {"role": "assistant", "content": content or None}
    if tool_calls:
        msg["tool_calls"] = [
            {"id": tc["id"], "type": "function", "function": {"name": tc["name"], "arguments": tc["arguments_str"]}}
            for tc in tool_calls
        ]
    finish = "tool_calls" if tool_calls else "stop"
    msgs = body.get("messages", [])
    ptok = sum(len(str(m.get("content", ""))) // 4 for m in msgs)
    ctok = len(content or "") // 4
    return {
        "id": f"chatcmpl-{uuid.uuid4().hex[:12]}", "object": "chat.completion",
        "created": int(time.time()), "model": model,
        "choices": [{"index": 0, "message": msg, "finish_reason": finish}],
        "usage": {"prompt_tokens": ptok, "completion_tokens": ctok, "total_tokens": ptok + ctok},
    }


def _openai_stream_chunks(content: str, tool_calls: List[Dict], model: str):
    """Yield OpenAI SSE chunks directly."""
    cid = f"chatcmpl-{uuid.uuid4().hex[:12]}"
    ts = int(time.time())
    if tool_calls:
        yield f"data: {json.dumps({'id': cid, 'object': 'chat.completion.chunk', 'created': ts, 'model': model, 'choices': [{'index': 0, 'delta': {'role': 'assistant', 'content': None}, 'finish_reason': None}]})}\n\n"
        for i, tc in enumerate(tool_calls):
            yield f"data: {json.dumps({'id': cid, 'object': 'chat.completion.chunk', 'created': ts, 'model': model, 'choices': [{'index': 0, 'delta': {'tool_calls': [{'index': i, 'id': tc['id'], 'type': 'function', 'function': {'name': tc['name'], 'arguments': tc['arguments_str']}}]}, 'finish_reason': None}]})}\n\n"
        yield f"data: {json.dumps({'id': cid, 'object': 'chat.completion.chunk', 'created': ts, 'model': model, 'choices': [{'index': 0, 'delta': {}, 'finish_reason': 'tool_calls'}]})}\n\n"
    else:
        yield f"data: {json.dumps({'id': cid, 'object': 'chat.completion.chunk', 'created': ts, 'model': model, 'choices': [{'index': 0, 'delta': {'role': 'assistant', 'content': content}, 'finish_reason': None}]})}\n\n"
        yield f"data: {json.dumps({'id': cid, 'object': 'chat.completion.chunk', 'created': ts, 'model': model, 'choices': [{'index': 0, 'delta': {}, 'finish_reason': 'stop'}]})}\n\n"
    yield "data: [DONE]\n\n"


# ──── Anthropic: Direct Path ────────────────────────────────────────────────
# Anthropic body → flat text → Copilot → parse → Anthropic response

def _anthropic_to_prompt(body: Dict) -> Tuple[str, bool]:
    """Serialize Anthropic request directly to Copilot flat prompt."""
    parts_sys: List[str] = []
    parts_conv: List[str] = []

    # System (top-level field in Anthropic)
    system = body.get("system", "")
    if isinstance(system, list):
        system = "\n".join(b.get("text", "") for b in system if b.get("type") == "text")
    if system:
        parts_sys.append(system)

    tools = body.get("tools")
    if tools:
        # Anthropic tools: {name, description, input_schema}
        parts_sys.append(_format_tool_defs(tools))

    for msg in body.get("messages", []):
        role = msg.get("role", "user")
        content = msg.get("content", "")

        if isinstance(content, str):
            parts_conv.append(f"{'User' if role == 'user' else 'Assistant'}: {content}")
        elif isinstance(content, list):
            texts = []
            for block in content:
                bt = block.get("type", "text")
                if bt == "text":
                    texts.append(block.get("text", ""))
                elif bt == "tool_use":
                    args = json.dumps(block.get("input", {}))
                    texts.append(f'<tool_call>\n{{"name": "{block.get("name", "")}", "arguments": {args}}}\n</tool_call>')
                elif bt == "tool_result":
                    rc = block.get("content", "")
                    if isinstance(rc, list):
                        rc = "\n".join(b.get("text", "") for b in rc if b.get("type") == "text")
                    texts.append(f"Tool result ({block.get('tool_use_id', '')}):\n{rc}")
            label = "User" if role == "user" else "Assistant"
            parts_conv.append(f"{label}: " + "\n".join(texts))

    sys_text = "\n\n".join(parts_sys)
    conv_text = "\n\n".join(parts_conv)
    prompt = f"System Instructions:\n{sys_text}\n\n{conv_text}" if sys_text else conv_text
    return prompt, bool(tools)


def _anthropic_response(content: str, tool_calls: List[Dict], model: str, body: Dict) -> Dict:
    """Build Anthropic /v1/messages response directly from parsed output."""
    blocks: List[Dict] = []
    if content:
        blocks.append({"type": "text", "text": content})
    for tc in tool_calls:
        blocks.append({
            "type": "tool_use",
            "id": tc["id"].replace("call_", "toolu_"),
            "name": tc["name"],
            "input": tc["arguments"],
        })
    if not blocks:
        blocks.append({"type": "text", "text": ""})

    stop = "tool_use" if tool_calls else "end_turn"
    msgs = body.get("messages", [])
    ptok = sum(len(str(m.get("content", ""))) // 4 for m in msgs)
    ctok = len(content or "") // 4
    return {
        "id": f"msg_{uuid.uuid4().hex[:16]}", "type": "message", "role": "assistant",
        "model": model, "content": blocks, "stop_reason": stop, "stop_sequence": None,
        "usage": {"input_tokens": ptok, "output_tokens": ctok},
    }


def _anthropic_stream_chunks(content: str, tool_calls: List[Dict], model: str, body: Dict):
    """Yield Anthropic SSE events directly."""
    resp = _anthropic_response(content, tool_calls, model, body)
    blocks = resp["content"]
    ptok = resp["usage"]["input_tokens"]
    ctok = resp["usage"]["output_tokens"]

    yield f"event: message_start\ndata: {json.dumps({'type': 'message_start', 'message': {'id': resp['id'], 'type': 'message', 'role': 'assistant', 'model': model, 'content': [], 'stop_reason': None, 'usage': {'input_tokens': ptok, 'output_tokens': 0}}})}\n\n"
    for i, block in enumerate(blocks):
        yield f"event: content_block_start\ndata: {json.dumps({'type': 'content_block_start', 'index': i, 'content_block': block})}\n\n"
        yield f"event: content_block_stop\ndata: {json.dumps({'type': 'content_block_stop', 'index': i})}\n\n"
    yield f"event: message_delta\ndata: {json.dumps({'type': 'message_delta', 'delta': {'stop_reason': resp['stop_reason']}, 'usage': {'output_tokens': ctok}})}\n\n"
    yield f"event: message_stop\ndata: {json.dumps({'type': 'message_stop'})}\n\n"


# ──── Gemini: Direct Path ───────────────────────────────────────────────────
# Gemini body → flat text → Copilot → parse → Gemini response

def _gemini_to_prompt(body: Dict) -> Tuple[str, bool]:
    """Serialize Gemini request directly to Copilot flat prompt."""
    parts_sys: List[str] = []
    parts_conv: List[str] = []

    # System instruction
    si = body.get("system_instruction", {})
    if si:
        si_text = "\n".join(p.get("text", "") for p in si.get("parts", []) if "text" in p)
        if si_text:
            parts_sys.append(si_text)

    # Tools (Gemini: tools[].function_declarations[])
    tools_found = False
    for tg in body.get("tools", []):
        decls = tg.get("function_declarations", tg.get("functionDeclarations", []))
        if decls:
            tools_found = True
            # Convert to generic format for _format_tool_defs
            generic = [{"name": d.get("name", ""), "description": d.get("description", ""), "parameters": d.get("parameters", {})} for d in decls]
            parts_sys.append(_format_tool_defs(generic))

    for content in body.get("contents", []):
        role = content.get("role", "user")
        label = "User" if role == "user" else "Assistant"
        texts = []
        for part in content.get("parts", []):
            if "text" in part:
                texts.append(part["text"])
            elif "functionCall" in part:
                fc = part["functionCall"]
                args = json.dumps(fc.get("args", {}))
                texts.append(f'<tool_call>\n{{"name": "{fc.get("name", "")}", "arguments": {args}}}\n</tool_call>')
            elif "functionResponse" in part:
                fr = part["functionResponse"]
                texts.append(f"Tool result ({fr.get('name', '')}):\n{json.dumps(fr.get('response', {}))}")
        parts_conv.append(f"{label}: " + "\n".join(texts))

    sys_text = "\n\n".join(parts_sys)
    conv_text = "\n\n".join(parts_conv)
    prompt = f"System Instructions:\n{sys_text}\n\n{conv_text}" if sys_text else conv_text
    return prompt, tools_found


def _gemini_response(content: str, tool_calls: List[Dict], model: str, body: Dict) -> Dict:
    """Build Gemini generateContent response directly from parsed output."""
    parts: List[Dict] = []
    if content:
        parts.append({"text": content})
    for tc in tool_calls:
        parts.append({"functionCall": {"name": tc["name"], "args": tc["arguments"]}})
    if not parts:
        parts.append({"text": ""})

    msgs = body.get("contents", [])
    ptok = sum(len(str(p.get("text", ""))) for c in msgs for p in c.get("parts", [])) // 4
    ctok = len(content or "") // 4
    return {
        "candidates": [{"content": {"role": "model", "parts": parts}, "finishReason": "STOP", "index": 0}],
        "usageMetadata": {"promptTokenCount": ptok, "candidatesTokenCount": ctok, "totalTokenCount": ptok + ctok},
        "modelVersion": model,
    }


# ──── LMStudio: Direct Passthrough ──────────────────────────────────────────

def _lmstudio_passthrough(body: Dict, stream: bool = False) -> Any:
    """Forward OpenAI request directly to LMStudio. Zero conversion."""
    import requests
    body["stream"] = stream
    resp = requests.post(f"{_cfg['lmstudio_url']}/chat/completions", json=body, timeout=120, stream=stream)
    resp.raise_for_status()
    return resp if stream else resp.json()


# ──── FastAPI Server ─────────────────────────────────────────────────────────

def create_app():
    from fastapi import FastAPI, Body, Request
    from fastapi.middleware.cors import CORSMiddleware
    from fastapi.responses import JSONResponse, StreamingResponse

    app = FastAPI(title="CosySim Model Proxy Direct", version="1.57.2")
    app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])

    @app.get("/health")
    async def health():
        return {"status": "ok", "version": "1.57.2-direct", "protocols": ["openai", "anthropic", "gemini"],
                "models": len(MODELS), "default": _cfg["default_model"]}

    # ── OpenAI ─────────────────────────────────────────────────────

    @app.get("/v1/models")
    async def openai_models():
        return {"object": "list", "data": [
            {"id": m["id"], "object": "model", "created": 1700000000, "owned_by": m["vendor"]} for m in MODELS
        ]}

    @app.post("/v1/chat/completions")
    async def openai_chat(body: Dict[str, Any] = Body(...)):
        model = resolve_model(body.get("model", _cfg["default_model"]))
        stream = body.get("stream", False)

        logger.info("[OpenAI] model=%s msgs=%d stream=%s", model, len(body.get("messages", [])), stream)

        try:
            # LMStudio: full passthrough
            if model == "lmstudio":
                if stream:
                    resp = _lmstudio_passthrough(body, stream=True)
                    async def fwd():
                        for line in resp.iter_lines(decode_unicode=True):
                            if line:
                                yield line + "\n\n"
                    return StreamingResponse(fwd(), media_type="text/event-stream")
                return _lmstudio_passthrough(body)

            # NLM: text only
            if model == "nlm":
                prompt = ""
                for m in reversed(body.get("messages", [])):
                    if m.get("role") == "user":
                        prompt = m.get("content", "")
                        break
                text = _clean(_nlm_call(prompt))
                return _openai_response(text, [], model, body)

            # Copilot: direct path
            prompt, has_tools = _openai_to_prompt(body)

            if stream and not has_tools:
                async def gen():
                    cid = f"chatcmpl-{uuid.uuid4().hex[:12]}"
                    ts = int(time.time())
                    for chunk in _copilot_stream(prompt, model):
                        yield f"data: {json.dumps({'id': cid, 'object': 'chat.completion.chunk', 'created': ts, 'model': model, 'choices': [{'index': 0, 'delta': {'content': chunk}, 'finish_reason': None}]})}\n\n"
                    yield f"data: {json.dumps({'id': cid, 'object': 'chat.completion.chunk', 'created': ts, 'model': model, 'choices': [{'index': 0, 'delta': {}, 'finish_reason': 'stop'}]})}\n\n"
                    yield "data: [DONE]\n\n"
                return StreamingResponse(gen(), media_type="text/event-stream")

            # Buffered (or has tools)
            raw = _clean(_copilot_call(prompt, model))
            content, calls = _parse_tool_calls(raw) if has_tools else (raw, [])

            if stream:
                async def stream_buf():
                    for chunk in _openai_stream_chunks(content, calls, model):
                        yield chunk
                return StreamingResponse(stream_buf(), media_type="text/event-stream")
            return _openai_response(content, calls, model, body)

        except Exception as e:
            logger.error("[OpenAI] %s", e, exc_info=True)
            return JSONResponse(502, {"error": {"message": str(e), "type": "backend_error"}})

    # ── Anthropic ──────────────────────────────────────────────────

    @app.post("/v1/messages")
    async def anthropic_chat(body: Dict[str, Any] = Body(...)):
        model = resolve_model(body.get("model", _cfg["default_model"]))
        stream = body.get("stream", False)

        logger.info("[Anthropic] model=%s msgs=%d stream=%s", model, len(body.get("messages", [])), stream)

        try:
            if model == "nlm":
                prompt = ""
                for m in reversed(body.get("messages", [])):
                    c = m.get("content", "")
                    if m.get("role") == "user":
                        prompt = c if isinstance(c, str) else "\n".join(b.get("text", "") for b in c if b.get("type") == "text")
                        break
                text = _clean(_nlm_call(prompt))
                return _anthropic_response(text, [], model, body)

            # Direct: Anthropic body → prompt → Copilot → Anthropic response
            prompt, has_tools = _anthropic_to_prompt(body)
            raw = _clean(_copilot_call(prompt, model))
            content, calls = _parse_tool_calls(raw) if has_tools else (raw, [])

            if stream:
                async def gen():
                    for chunk in _anthropic_stream_chunks(content, calls, model, body):
                        yield chunk
                return StreamingResponse(gen(), media_type="text/event-stream")
            return _anthropic_response(content, calls, model, body)

        except Exception as e:
            logger.error("[Anthropic] %s", e, exc_info=True)
            return JSONResponse(502, {"type": "error", "error": {"type": "api_error", "message": str(e)}})

    # ── Gemini ─────────────────────────────────────────────────────

    @app.post("/v1beta/models/{model_id}:generateContent")
    async def gemini_generate(model_id: str, body: Dict[str, Any] = Body(...)):
        model = resolve_model(model_id)
        logger.info("[Gemini] model=%s contents=%d", model, len(body.get("contents", [])))

        try:
            if model == "nlm":
                prompt = ""
                for c in reversed(body.get("contents", [])):
                    if c.get("role") == "user":
                        prompt = "\n".join(p.get("text", "") for p in c.get("parts", []) if "text" in p)
                        break
                return _gemini_response(_clean(_nlm_call(prompt)), [], model, body)

            prompt, has_tools = _gemini_to_prompt(body)
            raw = _clean(_copilot_call(prompt, model))
            content, calls = _parse_tool_calls(raw) if has_tools else (raw, [])
            return _gemini_response(content, calls, model, body)

        except Exception as e:
            logger.error("[Gemini] %s", e, exc_info=True)
            return JSONResponse(502, {"error": {"code": 502, "message": str(e), "status": "INTERNAL"}})

    @app.post("/v1beta/models/{model_id}:streamGenerateContent")
    async def gemini_stream(model_id: str, body: Dict[str, Any] = Body(...)):
        return await gemini_generate(model_id, body)

    return app


# ──── Main ───────────────────────────────────────────────────────────────────

def main():
    import argparse
    import uvicorn

    parser = argparse.ArgumentParser(
        description="Model Proxy Direct v1.57.2 -- Zero-Conversion Multi-Protocol Gateway",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Direct-path proxy: each protocol serializes straight to/from Copilot text.
No intermediate OpenAI conversion. ~7x faster than the normalized proxy.

Protocols (all active simultaneously):
  OpenAI:    POST /v1/chat/completions
  Anthropic: POST /v1/messages
  Gemini:    POST /v1beta/models/{model}:generateContent
        """,
    )
    parser.add_argument("--port", type=int, default=5801, help="Server port (default: 5801)")
    parser.add_argument("--default", default="claude-sonnet-4.6", help="Default model")
    parser.add_argument("--account", default="nihilistcod", help="GitHub Copilot account")
    parser.add_argument("--lmstudio-url", default="http://localhost:1234/v1", help="LMStudio base URL")
    parser.add_argument("--cdp-port", type=int, default=9223, help="CDP port for NLM")
    parser.add_argument("--list-models", action="store_true", help="Print catalog and exit")
    args = parser.parse_args()

    if args.list_models:
        print(f"\n  Model Catalog ({len(MODELS)} models)")
        print(f"  {'-' * 55}")
        for m in MODELS:
            print(f"  {m['id']:<25} {m['vendor']:<20} {m['tier']}")
        print()
        return

    _cfg["default_model"] = resolve_model(args.default)
    _cfg["account"] = args.account
    _cfg["lmstudio_url"] = args.lmstudio_url
    _cfg["cdp_port"] = args.cdp_port

    app = create_app()

    print(f"\n{'='*62}")
    print(f"  CosySim Model Proxy Direct v1.57.2")
    print(f"  Zero-conversion multi-protocol gateway")
    print(f"{'='*62}")
    print(f"\n  Port: {args.port}    Default: {_cfg['default_model']}")
    print(f"\n  Protocols (all active, direct path):")
    print(f"    OpenAI:    http://localhost:{args.port}/v1/chat/completions")
    print(f"    Anthropic: http://localhost:{args.port}/v1/messages")
    print(f"    Gemini:    http://localhost:{args.port}/v1beta/models/M:generateContent")
    print(f"\n  Base URL: http://localhost:{args.port}/v1   API Key: anything")
    print(f"  Models: opus, sonnet, haiku, gpt5, codex, gemini, flash, grok, nlm, lmstudio")
    print()

    uvicorn.run(app, host="0.0.0.0", port=args.port, log_level="info")


if __name__ == "__main__":
    main()
