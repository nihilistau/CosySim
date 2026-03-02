import json

new_code = """

class ServeLoungeDrinkResponse(BaseModel):
    ok: bool
    drink: str
    narrative: str

@mcp_tool
def serve_lounge_drink_impl(
    drink_id: str,
    bartender_id: str,
    fw: Any,
    ssm: Any,
    router: Any,
    scene_id: str = "lounge"
) -> ServeLoungeDrinkResponse:
    from content.scenes.lounge.lounge_mcp import get_cocktail, LOLA_ID

    drink = get_cocktail(drink_id)
    if not drink:
        raise Exception(f"Drink '{drink_id}' not found on the menu.")

    desc = f"[{bartender_id.title()} serves {drink['name']}]"
    if drink.get("presentation"):
        desc += f" {drink['presentation']}"

    if drink.get("effects"):
        fw.schedule_consequence(
            scene_id=scene_id,
            character_id="user_char",
            consequence_type="stat_change",
            params=drink["effects"],
            trigger_after_turns=1,
            description=f"The {drink['name']} takes effect.",
            created_by="serve_lounge_drink",
        )

    ssm.add_narrative(
        scene_id,
        desc,
        entry_type="system",
        character_id=bartender_id,
    )

    if drink_id == "neat_bourbon":
        ssm.set_scene_state(scene_id, "viktor_drinking", True)
        desc += " He pours a measure for himself, leaning against the counter."

    effects = drink.get("effects", {})
    if effects.get("arousal", 0) > 0 or drink_id in ["siren_song", "velvet_rose"]:
        router.send(
            LOLA_ID,
            f"Viktor just served the guest a {drink['name']}. It's a bold choice.",
            sender_id="system",
        )

    return ServeLoungeDrinkResponse(
        ok=True,
        drink=drink["name"],
        narrative=desc
    )
"""

with open("engine/mcp/tools/lounge_tools.py", "a", encoding="utf-8") as f:
    f.write(new_code)
