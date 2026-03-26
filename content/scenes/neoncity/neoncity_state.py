"""
NeonCity — Cyberpunk Strategy Board Game State Engine
=====================================================

Procedural hex grid with Glitch Storm shrink mechanic, prefab locations,
turn-based movement/action, and MCP GameState integration.

Version: v1.54.0 [2026-03-26]

Change Log:
    v1.54.0 [2026-03-26] — Grid bounds validation helper + guards in move_player and ai_turn
"""
from __future__ import annotations

import logging
import random
import time
import uuid
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)

# ═══════════════════════════════════════════════════════════════
#  CONSTANTS
# ═══════════════════════════════════════════════════════════════

GRID_SIZE = 12  # 12x12 hex grid

PREFAB_TYPES = {
    "ai_research":   {"label": "AI Research Corp",    "icon": "🧪", "loot": "hacking_software", "description": "High-tier hacking programs and viruses."},
    "implant_shop":  {"label": "Cyber Implant Shop",  "icon": "🦾", "loot": "implant",          "description": "Permanent stat boosts or extra movement."},
    "wong_shop":     {"label": "Mr. Wong's Computers", "icon": "🖥️", "loot": "hardware",        "description": "Armor, shields, defensive hardware."},
    "black_market":  {"label": "Black Market Alley",   "icon": "🗡️", "loot": "weapon",          "description": "Devastating weapons with a permanent debuff."},
    "noodle_stand":  {"label": "Noodle Stand Hub",     "icon": "🍜", "loot": "intel",            "description": "HP restore + rumor intel on other players."},
}

IMPLANTS = [
    {"id": "reflex_boost",  "name": "Reflex Boost",  "stat": "agility",  "bonus": 3},
    {"id": "neural_link",   "name": "Neural Link",   "stat": "hacking",  "bonus": 3},
    {"id": "dermal_armor",  "name": "Dermal Armor",   "stat": "defense",  "bonus": 4},
    {"id": "speed_legs",    "name": "Speed Legs",     "stat": "movement", "bonus": 2},
    {"id": "optic_scanner", "name": "Optic Scanner",  "stat": "accuracy", "bonus": 3},
]

WEAPONS = [
    {"id": "plasma_pistol",  "name": "Plasma Pistol",   "damage": 15, "accuracy": 75},
    {"id": "emp_grenade",    "name": "EMP Grenade",      "damage": 25, "accuracy": 60, "effect": "stun"},
    {"id": "mono_blade",     "name": "Mono-Blade",       "damage": 30, "accuracy": 85, "range": 1},
    {"id": "railgun",        "name": "Railgun",          "damage": 40, "accuracy": 50, "range": 4},
    {"id": "virus_launcher", "name": "Virus Launcher",   "damage": 10, "accuracy": 90, "effect": "hack"},
]

HACK_PROGRAMS = [
    {"id": "firewall_crack", "name": "Firewall Crack",  "power": 20, "description": "Bypass one firewall layer."},
    {"id": "data_worm",      "name": "Data Worm",       "power": 15, "description": "Steal credits from target."},
    {"id": "ghost_protocol", "name": "Ghost Protocol",   "power": 25, "description": "Become invisible for 1 turn."},
    {"id": "ice_breaker",    "name": "ICE Breaker",      "power": 30, "description": "Destroy AI security node."},
]

EVENT_POOL = [
    {"id": "blackout",     "label": "Grid Blackout",     "effect": "all_lose_1_move",   "description": "Power grid failure. All players lose 1 movement point."},
    {"id": "drone_strike",  "label": "Corp Drone Strike", "effect": "random_damage_15",  "description": "Corporate drones sweep the area."},
    {"id": "data_leak",     "label": "Data Leak",         "effect": "reveal_inventories", "description": "Everyone's inventory becomes public."},
    {"id": "virus_rain",    "label": "Virus Rain",        "effect": "random_hack_debuff", "description": "Malware rains from corrupted satellites."},
    {"id": "neon_surge",    "label": "Neon Power Surge",  "effect": "boost_all_stats_1",  "description": "Electromagnetic surge boosts all cybernetics."},
]


# ═══════════════════════════════════════════════════════════════
#  PLAYER STATE
# ═══════════════════════════════════════════════════════════════

@dataclass
class NeonPlayer:
    id: str
    name: str
    is_ai: bool = False
    x: int = 0
    y: int = 0
    hp: int = 100
    max_hp: int = 100
    credits: int = 50
    movement_points: int = 3
    max_movement: int = 3
    attack: int = 10
    defense: int = 5
    hacking: int = 5
    agility: int = 5
    accuracy: int = 70
    weapons: List[Dict[str, Any]] = field(default_factory=list)
    programs: List[Dict[str, Any]] = field(default_factory=list)
    implants: List[Dict[str, Any]] = field(default_factory=list)
    status_effects: List[str] = field(default_factory=list)
    alive: bool = True
    visited_prefabs: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id, "name": self.name, "is_ai": self.is_ai,
            "x": self.x, "y": self.y, "hp": self.hp, "max_hp": self.max_hp,
            "credits": self.credits, "movement_points": self.movement_points,
            "attack": self.attack, "defense": self.defense,
            "hacking": self.hacking, "agility": self.agility,
            "accuracy": self.accuracy, "alive": self.alive,
            "weapons": self.weapons, "programs": self.programs,
            "implants": [i["name"] for i in self.implants],
            "status_effects": self.status_effects,
        }

    def take_damage(self, amount: int) -> Tuple[int, bool]:
        actual = max(0, amount - self.defense)
        self.hp = max(0, self.hp - actual)
        if self.hp <= 0:
            self.alive = False
        return self.hp, not self.alive

    def heal(self, amount: int) -> int:
        self.hp = min(self.max_hp, self.hp + amount)
        return self.hp

    def can_move_to(self, tx: int, ty: int) -> bool:
        dist = abs(tx - self.x) + abs(ty - self.y)
        return dist <= self.movement_points


# ═══════════════════════════════════════════════════════════════
#  GRID CELL
# ═══════════════════════════════════════════════════════════════

@dataclass
class GridCell:
    x: int
    y: int
    terrain: str = "street"      # street, building, alley, collapsed
    prefab: Optional[str] = None  # prefab type key
    prefab_looted: bool = False
    in_storm: bool = False

    def to_dict(self) -> Dict[str, Any]:
        return {
            "x": self.x, "y": self.y, "terrain": self.terrain,
            "prefab": self.prefab, "prefab_looted": self.prefab_looted,
            "in_storm": self.in_storm,
        }


# ═══════════════════════════════════════════════════════════════
#  NEONCITY GAME STATE
# ═══════════════════════════════════════════════════════════════

class NeonCityGameState:
    """Central state for one NeonCity session."""

    def __init__(self, num_ai_players: int = 3):
        self.session_id = f"neon_{uuid.uuid4().hex[:8]}"
        self.grid_size = GRID_SIZE
        self.turn_number: int = 0
        self.phase: str = "setup"  # setup, movement, action, event, ended
        self.current_player_idx: int = 0
        self.storm_radius: int = GRID_SIZE // 2  # shrinks each round
        self.storm_damage: int = 10
        self.started_at: float = 0.0
        self.ended: bool = False
        self.winner: Optional[str] = None
        self.event_log: List[Dict[str, Any]] = []

        # AI target location (center-ish)
        cx, cy = GRID_SIZE // 2, GRID_SIZE // 2
        self.target_x = cx + random.randint(-1, 1)
        self.target_y = cy + random.randint(-1, 1)
        self.target_firewall: int = 3  # layers to breach

        # Build grid
        self.grid: List[List[GridCell]] = []
        for y in range(GRID_SIZE):
            row = []
            for x in range(GRID_SIZE):
                terrain = random.choices(["street", "building", "alley"], weights=[60, 25, 15])[0]
                row.append(GridCell(x=x, y=y, terrain=terrain))
            self.grid.append(row)

        # Place target
        self.grid[self.target_y][self.target_x].terrain = "target"

        # Place prefabs
        self._place_prefabs()

        # Players
        self.players: List[NeonPlayer] = []
        # Human player
        self.players.append(NeonPlayer(
            id="player", name="Runner", is_ai=False,
            x=random.randint(0, 2), y=random.randint(0, 2),
        ))
        # AI players
        ai_names = ["RAZOR", "GHOST", "CHROME", "NEON", "SPIKE"]
        corners = [(GRID_SIZE-1, 0), (0, GRID_SIZE-1), (GRID_SIZE-1, GRID_SIZE-1)]
        for i in range(min(num_ai_players, len(corners))):
            cx, cy = corners[i]
            self.players.append(NeonPlayer(
                id=f"ai_{i}", name=ai_names[i], is_ai=True,
                x=cx + random.randint(-1, 0), y=cy + random.randint(-1, 0),
                hacking=random.randint(5, 12), attack=random.randint(8, 15),
            ))

    def _place_prefabs(self) -> None:
        """Scatter one of each prefab type on the grid."""
        available = []
        for y in range(self.grid_size):
            for x in range(self.grid_size):
                if self.grid[y][x].terrain == "street" and (x, y) != (self.target_x, self.target_y):
                    available.append((x, y))
        random.shuffle(available)
        for i, ptype in enumerate(PREFAB_TYPES.keys()):
            if i < len(available):
                x, y = available[i]
                self.grid[y][x].prefab = ptype

    def to_dict(self) -> Dict[str, Any]:
        return {
            "session_id": self.session_id,
            "grid_size": self.grid_size,
            "turn_number": self.turn_number,
            "phase": self.phase,
            "current_player": self.players[self.current_player_idx].id if self.players else None,
            "storm_radius": self.storm_radius,
            "target": {"x": self.target_x, "y": self.target_y, "firewall": self.target_firewall},
            "players": [p.to_dict() for p in self.players],
            "ended": self.ended,
            "winner": self.winner,
            "event_log_length": len(self.event_log),
        }

    def get_grid_dict(self) -> List[List[Dict[str, Any]]]:
        return [[cell.to_dict() for cell in row] for row in self.grid]

    def get_current_player(self) -> Optional[NeonPlayer]:
        if not self.players:
            return None
        return self.players[self.current_player_idx]

    def get_player(self, player_id: str) -> Optional[NeonPlayer]:
        """Look up a player by ID."""
        return next((p for p in self.players if p.id == player_id), None)

    def is_in_storm(self, x: int, y: int) -> bool:
        """Return True if the given cell is inside the Glitch Storm."""
        if 0 <= y < self.grid_size and 0 <= x < self.grid_size:
            return self.grid[y][x].in_storm
        return True

    # ── Turn management ──

    def start_game(self) -> Dict[str, Any]:
        self.phase = "movement"
        self.started_at = time.time()
        self.turn_number = 1
        return {"started": True, "turn": 1, "current_player": self.players[0].id}

    def advance_turn(self) -> Dict[str, Any]:
        """Move to next player or next round."""
        self.current_player_idx += 1
        if self.current_player_idx >= len(self.players):
            self.current_player_idx = 0
            self.turn_number += 1
            self._advance_storm()
            self._apply_storm_damage()
            # Reset movement
            for p in self.players:
                if p.alive:
                    p.movement_points = p.max_movement
                    p.status_effects = [e for e in p.status_effects if e != "stunned"]

        # Skip dead players
        attempts = 0
        while not self.players[self.current_player_idx].alive and attempts < len(self.players):
            self.current_player_idx = (self.current_player_idx + 1) % len(self.players)
            attempts += 1

        self.phase = "movement"
        alive = [p for p in self.players if p.alive]
        if len(alive) <= 1:
            self.ended = True
            self.winner = alive[0].id if alive else None

        return {"turn": self.turn_number, "current_player": self.players[self.current_player_idx].id, "storm_radius": self.storm_radius}

    def _advance_storm(self) -> None:
        """Shrink the Glitch Storm boundary."""
        if self.storm_radius > 2:
            self.storm_radius -= 1
            self.storm_damage += 5
        cx, cy = self.grid_size // 2, self.grid_size // 2
        for y in range(self.grid_size):
            for x in range(self.grid_size):
                dist = max(abs(x - cx), abs(y - cy))
                self.grid[y][x].in_storm = dist > self.storm_radius

    def _apply_storm_damage(self) -> None:
        """Damage players caught in the storm."""
        for p in self.players:
            if p.alive and self.grid[p.y][p.x].in_storm:
                p.take_damage(self.storm_damage)
                self.event_log.append({"type": "storm_damage", "player": p.id, "damage": self.storm_damage, "turn": self.turn_number})

    # ── Movement ──

    def move_player(self, player_id: str, tx: int, ty: int) -> Dict[str, Any]:
        p = self._get_player(player_id)
        if not p or not p.alive:
            return {"error": "Invalid player"}
        if "stunned" in p.status_effects:
            return {"error": "Player is stunned"}
        # v1.54.0 [2026-03-26] — Bounds validation via helper
        try:
            self._validate_position(tx, ty)
        except ValueError as exc:
            logger.warning("[NeonCity] Move rejected (operation=move, player=%s): %s", player_id, exc)
            return {"error": "Out of bounds"}
        cell = self.grid[ty][tx]
        if cell.terrain == "building":
            return {"error": "Cannot move into building"}
        dist = abs(tx - p.x) + abs(ty - p.y)
        if dist > p.movement_points:
            return {"error": f"Not enough movement ({dist} needed, {p.movement_points} available)"}
        p.movement_points -= dist
        p.x, p.y = tx, ty
        result: Dict[str, Any] = {"moved": True, "x": tx, "y": ty, "movement_left": p.movement_points}
        # Check prefab
        if cell.prefab and not cell.prefab_looted:
            loot = self._loot_prefab(p, cell)
            result["loot"] = loot
        # Check target
        if tx == self.target_x and ty == self.target_y:
            result["at_target"] = True
        return result

    def _loot_prefab(self, player: NeonPlayer, cell: GridCell) -> Dict[str, Any]:
        cell.prefab_looted = True
        ptype = PREFAB_TYPES.get(cell.prefab, {})
        loot_type = ptype.get("loot", "misc")
        player.visited_prefabs.append(cell.prefab)

        if loot_type == "hacking_software":
            prog = random.choice(HACK_PROGRAMS)
            player.programs.append(dict(prog))
            return {"type": "program", "item": prog}
        elif loot_type == "implant":
            imp = random.choice(IMPLANTS)
            player.implants.append(dict(imp))
            setattr(player, imp["stat"], getattr(player, imp["stat"], 0) + imp["bonus"])
            return {"type": "implant", "item": imp}
        elif loot_type == "hardware":
            player.defense += 5
            player.max_hp += 15
            player.hp = min(player.hp + 15, player.max_hp)
            return {"type": "hardware", "effect": "+5 DEF, +15 HP"}
        elif loot_type == "weapon":
            wpn = random.choice(WEAPONS)
            player.weapons.append(dict(wpn))
            # Black market debuff
            player.max_hp -= 10
            player.hp = min(player.hp, player.max_hp)
            return {"type": "weapon", "item": wpn, "debuff": "-10 max HP"}
        elif loot_type == "intel":
            player.heal(30)
            # Rumor: reveal a random AI player's stats
            ai_players = [p for p in self.players if p.is_ai and p.alive and p.id != player.id]
            rumor = None
            if ai_players:
                target = random.choice(ai_players)
                rumor = {"player": target.name, "hp": target.hp, "weapons": len(target.weapons)}
            return {"type": "intel", "healed": 30, "rumor": rumor}
        return {"type": "nothing"}

    # ── Combat ──

    def attack_player(self, attacker_id: str, target_id: str, weapon_idx: int = 0) -> Dict[str, Any]:
        attacker = self._get_player(attacker_id)
        target = self._get_player(target_id)
        if not attacker or not target or not attacker.alive or not target.alive:
            return {"error": "Invalid combatants"}
        dist = abs(attacker.x - target.x) + abs(attacker.y - target.y)
        if dist > 3:
            return {"error": "Target out of range"}

        weapon = attacker.weapons[weapon_idx] if weapon_idx < len(attacker.weapons) else None
        damage = (weapon["damage"] if weapon else attacker.attack) + random.randint(-3, 5)
        accuracy = weapon.get("accuracy", attacker.accuracy) if weapon else attacker.accuracy
        hit = random.randint(1, 100) <= accuracy

        if not hit:
            self.event_log.append({"type": "attack_miss", "attacker": attacker_id, "target": target_id, "turn": self.turn_number})
            return {"hit": False, "attacker": attacker_id, "target": target_id}

        hp, dead = target.take_damage(damage)
        effect = weapon.get("effect") if weapon else None
        if effect == "stun" and "stunned" not in target.status_effects:
            target.status_effects.append("stunned")
        if effect == "hack":
            target.hacking = max(0, target.hacking - 3)

        self.event_log.append({"type": "attack_hit", "attacker": attacker_id, "target": target_id, "damage": damage, "killed": dead, "turn": self.turn_number})
        return {"hit": True, "damage": damage, "target_hp": hp, "killed": dead, "effect": effect}

    # ── Hacking (at target) ──

    def hack_target(self, player_id: str) -> Dict[str, Any]:
        p = self._get_player(player_id)
        if not p or not p.alive:
            return {"error": "Invalid player"}
        if p.x != self.target_x or p.y != self.target_y:
            return {"error": "Not at target location"}
        if self.target_firewall <= 0:
            return {"error": "Already breached"}

        power = p.hacking + sum(pr.get("power", 0) for pr in p.programs)
        dc = 15 + (self.target_firewall * 5)
        roll = random.randint(1, 20) + power
        success = roll >= dc

        if success:
            self.target_firewall -= 1
            if self.target_firewall <= 0:
                self.ended = True
                self.winner = player_id
                self.event_log.append({"type": "target_breached", "player": player_id, "turn": self.turn_number})
                return {"success": True, "breached": True, "winner": player_id}
            return {"success": True, "firewall_remaining": self.target_firewall, "roll": roll, "dc": dc}
        return {"success": False, "firewall_remaining": self.target_firewall, "roll": roll, "dc": dc}

    # ── Random Events ──

    def trigger_event(self) -> Dict[str, Any]:
        event = random.choice(EVENT_POOL)
        result: Dict[str, Any] = {"event": event}
        eff = event["effect"]
        if eff == "all_lose_1_move":
            for p in self.players:
                p.max_movement = max(1, p.max_movement - 1)
        elif eff == "random_damage_15":
            target = random.choice([p for p in self.players if p.alive])
            target.take_damage(15)
            result["target"] = target.id
        elif eff == "reveal_inventories":
            result["revealed"] = {p.id: {"weapons": len(p.weapons), "programs": len(p.programs)} for p in self.players if p.alive}
        elif eff == "random_hack_debuff":
            target = random.choice([p for p in self.players if p.alive])
            target.hacking = max(0, target.hacking - 2)
            result["target"] = target.id
        elif eff == "boost_all_stats_1":
            for p in self.players:
                if p.alive:
                    p.attack += 1
                    p.defense += 1
        self.event_log.append({"type": "event", "event_id": event["id"], "turn": self.turn_number})
        return result

    # ── AI Turn ──

    def ai_turn(self, player_id: str) -> List[Dict[str, Any]]:
        """Simple AI: move toward target, attack nearby enemies, loot prefabs."""
        p = self._get_player(player_id)
        if not p or not p.alive or not p.is_ai:
            return []
        actions = []

        # Move toward target
        dx = 1 if self.target_x > p.x else (-1 if self.target_x < p.x else 0)
        dy = 1 if self.target_y > p.y else (-1 if self.target_y < p.y else 0)
        nx, ny = p.x + dx, p.y + dy
        # v1.54.0 [2026-03-26] — Clamp and validate AI move target
        nx = max(0, min(self.grid_size - 1, nx))
        ny = max(0, min(self.grid_size - 1, ny))
        try:
            self._validate_position(nx, ny)
        except ValueError:
            logger.warning("[NeonCity] AI move out of bounds (operation=ai_turn, player=%s, pos=(%d,%d))", player_id, nx, ny)
            return actions
        if self.grid[ny][nx].terrain != "building":
            result = self.move_player(player_id, nx, ny)
            actions.append({"action": "move", **result})

        # Attack nearby human player
        human = next((pl for pl in self.players if not pl.is_ai and pl.alive), None)
        if human and abs(human.x - p.x) + abs(human.y - p.y) <= 3:
            if random.random() < 0.4:
                result = self.attack_player(player_id, human.id)
                actions.append({"action": "attack", **result})

        # Hack if at target
        if p.x == self.target_x and p.y == self.target_y:
            result = self.hack_target(player_id)
            actions.append({"action": "hack", **result})

        return actions

    # v1.54.0 [2026-03-26] — Grid bounds validation helper
    def _validate_position(self, x: int, y: int) -> None:
        """Raise ValueError if (x, y) is outside the hex grid."""
        if not (0 <= x < self.grid_size and 0 <= y < self.grid_size):
            raise ValueError(
                f"Position ({x}, {y}) out of bounds (grid size {self.grid_size})"
            )

    def _get_player(self, player_id: str) -> Optional[NeonPlayer]:
        return next((p for p in self.players if p.id == player_id), None)
