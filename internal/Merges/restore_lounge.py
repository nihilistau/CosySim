import re

with open('engine/mcp/tools/lounge_tools.py', 'r', encoding='utf-8') as f:
    code = f.read()

# Fix the broken lounge_heat_tick_impl
bad_code = """    ssm.update_stats(scene_id, heat_level=new_heat)

    fired = []
    if new_heat >= 85:
        try:
     


class ServeLoungeDrinkResponse"""

good_code = """    ssm.update_stats(scene_id, heat_level=new_heat)

    fired = []
    if new_heat >= 85:
        try:
            eng.evaluate_event(scene_id, "heat_critical")
            fired.append("heat_critical")
        except Exception:
            pass
    elif new_heat >= 65:
        try:
            eng.evaluate_event(scene_id, "heat_warning")
            fired.append("heat_warning")
        except Exception:
            pass

    return HeatTickResponse(new_heat=new_heat, rules_fired=fired)


class ServeLoungeDrinkResponse"""

new_code = code.replace(bad_code, good_code)
with open('engine/mcp/tools/lounge_tools.py', 'w', encoding='utf-8') as f:
    f.write(new_code)
