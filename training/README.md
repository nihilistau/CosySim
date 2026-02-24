# CosySim Training — Gemma 270M Router

Fine-tune Google's Gemma 3 270M as a specialised ultra-fast router/classifier for CosySim.

## Quick Start

```bash
# 1. Generate training datasets locally
python -m training.generate_datasets

# 2. Upload training/datasets/*.jsonl to Google Drive
#    → cosysim_training/ folder

# 3. Open training/gemma_router_finetune.ipynb in Google Colab
#    → Set DATASET_NAME, run all cells

# 4. Download GGUF from Google Drive → LMStudio models directory
```

## Datasets

| Dataset | Examples | Purpose |
|---------|----------|---------|
| `tag_extraction` | 800 | Parse `[MOOD:x]` `[IMAGE:x]` tags from LLM output |
| `tool_routing` | 400 | Classify intent → tool call |
| `priority_classify` | 300 | Request → priority tier (realtime/interactive/background/batch) |
| `decision_classify` | 300 | Character state → next action |
| `response_validate` | 300 | Check if output matches expected format |

## Training Budget

- **GPU**: T4 (Colab Pro free tier or ~5 compute units per run)
- **Time**: ~10-15 minutes per dataset
- **Total**: ~25-50 compute units for all 5 datasets × 2 iterations

## Output Formats

- `gguf/` — Q4_K_M quantised (~150MB) for LMStudio deployment
- `gguf-q8/` — Q8_0 quantised (~300MB) for higher quality
- `lora/` — LoRA adapter weights for further fine-tuning

## Architecture

Uses **Qwen3-style XML tool template** for structured output:

```
<tool_call>{"name":"route_tags","arguments":{"mood":"happy","action":"sit_down"}}</tool_call>
```

This template boosts 270M model accuracy from ~10-39% to ~90-97% on structured tasks.

## Files

```
training/
├── __init__.py
├── generate_datasets.py      # Dataset generator (run locally)
├── gemma_router_finetune.ipynb  # Colab notebook
├── README.md                 # This file
└── datasets/                 # Generated training data
    ├── tag_extraction_train.jsonl
    ├── tag_extraction_val.jsonl
    ├── tool_routing_train.jsonl
    ├── tool_routing_val.jsonl
    ├── priority_classify_train.jsonl
    ├── priority_classify_val.jsonl
    ├── decision_classify_train.jsonl
    ├── decision_classify_val.jsonl
    ├── response_validate_train.jsonl
    └── response_validate_val.jsonl
```
