# ComfyUI Integration Guide

## Overview
Scarab of Ra integrates with a local ComfyUI server to generate game assets and atmospheric visuals on the fly. The system uses a standalone Python wrapper (`src/framework/comfyui_generator.py`) to manage websocket connections, prompt queuing, and image retrieval.

## Setup
1. Ensure ComfyUI is running (default: `http://127.0.0.1:8188` or `192.168.8.150:8188`).
2. Place your workflow JSON files in `workflows/`.
   - Recommended: `generate_Image.json` (API format).

## Usage (Python)
```python
from framework.comfyui_generator import ImageGenerator

# Initialize
gen = ImageGenerator(workflow_path="workflows/generate_Image.json", server="127.0.0.1:8188")

# Generate
images = gen.generate(
    positive_prompt="ancient egyptian tomb, glowing runes, unreal engine 5",
    negative_prompt="blurry, watermark"
)

# Save
saved_paths = gen.save_images(images, "output/directory")
print(f"Saved to {saved_paths}")
```

## Agent Integration
The `ImageGenAgent` (`src/agents/image_gen.py`) wraps this functionality for the AgentScope framework.
- Input: `Msg(content="a dark corridor")`
- Output: `Msg(content="path/to/image.png")`

## Troubleshooting
- **Connection Refused**: Check if ComfyUI is running and the IP/Port in `src/backend/app.py` matches.
- **Node Errors**: Ensure your workflow JSON uses standard node IDs or update `comfyui_generator.py` to match your specific custom nodes.
