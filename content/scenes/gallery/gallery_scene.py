"""
THE OBSCURA — Gallery Scene v0.68 "Dark Renaissance"
=====================================================
Dark art gallery with disturbing and adult exhibits.  Characters inhabit the
roles of curator, critic, and private collector in a space where art confronts
the viewer across every comfort boundary.

• **Dark Renaissance aesthetic** — violet accent (#7c3aed), spotlight framing
• **ContentGate-gated exhibits** — adult pieces blur until private viewing unlocked
• **Economy integration** — private viewings cost 250 credits via EconomyManager
• **SceneArtManager** — commission new works via ComfyUI generation
• **SceneDirector** — narrative beats drive the exhibit's evolving mood
• **EventBus** — cross-scene events (gallery.commission, gallery.private_viewing)
• **MCP framework** — rules, state management, consequence chains

Port: 5560 (configurable)
"""
from __future__ import annotations

import json
import logging
import os
import random
import threading
import time
import uuid
from dataclasses import dataclass, field, asdict
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

from flask import Flask, jsonify, request, render_template
from flask_socketio import SocketIO, emit

from engine.paths import ROOT as project_root
import sys; sys.path.insert(0, str(project_root))

from engine.scenes.base_scene import BaseScene
from engine.scenes.nexus_mixin import NexusSceneMixin
from engine.mcp.framework import MCPSceneMixin, get_framework
from content.simulation.database.db import Database
from content.shared import register_shared_assets
from engine.mcp.scene_state import get_scene_state_manager
from engine.mcp.tag_registry import TagRegistry
from content.scenes.gallery.gallery_rules import register_gallery_rules

try:
    from engine.world.world_state import get_world_state
    from engine.events.event_bus import get_event_bus, EventBus
    _WORLD_AVAILABLE = True
except ImportError:
    _WORLD_AVAILABLE = False

logger = logging.getLogger(__name__)

SCENE_ID = "gallery"
_SCENE_ROOT = Path(__file__).parent

# ── Art & Gallery Data ─────────────────────────────────────────────────────────

ART_STYLES = [
    "impressionist", "surrealist", "abstract", "renaissance", "pop_art",
    "art_deco", "minimalist", "cyberpunk", "gothic", "baroque",
]

GALLERY_ROOMS = {
    "main_hall": {
        "name": "Main Hall",
        "description": "Grand entrance with marble floors and skylights.",
        "capacity": 10,
        "lighting": "bright natural",
    },
    "modern_wing": {
        "name": "Modern Wing",
        "description": "Stark white walls, spotlights on bold contemporary pieces.",
        "capacity": 6,
        "lighting": "dramatic spots",
    },
    "sculpture_garden": {
        "name": "Sculpture Garden",
        "description": "Open courtyard with bronze and stone works amid greenery.",
        "capacity": 8,
        "lighting": "dappled sunlight",
    },
    "dark_room": {
        "name": "The Dark Room",
        "description": "A dimly-lit chamber for projected and illuminated art.",
        "capacity": 4,
        "lighting": "ultraviolet and projection",
    },
    "private_collection": {
        "name": "Private Collection",
        "description": "Invitation-only vault with rare and controversial pieces.",
        "capacity": 3,
        "lighting": "warm amber",
    },
}

PREMADE_EXHIBITIONS = {
    "dreams_unveiled": {
        "label": "Dreams Unveiled",
        "emoji": "🌙",
        "theme": "Surreal dreamscapes and subconscious imagery",
        "style_hint": "surrealist",
        "seed_artworks": [
            {"title": "The Melting Clock Tower", "style": "surrealist",
             "description": "A towering clock dissolves into a river of time"},
            {"title": "Doors to Nowhere", "style": "surrealist",
             "description": "Floating doors open to impossible landscapes"},
        ],
    },
    "neon_futures": {
        "label": "Neon Futures",
        "emoji": "🔮",
        "theme": "Cyberpunk visions of technology and humanity",
        "style_hint": "cyberpunk",
        "seed_artworks": [
            {"title": "Neural Bloom", "style": "cyberpunk",
             "description": "A brain made of neon circuitry blooming with flowers"},
            {"title": "The Last Sunset.exe", "style": "cyberpunk",
             "description": "A pixelated sunset over a digital ocean"},
        ],
    },
    "raw_emotions": {
        "label": "Raw Emotions",
        "emoji": "💔",
        "theme": "Abstract expressions of love, loss, and desire",
        "style_hint": "abstract",
        "seed_artworks": [
            {"title": "Shattered Embrace", "style": "abstract",
             "description": "Two figures fragmenting into each other in vivid red"},
            {"title": "Whisper of Touch", "style": "abstract",
             "description": "Soft overlapping gradients suggesting intimate contact"},
        ],
    },
}

# ── THE OBSCURA Permanent Collection ──────────────────────────────────────────

OBSCURA_PIECES: List[Dict] = [
    {
        "id": "ob_001",
        "title": "Anatomia Proibita",
        "artist": "Unknown, 1887",
        "medium": "oil on canvas",
        "description": "A medical illustration turned fever dream. Bodies dissected into component desires.",
        "intensity": 2,
        "tags": ["disturbing", "adult:violent"],
        "adult": True,
        "placeholder_gradient": "linear-gradient(135deg, #1a0a2e 0%, #3d1a4a 100%)",
    },
    {
        "id": "ob_002",
        "title": "The Collector's Appetite",
        "artist": "M. Veyne",
        "medium": "mixed media",
        "description": "Objects of obsession mounted and labeled. The viewer becomes the specimen.",
        "intensity": 1,
        "tags": ["disturbing"],
        "adult": False,
        "placeholder_gradient": "linear-gradient(135deg, #0a1628 0%, #1e2d4a 100%)",
    },
    {
        "id": "ob_003",
        "title": "Rapture Studies I\u2013IV",
        "artist": "Anonymous",
        "medium": "charcoal",
        "description": "Four panels documenting states of extreme sensation. Clinical yet intimate.",
        "intensity": 3,
        "tags": ["explicit", "adult:sexual"],
        "adult": True,
        "placeholder_gradient": "linear-gradient(135deg, #2a0a0a 0%, #4a1a1a 100%)",
    },
    {
        "id": "ob_004",
        "title": "Last Rites (After Goya)",
        "artist": "D. Mercer",
        "medium": "oil on canvas",
        "description": "Figures in extremis. The line between ecstasy and suffering, indistinguishable.",
        "intensity": 2,
        "tags": ["violent", "disturbing"],
        "adult": False,
        "placeholder_gradient": "linear-gradient(135deg, #0d0d1a 0%, #2a1a3a 100%)",
    },
    {
        "id": "ob_005",
        "title": "Taxonomy of Hunger",
        "artist": "K. Voss",
        "medium": "ink and gold leaf",
        "description": "A bestiary of human appetites illustrated in the style of medieval manuscripts.",
        "intensity": 2,
        "tags": ["disturbing", "adult:violent"],
        "adult": True,
        "placeholder_gradient": "linear-gradient(135deg, #1a1400 0%, #3d3200 100%)",
    },
    {
        "id": "ob_006",
        "title": "Portrait of the Warden",
        "artist": "Unknown",
        "medium": "daguerreotype, altered",
        "description": "A face composed of faces. All of them consenting. None of them present.",
        "intensity": 1,
        "tags": ["unsettling"],
        "adult": False,
        "placeholder_gradient": "linear-gradient(135deg, #0a0a0a 0%, #2a2a2a 100%)",
    },
    {
        "id": "ob_007",
        "title": "The Architecture of Transgression",
        "artist": "R. Sade (attr.)",
        "medium": "architectural drawing",
        "description": "Blueprint for a structure designed for a single, unstated purpose.",
        "intensity": 3,
        "tags": ["explicit", "adult:sexual"],
        "adult": True,
        "placeholder_gradient": "linear-gradient(135deg, #0a1a0a 0%, #1a3a2a 100%)",
    },
    {
        "id": "ob_008",
        "title": "Piet\u00e0 (Secular)",
        "artist": "A. Blackwood",
        "medium": "sculpture, resin",
        "description": "A reversal of comfort. The mourner and the mourned exchange positions endlessly.",
        "intensity": 1,
        "tags": ["disturbing", "grief"],
        "adult": False,
        "placeholder_gradient": "linear-gradient(135deg, #1a1a2e 0%, #0a0a1a 100%)",
    },
]


@dataclass
class Artwork:
    """A piece of art in the gallery."""
    id: str = ""
    title: str = ""
    style: str = ""
    description: str = ""
    room: str = "main_hall"
    artist_id: str = ""
    image_prompt: str = ""
    image_path: Optional[str] = None
    evaluations: List[Dict] = field(default_factory=list)
    created_at: str = ""

    def to_dict(self) -> Dict:
        return asdict(self)


@dataclass
class GalleryCharacter:
    """A character with a gallery-specific role."""
    char_id: str = ""
    name: str = ""
    role: str = "visitor"  # curator, critic, artist, visitor
    specialty: str = ""
    personality_style: str = ""
    current_room: str = "main_hall"
    mood: str = "neutral"
    artworks_evaluated: int = 0

    def to_dict(self) -> Dict:
        return asdict(self)


# ── Gallery Scene ──────────────────────────────────────────────────────────────

class GalleryScene(BaseScene, MCPSceneMixin, NexusSceneMixin, mcp_scene_id=SCENE_ID):
    """Interactive art gallery — v2.7 framework showcase."""

    SCENE_METADATA = {
        "name": "gallery",
        "display_name": "THE OBSCURA",
        "port": 5560,
        "type": "narrative",
        "accent_color": "#7c3aed",
        "accent_rgb": "124 58 237",
        "description": "Art is violence. The exhibit changes you. You cannot unsee it.",
        "features": [
            "image_generation", "content_gate", "economy",
            "scene_director", "event_bus", "character_memory",
        ],
    }

    def __init__(self, host: str = "0.0.0.0", port: int = 5560):
        super().__init__(scene_name="gallery", host=host, port=port)
        self.db = Database()

        # Gallery state
        self.artworks: Dict[str, Artwork] = {}
        self.characters: Dict[str, GalleryCharacter] = {}
        self.active_exhibition: Optional[str] = None
        self.gallery_log: List[Dict] = []

        # Streaming enabled by default (v2.7 showcase)
        self.streaming_enabled = True

        # Background ticker
        self._ticker_stop = threading.Event()
        self._ticker_thread: Optional[threading.Thread] = None

        # Flask
        self.app = Flask(
            __name__,
            template_folder=str(_SCENE_ROOT / "templates"),
            static_folder=str(_SCENE_ROOT / "static"),
        )
        register_shared_assets(self.app)
        self.register_health_route(self.app)
        self.register_hud_route(self.app)
        self.register_announcer_route(self.app)
        self.app.secret_key = os.urandom(24)
        self.socketio = SocketIO(self.app, cors_allowed_origins="*", async_mode="threading")

        try:
            from engine.overlay import mount_overlay
            mount_overlay(self.app, self.socketio)
        except Exception:
            pass

        self._register_routes()
        self._register_socketio()

        # Framework integration
        self._state_mgr = get_scene_state_manager()
        self._tag_registry = TagRegistry.get()
        self._governors: Dict[str, Any] = {}  # char_id → governor

        self.nexus_init("gallery")

        # Bench & TTS helpers (BaseScene-provided)
        try:
            self.register_bench_route(self.app, self.socketio)
            self.register_tts_route(self.app)
        except Exception:
            pass

        # THE OBSCURA state
        self._curator_mood: str = "contemplative"

    def _get_governor_context(self, char_id: str) -> str:
        """
        Gather framework context via the interceptor pipeline.

        Uses build_governance_context() which runs the full interceptor PRE
        phase to generate directives (mood drift, heat, personality, rules).
        """
        try:
            from engine.mcp.comms_framework import build_governance_context
            ctx = build_governance_context(char_id, "gallery", "")
            if ctx:
                return ctx
        except Exception:
            pass
        # Fallback: basic state info
        lines: List[str] = []
        try:
            from engine.mcp.state_coordinator import get_coordinator
            state = get_coordinator().get_full_state(char_id)
            if state:
                mood = state.get("mood", "neutral")
                energy = state.get("energy", 50)
                lines.append(f"Current mood: {mood} | Energy: {energy:.0f}")
        except Exception:
            pass
        return "\n".join(lines)

    # ── Lifecycle ───────────────────────────────────────────────────────────

    def start(self) -> None:
        self._seed_characters()
        try:
            self._mcp_init()
            register_gallery_rules()
            fw = get_framework()
            fw.on("artwork_created", lambda evt: self._on_art_event(evt))
        except Exception as exc:
            logger.warning("MCP init skipped: %s", exc)
        # ── World State ──────────────────────────────────────────────
        self._world_state = None
        self._event_bus = None
        if _WORLD_AVAILABLE:
            self._world_state = get_world_state()
            self._event_bus = get_event_bus()
            self._event_bus.subscribe("world.tick", self._on_world_tick)
            self._event_bus.subscribe("world.time_change", self._on_time_change)
        # Start background ticker for ambient updates
        self._start_ticker()
        logger.info("GalleryScene started on %s:%s", self.host, self.port)
        self.socketio.run(self.app, host=self.host, port=self.port, debug=False,
                          use_reloader=False, allow_unsafe_werkzeug=True)

    def stop(self) -> None:
        self.nexus_flush()
        self._ticker_stop.set()
        if hasattr(self, "_event_bus") and self._event_bus:
            try:
                self._event_bus.unsubscribe("world.tick", self._on_world_tick)
                self._event_bus.unsubscribe("world.time_change", self._on_time_change)
            except Exception:
                pass
        if self._ticker_thread and self._ticker_thread.is_alive():
            self._ticker_thread.join(timeout=3)
        try:
            get_framework().save_state()
        except Exception:
            pass
        logger.info("GalleryScene stopped")

    # ── World State handlers ──────────────────────────────────────────
    def _on_world_tick(self, event: dict) -> None:
        """React to world simulation tick."""
        if hasattr(self, "socketio") and self.socketio:
            try:
                time_data = self._world_state.get_time()
                self.socketio.emit("world_tick", {
                    "hour": getattr(time_data, "hour", 0),
                    "day": getattr(time_data, "day", 1),
                    "weather": str(getattr(time_data, "weather", "clear")),
                })
            except Exception:
                pass

    def _on_time_change(self, event: dict) -> None:
        """Rotate featured exhibit at midnight."""
        if event.get("hour", 0) == 0 and hasattr(self, "socketio") and self.socketio:
            self.socketio.emit("exhibit_rotate", {})

    def _start_ticker(self, interval: float = 45.0) -> None:
        """Background loop for ambient gallery events."""
        def _loop():
            while not self._ticker_stop.is_set():
                self._ticker_stop.wait(interval)
                if self._ticker_stop.is_set():
                    break
                try:
                    self._gallery_tick()
                except Exception as e:
                    logger.debug("Gallery tick error: %s", e)

        self._ticker_thread = threading.Thread(
            target=_loop, daemon=True, name="GalleryTicker"
        )
        self._ticker_thread.start()

    def _gallery_tick(self) -> None:
        """Periodic ambient update — mood decay, visitor events, state broadcast."""
        if not self.characters:
            return

        changes = []

        for cid, char in self.characters.items():
            # Mood drift (small random walk)
            old_mood = char.mood
            drift = random.choice([-0.02, -0.01, 0.0, 0.01, 0.02])
            char.mood = max(0.0, min(1.0, char.mood + drift))
            if abs(char.mood - old_mood) > 0.01:
                changes.append(f"{cid}: mood {old_mood:.2f}→{char.mood:.2f}")

        # Random ambient event (10% chance per tick)
        if random.random() < 0.10 and self.artworks:
            artwork = random.choice(list(self.artworks.values()))
            events = [
                f"A visitor pauses to admire '{artwork.title}'.",
                f"Light shifts across '{artwork.title}', revealing new details.",
                f"Quiet murmurs of appreciation surround '{artwork.title}'.",
            ]
            event_msg = random.choice(events)
            self.gallery_log.append({
                "time": datetime.now().isoformat(),
                "type": "ambient",
                "message": event_msg,
            })
            changes.append(event_msg)

        # Broadcast state if anything changed
        if changes:
            try:
                self.socketio.emit("gallery_update", {
                    "characters": {cid: c.to_dict() for cid, c in self.characters.items()},
                    "log": self.gallery_log[-5:],
                })
            except Exception:
                pass

    def get_plugin_info(self) -> Dict[str, Any]:
        return {
            "name": "THE OBSCURA",
            "scene_id": SCENE_ID,
            "display_name": "THE OBSCURA",
            "description": "Dark art gallery with disturbing and adult exhibits. v0.68 Dark Renaissance.",
            "version": "0.68",
            "port": self.port,
            "skill_packs": ["gallery"],
            "features": ["content_gate", "economy", "scene_director", "event_bus", "image_gen"],
            "accent_color": "#7c3aed",
        }

    def _on_art_event(self, evt) -> None:
        try:
            self.socketio.emit("art_event", evt.payload)
        except Exception:
            pass

    # ── Character Seeding ──────────────────────────────────────────────────

    def _seed_characters(self) -> None:
        """Load characters and assign gallery roles."""
        try:
            chars = self.db.get_all_characters()
            roles = ["curator", "critic", "artist", "visitor"]
            specialties = {
                "curator": "exhibition design and art history",
                "critic": "evaluating composition, technique, and emotional impact",
                "artist": "creating new works inspired by the current exhibition",
                "visitor": "experiencing art with fresh eyes",
            }
            for i, row in enumerate(chars[:4]):
                char_id = str(row.get("id") or row.get("character_id") or "")
                if not char_id:
                    continue
                role = roles[i % len(roles)]
                gc = GalleryCharacter(
                    char_id=char_id,
                    name=row.get("name", char_id),
                    role=role,
                    specialty=specialties.get(role, ""),
                    personality_style=row.get("personality", ""),
                    current_room="main_hall",
                )
                self.characters[char_id] = gc
                try:
                    fw = get_framework()
                    fw.get_character(char_id).enter_scene(SCENE_ID)
                    fw.get_character(char_id).update_state({"role": role})
                except Exception:
                    pass
            logger.info("Seeded %d gallery characters", len(self.characters))
        except Exception as exc:
            logger.warning("Character seeding failed: %s", exc)

    # ── Core: Streaming Art Evaluation (v2.7 Showcase) ─────────────────────

    def _evaluate_artwork(self, char_id: str, artwork: Artwork) -> Dict[str, Any]:
        """
        Have a character evaluate an artwork using infer_processed().
        Demonstrates: streaming, mood extraction, structured + free-form hybrid.
        """
        gc = self.characters.get(char_id)
        if not gc:
            return {"error": "Character not in gallery"}

        char = self.db.get_character(char_id)
        name = gc.name
        role = gc.role

        system = (
            f"You are {name}, a {role} at an art gallery.\n"
            f"Your specialty: {gc.specialty}\n"
            f"Your personality: {gc.personality_style}\n\n"
            f"Express your reaction using [MOOD:emotion] tags.\n"
            f"If inspired to create something, use [IMAGE:prompt description].\n"
            f"If you take an action, use [ACTION:description].\n"
            f"Be vivid, opinionated, and authentic."
        )
        # Enrich with framework state (mood, heat, narrative)
        gov_ctx = self._get_governor_context(char_id)
        if gov_ctx:
            system = f"{system}\n\n{gov_ctx}"
        prompt = (
            f"You are viewing: \"{artwork.title}\"\n"
            f"Style: {artwork.style}\n"
            f"Description: {artwork.description}\n"
            f"Room: {GALLERY_ROOMS.get(artwork.room, {}).get('name', artwork.room)}\n\n"
            f"Give your honest reaction as a {role}. What do you see? How does it make you feel? "
            f"Rate it 1-10 for technique and emotional impact."
        )

        result = {
            "evaluator": name,
            "role": role,
            "artwork_id": artwork.id,
            "text": "",
            "mood": None,
            "image_requests": [],
            "action_tags": [],
            "scores": {},
        }

        try:
            from engine.agents.virtual_agent_manager import get_virtual_agent_manager
            from engine.agents.virtual_agent import InferenceRequest
            mgr = get_virtual_agent_manager()

            req = InferenceRequest(
                agent_id=char_id,
                messages=[
                    {"role": "system", "content": system},
                    {"role": "user", "content": prompt},
                ],
                temperature=0.85,
                max_output_tokens=3000,
                store=False,
                metadata={"scene": SCENE_ID, "type": "art_evaluation"},
            )

            # Stream with real-time callbacks to UI
            def on_delta(text):
                self.socketio.emit("evaluation_delta", {
                    "char_id": char_id, "artwork_id": artwork.id, "text": text,
                })

            def on_mood(mood):
                gc.mood = mood
                self.socketio.emit("mood_change", {
                    "char_id": char_id, "mood": mood,
                })

            proc = mgr.infer_processed(req, on_delta=on_delta, on_mood=on_mood)

            result["text"] = (proc.clean_text or "").strip()
            result["mood"] = proc.mood_tags[0] if proc.mood_tags else None
            result["image_requests"] = list(proc.image_requests)
            result["action_tags"] = list(proc.action_tags)

            # Update character state
            gc.artworks_evaluated += 1
            if result["mood"]:
                gc.mood = result["mood"]
                try:
                    from engine.mcp.state_coordinator import get_coordinator
                    get_coordinator().update(
                        char_id,
                        mood=result["mood"],
                        source="gallery_evaluation",
                        scene=SCENE_ID,
                    )
                except Exception:
                    pass
                try:
                    fw = get_framework()
                    fw.get_character(char_id).update_state({
                        "artworks_evaluated": gc.artworks_evaluated,
                    })
                except Exception:
                    pass

            # Store evaluation on artwork
            artwork.evaluations.append({
                "evaluator": name,
                "role": role,
                "text": result["text"],
                "mood": result["mood"],
                "timestamp": datetime.now().isoformat(),
            })

        except Exception as exc:
            logger.error("Evaluation failed for %s: %s", char_id, exc)
            result["text"] = f"({name} is speechless before this work.)"

        return result

    # ── Core: Structured Art Critique (v2.7 Showcase) ──────────────────────

    def _structured_critique(self, char_id: str, artwork: Artwork) -> Dict[str, Any]:
        """
        Demonstrates SceneAgent.run_structured() — JSON schema output.
        Returns a typed evaluation with technique, emotion, originality scores.
        """
        gc = self.characters.get(char_id)
        if not gc:
            return {"error": "Character not in gallery"}

        try:
            from engine.agents.scene_agent import SceneAgent
            agent = SceneAgent(scene_id=SCENE_ID)
            schema = {
                "type": "object",
                "properties": {
                    "technique_score": {"type": "integer", "minimum": 1, "maximum": 10},
                    "emotion_score": {"type": "integer", "minimum": 1, "maximum": 10},
                    "originality_score": {"type": "integer", "minimum": 1, "maximum": 10},
                    "one_word_reaction": {"type": "string"},
                    "would_buy": {"type": "boolean"},
                    "suggested_price": {"type": "string"},
                },
                "required": ["technique_score", "emotion_score", "originality_score", "one_word_reaction"],
            }

            prompt = (
                f"You are {gc.name}, a {gc.role}.\n"
                f"Evaluate \"{artwork.title}\" ({artwork.style}): {artwork.description}\n"
                f"Provide a structured JSON critique."
            )

            result = agent.run_structured(prompt, schema=schema, schema_name="art_critique")
            return result if isinstance(result, dict) else {"raw": str(result)}
        except Exception as exc:
            logger.error("Structured critique failed: %s", exc)
            return {"technique_score": 5, "emotion_score": 5, "originality_score": 5,
                    "one_word_reaction": "interesting", "would_buy": False}

    # ── Core: Art Debate with Branching (v2.7 Showcase) ────────────────────

    def _debate_artwork(self, artwork: Artwork, char_ids: List[str] = None) -> Dict[str, Any]:
        """
        Demonstrates try_alternatives() — generate multiple interpretations,
        then characters respond to each other.
        """
        if not char_ids:
            char_ids = list(self.characters.keys())[:2]

        debate_log = []
        for char_id in char_ids:
            gc = self.characters.get(char_id)
            if not gc:
                continue

            try:
                from engine.mcp.dialog_system import DialogSystem
                dialog = DialogSystem()

                # Generate 2 alternative interpretations, pick the more interesting one
                alternatives = []
                try:
                    from engine.agents.scene_agent import SceneAgent
                    agent = SceneAgent(scene_id=SCENE_ID)
                    for i in range(2):
                        prompt = (
                            f"You are {gc.name}, a {gc.role}.\n"
                            f"Artwork: \"{artwork.title}\" — {artwork.description}\n"
                            f"Previous debate: {json.dumps(debate_log[-2:]) if debate_log else 'none'}\n"
                            f"Give interpretation #{i+1}. Be {'bold and contrarian' if i else 'thoughtful and deep'}."
                        )
                        text = agent.run(prompt) or ""
                        alternatives.append({"text": text.strip(), "approach": "contrarian" if i else "thoughtful"})
                except Exception:
                    pass

                # Pick the longer/more substantive one
                best = max(alternatives, key=lambda a: len(a.get("text", ""))) if alternatives else {"text": ""}

                if best.get("text"):
                    debate_log.append({
                        "speaker": gc.name,
                        "role": gc.role,
                        "text": best["text"],
                        "approach": best.get("approach", ""),
                        "timestamp": datetime.now().isoformat(),
                    })

            except Exception as exc:
                logger.error("Debate failed for %s: %s", char_id, exc)

        # Emit debate as gallery event
        self.socketio.emit("debate", {
            "artwork_id": artwork.id,
            "artwork_title": artwork.title,
            "debate": debate_log,
        })

        return {"artwork_id": artwork.id, "debate": debate_log}

    # ── Core: Create Art (v2.7 Image Gen Showcase) ─────────────────────────

    def _create_artwork(self, char_id: str, theme: str = "") -> Optional[Artwork]:
        """Have an artist character create a new artwork with image generation."""
        gc = self.characters.get(char_id)
        if not gc:
            return None

        try:
            from engine.agents.virtual_agent_manager import get_virtual_agent_manager
            from engine.agents.virtual_agent import InferenceRequest
            mgr = get_virtual_agent_manager()

            exhibition = PREMADE_EXHIBITIONS.get(self.active_exhibition, {})
            style_hint = exhibition.get("style_hint", random.choice(ART_STYLES))

            system = (
                f"You are {gc.name}, an artist at a gallery.\n"
                f"Create a new artwork. Use [IMAGE:detailed visual description] to describe what it looks like.\n"
                f"Style guidance: {style_hint}\n"
                f"Theme: {theme or exhibition.get('theme', 'express yourself freely')}\n"
                f"Include [MOOD:emotion] for how creating this makes you feel."
            )
            # Enrich with framework state
            gov_ctx = self._get_governor_context(char_id)
            if gov_ctx:
                system = f"{system}\n\n{gov_ctx}"

            req = InferenceRequest(
                agent_id=char_id,
                messages=[
                    {"role": "system", "content": system},
                    {"role": "user", "content": "Create your masterpiece. Describe it and give it a title."},
                ],
                temperature=0.95,
                max_output_tokens=2000,
                store=False,
                metadata={"scene": SCENE_ID, "type": "art_creation"},
            )

            proc = mgr.infer_processed(req)
            title = proc.clean_text.split("\n")[0][:80] if proc.clean_text else "Untitled"
            # Clean up title — remove leading "Title:" etc
            for prefix in ("Title:", "title:", "**", "#"):
                title = title.lstrip(prefix).strip()
            title = title.strip('"\'')

            art = Artwork(
                id=str(uuid.uuid4())[:8],
                title=title or "Untitled",
                style=style_hint,
                description=proc.clean_text or "",
                room=gc.current_room,
                artist_id=char_id,
                image_prompt=proc.image_requests[0] if proc.image_requests else "",
                created_at=datetime.now().isoformat(),
            )

            # Attempt ComfyUI image generation if we got an image prompt
            if art.image_prompt:
                try:
                    from content.simulation.services.comfyui_client import get_comfyui_client
                    comfy = get_comfyui_client()
                    path = comfy.generate_image(prompt=art.image_prompt, character_name=gc.name)
                    if path:
                        art.image_path = str(path)
                except Exception as img_exc:
                    logger.debug("ComfyUI generation skipped: %s", img_exc)

            self.artworks[art.id] = art

            # Update mood
            if proc.mood_tags:
                gc.mood = proc.mood_tags[0]

            # Emit event
            self.socketio.emit("artwork_created", art.to_dict())
            try:
                get_framework().emit_event("artwork_created", {
                    "scene_id": SCENE_ID, "char_id": char_id,
                    "artwork_id": art.id, "title": art.title,
                }, source=SCENE_ID)
            except Exception:
                pass

            self._log("artwork_created", f"{gc.name} created '{art.title}'")
            return art

        except Exception as exc:
            logger.error("Create artwork failed: %s", exc)
            return None

    # ── Gallery Log ────────────────────────────────────────────────────────

    def _log(self, event_type: str, text: str) -> None:
        entry = {
            "type": event_type,
            "text": text,
            "timestamp": datetime.now().isoformat(),
        }
        self.gallery_log.append(entry)
        if len(self.gallery_log) > 200:
            self.gallery_log = self.gallery_log[-100:]
        self.socketio.emit("gallery_log", entry)

    # ── THE OBSCURA Helpers ────────────────────────────────────────────────

    def _get_pieces(self) -> List[Dict]:
        """Return OBSCURA permanent collection, merged with any commissioned artworks."""
        pieces = [dict(p) for p in OBSCURA_PIECES]
        for art in self.artworks.values():
            pieces.append({
                "id": art.id,
                "title": art.title,
                "artist": "Commissioned",
                "medium": art.style,
                "description": art.description,
                "intensity": 1,
                "tags": [],
                "adult": False,
                "placeholder_gradient": "linear-gradient(135deg, #1a1a2e 0%, #2a0a3a 100%)",
                "image_url": art.image_path,
            })
        return pieces

    def _get_piece_detail(self, piece_id: str) -> Optional[Dict]:
        """Return enriched piece dict with curator commentary."""
        piece = next((p for p in OBSCURA_PIECES if p["id"] == piece_id), None)
        if not piece:
            art = self.artworks.get(piece_id)
            if art:
                piece = {
                    "id": art.id, "title": art.title, "artist": "Commissioned",
                    "medium": art.style, "description": art.description,
                    "tags": [], "adult": False, "intensity": 1,
                    "image_url": art.image_path,
                }
        if not piece:
            return None
        commentary = self._default_commentary(piece)
        try:
            from engine.content.content_engine import get_content_engine
            item = get_content_engine().get_scenario(
                "gallery", intensity=piece.get("intensity", 1)
            )
            if item and item.content:
                commentary = item.content[:300]
        except Exception:
            pass
        return {**piece, "commentary": commentary}

    def _default_commentary(self, piece: Dict) -> str:
        """Static curator commentary based on piece tags."""
        tag_comments = {
            "adult:sexual": "The body rendered as text. Read it carefully.",
            "adult:violent": "Violence made beautiful. This is the gallery's mandate.",
            "explicit": "Explicit in every sense the word allows. Proceed deliberately.",
            "violent": "Suffering as subject matter. The artist does not flinch.",
            "disturbing": "The work unsettles without apology. Sit with that discomfort.",
            "unsettling": "Something here will stay with you. We cannot say what.",
            "grief": "Loss made visible. The absence is the subject.",
        }
        for tag in piece.get("tags", []):
            if tag in tag_comments:
                return tag_comments[tag]
        return "The curator offers no comment. Let the work speak."

    # ── Socket.IO ──────────────────────────────────────────────────────────

    def _register_socketio(self) -> None:
        @self.socketio.on("connect")
        def on_connect():
            emit("gallery_state", self._get_state())

        @self.socketio.on("request_state")
        def on_request():
            emit("gallery_state", self._get_state())

        @self.socketio.on("get_gallery_state")
        def on_get_gallery_state():
            """Emit full gallery state: current_exhibit, pieces, curator_mood."""
            emit("gallery_state", self._get_state())

        @self.socketio.on("view_piece")
        def on_view_piece(data):
            """Detailed piece view with curator commentary."""
            piece_id = (data or {}).get("piece_id", "")
            detail = self._get_piece_detail(piece_id)
            if detail:
                intensity = detail.get("intensity", 1)
                moods = ["contemplative", "unsettled", "disturbed", "transgressed"]
                self._curator_mood = moods[min(intensity, len(moods) - 1)]
                emit("piece_detail", detail)
                self._log("view_piece", f"Piece viewed: '{detail.get('title', piece_id)}'")
            else:
                emit("piece_not_found", {"piece_id": piece_id})

        @self.socketio.on("get_private_viewing")
        def on_private_viewing(data):
            """Adult-gated exhibit access. Requires ContentGate clearance + 250 credits."""
            piece_id = (data or {}).get("piece_id", "")
            piece = next((p for p in OBSCURA_PIECES if p["id"] == piece_id), None)
            if not piece:
                emit("private_viewing_denied", {
                    "reason": "Exhibit not found in the permanent collection."
                })
                return

            # Content gate check
            adult_tags = [t for t in piece.get("tags", []) if t.startswith("adult:")]
            if adult_tags:
                try:
                    from engine.content.content_gate import get_content_gate
                    if not get_content_gate().can_show(adult_tags):
                        emit("private_viewing_denied", {
                            "reason": "Content profile does not permit access to this exhibit."
                        })
                        return
                except Exception:
                    pass  # Gate unavailable — proceed

            # Economy spend
            try:
                from engine.economy.economy import get_economy_manager, TransactionType
                em = get_economy_manager()
                balance = em.get_balance()
                if balance < 250:
                    emit("private_viewing_denied", {
                        "reason": (
                            f"Insufficient funds — 250 credits required. "
                            f"Balance: {balance}."
                        )
                    })
                    return
                em.transact(
                    -250, TransactionType.SPEND, "gallery",
                    f"Private viewing: {piece['title']}"
                )
            except Exception:
                pass  # Economy unavailable — proceed

            detail = self._get_piece_detail(piece_id) or dict(piece)
            emit("private_viewing_granted", {
                "piece": detail,
                "commentary": detail.get("commentary", ""),
            })
            self._log("private_viewing", f"Private viewing granted: '{piece['title']}'")

            try:
                from engine.events.event_bus import get_event_bus
                get_event_bus().publish(
                    "gallery.private_viewing",
                    {"piece_id": piece_id, "piece_title": piece["title"]},
                    scene="gallery",
                )
            except Exception:
                pass

        @self.socketio.on("commission_work")
        def on_commission_work(data):
            """Commission a new work via SceneArtManager (ComfyUI)."""
            description = (data or {}).get("description", "")
            intensity = max(1, min(3, int((data or {}).get("intensity", 1))))
            if not description:
                emit("commission_error", {
                    "reason": "A description is required to commission work."
                })
                return

            result: Dict = {
                "description": description,
                "intensity": intensity,
                "url": None,
                "cached": False,
            }
            try:
                from engine.art.scene_art import get_scene_art_manager
                art_result = get_scene_art_manager().get_action_card(
                    description, scene="gallery", intensity=intensity
                )
                result.update({"url": art_result.url, "cached": art_result.cached})
            except Exception as exc:
                logger.debug("SceneArtManager commission skipped: %s", exc)

            emit("commission_complete", result)
            self._log("commission", f"Commission: '{description[:60]}' (intensity {intensity})")

            try:
                from engine.events.event_bus import get_event_bus
                get_event_bus().publish(
                    "gallery.commission",
                    {"description": description, "intensity": intensity, "url": result.get("url")},
                    scene="gallery",
                )
            except Exception:
                pass

    def _get_state(self) -> Dict:
        return {
            "characters": {k: v.to_dict() for k, v in self.characters.items()},
            "artworks": {k: v.to_dict() for k, v in self.artworks.items()},
            "rooms": GALLERY_ROOMS,
            "active_exhibition": self.active_exhibition,
            "exhibition_info": PREMADE_EXHIBITIONS.get(self.active_exhibition, {}),
            "log": self.gallery_log[-50:],
            "streaming_enabled": self.streaming_enabled,
            # THE OBSCURA state
            "pieces": self._get_pieces(),
            "curator_mood": self._curator_mood,
        }

    # ── HTTP Routes ────────────────────────────────────────────────────────

    def _register_routes(self) -> None:
        app = self.app

        @app.route("/")
        def index():
            return render_template("gallery.html", **self.inject_navbar_context())

        @app.route("/api/state")
        def get_state():
            return jsonify({"ok": True, **self._get_state()})

        # ── Exhibition ────────────────────────────────────────────────
        @app.route("/api/exhibitions")
        def list_exhibitions():
            return jsonify({"ok": True, "exhibitions": {
                k: {"label": v["label"], "emoji": v["emoji"], "theme": v["theme"]}
                for k, v in PREMADE_EXHIBITIONS.items()
            }})

        @app.route("/api/exhibition/set", methods=["POST"])
        def set_exhibition():
            key = (request.json or {}).get("exhibition")
            if key not in PREMADE_EXHIBITIONS:
                return jsonify({"ok": False, "error": "Unknown exhibition"}), 400
            self.active_exhibition = key
            ex = PREMADE_EXHIBITIONS[key]
            # Seed artworks
            for seed in ex.get("seed_artworks", []):
                art = Artwork(
                    id=str(uuid.uuid4())[:8],
                    title=seed["title"],
                    style=seed.get("style", ""),
                    description=seed.get("description", ""),
                    room="main_hall",
                    created_at=datetime.now().isoformat(),
                )
                self.artworks[art.id] = art
            self._log("exhibition_set", f"Exhibition '{ex['label']}' opened")
            self.socketio.emit("gallery_state", self._get_state())
            return jsonify({"ok": True, "exhibition": key})

        # ── Artworks ──────────────────────────────────────────────────
        @app.route("/api/artworks")
        def list_artworks():
            return jsonify({"ok": True, "artworks": {
                k: v.to_dict() for k, v in self.artworks.items()
            }})

        @app.route("/api/artwork/create", methods=["POST"])
        def create_artwork():
            body = request.json or {}
            char_id = body.get("character_id", "")
            theme = body.get("theme", "")
            if char_id not in self.characters:
                # Use first artist character
                artists = [c for c in self.characters.values() if c.role == "artist"]
                if artists:
                    char_id = artists[0].char_id
                elif self.characters:
                    char_id = list(self.characters.keys())[0]
                else:
                    return jsonify({"ok": False, "error": "No characters"}), 400
            art = self._create_artwork(char_id, theme)
            if art:
                return jsonify({"ok": True, "artwork": art.to_dict()})
            return jsonify({"ok": False, "error": "Creation failed"}), 500

        @app.route("/api/artwork/add", methods=["POST"])
        def add_artwork():
            body = request.json or {}
            art = Artwork(
                id=str(uuid.uuid4())[:8],
                title=body.get("title", "Untitled"),
                style=body.get("style", ""),
                description=body.get("description", ""),
                room=body.get("room", "main_hall"),
                created_at=datetime.now().isoformat(),
            )
            self.artworks[art.id] = art
            self._log("artwork_added", f"'{art.title}' added to gallery")
            self.socketio.emit("gallery_state", self._get_state())
            return jsonify({"ok": True, "artwork": art.to_dict()})

        # ── Evaluation (streaming showcase) ───────────────────────────
        @app.route("/api/evaluate", methods=["POST"])
        def evaluate():
            body = request.json or {}
            char_id = body.get("character_id", "")
            artwork_id = body.get("artwork_id", "")
            artwork = self.artworks.get(artwork_id)
            if not artwork:
                return jsonify({"ok": False, "error": "Artwork not found"}), 404
            if char_id not in self.characters:
                return jsonify({"ok": False, "error": "Character not in gallery"}), 400

            # Run evaluation off-thread to avoid blocking
            result = {"done": False}
            def _eval():
                r = self._evaluate_artwork(char_id, artwork)
                result.update(r)
                result["done"] = True
                self.socketio.emit("evaluation_complete", r)
                self._log("evaluation", f"{self.characters[char_id].name} evaluated '{artwork.title}'")

            t = threading.Thread(target=_eval, daemon=True)
            t.start()
            t.join(timeout=30)
            return jsonify({"ok": True, "result": result})

        # ── Structured Critique (SceneAgent showcase) ─────────────────
        @app.route("/api/critique", methods=["POST"])
        def critique():
            body = request.json or {}
            char_id = body.get("character_id", "")
            artwork_id = body.get("artwork_id", "")
            artwork = self.artworks.get(artwork_id)
            if not artwork:
                return jsonify({"ok": False, "error": "Artwork not found"}), 404
            result = self._structured_critique(char_id, artwork)
            return jsonify({"ok": True, "critique": result})

        # ── Debate (branching showcase) ───────────────────────────────
        @app.route("/api/debate", methods=["POST"])
        def debate():
            body = request.json or {}
            artwork_id = body.get("artwork_id", "")
            artwork = self.artworks.get(artwork_id)
            if not artwork:
                return jsonify({"ok": False, "error": "Artwork not found"}), 404
            char_ids = body.get("character_ids") or list(self.characters.keys())[:2]
            result = self._debate_artwork(artwork, char_ids)
            return jsonify({"ok": True, **result})

        # ── Characters ────────────────────────────────────────────────
        @app.route("/api/characters")
        def list_characters():
            return jsonify({"ok": True, "characters": {
                k: v.to_dict() for k, v in self.characters.items()
            }})

        @app.route("/api/character/move", methods=["POST"])
        def move_character():
            body = request.json or {}
            char_id = body.get("character_id", "")
            room = body.get("room", "")
            if char_id not in self.characters or room not in GALLERY_ROOMS:
                return jsonify({"ok": False, "error": "Invalid character or room"}), 400
            self.characters[char_id].current_room = room
            self._log("move", f"{self.characters[char_id].name} moved to {GALLERY_ROOMS[room]['name']}")
            self.socketio.emit("gallery_state", self._get_state())
            return jsonify({"ok": True})

        # ── Gallery Log ───────────────────────────────────────────────
        @app.route("/api/log")
        def get_log():
            limit = int(request.args.get("limit", 50))
            return jsonify({"ok": True, "log": self.gallery_log[-limit:]})

        # ── MCP Status ────────────────────────────────────────────────
        @app.route("/api/mcp/status")
        def mcp_status():
            try:
                fw = get_framework()
                return jsonify({"ok": True, "status": fw.get_status()})
            except Exception as exc:
                return jsonify({"ok": False, "error": str(exc)}), 500

        # ── Gallery Pieces (THE OBSCURA) ──────────────────────────────────
        @app.route("/api/gallery/pieces")
        def gallery_pieces():
            """List all artwork pieces: permanent OBSCURA collection + commissioned works."""
            return jsonify({
                "ok": True,
                "pieces": self._get_pieces(),
                "curator_mood": self._curator_mood,
            })

        @app.route("/api/gallery/piece/<piece_id>")
        def gallery_piece_detail(piece_id: str):
            """Detail view for a single piece with curator commentary."""
            detail = self._get_piece_detail(piece_id)
            if not detail:
                return jsonify({"ok": False, "error": "Piece not found"}), 404
            return jsonify({"ok": True, "piece": detail})

        @app.route("/api/health")
        def health():
            return jsonify(self.get_health())

        @app.route("/api/economy")
        def api_economy():
            """Return current economy state for this scene."""
            try:
                from engine.economy.economy import get_economy_manager
                em = get_economy_manager()
                player_id = request.args.get("player_id", "player")
                return jsonify({
                    "scene": SCENE_ID,
                    "balance": em.get_balance(player_id),
                    "debt": em.check_debt(player_id),
                    "recent_transactions": [t.to_dict() for t in em.get_history(player_id, limit=10)],
                })
            except Exception as exc:
                return jsonify({"error": str(exc)}), 500


# ── Module entry point ─────────────────────────────────────────────────────────

def create_app(host: str = "0.0.0.0", port: int = 5560) -> GalleryScene:
    """Factory used by the scene manager / launcher."""
    return GalleryScene(host=host, port=port)


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    scene = create_app()
    scene.start()
