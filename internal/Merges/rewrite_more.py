import re

with open("engine/mcp/cosysim_server.py", "r", encoding="utf-8") as f:
    content = f.read()

# get_my_skills
pattern_skills = r'@mcp\.tool\(\)\ndef get_my_skills[\s\S]*?return json\.dumps\(\{"error": str\(e\)\}\)'
new_skills = '''@mcp.tool()
def get_my_skills(scene: str = "phone") -> str:
    """
    List all skills available to you in the current scene.
    Returns skill names, triggers (auto/optional/required), and descriptions.
    Call this to understand what tools you have access to before deciding
    whether to use one.
    """
    from engine.mcp.tools.scene_tools import get_my_skills_impl
    return get_my_skills_impl(scene, get_skill_manifest())'''
content = re.sub(pattern_skills, new_skills, content)

# send_to_agent
pattern_send = (
    r'@mcp\.tool\(\)\ndef send_to_agent[\s\S]*?return f"Failed to send: \{e\}"'
)
new_send = '''@mcp.tool()
def send_to_agent(
    recipient_id: str,
    message: str,
    sender_id: str = "system",
) -> str:
    """
    Send a message to another agent's inbox.
    The recipient will see this message on their next reply tick.
    Use this for agent-to-agent communication, coordination, or triggering
    reactions in other characters.
    sender_id should be your character ID or 'system'.
    """
    from engine.mcp.tools.scene_tools import send_to_agent_impl
    return send_to_agent_impl(get_router(), recipient_id, message, sender_id)'''
content = re.sub(pattern_send, new_send, content)

# intercept_and_enhance
pattern_intercept = r'@mcp\.tool\(\)\ndef intercept_and_enhance[\s\S]*?return json\.dumps\(\{"error": str\(e\)\}\)'
new_intercept = '''@mcp.tool()
def intercept_and_enhance(
    original_message: str,
    instruction: str,
) -> str:
    """
    Reshape or enhance a message according to a specific instruction.
    Use this to rewrite your own response before delivering it, apply a
    specific style, add depth, check it against a rule, or transform it.
    Examples:
      instruction='make this more mysterious and cryptic'
      instruction='add a flirty undertone while keeping the core meaning'
      instruction='verify this does not reveal the mystery answer'
      instruction='trim to under 50 words while keeping emotion intact'
    """
    from engine.mcp.tools.scene_tools import intercept_and_enhance_impl
    return intercept_and_enhance_impl(get_virtual_agent_manager(), original_message, instruction)'''
content = re.sub(pattern_intercept, new_intercept, content)

# get_all_tools_for_scene
pattern_tools = r'@mcp\.tool\(\)\ndef get_all_tools_for_scene[\s\S]*?return json\.dumps\(\{"error": str\(e\)\}\)'
new_tools = '''@mcp.tool()
def get_all_tools_for_scene(scene_id: str = "bedroom") -> str:
    """
    Get a complete reference of all MCP tools available in a scene.
    Call this at the start of a session so you know every tool at your disposal.
    Agents should internalise this list and joke/reference their abilities naturally.
    """
    from engine.mcp.tools.scene_tools import get_all_tools_for_scene_impl
    return get_all_tools_for_scene_impl(scene_id)'''
content = re.sub(pattern_tools, new_tools, content)

# director_dictate
pattern_director = r'@mcp\.tool\(\)\ndef director_dictate[\s\S]*?return json\.dumps\(\{"error": str\(e\)\}\)'
new_director = '''@mcp.tool()
def director_dictate(
    scene_id: str,
    action: str,
    target_character_ids: str = "",
    stat_impact: str = "",
) -> str:
    """
    Inject a Director action into the scene.  The Director's word carries weight —
    this logs the directive and optionally applies immediate stat effects.

    action: what the Director says/dictates (free text)
    target_character_ids: comma-separated character ids to notify (blank = all in scene)
    stat_impact: optional JSON string of stat changes e.g. '{"arousal": 10}'

    Characters receive this as a system-level directive.  Whether they comply
    depends on their check_character_consent() score.
    """
    from engine.mcp.tools.scene_tools import director_dictate_impl
    return director_dictate_impl(scene_id, action, target_character_ids, stat_impact, _ssm(), get_router())'''
content = re.sub(pattern_director, new_director, content)

# trigger_mood_contagion
pattern_mood = r'@mcp\.tool\(\)\ndef trigger_mood_contagion[\s\S]*?return json\.dumps\(\{"error": str\(e\)\}\)'
new_mood = '''@mcp.tool()
def trigger_mood_contagion(
    scene_id: str,
    initiator_id: str,
    emotion: str,
    intensity: float = 1.0,
    target_ids_json: str = "[]",
    affinity_factor: float = 1.0,
) -> str:
    """
    **PSYCHOLOGICAL TOOL** — Spread a mood from one character to others in a scene.

    The tool adjusts mood state in CharacterRegistry and optionally biases
    stats.  It logs the contagion event to the scene narrative.

    Emotions:
      excited, aroused, tender, warm, sad, nervous, dominant, submissive,
      playful, serious, angry, fearful, joyful, vulnerable, charged

    Args:
        scene_id:        Scene where contagion occurs
        initiator_id:    Character whose mood is spreading
        emotion:         The emotion/mood spreading
        intensity:       How strongly it spreads (0.0 = no effect, 1.0 = full)
        target_ids_json: JSON list of target char IDs (empty = all present in scene)
        affinity_factor: Multiplier for closeness (1.0 = normal, 2.0 = very close)
    """
    from engine.mcp.tools.interaction_tools import trigger_mood_contagion_impl
    return trigger_mood_contagion_impl(
        scene_id,
        initiator_id,
        emotion,
        get_character_registry(),
        get_scene_state_manager(),
        intensity=intensity,
        target_ids_json=target_ids_json,
        affinity_factor=affinity_factor,
    )'''
content = re.sub(pattern_mood, new_mood, content)

with open("engine/mcp/cosysim_server.py", "w", encoding="utf-8") as f:
    f.write(content)
print("Updated more endpoints")
