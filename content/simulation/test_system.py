"""
Test and Initialize Virtual Companion System
Run this to verify everything is working
"""
import sys
from pathlib import Path

# Add to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from simulation.database.db import Database
from simulation.database.rag import RAGMemory
from simulation.character_system.personality import Personality
from simulation.character_system.role import Role
from simulation.character_system.character import Character


def test_database():
    """Test database initialization"""
    print("\n" + "="*60)
    print("Testing Database System")
    print("="*60)
    
    db = Database()
    print("✅ Database initialized")
    
    # Test creating personality
    pers_id = db.create_personality(
        name="Test Personality",
        system_prompt="You are a test personality.",
        traits=["test", "friendly"],
        sexual_openness=0.5
    )
    print(f"✅ Created test personality: {pers_id}")
    
    # Test creating character
    char_id = db.create_character(
        name="Test Character",
        personality_id=pers_id,
        age=25,
        sex="female",
        tags=["test"]
    )
    print(f"✅ Created test character: {char_id}")
    
    # Test retrieving
    char = db.get_character(char_id)
    print(f"✅ Retrieved character: {char['name']}")
    
    return db, char_id


def test_rag():
    """Test RAG memory system"""
    print("\n" + "="*60)
    print("Testing RAG Memory System")
    print("="*60)
    
    rag = RAGMemory()
    print("✅ RAG system initialized")
    
    char_id = "test_char_001"
    
    # Add memories
    rag.add_memory(
        char_id,
        "We had a wonderful first date at the Italian restaurant.",
        importance=0.9
    )
    rag.add_memory(
        char_id,
        "You mentioned that you love hiking and nature.",
        importance=0.7
    )
    print("✅ Added test memories")
    
    # Query memories
    results = rag.query_memories(char_id, "tell me about our date", n_results=2)
    print(f"✅ Queried memories: {len(results)} results")
    
    for mem in results:
        print(f"   - {mem['content'][:50]}...")
    
    return rag


def test_personalities():
    """Test personality system"""
    print("\n" + "="*60)
    print("Testing Personality System")
    print("="*60)
    
    pers_mgr = Personality()
    print("✅ Personality manager initialized")
    
    # Initialize default personalities
    created = pers_mgr.initialize_defaults()
    print(f"✅ Initialized {len(created)} default personalities")
    
    # List all
    all_pers = pers_mgr.list_all()
    print(f"✅ Total personalities: {len(all_pers)}")
    
    for p in all_pers[:3]:
        print(f"   - {p['name']}")
    
    return pers_mgr


def test_roles():
    """Test role system"""
    print("\n" + "="*60)
    print("Testing Role System")
    print("="*60)
    
    role_mgr = Role()
    print("✅ Role manager initialized")
    
    # Initialize default roles
    created = role_mgr.initialize_defaults()
    print(f"✅ Initialized {len(created)} default roles")
    
    # List all
    all_roles = role_mgr.list_all()
    print(f"✅ Total roles: {len(all_roles)}")
    
    for r in all_roles[:3]:
        print(f"   - {r['name']}")
    
    return role_mgr


def test_character_system(db, pers_mgr):
    """Test character system"""
    print("\n" + "="*60)
    print("Testing Character System")
    print("="*60)
    
    # Get a personality
    playful = pers_mgr.get_by_name("Playful Girlfriend")
    if not playful:
        print("⚠️  Playful Girlfriend personality not found, creating...")
        pers_id = pers_mgr.create_from_template('playful_girlfriend')
        playful = pers_mgr.get(pers_id)
    
    # Create character
    char = Character.create(
        name="Emma",
        personality_id=playful['id'],
        age=24,
        sex="female",
        hair_color="blonde",
        eye_color="blue",
        height="5'6\"",
        body_type="athletic",
        tags=["girlfriend", "playful", "romantic"],
        db=db
    )
    print(f"✅ Created character: {char.name}")
    
    # Test memory
    char.add_memory("We met at a coffee shop downtown", importance=0.9)
    char.add_memory("You love hiking and the outdoors", importance=0.7)
    print(f"✅ Added memories")
    
    # Test conversation
    conv_id = char.start_conversation()
    char.add_message("user", "Hey, how are you?")
    char.add_message("assistant", "I'm great! Just thinking about you 😊")
    print(f"✅ Created conversation: {conv_id}")
    
    # Test state
    char.set_mood("happy")
    char.adjust_relationship(0.1)
    print(f"✅ Updated state - Mood: {char.mood}, Relationship: {char.relationship_level:.1%}")
    
    # Get system prompt
    prompt = char.get_system_prompt()
    print(f"✅ Generated system prompt ({len(prompt)} chars)")
    
    return char


def main():
    """Run all tests"""
    print("\n" + "="*60)
    print("🎮 VIRTUAL COMPANION SYSTEM - INITIALIZATION TEST")
    print("="*60)
    
    try:
        # Test database
        db, test_char_id = test_database()
        
        # Test RAG
        rag = test_rag()
        
        # Test personalities
        pers_mgr = test_personalities()
        
        # Test roles
        role_mgr = test_roles()
        
        # Test character system
        char = test_character_system(db, pers_mgr)
        
        # Summary
        print("\n" + "="*60)
        print("🎉 ALL TESTS PASSED!")
        print("="*60)
        print("\n✅ Database: Working")
        print("✅ RAG Memory: Working")
        print("✅ Personalities: Working")
        print("✅ Roles: Working")
        print("✅ Character System: Working")
        
        print("\n" + "="*60)
        print("📊 System Status")
        print("="*60)
        
        characters = db.get_all_characters()
        personalities = pers_mgr.list_all()
        roles = role_mgr.list_all()
        
        print(f"Characters: {len(characters)}")
        print(f"Personalities: {len(personalities)}")
        print(f"Roles: {len(roles)}")
        
        print("\n" + "="*60)
        print("🚀 Next Steps")
        print("="*60)
        print("\n1. Launch Dashboard:")
        print("   streamlit run simulation/scenes/dashboard/dashboard_v2.py")
        print("\n2. Launch Phone Scene:")
        print("   python simulation/scenes/phone/phone_scene.py")
        print("\n3. Create more characters in the dashboard!")
        
        return True
        
    except Exception as e:
        print(f"\n❌ ERROR: {e}")
        import traceback
        traceback.print_exc()
        return False


if __name__ == "__main__":
    success = main()
    sys.exit(0 if success else 1)
