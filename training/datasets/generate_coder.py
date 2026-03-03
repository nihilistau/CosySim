"""Auto-generate coder training dataset from CosySim codebase and Nexus Q&A.

Implements 10 complementary strategies to produce 5000+ diverse examples
for fine-tuning the CosySim coder model (llama-3b base).
"""
from __future__ import annotations

import ast
import json
import logging
import random
import subprocess
import textwrap
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)

_OUTPUT_PATH = Path("training/datasets/coder_train.jsonl")
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

# ──── Helpers ─────────────────────────────────────────────────────────────────


def _make_example(
    instruction: str,
    input_text: str,
    output: str,
    strategy: str,
    source_file: str = "",
    convention_type: Optional[str] = None,
) -> Dict[str, Any]:
    """Build a standardised training example dict."""
    return {
        "instruction": instruction,
        "input": input_text,
        "output": output,
        "model_type": "coder",
        "strategy": strategy,
        "source_file": source_file,
        "convention_type": convention_type,
    }


def _get_python_files(max_files: int = 300) -> List[Path]:
    """Collect Python files from scan dirs, respecting exclude patterns."""
    files: List[Path] = []
    for scan_dir in _SCAN_DIRS:
        dir_path = _CODEBASE_ROOT / scan_dir
        if not dir_path.exists():
            continue
        for py_file in dir_path.rglob("*.py"):
            if any(excl in str(py_file) for excl in _EXCLUDE_PATTERNS):
                continue
            files.append(py_file)
            if len(files) >= max_files:
                return files
    return files


def _get_func_source(lines: List[str], node: ast.FunctionDef) -> str:
    """Extract function source from file lines."""
    start = node.lineno - 1
    end = getattr(node, "end_lineno", start + 30)
    return "\n".join(lines[start:end])


# ──── Strategy 1: FIM-style function completion ───────────────────────────────


def generate_fim_examples() -> List[Dict[str, Any]]:
    """Generate fill-in-the-middle examples by splitting function bodies.

    Returns:
        List of FIM training examples.
    """
    examples: List[Dict[str, Any]] = []
    for path in _get_python_files(max_files=200):
        try:
            source = path.read_text(encoding="utf-8")
            tree = ast.parse(source)
        except Exception:
            continue
        lines = source.splitlines()
        for node in ast.walk(tree):
            if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            func_lines_count = getattr(node, "end_lineno", node.lineno) - node.lineno
            if func_lines_count < 5:
                continue
            func_source = _get_func_source(lines, node)
            func_lines = func_source.splitlines()
            if len(func_lines) < 5:
                continue
            # Find a split point (not first 2 or last 1 lines)
            split_candidates = list(range(2, len(func_lines) - 1))
            if not split_candidates:
                continue
            split_at = random.choice(split_candidates)
            prefix = "\n".join(func_lines[:split_at])
            mod_name = path.stem
            # Build docstring/sig for context
            sig = func_lines[0]
            docstring = ast.get_docstring(node) or ""
            doc_preview = docstring.split("\n")[0][:80] if docstring else ""
            input_text = (
                f"# Module: {mod_name}\n"
                f"# Complete this function:\n"
                f"{sig}\n"
                f'{("    " + chr(34)*3 + doc_preview + chr(34)*3) if doc_preview else ""}\n'
                f"{prefix}\n"
                f"    # ... complete this function"
            ).strip()
            if len(func_source) > 3000 or len(func_source) < 50:
                continue
            examples.append(_make_example(
                instruction="Complete the partial Python function following CosySim conventions.",
                input_text=input_text,
                output=func_source,
                strategy="fim_completion",
                source_file=str(path),
            ))
    return examples


# ──── Strategy 2: Docstring → implementation ─────────────────────────────────


def generate_docstring_examples() -> List[Dict[str, Any]]:
    """Generate signature+docstring → full function body examples.

    Returns:
        List of docstring-to-implementation training examples.
    """
    examples: List[Dict[str, Any]] = []
    for path in _get_python_files(max_files=200):
        try:
            source = path.read_text(encoding="utf-8")
            tree = ast.parse(source)
        except Exception:
            continue
        lines = source.splitlines()
        for node in ast.walk(tree):
            if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            docstring = ast.get_docstring(node)
            if not docstring or len(docstring) < 20:
                continue
            func_source = _get_func_source(lines, node)
            if len(func_source) > 3000 or len(func_source) < 50:
                continue
            func_lines = func_source.splitlines()
            # Collect sig + docstring lines
            sig_doc_lines: List[str] = []
            in_docstring = False
            ds_count = 0
            for fl in func_lines:
                sig_doc_lines.append(fl)
                if '"""' in fl or "'''" in fl:
                    ds_count += fl.count('"""') + fl.count("'''")
                    in_docstring = ds_count % 2 != 0
                    if ds_count >= 2:
                        break
            if len(sig_doc_lines) < 2:
                continue
            input_text = "\n".join(sig_doc_lines) + "\n    # ... implement this function"
            examples.append(_make_example(
                instruction="Implement the Python function described by the docstring.",
                input_text=input_text,
                output=func_source,
                strategy="docstring_to_impl",
                source_file=str(path),
            ))
    return examples


# ──── Strategy 3: Bug injection + fix ────────────────────────────────────────


def _inject_wrong_indent(func_lines: List[str]) -> Optional[str]:
    """Dedent the last return statement by one level."""
    for i in range(len(func_lines) - 1, 0, -1):
        if func_lines[i].lstrip().startswith("return "):
            indent = len(func_lines[i]) - len(func_lines[i].lstrip())
            if indent >= 4:
                buggy = list(func_lines)
                buggy[i] = func_lines[i][4:]  # remove one indent level
                return "\n".join(buggy)
    return None


def _inject_missing_self(func_lines: List[str]) -> Optional[str]:
    """Remove self. from first attribute access in function body."""
    import re
    for i in range(1, len(func_lines)):
        m = re.search(r"\bself\.(\w+)", func_lines[i])
        if m:
            buggy = list(func_lines)
            buggy[i] = func_lines[i].replace(m.group(0), m.group(1), 1)
            return "\n".join(buggy)
    return None


def _inject_wrong_comparison(func_lines: List[str]) -> Optional[str]:
    """Replace == with = in a condition (only when single safe occurrence)."""
    import re
    for i in range(1, len(func_lines)):
        line = func_lines[i]
        stripped = line.lstrip()
        if stripped.startswith("if ") and "==" in line:
            # Count == occurrences
            occurrences = line.count("==")
            if occurrences == 1:
                buggy = list(func_lines)
                buggy[i] = line.replace("==", "=", 1)
                return "\n".join(buggy)
    return None


def _inject_missing_colon(func_lines: List[str]) -> Optional[str]:
    """Remove : from an if/for/def line."""
    import re
    for i in range(1, len(func_lines)):
        stripped = func_lines[i].lstrip()
        if re.match(r"(if |for |def )\w", stripped) and func_lines[i].rstrip().endswith(":"):
            buggy = list(func_lines)
            buggy[i] = func_lines[i].rstrip()[:-1]
            return "\n".join(buggy)
    return None


def _inject_wrong_var(func_lines: List[str]) -> Optional[str]:
    """Swap two variable names in the body."""
    import re
    # Collect variable names from assignments
    var_names: List[str] = []
    for line in func_lines[1:]:
        for m in re.finditer(r"\b([a-z_][a-z0-9_]*)\s*=\s*[^=]", line):
            name = m.group(1)
            if name not in ("self", "cls") and name not in var_names:
                var_names.append(name)
    if len(var_names) < 2:
        return None
    a, b = var_names[0], var_names[1]
    # Only swap if both appear in body
    body = "\n".join(func_lines[1:])
    if body.count(a) < 1 or body.count(b) < 1:
        return None
    buggy_body = body.replace(a, "__PLACEHOLDER__").replace(b, a).replace("__PLACEHOLDER__", b)
    return func_lines[0] + "\n" + buggy_body


_BUG_INJECTORS = [
    ("wrong_indent", _inject_wrong_indent),
    ("missing_self", _inject_missing_self),
    ("wrong_comparison", _inject_wrong_comparison),
    ("missing_colon", _inject_missing_colon),
    ("wrong_var", _inject_wrong_var),
]


def generate_bug_fix_examples() -> List[Dict[str, Any]]:
    """Generate bug-injection + fix training examples.

    Returns:
        List of bug-fix training examples.
    """
    examples: List[Dict[str, Any]] = []
    for path in _get_python_files(max_files=150):
        try:
            source = path.read_text(encoding="utf-8")
            tree = ast.parse(source)
        except Exception:
            continue
        lines = source.splitlines()
        for node in ast.walk(tree):
            if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            func_source = _get_func_source(lines, node)
            func_lines = func_source.splitlines()
            if len(func_lines) < 8:
                continue
            if len(func_source) > 2000:
                continue
            injected_count = 0
            shuffled_injectors = list(_BUG_INJECTORS)
            random.shuffle(shuffled_injectors)
            for bug_name, injector in shuffled_injectors:
                if injected_count >= 3:
                    break
                try:
                    buggy = injector(func_lines)
                except Exception:
                    continue
                if buggy is None or buggy == func_source:
                    continue
                examples.append(_make_example(
                    instruction="Fix the bug in the Python code below.",
                    input_text=f"Fix the bug in this Python code:\n{buggy}",
                    output=func_source,
                    strategy="bug_fix",
                    source_file=str(path),
                ))
                injected_count += 1
    return examples


# ──── Strategy 4: CosySim convention training ─────────────────────────────────

# Base patterns (wrong → right pairs)
_BASE_CONVENTION_PAIRS: List[Dict[str, Any]] = [
    {
        "wrong": "from .config import get_config",
        "right": "from engine.config import get_config",
        "convention": "absolute_import",
        "instruction": "Fix the import to use an absolute path.",
    },
    {
        "wrong": "from .nexus.client import get_nexus_client",
        "right": "from engine.nexus.client import get_nexus_client",
        "convention": "absolute_import",
        "instruction": "Fix the import to use an absolute path.",
    },
    {
        "wrong": "from ..skills.skill import skill",
        "right": "from engine.skills.skill import skill",
        "convention": "absolute_import",
        "instruction": "Fix the import to use an absolute path.",
    },
    {
        "wrong": "from .base_scene import BaseScene",
        "right": "from engine.scenes.base_scene import BaseScene",
        "convention": "absolute_import",
        "instruction": "Fix the import to use an absolute path.",
    },
    {
        "wrong": 'print("Starting scene")',
        "right": 'logger.info("Starting scene")',
        "convention": "no_print",
        "instruction": "Replace print() with the correct logger call.",
    },
    {
        "wrong": 'print(f"Error: {e}")',
        "right": 'logger.error("Error: %s", e)',
        "convention": "no_print",
        "instruction": "Replace print() with the correct logger call.",
    },
    {
        "wrong": 'print("Debug:", value)',
        "right": 'logger.debug("Debug: %s", value)',
        "convention": "no_print",
        "instruction": "Replace print() with the correct logger call.",
    },
    {
        "wrong": 'print(f"Loaded {count} items")',
        "right": 'logger.info("Loaded %d items", count)',
        "convention": "no_print",
        "instruction": "Replace print() with the correct logger call.",
    },
    {
        "wrong": "def process(data):\n    return data",
        "right": "def process(data: dict) -> dict:\n    return data",
        "convention": "type_hints",
        "instruction": "Add type hints to the function signature.",
    },
    {
        "wrong": "def fetch(url, timeout=30):\n    pass",
        "right": "def fetch(url: str, timeout: int = 30) -> Optional[str]:\n    pass",
        "convention": "type_hints",
        "instruction": "Add type hints to the function signature.",
    },
    {
        "wrong": "def get_score(name, value):\n    return value",
        "right": "def get_score(name: str, value: float) -> float:\n    return value",
        "convention": "type_hints",
        "instruction": "Add type hints to the function signature.",
    },
    {
        "wrong": "port = 8080",
        "right": "port = get_config().get(\"server.port\", 8080)",
        "convention": "config_access",
        "instruction": "Replace hardcoded value with config access.",
    },
    {
        "wrong": 'host = "localhost"',
        "right": 'host = get_config().get("server.host", "localhost")',
        "convention": "config_access",
        "instruction": "Replace hardcoded value with config access.",
    },
    {
        "wrong": 'path = "/var/data/cosysim"',
        "right": 'path = Path(get_config().get("data.path", "data"))',
        "convention": "config_access",
        "instruction": "Replace hardcoded path with config access.",
    },
    {
        "wrong": "import logging\nprint = logging.info",
        "right": "import logging\nlogger = logging.getLogger(__name__)",
        "convention": "logger_setup",
        "instruction": "Set up logging correctly using getLogger(__name__).",
    },
    {
        "wrong": "logger = logging.getLogger('my_module')",
        "right": "logger = logging.getLogger(__name__)",
        "convention": "logger_setup",
        "instruction": "Use __name__ as the logger name.",
    },
    {
        "wrong": "def my_func(x):\n    # returns x * 2\n    return x * 2",
        "right": 'def my_func(x: int) -> int:\n    """Multiply x by 2.\n\n    Args:\n        x: Input value.\n\n    Returns:\n        x multiplied by 2.\n    """\n    return x * 2',
        "convention": "google_docstring",
        "instruction": "Add a Google-style docstring to the function.",
    },
    {
        "wrong": "def load_data(path):\n    \"\"\"Load data\"\"\"\n    pass",
        "right": 'def load_data(path: Path) -> List[Dict[str, Any]]:\n    """Load data from a JSONL file.\n\n    Args:\n        path: Path to the JSONL file.\n\n    Returns:\n        List of parsed records.\n\n    Raises:\n        FileNotFoundError: If path does not exist.\n    """\n    pass',
        "convention": "google_docstring",
        "instruction": "Expand the docstring to full Google style.",
    },
    {
        "wrong": "@skill(pack='custom', description='Do something')\ndef my_skill(x):\n    return x",
        "right": "@skill(\n    pack=\"custom\",\n    description=\"Do something useful\",\n    category=\"GAME\",\n)\ndef my_skill(x: str) -> str:\n    \"\"\"Do something useful.\n\n    Args:\n        x: Input string.\n\n    Returns:\n        Result string.\n    \"\"\"\n    return x",
        "convention": "skill_pattern",
        "instruction": "Fix the @skill decorator and function to follow CosySim conventions.",
    },
    {
        "wrong": "config = yaml.safe_load(open('config.yaml'))",
        "right": "from engine.config import get_config\ncfg = get_config()",
        "convention": "config_access",
        "instruction": "Replace direct YAML loading with CosySim config access.",
    },
]


def _generate_convention_variants() -> List[Dict[str, Any]]:
    """Generate variations of base convention pairs to reach 50+ examples."""
    variants: List[Dict[str, Any]] = []

    # Absolute import variants
    modules = [
        ("mcp", "engine.mcp"),
        ("config", "engine.config"),
        ("lmstudio.client", "engine.lmstudio.client"),
        ("skills.skill", "engine.skills.skill"),
        ("nexus.client", "engine.nexus.client"),
        ("scenes.base_scene", "engine.scenes.base_scene"),
    ]
    for short, full in modules:
        variants.append({
            "wrong": f"from .{short} import *",
            "right": f"from {full} import get_{short.split('.')[-1].replace('_', '')}",
            "convention": "absolute_import",
            "instruction": "Fix the relative import to an absolute import.",
        })

    # No print variants
    messages = [
        ("Initializing", "info"),
        ("Warning: {msg}", "warning"),
        ("Done processing", "info"),
        ("Failed: {err}", "error"),
        ("Connected to server", "info"),
        ("Disconnected", "warning"),
        ("Loaded model", "info"),
        ("Skipping {item}", "debug"),
    ]
    for msg, level in messages:
        if "{" in msg:
            clean = msg.replace("{msg}", "message").replace("{err}", "error").replace("{item}", "item")
            wrong = f'print(f"{msg}")'
            right = f'logger.{level}("{clean}")'
        else:
            wrong = f'print("{msg}")'
            right = f'logger.{level}("{msg}")'
        variants.append({
            "wrong": wrong,
            "right": right,
            "convention": "no_print",
            "instruction": "Replace print() with the correct logger call.",
        })

    # Type hint variants
    type_pairs = [
        ("name", "str"),
        ("count", "int"),
        ("score", "float"),
        ("items", "List[str]"),
        ("data", "Dict[str, Any]"),
        ("flag", "bool"),
        ("path", "Path"),
    ]
    for param, typ in type_pairs:
        variants.append({
            "wrong": f"def handle({param}):\n    pass",
            "right": f"def handle({param}: {typ}) -> None:\n    pass",
            "convention": "type_hints",
            "instruction": "Add type hints to the function signature.",
        })

    # MCP state pattern
    node_names = ["player_stats", "scene_state", "dialog_history", "quest_data", "faction_rep"]
    for node_name in node_names:
        variants.append({
            "wrong": f'state = dict()\nstate["{node_name}"] = value',
            "right": (
                "from engine.mcp import get_framework\n"
                "fw = get_framework()\n"
                f'node = fw.get_or_create("scenes.my_scene.{node_name}", dict)\n'
                'node["value"] = value'
            ),
            "convention": "mcp_state",
            "instruction": "Replace raw dict with MCP node state management.",
        })

    return variants


def generate_convention_examples() -> List[Dict[str, Any]]:
    """Generate CosySim convention training examples.

    Returns:
        List of convention training examples (50+).
    """
    all_pairs = list(_BASE_CONVENTION_PAIRS) + _generate_convention_variants()
    examples: List[Dict[str, Any]] = []
    for pair in all_pairs:
        wrong = pair["wrong"]
        right = pair["right"]
        convention = pair["convention"]
        instruction = pair["instruction"]
        examples.append(_make_example(
            instruction=instruction,
            input_text=wrong,
            output=right,
            strategy="convention",
            source_file="",
            convention_type=convention,
        ))
    return examples


# ──── Strategy 5: @skill scaffolding ─────────────────────────────────────────


def _find_skill_files() -> List[Path]:
    """Find all skill files in builtin and content/scenes."""
    files: List[Path] = []
    for pattern in [
        "engine/skills/builtin/*_skills.py",
        "content/scenes/**/*_skills.py",
    ]:
        for p in _CODEBASE_ROOT.glob(pattern):
            if any(excl in str(p) for excl in _EXCLUDE_PATTERNS):
                continue
            files.append(p)
    return files


def _extract_skills_from_file(path: Path) -> List[Dict[str, str]]:
    """Extract @skill decorated functions from a skill file.

    Args:
        path: Path to a skill Python file.

    Returns:
        List of dicts with name, pack, description, source keys.
    """
    skills: List[Dict[str, str]] = []
    try:
        source = path.read_text(encoding="utf-8")
        tree = ast.parse(source)
    except Exception:
        return skills
    lines = source.splitlines()
    for node in ast.walk(tree):
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        # Check for @skill decorator
        skill_decorator = None
        for dec in node.decorator_list:
            if isinstance(dec, ast.Call):
                func = dec.func
                name_str = ""
                if isinstance(func, ast.Name):
                    name_str = func.id
                elif isinstance(func, ast.Attribute):
                    name_str = func.attr
                if name_str == "skill":
                    skill_decorator = dec
                    break
        if skill_decorator is None:
            continue
        # Extract pack and description from keyword args
        pack = ""
        description = ""
        for kw in skill_decorator.keywords:
            if kw.arg == "pack" and isinstance(kw.value, ast.Constant):
                pack = str(kw.value.value)
            elif kw.arg == "description" and isinstance(kw.value, ast.Constant):
                description = str(kw.value.value)
        if not pack or not description:
            continue
        # Include decorator lines in source (start from first decorator line)
        dec_start = node.decorator_list[0].lineno - 1
        func_end = getattr(node, "end_lineno", node.lineno + 20)
        func_source = "\n".join(lines[dec_start:func_end])
        if len(func_source) > 3000:
            continue
        skills.append({
            "name": node.name,
            "pack": pack,
            "description": description,
            "source": func_source,
        })
    return skills


def generate_skill_scaffold_examples() -> List[Dict[str, Any]]:
    """Generate @skill scaffolding examples from existing skill files.

    Returns:
        List of skill-scaffold training examples.
    """
    examples: List[Dict[str, Any]] = []
    for path in _find_skill_files():
        skills = _extract_skills_from_file(path)
        for sk in skills:
            if len(sk["source"]) < 50:
                continue
            input_text = (
                f"Create a @skill named {sk['name']} that {sk['description']} "
                f"(pack='{sk['pack']}')"
            )
            examples.append(_make_example(
                instruction="Scaffold a @skill function following CosySim conventions.",
                input_text=input_text,
                output=sk["source"],
                strategy="skill_scaffold",
                source_file=str(path),
            ))
    return examples


# ──── Strategy 6: Git diff pairs ─────────────────────────────────────────────


def _run_git(*args: str) -> str:
    """Run a git command and return stdout."""
    result = subprocess.run(
        ["git"] + list(args),
        capture_output=True,
        text=True,
        cwd=str(_CODEBASE_ROOT),
        timeout=30,
    )
    return result.stdout


def _parse_diff_hunks(diff_text: str) -> List[Tuple[str, str]]:
    """Parse unified diff into (before, after) pairs.

    Args:
        diff_text: Raw unified diff output.

    Returns:
        List of (before_code, after_code) tuples.
    """
    pairs: List[Tuple[str, str]] = []
    hunk_lines: List[str] = []
    in_hunk = False

    for line in diff_text.splitlines():
        if line.startswith("@@"):
            if in_hunk and hunk_lines:
                pair = _extract_pair_from_hunk(hunk_lines)
                if pair:
                    pairs.append(pair)
            hunk_lines = []
            in_hunk = True
        elif line.startswith("diff ") or line.startswith("index ") or line.startswith("--- ") or line.startswith("+++ "):
            if in_hunk and hunk_lines:
                pair = _extract_pair_from_hunk(hunk_lines)
                if pair:
                    pairs.append(pair)
                hunk_lines = []
                in_hunk = False
        elif in_hunk:
            hunk_lines.append(line)

    if in_hunk and hunk_lines:
        pair = _extract_pair_from_hunk(hunk_lines)
        if pair:
            pairs.append(pair)

    return pairs


def _extract_pair_from_hunk(hunk_lines: List[str]) -> Optional[Tuple[str, str]]:
    """Extract before/after code pair from a hunk.

    Args:
        hunk_lines: Lines of a diff hunk.

    Returns:
        (before, after) tuple or None if invalid.
    """
    before_lines: List[str] = []
    after_lines: List[str] = []
    has_minus = False
    has_plus = False

    for line in hunk_lines:
        if line.startswith("-"):
            before_lines.append(line[1:])
            has_minus = True
        elif line.startswith("+"):
            after_lines.append(line[1:])
            has_plus = True
        else:
            ctx = line[1:] if line.startswith(" ") else line
            before_lines.append(ctx)
            after_lines.append(ctx)

    if not has_minus or not has_plus:
        return None
    total = len(before_lines) + len(after_lines)
    if total > 100:
        return None

    before = "\n".join(before_lines)
    after = "\n".join(after_lines)
    return before, after


def generate_git_diff_examples() -> List[Dict[str, Any]]:
    """Generate refactoring examples from git history.

    Returns:
        List of git-diff training examples (up to 200).
    """
    examples: List[Dict[str, Any]] = []
    try:
        log = _run_git("log", "--oneline", "-100")
        if not log:
            return examples
        commits = [line.split()[0] for line in log.strip().splitlines() if line.strip()]
    except Exception as e:
        logger.debug(f"git log failed: {e}")
        return examples

    for commit in commits:
        if len(examples) >= 200:
            break
        try:
            diff = _run_git("diff", f"{commit}^", commit, "--", "*.py")
            if not diff:
                continue
            pairs = _parse_diff_hunks(diff)
            for before, after in pairs:
                if len(before.strip()) < 10 or len(after.strip()) < 10:
                    continue
                examples.append(_make_example(
                    instruction="Refactor the Python code as shown.",
                    input_text=f"Refactor this Python code:\n{before}",
                    output=after,
                    strategy="git_diff",
                    source_file=f"git:{commit}",
                ))
        except Exception as e:
            logger.debug(f"git diff {commit} failed: {e}")
            continue

    return examples


# ──── Strategy 7: Test generation (bidirectional) ─────────────────────────────


def generate_test_gen_examples() -> List[Dict[str, Any]]:
    """Generate bidirectional test↔implementation examples.

    Returns:
        List of test-generation training examples.
    """
    examples: List[Dict[str, Any]] = []
    tests_dir = _CODEBASE_ROOT / "tests"
    if not tests_dir.exists():
        return examples

    for test_file in tests_dir.glob("test_*.py"):
        try:
            test_source = test_file.read_text(encoding="utf-8")
            test_tree = ast.parse(test_source)
        except Exception:
            continue
        test_lines = test_source.splitlines()

        # Find corresponding impl file
        impl_name = test_file.stem[5:]  # strip "test_"
        impl_candidates = list(_CODEBASE_ROOT.rglob(f"{impl_name}.py"))
        impl_candidates = [p for p in impl_candidates if "test" not in str(p).lower() and
                          not any(excl in str(p) for excl in _EXCLUDE_PATTERNS)]

        impl_tree = None
        impl_lines: List[str] = []
        impl_path: Optional[Path] = None
        for cand in impl_candidates:
            try:
                src = cand.read_text(encoding="utf-8")
                impl_tree = ast.parse(src)
                impl_lines = src.splitlines()
                impl_path = cand
                break
            except Exception:
                continue

        for node in ast.walk(test_tree):
            if not isinstance(node, ast.FunctionDef):
                continue
            if not node.name.startswith("test_"):
                continue
            test_func_source = _get_func_source(test_lines, node)
            if len(test_func_source) > 2000 or len(test_func_source) < 50:
                continue
            impl_name_bare = node.name[5:]  # strip "test_"

            # Try to find impl function
            impl_source: Optional[str] = None
            if impl_tree and impl_lines:
                for impl_node in ast.walk(impl_tree):
                    if isinstance(impl_node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                        if impl_node.name == impl_name_bare:
                            impl_source = _get_func_source(impl_lines, impl_node)
                            break

            if impl_source and len(impl_source) >= 50 and len(impl_source) <= 2000:
                # Forward: impl → test
                examples.append(_make_example(
                    instruction="Generate the requested Python code.",
                    input_text=f"Write a pytest test for this function:\n{impl_source}",
                    output=test_func_source,
                    strategy="test_gen",
                    source_file=str(test_file),
                ))
                # Reverse: test → impl
                examples.append(_make_example(
                    instruction="Generate the requested Python code.",
                    input_text=f"Implement the function that passes this test:\n{test_func_source}",
                    output=impl_source,
                    strategy="test_gen",
                    source_file=str(impl_path) if impl_path else "",
                ))

    return examples


# ──── Strategy 8: Class method completion ────────────────────────────────────


def generate_class_method_examples() -> List[Dict[str, Any]]:
    """Generate class method completion examples from class definitions.

    Returns:
        List of class-method training examples.
    """
    examples: List[Dict[str, Any]] = []
    for path in _get_python_files(max_files=150):
        try:
            source = path.read_text(encoding="utf-8")
            tree = ast.parse(source)
        except Exception:
            continue
        lines = source.splitlines()
        for node in ast.walk(tree):
            if not isinstance(node, ast.ClassDef):
                continue
            methods = [
                n for n in ast.walk(node)
                if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))
                and n.name not in ("__init__", "__repr__", "__str__")
            ]
            if not methods:
                continue
            # Build class skeleton
            class_start = node.lineno - 1
            class_end = getattr(node, "end_lineno", class_start + 5)
            # Get class header line(s)
            class_header = lines[class_start:class_start + 2]

            # Find __init__ if present
            init_source = ""
            for m in ast.walk(node):
                if isinstance(m, (ast.FunctionDef, ast.AsyncFunctionDef)) and m.name == "__init__":
                    init_source = _get_func_source(lines, m)
                    break

            for method in methods[:5]:  # limit per class
                method_source = _get_func_source(lines, method)
                if len(method_source) < 30 or len(method_source) > 2000:
                    continue
                # Build skeleton
                skeleton_parts = ["\n".join(class_header)]
                if init_source:
                    skeleton_parts.append(textwrap.indent(init_source, "    "))
                # Add stub for the target method
                stub_line = f"    def {method.name}(self):  # ... implement this"
                skeleton_parts.append(stub_line)
                class_skeleton = "\n\n".join(skeleton_parts)
                examples.append(_make_example(
                    instruction="Complete the class method following CosySim conventions.",
                    input_text=(
                        f"Add method {method.name} to class {node.name}:\n"
                        f"{class_skeleton}"
                    ),
                    output=method_source,
                    strategy="class_method",
                    source_file=str(path),
                ))
    return examples


# ──── Strategy 9: Multi-file context ─────────────────────────────────────────


def generate_multi_file_examples() -> List[Dict[str, Any]]:
    """Generate multi-file context examples from scene skill files.

    Returns:
        List of multi-file-context training examples.
    """
    examples: List[Dict[str, Any]] = []
    scenes_dir = _CODEBASE_ROOT / "content" / "scenes"
    if not scenes_dir.exists():
        return examples

    for skill_file in scenes_dir.rglob("*_skills.py"):
        if any(excl in str(skill_file) for excl in _EXCLUDE_PATTERNS):
            continue
        skills = _extract_skills_from_file(skill_file)
        if not skills:
            continue
        scene_name = skill_file.parent.name
        skill_names = [sk["name"] for sk in skills]
        for sk in skills:
            if len(sk["source"]) < 50:
                continue
            input_text = (
                f"# File: {skill_file.name}\n"
                f"# Scene: {scene_name}\n"
                f"# Existing skills: {', '.join(n for n in skill_names if n != sk['name'])}\n"
                f"# Task: Add a skill that {sk['description']}"
            )
            examples.append(_make_example(
                instruction="Add a @skill function to the scene skill file.",
                input_text=input_text,
                output=sk["source"],
                strategy="multi_file_context",
                source_file=str(skill_file),
            ))
    return examples


# ──── Strategy 10: Nexus Q&A extraction ──────────────────────────────────────


def generate_nexus_qa_examples() -> List[Dict[str, Any]]:
    """Extract code-related Q&A from Nexus for training.

    Returns:
        List of nexus-QA training examples, empty list on failure.
    """
    examples: List[Dict[str, Any]] = []
    try:
        from engine.nexus.client import get_nexus_client
        client = get_nexus_client()
    except Exception as e:
        logger.debug(f"Nexus unavailable: {e}")
        return examples

    for category in ("api", "debugging", "architecture", "testing"):
        try:
            results = client.search(f"python code {category}", limit=100)
            for entry in results:
                content = entry.get("content", "")
                title = entry.get("title", "")
                if not content or len(content) < 50:
                    continue
                if not any(kw in content for kw in ["def ", "class ", "import ", "```python", "return "]):
                    continue
                input_text = title if title else f"CosySim {category} code question"
                examples.append(_make_example(
                    instruction="Answer the coding question.",
                    input_text=input_text,
                    output=content,
                    strategy="nexus_qa",
                    source_file="nexus",
                ))
        except Exception as e:
            logger.debug(f"Nexus search for {category} failed: {e}")

    return examples


# ──── Legacy compatibility: scan_codebase ────────────────────────────────────


def scan_codebase(max_files: int = 200) -> List[Dict[str, Any]]:
    """Scan CosySim Python files to extract docstring + function examples.

    Args:
        max_files: Maximum number of files to scan.

    Returns:
        List of example dicts with input (docstring/context) and output (code).
    """
    examples: List[Dict[str, Any]] = []
    scanned = 0
    for path in _get_python_files(max_files=max_files):
        try:
            source = path.read_text(encoding="utf-8")
            tree = ast.parse(source)
        except Exception:
            continue
        lines = source.splitlines()
        for node in ast.walk(tree):
            if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            docstring = ast.get_docstring(node)
            if not docstring or len(docstring) < 20:
                continue
            func_source = _get_func_source(lines, node)
            if len(func_source) > 2000 or len(func_source) < 30:
                continue
            func_lines = func_source.splitlines()
            sig_line = func_lines[0] if func_lines else ""
            module_name = path.stem
            input_text = (
                f"# Module: {module_name}\n"
                f"# Task: {docstring.split(chr(10))[0]}\n"
                f"{sig_line}"
            )
            examples.append({"input": input_text, "output": func_source, "source_file": str(path)})
        scanned += 1

    logger.info(f"Scanned {scanned} files, extracted {len(examples)} code examples")
    return examples


# ──── Quality filter + dedup ──────────────────────────────────────────────────

_SKIP_OUTPUTS = {"pass", "...", "raise NotImplementedError"}


def _filter_and_dedup(examples: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Apply quality filters and deduplicate examples.

    Args:
        examples: Raw list of training examples.

    Returns:
        Filtered and deduplicated examples.
    """
    seen: set = set()
    filtered: List[Dict[str, Any]] = []
    for ex in examples:
        output = ex.get("output", "")
        inp = ex.get("input", "")
        instruction = ex.get("instruction", "")
        # Length filters
        if len(output) < 50 or len(output) > 3000:
            continue
        # Skip trivial outputs
        if output.strip() in _SKIP_OUTPUTS:
            continue
        if output.strip().startswith("raise NotImplementedError"):
            continue
        # Dedup key
        key = instruction[:50] + inp[:100]
        if key in seen:
            continue
        seen.add(key)
        filtered.append(ex)
    return filtered


# ──── Save dataset ────────────────────────────────────────────────────────────


def save_dataset(examples: List[Dict[str, Any]], output_path: Optional[Path] = None) -> Path:
    """Save coder examples to JSONL in Alpaca format.

    Args:
        examples: List of example dicts.
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
                "instruction": ex.get("instruction", "Complete or generate the requested code following CosySim conventions."),
                "input": ex.get("input", ""),
                "output": ex.get("output", ""),
                "model_type": ex.get("model_type", "coder"),
                "strategy": ex.get("strategy", "docstring_to_impl"),
                "source_file": ex.get("source_file", ""),
                "convention_type": ex.get("convention_type"),
            }
            f.write(json.dumps(record) + "\n")

    logger.info(f"Saved {len(examples)} coder examples to {out}")
    return out


# ──── Main ────────────────────────────────────────────────────────────────────


def main() -> None:
    """Generate and save the coder training dataset."""
    logging.basicConfig(level=logging.INFO)
    all_examples: List[Dict[str, Any]] = []
    counts: Dict[str, int] = {}

    strategies = [
        ("fim_completion", generate_fim_examples),
        ("docstring_to_impl", generate_docstring_examples),
        ("bug_fix", generate_bug_fix_examples),
        ("convention", generate_convention_examples),
        ("skill_scaffold", generate_skill_scaffold_examples),
        ("git_diff", generate_git_diff_examples),
        ("test_gen", generate_test_gen_examples),
        ("class_method", generate_class_method_examples),
        ("multi_file_context", generate_multi_file_examples),
        ("nexus_qa", generate_nexus_qa_examples),
    ]

    for name, func in strategies:
        try:
            examples = func()
            counts[name] = len(examples)
            all_examples.extend(examples)
            logger.info(f"Strategy {name}: {len(examples)} examples")
        except Exception as e:
            logger.warning(f"Strategy {name} failed: {e}")
            counts[name] = 0

    # Quality filter + dedup
    filtered = _filter_and_dedup(all_examples)

    path = save_dataset(filtered)
    logger.info(f"Total: {len(filtered)} examples → {path}")
    for name, count in counts.items():
        print(f"  {name}: {count}")
    print(f"  TOTAL (after dedup): {len(filtered)}")


if __name__ == "__main__":
    main()
