import re

# Update lounge_tools.py
with open('engine/mcp/tools/lounge_tools.py', 'r', encoding='utf-8') as f:
    lounge_code = f.read()

pattern_impl = r'@mcp_tool\ndef serve_lounge_drink_impl\(.*?\) -> ServeLoungeDrinkResponse:\n.*?return ServeLoungeDrinkResponse\(\n        ok=True,\n        drink=drink\["name"\],\n        narrative=desc\n    \)'

new_impl = '''@mcp_tool
def serve_lounge_drink_impl(
    drink_id: str,
    bartender_id: str,
    fw: Any,
    ssm: Any,
    ds: Any,
    scene_id: str = "lounge"
) -> ServeLoungeDrinkResponse:
    from content.scenes.lounge.lounge_mcp import get_cocktail, LOLA_ID, VIKTOR_ID

    cocktail = get_cocktail(drink_id)
    if not cocktail:
        raise Exception(f"No cocktail found with id '{drink_id}'.")

    scheduled = []
    for stat, delta in (cocktail.get("stat_effects") or {}).items():
        if stat in (
            "trust",
            "arousal",
            "openness",
            "inhibition",
            "happiness",
            "affection",
            "confidence",
        ):
            fw.schedule_consequence(
                scene_id=scene_id,
                character_id="guest",
                consequence_type="stat_adjust",
                params={"stat": stat, "delta": delta},
                trigger_after_turns=1,
                description=f"Drink '{cocktail['name']}': {stat} {'+' if delta > 0 else ''}{delta}",
            )
            scheduled.append(f"{stat}{'+' if delta > 0 else ''}{delta}")

    if cocktail.get("lola_reaction"):
        ds.set_directive(
            character_id=LOLA_ID,
            scene_id=scene_id,
            directive_type="must_include",
            value="catches the guest's eye briefly across the bar",
            turns=1,
            issued_by="serve_lounge_drink",
        )
        fw.cross_scene_send(
            from_char=VIKTOR_ID,
            from_scene=scene_id,
            to_char=LOLA_ID,
            to_scene=scene_id,
            message=f"Poured '{cocktail['name']}' for the guest.",
            message_type="drink_notification",
        )

    if cocktail.get("viktor_joins"):
        ds.set_directive(
            character_id=VIKTOR_ID,
            scene_id=scene_id,
            directive_type="must_include",
            value="pours a glass for himself, stays at that end of the bar",
            turns=1,
            issued_by="bourbon_ritual",
        )

    viktor_line = (
        cocktail.get("viktor_line")
        or f"Viktor serves the {cocktail['name']} without comment."
    )
    ssm.add_narrative(scene_id, VIKTOR_ID, viktor_line)

    effects_str = ", ".join(scheduled) if scheduled else "none"
    return ServeLoungeDrinkResponse(
        ok=True,
        drink=cocktail["name"],
        narrative=f"Viktor serves '{cocktail['name']}'. {cocktail.get('note', '')}\nEffects queued (fires next turn): {effects_str}\nScene: {viktor_line}"
    )'''

new_lounge_code = re.sub(pattern_impl, new_impl, lounge_code, flags=re.DOTALL)
with open('engine/mcp/tools/lounge_tools.py', 'w', encoding='utf-8') as f:
    f.write(new_lounge_code)


# Update cosysim_server.py
with open('engine/mcp/cosysim_server.py', 'r', encoding='utf-8') as f:
    code = f.read()

pattern = r'    try:\n        from content\.scenes\.lounge\.lounge_mcp import \((.*?)\n    except Exception as exc:\n        return f"serve_lounge_drink failed: \{exc\}"'

replacement = r'''    from engine.mcp.tools.lounge_tools import serve_lounge_drink_impl
    
    resp_json = serve_lounge_drink_impl(
        drink_id,
        bartender_id,
        fw=get_framework(),
        ssm=get_scene_state_manager(),
        ds=get_dialog_system(),
        scene_id=scene_id
    )
    import json
    return json.loads(resp_json)["narrative"] if '{"ok":' in resp_json else resp_json'''

new_code = re.sub(pattern, replacement, code, flags=re.DOTALL)

with open('engine/mcp/cosysim_server.py', 'w', encoding='utf-8') as f:
    f.write(new_code)

print("Updated serve_lounge_drink.")
