"""
AgentLoop — v2.5 tick-based autonomous decision engine using VirtualAgentManager.

Each tick, every character in the scene:
  1. **Perceives** — observes location, nearby characters, recent events
  2. **Decides**  — VirtualAgentManager produces a structured JSON action
  3. **Executes** — action is applied to the scene and logged to EventChain

All LLM calls are routed through VirtualAgentManager for centralised
control over model routing, concurrency, and lifecycle.  When multiple
agents are registered, batch inference is used for parallel decisions.

Usage::

    loop = AgentLoop(scene_map, db, socketio, scene_id="bedroom")
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

# JSON schema for structured agent decisions
DECISION_SCHEMA = {
    "type": "object",
    "properties": {
        "action": {
            "type": "string",
            "enum": ["speak", "move", "interact", "idle",
                     "flirt", "touch", "kiss", "cuddle", "intimate"],
        },
        "target": {"type": "string", "description": "Target name or location"},
        "message": {"type": "string", "description": "What you say or do"},
    },
    "required": ["action"],
}


class AgentLoop:
    """Tick-based multi-agent decision engine using VirtualAgentManager.

    Args:
        scene_map: :class:`engine.spatial.SceneMap` instance.
        db: Database handle for persistence.
        socketio: Flask-SocketIO for real-time UI pushes.
        llm_url: Deprecated — ignored; LMSClient is auto-configured.
        scene_id: Scene identifier for EventChain.
    """

    VALID_ACTIONS = frozenset([
        "speak", "move", "interact", "idle",
        "flirt", "touch", "kiss", "cuddle", "intimate",
    ])

    def __init__(
        self,
        scene_map,
        db=None,
        socketio=None,
        llm_url: str = "",
        scene_id: str = "bedroom",
    ):
        self.scene_map = scene_map
        self.db = db
        self.socketio = socketio
        self.llm_url = llm_url
        self.scene_id = scene_id

        self._characters: Dict[str, Any] = {}   # id → Character
        self._agents: Dict[str, Any] = {}        # id → CharacterAgent/VirtualAgent
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

        # MCP: ensure tracked in CharacterRegistry + MCPFramework scene
        try:
            from engine.mcp.character_registry import get_character_registry
            get_character_registry().ensure(
                character.id,
                display_name=character.name,
            )
            from engine.mcp.framework import get_framework
            get_framework().get_character(character.id).enter_scene(self.scene_id)
            logger.debug("AgentLoop: MCP registered %s → %s", character.id, self.scene_id)
        except Exception as _exc:
            logger.debug("AgentLoop.register_character MCP sync failed: %s", _exc)

    def unregister_character(self, character_id: str) -> None:
        self._characters.pop(character_id, None)
        self._agents.pop(character_id, None)
        self._names.pop(character_id, None)
        self.scene_map.remove_character(character_id)
        # MCP: leave scene
        try:
            from engine.mcp.framework import get_framework
            get_framework().get_character(character_id).leave_scene()
        except Exception:
            pass

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
        """Run one full decision cycle for all characters.

        Uses batch inference when multiple characters need decisions,
        giving the VirtualAgentManager the opportunity to parallelize.
        """
        self._tick_count += 1
        actions = []
        char_ids = list(self._characters.keys())
        random.shuffle(char_ids)

        # Phase 1: Perceive all characters first (no LLM calls)
        contexts: Dict[str, str] = {}
        for cid in char_ids:
            if cid in self._characters:
                try:
                    contexts[cid] = self._perceive(cid)
                except Exception as e:
                    logger.warning("Perceive error for %s: %s", cid, e)

        # Phase 2: Batch decide (all characters in parallel via manager)
        decisions: Dict[str, Dict] = {}
        decidable = [cid for cid in char_ids if cid in contexts]
        if len(decidable) > 1:
            try:
                decisions = self._decide_batch(decidable, contexts)
            except Exception as e:
                logger.warning("Batch decide failed, falling back to sequential: %s", e)
        # Sequential fallback for any missing decisions
        for cid in decidable:
            if cid not in decisions:
                try:
                    decisions[cid] = self._decide(cid, contexts[cid])
                except Exception as e:
                    logger.warning("Decide error for %s: %s", cid, e)
                    decisions[cid] = {"action": "idle", "target": "", "message": ""}

        # Phase 3: Execute all decisions
        for cid in char_ids:
            decision = decisions.get(cid, {"action": "idle", "target": "", "message": ""})
            try:
                result = self._execute(cid, decision)
                actions.append(result)
                if self._on_action:
                    self._on_action(cid, result)
            except Exception as e:
                logger.warning("Execute error for %s: %s", cid, e)
                actions.append({"character_id": cid, "action": "idle", "error": str(e)})

        # Emit tick summary to UI
        if self.socketio:
            self.socketio.emit("agent_tick", {
                "tick": self._tick_count,
                "actions": actions,
                "timestamp": datetime.now().isoformat(),
            })

        # MCPFramework tick — drains consequence queue, advances turn counter
        try:
            from engine.mcp.framework import get_framework
            get_framework().tick()
        except Exception:
            pass

        # ActivityBus: publish tick summary
        try:
            from engine.services.activity_bus import get_activity_bus
            bus = get_activity_bus()
            bus.publish(
                activity_type="agent_loop_tick",
                description=f"Tick {self._tick_count}: {len(actions)} actions in scene '{self.scene_id}'",
                agent_id="agent_loop",
                scene=self.scene_id,
                data={"tick": self._tick_count, "action_count": len(actions)},
            )
        except Exception:
            pass

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

        # All other characters — with their current locations so the model
        # understands the full scene, not just who is physically next to them.
        nearby = self.scene_map.get_nearby_characters(character_id)
        others_info = []
        for oid, other in self._characters.items():
            if oid == character_id:
                continue
            other_loc = self.scene_map.get_character_location(oid)
            loc_label = other_loc.name if other_loc else "unknown location"
            mood_str = getattr(other, 'mood', 'neutral')
            arousal_str = getattr(other, 'arousal', 0.0)
            closeness = "(nearby)" if oid in nearby else f"(at {loc_label})"
            others_info.append(
                f"{other.name} {closeness}: mood={mood_str}, "
                f"arousal={arousal_str:.0%}"
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
            f"\n## People in Scene\n{chr(10).join(others_info) if others_info else 'You are alone in the scene.'}\n"
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
        """Ask VirtualAgentManager for a structured action decision with mood/stat extraction."""
        character = self._characters[character_id]
        agent = self._agents.get(character_id)

        system = (
            f"You are {character.name}. You are in a scene with another person. "
            f"You must decide what to do next based on your mood, the situation, "
            f"and your personality. Be spontaneous and natural. "
            f"Respond ONLY with a JSON object — no extra text.\n"
            f"You may include [MOOD:emotion] to express your current feeling."
        )

        # Try agent.quick_query first (routes through VirtualAgentManager)
        if agent:
            try:
                response = agent.quick_query(system + "\n\n" + context, max_tokens=2000)
                if response:
                    return self._parse_decision(response)
            except Exception as e:
                logger.debug("agent.quick_query failed: %s", e)

        # Use VirtualAgentManager with infer_processed for rich response
        try:
            from engine.agents.virtual_agent_manager import get_virtual_agent_manager
            from engine.agents.virtual_agent import InferenceRequest
            mgr = get_virtual_agent_manager()
            request = InferenceRequest(
                agent_id=character_id,
                messages=[
                    {"role": "system", "content": system},
                    {"role": "user", "content": context},
                ],
                temperature=0.9,
                max_output_tokens=2000,
                structured_schema=DECISION_SCHEMA,
                schema_name="agent_decision",
                store=False,
                priority=3,
                metadata={"type": "agent_loop_decide", "scene": self.scene_id},
            )
            proc = mgr.infer_processed(request)
            text = proc.clean_text or proc.raw_text or ""
            if text:
                decision = self._parse_decision(text)
                # Enrich decision with mood from stream
                if proc.mood_tags:
                    decision["mood"] = proc.mood_tags[0]
                    self._update_character_mood(character_id, proc.mood_tags[0])
                if proc.action_tags:
                    decision["extra_actions"] = list(proc.action_tags)
                return decision
        except Exception as e:
            logger.debug("VirtualAgentManager decide failed: %s", e)

        return self._random_action(character_id)

    def _update_character_mood(self, character_id: str, mood: str) -> None:
        """Update character mood in MCP framework from stream-extracted tag."""
        try:
            from engine.mcp.framework import get_framework
            fw = get_framework()
            char_node = fw.get_character(character_id)
            if char_node:
                char_node.update_state({"mood": mood, "last_mood_source": "agent_loop"})
        except Exception:
            pass

    def _decide_batch(self, char_ids: List[str], contexts: Dict[str, str]) -> Dict[str, Dict]:
        """Batch-decide actions for multiple characters in parallel."""
        from engine.agents.virtual_agent_manager import get_virtual_agent_manager
        from engine.agents.virtual_agent import InferenceRequest
        mgr = get_virtual_agent_manager()

        requests = []
        ordered_ids = []
        for cid in char_ids:
            character = self._characters.get(cid)
            if not character:
                continue
            system = (
                f"You are {character.name}. You are in a scene with another person. "
                f"You must decide what to do next based on your mood, the situation, "
                f"and your personality. Be spontaneous and natural. "
                f"Respond ONLY with a JSON object — no extra text."
            )
            requests.append(InferenceRequest(
                agent_id=cid,
                messages=[
                    {"role": "system", "content": system},
                    {"role": "user", "content": contexts[cid]},
                ],
                temperature=0.9,
                max_output_tokens=2000,
                structured_schema=DECISION_SCHEMA,
                schema_name="agent_decision",
                priority=3,
                metadata={"type": "agent_loop_batch", "scene": self.scene_id},
            ))
            ordered_ids.append(cid)

        if not requests:
            return {}

        responses = mgr.infer_batch(requests)
        results = {}
        for cid, resp in zip(ordered_ids, responses):
            text = resp.content or resp.reasoning_content or ""
            if text:
                results[cid] = self._parse_decision(text)
            else:
                results[cid] = self._random_action(cid)
        return results

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

        # ActivityBus: publish every action for admin panel visibility
        try:
            from engine.services.activity_bus import get_activity_bus
            get_activity_bus().publish(
                activity_type=f"agent_{action}",
                description=result.get("description", f"{character.name} {action}"),
                agent_id=character_id,
                scene=self.scene_id,
                data={"action": action, "target": target, "message": message, "tick": self._tick_count},
            )
        except Exception:
            pass

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
