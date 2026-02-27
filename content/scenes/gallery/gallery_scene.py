"""
Gallery Scene — v2.7 Framework Showcase
========================================
An interactive art gallery where AI characters act as curators, critics, and
artists. Demonstrates the full v2.7 streaming framework:

• **Streaming inference** with real-time mood/action extraction via StreamProcessor
• **Image generation** — characters "create" art via [IMAGE:prompt] tags
• **Conversation branching** — debate art interpretations with try_alternatives()
• **Structured output** — art evaluations as typed JSON via run_structured()
• **Multi-character interaction** — curator and critic with different perspectives
• **Store control** — stateful gallery tours vs stateless quick evaluations
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
        "title": "Art Gallery",
        "description": "AI art gallery where characters evaluate and discuss generated artwork. "
                       "Showcases image generation integration.",
        "genre": "creative",
        "max_characters": 5,
        "features": ["image_generation", "art_evaluation", "gallery_curation",
                     "character_opinions"],
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
        # Start background ticker for ambient updates
        self._start_ticker()
        logger.info("GalleryScene started on %s:%s", self.host, self.port)
        self.socketio.run(self.app, host=self.host, port=self.port, debug=False, use_reloader=False)

    def stop(self) -> None:
        self.nexus_flush()
        self._ticker_stop.set()
        if self._ticker_thread and self._ticker_thread.is_alive():
            self._ticker_thread.join(timeout=3)
        try:
            get_framework().save_state()
        except Exception:
            pass
        logger.info("GalleryScene stopped")

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
            "name": "Gallery",
            "scene_id": SCENE_ID,
            "description": "Interactive art gallery — v2.7 streaming framework showcase.",
            "version": "0.50b",
            "port": self.port,
            "skill_packs": ["narrative", "memory", "character"],
            "features": ["streaming", "structured_output", "branching", "image_gen"],
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

    # ── Socket.IO ──────────────────────────────────────────────────────────

    def _register_socketio(self) -> None:
        @self.socketio.on("connect")
        def on_connect():
            emit("gallery_state", self._get_state())

        @self.socketio.on("request_state")
        def on_request():
            emit("gallery_state", self._get_state())

    def _get_state(self) -> Dict:
        return {
            "characters": {k: v.to_dict() for k, v in self.characters.items()},
            "artworks": {k: v.to_dict() for k, v in self.artworks.items()},
            "rooms": GALLERY_ROOMS,
            "active_exhibition": self.active_exhibition,
            "exhibition_info": PREMADE_EXHIBITIONS.get(self.active_exhibition, {}),
            "log": self.gallery_log[-50:],
            "streaming_enabled": self.streaming_enabled,
        }

    # ── HTTP Routes ────────────────────────────────────────────────────────

    def _register_routes(self) -> None:
        app = self.app

        @app.route("/")
        def index():
            return render_template("gallery_ui.html")

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

        @app.route("/api/health")
        def health():
            return jsonify(self.get_health())


# ── Module entry point ─────────────────────────────────────────────────────────

def create_app(host: str = "0.0.0.0", port: int = 5560) -> GalleryScene:
    """Factory used by the scene manager / launcher."""
    return GalleryScene(host=host, port=port)


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    scene = create_app()
    scene.start()
