import re

with open("engine/mcp/tools/scene_tools.py", "r", encoding="utf-8") as f:
    content = f.read()

impl = '''
class ResolveSceneEventResponse(BaseModel):
    scene_id: str
    event: str
    effects: Dict[str, int]

@mcp_tool
def resolve_random_scene_event_impl(scene_id: str, ssm: Any) -> ResolveSceneEventResponse:
    """Generate a random scene event to keep things fresh."""
    import random
    bedroom_events = [
        {
            "event": "The music changes to something slower and more suggestive.",
            "effects": {"arousal": 10},
        },
        {
            "event": "Someone laughs in the next room, breaking the silence.",
            "effects": {"inhibition": 5},
        },
        {
            "event": "A sudden rush of warmth hits the room.",
            "effects": {"openness": 5, "arousal": 5},
        },
        {
            "event": "A text message notification buzzes loudly nearby.",
            "effects": {"inhibition": 10},
        },
        {
            "event": "Eye contact holds for a second too long.",
            "effects": {"affection": 10, "arousal": 5},
        },
    ]

    if scene_id == "bedroom":
        evt = random.choice(bedroom_events)
    else:
        evt = {
            "event": "A cool breeze passes through, shifting the atmosphere.",
            "effects": {"openness": 5},
        }

    try:
        ssm.add_narrative(
            scene_id,
            f"[SCENE EVENT]: {evt['event']}",
            entry_type="system",
        )
    except Exception:
        pass

    return ResolveSceneEventResponse(
        scene_id=scene_id,
        event=evt["event"],
        effects=evt["effects"]
    )
'''

if "resolve_random_scene_event_impl" not in content:
    content += impl
    with open("engine/mcp/tools/scene_tools.py", "w", encoding="utf-8") as f:
        f.write(content)
