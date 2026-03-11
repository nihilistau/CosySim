# Asset Studio — ComfyUI Integration Guide

> v0.73b · Asset generation, workflow tuning, and scene injection for CosySim.

---

## Overview

Asset Studio is CosySim's integrated ComfyUI pipeline. It provides:

- **15 pre-built workflow variants** (image + video) with all parameters exposed
- **A++ tuning engine** — automated quality benchmarking with Qwen3 VL scoring
- **Scene asset injection** — generate backgrounds and items directly into scene static folders
- **Batch background generator** — nightly scheduler task for all 9 game scenes

---

## Architecture

```
Asset Studio
├── engine/asset_studio/
│   ├── __init__.py            — module exports
│   ├── workflow_builder.py    — 15 workflow builders + WORKFLOW_REGISTRY
│   ├── workflow_manager.py    — high-level generate() API
│   ├── tuning_engine.py       — benchmark runner, VL scorer, auto-tuner
│   └── generators/
│       ├── image_gen.py       — image generation helpers
│       ├── portrait_gen.py    — portrait-specific helpers
│       └── video_gen.py       — Wan 2.2 video helpers
├── engine/skills/builtin/
│   └── comfyui_skills.py      — LLM-callable skills (4 skills)
└── content/simulation/services/
    └── comfyui_client.py      — raw ComfyUI HTTP client
```

---

## Workflow Variants

### Image Workflows (9)

| Name | Resolution | Steps | Use Case |
|------|-----------|-------|----------|
| `portrait_hires` | 512×768 | 20 | Character portraits, default |
| `portrait_refiner` | 512×768 | 30 | High-quality portrait with refiner pass |
| `portrait_fast` | 512×768 | 6 | Fast character generation |
| `character_card` | 512×512 | 15 | Square character card |
| `game_item_icon` | 256×256 | 10 | Item/skill icons |
| `scene_background` | 1920×1080 | 20 | Full scene backgrounds |
| `action_card` | 768×512 | 15 | Action/event landscape cards |
| `ui_icon` | 128×128 | 8 | Small UI elements |
| `message_image` | 512×512 | 12 | In-conversation images |

**Proven defaults:** sampler=`euler`, scheduler=`exponential`, cfg=`1.0`, model=`dreamshaper_8_lcm`

### Video Workflows — Wan 2.2 GGUF (6)

| Name | Resolution | Frames | FPS | Use Case |
|------|-----------|--------|-----|----------|
| `video_wan_t2v` | 480×272 | 49 | 16 | Text-to-video (uses white.png start) |
| `video_wan_i2v` | 480×272 | 49 | 16 | Image-to-video |
| `video_wan_landscape` | 480×272 | 49 | 16 | Widescreen T2V |
| `video_wan_portrait_fast` | 272×352 | 49 | 16 | Quick portrait-aspect video |
| `video_wan_character_hq` | 272×352 | 81 | 24 | High-quality character video |

**Wan 2.2 dual-model architecture:**
- High model: `wan22EnhancedNSFWSVICamera_nsfwFASTMOVEV2Q4KMH.gguf`
- Low model: `wan22EnhancedNSFWSVICamera_nsfwFASTMOVEV2Q4KML.gguf`
- CLIP: `nsfwWanUMT5XXLGGUF_q5AndQ4KM.gguf`
- LoRA: `lightx2v_I2V_14B_480p_cfg_step_distill_rank128_bf16.safetensors`
- Dual KSamplerAdvanced: stage1 (steps 0→N/2), stage2 (N/2→N)
- T2V trick: `D:\ComfyUI\input\white.png` as start image → model acts as T2V

**Proven video defaults:** sampler=`euler`, scheduler=`simple`, cfg=`1.0`, steps=`6`, shift=`5.0`

### Upscale Workflow (1)

| Name | Scale | Use Case |
|------|-------|----------|
| `upscale_enhance` | 2× | Post-process upscale of any generated image |

---

## Workflow Manager API

```python
from engine.asset_studio.workflow_manager import get_workflow_manager

wm = get_workflow_manager()

# Generate with a named workflow
result = wm.generate(
    workflow_name="portrait_hires",
    params={
        "prompt": "cinematic portrait of a detective, noir lighting",
        "negative_prompt": "blurry, watermark",
        "width": 512,
        "height": 768,
        "steps": 20,
        "cfg": 1.0,
        "seed": -1,        # -1 = random
        "output_prefix": "detective",
    },
)
# result = {"status": "ok", "output_path": "/path/to/image.png"}

# List available workflows
workflows = wm.list_workflows()
```

### Exposable Parameters (all workflows)

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `prompt` | str | required | Positive prompt |
| `negative_prompt` | str | `""` | Negative prompt |
| `width` | int | workflow default | Output width |
| `height` | int | workflow default | Output height |
| `steps` | int | workflow default | Diffusion steps |
| `cfg` | float | 1.0 | Guidance scale |
| `seed` | int | -1 | -1 = random |
| `sampler` | str | `euler` | Sampler name |
| `scheduler` | str | `exponential` | Scheduler name |
| `output_prefix` | str | `cosysim` | Filename prefix |

**Video-only parameters:**

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `fps` | int | 16 | Output FPS |
| `frame_count` | int | 49 | Total frames (controls length) |
| `batch_size` | int | 1 | Videos to generate |
| `shift` | float | 5.0 | ModelSamplingSD3 shift |
| `start_image` | str | white.png | Image for I2V mode |

**Length formula:** `duration_seconds = frame_count / fps`
- 49 frames @ 16fps = ~3 seconds
- 81 frames @ 24fps = ~3.4 seconds
- 97 frames @ 16fps = ~6 seconds

---

## LLM Skills

Four skills available to agents via the `comfyui` skill pack:

### `generate_image(prompt, negative_prompt, width, height, steps, cfg_scale, style)`
Generate an image and return its download URL.

### `generate_character_portrait(character_name, physical_description, mood, style)`
Generate a character headshot. Wraps `generate_image` with portrait-appropriate defaults.

### `generate_scene_image(scene, image_type, prompt, width, height, steps, cfg, filename)`
Generate an image and inject it into the target scene's `static/img/` folder.
Returns the Flask static URL (e.g. `/scenes/penthouse/static/img/bg_001.png`).

Scene-aware auto-prompts are built if no prompt is supplied:
```
penthouse  → luxury penthouse at night, purple neon
casino   → high-end casino floor, golden chandeliers, noir
tavern   → rustic fantasy tavern, warm firelight
arena    → gladiatorial arena, stone walls, torches
...
```

### `generate_all_scene_backgrounds(scenes, force)`
Batch-generate backgrounds for all 9 game scenes. Skips existing unless `force=True`.
Intended for the nightly `scene-backgrounds` scheduler task.

### `list_comfyui_workflows()`
Return JSON list of available workflow names.

---

## A++ Tuning Engine

`engine/asset_studio/tuning_engine.py`

### Benchmarking

The tuning engine runs systematic quality benchmarks:
- **9 samples per workflow** (3 seeds × 3 prompts from the benchmark set)
- **VL scoring** via Qwen3-VL (loaded via LMStudio): rates each image 0.0–1.0
- **Metric storage** in Nexus under category `performance`
- **Trend tracking** across runs — detects quality regression

```python
from engine.asset_studio.tuning_engine import get_tuning_engine

engine = get_tuning_engine()

# Run a full benchmark for a workflow
results = engine.benchmark_workflow("portrait_hires")
# → {"workflow": "portrait_hires", "mean_score": 0.87, "samples": [...]}

# Get quality trend
trend = engine.get_quality_trend("portrait_hires", last_n=10)
```

### Auto-Tuner

The auto-tuner state machine tries adjacent parameter settings when quality drops:

```
1. Generate 9 samples with current settings → score
2. If mean_score < threshold (0.75 default):
   - Try: steps ± 2, cfg ± 0.5, sampler variants
   - Score each candidate
   - Keep best-performing settings
   - Store decision in Nexus
3. Re-benchmark with new settings
4. Repeat up to max_iterations (default: 5)
```

Proven profiles are locked in `PROVEN_PROFILES` dict and used as baselines.

### Proven Profiles

**portrait_hires**
```yaml
sampler: euler
scheduler: exponential
cfg: 1.0
steps: 20
```

**video_wan_t2v**
```yaml
sampler: euler
scheduler: simple
cfg: 1.0
steps: 6
shift: 5.0
fps: 16
frame_count: 49
```

---

## Scene Asset Injection

When `generate_scene_image` runs successfully:

1. ComfyUI generates the image to its output folder
2. The skill copies the file to `content/scenes/{scene}/static/img/{filename}.png`
3. Returns `/scenes/{scene}/static/img/{filename}.png` — immediately serveable by Flask

### "Inject to Scene" Flow

In the Asset Studio UI (`/asset_studio` route on the hub):
1. Select workflow + enter prompt
2. Click **Generate**
3. When complete, click **Inject to [scene]** button
4. The scene's background or overlay updates via Socket.IO `scene_asset_updated` event

---

## Scheduler Integration

Two scheduled tasks manage automated asset generation:

| Task | Schedule | Description |
|------|----------|-------------|
| `scene-backgrounds` | Nightly 02:00 | Generate backgrounds for all 9 scenes (skip existing) |
| `benchmark-workflows` | Weekly Sunday 03:00 | Full benchmark run + auto-tune cycle |

Add to scheduler:
```python
from engine.nexus.scheduler_daemon import get_scheduler
scheduler = get_scheduler()
scheduler.schedule("scene-backgrounds", cron="0 2 * * *")
scheduler.schedule("benchmark-workflows", cron="0 3 * * 0")
```

---

## Configuration

All asset studio settings live under `asset_studio` in `config/default.yaml`:

```yaml
asset_studio:
  enabled: true
  comfyui_url: "http://localhost:8188"
  output_dir: "content/simulation/media/images"
  video_output_dir: "content/simulation/media/video"
  benchmark:
    enabled: true
    score_threshold: 0.75
    samples_per_workflow: 9
    max_tune_iterations: 5
  wan_models:
    high: "wan22EnhancedNSFWSVICamera_nsfwFASTMOVEV2Q4KMH.gguf"
    low: "wan22EnhancedNSFWSVICamera_nsfwFASTMOVEV2Q4KML.gguf"
    clip: "nsfwWanUMT5XXLGGUF_q5AndQ4KM.gguf"
  t2v_white_image: "D:/ComfyUI/input/white.png"
```

---

## Testing

```bash
# All asset studio tests (145 tests)
python -m pytest tests/test_asset_studio_workflows.py -v

# Skills tests
python -m pytest tests/test_comfyui_skills.py -v

# Smart runner (auto-detects changed files)
python scripts/smart_test.py --domain comfyui
```

### Test Files

| File | Tests | Covers |
|------|-------|--------|
| `tests/test_asset_studio_workflows.py` | 145 | All 15 workflow variants, registry, params |
| `tests/test_comfyui_skills.py` | 38 | All 4 skills including generate_scene_image |

---

## Common Issues

**ComfyUI not running**
All skills return error strings (never raise) when ComfyUI is offline. Check `http://localhost:8188` is up.

**White.png missing for T2V**
Create: `D:\ComfyUI\input\white.png` (512×512 pure white PNG). Without it, T2V workflows will fail to load the start image.

**GGUF models not loading**
Ensure models are in `D:\ComfyUI\models\unet\` and `D:\ComfyUI\models\clip\`. Check ComfyUI console for load errors.

**VL scoring returns None**
Qwen3-VL must be loaded in LMStudio. Check `http://localhost:1234/api/v1/models` — the model ID must contain `qwen` and `vl`.
