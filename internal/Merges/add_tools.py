import json

new_code = """
class SkillsResponse(BaseModel):
    scene: str
    auto_skills: List[Dict[str, str]]
    optional_skills: List[Dict[str, str]]

@mcp_tool
def get_my_skills_impl(scene: str, manifest: Any) -> SkillsResponse:
    man = manifest.get(scene, {}) if manifest else {}
    return SkillsResponse(
        scene=scene,
        auto_skills=man.get("auto", []),
        optional_skills=man.get("optional", [])
    )

class SendToAgentResponse(BaseModel):
    ok: bool
    recipient_id: str
    message: str

@mcp_tool
def send_to_agent_impl(router: Any, recipient_id: str, message: str, sender_id: str) -> SendToAgentResponse:
    router.send(recipient_id, message, sender_id=sender_id)
    return SendToAgentResponse(ok=True, recipient_id=recipient_id, message=f"Message sent to {recipient_id}.")

class EnhanceResponse(BaseModel):
    ok: bool
    original: str
    enhanced: str

@mcp_tool
def intercept_and_enhance_impl(mgr: Any, original_message: str, instruction: str) -> EnhanceResponse:
    from engine.agents.virtual_agent import InferenceRequest
    request = InferenceRequest(
        agent_id="mcp_enhance",
        messages=[
            {
                "role": "system",
                "content": "You are a rewriting engine. Output ONLY the rewritten text, nothing else.",
            },
            {
                "role": "user",
                "content": f"Original: {original_message}\\n\\nInstruction: {instruction}",
            },
        ],
        max_tokens=200,
        temperature=0.7,
    )
    result = mgr.infer(request)
    return EnhanceResponse(ok=True, original=original_message, enhanced=result.text.strip())

class ToolsResponse(BaseModel):
    scene_id: str
    tools: List[str]

@mcp_tool
def get_all_tools_for_scene_impl(scene_id: str) -> ToolsResponse:
    bedroom_tools = [
        "wardrobe_get",
        "wardrobe_init",
        "wardrobe_remove_item",
        "wardrobe_remove_outermost",
        "perform_interaction",
        "start_timed_action",
        "check_character_consent",
        "resolve_random_scene_event",
        "get_scene_available_actions",
        "director_dictate",
    ]
    phone_tools = [
        "cross_scene_message",
        "get_cross_scene_inbox",
        "get_scene_available_actions",
        "start_game",
        "make_move",
        "get_game_state",
        "end_game",
    ]
    tools = bedroom_tools if scene_id == "bedroom" else phone_tools
    tools += ["memory_recall", "speak_as", "suggest_activity"]
    return ToolsResponse(scene_id=scene_id, tools=tools)

class DirectorDictateResponse(BaseModel):
    ok: bool
    scene_id: str
    applied_stats: Dict[str, Any]

@mcp_tool
def director_dictate_impl(
    scene_id: str,
    action: str,
    target_character_ids: str,
    stat_impact: str,
    ssm: Any,
    router: Any
) -> DirectorDictateResponse:
    import json
    targets = [t.strip() for t in target_character_ids.split(",") if t.strip()]
    ssm.add_narrative(scene_id, f"[DIRECTOR]: {action}", entry_type="system")

    applied = {}
    if stat_impact:
        try:
            impact = json.loads(stat_impact)
            for cid in targets:
                ssm.update_stats(cid, **impact)
            applied = impact
        except Exception as e:
            logger.debug("Suppressed exception", exc_info=True)

    for cid in targets:
        router.send(
            cid, f"[DIRECTOR DIRECTIVE]: {action}", sender_id="director"
        )
    return DirectorDictateResponse(ok=True, scene_id=scene_id, applied_stats=applied)
"""

with open("engine/mcp/tools/scene_tools.py", "a", encoding="utf-8") as f:
    f.write(new_code)
