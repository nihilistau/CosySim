"""
AgentLoop — tick-based autonomous decision cycle for multi-agent scenes.

Each tick, every character in the scene:
  1. **Perceives** — observes location, nearby characters, recent events
  2. **Decides**  — LLM chooses an action (speak, move, interact, idle)
  3. **Executes** — action is applied to the scene and logged to EventChain

The loop runs on a configurable interval (default 30 s) and characters
take turns in round-robin order to avoid conflicts.

Usage::

    loop = AgentLoop(scene_map, db, socketio, llm_url)
    loop.register_character(char_a)
    loop.register_character(char_b)
    loop.start(interval=30)
"""
from __future__ import annotations

import json
import random
import threading
import logging
from datetime import datetime
from typing import Any, Callable, Dict, List, Optional

logger = logging.getLogger(__name__)


class AgentLoop:
    """Tick-based multi-agent decision engine.

    Args:
        scene_map: :class:`engine.spatial.SceneMap` instance.
        db: Database handle for persistence.
        socketio: Flask-SocketIO for real-time UI pushes.
        llm_url: LMStudio base URL (``http://localhost:1234/v1``).
        scene_id: Scene identifier for EventChain.
    """

    # Actions the LLM can choose from
    VALID_ACTIONS = frozenset([
        "speak", "move", "interact", "idle",
        "flirt", "touch", "kiss", "cuddle", "intimate",
    ])

    def __init__(
        self,
        scene_map,
        db=None,
        socketio=None,
        llm_url: str = "http://localhost:1234/v1",
        scene_id: str = "bedroom",
    ):
        self.scene_map = scene_map
        self.db = db
        self.socketio = socketio
        self.llm_url = llm_url
        self.scene_id = scene_id

        self._characters: Dict[str, Any] = {}   # id → Character
        self._agents: Dict[str, Any] = {}        # id → CharacterAgent
        self._names: Dict[str, str] = {}         # id → display name
        self._running = False
        self._thread: Optional[threading.Thread] = None
        self._stop_event = threading.Event()
        self._tick_count = 0

        # Conversation log visible to all agents (pruned to 200 max)
        self.shared_log: List[Dict] = []
        self._shared_log_max = 200
        self._log_lock = threading.Lock()

        # Callbacks
        self._on_action: Optional[Callable] = None

    # ── Character registration ──────────────────────────────────────────
    def register_character(self, character, agent=None) -> None:
        """Register a character (and optional CharacterAgent) for the loop."""
        self._characters[character.id] = character
        self._names[character.id] = character.name
        if agent:
            self._agents[character.id] = agent

    def unregister_character(self, character_id: str) -> None:
        self._characters.pop(character_id, None)
        self._agents.pop(character_id, None)
        self._names.pop(character_id, None)
        self.scene_map.remove_character(character_id)

    def set_action_callback(self, fn: Callable) -> None:
        """Set a callback ``fn(character_id, action_dict)`` fired after every action."""
        self._on_action = fn

    # ── Loop control ────────────────────────────────────────────────────
    def start(self, interval: float = 30.0) -> None:
        """Start the autonomous tick loop in a background thread."""
        if self._running:
            return
        self._running = True
        self._stop_event.clear()
        self._thread = threading.Thread(
            target=self._run, args=(interval,), daemon=True, name="AgentLoop"
        )
        self._thread.start()
        logger.info("AgentLoop started (interval=%.1fs, %d characters)", interval, len(self._characters))

    def stop(self) -> None:
        self._running = False
        self._stop_event.set()
        if self._thread:
            self._thread.join(timeout=5)
        logger.info("AgentLoop stopped after %d ticks", self._tick_count)

    @property
    def is_running(self) -> bool:
        return self._running

    def _run(self, interval: float) -> None:
        while not self._stop_event.is_set():
            try:
                self.tick()
            except Exception as e:
                logger.error("AgentLoop tick error: %s", e)
            self._stop_event.wait(timeout=interval)

    # ── Core tick ───────────────────────────────────────────────────────
    def tick(self) -> List[Dict]:
        """Run one full decision cycle for all characters (round-robin)."""
        self._tick_count += 1
        actions = []
        char_ids = list(self._characters.keys())
        random.shuffle(char_ids)  # randomise order each tick

        for cid in char_ids:
            character = self._characters.get(cid)
            if not character:
                continue
            try:
                ctx = self._perceive(cid)
                decision = self._decide(cid, ctx)
                result = self._execute(cid, decision)
                actions.append(result)
                if self._on_action:
                    self._on_action(cid, result)
            except Exception as e:
                logger.warning("Tick error for %s: %s", cid, e)
                actions.append({"character_id": cid, "action": "idle", "error": str(e)})

        # Emit tick summary to UI
        if self.socketio:
            self.socketio.emit("agent_tick", {
                "tick": self._tick_count,
                "actions": actions,
                "timestamp": datetime.now().isoformat(),
            })
        return actions

    # ── Perceive ────────────────────────────────────────────────────────
    def _perceive(self, character_id: str) -> str:
        """Build a perception context string for the character."""
        character = self._characters[character_id]
        loc_ctx = self.scene_map.context_for_character(character_id, self._names)

        # Recent shared conversation (last 10 entries)
        with self._log_lock:
            recent = self.shared_log[-10:] if self.shared_log else []
        convo = "\n".join(
            f"  {e.get('name','?')}: {e.get('text','')}" for e in recent
        ) if recent else "(silence)"

        # Other character states
        nearby = self.scene_map.get_nearby_characters(character_id)
        others_info = []
        for oid in nearby:
            other = self._characters.get(oid)
            if other:
                others_info.append(
                    f"{other.name}: mood={other.mood}, "
                    f"arousal={getattr(other, 'arousal', 0.0):.0%}"
                )

        mood = getattr(character, 'mood', 'neutral')
        arousal = getattr(character, 'arousal', 0.0)
        energy = getattr(character, 'energy', 1.0)

        # Available locations for movement
        all_locs = self.scene_map.location_names
        cur_loc = self.scene_map.get_character_location(character_id)
        cur_name = cur_loc.name if cur_loc else "nowhere"

        return (
            f"## Your State\n"
            f"Mood: {mood}, Arousal: {arousal:.0%}, Energy: {energy:.0%}\n"
            f"\n## Location\n{loc_ctx}\n"
            f"\n## Nearby People\n{chr(10).join(others_info) if others_info else 'You are alone.'}\n"
            f"\n## Recent Conversation\n{convo}\n"
            f"\n## Available Locations\n{', '.join(all_locs)}\n"
            f"\n## Location Activities\n"
            f"{self._location_activities(character_id)}\n"
            f"\n## Instructions\n"
            f"Choose ONE action. Respond as JSON: "
            f'{{"action": "<ACTION>", "target": "<target_name_or_location>", "message": "<what_you_say>"}}\n'
            f"Actions: speak, move, interact, idle, flirt, touch, kiss, cuddle, intimate\n"
            f"- speak: say something (put text in 'message')\n"
            f"- move: go to a different location (put location name in 'target')\n"
            f"- interact: do an activity at your location\n"
            f"- flirt/touch/kiss/cuddle/intimate: physical interaction with someone nearby\n"
            f"- idle: do nothing, observe\n"
        )

    def _location_activities(self, character_id: str) -> str:
        """Describe what activities are available at the character's location."""
        loc = self.scene_map.get_character_location(character_id)
        if not loc:
            return "No activities available."
        activities = loc.interactions or []
        props = loc.properties if hasattr(loc, "properties") and loc.properties else {}
        privacy = props.get("privacy", 0.5)
        spiciness = props.get("spiciness", 0)
        capacity = props.get("capacity", 4)

        lines = [f"At the {loc.name}: {', '.join(activities)}" if activities else f"At the {loc.name}: nothing specific"]

        # Location mood influence
        mood_hints = {
            "bed": "Soft pillows and warm sheets invite closeness and vulnerability.",
            "couch": "A comfortable spot for relaxed conversation or cuddling up together.",
            "bar": "The glow of bottles and candlelight creates a social, flirty atmosphere.",
            "bathroom": "Steam and water sounds create an intimate, private atmosphere.",
            "balcony": "The night air and distant city sounds feel romantic and freeing.",
            "vanity": "The mirror reflects a space for self-admiration or shared grooming.",
            "doorway": "The threshold between staying and leaving — a liminal, uncertain space.",
        }
        loc_lower = loc.name.lower()
        for key, hint in mood_hints.items():
            if key in loc_lower:
                lines.append(hint)
                break

        if privacy > 0.7:
            lines.append("This is a private location — intimate actions feel natural here.")
        elif privacy < 0.3:
            lines.append("This location feels exposed — bold actions would take courage.")
        if spiciness >= 4:
            lines.append("The atmosphere is sensual and inviting.")
        elif spiciness >= 2:
            lines.append("There's a subtle romantic tension in the air.")

        # Environmental events (from menace menu or similar)
        with self._log_lock:
            env_events = [e for e in self.shared_log[-5:] if e.get("type") == "environment"]
        if env_events:
            lines.append("⚠ Something just happened in the environment: " + env_events[-1].get("text", ""))

        return "\n".join(lines)

    # ── Decide ──────────────────────────────────────────────────────────
    def _decide(self, character_id: str, context: str) -> Dict:
        """Ask the LLM to choose an action. Falls back to idle on error."""
        character = self._characters[character_id]
        agent = self._agents.get(character_id)

        # Build system prompt
        system = (
            f"You are {character.name}. You are in a scene with another person. "
            f"You must decide what to do next based on your mood, the situation, "
            f"and your personality. Be spontaneous and natural. "
            f"Respond ONLY with a JSON object — no extra text."
        )

        # If we have a CharacterAgent, use reply() for full skill/MCP support
        if agent:
            try:
                response = agent.reply(
                    context,
                    history=[{"role": "system", "content": system}],
                    use_tools=False,  # Decisions are text-only JSON
                )
                if response:
                    return self._parse_decision(response)
            except Exception as e:
                logger.debug("CharacterAgent.reply() failed: %s, trying quick_query", e)
            # Fallback to quick_query
            try:
                response = agent.quick_query(system + "\n\n" + context)
                return self._parse_decision(response)
            except Exception:
                pass

        # Fallback: try direct OpenAI-compatible API call
        try:
            import requests
            resp = requests.post(
                f"{self.llm_url}/chat/completions",
                json={
                    "model": "default",
                    "messages": [
                        {"role": "system", "content": system},
                        {"role": "user", "content": context},
                    ],
                    "temperature": 0.9,
                    "max_tokens": 200,
                },
                timeout=30,
            )
            if resp.status_code == 200:
                text = resp.json()["choices"][0]["message"]["content"]
                return self._parse_decision(text)
        except Exception as e:
            logger.debug("LLM call failed: %s", e)

        # Ultimate fallback: random action
        return self._random_action(character_id)

    def _parse_decision(self, text: str) -> Dict:
        """Extract JSON action from LLM response."""
        text = text.strip()
        # Find JSON in the response
        start = text.find("{")
        end = text.rfind("}") + 1
        if start >= 0 and end > start:
            try:
                data = json.loads(text[start:end])
                action = data.get("action", "idle").lower()
                if action not in self.VALID_ACTIONS:
                    action = "idle"
                return {
                    "action": action,
                    "target": data.get("target", ""),
                    "message": data.get("message", ""),
                }
            except json.JSONDecodeError:
                pass
        return {"action": "idle", "target": "", "message": ""}

    def _random_action(self, character_id: str) -> Dict:
        """Generate a plausible random action (fallback when LLM unavailable)."""
        character = self._characters[character_id]
        nearby = self.scene_map.get_nearby_characters(character_id)
        arousal = float(getattr(character, 'arousal', 0.0) or 0.0)

        # Weight actions by state
        if nearby and arousal > 0.5:
            actions = ["flirt", "speak", "touch", "speak", "kiss"]
        elif nearby:
            actions = ["speak", "speak", "speak", "idle", "flirt", "move"]
        else:
            actions = ["move", "move", "idle", "idle"]

        action = random.choice(actions)
        result = {"action": action, "target": "", "message": ""}

        if action == "move":
            locs = self.scene_map.get_empty_locations()
            cur_loc = self.scene_map.get_character_location(character_id)
            candidates = [l for l in self.scene_map.locations if l.id != (cur_loc.id if cur_loc else "")]
            if candidates:
                result["target"] = random.choice(candidates).name
        elif action == "speak" and nearby:
            other = self._characters.get(nearby[0])
            other_name = other.name if other else "someone"
            phrases = [
                f"Hey {other_name}, how are you feeling?",
                "This is nice, being here with you.",
                "What are you thinking about?",
                "Come here...",
                "You look amazing right now.",
            ]
            result["message"] = random.choice(phrases)
            result["target"] = other_name
        elif action in ("flirt", "touch", "kiss") and nearby:
            other = self._characters.get(nearby[0])
            result["target"] = other.name if other else ""

        return result

    # ── Execute ─────────────────────────────────────────────────────────
    def _execute(self, character_id: str, decision: Dict) -> Dict:
        """Apply the decided action to the scene and return a result dict."""
        character = self._characters[character_id]
        action = decision["action"]
        target = decision.get("target", "")
        message = decision.get("message", "")
        timestamp = datetime.now().isoformat()

        result = {
            "character_id": character_id,
            "character_name": character.name,
            "action": action,
            "target": target,
            "message": message,
            "timestamp": timestamp,
            "success": True,
        }

        if action == "move":
            loc = self.scene_map.get_location_by_name(target)
            if loc:
                success = self.scene_map.move_character(character_id, loc.id)
                result["success"] = success
                result["description"] = f"{character.name} moved to the {target}." if success else f"{target} is full."
            else:
                result["success"] = False
                result["description"] = f"{character.name} doesn't know where '{target}' is."

        elif action == "speak":
            with self._log_lock:
                self.shared_log.append({
                    "name": character.name, "text": message,
                    "timestamp": timestamp, "type": "speech",
                })
                self.shared_log = self.shared_log[-self._shared_log_max:]
            result["description"] = f'{character.name} says: "{message}"'

        elif action in ("flirt", "touch", "kiss", "cuddle", "intimate"):
            # Physical interaction — check proximity
            nearby = self.scene_map.get_nearby_characters(character_id)
            target_id = None
            for nid in nearby:
                other = self._characters.get(nid)
                if other and (other.name.lower() == target.lower() or not target):
                    target_id = nid
                    break
            if target_id:
                other = self._characters[target_id]
                desc_map = {
                    "flirt": f"{character.name} flirts with {other.name}",
                    "touch": f"{character.name} gently touches {other.name}",
                    "kiss": f"{character.name} kisses {other.name}",
                    "cuddle": f"{character.name} cuddles up to {other.name}",
                    "intimate": f"{character.name} and {other.name} share an intimate moment",
                }
                result["description"] = desc_map.get(action, f"{character.name} interacts with {other.name}")
                with self._log_lock:
                    self.shared_log.append({
                        "name": character.name, "text": f"*{result['description']}*",
                        "timestamp": timestamp, "type": "action",
                    })
                    self.shared_log = self.shared_log[-self._shared_log_max:]
                arousal_boost = {"flirt": 0.05, "touch": 0.08, "kiss": 0.12, "cuddle": 0.10, "intimate": 0.20}
                delta = arousal_boost.get(action, 0.05)
                for cid in (character_id, target_id):
                    c = self._characters.get(cid)
                    if c and hasattr(c, 'adjust_arousal'):
                        c.adjust_arousal(delta)
            else:
                result["success"] = False
                result["description"] = f"No one nearby to {action} with."

        elif action == "interact":
            loc = self.scene_map.get_character_location(character_id)
            if loc and loc.interactions:
                activity = random.choice(loc.interactions) if not message else message
                result["description"] = f"{character.name} {activity} at the {loc.name}."
                with self._log_lock:
                    self.shared_log.append({
                        "name": character.name, "text": f"*{result['description']}*",
                        "timestamp": timestamp, "type": "action",
                    })
                    self.shared_log = self.shared_log[-self._shared_log_max:]
            else:
                result["description"] = f"{character.name} looks around."

        else:  # idle
            loc = self.scene_map.get_character_location(character_id)
            loc_name = loc.name if loc else "the room"
            idle_descs = [
                f"{character.name} looks around the {loc_name} thoughtfully.",
                f"{character.name} stretches and relaxes at the {loc_name}.",
                f"{character.name} checks their phone.",
                f"{character.name} gazes out the window.",
                f"{character.name} hums softly to themselves.",
                f"{character.name} adjusts their hair in a nearby mirror.",
            ]
            result["description"] = random.choice(idle_descs)

        # Log to EventChain
        self._log_action(result)

        # Emit to UI
        if self.socketio:
            self.socketio.emit("agent_action", result)

        return result

    def _log_action(self, result: Dict) -> None:
        """Log action to EventChain (best-effort)."""
        try:
            from content.simulation.database.events import EventChain
            ec = EventChain(self.db)
            chain_id = ec.start_chain(
                scene_id=self.scene_id,
                character_id=result["character_id"],
                summary=result.get("description", "agent action"),
            )
            ec.log(
                event_type="autonomous_trigger",
                actor="agent_loop",
                payload=result,
                summary=result.get("description", ""),
                chain_id=chain_id,
                scene_id=self.scene_id,
                character_id=result["character_id"],
            )
        except Exception:
            pass
