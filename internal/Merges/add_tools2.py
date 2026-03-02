import json

new_code = """

class MoodContagionResponse(BaseModel):
    ok: bool
    initiator_id: str
    emotion: str
    intensity_applied: float
    targets_affected: List[str]

@mcp_tool
def trigger_mood_contagion_impl(
    scene_id: str,
    initiator_id: str,
    emotion: str,
    reg: Any,
    ssm: Any,
    intensity: float = 1.0,
    target_ids_json: str = "[]",
    affinity_factor: float = 1.0,
) -> MoodContagionResponse:
    import json
    target_ids: List[str] = (
        json.loads(target_ids_json)
        if target_ids_json and target_ids_json != "[]"
        else []
    )
    if not target_ids:
        try:
            active = ssm.get_scene_state(scene_id).get("active_characters", [])
            target_ids = [c for c in active if c != initiator_id]
        except Exception:
            pass

    applied = []
    _EMOTION_STATS = {
        "excited": {"arousal": 0.2, "happiness": 0.3},
        "aroused": {"arousal": 0.5, "openness": 0.2},
        "tender": {"affection": 0.4, "openness": 0.2},
        "warm": {"affection": 0.3, "happiness": 0.2},
        "sad": {"happiness": -0.4},
        "nervous": {"fear": 0.3, "arousal": 0.1},
        "dominant": {"inhibition": -0.2, "openness": 0.1},
        "submissive": {"inhibition": 0.2, "openness": 0.2},
        "playful": {"happiness": 0.3, "arousal": 0.1},
        "serious": {"happiness": -0.1},
        "angry": {"fear": 0.2, "happiness": -0.3},
        "fearful": {"fear": 0.5},
        "joyful": {"happiness": 0.5, "arousal": 0.15},
        "vulnerable": {"affection": 0.3, "openness": 0.25},
        "charged": {"arousal": 0.4, "openness": 0.2},
    }
    stat_impacts = _EMOTION_STATS.get(emotion, {"happiness": 0.1})

    for target_id in target_ids:
        try:
            reg.ensure(target_id)
            state = reg.get_state(target_id)
            inhibition = getattr(state, "inhibition", 0.3)
            resistance = inhibition * 0.5
            effective = max(0.0, intensity * affinity_factor * (1.0 - resistance))

            reg.set_state(target_id, mood=emotion, mood_intensity=effective)

            for stat, delta_factor in stat_impacts.items():
                delta = delta_factor * effective * 100
                try:
                    ssm.update_stats(target_id, **{stat: delta})
                except Exception:
                    logger.debug("Suppressed exception", exc_info=True)

            applied.append(target_id)
        except Exception:
            logger.debug("Suppressed exception", exc_info=True)

    if applied:
        ssm.add_narrative(
            scene_id,
            f"[{initiator_id}'s {emotion} mood spreads to: {', '.join(applied)}]",
            entry_type="system",
        )

    return MoodContagionResponse(
        ok=True,
        initiator_id=initiator_id,
        emotion=emotion,
        intensity_applied=intensity,
        targets_affected=applied,
    )

class ConsequenceScheduleResponse(BaseModel):
    ok: bool
    consequence_id: str
    fires_in_turns: int

@mcp_tool
def schedule_consequence_impl(
    scene_id: str,
    character_id: str,
    consequence_type: str,
    params_json: str,
    trigger_after_turns: int,
    description: str,
    created_by: str,
    fw: Any
) -> ConsequenceScheduleResponse:
    import json
    params = json.loads(params_json) if params_json else {}
    cseq = fw.schedule_consequence(
        scene_id=scene_id,
        character_id=character_id,
        consequence_type=consequence_type,
        params=params,
        trigger_after_turns=trigger_after_turns,
        description=description,
        created_by=created_by,
    )
    return ConsequenceScheduleResponse(
        ok=True,
        consequence_id=cseq.id,
        fires_in_turns=trigger_after_turns
    )

class CancelConsequenceResponse(BaseModel):
    ok: bool
    consequence_id: str

@mcp_tool
def cancel_consequence_impl(consequence_id: str, fw: Any) -> CancelConsequenceResponse:
    ok = fw.cancel_consequence(consequence_id)
    return CancelConsequenceResponse(ok=ok, consequence_id=consequence_id)

class PendingConsequencesResponse(BaseModel):
    pending: List[Dict[str, Any]]
    count: int

@mcp_tool
def get_pending_consequences_impl(scene_id: str, character_id: str, fw: Any) -> PendingConsequencesResponse:
    pending = fw.get_pending_consequences(scene_id=scene_id, character_id=character_id)
    return PendingConsequencesResponse(pending=pending, count=len(pending))

class MoodWhisperResponse(BaseModel):
    ok: bool
    from_character_id: str
    to_character_id: str
    duration_turns: int
    note: str

@mcp_tool
def mood_whisper_impl(
    from_character_id: str,
    to_character_id: str,
    whisper_content: str,
    duration_turns: int,
    fw: Any,
    ds: Any,
    ssm: Any,
    scene_id: str = ""
) -> MoodWhisperResponse:
    duration_turns = max(1, min(5, duration_turns))
    target_scene = scene_id
    if not target_scene:
        try:
            target_scene = fw.get_character(to_character_id).current_scene or "phone"
        except Exception:
            target_scene = "phone"

    directive_val = f"[MOOD WHISPER from {from_character_id}]: {whisper_content}"
    ds.set_directive(
        character_id=to_character_id,
        scene_id=target_scene,
        directive_type="mood_set",
        value=directive_val,
        turns=duration_turns,
        issued_by=from_character_id,
    )

    ssm.add_narrative(
        target_scene,
        f"[{from_character_id} planted a mood whisper in {to_character_id}'s mind.]",
        entry_type="system",
        character_id=to_character_id,
    )

    return MoodWhisperResponse(
        ok=True,
        from_character_id=from_character_id,
        to_character_id=to_character_id,
        duration_turns=duration_turns,
        note="Whisper planted. They will feel it for the next few turns."
    )

class MirrorSoulResponse(BaseModel):
    ok: bool
    character_id: str
    target_id: str
    chosen_style: str
    lasts_turns: int
    narrative: str

@mcp_tool
def mirror_soul_impl(
    character_id: str,
    target_id: str,
    duration_turns: int,
    scene_id: str,
    reg: Any,
    ds: Any,
    ssm: Any,
    fw: Any
) -> MirrorSoulResponse:
    duration_turns = max(1, min(6, duration_turns))

    target_state = reg.get_state(target_id)
    target_mood = target_state.mood if target_state else "neutral"

    mood_to_style = {
        "vulnerable": "warm",
        "sad": "warm",
        "angry": "calm",
        "aroused": "charged",
        "playful": "teasing",
        "nervous": "dominant",
        "dominant": "submissive",
        "submissive": "dominant",
        "excited": "playful",
    }
    chosen_style = mood_to_style.get(target_mood, "natural")

    ds.set_directive(
        character_id=character_id,
        scene_id=scene_id,
        directive_type="style_lock",
        value=chosen_style,
        turns=duration_turns,
        issued_by="mirror_soul",
    )

    ssm.update_stats(character_id, openness=15, affection=10)
    ssm.update_stats(target_id, openness=15, affection=10)

    narrative = (
        f"Something shifts. {character_id} doesn't change, exactly — "
        f"they just become the version of themselves {target_id} most needs right now. "
        f"Style: {chosen_style.upper()}. Duration: {duration_turns} turns."
    )

    ssm.add_narrative(
        scene_id,
        f"[MIRROR SOUL]: {character_id} attuned to {target_id}'s {target_mood} mood, adopting {chosen_style} style.",
        entry_type="system",
        character_id=character_id,
    )

    fw.schedule_consequence(
        scene_id=scene_id,
        character_id=character_id,
        consequence_type="directive_clear",
        params={},
        trigger_after_turns=duration_turns,
        description=f"The Mirror Soul attunement fades. {character_id} returns to baseline.",
        created_by="mirror_soul",
    )

    return MirrorSoulResponse(
        ok=True,
        character_id=character_id,
        target_id=target_id,
        chosen_style=chosen_style,
        lasts_turns=duration_turns,
        narrative=narrative
    )
"""

with open("engine/mcp/tools/interaction_tools.py", "a", encoding="utf-8") as f:
    f.write(new_code)
