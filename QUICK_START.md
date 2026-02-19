# 🎮 Virtual Companion - Quick Start Guide

## 🚀 Installation (5 minutes)

### Step 1: Install Dependencies
```bash
pip install chromadb sentence-transformers flask flask-socketio python-socketio streamlit
```

Or use the requirements file:
```bash
pip install -r simulation/requirements.txt
```

### Step 2: Initialize & Test
```bash
python simulation/test_system.py
```

This will:
- Create the database
- Initialize 8 personality templates
- Initialize 12 role templates
- Create test characters
- Test all systems

Expected output:
```
🎉 ALL TESTS PASSED!
✅ Database: Working
✅ RAG Memory: Working
✅ Personalities: Working (9 personalities)
✅ Roles: Working (12 roles)
✅ Character System: Working (2 characters)
```

## 🎯 Using the System

### Option 1: Launch Dashboard (Recommended for First Time)

```bash
streamlit run simulation/scenes/dashboard/dashboard_v2.py
```

Opens at: `http://localhost:8501`

**What you can do:**
1. **Create Characters**:
   - Go to "👤 Characters" tab
   - Click "Create Character"
   - Fill in name, age, appearance
   - Select a personality (Playful, Sweet, Confident, etc.)
   - Add tags (girlfriend, playful, romantic)
   - Click "Create Character"

2. **Browse Personalities**:
   - Go to "🎭 Personalities" tab
   - View 8 pre-made personalities
   - Create custom personalities

3. **Browse Roles**:
   - Go to "🎬 Roles" tab
   - View 12 relationship scenarios
   - Create custom roles

4. **View Memories**:
   - Go to "💾 Memories" tab
   - Select a character
   - Browse recent/important memories
   - Search semantically

### Option 2: Launch Phone Scene

```bash
python simulation/scenes/phone/phone_scene.py
```

Opens at: `http://localhost:5555`

**What you can do:**
1. **Select Character**: Choose from dropdown in control panel
2. **Send Messages**: Open Messages app, type and send
3. **Make Calls**: Open Phone app, initiate voice/video call
4. **View Gallery**: Open Gallery app (placeholder)
5. **Real-time**: Messages appear instantly via WebSocket

### Option 3: Use Python API

```python
from simulation.character_system.character import Character
from simulation.character_system.personality import Personality

# Get a personality
pers_mgr = Personality()
playful = pers_mgr.get_by_name("Playful Girlfriend")

# Create a character
char = Character.create(
    name="Luna",
    personality_id=playful['id'],
    age=24,
    sex="female",
    hair_color="brunette",
    eye_color="green",
    tags=["girlfriend", "playful"]
)

# Add a memory
char.add_memory(
    "We met at a coffee shop on a rainy day",
    importance=0.9
)

# Start conversation
char.start_conversation()
char.add_message("user", "Hey, how are you?")
char.add_message("assistant", "I'm great! Just thinking about you 😊")

# Update state
char.set_mood("happy")
char.adjust_relationship(0.1)

print(f"Mood: {char.mood}")
print(f"Relationship: {char.relationship_level:.0%}")
```

## 🎨 Character Creation Examples

### Example 1: Playful Girlfriend
```
Name: Emma
Age: 24
Sex: female
Hair: blonde
Eyes: blue
Height: 5'6"
Body Type: athletic
Personality: Playful Girlfriend
Tags: girlfriend, playful, romantic, fun
```

### Example 2: Shy Girlfriend
```
Name: Yuki
Age: 22
Sex: female
Hair: black
Eyes: brown
Height: 5'4"
Body Type: petite
Personality: Shy Girlfriend
Tags: girlfriend, shy, sweet, caring
```

### Example 3: Confident Girlfriend
```
Name: Sophia
Age: 26
Sex: female
Hair: red
Eyes: green
Height: 5'8"
Body Type: fit
Personality: Confident Girlfriend
Tags: girlfriend, confident, independent, ambitious
```

## 📱 Phone Scene Features

### Messages App
- Send/receive text messages
- Typing indicators
- Message bubbles (blue for you, gray for her)
- Real-time updates
- Message history

### Phone App
- Voice call button
- Video call button
- Caller interface
- Call controls (mute, speaker, end)

### Gallery App
- Photo grid (placeholder)
- Ready for generated images

### Home Screen
- Live clock
- App icons with badges
- Android-style navigation
- Status bar

## 🧠 Memory System

The RAG memory system automatically:
- Stores all conversations
- Enables semantic search
- Builds context for responses
- Scores importance
- Retrieves relevant memories

Example queries:
```python
# Recent memories
recent = char.get_recent_memories(n_results=10)

# Important memories
important = char.get_important_memories(min_importance=0.7)

# Semantic search
results = char.query_memories("tell me about our first date")

# Build context
context = char.build_context("What do you remember about us?")
```

## 🔄 State Management

Characters have dynamic states:
- **Mood**: neutral, happy, sad, playful, romantic, horny, angry
- **Energy**: 0.0 to 1.0
- **Relationship Level**: 0.0 to 1.0 (0% to 100%)
- **Arousal**: 0.0 to 1.0

Update states:
```python
char.set_mood("romantic")
char.adjust_relationship(0.05)  # +5%
char.adjust_arousal(0.1)  # +10%
char.adjust_energy(-0.2)  # -20%
```

## 🎭 Available Personalities

1. **Playful Girlfriend**: Fun, teasing, affectionate (openness: 70%)
2. **Sweet Girlfriend**: Caring, nurturing, romantic (openness: 40%)
3. **Confident Girlfriend**: Assertive, independent (openness: 80%)
4. **Shy Girlfriend**: Reserved, gentle, slowly opens up (openness: 30%)
5. **Adventurous Girlfriend**: Spontaneous, exciting (openness: 75%)
6. **Intellectual Girlfriend**: Thoughtful, deep conversations (openness: 50%)
7. **Submissive Girlfriend**: Pleasing, obedient, devoted (openness: 80%)
8. **Dominant Girlfriend**: Commanding, in control (openness: 85%)

## 🎬 Available Roles

1. **Girlfriend**: Standard romantic relationship
2. **Long Distance Girlfriend**: Separated by distance
3. **New Girlfriend**: Just started dating
4. **Friends With Benefits**: Casual relationship
5. **Ex Girlfriend**: Past relationship
6. **Secret Affair**: Hidden relationship
7. **Flirty Roommate**: Living together with tension
8. **Office Romance**: Coworker relationship
9. **Childhood Friend Romance**: Friends turned romantic
10. **Sugar Baby**: Arrangement relationship
11. **Virtual Only Girlfriend**: Online relationship
12. **Celebrity/Influencer**: Famous partner

## 🔧 Integration Guide

### LM Studio Integration
Add to `phone_scene.py`:
```python
import requests

def _generate_response(self, user_message: str) -> str:
    context = self.active_character.build_context(user_message)
    system_prompt = self.active_character.get_system_prompt()
    
    response = requests.post("http://localhost:1234/v1/chat/completions", json={
        "messages": [
            {"role": "system", "content": f"{system_prompt}\n\n{context}"},
            {"role": "user", "content": user_message}
        ],
        "temperature": 0.8,
        "max_tokens": 200
    })
    
    return response.json()["choices"][0]["message"]["content"]
```

## 📊 Database Files

Created automatically:
- `simulation/simulation.db` - SQLite database
- `simulation/chroma_db/` - ChromaDB vector store

## 🎉 You're Ready!

Start with the dashboard to create your first character, then launch the phone scene to interact with them!

```bash
# Dashboard
streamlit run simulation/scenes/dashboard/dashboard_v2.py

# Phone Scene (in another terminal)
python simulation/scenes/phone/phone_scene.py
```

Enjoy! 🚀
