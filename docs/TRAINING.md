# CosySim Training Pipeline

> CosySim Documentation — v1.51.1 [2026-03-25]
>
> End-to-end self-improving training pipeline — data collection, fine-tuning, evaluation, and promotion.
> Every runtime interaction feeds the DataCollector, accumulates into typed datasets, triggers
> threshold-gated QLoRA fine-tuning, and promotes models that beat the current benchmark.

---

## Overview

CosySim runs a **Data Flywheel** — a fully autonomous training pipeline that collects
signal from every runtime event, accumulates it into typed datasets, and continuously
fine-tunes a fleet of local models without manual intervention.

**More runtime interactions -> richer datasets -> better models -> better runtime behaviour -> more interactions.**

```
Runtime Events
      |
      v
+---------------------+      every_4h       +---------------------+
|   DataCollector      |  --------------->   |  Dataset Merge       |
|   (JSONL appender)   |                    |  live -> train.jsonl  |
+---------------------+                    +----------+-----------+
                                                       |  daily
                                                       v
                                           +---------------------+
                                           |  model-zoo-train     |
                                           |  (threshold check)   |
                                           +----------+-----------+
                                                       |  if >= threshold
                                                       v
                                           +---------------------+
                                           | FinetuneOrchestrator |
                                           | (QLoRA / Unsloth)    |
                                           +----------+-----------+
                                                       |
                                                       v
                                           +---------------------+
                                           |   BenchmarkRunner    |
                                           |   (score > previous) |
                                           +----------+-----------+
                                                       |  if promoted
                                                       v
                                           +---------------------+
                                           |   ModelRegistry      |<-- LMStudio loads
                                           |   (active model)     |    promoted model
                                           +---------------------+
```

---

## 1. Data Collection

### DataCollector (`training/data_collector.py`)

Thread-safe JSONL appender. All runtime components write to the DataCollector; it
maintains per-type live files and exposes stats and pruning utilities.

**Key methods:**

| Method | Signature | Description |
|--------|-----------|-------------|
| `collect_conversation` | `(messages, model, quality)` | Log a completed VirtualAgent exchange |
| `collect_code` | `(prompt, completion, skill, language)` | Log a coder skill call result |
| `collect_grammar_error` | `(text, violation, fix, severity)` | Log a grammar scanner violation |
| `collect_output_rating` | `(prompt, response, score, reason)` | Log an output evaluator rating |
| `stats` | `() -> dict` | Per-type counts, file sizes, last-write timestamps |
| `flush` | `(data_type)` | Merge one live file into its training dataset |
| `flush_all` | `()` | Merge all live files into training datasets |
| `get_stats` | `() -> DataStats` | Structured stats dataclass |
| `prune_low_quality` | `(data_type, min_score)` | Drop samples below quality threshold |

**Live file locations:**

```
training/datasets/collected/
+-- conversation_live.jsonl
+-- code_live.jsonl
+-- grammar_error_live.jsonl
+-- output_rating_live.jsonl
```

**Merged training datasets (after flush):**

```
training/datasets/
+-- conversation_train.jsonl
+-- code_train.jsonl
+-- grammar_error_train.jsonl
+-- output_rating_train.jsonl
```

```python
from training.data_collector import get_data_collector

dc = get_data_collector()

# Log a conversation (called automatically by VirtualAgent)
dc.collect_conversation(
    messages=[{"role": "user", "content": "..."}, {"role": "assistant", "content": "..."}],
    model="llama-3.2-3b",
    quality=0.87,
)

# Check stats
stats = dc.get_stats()
print(stats.conversation_count)   # 1,240
print(stats.code_count)           # 387

# Prune low-quality samples
dc.prune_low_quality("code", min_score=0.5)

# Flush live data into training datasets
dc.flush_all()
```

### Data Sources

**VirtualAgent conversations** -- every completed exchange across all active scenes is
collected automatically. High-traffic scenes (penthouse, phone, lounge) generate hundreds
of samples per session.

**Coder skills** -- `coder_complete`, `coder_fix`, and `coder_generate` each write a
training sample on every invocation via `DataCollector.collect_code()`.

**Grammar scanner** -- post-call interceptor (`GrammarScannerInterceptor`, priority
`POST_CALL_50`) runs 6 grammar checks on every LLM response: `subject_verb_agreement`,
`tense_consistency`, `article_usage`, `double_negation`, `run_on_sentence`,
`comma_splice`. Violations are collected with the original text, violation type,
corrected form, and severity (0.0--1.0).

**Output evaluator** -- scores every LLM response on a 0.0--1.0 scale across five
dimensions (fluency, relevance, detail, tone consistency, character adherence). Responses
scoring below 0.6 are collected as `output_rating` samples and posted to Nexus under
`category=improvement`.

**Human ratings** -- admin thumbs up/down from the admin overlay translates to quality
scores (1.0 / 0.0) and is collected as `output_rating` samples.

### MicroDatasetManager (`training/micro_datasets.py`)

Uses a **TeacherPipeline** (Gemini 3.0 via NLM) to generate synthetic training examples
at scale for micro-models.

```python
from training.micro_datasets import MicroDatasetManager

mgr = MicroDatasetManager()

# Build a single dataset
result = mgr.build("qa_evaluator", count=1000)

# Build all datasets
results = mgr.build_all(count_per_model=500)
```

Supported model types: `qa_evaluator`, `conversation_analyzer`, `syntax_fixer`,
`router_v2`, `router_v3`, `knowledge_synthesizer`.

### RouterDataCollector

Captures real inference traffic for use as training data:

```python
from training.data_manager import get_data_manager

mgr = get_data_manager()
mgr.seed_datasets()          # generate synthetic seed data
mgr.prepare_for_training()   # combine live + synthetic, deduplicate
status = mgr.get_pipeline_status()
```

---

## 2. Datasets

### Dataset Format

**Micro-model datasets** use a simple input/output JSONL format:

```json
{"input": "Attack the guard with my sword.", "output": "game_action"}
{"input": "How does she feel about what I did?", "output": "character_emotion"}
```

**Coder datasets** use the Alpaca instruction format:

```json
{"instruction": "Complete the following Python code snippet.", "input": "def score(results: list) ->", "output": "    return sum(results) / len(results) if results else 0.0", "source": "coder_complete", "language": "python", "quality": 0.82}
{"instruction": "Fix the following Python code.\nError: KeyError: 'model'", "input": "return config['model']", "output": "return config.get('model', 'default')", "source": "coder_fix", "language": "python", "quality": 0.91}
```

Each coder sample includes `source` (which strategy produced it) and `quality` (0.0--1.0)
for use by `DataCollector.prune_low_quality()`.

### Router v3 Dataset -- 16-Class Taxonomy

The most comprehensive intent classifier. 2,080 examples split 90/10 train/val plus 100
held-out test.

| Class | Description |
|-------|-------------|
| `small_talk` | Casual conversation, greetings |
| `game_action` | Combat, items, crafting, skills |
| `story_narrative` | Story progression, lore, quest dialogue |
| `character_emotion` | Character feelings, reactions, relationships |
| `world_query` | Questions about world, lore, factions |
| `skill_call` | Direct tool/skill invocation by agent |
| `memory_recall` | Remembering past events or conversations |
| `scene_transition` | Moving between scenes or locations |
| `system_command` | Admin/system commands, config queries |
| `creative_generation` | Writing, poetry, descriptions, art direction |
| `information_lookup` | Factual queries, knowledge search |
| `emotional_support` | Empathy, comfort, mental health conversations |
| `adult_content` | Mature themes -- violence, romance, dark themes |
| `combat_narrative` | Combat narration, battle descriptions |
| `economic_action` | Trading, buying, selling, economy actions |
| `investigation` | Clues, mysteries, detective work |

Regenerate with: `python training/datasets/generate_router_v3.py`

### Coder Dataset -- 10 Collection Strategies

`CoderPipeline` (`training/coder_pipeline.py`) implements 10 strategies that together
produce `code_train.jsonl`:

| # | Strategy | Source |
|---|----------|--------|
| 1 | CosySim codebase AST parsing | Docstring -> function body pairs from `engine/`, `training/`, `tools/`, `scripts/` |
| 2 | Nexus Q&A cache | Code-category entries and fenced code block answers |
| 3 | `coder_complete` runtime calls | Partial code -> completion pairs |
| 4 | `coder_fix` runtime calls | Buggy code + error -> fixed code pairs |
| 5 | `coder_generate` runtime calls | Spec -> generated code pairs |
| 6 | Docstring -> implementation extraction | Non-trivial functions (>= 5 lines) with inline comments |
| 7 | Test -> implementation pairs | Test body paired against the implementation it tests |
| 8 | Refactoring examples | Git history "refactor" commits: before/after function versions |
| 9 | Config patterns | YAML config manipulation tasks (read, update, validate) |
| 10 | Import / API usage patterns | Import + usage examples extracted from the codebase |

Seed from scratch: `python -m training.coder_pipeline seed`

---

## 3. Model Zoo (`training/model_zoo.py`)

Registry of all trainable model types. Each `ModelSpec` declares the base model, LoRA
configuration, training schedule, and promotion threshold.

### Base Model Aliases

| Alias | HuggingFace ID |
|-------|---------------|
| `qwen-270m` | `Qwen/Qwen2.5-0.5B-Instruct` |
| `qwen-1.7b` | `Qwen/Qwen2.5-1.5B-Instruct` |
| `llama-3b` | `meta-llama/Llama-3.2-3B-Instruct` |
| `qwen-7b` | `Qwen/Qwen2.5-7B-Instruct` |

### 9 Zoo Entries

| ID | Label | Base Model | LoRA r | Epochs | Threshold |
|----|-------|-----------|--------|--------|-----------|
| `coder` | Local Coder | `meta-llama/Llama-3.2-3B-Instruct` | 16 | 2 | 500 |
| `tool_dispatch` | Tool Dispatcher | `Qwen/Qwen2.5-0.5B-Instruct` | 8 | 3 | 300 |
| `conversational` | Conversational | `Qwen/Qwen2.5-1.5B-Instruct` | 8 | 2 | 1000 |
| `grammar_scanner` | Grammar Scanner | `Qwen/Qwen2.5-0.5B-Instruct` | 4 | 3 | 200 |
| `output_evaluator` | Output Evaluator | `Qwen/Qwen2.5-0.5B-Instruct` | 4 | 3 | 200 |
| `router` | Request Router | `Qwen/Qwen2.5-0.5B-Instruct` | 8 | 3 | 400 |
| `voice_encoder` | Voice Encoder | `Qwen/Qwen2.5-0.5B-Instruct` | 4 | 2 | 150 |
| `voice_decoder` | Voice Decoder | `Qwen/Qwen2.5-0.5B-Instruct` | 4 | 2 | 150 |
| `speculative` | Speculative Drafter | `Qwen/Qwen2.5-0.5B-Instruct` | 8 | 2 | 600 |

### Additional Micro-Model Fleet

| Model Type | Task | Recommended Base | Dataset |
|------------|------|-----------------|---------|
| `qa_evaluator` | Score Q&A pair quality (0--1) | Qwen2.5-0.5B-Instruct | `qa_evaluator_train.jsonl` |
| `conversation_analyzer` | Classify conversation quality | Qwen2.5-0.5B-Instruct | `conversation_analyzer_train.jsonl` |
| `syntax_fixer` | Fix malformed JSON/YAML/code | Qwen2.5-1.5B-Instruct | `syntax_fixer_train.jsonl` |
| `router_v2` | 8-class intent classification | Qwen2.5-0.5B-Instruct | `router_v2_train.jsonl` |
| `router_v3` | 16-class intent classification | Qwen2.5-0.5B-Instruct | `router_v3_train.jsonl` |
| `knowledge_synthesizer` | Synthesise knowledge from context | Qwen2.5-1.5B-Instruct | `knowledge_synthesizer_train.jsonl` |

```python
from training.model_zoo import MODEL_ZOO, ModelSpec

spec = MODEL_ZOO["coder"]
print(spec.base_model)        # meta-llama/Llama-3.2-3B-Instruct
print(spec.train_threshold)   # 500
```

---

## 4. Fine-Tuning

### FinetuneOrchestrator (`training/finetune_orchestrator.py`)

Manages the QLoRA training job queue, progress tracking, checkpoint management, and
auto-merge of LoRA adapters on completion.

```python
from training.finetune_orchestrator import get_finetune_orchestrator

orch = get_finetune_orchestrator()

job = orch.submit(
    "router_v3",
    base_model="qwen-270m",
    config={
        "num_epochs": 3,
        "learning_rate": 2e-4,
        "batch_size": 4,
        "max_seq_length": 512,
        "lora_rank": 16,
        "lora_alpha": 32,
    }
)

orch.run_next()                   # blocks until done
status = orch.get_job(job.job_id)
print(status.status)              # "running" | "done" | "failed"
print(status.progress)            # 0.0 -> 1.0
```

### Job Lifecycle

```
PENDING -> RUNNING -> DONE
                   |
              adapter saved to training/models/{job_id}/adapter/
                   |
              auto-merge: 16-bit model at training/models/{job_id}/merged/
                   |
              ModelRegistry.register() called automatically
```

### QLoRA Defaults Per Base Model

| Parameter | qwen-270m | qwen-1.7b | llama-3b (coder) |
|-----------|-----------|-----------|------------------|
| `lora_rank` | 16 | 8 | 16 |
| `lora_alpha` | 32 | 16 | 32 |
| `num_epochs` | 3 | 2 | 2 |
| `learning_rate` | 2e-4 | 1e-4 | 2e-4 |
| `batch_size` | 4 | 2 | 4 |
| `max_seq_length` | 512 | 512 | 2048 |

### AutoTrain (`training/auto_train.py`)

Orchestrates the daily training sweep. Reads dataset sizes from DataCollector, compares
against `ModelSpec.train_threshold`, and submits fine-tune jobs for types above threshold.

| Function | Description |
|----------|-------------|
| `check_and_train_all_zoo()` | Sweep all zoo entries, submit jobs for types above threshold |
| `get_status()` | Return per-type status dict: `{model_id: {count, threshold, ready, last_trained}}` |
| `daemon_loop()` | Blocking loop -- runs `check_and_train_all_zoo()` on schedule |

### Google Colab Workflow

For GPU training, use `training/gemma_router_finetune.ipynb`:

1. Upload the JSONL dataset to Google Drive via `upload_to_drive.py`
2. Open the notebook in Colab (T4 or better)
3. Run all cells -- the notebook uses Unsloth for 4-bit QLoRA
4. Download the adapter `.zip` and place in `training/models/`
5. Run `merge_adapters.py` to produce the merged 16-bit model

---

## 5. Evaluation & Promotion

### BenchmarkRunner (`training/benchmark_runner.py`)

Evaluates fine-tuned models against held-out test splits and optionally auto-promotes
if the score beats the current active model.

```python
from training.benchmark_runner import get_benchmark_runner

runner = get_benchmark_runner()

result = runner.run("router_v3", auto_promote=True)
print(result.summary())
# -> "router_v3/abc123: acc=0.923 f1=0.918 exact=0.910 score=0.917 latency=12ms"

results = runner.run_all()
```

**BenchmarkResult fields:**

```python
@dataclass
class BenchmarkResult:
    model_id: str
    model_type: str
    accuracy: float          # correct / total
    f1: float                # macro F1 across all classes
    exact_match: float       # exact string match rate
    total_examples: int
    correct: int
    latency_ms_avg: float    # average inference latency
    aggregate_score: float   # 0.5*accuracy + 0.3*f1 + 0.2*exact_match
    promoted: bool           # True if auto-promoted in this run
```

**Auto-promote logic:** if `result.aggregate_score > current_active.benchmark_score`,
the new model is promoted automatically.

Results are stored in `training/benchmarks.jsonl` and in Nexus for historical tracking.
`BenchmarkRunner` can use LMStudio for inference (default) or fall back to a rule-based
baseline (`use_lmstudio=False`).

### Coder Model Benchmark Metrics

The coder model uses different evaluation metrics:

| Metric | Weight | Description |
|--------|--------|-------------|
| `pass@1` | 0.5 | Does the generated code run without error on the test case? |
| `BLEU` | 0.3 | Token overlap between generated and reference output |
| `perplexity` | 0.2 | Model confidence (lower is better; normalised to 0--1) |

**Promotion threshold:** `aggregate_score > 0.65`

### ModelRegistry (`training/model_registry.py`)

Tracks all registered fine-tuned models, their benchmark scores, and which model is
currently active for each type. Persisted as JSON at `training/model_registry.json`.

```python
from training.model_registry import get_model_registry

registry = get_model_registry()

# Register a new model (done automatically by FinetuneOrchestrator)
model = registry.register(
    model_type="router_v3",
    adapter_path="training/models/router_v3_abc123/adapter",
    base_model="Qwen/Qwen2.5-0.5B-Instruct",
    merged_path="training/models/router_v3_abc123/merged",
    job_id="job-abc123",
    notes="First v3 run, 3 epochs",
)

registry.promote("router_v3", model.model_id)
active = registry.get_active("router_v3")
```

### InferenceRouter Integration

Once a model is promoted, `InferenceRouter` (`engine/lmstudio/router.py`) routes
inference requests using a 3-tier priority queue:

```
Tier 1 (T1): role=="game_master"  -> large model (primary LLM)
Tier 2 (T2): task_type=="small"   -> small model
Tier 3 (T3): task_type=="classify" or "route"  -> micro-model (fine-tuned)
```

`FinetunedRouter` (`engine/lmstudio/finetuned_router.py`) wraps the active fine-tuned
models and is called by `InferenceRouter` for T3 requests:

```python
from engine.lmstudio.finetuned_router import get_finetuned_router

router = get_finetuned_router()
label = router.classify("Attack the guard", model_type="router_v3")
# -> "game_action"
```

---

## 6. Coder Model Deep Dive

### Architecture

- **Base model:** `meta-llama/Llama-3.2-3B-Instruct`
- **LoRA rank:** 16, alpha 32
- **Training:** 2 epochs, lr 2e-4, batch 4, max seq 2048
- **Threshold:** 500 examples
- **Dataset:** `training/datasets/code_train.jsonl`
- **Adapter output:** `training/models/coder_{job_id}/adapter/`
- **Merged output:** `training/models/coder_{job_id}/merged/`

Runs fully offline -- no external API calls for code tasks. Fine-tuned on CosySim's own
Python codebase. Improves automatically as coder skills are used.

### Skill Pack -- `coder` (`engine/skills/builtin/coder_skills.py`)

Eight `@skill` functions registered under the `coder` pack:

| Skill | Arguments | Description |
|-------|-----------|-------------|
| `coder_complete` | `partial_code`, `context` | Fill in missing code given partial input |
| `coder_fix` | `code`, `error_msg` | Fix a bug given the code and error message |
| `coder_generate` | `spec`, `language` | Generate code from a natural-language spec |
| `coder_review` | `code` | Identify bugs, style issues, improvements |
| `coder_docstring` | `code` | Generate a Google-style docstring |
| `coder_test` | `code` | Generate a pytest test suite |
| `coder_refactor` | `code`, `goal` | Refactor with a specific goal |
| `coder_explain` | `code` | Plain-English explanation |

`coder_complete`, `coder_fix`, and `coder_generate` auto-collect training samples.
The other five do not (output format varies too much for unsupervised quality scoring).

### Coder Config Keys

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

## 7. Scheduler Automation

Training-related tasks in `SchedulerDaemon` (`engine/nexus/scheduler_daemon.py`):

| Task ID | Schedule | Action |
|---------|----------|--------|
| `collect-flush` | Every 4 hours | `DataCollector.flush_all()` -- merges live JSONL into training datasets |
| `model-zoo-train` | Daily | `check_and_train_all_zoo()` -- submits fine-tune jobs above threshold |
| `improvement-review` | Weekly | Surfaces Nexus `category=improvement` entries for human review |
| `teacher-dataset-gen` | Weekly | `MicroDatasetManager.build_all(count_per_model=500)` |
| `finetune-if-ready` | Weekly | Submits finetune job if new data available |
| `model-benchmark` | Daily | `BenchmarkRunner.run_all()` |
| `router-finetune-cycle` | Weekly | Full dataset -> train -> benchmark -> promote cycle |
| `dataset-augment` | Weekly | Re-augments all datasets with new session data |
| `conversation-analyze` | Daily | Generates training candidates from recent sessions |

```yaml
# config/default.yaml -- scheduler section
scheduler:
  tasks:
    collect-flush:
      interval: every_4h
      enabled: true
    model-zoo-train:
      interval: daily
      enabled: true
    improvement-review:
      interval: weekly
      enabled: true
```

---

## 8. Admin Dashboard

Training stats and controls are exposed in the admin overlay **[TRAINING]** tab.

### REST Endpoints

| Method | Endpoint | Description |
|--------|----------|-------------|
| `GET` | `/api/admin/training/stats` | DataCollector stats + model zoo status per type |
| `POST` | `/api/admin/training/seed` | Generate seed data via MicroDatasetManager |
| `POST` | `/api/admin/training/prune` | Run `prune_low_quality()` on a dataset type |
| `POST` | `/api/admin/training/trigger/<model_type>` | Manually trigger fine-tune for one zoo type |

Frontend: `static/admin_training.js` polls stats every 30s, renders per-type progress
bars (count / threshold), provides trigger buttons.

---

## CLI Reference

```bash
# Zoo status
python -m training.auto_train status

# Flush live data to training datasets
python -m training.data_collector flush_all

# Trigger training for a specific type
python -m training.auto_train trigger coder

# Full zoo sweep (same as daily scheduler task)
python -m training.auto_train sweep

# Prune low-quality samples
python -m training.data_collector prune code 0.5

# View DataCollector stats
python -m training.data_collector stats

# Seed coder dataset from codebase
python -m training.coder_pipeline seed

# Benchmark a model
python -m training.benchmark_runner run coder --auto-promote

# Scheduler daemon
python -m engine.nexus.scheduler_daemon start
python -m engine.nexus.scheduler_daemon status
python -m engine.nexus.scheduler_daemon run collect-flush
python -m engine.nexus.scheduler_daemon run model-zoo-train
python -m engine.nexus.scheduler_daemon run teacher-dataset-gen

# Admin API trigger
curl -X POST http://localhost:5555/api/admin/training/trigger/coder
```

Via MCP tool (from any scene):

```
scheduler_run_now("collect-flush")
scheduler_run_now("model-zoo-train")
scheduler_run_now("teacher-dataset-gen")
```

---

## Full Manual Pipeline Walkthrough

```python
# 1. Generate/refresh dataset
from training.micro_datasets import MicroDatasetManager
mgr = MicroDatasetManager()
mgr.build("router_v3", count=2000)

# 2. Prepare combined dataset
from training.data_manager import get_data_manager
dm = get_data_manager()
dm.prepare_for_training()

# 3. Submit fine-tune job
from training.finetune_orchestrator import get_finetune_orchestrator
orch = get_finetune_orchestrator()
job = orch.submit("router_v3", base_model="qwen-270m")
orch.run_next()

# 4. Benchmark and auto-promote
from training.benchmark_runner import get_benchmark_runner
runner = get_benchmark_runner()
result = runner.run("router_v3", auto_promote=True)
print(result.summary())

# 5. Verify routing uses new model
from engine.lmstudio.finetuned_router import get_finetuned_router
router = get_finetuned_router()
print(router.classify("Buy the stolen data chip", model_type="router_v3"))
# -> "economic_action"
```

---

## Directory Reference

```
training/
+-- data_collector.py             # Thread-safe JSONL appender
+-- model_zoo.py                  # MODEL_ZOO registry (9 ModelSpec entries)
+-- auto_train.py                 # check_and_train_all_zoo(), daemon_loop()
+-- finetune_orchestrator.py      # QLoRA job queue and execution
+-- model_registry.py             # Active model tracking, promotion
+-- model_registry.json           # Active model registry (JSON)
+-- benchmark_runner.py           # Evaluation against held-out test splits
+-- benchmarks.jsonl              # Benchmark result history
+-- jobs.jsonl                    # Fine-tune job history
+-- coder_pipeline.py             # 10 coder data collection strategies
+-- micro_datasets.py             # MicroDatasetManager (NLM teacher generation)
+-- data_manager.py               # Dataset combination and deduplication
+-- deploy_router.py              # Router deployment utilities
+-- gemma_router_finetune.ipynb   # Colab training notebook
+-- datasets/
|   +-- collected/                # Live JSONL (pre-flush)
|   |   +-- conversation_live.jsonl
|   |   +-- code_live.jsonl
|   |   +-- grammar_error_live.jsonl
|   |   +-- output_rating_live.jsonl
|   +-- conversation_train.jsonl  # Merged training datasets
|   +-- code_train.jsonl
|   +-- grammar_error_train.jsonl
|   +-- output_rating_train.jsonl
|   +-- router_v3_train.jsonl     # 1,872 examples (90%)
|   +-- router_v3_val.jsonl       # 208 examples (10%)
|   +-- router_v3_test.jsonl      # 100 examples (held-out)
|   +-- router_v2_train.jsonl     # 364 examples, 8-class
|   +-- qa_evaluator_train.jsonl
|   +-- conversation_analyzer_train.jsonl
|   +-- syntax_fixer_train.jsonl
|   +-- knowledge_synthesizer_train.jsonl
+-- models/                       # Fine-tuned adapter outputs

engine/
+-- agents/
|   +-- grammar_scanner_interceptor.py
|   +-- output_evaluator.py
+-- lmstudio/
|   +-- router.py                 # InferenceRouter (3-tier)
|   +-- finetuned_router.py       # FinetunedRouter (micro-model wrapper)
+-- nexus/
    +-- scheduler_daemon.py       # Scheduler tasks
```

---

## Config Keys

| Key | Default | Description |
|-----|---------|-------------|
| `training.collect_path` | `training/datasets/collected/` | Live JSONL output directory |
| `training.dataset_path` | `training/datasets/` | Merged training dataset directory |
| `training.models_path` | `training/models/` | Fine-tuned model output directory |
| `training.auto_train.enabled` | `true` | Enable daily zoo sweep |
| `training.auto_train.min_score` | `0.5` | Default quality floor for prune |
| `training.grammar_scanner.enabled` | `true` | Enable grammar scanner interceptor |
| `training.output_evaluator.low_score_threshold` | `0.6` | Collect responses below this score |
| `training.coder.enabled` | `true` | Enable coder skill data collection |
| `training.coder.min_quality` | `0.5` | Discard coder samples below this score |
| `training.coder.seed_on_startup` | `false` | Run AST seed scan at startup |
| `training.coder.promotion_threshold` | `0.65` | Minimum coder benchmark score to promote |

---

## Troubleshooting

**Dataset too small** -- check `get_data_manager().get_pipeline_status().synthetic_counts`.
If a dataset has < 200 examples, run `mgr.seed_datasets()` to regenerate.

**Fine-tune job stuck** -- list jobs with `orch.list_jobs()`, cancel with `orch.cancel(job_id)`.

**Model not routing to fine-tuned model** -- verify `registry.get_active("router_v3")` is
not `None`. If no active model, run `BenchmarkRunner.run()` first.

**Running benchmarks without GPU** -- set `use_lmstudio=False` to run the rule-based
baseline offline.

---

## Cross-References

- [Architecture](ARCHITECTURE.md) — System overview and engine layers
- [Nexus](NEXUS.md) — How Nexus stores benchmark results and training data
- [LMStudio](LMSTUDIO.md) — InferenceRouter and FinetunedRouter architecture
- [Skills](SKILLS.md) — The `@skill` decorator and coder skill pack registration
- [Argus](ARGUS.md) — External API monitoring and health checks

---

## Change Log

| Version | Date | Description |
|---------|------|-------------|
| v1.50 | 2026-03-22 | Updated header to v1.50, fixed cross-references (NEXUS_INTEGRATION, ADMIN_GUIDE -> current names) |
| v1.04 | 2026-03-15 | Added coder model deep dive, scheduler automation, admin dashboard endpoints |
| v0.90 | 2026-03-12 | Initial training pipeline documentation with data flywheel, model zoo, fine-tuning, benchmarks |
