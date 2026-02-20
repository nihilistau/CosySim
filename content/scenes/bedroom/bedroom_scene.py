"""
3D Bedroom Scene — Multi-Agent Emergent Playground

Two characters occupy a bedroom with 7 interactive locations (bed, couch,
bar, bathroom, balcony, vanity, doorway).  An :class:`AgentLoop` runs a
tick-based decision cycle where each character autonomously perceives,
decides, and acts — producing emergent conversation, movement, flirtation,
and intimacy.

The user can **observe** (read-only) or **direct** (whisper to either agent
to influence their next decision).
"""

from flask import Flask, render_template, jsonify, request
from flask_socketio import SocketIO, emit
from flask_cors import CORS
from typing import Optional, Dict, List
import json
import random
from datetime import datetime
import os
import sys
from pathlib import Path

project_root = Path(__file__).parent.parent.parent
sys.path.insert(0, str(project_root))

from engine.scenes.base_scene import BaseScene
from engine.agents.agent_loop import AgentLoop
from engine.agents.character_agent import CharacterAgent
from engine.spatial.location import Location
from engine.spatial.scene_map import SceneMap
from content.simulation.database.db import Database
from content.simulation.character_system.character import Character


# ── Bedroom Locations ───────────────────────────────────────────────────
def _build_bedroom_map() -> SceneMap:
    """Create the default bedroom layout with 7 interactive locations."""
    sm = SceneMap()
    locations = [
        Location(
            id="bed", name="Bed",
            description="A large king-size bed with soft sheets and dim warm lighting.",
            interactions=["lie down", "cuddle", "pillow talk", "sleep", "get intimate"],
            capacity=2,
            properties={"privacy": 0.9, "comfort": 1.0, "spiciness": 5,
                        "pos": {"x": -3, "y": 0, "z": -3}},
        ),
        Location(
            id="couch", name="Couch",
            description="A plush velvet couch facing a large TV. Perfect for lounging.",
            interactions=["sit", "watch TV", "cuddle", "chat", "make out"],
            capacity=2,
            properties={"privacy": 0.5, "comfort": 0.8, "spiciness": 3,
                        "pos": {"x": 3, "y": 0, "z": 0}},
        ),
        Location(
            id="bar", name="Bar",
            description="A small home bar with mood lighting, bottles, and two stools.",
            interactions=["make a drink", "pour wine", "toast", "chat", "eat"],
            capacity=2,
            properties={"privacy": 0.3, "comfort": 0.5, "spiciness": 2,
                        "pos": {"x": 4, "y": 0, "z": -4}},
        ),
        Location(
            id="bathroom", name="Bathroom",
            description="A luxurious bathroom with a large bathtub, shower, and candles.",
            interactions=["shower", "take a bath", "freshen up", "share a bath"],
            capacity=2,
            properties={"privacy": 1.0, "comfort": 0.7, "spiciness": 5,
                        "pos": {"x": -5, "y": 0, "z": 2}},
        ),
        Location(
            id="balcony", name="Balcony",
            description="A romantic balcony overlooking the city skyline at night.",
            interactions=["gaze at stars", "smoke", "lean on railing", "chat", "kiss"],
            capacity=2,
            properties={"privacy": 0.2, "comfort": 0.4, "spiciness": 2,
                        "pos": {"x": 0, "y": 0, "z": -5}},
        ),
        Location(
            id="vanity", name="Vanity",
            description="An elegant vanity mirror with soft ring-light. Good for selfies.",
            interactions=["check mirror", "apply makeup", "take a selfie", "pose"],
            capacity=1,
            properties={"privacy": 0.4, "comfort": 0.5, "spiciness": 3,
                        "pos": {"x": -5, "y": 0, "z": -1}},
        ),
        Location(
            id="doorway", name="Doorway",
            description="The entrance to the bedroom. A neutral spot.",
            interactions=["enter", "leave", "greet", "lean against frame"],
            capacity=2,
            properties={"privacy": 0.1, "comfort": 0.2, "spiciness": 1,
                        "pos": {"x": 5, "y": 0, "z": 3}},
        ),
    ]
    for loc in locations:
        sm.add_location(loc)
    return sm


class BedroomScene(BaseScene):
    """Multi-agent 3D bedroom with emergent behaviour and spatial locations."""

    def __init__(self, host: str = "0.0.0.0", port: int = 5556):
        super().__init__(scene_name="bedroom", host=host, port=port)
        self.db = Database()

        # Spatial system
        self.scene_map = _build_bedroom_map()

        # Characters (max 2)
        self.characters: Dict[str, Character] = {}
        self.active_character: Optional[Character] = None  # compat

        # Agent loop
        self.agent_loop: Optional[AgentLoop] = None
        # Per-agent model config: {character_id: {"model": str, "mode": str}}
        # mode: "default" | "speculative" | "concurrent"
        self.agent_model_config: Dict[str, Dict] = {}

        # Lighting presets
        self.lighting_presets = {
            'morning':   {'ambient': 0.7, 'directional': 0.9, 'color': '#e8f4f8'},
            'afternoon': {'ambient': 0.6, 'directional': 0.8, 'color': '#fff8e8'},
            'evening':   {'ambient': 0.4, 'directional': 0.5, 'color': '#ffb088'},
            'night':     {'ambient': 0.2, 'directional': 0.3, 'color': '#6688cc'},
        }

        # Scene state
        self.scene_state = {
            'time_of_day': 'evening',
            'lighting': self.lighting_presets['evening'],
            'characters': {},      # id → {name, location, mood, arousal, …}
            'locations': {},       # id → {name, occupants, pos}
            'agent_loop_running': False,
            'mode': 'observe',     # observe | direct
        }
        self._refresh_location_state()

        # Flask
        self.app = Flask(
            __name__,
            template_folder=str(Path(__file__).parent / "templates"),
            static_folder=str(Path(__file__).parent / "static"),
        )
        self.app.config['SECRET_KEY'] = 'bedroom_scene_secret_2024'
        CORS(self.app)
        self.socketio = SocketIO(self.app, cors_allowed_origins="*", manage_session=False)

        self._setup_routes()
        self._setup_socketio()

    # ── Helpers ──────────────────────────────────────────────────────────
    def _refresh_location_state(self):
        """Rebuild the scene_state.locations dict from the SceneMap."""
        self.scene_state['locations'] = {}
        for loc in self.scene_map.locations:
            self.scene_state['locations'][loc.id] = {
                'name': loc.name,
                'description': loc.description,
                'interactions': loc.interactions,
                'occupants': loc.occupants,
                'pos': loc.properties.get('pos', {'x': 0, 'y': 0, 'z': 0}),
                'spiciness': loc.spiciness,
            }

    def _refresh_character_state(self):
        """Rebuild scene_state.characters from loaded Character objects."""
        self.scene_state['characters'] = {}
        for cid, char in self.characters.items():
            loc = self.scene_map.get_character_location(cid)
            self.scene_state['characters'][cid] = {
                'name': char.name,
                'mood': char.mood,
                'arousal': getattr(char, 'arousal', 0.0),
                'energy': getattr(char, 'energy', 1.0),
                'relationship_level': getattr(char, 'relationship_level', 0.5),
                'location': loc.name if loc else None,
                'location_id': loc.id if loc else None,
            }

    def _broadcast_state(self):
        """Push full state to all connected clients."""
        self._refresh_location_state()
        self._refresh_character_state()
        self.scene_state['agent_loop_running'] = (
            self.agent_loop.is_running if self.agent_loop else False
        )
        self.socketio.emit('scene_state', self.scene_state)

    def _load_character(self, char_id: str, slot: str = "a") -> Optional[Character]:
        """Load a character from DB and register in the scene."""
        if len(self.characters) >= 2 and char_id not in self.characters:
            return None  # max 2
        char = Character.load(char_id, db=self.db)
        if not char:
            return None
        self.characters[char.id] = char
        if not self.active_character:
            self.active_character = char
        # Place at a random empty location (or doorway)
        empty = self.scene_map.get_empty_locations()
        loc = random.choice(empty) if empty else self.scene_map.get_location("doorway")
        if loc:
            self.scene_map.place_character(char.id, loc.id)
        self._broadcast_state()
        return char

    # ── Routes ──────────────────────────────────────────────────────────
    def _setup_routes(self):

        @self.app.route('/')
        def index():
            return render_template('bedroom_ui.html')

        @self.app.route('/api/scene/state')
        def get_scene_state():
            self._refresh_location_state()
            self._refresh_character_state()
            return jsonify(self.scene_state)

        @self.app.route('/api/scene/time', methods=['POST'])
        def set_time():
            t = (request.json or {}).get('time', 'evening')
            self.scene_state['time_of_day'] = t
            self.scene_state['lighting'] = self.lighting_presets.get(t, self.lighting_presets['evening'])
            self.socketio.emit('time_changed', {
                'time': t, 'lighting': self.scene_state['lighting'],
            })
            return jsonify({'success': True})

        # ── Character management ────────────────────────────────────────
        @self.app.route('/api/characters/list')
        def list_characters():
            db_chars = self.db.get_all_characters()
            for c in db_chars:
                c['source'] = 'database'
                c['loaded'] = c['id'] in self.characters
            return jsonify({'characters': db_chars})

        @self.app.route('/api/character/load', methods=['POST'])
        def load_character():
            cid = (request.json or {}).get('character_id')
            if not cid:
                return jsonify({'error': 'No character_id'}), 400
            if len(self.characters) >= 2 and cid not in self.characters:
                return jsonify({'error': 'Maximum 2 characters in bedroom'}), 400
            char = self._load_character(cid)
            if not char:
                return jsonify({'error': 'Character not found'}), 404
            return jsonify({'success': True, 'character': {
                'id': char.id, 'name': char.name,
            }})

        @self.app.route('/api/character/remove', methods=['POST'])
        def remove_character():
            cid = (request.json or {}).get('character_id')
            if cid in self.characters:
                del self.characters[cid]
                self.scene_map.remove_character(cid)
                if self.agent_loop:
                    self.agent_loop.unregister_character(cid)
                self._broadcast_state()
            return jsonify({'success': True})

        @self.app.route('/api/characters/loaded')
        def loaded_characters():
            self._refresh_character_state()
            return jsonify({'characters': self.scene_state['characters']})

        # ── Spatial ─────────────────────────────────────────────────────
        @self.app.route('/api/location/move', methods=['POST'])
        def move_character():
            data = request.json or {}
            cid = data.get('character_id')
            loc_name = data.get('location')
            loc = self.scene_map.get_location_by_name(loc_name)
            if not loc or cid not in self.characters:
                return jsonify({'error': 'Invalid character or location'}), 400
            ok = self.scene_map.move_character(cid, loc.id)
            self._broadcast_state()
            return jsonify({'success': ok})

        @self.app.route('/api/locations')
        def list_locations():
            self._refresh_location_state()
            return jsonify({'locations': self.scene_state['locations']})

        # ── Agent Loop ──────────────────────────────────────────────────
        @self.app.route('/api/agents/start', methods=['POST'])
        def start_agent_loop():
            if len(self.characters) < 2:
                return jsonify({'error': 'Need 2 characters to start'}), 400
            interval = (request.json or {}).get('interval', 30)
            self._start_agent_loop(interval)
            return jsonify({'success': True, 'interval': interval})

        @self.app.route('/api/agents/stop', methods=['POST'])
        def stop_agent_loop():
            if self.agent_loop:
                self.agent_loop.stop()
            self.scene_state['agent_loop_running'] = False
            self._broadcast_state()
            return jsonify({'success': True})

        @self.app.route('/api/agents/tick', methods=['POST'])
        def manual_tick():
            """Force a single tick (useful for testing)."""
            if not self.agent_loop:
                self._start_agent_loop(interval=9999)  # create but don't auto-run
                self.agent_loop.stop()
            actions = self.agent_loop.tick()
            self._broadcast_state()
            return jsonify({'actions': actions})

        @self.app.route('/api/agents/whisper', methods=['POST'])
        def whisper():
            """User whispers a direction to one agent."""
            data = request.json or {}
            cid = data.get('character_id')
            msg = data.get('message', '')
            if cid not in self.characters:
                return jsonify({'error': 'Character not loaded'}), 400
            # Inject as context into the agent loop shared log
            if self.agent_loop:
                self.agent_loop.shared_log.append({
                    'name': '(Director)',
                    'text': f"[whisper to {self.characters[cid].name}] {msg}",
                    'timestamp': datetime.now().isoformat(),
                    'type': 'whisper',
                })
            return jsonify({'success': True})

        # ── Model selection ─────────────────────────────────────────────
        @self.app.route('/api/models/available')
        def list_models():
            """List models from LMStudio (loaded + available)."""
            models = {"loaded": [], "available": []}
            try:
                from engine.lmstudio.client_v2 import LMStudioClientV2
                client = LMStudioClientV2()
                loaded = client.get_models()
                models["loaded"] = [
                    {"id": m.get("id", ""), "object": m.get("object", "")}
                    for m in loaded
                ]
            except Exception:
                pass
            try:
                from engine.lmstudio.client import get_lmstudio_manager
                mgr = get_lmstudio_manager()
                available = mgr.get_available_models()
                models["available"] = [
                    {"id": m.get("path", m.get("id", "")), "size": m.get("size", "")}
                    for m in (available if isinstance(available, list) else [])
                ]
            except Exception:
                pass
            return jsonify(models)

        @self.app.route('/api/agents/model', methods=['POST'])
        def set_agent_model():
            """Set model + inference mode for a specific agent."""
            data = request.json or {}
            cid = data.get('character_id')
            model = data.get('model')  # model ID string
            mode = data.get('mode', 'default')  # default | speculative | concurrent
            if cid and cid in self.characters:
                self.agent_model_config[cid] = {"model": model, "mode": mode}
                return jsonify({'success': True, 'config': self.agent_model_config[cid]})
            return jsonify({'error': 'Character not loaded'}), 400

        @self.app.route('/api/agents/model', methods=['GET'])
        def get_agent_models():
            """Get current model config for all agents."""
            config = {}
            for cid in self.characters:
                cfg = self.agent_model_config.get(cid, {})
                config[cid] = {
                    "character": self.characters[cid].name,
                    "model": cfg.get("model"),
                    "mode": cfg.get("mode", "default"),
                }
            return jsonify(config)

        # ── Mode ────────────────────────────────────────────────────────
        @self.app.route('/api/mode', methods=['POST'])
        def set_mode():
            mode = (request.json or {}).get('mode', 'observe')
            self.scene_state['mode'] = mode
            self._broadcast_state()
            return jsonify({'success': True, 'mode': mode})

        # ── Scene persistence ───────────────────────────────────────────
        @self.app.route('/api/scene/save', methods=['POST'])
        def save_scene_route():
            name = (request.json or {}).get('name')
            self.scene_config['settings'] = {
                'time_of_day': self.scene_state['time_of_day'],
                'character_ids': list(self.characters.keys()),
                'map_snapshot': self.scene_map.snapshot(),
            }
            try:
                sid = self.save_scene(name)
                return jsonify({'success': True, 'scene_id': sid})
            except Exception as e:
                return jsonify({'error': str(e)}), 500

        @self.app.route('/api/scene/list')
        def list_scenes():
            try:
                scenes = self.asset_manager.search(asset_type='scene', limit=100)
                return jsonify({'scenes': scenes})
            except Exception as e:
                return jsonify({'error': str(e)}), 500

        @self.app.route('/api/history')
        def get_history():
            if self.agent_loop:
                return jsonify({'success': True, 'history': self.agent_loop.shared_log[-100:]})
            return jsonify({'success': True, 'history': []})

        # ── Ambient Audio ──────────────────────────────────────────────
        @self.app.route('/api/ambient/tracks')
        def list_ambient_tracks():
            audio_dir = Path(__file__).parent / 'static' / 'audio'
            audio_dir.mkdir(parents=True, exist_ok=True)
            exts = {'.mp3', '.wav', '.ogg', '.flac', '.m4a'}
            tracks = [f.name for f in audio_dir.iterdir()
                      if f.suffix.lower() in exts]
            return jsonify(sorted(tracks))

        # ── Menace Menu ────────────────────────────────────────────────
        @self.app.route('/api/menace', methods=['POST'])
        def menace_action():
            data = request.get_json(force=True)
            menace_type = data.get('type', 'unknown')
            event_messages = {
                'flicker_lights': 'The lights flicker and dim ominously.',
                'strange_sound': 'A strange, unidentifiable sound echoes through the room.',
                'cold_draft': 'A sudden icy draft sweeps through the room despite the closed windows.',
                'move_object': 'Something on the table shifts on its own.',
                'knock': 'Three slow, deliberate knocks come from the door — but nobody is there.',
                'power_out': 'The lights go completely dark for a few seconds.',
                'romantic_mood': 'The lighting shifts to a warm, intimate glow. Candles seem to brighten.',
                'thunder': 'A crack of thunder shakes the room, followed by a flash of lightning.',
            }
            msg = event_messages.get(menace_type, f'Something strange happens: {menace_type}')
            if self.agent_loop:
                self.agent_loop.shared_log.append({
                    'name': '(environment)',
                    'text': msg,
                    'timestamp': datetime.now().isoformat(),
                    'type': 'environment',
                })
            self.socketio.emit('menace_event', {
                'type': menace_type, 'message': msg,
            })
            return jsonify({'success': True, 'message': msg})

    # ── SocketIO ────────────────────────────────────────────────────────
    def _setup_socketio(self):

        @self.socketio.on('connect')
        def handle_connect():
            self._refresh_location_state()
            self._refresh_character_state()
            emit('scene_state', self.scene_state)

        @self.socketio.on('disconnect')
        def handle_disconnect():
            pass

        @self.socketio.on('request_state')
        def handle_request():
            self._broadcast_state()

        @self.socketio.on('chat_message')
        def handle_chat(data):
            msg = data.get('message', '')
            ts = datetime.now().isoformat()
            if self.agent_loop:
                self.agent_loop.shared_log.append({
                    'name': 'You', 'text': msg,
                    'timestamp': ts, 'type': 'speech',
                })
            self.socketio.emit('chat_message', {
                'name': 'You', 'message': msg, 'timestamp': ts,
            })

    # ── Agent Loop wiring ───────────────────────────────────────────────
    def _start_agent_loop(self, interval: float = 30):
        if self.agent_loop and self.agent_loop.is_running:
            return
        self.agent_loop = AgentLoop(
            scene_map=self.scene_map,
            db=self.db,
            socketio=self.socketio,
            scene_id='bedroom',
        )
        for cid, char in self.characters.items():
            # Use per-agent model if configured
            agent_cfg = self.agent_model_config.get(cid, {})
            agent_model = agent_cfg.get("model") or None
            agent = CharacterAgent(
                char,
                db=self.db,
                skill_packs=["memory", "character", "comfyui"],
                model=agent_model,
            )
            self.agent_loop.register_character(char, agent=agent)
        self.agent_loop.set_action_callback(self._on_agent_action)
        self.agent_loop.start(interval=interval)
        self.scene_state['agent_loop_running'] = True
        self._broadcast_state()

    def _on_agent_action(self, character_id: str, action: Dict):
        """Callback fired after every agent action — update UI."""
        self._broadcast_state()

    # ── BaseScene interface ─────────────────────────────────────────────
    def get_plugin_info(self) -> dict:
        return {
            "name": "Bedroom Scene",
            "description": "Multi-agent 3D bedroom with emergent behaviour, 7 locations, and spicy interactions",
            "version": "3.0.0",
            "author": "CosySim",
            "port": self.port,
            "tags": ["bedroom", "3d", "multi-agent", "emergent", "spatial", "intimate"],
            "skill_packs": ["memory", "character", "comfyui"],
        }

    def start(self) -> None:
        print("🛏️  Starting Multi-Agent Bedroom Scene...")
        print(f"   Access at: http://{self.host}:{self.port}")
        self.socketio.run(
            self.app, host=self.host, port=self.port,
            debug=False, allow_unsafe_werkzeug=True,
        )

    def stop(self) -> None:
        if self.agent_loop:
            self.agent_loop.stop()
        print("Bedroom scene stopped.")


if __name__ == '__main__':
    scene = BedroomScene(host='0.0.0.0', port=5556)
    scene.start()
