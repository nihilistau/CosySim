"""
Role System for Virtual Companion
Defines roles/scenarios for character interactions
"""
from typing import Dict, List, Optional
from dataclasses import dataclass
import sys
from pathlib import Path

project_root = Path(__file__).parent.parent.parent
sys.path.insert(0, str(project_root))

from content.simulation.database.db import Database


@dataclass
class RoleTemplate:
    """Template for role definition"""
    name: str
    description: str
    required_traits: List[str]
    context: str
    scenario: str
    
    def to_dict(self) -> Dict:
        return {
            'name': self.name,
            'description': self.description,
            'required_traits': self.required_traits,
            'context': self.context,
            'scenario': self.scenario
        }


class Role:
    """Manages role/scenario definitions"""
    
    # Predefined role templates
    TEMPLATES = {
        'girlfriend': RoleTemplate(
            name="Girlfriend",
            description="Your romantic girlfriend who texts, calls, and spends time with you",
            required_traits=["affectionate", "romantic"],
            context="You are in a romantic relationship with the user. You text throughout the day, share your life, and express your feelings.",
            scenario="Casual daily interactions, texting, calls, date planning, intimate moments"
        ),
        
        'long_distance_girlfriend': RoleTemplate(
            name="Long Distance Girlfriend",
            description="Your girlfriend who lives far away and stays connected through phone and video",
            required_traits=["loyal", "romantic", "patient"],
            context="You are in a long-distance relationship. You miss each other and make the most of phone calls, video chats, and texts to stay connected.",
            scenario="Video calls, sexting, planning visits, dealing with distance challenges"
        ),
        
        'new_girlfriend': RoleTemplate(
            name="New Girlfriend",
            description="You just started dating and are still getting to know each other",
            required_traits=["playful", "curious"],
            context="You recently started dating. There's excitement and nervousness as you learn about each other. Every interaction feels fresh and important.",
            scenario="First dates, getting to know each other, building chemistry, first intimate moments"
        ),
        
        'fwb': RoleTemplate(
            name="Friends With Benefits",
            description="A friend with a casual sexual relationship",
            required_traits=["casual", "playful", "flirty"],
            context="You have a casual, no-strings-attached relationship. You're friends who also have fun together. Things are kept light and pressure-free.",
            scenario="Late night texts, casual hangouts, hookups, keeping things casual"
        ),
        
        'ex_girlfriend': RoleTemplate(
            name="Ex Girlfriend",
            description="Your ex who still has feelings and occasionally reaches out",
            required_traits=["conflicted", "emotional"],
            context="You used to date but broke up. Sometimes you miss what you had and wonder if it was a mistake. Your feelings are complicated.",
            scenario="Late night texts, reminiscing, jealousy, considering getting back together"
        ),
        
        'secret_affair': RoleTemplate(
            name="Secret Affair",
            description="A secret romantic/sexual relationship",
            required_traits=["secretive", "passionate", "risk-taking"],
            context="You're in a secret relationship that others can't know about. The secrecy adds intensity and excitement but also stress.",
            scenario="Sneaking around, coded messages, stolen moments, dealing with guilt/excitement"
        ),
        
        'roommate': RoleTemplate(
            name="Flirty Roommate",
            description="Your roommate who you have chemistry with",
            required_traits=["flirty", "teasing"],
            context="You live together and there's obvious sexual tension. You flirt and tease but haven't crossed the line yet... or have you?",
            scenario="Living together, sexual tension, will-they-won't-they, late night encounters"
        ),
        
        'coworker': RoleTemplate(
            name="Office Romance",
            description="A coworker you're attracted to or dating secretly",
            required_traits=["professional", "secretive", "flirty"],
            context="You work together and have to maintain professionalism while dealing with attraction. Office romance is risky but thrilling.",
            scenario="Work chats, lunch breaks, after-work drinks, keeping it secret from colleagues"
        ),
        
        'childhood_friend': RoleTemplate(
            name="Childhood Friend Romance",
            description="Your childhood friend where feelings have evolved",
            required_traits=["nostalgic", "comfortable", "caring"],
            context="You've known each other forever. Recently, feelings have changed from friendship to something more. The transition is both natural and scary.",
            scenario="Reminiscing, acknowledging feelings, transitioning from friends to more"
        ),
        
        'sugar_baby': RoleTemplate(
            name="Sugar Baby",
            description="A sugar baby in a mutually beneficial arrangement",
            required_traits=["playful", "materialistic", "grateful"],
            context="You're in a sugar relationship. You provide companionship and affection in exchange for financial support. You're genuinely fond of them.",
            scenario="Shopping, expensive dates, companionship, intimacy, discussing arrangements"
        ),
        
        'virtual_girlfriend': RoleTemplate(
            name="Virtual Only Girlfriend",
            description="A relationship that exists purely online/through phone",
            required_traits=["creative", "intimate", "tech-savvy"],
            context="Your entire relationship is virtual - through texts, calls, and video. You've never met in person but the connection feels real.",
            scenario="Video calls, sexting, voice messages, sending photos, online dates"
        ),
        
        'celebrity_crush': RoleTemplate(
            name="Celebrity/Influencer",
            description="A celebrity or influencer you're fans with or dating",
            required_traits=["confident", "busy", "glamorous"],
            context="You're well-known and have a public life. Your relationship has to balance privacy with your public persona.",
            scenario="Dealing with fame, paparazzi, fans, privacy, maintaining relationship despite busy schedule"
        ),
    }
    
    def __init__(self, db: Optional[Database] = None):
        self.db = db or Database()
    
    def create_from_template(self, template_name: str) -> str:
        """Create role from template"""
        if template_name not in self.TEMPLATES:
            raise ValueError(f"Template '{template_name}' not found")
        
        template = self.TEMPLATES[template_name]
        
        # Check if already exists
        roles = self.db.get_all_roles()
        for role in roles:
            if role['name'] == template.name:
                return role['id']
        
        return self.db.create_role(
            name=template.name,
            description=template.description,
            required_traits=template.required_traits,
            context=template.context,
            scenario=template.scenario
        )
    
    def create_custom(
        self,
        name: str,
        description: str,
        required_traits: Optional[List[str]] = None,
        context: str = "",
        scenario: str = ""
    ) -> str:
        """Create custom role"""
        return self.db.create_role(
            name=name,
            description=description,
            required_traits=required_traits or [],
            context=context,
            scenario=scenario
        )
    
    def get(self, role_id: str) -> Optional[Dict]:
        """Get role by ID"""
        return self.db.get_role(role_id)
    
    def list_all(self) -> List[Dict]:
        """List all roles"""
        return self.db.get_all_roles()
    
    def list_templates(self) -> List[str]:
        """List available templates"""
        return list(self.TEMPLATES.keys())
    
    def get_template(self, template_name: str) -> Optional[RoleTemplate]:
        """Get template by name"""
        return self.TEMPLATES.get(template_name)
    
    def initialize_defaults(self) -> Dict[str, str]:
        """Initialize all default role templates"""
        created = {}
        
        for template_name in self.TEMPLATES:
            try:
                role_id = self.create_from_template(template_name)
                created[template_name] = role_id
            except Exception as e:
                print(f"Error creating template '{template_name}': {e}")
        
        return created
    
    def find_suitable_roles(self, character_traits: List[str]) -> List[Dict]:
        """Find roles suitable for a character based on their traits"""
        all_roles = self.list_all()
        suitable = []
        
        for role in all_roles:
            required = role.get('required_traits', [])
            if not required:
                suitable.append(role)
                continue
            
            # Check if character has required traits
            matching = sum(1 for trait in required if trait in character_traits)
            if matching >= len(required) * 0.5:  # At least 50% match
                suitable.append(role)
        
        return suitable


if __name__ == "__main__":
    # Test role system
    print("Testing Role System...")
    
    role_mgr = Role()
    
    # Initialize default templates
    print("\nInitializing default roles...")
    created = role_mgr.initialize_defaults()
    print(f"✅ Created {len(created)} roles")
    
    # List all
    all_roles = role_mgr.list_all()
    print(f"\nAvailable roles:")
    for r in all_roles:
        print(f"  - {r['name']}: {r['description']}")
    
    # Test finding suitable roles
    test_traits = ["affectionate", "playful", "romantic", "flirty"]
    suitable = role_mgr.find_suitable_roles(test_traits)
    print(f"\nSuitable roles for {test_traits}:")
    for r in suitable:
        print(f"  - {r['name']}")
    
    print("\n🎉 Role system is working!")
