# CosySim Training Pipeline

Fine-tune **Google Gemma 3 270M** as an ultra-fast router/classifier for CosySim tasks.

## Overview

The training system generates synthetic datasets, fine-tunes task-specific LoRA adapters using QLoRA + Unsloth, merges them into a single model, and exports to GGUF format for local inference. Live production data can supplement synthetic training data via MetricsDB export.

**Architecture**: Qwen3-style XML tool template boosts 270M accuracy from ~10–39% to ~90–97%.

## Directory Layout

```
training/
├── generate_datasets.py          # Synthetic dataset generator
├── finetune_local.py             # Local QLoRA fine-tuning
├── merge_adapters.py             # Sequential LoRA adapter merge + GGUF export
├── auto_train.py                 # Automated training daemon
├── prepare_from_live.py          # MetricsDB → JSONL export
├── gemma_router_finetune.ipynb   # Google Colab notebook
├── datasets/                     # Generated/live training data
└── output/                       # Trained models (adapters, GGUF)
```

## Dataset Generation

`generate_datasets.py` produces **5 JSONL datasets** (2,100 examples total):

| Dataset | Examples | Purpose |
|---------|----------|---------|
| `tag_extraction` | 800 | Parse `[MOOD:x]` `[IMAGE:x]` tags from LLM output |
| `tool_routing` | 400 | Classify user intent → tool call |
| `priority_classify` | 300 | Route requests to priority tier (realtime/interactive/background/batch) |
| `decision_classify` | 300 | Character state → next action decision |
| `response_validate` | 300 | Validate output format (valid JSON / plain text / malformed) |

Each dataset is split into train (90%) and validation (10%) JSONL files.

```bash
# Generate all datasets
python -m training.generate_datasets

# Generate specific datasets with custom output dir and seed
python -m training.generate_datasets --out training/datasets --only tag_extraction,tool_routing --seed 42
```

## Local Fine-Tuning

`finetune_local.py` performs QLoRA fine-tuning with Unsloth, supporting both CPU and GPU.

### Default Hyperparameters

| Parameter | Default |
|-----------|---------|
| Base model | `google/gemma-3-270m-it` |
| LoRA rank (r) | 16 |
| LoRA alpha | 16 |
| LoRA dropout | 0 |
| Learning rate | 2e-4 |
| Batch size | 4 |
| Gradient accumulation | 4 |
| Max sequence length | 512 |
| Weight decay | 0.01 |
| Warmup steps | 5 |
| Quantization | 4-bit (QLoRA) |

### Commands

```bash
# Train on a dataset
python -m training.finetune_local train --dataset tag_extraction --epochs 3 --lr 2e-4

# Evaluate a trained adapter
python -m training.finetune_local eval --adapter training/output/cosysim-tag_extraction/adapter --dataset tag_extraction --max-samples 50

# Check dependencies (unsloth, transformers, peft, trl, torch)
python -m training.finetune_local check

# Show dataset statistics
python -m training.finetune_local stats
```

**Output**: `training/output/cosysim-{dataset_name}/` containing `adapter/`, `gguf/` (Q4_K_M ~150 MB), and `gguf-q8/` (Q8_0 ~300 MB).

## Adapter Merging

`merge_adapters.py` sequentially merges multiple task-specific LoRA adapters into a single model and exports to GGUF.

```bash
# Merge two adapters and export GGUF
python -m training.merge_adapters --adapters path/adapter_a path/adapter_b --output merged

# Merge without GGUF export
python -m training.merge_adapters --adapters path/adapter_a --no-gguf --max-seq-length 512
```

## Auto-Train

`auto_train.py` is a daemon that continuously monitors MetricsDB for new training candidates and triggers fine-tuning when thresholds are met.

### Default Thresholds

| Dataset | Min Examples |
|---------|-------------|
| `tag_extraction` | 100 |
| `tool_routing` | 50 |
| `priority_classify` | 50 |
| `decision_classify` | 50 |
| `response_validate` | 50 |

```bash
# One-shot check
python -m training.auto_train

# Run as daemon (check every hour)
python -m training.auto_train --daemon --interval 3600

# Check status
python -m training.auto_train --status

# Dry run (check without training)
python -m training.auto_train --dry-run --min-quality 0.7
```

State is persisted in `.auto_train_state.json`.

## Live Data Export

`prepare_from_live.py` exports production metrics from MetricsDB into training-ready JSONL.

```bash
# Export live data for a specific dataset
python -m training.prepare_from_live --dataset tag_extraction --min-quality 0.7

# Show example counts per dataset
python -m training.prepare_from_live --stats

# Merge synthetic + live datasets into combined files
python -m training.prepare_from_live --merge
```

**File naming convention**:
- `{dataset}_train.jsonl` — synthetic training data
- `{dataset}_val.jsonl` — synthetic validation data
- `{dataset}_live.jsonl` — exported live examples
- `{dataset}_combined.jsonl` — merged synthetic + live

## Colab Notebook

`gemma_router_finetune.ipynb` provides a Google Colab environment for training on a T4 GPU.

**Suggested training order**: tag_extraction → tool_routing → priority_classify → decision_classify → response_validate

**Training budget**: ~25–50 compute units total (T4 GPU, 10–15 min per dataset).

## MCP Skills

Four training skills are registered in `engine/skills/builtin/training_skills.py` (pack: `training`):

| Skill | Description |
|-------|-------------|
| `trigger_finetune(dataset, epochs=3)` | Launch async background training job; returns job_id and status |
| `get_training_status(job_id="")` | Poll job status or list all jobs |
| `export_training_data(dataset, min_quality=0.7)` | Export MetricsDB candidates to JSONL |
| `list_trained_models()` | Scan `training/output/` for artifacts (adapters, GGUF, sizes) |
