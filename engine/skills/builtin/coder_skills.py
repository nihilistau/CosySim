"""CosySim Coder Skills — LLM-callable tools using the fine-tuned coder model."""
from __future__ import annotations

import logging
import re
from typing import Optional

from engine.skills.skill import skill

logger = logging.getLogger(__name__)

_COSYSIM_CONVENTIONS = """
CosySim conventions:
- Absolute imports only (from engine.config import get_config)
- Type hints on all function signatures
- logger = logging.getLogger(__name__) — never print()
- Google docstrings with Args/Returns/Raises
- @skill decorator for LLM-callable tools
- get_config().get("key", default) for configuration
"""


def _call_lmstudio(prompt: str, model_hint: str = "coder") -> str:
    """Call LMStudio for code generation. Falls back gracefully.

    Args:
        prompt: The full prompt to send.
        model_hint: Hint for which model to use.

    Returns:
        Generated text or fallback message.
    """
    try:
        from engine.lmstudio.client import get_lmstudio_client
        client = get_lmstudio_client()
        response = client.complete(prompt, max_tokens=1024, temperature=0.2)
        if isinstance(response, dict):
            return response.get("content", response.get("text", str(response)))
        return str(response)
    except Exception as e:
        logger.debug(f"LMStudio call failed: {e}")
        return (
            f"[LMStudio unavailable — would send prompt to {model_hint} model]\n"
            f"Prompt preview: {prompt[:200]}..."
        )


@skill(
    pack="coder",
    description="Complete a Python function given its signature and docstring",
    category="SYSTEM",
)
def coder_complete(signature_and_docstring: str, context: str = "") -> str:
    """Complete a Python function using the trained coder model via LMStudio.

    Args:
        signature_and_docstring: Function signature and docstring to complete.
        context: Optional additional context (module name, imports, etc.).

    Returns:
        Completed function source code.
    """
    prompt = (
        f"{_COSYSIM_CONVENTIONS}\n\n"
        f"{'Context: ' + context + chr(10) if context else ''}"
        f"Complete this Python function following CosySim conventions:\n\n"
        f"{signature_and_docstring}\n\n"
        f"# Complete the function body:"
    )
    result = _call_lmstudio(prompt, model_hint="coder")
    try:
        from training.data_collector import get_data_collector
        get_data_collector().collect_code(signature_and_docstring, result, language="python", source="coder_complete")
    except Exception:
        pass
    return result


@skill(
    pack="coder",
    description="Fix a Python bug given the code and optional error message",
    category="SYSTEM",
)
def coder_fix(buggy_code: str, error_message: str = "") -> str:
    """Fix Python code errors. Provide the error message for better results.

    Args:
        buggy_code: The Python code containing a bug.
        error_message: Optional error/traceback message.

    Returns:
        Fixed Python code.
    """
    error_context = f"\nError message:\n{error_message}\n" if error_message else ""
    prompt = (
        f"{_COSYSIM_CONVENTIONS}\n\n"
        f"Fix the bug in this Python code:{error_context}\n\n"
        f"```python\n{buggy_code}\n```\n\n"
        f"Fixed code:"
    )
    result = _call_lmstudio(prompt, model_hint="coder")
    try:
        from training.data_collector import get_data_collector
        prompt_key = f"{buggy_code[:200]}\n{error_message[:100] if error_message else ''}"
        get_data_collector().collect_code(prompt_key, result, language="python", source="coder_fix")
    except Exception:
        pass
    return result


@skill(
    pack="coder",
    description="Generate Python code from a natural language specification",
    category="SYSTEM",
)
def coder_generate(specification: str, module_context: str = "") -> str:
    """Generate new Python code following CosySim conventions.

    Args:
        specification: Natural language description of the code to generate.
        module_context: Optional module/class context.

    Returns:
        Generated Python code.
    """
    prompt = (
        f"{_COSYSIM_CONVENTIONS}\n\n"
        f"{'Module context: ' + module_context + chr(10) if module_context else ''}"
        f"Generate Python code for: {specification}\n\n"
        f"Follow all CosySim conventions. Generated code:"
    )
    result = _call_lmstudio(prompt, model_hint="coder")
    try:
        from training.data_collector import get_data_collector
        get_data_collector().collect_code(specification, result, language="python", source="coder_generate")
    except Exception:
        pass
    return result


@skill(
    pack="coder",
    description="Review code for CosySim convention compliance",
    category="SYSTEM",
)
def coder_review(code: str) -> str:
    """Check code for: absolute imports, type hints, no print(), Google docstrings, @skill usage.

    Args:
        code: Python source code to review.

    Returns:
        Newline-separated list of violations, or 'OK — no violations found'.
    """
    violations: list = []

    lines = code.splitlines()
    for i, line in enumerate(lines, 1):
        stripped = line.strip()
        # Check relative imports
        if stripped.startswith("from .") or stripped.startswith("import ."):
            violations.append(
                f"Line {i}: relative import found — use absolute imports "
                f"(e.g., from engine.config import get_config)"
            )

        # Check print() — but not in comments or docstrings
        if "print(" in line:
            comment_start = line.find("#")
            print_pos = line.find("print(")
            if comment_start == -1 or print_pos < comment_start:
                violations.append(
                    f"Line {i}: print() found — use logger.info() / logger.debug()"
                )

    # Check missing return type hint on def lines
    for i, line in enumerate(lines, 1):
        if re.match(r"\s*def \w+\(", line) and "->" not in line and ":" in line:
            if not line.strip().startswith("#"):
                violations.append(
                    f"Line {i}: missing return type hint on function definition"
                )

    # Check missing type hints on parameters (heuristic: def foo(x, y):)
    for i, line in enumerate(lines, 1):
        m = re.match(r"\s*def \w+\(([^)]+)\)\s*:", line)
        if m:
            params = m.group(1)
            if (
                params.strip()
                and "self" not in params
                and ":" not in params
                and "*" not in params
            ):
                violations.append(
                    f"Line {i}: function parameters appear to lack type hints"
                )

    # Check hardcoded absolute paths (heuristic)
    for i, line in enumerate(lines, 1):
        if re.search(r'["\']C:\\\\|["\']\/home\/|["\']\/var\/', line):
            violations.append(
                f"Line {i}: hardcoded path found — use Path() and get_config()"
            )

    # Check hardcoded port numbers
    for i, line in enumerate(lines, 1):
        if (
            re.search(r"=\s*(8[0-9]{3}|1234|5[0-9]{3})\b", line)
            and "port" not in line.lower()
            and "#" not in line
        ):
            violations.append(
                f"Line {i}: possible hardcoded port number — use get_config().get('...', default)"
            )

    if not violations:
        return "OK — no violations found"
    return "\n".join(violations)


@skill(
    pack="coder",
    description="Add type hints to a Python function",
    category="SYSTEM",
)
def coder_add_types(code: str) -> str:
    """Add missing type hints to function signatures using the coder model.

    Args:
        code: Python function source code lacking type hints.

    Returns:
        Code with type hints added.
    """
    prompt = (
        f"{_COSYSIM_CONVENTIONS}\n\n"
        f"Add appropriate Python type hints to all function signatures in this code.\n"
        f"Preserve all existing logic. Only add/update type annotations.\n\n"
        f"```python\n{code}\n```\n\n"
        f"Code with type hints added:"
    )
    return _call_lmstudio(prompt, model_hint="coder")


@skill(
    pack="coder",
    description="Generate a Google-style docstring for a function",
    category="SYSTEM",
)
def coder_docstring(function_code: str) -> str:
    """Generate a complete Google-style docstring for the given function.

    Args:
        function_code: Python function source code without a docstring.

    Returns:
        The docstring text (without triple-quotes, ready to insert).
    """
    prompt = (
        f"Generate a Google-style Python docstring for this function.\n"
        f"Include: one-line summary, Args section, Returns section, Raises section (if applicable).\n\n"
        f"```python\n{function_code}\n```\n\n"
        f"Docstring (Google style, without triple quotes):"
    )
    return _call_lmstudio(prompt, model_hint="coder")


@skill(
    pack="coder",
    description="Scaffold a new @skill function with decorator, type hints, and docstring",
    category="SYSTEM",
)
def coder_scaffold_skill(
    name: str,
    description: str,
    pack: str = "custom",
    category: str = "GAME",
) -> str:
    """Generate a complete @skill function scaffold ready to implement.

    Args:
        name: The skill function name (snake_case).
        description: What the skill does (used in the @skill decorator).
        pack: Skill pack name.
        category: Skill category (GAME, SYSTEM, MEMORY, etc.).

    Returns:
        Complete @skill function boilerplate as a string.
    """
    # Pure template — no LMStudio needed
    scaffold = (
        f'@skill(\n'
        f'    pack="{pack}",\n'
        f'    description="{description}",\n'
        f'    category="{category}",\n'
        f')\n'
        f'def {name}(  # TODO: add parameters with type hints\n'
        f') -> str:\n'
        f'    """{description}.\n\n'
        f'    Args:\n'
        f'        # TODO: document parameters\n\n'
        f'    Returns:\n'
        f'        Result string for LLM consumption.\n'
        f'    """\n'
        f'    try:\n'
        f'        # TODO: implement\n'
        f'        result = ""\n'
        f'        return result or "Done."\n'
        f'    except Exception as e:\n'
        f'        logger.error(f"{name} failed: {{e}}")\n'
        f'        return f"Error in {name}: {{e}}"\n'
    )
    return scaffold


@skill(
    pack="coder",
    description="Get the status of the coder model pipeline",
    category="SYSTEM",
)
def coder_status() -> str:
    """Return coder pipeline status: dataset size, active job, best score, readiness.

    Returns:
        Human-readable status string.
    """
    try:
        from training.coder_pipeline import get_coder_pipeline
        pipeline = get_coder_pipeline()
        s = pipeline.status()
        lines = [
            "Coder Pipeline Status:",
            f"  Dataset: {s.dataset_size} examples (threshold: {s.train_threshold})",
            f"  Ready to train: {s.ready_to_train}",
            f"  Active job: {s.active_job_id or 'none'} ({s.active_job_status or 'n/a'})",
            f"  Active model: {s.active_model_id or 'none'}",
            f"  Best score: {s.best_score:.3f}",
            f"  LMStudio loaded: {s.lmstudio_loaded}",
            f"  Last refresh: {s.last_dataset_refresh or 'never'}",
        ]
        return "\n".join(lines)
    except Exception as e:
        logger.error(f"coder_status failed: {e}")
        return f"Error getting coder status: {e}"


@skill(
    pack="coder",
    description="Trigger a coder dataset refresh from the codebase",
    category="SYSTEM",
)
def coder_rebuild_dataset() -> str:
    """Rebuild coder training dataset from CosySim codebase and Nexus Q&A.

    Returns:
        Summary of rebuild result.
    """
    try:
        from training.coder_pipeline import get_coder_pipeline
        pipeline = get_coder_pipeline()
        count = pipeline.refresh_dataset()
        return f"Coder dataset rebuilt: {count} examples."
    except Exception as e:
        logger.error(f"coder_rebuild_dataset failed: {e}")
        return f"Error rebuilding coder dataset: {e}"
