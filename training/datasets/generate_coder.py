"""Auto-generate coder training dataset from CosySim codebase and Nexus Q&A."""
from __future__ import annotations

import ast
import json
import logging
import random
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)

_OUTPUT_PATH = Path("training/datasets/coder_train.jsonl")
_INSTRUCTION = "Complete or generate the requested code following CosySim conventions."

_CODEBASE_ROOT = Path(".")
_SCAN_DIRS = [
    "engine",
    "content/scenes",
    "training",
    "tests",
]
_EXCLUDE_PATTERNS = {
    "__pycache__",
    ".pyc",
    "unsloth_compiled_cache",
    "node_modules",
    ".git",
}


def scan_codebase(max_files: int = 200) -> List[Dict[str, Any]]:
    """Scan CosySim Python files to extract docstring + function examples.

    Args:
        max_files: Maximum number of files to scan.

    Returns:
        List of example dicts with input (docstring/context) and output (code).
    """
    examples: List[Dict[str, Any]] = []
    scanned = 0

    for scan_dir in _SCAN_DIRS:
        dir_path = _CODEBASE_ROOT / scan_dir
        if not dir_path.exists():
            continue
        for py_file in dir_path.rglob("*.py"):
            if scanned >= max_files:
                break
            if any(excl in str(py_file) for excl in _EXCLUDE_PATTERNS):
                continue
            try:
                file_examples = _extract_from_file(py_file)
                examples.extend(file_examples)
                scanned += 1
            except Exception as e:
                logger.debug(f"Could not scan {py_file}: {e}")

    logger.info(f"Scanned {scanned} files, extracted {len(examples)} code examples")
    return examples


def _extract_from_file(path: Path) -> List[Dict[str, Any]]:
    """Extract training examples from a Python file.

    Args:
        path: Path to a Python source file.

    Returns:
        List of (docstring/signature → function body) example dicts.
    """
    examples: List[Dict[str, Any]] = []
    try:
        source = path.read_text(encoding="utf-8")
        tree = ast.parse(source)
    except Exception:
        return examples

    lines = source.splitlines()

    for node in ast.walk(tree):
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        if not (node.body and isinstance(node.body[0], ast.Expr) and isinstance(node.body[0].value, ast.Constant)):
            continue

        docstring = ast.get_docstring(node)
        if not docstring or len(docstring) < 20:
            continue

        # Get function source lines
        start = node.lineno - 1
        end = node.end_lineno if hasattr(node, "end_lineno") else start + 20
        func_lines = lines[start:end]
        if len(func_lines) < 3:
            continue

        func_source = "\n".join(func_lines)
        if len(func_source) > 2000:
            continue

        # Build input: docstring + signature context
        sig_line = func_lines[0] if func_lines else ""
        module_name = path.stem
        input_text = (
            f"# Module: {module_name}\n"
            f"# Task: {docstring.split(chr(10))[0]}\n"
            f"{sig_line}"
        )
        examples.append({"input": input_text, "output": func_source})

    return examples


def extract_nexus_code_qa(limit: int = 500) -> List[Dict[str, Any]]:
    """Extract code-related Q&A pairs from Nexus.

    Args:
        limit: Maximum number of entries to extract.

    Returns:
        List of example dicts extracted from Nexus code entries.
    """
    examples: List[Dict[str, Any]] = []
    try:
        from engine.nexus.client import get_nexus_client
        client = get_nexus_client()
        results = client.search("python code snippet cosysim", limit=limit)
        for entry in results:
            content = entry.get("content", "")
            title = entry.get("title", "")
            if not content or len(content) < 50:
                continue
            if any(kw in content for kw in ["def ", "class ", "import ", "```python"]):
                input_text = f"# {title}" if title else "# Complete this CosySim code"
                examples.append({"input": input_text, "output": content})
    except Exception as e:
        logger.debug(f"extract_nexus_code_qa failed: {e}")
    return examples


def generate_docstring_prompts(examples: List[Dict[str, Any]], count: int = 200) -> List[Dict[str, Any]]:
    """Generate docstring-to-code prompts from existing examples.

    Args:
        examples: Existing code examples to derive prompts from.
        count: Number of additional prompts to generate.

    Returns:
        List of additional example dicts.
    """
    extra: List[Dict[str, Any]] = []
    pool = [e for e in examples if "def " in e.get("output", "")]
    random.shuffle(pool)

    for ex in pool[:count]:
        output = ex.get("output", "")
        # Create a "complete this function" prompt
        lines = output.splitlines()
        if len(lines) >= 3:
            # Just the signature + docstring as input, full function as output
            sig_lines = []
            for i, line in enumerate(lines):
                sig_lines.append(line)
                if i > 0 and '"""' in line and i > 1:
                    break
            if len(sig_lines) >= 2:
                input_text = "\n".join(sig_lines) + "\n    # ... complete this function"
                extra.append({"input": input_text, "output": output})

    return extra


def save_dataset(examples: List[Dict[str, Any]], output_path: Optional[Path] = None) -> Path:
    """Save coder examples to JSONL in Alpaca format.

    Args:
        examples: List of example dicts with input/output keys.
        output_path: Output path. Defaults to training/datasets/coder_train.jsonl.

    Returns:
        Path to the saved file.
    """
    out = output_path or _OUTPUT_PATH
    out.parent.mkdir(parents=True, exist_ok=True)

    random.shuffle(examples)
    with out.open("w", encoding="utf-8") as f:
        for ex in examples:
            record = {
                "instruction": _INSTRUCTION,
                "input": ex.get("input", ""),
                "output": ex.get("output", ""),
                "model_type": "coder",
            }
            f.write(json.dumps(record) + "\n")

    logger.info(f"Saved {len(examples)} coder examples to {out}")
    return out


def main() -> None:
    """Generate and save the coder training dataset."""
    logging.basicConfig(level=logging.INFO)
    examples: List[Dict[str, Any]] = []

    # 1. Scan codebase
    codebase_examples = scan_codebase(max_files=200)
    examples.extend(codebase_examples)

    # 2. Extract from Nexus
    nexus_examples = extract_nexus_code_qa(limit=500)
    examples.extend(nexus_examples)

    # 3. Generate docstring prompts
    extra = generate_docstring_prompts(examples, count=200)
    examples.extend(extra)

    # Deduplicate
    seen: set = set()
    unique: List[Dict[str, Any]] = []
    for ex in examples:
        key = ex.get("input", "")[:100]
        if key not in seen:
            seen.add(key)
            unique.append(ex)

    path = save_dataset(unique[:2000])
    print(f"Generated {len(unique)} coder examples → {path}")


if __name__ == "__main__":
    main()
