# Animation Creation Guide

## Overview

CosySim's animation system uses a **procedural bone-based** approach for character
animation. Characters are built from Three.js geometry and animated by rotating
named bone groups. This guide covers creating poses, animations, interaction
chains, and importing external models.

## Architecture

```
YAML Configs (source of truth)
├── animations.yaml      → State machine, expressions, procedural params
├── interactions.yaml    → Location+action mappings, chains, transitions
├── characters.yaml      → Body dimensions, materials, colors
├── outfits.yaml         → Outfit definitions, layer mappings
└── models/catalog.yaml  → External model registry, bone mapping

JSON Data (runtime)
└── data/penthouse/animations/poses.json  → Pose presets (joint rotations)

JavaScript (frontend)
├── penthouse_anim.js         → State machine, AnimState, AnimManager
├── character_models.js       → Procedural character builder
├── character_bridge.js       → Glue: socket events → 3D scene
├── penthouse_anim_studio.js  → UI: pose editor, library, sequencer
└── penthouse_customizer.js   → UI: outfit/color editor

Python (backend)
├── engine/animation/           → Reusable framework
│   ├── animation_config.py     → YAML config loader
│   ├── pose_library.py         → Pose CRUD manager
│   └── model_catalog.py        → Model registry & scanner
├── penthouse_skills.py         → MCP animation skills
└── penthouse_anim_studio_mixin.py → Backend pose CRUD routes
```

## Creating Poses

### Using the Animation Studio UI

1. Open the penthouse scene in your browser
2. Click the **Animation Studio** button in the sidebar
3. Use the **Poses** tab to manipulate bone sliders
4. Click **Save to Library** to persist the pose

### Using poses.json Directly

Add entries to `data/penthouse/animations/poses.json`:

```json
{
  "my-custom-pose": {
    "name": "My Custom Pose",
    "builtin": false,
    "category": "custom",
    "location": "any",
    "joints": {
      "head":      { "x": 0,  "y": 0,  "z": 0 },
      "torso":     { "x": 0,  "y": 0,  "z": 0 },
      "arm_l":     { "x": 0,  "y": 0,  "z": -30 },
      "arm_r":     { "x": 0,  "y": 0,  "z": 30 },
      "forearm_l": { "x": -45, "y": 0,  "z": 0 },
      "forearm_r": { "x": -45, "y": 0,  "z": 0 },
      "hand_l":    { "x": 0,  "y": 0,  "z": 0 },
      "hand_r":    { "x": 0,  "y": 0,  "z": 0 },
      "thigh_l":   { "x": 0,  "y": 0,  "z": 0 },
      "thigh_r":   { "x": 0,  "y": 0,  "z": 0 },
      "shin_l":    { "x": 0,  "y": 0,  "z": 0 },
      "shin_r":    { "x": 0,  "y": 0,  "z": 0 }
    },
    "joint_count": 12,
    "created_at": "2026-01-01T00:00:00"
  }
}
```

### Joint Rotation Reference

All values are in **degrees**. The animation system converts to radians internally.

| Joint | X (pitch) | Y (yaw) | Z (roll) |
|-------|-----------|---------|----------|
| head | Nod up(-)/down(+) | Turn left(-)/right(+) | Tilt left(-)/right(+) |
| torso | Lean forward(+)/back(-) | Twist left(-)/right(+) | Side lean left(-)/right(+) |
| arm_l | Raise forward(-)/back(+) | Rotate in/out | Raise sideways(-) |
| arm_r | Raise forward(-)/back(+) | Rotate in/out | Raise sideways(+) |
| forearm_l | Bend elbow(-) | Twist | — |
| forearm_r | Bend elbow(-) | Twist | — |
| hand_l | Flex wrist | Twist | Side flex |
| hand_r | Flex wrist | Twist | Side flex |
| thigh_l | Raise forward(-)/back(+) | Rotate in/out | Spread(-) |
| thigh_r | Raise forward(-)/back(+) | Rotate in/out | Spread(+) |
| shin_l | Bend knee(+) | — | — |
| shin_r | Bend knee(+) | — | — |

### Pose Categories

| Category | Purpose |
|----------|---------|
| `body_position` | Standing, sitting, lying, kneeling poses |
| `furniture_bed` | Bed-specific poses |
| `furniture_couch` | Couch-specific poses |
| `furniture_bath` | Bath/tub poses |
| `intimate` | Romantic/adult poses |
| `dance` | Dancing poses |
| `action` | Gestural/activity poses |
| `emotion` | Emotional expression poses |
| `custom` | User-created poses |

## Creating Animation States

Animation states are defined in `penthouse_anim.js` in the `ANIM_STATES` dict.
Each state has: `label`, `priority`, and optional `loopSpeed`.

### Adding a New State

1. Add to `ANIM_STATES`:
```javascript
my_state: { label: 'My State', priority: 2 },
```

2. Add blend duration in `BLEND_DURATIONS`:
```javascript
'idle->my_state': 0.6,
'my_state->idle': 0.8,
```

3. Add procedural animation in `_applyAnimState()`:
```javascript
case 'my_state': {
  const dims = model.dims || {};
  // Manipulate bone rotations, positions, scales
  model.headGroup.rotation.x = -0.1 * t;
  model.bodyGroup.rotation.x = 0.15 * t;
  break;
}
```

4. Add keyword mapping in `inferAnimState()`:
```javascript
if (act.includes('my action')) return 'my_state';
```

5. Add to YAML config (`animations.yaml` → `state_categories`):
```yaml
my_category:
  priority: 2
  states: [my_state]
```

### State Priorities

| Priority | Category | Examples |
|----------|----------|----------|
| 0 | Idle | idle |
| 1 | Movement | walk, run, crawl |
| 2 | Position | sit, lie, stand variations |
| 3 | Ground/Furniture | kneel, all_fours, drink, bathe |
| 4 | Action | dance, undress, massage, flirt |
| 5 | Intimate | embrace, kiss, ride, doggy |
| 6 | Special | pose (manual override) |

## Creating Interaction Chains

Interaction chains are multi-step animation sequences defined in
`config/penthouse/interactions.yaml`.

### Adding a New Chain

```yaml
chains:
  my_chain:
    steps:
      - action: "flirt"
        duration: 3.0
      - action: "dance_sway"
        duration: 4.0
      - action: "embrace"
        duration: 3.0
        paired: true
```

Then add the frontend handler in `penthouse.js` `_onInteractionChain()`.

### Using Chains via MCP Skill

```python
# From an agent/skill
penthouse_interaction_chain(
    character_id="lola",
    chain="seduction",
    partner_id="viktor"
)
```

## Paired Animations

Paired animations involve two characters. Configuration is in
`animations.yaml` → `paired_animations`.

### Configuration

```yaml
paired_animations:
  my_paired:
    roles: [initiator, receiver]
    min_distance: 0.3
    max_distance: 0.8
    facing: towards
    sync: true
    expression_initiator: happy
    expression_receiver: aroused
```

### Triggering via Skill

```python
penthouse_paired_animation(
    character_id_1="lola",
    character_id_2="viktor",
    animation="embrace"
)
```

## Importing External Models

### Supported Formats
- `.glb` — GL Binary (recommended)
- `.gltf` — GL Transmission Format
- `.vrm` — VRM avatar format

### Adding Models to Catalog

1. Place model file in a source directory (e.g. `C:/Files/Models/avatat_models/`)
2. Add entry to `config/penthouse/models/catalog.yaml`:

```yaml
catalog:
  my_model:
    file: "my_model.glb"
    source_dir: "C:/Files/Models/avatat_models"
    size_mb: 15.0
    type: character
    gender: female
    description: "My custom character model"
    tags: [female, custom]
    has_skeleton: true
    has_animations: false
```

3. Or use the Python API to scan automatically:

```python
from engine.animation import ModelCatalog

catalog = ModelCatalog("config/penthouse/models/catalog.yaml")
catalog.scan_directory("C:/Files/Models/my_models")
```

### Skeleton Bone Mapping

External models use different bone naming conventions. The catalog includes
a `bone_mapping` section that maps common conventions (Mixamo, VRM) to our
internal bone names.

Add custom mappings as needed:

```yaml
bone_mapping:
  MyRig:Spine: spine
  MyRig:Head: head
  # etc.
```

## Expression System

Expressions are morph-like values applied to face geometry.

### Expression Values

| Parameter | Range | Description |
|-----------|-------|-------------|
| mouth_open | 0.0-1.0 | Jaw opening |
| smile | -1.0-1.0 | Smile (+) / frown (-) |
| brow_raise | -1.0-1.0 | Raise (+) / furrow (-) |
| eye_squint | 0.0-1.0 | Eye closing |
| blush | 0.0-1.0 | Face reddening |
| pupil_dilate | -0.5-1.0 | Pupil size change |

### Adding Expressions

In `config/penthouse/animations.yaml`:

```yaml
expressions:
  my_expression:
    label: "My Expression"
    mouth_open: 0.2
    smile: 0.5
    brow_raise: 0.1
    eye_squint: 0.0
    blush: 0.0
    pupil_dilate: 0.0
```

## API Reference

### MCP Skills (Agent-Callable)

| Skill | Description |
|-------|-------------|
| `penthouse_set_animation(character_id, state)` | Set animation state |
| `penthouse_set_expression(character_id, expression)` | Set facial expression |
| `penthouse_paired_animation(char1, char2, animation)` | Start paired animation |
| `penthouse_change_outfit(character_id, outfit)` | Change outfit with animation |
| `penthouse_interaction_chain(character_id, chain, partner_id)` | Multi-step sequence |
| `penthouse_list_animations()` | List all available states |

### REST API

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/api/config/animations` | GET | Animation YAML config |
| `/api/config/interactions` | GET | Interaction YAML config |
| `/api/config/models` | GET | Model catalog YAML |
| `/api/config/characters` | GET | Character YAML config |
| `/api/config/outfits` | GET | Outfit YAML config |
| `/api/config/all` | GET | All configs merged |
| `/api/anim/poses` | GET | All poses |
| `/api/anim/poses` | POST | Create/update pose |
| `/api/anim/poses/<id>` | DELETE | Delete pose |

### Socket.IO Events

| Event | Direction | Description |
|-------|-----------|-------------|
| `set_animation` | Server→Client | Set character animation |
| `set_expression` | Server→Client | Set character expression |
| `paired_animation` | Server→Client | Start paired animation |
| `outfit_change` | Server→Client | Change character outfit |
| `interaction_chain` | Server→Client | Start animation chain |
| `agent_action` | Server→Client | Agent action event |
| `character_speaking` | Server→Client | Character speech event |

## Python Framework

```python
from engine.animation import AnimationConfig, PoseLibrary, ModelCatalog

# Load configs
config = AnimationConfig("config/penthouse")

# Query interaction state
state, expr = config.get_interaction_state("bed", "cuddle")

# Manage poses
poses = PoseLibrary("data/penthouse/animations/poses.json")
print(poses.stats())

# Manage models
catalog = ModelCatalog("config/penthouse/models/catalog.yaml")
catalog.scan_all_sources()
print(catalog.stats())
```
