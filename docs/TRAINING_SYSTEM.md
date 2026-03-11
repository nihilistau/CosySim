# CosySim Training System

> End-to-end self-improving training pipeline — v0.78b "THE DATA FLYWHEEL".
> Every runtime interaction feeds the DataCollector → dataset merges → threshold-gated
> fine-tuning → BenchmarkRunner evaluation → ModelRegistry promotion → LMStudio reload.

---

## Overview

CosySim v0.78b introduces the **Data Flywheel** — a fully autonomous training pipeline
that collects signal from every runtime event, accumulates it into typed datasets, and
continuously fine-tunes a fleet of local models without any manual intervention.

The compound effect: **more runtime interactions → richer datasets → better models →
better runtime behaviour → more interactions**. The system improves automatically as
it is used.

```
Runtime Events
      │
      ▼
┌─────────────────────┐      every_4h       ┌─────────────────────┐
│   DataCollector      │  ──────────────►   │  Dataset Merge       │
│   (JSONL appender)   │                    │  live → train.jsonl  │
└─────────────────────┘                    └──────────┬──────────┘
                                                       │  daily
                                                       ▼
                                           ┌─────────────────────┐
                                           │  model-zoo-train     │
                                           │  (threshold check)   │
                                           └──────────┬──────────┘
                                                       │  if ≥ threshold
                                                       ▼
                                           ┌─────────────────────┐
                                           │ FinetuneOrchestrator │
                                           │ (QLoRA / Unsloth)    │
                                           └──────────┬──────────┘
                                                       │
                                                       ▼
                                           ┌─────────────────────┐
                                           │   BenchmarkRunner    │
                                           │   (score > previous) │
                                           └──────────┬──────────┘
                                                       │  if promoted
                                                       ▼
                                           ┌─────────────────────┐
                                           │   ModelRegistry      │◄── LMStudio loads
                                           │   (active model)     │    promoted model
                                           └─────────────────────┘
```

---

## Architecture

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
| `stats` | `() → dict` | Per-type counts, file sizes, last-write timestamps |
| `flush` | `(data_type)` | Merge one live file into its training dataset |
| `flush_all` | `()` | Merge all live files into training datasets |
| `get_stats` | `() → DataStats` | Structured stats dataclass |
| `prune_low_quality` | `(data_type, min_score)` | Drop samples below quality threshold |

**Live file locations:**

```
training/datasets/collected/
├── conversation_live.jsonl
├── code_live.jsonl
├── grammar_error_live.jsonl
└── output_rating_live.jsonl
```

**Merged training datasets (after flush):**

```
training/datasets/
├── conversation_train.jsonl
├── code_train.jsonl
├── grammar_error_train.jsonl
└── output_rating_train.jsonl
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

---

### Model Zoo (`training/model_zoo.py`)

Registry of all trainable model types. Each entry is a `ModelSpec` dataclass that
declares the base model, LoRA configuration, training schedule, and promotion threshold.

**`ModelSpec` fields:**

| Field | Type | Description |
|-------|------|-------------|
| `id` | `str` | Unique model type identifier |
| `label` | `str` | Human-readable display name |
| `base_model` | `str` | HuggingFace model ID or local alias |
| `lora_r` | `int` | LoRA rank |
| `epochs` | `int` | Default training epochs |
| `train_threshold` | `int` | Minimum samples required to trigger training |

**`MODEL_ZOO` — 9 model types:**

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

```python
from training.model_zoo import MODEL_ZOO, ModelSpec

# Look up a spec
spec = MODEL_ZOO["coder"]
print(spec.base_model)        # meta-llama/Llama-3.2-3B-Instruct
print(spec.train_threshold)   # 500

# Iterate all zoo entries
for model_id, spec in MODEL_ZOO.items():
    print(f"{model_id}: needs {spec.train_threshold} samples")
```

---

### AutoTrain (`training/auto_train.py`)

Orchestrates the daily training sweep. Reads current dataset sizes from DataCollector,
compares against `ModelSpec.train_threshold` for each zoo entry, and submits fine-tune
jobs via `FinetuneOrchestrator` for any type that has crossed its threshold.

**Key functions:**

| Function | Description |
|----------|-------------|
| `check_and_train_all_zoo()` | Sweep all zoo entries, submit jobs for types above threshold |
| `get_status()` | Return per-type status dict: `{model_id: {count, threshold, ready, last_trained}}` |
| `daemon_loop()` | Blocking loop — runs `check_and_train_all_zoo()` on schedule |

```python
from training.auto_train import check_and_train_all_zoo, get_status

# Manual sweep
results = check_and_train_all_zoo()
for model_id, outcome in results.items():
    print(f"{model_id}: {outcome}")   # "submitted" | "below_threshold" | "skipped"

# Status overview
status = get_status()
print(status["coder"])
# {"count": 612, "threshold": 500, "ready": True, "last_trained": "2026-06-01T02:00:00Z"}
```

---

### Grammar Scanner Interceptor (`engine/agents/grammar_scanner_interceptor.py`)

Post-call interceptor that runs after every LLM response. Performs 6 grammar checks
and writes violations to the DataCollector as `grammar_error` samples for fine-tuning
the `grammar_scanner` model.

**6 grammar checks:**

| Check | Description |
|-------|-------------|
| `subject_verb_agreement` | Detects agreement mismatches (e.g., "she were") |
| `tense_consistency` | Flags mixed past/present tense within a response |
| `article_usage` | Catches missing or incorrect a/an/the usage |
| `double_negation` | Identifies double negatives |
| `run_on_sentence` | Flags excessively long unpunctuated sentences |
| `comma_splice` | Detects independent clauses joined only by a comma |

**Integration:** Registered as a post-call interceptor with priority `POST_CALL_50`.
Violations are collected with the original text, the detected violation type, a
corrected form, and a severity score (0.0–1.0).

---

### Output Evaluator (`engine/agents/output_evaluator.py`)

Scores every LLM response on a 0.0–1.0 scale. Low-scoring responses (`< 0.6`) are
collected as `output_rating` samples and additionally posted to Nexus under
`category=improvement` so the weekly `improvement-review` task can surface them for
human review.

```python
from engine.agents.output_evaluator import OutputEvaluator

evaluator = OutputEvaluator()
score = evaluator.score(
    prompt="Describe the tavern's atmosphere.",
    response="It is a tavern.",
)
print(score)   # 0.21 — collected as low-quality sample
```

**Scoring dimensions:** fluency, relevance, detail, tone consistency, character
adherence. Aggregate is the weighted mean.

---

### Scheduler Tasks (`engine/nexus/scheduler_daemon.py`)

Three training-related tasks drive the flywheel on automatic schedules:

| Task ID | Interval | Action |
|---------|----------|--------|
| `collect-flush` | Every 4 hours | `DataCollector.flush_all()` — merges live JSONL into training datasets |
| `model-zoo-train` | Daily | `check_and_train_all_zoo()` — submits fine-tune jobs for types above threshold |
| `improvement-review` | Weekly | Surfaces Nexus `category=improvement` entries for human review |

```yaml
# config/default.yaml — scheduler section
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

## Data Sources

### VirtualAgent Conversations

Every completed exchange between a VirtualAgent and the user is automatically collected:

```python
# Inside VirtualAgent.run_exchange() — called automatically
dc.collect_conversation(
    messages=exchange.messages,
    model=exchange.model_used,
    quality=exchange.quality_score,
)
```

Volume: **every interaction** across all 15 active scenes. High-traffic scenes
(penthouse, phone, lounge) generate hundreds of samples per session.

---

### Coder Skills

Three coder skill calls each write a training sample on every invocation:

| Skill | Collected as | Sample content |
|-------|-------------|---------------|
| `coder_complete` | `code` | `{prompt: partial_code, completion: result}` |
| `coder_fix` | `code` | `{prompt: buggy_code + error_msg, completion: fixed_code}` |
| `coder_generate` | `code` | `{prompt: spec, completion: generated_code}` |

Language and quality score are included in each sample.

---

### Grammar Scanner

Post-call violations are collected automatically by `GrammarScannerInterceptor`:

```python
dc.collect_grammar_error(
    text=original_response,
    violation="tense_consistency",
    fix=corrected_response,
    severity=0.72,
)
```

---

### Output Evaluator

Low-quality responses are collected with their score and reason:

```python
dc.collect_output_rating(
    prompt=request.prompt,
    response=llm_response,
    score=0.34,
    reason="low_detail,off_character",
)
```

Scores ≥ 0.6 are not collected — only cases where the model underperformed.

---

### Human Ratings

Admin thumbs up/down from the admin overlay is translated into quality scores and
collected as `output_rating` samples (`1.0` for thumbs up, `0.0` for thumbs down).

---

## Training Flow — Step by Step

```
Step 1: Runtime → DataCollector
        VirtualAgent, coder skills, grammar scanner, output evaluator all write to:
        training/datasets/collected/{type}_live.jsonl

Step 2: collect-flush task (every 4h)
        DataCollector.flush_all() merges live files →
        training/datasets/{type}_train.jsonl
        (deduplicates on content hash, preserves order)

Step 3: model-zoo-train task (daily)
        auto_train.check_and_train_all_zoo():
        ├─ Read dataset sizes
        ├─ Compare against ModelSpec.train_threshold
        └─ For each type above threshold → FinetuneOrchestrator.submit()

Step 4: FinetuneOrchestrator runs QLoRA training (Unsloth)
        ├─ LoRA adapter saved to training/models/{job_id}/adapter/
        └─ Merged 16-bit model at training/models/{job_id}/merged/

Step 5: BenchmarkRunner evaluates
        ├─ Scores new model on held-out test split
        ├─ Compares aggregate_score against current active model
        └─ If score > previous best → ModelRegistry.promote()

Step 6: LMStudio loads promoted model
        InferenceRouter detects registry change → hot-reloads model
        Improved model handles future runtime requests
```

---

## Admin Dashboard

Training stats and controls are exposed via the shared blueprint in
`content/shared/__init__.py` and rendered in the admin overlay **[TRAINING]** tab.

### REST Endpoints

| Method | Endpoint | Description |
|--------|----------|-------------|
| `GET` | `/api/admin/training/stats` | DataCollector stats + model zoo status per type |
| `POST` | `/api/admin/training/seed` | Generate seed data for a model type via MicroDatasetManager |
| `POST` | `/api/admin/training/prune` | Run `prune_low_quality()` on a dataset type |
| `POST` | `/api/admin/training/trigger/<model_type>` | Manually trigger fine-tune for one zoo type |

**`GET /api/admin/training/stats` response:**

```json
{
  "collector": {
    "conversation": {"count": 1240, "file_size_kb": 892, "last_write": "2026-06-02T14:32:00Z"},
    "code":         {"count": 387,  "file_size_kb": 214, "last_write": "2026-06-02T13:01:00Z"},
    "grammar_error":{"count": 156,  "file_size_kb": 78,  "last_write": "2026-06-02T12:55:00Z"},
    "output_rating":{"count": 203,  "file_size_kb": 98,  "last_write": "2026-06-02T11:20:00Z"}
  },
  "zoo": {
    "coder":        {"count": 387, "threshold": 500, "ready": false, "last_trained": null},
    "grammar_scanner":{"count": 156,"threshold": 200, "ready": false, "last_trained": null},
    "conversational":{"count": 1240,"threshold": 1000,"ready": true,  "last_trained": "2026-06-01T02:00:00Z"}
  }
}
```

### Frontend

- **JavaScript:** `static/admin_training.js` — polls `/api/admin/training/stats` every
  30 s, renders per-type progress bars (count / threshold), provides trigger buttons.
- **CSS:** `static/admin_training.css` — matches the admin overlay neon theme.
- **Tab:** Visible in the admin overlay as **[TRAINING]** alongside SCHEDULER, NEXUS, etc.

---

## CLI Usage

```bash
# Check zoo status (all types)
python -m training.auto_train status

# Manually flush live data to training datasets
python -m training.data_collector flush_all

# Trigger training for a specific type
python -m training.auto_train trigger coder

# Run full zoo sweep (same as daily scheduler task)
python -m training.auto_train sweep

# Prune low-quality samples (threshold 0.5)
python -m training.data_collector prune code 0.5

# View DataCollector stats
python -m training.data_collector stats
```

**Via scheduler daemon:**

```bash
# Force-run the flush task immediately
python -m engine.nexus.scheduler_daemon run collect-flush

# Force-run the daily training sweep
python -m engine.nexus.scheduler_daemon run model-zoo-train

# Check scheduler task status
python -m engine.nexus.scheduler_daemon status
```

**Via MCP tool (from any scene):**

```
scheduler_run_now("collect-flush")
scheduler_run_now("model-zoo-train")
```

---

## Directory Reference

```
training/
├── data_collector.py             # Thread-safe JSONL appender
├── model_zoo.py                  # MODEL_ZOO registry (9 ModelSpec entries)
├── auto_train.py                 # check_and_train_all_zoo(), daemon_loop()
├── finetune_orchestrator.py      # QLoRA job queue and execution
├── model_registry.py             # Active model tracking, promotion
├── benchmark_runner.py           # Evaluation against held-out test splits
├── datasets/
│   ├── collected/
│   │   ├── conversation_live.jsonl
│   │   ├── code_live.jsonl
│   │   ├── grammar_error_live.jsonl
│   │   └── output_rating_live.jsonl
│   ├── conversation_train.jsonl
│   ├── code_train.jsonl
│   ├── grammar_error_train.jsonl
│   └── output_rating_train.jsonl
└── models/                       # Fine-tuned adapter outputs

engine/
├── agents/
│   ├── grammar_scanner_interceptor.py
│   └── output_evaluator.py
└── nexus/
    └── scheduler_daemon.py       # collect-flush, model-zoo-train, improvement-review
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

---

*See [FINETUNING_GUIDE.md](./FINETUNING_GUIDE.md) for FinetuneOrchestrator and BenchmarkRunner internals.*  
*See [TRAINING_FLYWHEEL.md](./TRAINING_FLYWHEEL.md) for the RouterDataCollector routing-specific pipeline.*  
*See [CODER_MODEL.md](./CODER_MODEL.md) for the full coder model pipeline and skill pack.*  
*See [SKILLS.md](./SKILLS.md) for the `@skill` decorator and coder skill pack registration.*  
*See [ADMIN_GUIDE.md](./ADMIN_GUIDE.md) for the admin overlay TRAINING tab.*
