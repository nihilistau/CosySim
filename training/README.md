# CosySim Training — Gemma 270M Router

Fine-tune Google's Gemma 3 270M as a specialised ultra-fast router/classifier for CosySim.

## Quick Start

```bash
# 1. Generate training datasets (3900 examples at 1.5x scale)
python -m training.generate_datasets --seed 2026 --scale 1.5

# 2a. VS Code + Colab Pro (recommended)
#     Open training/gemma_router_finetune.ipynb → Connect to Colab runtime
#     Cell 3 auto-clones the repo with sparse checkout

# 2b. Or upload to Google Drive
python -m training.upload_to_drive --method auto

# 3. Run all cells in the notebook
#    Set DATASET_NAME per training run: tag_extraction → tool_routing → ...

# 4. Download GGUF from Google Drive → LMStudio models directory

# 5. Local training (Windows, no Triton needed)
python -m training.finetune_local train --dataset tag_extraction --backend hf
```

## Datasets

| Dataset | Default | @1.5x | Purpose |
|---------|---------|-------|---------|
| `tag_extraction` | 800 | 1,200 | Parse `[MOOD:x]` `[IMAGE:x]` tags from LLM output |
| `tool_routing` | 600 | 900 | Classify intent → tool call (34 tools) |
| `priority_classify` | 400 | 600 | Request → priority tier + device |
| `decision_classify` | 400 | 600 | Character state → next action |
| `response_validate` | 400 | 600 | Check if output matches expected format |

## Training Methods

### Colab Pro (recommended — fastest, cheapest)
- Open `gemma_router_finetune.ipynb` in VS Code with Colab integration
- Uses Unsloth + 4-bit QLoRA on T4 GPU
- ~10-15 min per dataset, ~5 compute units per run
- Exports GGUF directly (Q4_K_M ~150MB, Q8_0 ~300MB)

### Local (Windows/Linux)
- `python -m training.finetune_local train --dataset all --backend auto`
- Auto-selects: Unsloth (Linux) or HF Transformers + PEFT (Windows)
- Windows: uses fp16 on CUDA, no Triton dependency
- Linux: full Unsloth with 4-bit QLoRA

### Auto-train (daemon)
- `python -m training.auto_train --daemon`
- Monitors MetricsDB for new training candidates
- Auto-triggers training when thresholds met (100 tag, 50 others)

## Training Pipeline

```
generate_datasets.py ──→ training/datasets/*.jsonl
                              │
upload_to_drive.py ───────────┤ (optional, for Drive method)
                              │
                         ┌────┴────┐
                    Colab notebook  │  finetune_local.py
                    (Unsloth 4bit)  │  (HF or Unsloth)
                         └────┬────┘
                              │
                    training/output/
                    ├── gguf/     (Q4_K_M for LMStudio)
                    ├── gguf-q8/  (Q8_0 higher quality)
                    └── adapter/  (LoRA for iteration)
                              │
                    merge_adapters.py  (combine task adapters)
                              │
                    LMStudio T3 Router  (CPU, ~150MB)
```

## Live Data Capture

```bash
# Export from MetricsDB training_candidates
python -m training.prepare_from_live --min-quality 0.7

# Files output as {dataset}_live.jsonl
# finetune_local.py auto-loads live data alongside synthetic
```

## Output Formats

- `gguf/` — Q4_K_M quantised (~150MB) for LMStudio deployment
- `gguf-q8/` — Q8_0 quantised (~300MB) for higher quality
- `lora/` or `adapter/` — LoRA adapter weights for further fine-tuning

## Files

```
training/
├── __init__.py
├── generate_datasets.py       # Dataset generator (5 tasks, --scale flag)
├── gemma_router_finetune.ipynb # Colab notebook (VS Code integration)
├── finetune_local.py           # Local training (HF or Unsloth backend)
├── auto_train.py               # Automated training daemon
├── prepare_from_live.py        # Live data capture from MetricsDB
├── merge_adapters.py           # Combine multiple LoRA adapters
├── upload_to_drive.py          # Upload datasets to Google Drive
├── README.md                   # This file
└── datasets/                   # Generated training data
    ├── tag_extraction_{train,val}.jsonl
    ├── tool_routing_{train,val}.jsonl
    ├── priority_classify_{train,val}.jsonl
    ├── decision_classify_{train,val}.jsonl
    └── response_validate_{train,val}.jsonl
```
