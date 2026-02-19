# Virtual Companion Simulation System

A complete virtual companion system with character management, phone interface, and memory systems.

## 🎮 Features

- **Character System**: Create and manage virtual characters with personalities, traits, and states
- **RAG Memory**: Semantic memory storage and retrieval using ChromaDB
- **Phone Interface**: Realistic Android phone simulation with messaging, calls, and apps
- **Dashboard**: Streamlit-based management interface
- **Personality Templates**: Pre-built personalities (Playful, Sweet, Confident, etc.)
- **Role System**: Different relationship scenarios (Girlfriend, FWB, etc.)

## 📁 Structure

```
simulation/
├── database/
│   ├── db.py                    # SQLite database
│   └── rag.py                   # ChromaDB RAG memory
├── character_system/
│   ├── character.py             # Character class
│   ├── personality.py           # Personality system
│   └── role.py                  # Role templates
├── scenes/
│   ├── phone/                   # Phone scene
│   │   ├── phone_scene.py       # Flask server
│   │   ├── templates/           # HTML templates
│   │   └── static/              # CSS/JS assets
│   └── dashboard/
│       └── dashboard_v2.py      # Streamlit dashboard
├── requirements.txt
├── test_system.py
└── README.md
```

## 🚀 Quick Start

### 1. Install Dependencies

```bash
pip install -r simulation/requirements.txt
```

### 2. Test System

```bash
python simulation/test_system.py
```

This will:
- Initialize the database
- Create default personalities and roles
- Test all systems
- Create a test character

### 3. Launch Dashboard

```bash
streamlit run simulation/scenes/dashboard/dashboard_v2.py
```

The dashboard allows you to:
- Create and manage characters
- Browse personalities and roles
- View memories
- Manage system settings

### 4. Launch Phone Scene

```bash
python simulation/scenes/phone/phone_scene.py
```

Then open your browser to `http://localhost:5555` to interact with the phone interface.

## 📱 Phone Scene

The phone interface simulates a realistic Android phone with:
- **Messages**: Text conversations with typing indicators
- **Phone**: Voice and video call support
- **Gallery**: Photo management
- **Real-time**: WebSocket-based live updates

## 👤 Character System

### Creating a Character

```python
from simulation.character_system.character import Character
from simulation.character_system.personality import Personality

# Get personality
pers_mgr = Personality()
playful = pers_mgr.get_by_name("Playful Girlfriend")

# Create character
char = Character.create(
    name="Emma",
    personality_id=playful['id'],
    age=24,
    sex="female",
    hair_color="blonde",
    eye_color="blue",
    tags=["girlfriend", "playful"]
)
```

### Managing State

```python
# Update mood and relationship
char.set_mood("happy")
char.adjust_relationship(0.1)  # Increase by 10%

# Get current state
print(f"Mood: {char.mood}")
print(f"Relationship: {char.relationship_level:.0%}")
```

### Adding Memories

```python
# Add a memory
char.add_memory(
    "We had our first date at the Italian restaurant",
    importance=0.9
)

# Query memories
results = char.query_memories("tell me about our date")
```

## 🎭 Personalities

Built-in personalities:
- **Playful Girlfriend**: Fun, teasing, affectionate
- **Sweet Girlfriend**: Caring, nurturing, romantic
- **Confident Girlfriend**: Assertive, independent
- **Shy Girlfriend**: Reserved, gentle, gradually opens up
- **Adventurous Girlfriend**: Spontaneous, exciting
- **Intellectual Girlfriend**: Thoughtful, deep conversations
- **Submissive Girlfriend**: Pleasing, obedient
- **Dominant Girlfriend**: Commanding, in control

## 🎬 Roles

Built-in roles:
- **Girlfriend**: Standard romantic relationship
- **Long Distance Girlfriend**: Separated by distance
- **New Girlfriend**: Just started dating
- **Friends With Benefits**: Casual relationship
- **Ex Girlfriend**: Past relationship
- **Secret Affair**: Hidden relationship
- And more...

## 💾 Database

The system uses:
- **SQLite**: Main database for character data, conversations, etc.
- **ChromaDB**: Vector database for RAG memory system

Data is stored in:
- `simulation/simulation.db` (SQLite)
- `simulation/chroma_db/` (ChromaDB)

## 🔧 API Integration

### LM Studio Integration

To integrate with LM Studio for AI responses, modify `phone_scene.py`:

```python
def _generate_response(self, user_message: str) -> str:
    # Get context and system prompt
    context = self.active_character.build_context(user_message)
    system_prompt = self.active_character.get_system_prompt()
    
    # Call LM Studio API
    response = requests.post("http://localhost:1234/v1/chat/completions", json={
        "messages": [
            {"role": "system", "content": system_prompt + "\n\n" + context},
            {"role": "user", "content": user_message}
        ]
    })
    
    return response.json()["choices"][0]["message"]["content"]
```

## 📊 Dashboard Features

- **Character Management**: Create, edit, delete characters
- **Memory Browser**: View and search character memories
- **Personality Editor**: Create custom personalities
- **Role Editor**: Define custom relationship scenarios
- **Stats Dashboard**: View system statistics
- **Deploy Tools**: Launch phone scenes

## 🎯 Next Steps

1. **Integrate AI**: Connect to LM Studio for intelligent responses
2. **Add Voice**: Integrate CosyVoice for TTS
3. **Add Vision**: Generate character images with ComfyUI
4. **Video Calls**: Implement real-time video generation
5. **Autonomous Behavior**: Make characters initiate conversations

## 🐛 Troubleshooting

### Database Issues
```bash
# Reset database (deletes all data)
rm simulation/simulation.db
rm -rf simulation/chroma_db/
python simulation/test_system.py
```

### Port Already in Use
Change the port in `phone_scene.py` or when launching:
```python
scene = create_phone_scene(port=5556)
```

## 📝 License

Part of the CosyVoice Virtual Companion System.
