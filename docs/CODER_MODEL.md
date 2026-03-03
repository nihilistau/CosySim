# CosySim Coder Model

> Local code generation model — v0.78b "THE DATA FLYWHEEL".
> Llama 3.2-3B fine-tuned with LoRA on CosySim's own codebase and runtime code events.
> Handles 8 code skills via the `coder` skill pack.

---

## Overview

CosySim trains a **local coder model** — a Llama 3.2-3B-Instruct base with a 16-rank
LoRA adapter — entirely on data generated from its own codebase and runtime activity.
The model powers 8 dedicated `@skill` functions in `engine/skills/builtin/coder_skills.py`
and improves automatically as those skills are used.

**Key properties:**
- Runs fully offline — no external API calls for code tasks
- Fine-tuned on CosySim's own Python, the only codebase it needs to know
- Collects new training samples from every `coder_complete`, `coder_fix`, and
  `coder_generate` invocation
- Promoted automatically when benchmark score exceeds the previous active model

---

## Data Pipeline (`training/coder_pipeline.py`)

`CoderPipeline` implements 10 collection strategies that together produce the
`code_train.jsonl` dataset. Strategies are mixed at collection time; each sample
records the strategy source, language, and a quality score.

### Strategy 1 — CosySim Codebase (AST parsing)

Walks `engine/`, `training/`, `tools/`, and `scripts/` with Python's `ast` module.
Extracts every function that has a docstring: the docstring becomes the instruction,
the function body becomes the target completion.

```python
# Extracted sample (Alpaca format)
{
  "instruction": "Implement: score(prompt, response) -> float\n\nScore a response on a 0.0–1.0 scale across five dimensions.",
  "input": "",
  "output": "def score(self, prompt: str, response: str) -> float:\n    ..."
}
```

Yields **hundreds of samples** on first run; re-runs incrementally (only changed files).

---

### Strategy 2 — Nexus Q&A Cache (code answers)

Queries Nexus for entries where `category=code` or where the answer body contains a
fenced code block. Converts question → answer pairs into instruction-completion samples.

```python
{
  "instruction": "How do I register a new @skill in a scene?",
  "input": "",
  "output": "from engine.skills import skill\n\n@skill(pack='myscene')\ndef my_skill(arg: str) -> str:\n    ..."
}
```

---

### Strategy 3 — `coder_complete` Runtime Calls

Every call to `coder_complete(partial_code, context)` that returns a non-empty result
is collected as a `{prompt → completion}` pair via `DataCollector.collect_code()`.

```python
{
  "instruction": "Complete the following Python code snippet.",
  "input": "def calculate_score(results: list[float]) ->\n    # return weighted mean",
  "output": "    weights = [0.5, 0.3, 0.2]\n    return sum(r * w for r, w in zip(results, weights))"
}
```

---

### Strategy 4 — `coder_fix` Runtime Calls

Every `coder_fix(code, error_msg)` call produces a `{buggy → fixed}` training pair.
The error message is included in the instruction.

```python
{
  "instruction": "Fix the following Python code.\nError: TypeError: unsupported operand type(s) for +: 'int' and 'str'",
  "input": "total = count + \" items\"",
  "output": "total = str(count) + \" items\""
}
```

---

### Strategy 5 — `coder_generate` Runtime Calls

Every `coder_generate(spec, language)` call is collected as a `{spec → code}` pair.

```python
{
  "instruction": "Generate Python code from the following specification.",
  "input": "A function that takes a list of ModelSpec objects and returns only those above a training threshold.",
  "output": "def filter_ready(zoo: dict, counts: dict) -> list[str]:\n    return [k for k, spec in zoo.items() if counts.get(k, 0) >= spec.train_threshold]"
}
```

---

### Strategy 6 — Docstring → Implementation Extraction

A second AST pass targets functions where the implementation is non-trivial (>= 5
lines). Pairs the stripped function signature + docstring against the full body,
including internal comments as inline supervision signal.

---

### Strategy 7 — Test → Implementation Pairs

Scans `tests/` for test functions that test a corresponding implementation file.
Pairs the test body (what the function should do) against the implementation it tests.
Produces high-quality behaviour-grounded training samples.

---

### Strategy 8 — Refactoring Examples

Scans git history for commits with "refactor" in the message. Pairs the before-commit
version of a function against the after-commit version, with the commit message as
the instruction.

```python
{
  "instruction": "Refactor: extract validation logic into a separate helper function",
  "input": "# before\ndef process(data):\n    if not isinstance(data, dict): raise ...\n    ...",
  "output": "# after\ndef _validate(data): ...\ndef process(data):\n    _validate(data)\n    ..."
}
```

---

### Strategy 9 — Config Patterns

Parses `config/` YAML files and generates instruction pairs for common config
manipulation tasks (reading a key, updating a nested value, validating a schema).
Useful for grounding the model in CosySim's own config vocabulary.

---

### Strategy 10 — Import / API Usage Patterns

Scans all source files for import statements and common API call patterns. Generates
"how do I use X" instruction samples where the answer is the correct import + usage
example, extracted directly from the codebase.

---

## Skill Pack — `coder` (`engine/skills/builtin/coder_skills.py`)

Eight `@skill` functions registered under the `coder` pack. All skills call the
promoted coder model via `InferenceOrchestrator` and auto-collect training samples
on each invocation.

```python
from engine.skills import skill

@skill(pack="coder")
def coder_complete(partial_code: str, context: str = "") -> str:
    ...

@skill(pack="coder")
def coder_fix(code: str, error_msg: str) -> str:
    ...
```

### Skill Reference

| Skill | Arguments | Returns | Description |
|-------|-----------|---------|-------------|
| `coder_complete` | `partial_code: str`, `context: str` | `str` — completed code | Fill in missing code given partial input and optional context |
| `coder_fix` | `code: str`, `error_msg: str` | `str` — corrected code | Fix a bug given the code and the error message |
| `coder_generate` | `spec: str`, `language: str` | `str` — generated code | Generate a function or module from a natural-language specification |
| `coder_review` | `code: str` | `str` — review text | Identify bugs, style issues, and improvements |
| `coder_docstring` | `code: str` | `str` — docstring | Generate a Google-style docstring for a function or class |
| `coder_test` | `code: str` | `str` — test code | Generate a pytest test suite for the provided code |
| `coder_refactor` | `code: str`, `goal: str` | `str` — refactored code | Refactor with a specific goal (e.g., "reduce duplication") |
| `coder_explain` | `code: str` | `str` — explanation | Plain-English explanation of what the code does |

### Calling a Coder Skill

From any scene or agent:

```python
from engine.skills.builtin.coder_skills import coder_complete, coder_fix, coder_generate

# Complete a partial function
result = coder_complete(
    partial_code="def merge_datasets(a: list, b: list) ->",
    context="Both lists contain JSONL dicts with 'instruction' and 'output' keys.",
)

# Fix a bug
fixed = coder_fix(
    code="return total / count",
    error_msg="ZeroDivisionError: division by zero",
)

# Generate from spec
generated = coder_generate(
    spec="A context manager that times a code block and logs elapsed ms.",
    language="python",
)
```

### Data Collection in Skills

`coder_complete`, `coder_fix`, and `coder_generate` automatically collect samples:

```python
# Inside coder_complete — happens automatically
from training.data_collector import get_data_collector

dc = get_data_collector()
dc.collect_code(
    prompt=partial_code,
    completion=result,
    skill="coder_complete",
    language="python",
    quality=quality_score,
)
```

`coder_review`, `coder_docstring`, `coder_test`, `coder_refactor`, and `coder_explain`
do not auto-collect (output format varies too much for unsupervised quality scoring).

---

## Training Configuration

| Parameter | Value |
|-----------|-------|
| Base model | `meta-llama/Llama-3.2-3B-Instruct` |
| LoRA rank (`r`) | `16` |
| LoRA alpha | `32` |
| Epochs | `2` |
| Learning rate | `2e-4` |
| Batch size | `4` |
| Max sequence length | `2048` |
| Training threshold | `500` examples |
| Dataset path | `training/datasets/code_train.jsonl` |
| Adapter output | `training/models/coder_{job_id}/adapter/` |
| Merged output | `training/models/coder_{job_id}/merged/` |

**ModelSpec entry (`training/model_zoo.py`):**

```python
"coder": ModelSpec(
    id="coder",
    label="Local Coder",
    base_model="meta-llama/Llama-3.2-3B-Instruct",
    lora_r=16,
    epochs=2,
    train_threshold=500,
)
```

---

## Training Flow

```
Step 1: Dataset accumulates
        ├─ AST scan of CosySim codebase (seed)
        ├─ Nexus code Q&A (seed)
        ├─ Runtime skill calls (ongoing)
        └─ code_train.jsonl grows toward 500-sample threshold

Step 2: model-zoo-train scheduler task (daily)
        auto_train.check_and_train_all_zoo()
        └─ coder count >= 500 → submit job to FinetuneOrchestrator

Step 3: QLoRA fine-tuning (Unsloth, 2 epochs)
        ├─ LoRA adapter: training/models/coder_{job_id}/adapter/
        └─ Merged 16-bit model: training/models/coder_{job_id}/merged/

Step 4: BenchmarkRunner evaluation
        Metrics: pass@1, BLEU score, perplexity
        Aggregate: 0.5×pass@1 + 0.3×BLEU + 0.2×(1−perplexity_norm)
        └─ If aggregate_score > 0.65 AND > current active → promote

Step 5: ModelRegistry.promote("coder", model_id)
        └─ InferenceOrchestrator hot-reloads → coder skills use new model
```

---

## Promotion

`BenchmarkRunner` evaluates the coder model against a held-out code test split using
three metrics:

| Metric | Weight | Description |
|--------|--------|-------------|
| `pass@1` | 0.5 | Does the generated code run without error on the test case? |
| `BLEU` | 0.3 | Token overlap between generated and reference output |
| `perplexity` | 0.2 | Model confidence (lower is better; normalised to 0–1) |

**Promotion threshold:** `aggregate_score > 0.65`

If the new model meets the threshold and beats the current active model's score, it
is promoted automatically:

```python
from training.model_registry import get_model_registry
from training.benchmark_runner import get_benchmark_runner

runner = get_benchmark_runner()
result = runner.run("coder", auto_promote=True)

print(result.aggregate_score)   # 0.71
print(result.promoted)          # True — beat previous 0.68
```

On promotion, `InferenceOrchestrator` detects the registry change and reloads the
coder model. All subsequent coder skill calls use the improved model.

---

## Manual Operations

### Trigger fine-tuning via admin API

```bash
curl -X POST http://localhost:5555/api/admin/training/trigger/coder
```

Response:
```json
{"status": "submitted", "job_id": "coder-a3f9d1", "dataset_count": 612}
```

### Trigger via CLI

```bash
# Trigger coder training directly
python -m training.auto_train trigger coder

# Run full pipeline: flush → sweep → benchmark
python -m training.data_collector flush code
python -m training.auto_train trigger coder
python -m training.benchmark_runner run coder --auto-promote
```

### Seed the dataset from the codebase

Run all 10 collection strategies from scratch:

```bash
python -m training.coder_pipeline seed
```

This walks the entire codebase and Nexus Q&A cache, populating
`training/datasets/code_train.jsonl` with the initial seed corpus.

### Check status

```bash
python -m training.auto_train status
# coder: 612 / 500 samples — READY (last trained: 2026-06-01T02:00:00Z)
```

---

## Dataset Format

All coder samples use the **Alpaca instruction format**:

```json
{"instruction": "Complete the following Python code snippet.", "input": "def score(results: list) ->", "output": "    return sum(results) / len(results) if results else 0.0", "source": "coder_complete", "language": "python", "quality": 0.82}
{"instruction": "Fix the following Python code.\nError: KeyError: 'model'", "input": "return config['model']", "output": "return config.get('model', 'default')", "source": "coder_fix", "language": "python", "quality": 0.91}
```

Each sample includes `source` (which strategy produced it) and `quality` (0.0–1.0)
for use by `DataCollector.prune_low_quality()`.

---

## Config Keys

| Key | Default | Description |
|-----|---------|-------------|
| `training.coder.enabled` | `true` | Enable coder skill data collection |
| `training.coder.min_quality` | `0.5` | Discard samples below this score |
| `training.coder.seed_on_startup` | `false` | Run AST seed scan at startup |
| `training.coder.promotion_threshold` | `0.65` | Minimum benchmark score to promote |
| `training.coder.collect_completions` | `true` | Collect `coder_complete` results |
| `training.coder.collect_fixes` | `true` | Collect `coder_fix` results |
| `training.coder.collect_generate` | `true` | Collect `coder_generate` results |

---

*See [TRAINING_SYSTEM.md](./TRAINING_SYSTEM.md) for the full DataCollector → model zoo → auto-train architecture.*  
*See [FINETUNING_GUIDE.md](./FINETUNING_GUIDE.md) for FinetuneOrchestrator, BenchmarkRunner, and ModelRegistry internals.*  
*See [SKILLS.md](./SKILLS.md) for the `@skill` decorator and how to register new skill packs.*  
*See [ADMIN_GUIDE.md](./ADMIN_GUIDE.md) for the admin overlay TRAINING tab.*
