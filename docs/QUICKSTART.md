# CosySim Quick-Start Guide

> Get up and running in under 10 minutes.

---

## 1. Prerequisites

| Requirement | Minimum |
|---|---|
| Python | 3.10+ |
| RAM | 8 GB (16 GB recommended) |
| GPU | NVIDIA RTX 2060 or better |
| LM Studio | 0.3.x+ with server enabled |
| ComfyUI | Optional (image / video generation) |

---

## 2. Installation

```bash
# 1. Clone
git clone https://github.com/yourusername/CosySim.git
cd CosySim

# 2. Install (editable mode)
pip install -e .

# 3. Optionally install the LM Studio Python SDK
pip install lmstudio
```

---

## 3. Configure

Copy `config/default.yaml` and edit to match your setup:

```yaml
lmstudio:
  host: localhost   # change if running on a separate machine
  port: 1234

comfyui:
  base_url: http://localhost:8188   # change if ComfyUI is remote
```

Or set environment variables instead:

```powershell
$env:COSYSIM_LMSTUDIO_HOST = "192.168.1.50"
$env:COSYSIM_LMSTUDIO_PORT = "1234"
$env:COSYSIM_COMFYUI_URL   = "http://192.168.1.50:8188"
```

---

## 4. Start LM Studio Server

```bash
lms server start
```

Verify it is running:

```bash
lms ps
```

---

## 5. Launch CosySim

```bash
# Central hub (Streamlit)
python launcher.py --mode hub

# Phone scene directly (Flask on port 5555)
python launcher.py --mode phone

# Admin panel (Streamlit on port 8501)
python launcher.py --mode admin
```

Open your browser:
- Hub: http://localhost:8500
- Phone Scene: http://localhost:5555
- Admin Panel: http://localhost:8501

---

## 6. Create Your First Character

### Via Admin Panel

1. Navigate to **Character Manager**
2. Click **Create New Character**
3. Fill in name, description, and personality sliders
4. Click **Save**

### Via Python

```python
from content.simulation.database.db import Database
from content.simulation.character_system.character import Character

db = Database()
char = Character.create(
    name="Aria",
    age=25,
    personality_type="friendly",
    mood="happy",
    db=db,
)
print(f"Created: {char.id}")
```

---

## 7. Chat with a Character Using the Agent

```python
from content.simulation.database.db import Database
from content.simulation.character_system.character import Character
from engine.agents import CharacterAgent

db   = Database()
char = Character.load("your-character-id", db)

agent = CharacterAgent(char, db=db)
reply = agent.reply("Hello! How are you today?")
print(reply)
```

---

## 8. Run a Skill Manually

```python
from engine.skills import get_skills

# List all skills in the 'memory' pack
tools = get_skills("memory")
for t in tools:
    print(t.__name__)

# Call a skill directly
from engine.skills.builtin.memory_skills import search_memory
result = search_memory("beach holiday", character_id="your-character-id")
print(result)
```

---

## 9. Explore the Admin Panel

The admin panel (http://localhost:8501) provides:

- **Dashboard** — asset counts, system health
- **Character Manager** — create/edit characters
- **LM Studio** — live model management (load / unload)
- **Event Chains** — trace every LLM call and tool invocation
- **Log Viewer** — application logs

---

## 10. Next Steps

| Goal | Document |
|---|---|
| Add custom skills | [docs/SKILLS.md](SKILLS.md) |
| Full HTTP API reference | [docs/API.md](API.md) |
| Project structure | [docs/STRUCTURE_GUIDE.md](STRUCTURE_GUIDE.md) |
| ComfyUI integration | [docs/COMFYUI.md](COMFYUI.md) |
