"""GitHub Copilot skill pack.

Exposes GitHub Copilot AI models as MCP @skill tools for use by LLM agents
and scene systems.  Requires a GitHub account with Copilot access imported
via GithubAccountImporter.
"""
from __future__ import annotations

import logging
from typing import Any, Dict, List

from engine.skills.skill import skill

logger = logging.getLogger(__name__)

_DEFAULT_ACCOUNT = "nihilistcod"


def _client(account: str = _DEFAULT_ACCOUNT):  # type: ignore[return]
    """Return the singleton Copilot client, logging errors if unavailable."""
    from engine.integrations.github_copilot_client import get_copilot_client

    return get_copilot_client(account)


# ──── Core skills ─────────────────────────────────────────────────────────────


@skill(
    pack="copilot",
    description=(
        "Ask any GitHub Copilot model a question. "
        "Supports all 26 models including Claude, GPT, Gemini, and Grok. "
        "Default model is claude-sonnet-4.6."
    ),
    category="SYSTEM",
)
def copilot_ask(prompt: str, model: str = "claude-sonnet-4.6") -> str:
    """Send a prompt to GitHub Copilot and return the response.

    Args:
        prompt: The question or instruction to send.
        model: Copilot model ID (e.g. "claude-sonnet-4.6", "gpt-5.2-codex").

    Returns:
        Full response text from the model, or an error message.
    """
    try:
        return _client().ask(prompt, model=model)
    except Exception as exc:
        logger.error("copilot_ask failed: %s", exc)
        return f"Copilot error: {exc}"


@skill(
    pack="copilot",
    description=(
        "Generate code using GitHub Copilot. "
        "Specify the programming language and describe what you need. "
        "Default model is gpt-5.2-codex for best code generation."
    ),
    category="SYSTEM",
)
def copilot_code(
    prompt: str,
    language: str = "python",
    model: str = "gpt-5.2-codex",
) -> str:
    """Ask Copilot to generate code in a specific language.

    Args:
        prompt: Description of the code to generate.
        language: Target programming language.
        model: Copilot model to use.

    Returns:
        Generated code as a string.
    """
    full_prompt = (
        f"Write {language} code for the following task. "
        f"Return only the code, no explanations:\n\n{prompt}"
    )
    try:
        return _client().ask(full_prompt, model=model)
    except Exception as exc:
        logger.error("copilot_code failed: %s", exc)
        return f"Copilot code generation error: {exc}"


@skill(
    pack="copilot",
    description=(
        "Review code using GitHub Copilot. "
        "Provides feedback on bugs, style, performance, and best practices."
    ),
    category="SYSTEM",
)
def copilot_review(code: str, language: str = "python") -> str:
    """Ask Copilot to review code for issues and improvements.

    Args:
        code: Source code to review.
        language: Programming language of the code.

    Returns:
        Review feedback from Copilot.
    """
    prompt = (
        f"Review the following {language} code. "
        "Identify bugs, style issues, performance problems, and security concerns. "
        "Be concise and actionable:\n\n"
        f"```{language}\n{code}\n```"
    )
    try:
        return _client().ask(prompt, model="claude-sonnet-4.6")
    except Exception as exc:
        logger.error("copilot_review failed: %s", exc)
        return f"Copilot review error: {exc}"


@skill(
    pack="copilot",
    description=(
        "Fast response using Claude Haiku — lowest latency Copilot model. "
        "Best for quick questions, classification, or simple transformations."
    ),
    category="SYSTEM",
)
def copilot_fast(prompt: str) -> str:
    """Send a prompt to Claude Haiku for a fast response.

    Args:
        prompt: The question or instruction.

    Returns:
        Response text from Claude Haiku.
    """
    try:
        return _client().ask(prompt, model="claude-haiku-4.5")
    except Exception as exc:
        logger.error("copilot_fast failed: %s", exc)
        return f"Copilot fast error: {exc}"


@skill(
    pack="copilot",
    description=(
        "Deep reasoning using Claude Opus — highest capability Copilot model. "
        "Best for complex analysis, multi-step reasoning, or nuanced writing."
    ),
    category="SYSTEM",
)
def copilot_smart(prompt: str) -> str:
    """Send a prompt to Claude Opus for deep reasoning.

    Args:
        prompt: The question or instruction requiring deep analysis.

    Returns:
        Response text from Claude Opus.
    """
    try:
        return _client().ask(prompt, model="claude-opus-4.6")
    except Exception as exc:
        logger.error("copilot_smart failed: %s", exc)
        return f"Copilot smart error: {exc}"


@skill(
    pack="copilot",
    description=(
        "List all available GitHub Copilot models. "
        "Returns a formatted list of model IDs grouped by vendor."
    ),
    category="SYSTEM",
)
def copilot_models() -> str:
    """Fetch and format all available Copilot models.

    Returns:
        Formatted list of models as a readable string.
    """
    try:
        models = _client().list_models()
        if not models:
            return "No models available."

        # Group by vendor
        by_vendor: Dict[str, List[str]] = {}
        for m in models:
            vendor = m.get("vendor", m.get("company", "Other"))
            mid = m.get("id", str(m))
            by_vendor.setdefault(vendor, []).append(mid)

        lines = [f"Available Copilot models ({len(models)} total):"]
        for vendor, ids in sorted(by_vendor.items()):
            lines.append(f"\n{vendor}:")
            for mid in sorted(ids):
                lines.append(f"  - {mid}")
        return "\n".join(lines)
    except Exception as exc:
        logger.error("copilot_models failed: %s", exc)
        return f"Copilot models error: {exc}"


@skill(
    pack="copilot",
    description=(
        "Multi-turn Copilot conversation. "
        "Pass a list of {role, content} dicts. "
        "Creates a thread and sends messages in order, threading each reply."
    ),
    category="SYSTEM",
)
def copilot_thread(
    messages: List[Dict[str, str]],
    model: str = "claude-sonnet-4.6",
) -> str:
    """Run a multi-turn conversation using a Copilot thread.

    Args:
        messages: List of ``{"role": "user"|"assistant", "content": "..."}`` dicts.
        model: Copilot model to use throughout the conversation.

    Returns:
        Final assistant response text.
    """
    if not messages:
        return "No messages provided."

    try:
        client = _client()
        thread_id = client.create_thread()
        parent_message_id = "root"
        last_response = ""

        for msg in messages:
            role = msg.get("role", "user")
            content = msg.get("content", "")
            if role == "assistant":
                # Skip injected assistant turns; they don't get sent
                continue
            text, message_id = client.send_message(
                thread_id,
                content,
                model=model,
                parent_message_id=parent_message_id,
            )
            last_response = text
            parent_message_id = message_id

        return last_response
    except Exception as exc:
        logger.error("copilot_thread failed: %s", exc)
        return f"Copilot thread error: {exc}"


@skill(
    pack="copilot",
    description=(
        "Summarize text using GitHub Copilot. "
        "Style can be 'concise', 'detailed', or 'bullet'."
    ),
    category="SYSTEM",
)
def copilot_summarize(text: str, style: str = "concise") -> str:
    """Summarize text in the requested style.

    Args:
        text: The text to summarize.
        style: Summary style — ``"concise"``, ``"detailed"``, or ``"bullet"``.

    Returns:
        Summary from Copilot.
    """
    style_instructions = {
        "concise": "in 2-3 sentences",
        "detailed": "with a thorough paragraph covering key points",
        "bullet": "as a bullet-point list of key takeaways",
    }
    instruction = style_instructions.get(style, "concisely")
    prompt = f"Summarize the following text {instruction}:\n\n{text}"
    try:
        return _client().ask(prompt, model="claude-sonnet-4.6")
    except Exception as exc:
        logger.error("copilot_summarize failed: %s", exc)
        return f"Copilot summarize error: {exc}"


@skill(
    pack="copilot",
    description=(
        "Analyze and explain code using GitHub Copilot. "
        "Provides a clear explanation of what the code does and how it works."
    ),
    category="SYSTEM",
)
def copilot_explain(code: str, language: str = "") -> str:
    """Ask Copilot to explain a piece of code.

    Args:
        code: Source code to explain.
        language: Optional programming language hint.

    Returns:
        Plain-language explanation from Copilot.
    """
    lang_hint = f" ({language})" if language else ""
    prompt = (
        f"Explain what the following code{lang_hint} does, "
        "step by step in plain language:\n\n"
        f"```{language}\n{code}\n```"
    )
    try:
        return _client().ask(prompt, model="claude-sonnet-4.6")
    except Exception as exc:
        logger.error("copilot_explain failed: %s", exc)
        return f"Copilot explain error: {exc}"
