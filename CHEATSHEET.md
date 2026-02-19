# 🎯 CosySim Quick Reference Cheat Sheet

## 📊 The 3-Layer Model

```
┌─────────────────────────────────────────────────┐
│  ENGINE/      ← Tech layer (stable)             │
│  CONTENT/     ← Your game (customize)           │  
│  CONFIG/      ← Settings (tune)                 │
└─────────────────────────────────────────────────┘
```

---

## 🗂️ Directory Quick Reference

| Path | What It Is | Modify? |
|------|-----------|---------|
| `engine/` | Core tech systems | ❌ Rarely |
| `engine/assets/` | Asset management | ❌ No |
| `engine/config.py` | Config loader | ❌ No |
| `engine/scenes/` | Scene framework | ❌ No |
| `engine/tts/` | Text-to-speech | ❌ No |
| **`content/`** | **Your game** | ✅ **Yes!** |
| **`content/scenes/`** | **5 scenes** | ✅ **Customize** |
| **`content/simulation/`** | **Gameplay logic** | ✅ **Extend** |
| `content/simulation/character_system/` | Characters | ✅ Add more |
| `content/simulation/database/` | Storage | ⚠️ Careful |
| `config/` | YAML settings | ✅ Tune |
| `docs/` | Documentation | 📖 Read |
| `tests/` | Tests | 🧪 Run |

---

## 🎮 The 5 Scenes

| Scene | Port | Path | Purpose |
|-------|------|------|---------|
| **Hub** | 8500 | `content/scenes/hub/` | Central launcher + tutorial |
| **Phone** | 5555 | `content/scenes/phone/` | Messages, calls, gallery |
| **Bedroom** | 5003 | `content/scenes/bedroom/` | Interactive environment |
| **Admin** | 8502 | `content/scenes/admin/` | System management |
| **Dashboard** | 8501 | `content/scenes/dashboard/` | Metrics overview |

---

## 👥 The 5 Characters

| Name | Age | Personality | Hair |
|------|-----|-------------|------|
| Sophia | 25 | Bubbly, energetic, playful | Short blonde |
| Emma | 22 | Sweet, caring, gentle | Long brown |
| Isabella | 27 | Confident, flirty, mysterious | Dark wavy |
| Olivia | 26 | Witty, sarcastic, loyal | Red |
| Mia | 23 | Shy, thoughtful, creative | Black |

---

## 🚀 Common Commands

```bash
# Launch system
python launcher.py

# Launch specific scene
python -m content.scenes.phone.phone_scene

# Run tests
pytest tests/

# Check config
python -c "from engine.config import get_config; print(get_config()._config)"
```

---

## 🔧 Quick Edits

### Change Port
```yaml
# config/default.yaml
scenes:
  phone:
    port: 5555  ← Change this
```

### Add Character
```python
# content/simulation/character_system/character.py
new_char = Character(
    name="Alice",
    age=24,
    personality=Personality(traits=["smart", "funny"])
)
```

### Register Asset
```python
from engine.assets import AssetManager
am = AssetManager()
asset_id = am.register_asset(type="image", path="photo.jpg")
```

---

## 📁 File Naming Patterns

| Pattern | Example | Purpose |
|---------|---------|---------|
| `{scene}_scene.py` | `phone_scene.py` | Main scene file |
| `{feature}.py` | `messages.py` | Feature module |
| `{scene}_ui.html` | `phone_ui.html` | HTML template |
| `{scene}.css` | `phone.css` | Styling |
| `{scene}.js` | `phone.js` | JavaScript |

---

## 🔄 Typical Data Flow

```
User Action
    ↓
Frontend (HTML/CSS/JS)
    ↓
Flask Route (scene.py)
    ↓
Database (db.py) + RAG (rag.py)
    ↓
Character System (character.py)
    ↓
TTS (engine/tts/)
    ↓
Asset Manager (engine/assets/)
    ↓
Response to User
```

---

## 💾 Database Tables

| Table | What It Stores |
|-------|----------------|
| `messages` | Chat history |
| `characters` | Character data |
| `assets` | Media registry |
| `scenes` | Scene state |
| `relationships` | Character relationships |

---

## 🎨 Asset Types

| Type | Example | Used For |
|------|---------|----------|
| `image` | JPG, PNG | Photos, avatars |
| `audio` | WAV, MP3 | Voice messages |
| `video` | MP4 | Video calls |
| `text` | TXT, MD | Messages |
| `document` | PDF, DOCX | Files |

---

## ⚙️ Config Keys

```yaml
database:
  sqlite_path: "conversation_history.db"
  chroma_path: "content/simulation/chroma_db"

scenes:
  hub:
    port: 8500
  phone:
    port: 5555
  bedroom:
    port: 5003

tts:
  device: "cuda"  # or "cpu"
  model: "CosyVoice2-0.5B"

llm:
  provider: "openai"  # or "lmstudio"
  base_url: "http://localhost:1234/v1"
```

---

## 🔍 Finding Things Fast

**Need to find...?**

| What | Look Here |
|------|-----------|
| Scene code | `content/scenes/{scene}/*.py` |
| Scene UI | `content/scenes/{scene}/templates/*.html` |
| Scene style | `content/scenes/{scene}/static/css/*.css` |
| Scene JS | `content/scenes/{scene}/static/js/*.js` |
| Character logic | `content/simulation/character_system/` |
| Database code | `content/simulation/database/` |
| Asset code | `engine/assets/` |
| Config | `config/default.yaml` |
| Docs | `docs/*.md` |
| Tests | `tests/integration/*.py` |

---

## 🚨 Common Issues

| Problem | Solution |
|---------|----------|
| Port already in use | Change port in `config/default.yaml` |
| Module not found | `pip install -e .` |
| Symlink broken | Re-create or copy `pretrained_models/` |
| Config not loading | Check YAML syntax |
| Scene won't start | Check port conflicts, logs |

---

## 🎯 Where to Start

**Beginner:**
1. Read `README.md`
2. Read `QUICK_START.md`
3. Run `python launcher.py`
4. Explore the phone scene

**Developer:**
1. Read `docs/STRUCTURE_GUIDE.md` (this file!)
2. Read `docs/DEVELOPMENT.md`
3. Browse `content/scenes/phone/` as example
4. Modify or create your own scene

**Advanced:**
1. Read `docs/ARCHITECTURE.md`
2. Read `docs/API_REFERENCE.md`
3. Explore `engine/` systems
4. Extend framework

---

## 📚 Documentation Map

| File | Size | Purpose |
|------|------|---------|
| `README.md` | 9KB | Project overview |
| `QUICK_START.md` | Small | 5-min setup |
| `STRUCTURE_GUIDE.md` | 13KB | This guide! |
| `docs/ARCHITECTURE.md` | 135KB | Full system design |
| `docs/DEVELOPMENT.md` | 138KB | Developer guide |
| `docs/API_REFERENCE.md` | Large | API docs |
| `MIGRATION.md` | Med | CosyVoice → CosySim |
| `CLEANUP_SUMMARY.md` | 8KB | What changed |
| `DEPLOYMENT.md` | Med | Production setup |

---

## 🎁 What You Get

✅ 5 interactive scenes  
✅ 5 AI characters  
✅ Voice/video calls  
✅ Asset management  
✅ Character memory (RAG)  
✅ Admin panel  
✅ Testing framework  
✅ CI/CD pipeline  
✅ Docker deployment  
✅ Complete documentation  

---

## 💡 Key Principles

1. **Separation:** ENGINE (tech) vs CONTENT (game) vs CONFIG (settings)
2. **Independence:** Each scene can run standalone
3. **Centralization:** All assets through AssetManager
4. **Configuration:** Change behavior without code
5. **Documentation:** Everything is documented

---

## 🤝 Getting Help

1. Check `STRUCTURE_GUIDE.md` (this!)
2. Check `docs/ARCHITECTURE.md`
3. Check `docs/DEVELOPMENT.md`
4. Check `docs/API_REFERENCE.md`
5. Read the source code (it's well-commented!)

---

**Happy developing! 🚀**
