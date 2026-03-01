# CosySim Content Guide

> ContentEngine, ContentGate, adult profiles, NLM seeding.
> Added in v0.68 "Dark Renaissance".

## Overview

The ContentEngine manages dynamic content pools per scene — dialogue snippets,
story events, ambient descriptions. ContentGate enforces adult content profiles
per player. All content is stored in and generated from Nexus + NLM.

## ContentEngine (`engine/content/content_engine.py`)

```python
from engine.content.content_engine import get_content_engine
engine = get_content_engine()
item = engine.get("bedroom", "scenario")   # random scenario from pool
engine.add("bedroom", "scenario", "Victoria traces a finger along the bar...")
```

## ContentGate (`engine/content/content_gate.py`)

```python
from engine.content.content_gate import get_content_gate
gate = get_content_gate()
gate.set_profile("player1", sexual=2, violence=1, language=3)
allowed = gate.check("player1", "sexual", 3)   # False — above limit
```

## Intensity Levels

| Level | Label | Description |
|-------|-------|-------------|
| 0 | Clean | No adult content |
| 1 | Mild | Suggestive, mild language |
| 2 | Mature | Explicit suggestion, moderate violence |
| 3 | Explicit | Full explicit content |

## NLM Content Seeding

Seed all scene pools via TeacherPipeline:
```bash
python -m engine.content.seed_all   # seeds all 10 content scenes
```
Or per scene:
```python
from engine.nexus.teacher_pipeline import TeacherPipeline
tp = TeacherPipeline()
tp.generate_content("bedroom", content_type="scenarios", count=20)
```
