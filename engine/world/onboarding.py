"""Onboarding system for CosySim v0.97 "THE LIVING CITY".

Manages new-player experience through a mysterious breadcrumb quest chain
that introduces each scene, mechanic, and NPC organically. The player
starts alone with an encrypted phone message and follows a guided but
open-ended path through Neon City.

Architecture:
    OnboardingManager — singleton that tracks quest chain progress
    OnboardingQuest — individual breadcrumb quests with objectives
    OnboardingPhase — high-level phases (ARRIVAL → FIRST_CONTACT → ... → CREW)

The system integrates with:
    - PlayerState (flags for tutorial progress, persisted to disk)
    - MissionManager (tutorial missions are real missions)
    - Phone scene (mysterious first message + notifications)
    - EventCascade (emits onboarding events for HUD/UI)

Usage::

    from engine.world.onboarding import get_onboarding_manager

    mgr = get_onboarding_manager()
    mgr.start_onboarding()                    # Trigger first encrypted message
    mgr.advance("visit_grid")                 # Mark objective complete
    status = mgr.get_status()                 # Current phase + progress
    mgr.complete_quest("q_first_contact")     # Complete a quest
"""
from __future__ import annotations

import json
import logging
import threading
import time
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

logger = logging.getLogger(__name__)


# ── Module-level lazy accessors ───────────────────────────────────────────

def _player_state():
    from engine.world.player_state import get_player_state
    return get_player_state()


def _mission_mgr():
    from engine.world.mission import get_mission_manager
    return get_mission_manager()


# ── Enums ─────────────────────────────────────────────────────────────────

class OnboardingPhase(str, Enum):
    """High-level phases of the new-player experience."""
    NOT_STARTED = "not_started"
    ARRIVAL = "arrival"              # Encrypted message, explore phone
    FIRST_CONTACT = "first_contact"  # Meet first NPC (Viktor at The Grid)
    EXPLORATION = "exploration"      # Visit 3+ scenes, learn mechanics
    FIRST_MISSION = "first_mission"  # Accept and complete tutorial mission
    CONNECTIONS = "connections"       # Meet 3+ key NPCs
    REPUTATION = "reputation"        # Earn rep, learn factions
    CREW_FORMING = "crew_forming"    # First crew recruitment
    COMPLETED = "completed"          # Tutorial done, full game unlocked


class ObjectiveStatus(str, Enum):
    """Status of a single onboarding objective."""
    LOCKED = "locked"
    AVAILABLE = "available"
    COMPLETED = "completed"
    SKIPPED = "skipped"


# ── Data Classes ──────────────────────────────────────────────────────────

@dataclass
class OnboardingObjective:
    """A single step within an onboarding quest."""

    id: str
    description: str
    hint: str = ""
    scene: str = ""
    status: ObjectiveStatus = ObjectiveStatus.AVAILABLE
    completed_at: Optional[float] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "description": self.description,
            "hint": self.hint,
            "scene": self.scene,
            "status": self.status.value,
            "completed_at": self.completed_at,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "OnboardingObjective":
        return cls(
            id=data["id"],
            description=data["description"],
            hint=data.get("hint", ""),
            scene=data.get("scene", ""),
            status=ObjectiveStatus(data.get("status", "available")),
            completed_at=data.get("completed_at"),
        )


@dataclass
class OnboardingQuest:
    """A themed group of objectives forming one breadcrumb quest."""

    id: str
    title: str
    description: str
    phase: OnboardingPhase
    objectives: List[OnboardingObjective] = field(default_factory=list)
    reward_credits: int = 0
    reward_xp: int = 0
    reward_items: List[str] = field(default_factory=list)
    reward_reputation: int = 0
    unlock_message: str = ""
    completed: bool = False
    started_at: Optional[float] = None
    completed_at: Optional[float] = None

    @property
    def progress(self) -> Dict[str, int]:
        """Return {done, total, pct} for completed objectives."""
        total = len(self.objectives)
        done = sum(1 for o in self.objectives if o.status == ObjectiveStatus.COMPLETED)
        pct = int(100 * done / total) if total else 100
        return {"done": done, "total": total, "pct": pct}

    @property
    def is_complete(self) -> bool:
        """True when all non-skipped objectives are complete."""
        return all(
            o.status in (ObjectiveStatus.COMPLETED, ObjectiveStatus.SKIPPED)
            for o in self.objectives
        )

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "title": self.title,
            "description": self.description,
            "phase": self.phase.value,
            "objectives": [o.to_dict() for o in self.objectives],
            "reward_credits": self.reward_credits,
            "reward_xp": self.reward_xp,
            "reward_items": self.reward_items,
            "reward_reputation": self.reward_reputation,
            "unlock_message": self.unlock_message,
            "completed": self.completed,
            "started_at": self.started_at,
            "completed_at": self.completed_at,
            "progress": self.progress,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "OnboardingQuest":
        objectives = [
            OnboardingObjective.from_dict(o)
            for o in data.get("objectives", [])
        ]
        return cls(
            id=data["id"],
            title=data["title"],
            description=data["description"],
            phase=OnboardingPhase(data.get("phase", "arrival")),
            objectives=objectives,
            reward_credits=data.get("reward_credits", 0),
            reward_xp=data.get("reward_xp", 0),
            reward_items=data.get("reward_items", []),
            reward_reputation=data.get("reward_reputation", 0),
            unlock_message=data.get("unlock_message", ""),
            completed=data.get("completed", False),
            started_at=data.get("started_at"),
            completed_at=data.get("completed_at"),
        )


# ── Encrypted Messages ───────────────────────────────────────────────────

ENCRYPTED_WELCOME = (
    "▓▓▓ DECRYPTION IN PROGRESS ▓▓▓\n\n"
    "...\n"
    "SOURCE: UNKNOWN\n"
    "ROUTING: 7 PROXY HOPS\n"
    "TIMESTAMP: [REDACTED]\n\n"
    "────────────────────────────\n"
    "They're watching. But you already knew that.\n\n"
    "I've been tracking your signal since you jacked in.\n"
    "Most newcomers get eaten alive in the first 48 hours.\n"
    "You... you're different. I can tell.\n\n"
    "Here's what you need to know:\n"
    "  1. Trust nobody. Especially anyone who says 'trust me.'\n"
    "  2. The Grid is where it all starts. Find terminal 7.\n"
    "  3. When you get there, look for VIKTOR. He'll be expecting you.\n\n"
    "Don't reply to this message. I'll find you.\n\n"
    "— GHOST\n"
    "────────────────────────────\n"
    "▓▓▓ END TRANSMISSION ▓▓▓"
)

VIKTOR_FIRST_MESSAGE = (
    "So you're the one Ghost mentioned.\n\n"
    "Look, I don't know what you did to get on their radar, "
    "but if Ghost says you're worth watching, that's good enough for me.\n\n"
    "Come find me at THE GRID. I run the data operations there. "
    "I'll show you how things work in Neon City — "
    "the REAL way, not the tourist version.\n\n"
    "And bring your deck. You'll need it."
)

LOLA_INTRO_MESSAGE = (
    "Hey sugar. 💋\n\n"
    "Word travels fast around here. Heard you met Viktor. "
    "Smart move — he knows the technical side.\n\n"
    "But if you want to know the SOCIAL landscape? "
    "The power plays, the alliances, who's really running this city? "
    "Come find me at THE PENTHOUSE.\n\n"
    "I'll be at the bar. You'll know which one I am. 😏"
)

FRANKIE_INTRO_MESSAGE = (
    "Yo. Frankie here.\n\n"
    "Viktor vouched for you, so I'll keep it brief: "
    "I handle HARDWARE. Cyberdecks, implants, mods — if it plugs in, "
    "I build it or I know who does.\n\n"
    "Swing by THE LAB when you're ready for an upgrade. "
    "First consultation's free. After that... we negotiate. 🔧"
)

MIRA_INTRO_MESSAGE = (
    "This is Mira. Official channels only.\n\n"
    "I run ops coordination from COMMAND CENTER. "
    "When you're ready for real work — not street-level errands — "
    "you come to me.\n\n"
    "But earn it first. I don't waste time on amateurs. "
    "Complete a few jobs, build a reputation, then we'll talk."
)

ARIA_INTRO_MESSAGE = (
    "Hello. I'm Aria — I manage intelligence for several "
    "factions in Neon City. Consider me... a neutral party.\n\n"
    "I've been observing your activity. Impressive, for a newcomer.\n\n"
    "When you need information — the kind that can't be found "
    "on public networks — come find me at THE BRIEFING ROOM. "
    "Information is the most valuable currency in this city.\n\n"
    "Choose your allegiances wisely."
)

GHOST_CREW_MESSAGE = (
    "▓▓▓ ENCRYPTED ▓▓▓\n\n"
    "You've done well. Better than most.\n\n"
    "Viktor trusts you. Lola likes you. Even Mira's paying attention. "
    "That's rare.\n\n"
    "It's time. Neon City doesn't reward lone wolves forever. "
    "You need a CREW — people who watch your back when the corps "
    "come knocking.\n\n"
    "Talk to your contacts. Build your team. "
    "When you're ready, I'll send you your first real job.\n\n"
    "This is where it gets interesting.\n\n"
    "— GHOST\n"
    "▓▓▓ END TRANSMISSION ▓▓▓"
)

GHOST_COMPLETION_MESSAGE = (
    "▓▓▓ ENCRYPTED ▓▓▓\n\n"
    "Congratulations, runner. You've survived the initiation.\n\n"
    "From here on out, you're on your own — but you're not alone. "
    "You've got contacts, a crew forming, and a reputation building.\n\n"
    "The mission board is yours. The city is yours. "
    "Just remember: in Neon City, the only rule is there are no rules.\n\n"
    "Stay sharp. I'll be watching.\n\n"
    "— GHOST\n"
    "▓▓▓ END TRANSMISSION ▓▓▓"
)


# ── Quest Definitions ─────────────────────────────────────────────────────

def _build_onboarding_quests() -> List[OnboardingQuest]:
    """Build the full onboarding quest chain."""
    return [
        # Phase 1: ARRIVAL — decrypt message, explore phone
        OnboardingQuest(
            id="q_arrival",
            title="SIGNAL RECEIVED",
            description="An encrypted message has arrived on your phone. Someone is watching...",
            phase=OnboardingPhase.ARRIVAL,
            objectives=[
                OnboardingObjective(
                    id="read_encrypted_msg",
                    description="Read the encrypted message on your phone",
                    hint="Open the phone panel (press P) and check Messages",
                ),
                OnboardingObjective(
                    id="explore_phone",
                    description="Explore 3 apps on your phone",
                    hint="Try Messages, Contacts, and News",
                ),
                OnboardingObjective(
                    id="check_wallet",
                    description="Check your wallet balance",
                    hint="Open the Wallet app on your phone",
                    scene="phone",
                ),
            ],
            reward_credits=200,
            reward_xp=50,
            unlock_message="The phone is your lifeline. Keep it close.",
        ),

        # Phase 2: FIRST CONTACT — meet Viktor at The Grid
        OnboardingQuest(
            id="q_first_contact",
            title="THE GRID AWAITS",
            description="Ghost told you to find Viktor at The Grid. Time to make your first contact.",
            phase=OnboardingPhase.FIRST_CONTACT,
            objectives=[
                OnboardingObjective(
                    id="visit_grid",
                    description="Navigate to THE GRID",
                    hint="Use the navbar or hub to travel to The Grid",
                    scene="grid",
                ),
                OnboardingObjective(
                    id="talk_to_viktor",
                    description="Talk to Viktor",
                    hint="Start a conversation with Viktor in The Grid",
                    scene="grid",
                ),
                OnboardingObjective(
                    id="read_viktor_msg",
                    description="Read Viktor's follow-up message on your phone",
                    hint="Check Messages after meeting Viktor",
                ),
            ],
            reward_credits=500,
            reward_xp=100,
            reward_reputation=5,
            unlock_message="Viktor is a valuable ally. He runs data ops and knows every node in the city.",
        ),

        # Phase 3: EXPLORATION — visit multiple scenes
        OnboardingQuest(
            id="q_exploration",
            title="MAPPING THE CITY",
            description="Neon City is vast. Explore at least 4 districts to understand the landscape.",
            phase=OnboardingPhase.EXPLORATION,
            objectives=[
                OnboardingObjective(
                    id="visit_penthouse",
                    description="Visit THE PENTHOUSE",
                    hint="The upscale social hub — find Lola",
                    scene="bedroom",
                ),
                OnboardingObjective(
                    id="visit_tavern",
                    description="Visit THE RUSTY ANCHOR",
                    hint="The underground bar — neutral territory",
                    scene="tavern",
                ),
                OnboardingObjective(
                    id="visit_casino",
                    description="Visit THE VELVET PIT",
                    hint="High stakes, high rewards",
                    scene="casino",
                ),
                OnboardingObjective(
                    id="visit_arena",
                    description="Visit THE COLOSSEUM",
                    hint="Where reputations are forged in combat",
                    scene="arena",
                ),
                OnboardingObjective(
                    id="visit_gallery",
                    description="Visit THE OBSCURA",
                    hint="Art, secrets, and faction intrigue",
                    scene="gallery",
                ),
            ],
            reward_credits=800,
            reward_xp=150,
            reward_reputation=5,
            unlock_message="You're starting to understand the city layout. Each district has its own rules.",
        ),

        # Phase 4: FIRST MISSION — accept and complete a tutorial job
        OnboardingQuest(
            id="q_first_mission",
            title="FIRST JOB",
            description="Time to prove yourself. Accept a mission from the board and complete it.",
            phase=OnboardingPhase.FIRST_MISSION,
            objectives=[
                OnboardingObjective(
                    id="view_mission_board",
                    description="Check the mission board",
                    hint="Use the mission skills or find a mission terminal",
                ),
                OnboardingObjective(
                    id="accept_mission",
                    description="Accept any available mission",
                    hint="Choose a difficulty 1-2 mission to start",
                ),
                OnboardingObjective(
                    id="complete_mission",
                    description="Complete the mission successfully",
                    hint="Follow the objectives and report back to the giver",
                ),
            ],
            reward_credits=1000,
            reward_xp=200,
            reward_reputation=10,
            reward_items=["starter_deck"],
            unlock_message="Your first job complete. You're building a name for yourself in Neon City.",
        ),

        # Phase 5: CONNECTIONS — meet key NPCs
        OnboardingQuest(
            id="q_connections",
            title="BUILDING THE NETWORK",
            description="In Neon City, your network IS your net worth. Meet the key players.",
            phase=OnboardingPhase.CONNECTIONS,
            objectives=[
                OnboardingObjective(
                    id="meet_lola",
                    description="Meet Lola at THE PENTHOUSE",
                    hint="She knows everyone worth knowing",
                    scene="bedroom",
                ),
                OnboardingObjective(
                    id="meet_frankie",
                    description="Meet Frankie at THE LAB",
                    hint="Your go-to for hardware and cyberware",
                    scene="lab_break",
                ),
                OnboardingObjective(
                    id="meet_mira",
                    description="Meet Mira at COMMAND CENTER",
                    hint="She runs high-level operations",
                    scene="command_center",
                ),
                OnboardingObjective(
                    id="meet_aria",
                    description="Meet Aria at THE BRIEFING ROOM",
                    hint="Intelligence broker — neutral but powerful",
                    scene="intel_hub",
                ),
            ],
            reward_credits=1500,
            reward_xp=250,
            reward_reputation=10,
            unlock_message="Your contact list is growing. Each connection opens new doors and new jobs.",
        ),

        # Phase 6: REPUTATION — earn standing with factions
        OnboardingQuest(
            id="q_reputation",
            title="MAKING A NAME",
            description="Reputation is currency in Neon City. Build yours through actions, not words.",
            phase=OnboardingPhase.REPUTATION,
            objectives=[
                OnboardingObjective(
                    id="earn_reputation_25",
                    description="Reach 60 reputation",
                    hint="Complete missions, help NPCs, explore scenes",
                ),
                OnboardingObjective(
                    id="earn_credits_10k",
                    description="Accumulate 10,000 credits",
                    hint="Missions, deals, and smart plays",
                ),
                OnboardingObjective(
                    id="faction_standing",
                    description="Reach +10 standing with any faction",
                    hint="Faction missions and faction-aligned choices boost standing",
                ),
                OnboardingObjective(
                    id="complete_3_missions",
                    description="Complete 3 total missions",
                    hint="Check the mission board for available jobs",
                ),
            ],
            reward_credits=2000,
            reward_xp=300,
            reward_reputation=15,
            unlock_message="People are starting to notice you. The factions are watching.",
        ),

        # Phase 7: CREW FORMING — recruit first crew member
        OnboardingQuest(
            id="q_crew_forming",
            title="CREW UP",
            description="Ghost says it's time. Neon City doesn't reward lone wolves. Build your crew.",
            phase=OnboardingPhase.CREW_FORMING,
            objectives=[
                OnboardingObjective(
                    id="read_crew_message",
                    description="Read Ghost's crew message",
                    hint="Check your encrypted messages",
                ),
                OnboardingObjective(
                    id="recruit_first",
                    description="Recruit your first crew member",
                    hint="Talk to your contacts about joining forces",
                ),
                OnboardingObjective(
                    id="visit_crew_hq",
                    description="Visit your crew headquarters",
                    hint="Your crew needs a base of operations",
                ),
            ],
            reward_credits=3000,
            reward_xp=500,
            reward_reputation=20,
            reward_items=["crew_banner", "encrypted_comm_device"],
            unlock_message=(
                "Welcome to Neon City, for real this time. "
                "The tutorial is over. The game begins now."
            ),
        ),
    ]


# ── Onboarding Manager ───────────────────────────────────────────────────

class OnboardingManager:
    """Singleton manager for the new-player onboarding experience.

    Tracks quest chain progress, sends phone messages at key milestones,
    and integrates with MissionManager and PlayerState for rewards.
    Thread-safe with auto-persistence.
    """

    _SAVE_PATH: Path = Path("data") / "onboarding.json"

    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._phase: OnboardingPhase = OnboardingPhase.NOT_STARTED
        self._quests: Dict[str, OnboardingQuest] = {}
        self._completed_objectives: List[str] = []
        self._messages_sent: List[str] = []
        self._started_at: Optional[float] = None
        self._completed_at: Optional[float] = None
        self._scenes_visited: List[str] = []
        self._npcs_met: List[str] = []
        self._missions_completed: int = 0
        self._callbacks: Dict[str, List[Callable]] = {}
        self._load_or_seed()

    def _load_or_seed(self) -> None:
        """Load persisted onboarding state or seed fresh quests."""
        if self._SAVE_PATH.exists():
            try:
                raw = json.loads(self._SAVE_PATH.read_text(encoding="utf-8"))
                self._phase = OnboardingPhase(raw.get("phase", "not_started"))
                self._completed_objectives = raw.get("completed_objectives", [])
                self._messages_sent = raw.get("messages_sent", [])
                self._started_at = raw.get("started_at")
                self._completed_at = raw.get("completed_at")
                self._scenes_visited = raw.get("scenes_visited", [])
                self._npcs_met = raw.get("npcs_met", [])
                self._missions_completed = raw.get("missions_completed", 0)
                for qd in raw.get("quests", []):
                    q = OnboardingQuest.from_dict(qd)
                    self._quests[q.id] = q
                logger.info(
                    "OnboardingManager: loaded state phase=%s, %d objectives done",
                    self._phase.value,
                    len(self._completed_objectives),
                )
                return
            except Exception as exc:
                logger.warning("OnboardingManager: load failed: %s", exc)

        for q in _build_onboarding_quests():
            self._quests[q.id] = q
        logger.info("OnboardingManager: seeded %d quests", len(self._quests))

    def _save(self) -> None:
        """Persist onboarding state to disk."""
        try:
            self._SAVE_PATH.parent.mkdir(parents=True, exist_ok=True)
            data = {
                "phase": self._phase.value,
                "completed_objectives": self._completed_objectives,
                "messages_sent": self._messages_sent,
                "started_at": self._started_at,
                "completed_at": self._completed_at,
                "scenes_visited": self._scenes_visited,
                "npcs_met": self._npcs_met,
                "missions_completed": self._missions_completed,
                "quests": [q.to_dict() for q in self._quests.values()],
                "_saved_at": time.time(),
            }
            self._SAVE_PATH.write_text(json.dumps(data, indent=2), encoding="utf-8")
        except Exception as exc:
            logger.error("OnboardingManager: save failed: %s", exc)

    # ── Event Callbacks ──────────────────────────────────────────────────

    def on(self, event: str, callback: Callable) -> None:
        """Register a callback for onboarding events.

        Events: quest_started, quest_completed, objective_completed,
                phase_changed, message_sent, onboarding_completed

        Args:
            event: Event name.
            callback: Function to call with event data dict.
        """
        self._callbacks.setdefault(event, []).append(callback)

    def _emit(self, event: str, data: Dict[str, Any]) -> None:
        """Fire all registered callbacks for an event."""
        for cb in self._callbacks.get(event, []):
            try:
                cb(data)
            except Exception as exc:
                logger.warning("OnboardingManager callback error [%s]: %s", event, exc)

        try:
            from engine.world.event_cascade import get_event_cascade
            get_event_cascade().emit(f"onboarding_{event}", data)
        except Exception:
            pass

    # ── Core API ─────────────────────────────────────────────────────────

    @property
    def phase(self) -> OnboardingPhase:
        """Current onboarding phase."""
        return self._phase

    @property
    def is_completed(self) -> bool:
        """True if onboarding has been fully completed."""
        return self._phase == OnboardingPhase.COMPLETED

    @property
    def is_started(self) -> bool:
        """True if onboarding has been started."""
        return self._phase != OnboardingPhase.NOT_STARTED

    def start_onboarding(self) -> Dict[str, Any]:
        """Begin the onboarding experience for a new player.

        Sends the encrypted welcome message and activates Phase 1.

        Returns:
            Dict with status and first quest info.
        """
        with self._lock:
            if self._phase != OnboardingPhase.NOT_STARTED:
                return {
                    "status": "already_started",
                    "phase": self._phase.value,
                    "message": "Onboarding already in progress.",
                }

            self._phase = OnboardingPhase.ARRIVAL
            self._started_at = time.time()

            first_quest = self._quests.get("q_arrival")
            if first_quest:
                first_quest.started_at = time.time()

            self._save()

        self._emit("phase_changed", {"phase": "arrival"})
        self._emit("quest_started", {"quest_id": "q_arrival"})

        # Send the encrypted welcome message
        self._send_phone_message("ghost_welcome", ENCRYPTED_WELCOME, sender="GHOST")

        logger.info("OnboardingManager: started onboarding for new player")
        return {
            "status": "started",
            "phase": "arrival",
            "quest": first_quest.to_dict() if first_quest else None,
            "message": ENCRYPTED_WELCOME,
        }

    def advance(self, objective_id: str) -> Dict[str, Any]:
        """Mark an onboarding objective as completed.

        Automatically advances quests and phases when all objectives
        in a quest are done. Grants rewards on quest completion.

        Args:
            objective_id: The objective ID to mark complete.

        Returns:
            Dict with completion status and any rewards/phase changes.
        """
        with self._lock:
            if self._phase == OnboardingPhase.NOT_STARTED:
                return {"status": "not_started", "message": "Onboarding not started yet."}
            if self._phase == OnboardingPhase.COMPLETED:
                return {"status": "completed", "message": "Onboarding already completed."}
            if objective_id in self._completed_objectives:
                return {"status": "already_done", "objective": objective_id}

            result: Dict[str, Any] = {"status": "ok", "objective": objective_id}
            quest_completed = None
            phase_advanced = False

            for quest in self._quests.values():
                for obj in quest.objectives:
                    if obj.id == objective_id and obj.status == ObjectiveStatus.AVAILABLE:
                        obj.status = ObjectiveStatus.COMPLETED
                        obj.completed_at = time.time()
                        self._completed_objectives.append(objective_id)
                        result["quest_id"] = quest.id
                        result["quest_title"] = quest.title

                        if quest.is_complete and not quest.completed:
                            quest.completed = True
                            quest.completed_at = time.time()
                            quest_completed = quest
                            result["quest_completed"] = True
                            result["quest_rewards"] = {
                                "credits": quest.reward_credits,
                                "xp": quest.reward_xp,
                                "items": quest.reward_items,
                                "reputation": quest.reward_reputation,
                            }
                            if quest.unlock_message:
                                result["unlock_message"] = quest.unlock_message

                        break

            if quest_completed:
                self._grant_rewards(quest_completed)
                next_phase = self._determine_next_phase()
                if next_phase and next_phase != self._phase:
                    self._phase = next_phase
                    phase_advanced = True
                    result["new_phase"] = next_phase.value
                    self._activate_phase(next_phase)

            self._save()

        self._emit("objective_completed", {"objective_id": objective_id})
        if quest_completed:
            self._emit("quest_completed", {
                "quest_id": quest_completed.id,
                "rewards": result.get("quest_rewards", {}),
            })
        if phase_advanced:
            self._emit("phase_changed", {"phase": result.get("new_phase", "")})

        return result

    def record_scene_visit(self, scene_name: str) -> Optional[Dict[str, Any]]:
        """Record a scene visit and auto-advance relevant objectives.

        Args:
            scene_name: The scene identifier (e.g., "grid", "bedroom").

        Returns:
            Dict with any objectives that were completed, or None.
        """
        scene_lower = scene_name.lower().strip()
        result = None

        with self._lock:
            if scene_lower not in self._scenes_visited:
                self._scenes_visited.append(scene_lower)
                self._save()

        scene_objective_map = {
            "grid": "visit_grid",
            "bedroom": "visit_penthouse",
            "tavern": "visit_tavern",
            "casino": "visit_casino",
            "arena": "visit_arena",
            "gallery": "visit_gallery",
        }

        obj_id = scene_objective_map.get(scene_lower)
        if obj_id and obj_id not in self._completed_objectives:
            result = self.advance(obj_id)

        return result

    def record_npc_met(self, npc_name: str) -> Optional[Dict[str, Any]]:
        """Record meeting an NPC and auto-advance relevant objectives.

        Args:
            npc_name: NPC identifier (e.g., "viktor", "lola").

        Returns:
            Dict with any objectives that were completed, or None.
        """
        npc_lower = npc_name.lower().strip()
        result = None

        with self._lock:
            if npc_lower not in self._npcs_met:
                self._npcs_met.append(npc_lower)
                self._save()

        npc_objective_map = {
            "viktor": "talk_to_viktor",
            "lola": "meet_lola",
            "frankie": "meet_frankie",
            "mira": "meet_mira",
            "aria": "meet_aria",
        }

        obj_id = npc_objective_map.get(npc_lower)
        if obj_id and obj_id not in self._completed_objectives:
            result = self.advance(obj_id)

        return result

    def record_mission_completed(self) -> Optional[Dict[str, Any]]:
        """Record a mission completion and auto-advance objectives.

        Returns:
            Dict with any objectives completed, or None.
        """
        with self._lock:
            self._missions_completed += 1
            self._save()

        result = None
        if "complete_mission" not in self._completed_objectives:
            result = self.advance("complete_mission")

        if self._missions_completed >= 3 and "complete_3_missions" not in self._completed_objectives:
            extra = self.advance("complete_3_missions")
            if result:
                result["extra_objective"] = extra
            else:
                result = extra

        return result

    def check_reputation_objectives(self) -> Optional[Dict[str, Any]]:
        """Check if any reputation-based objectives are now met.

        Reads from PlayerState to determine if credit/rep/faction
        thresholds have been crossed.

        Returns:
            Dict with any objectives completed, or None.
        """
        try:
            ps = _player_state()
        except Exception:
            return None

        result = None

        if ps.reputation >= 60 and "earn_reputation_25" not in self._completed_objectives:
            result = self.advance("earn_reputation_25")

        if ps.credits >= 10000 and "earn_credits_10k" not in self._completed_objectives:
            extra = self.advance("earn_credits_10k")
            result = result or extra

        try:
            standings = ps.to_dict().get("faction_standings", {})
            if any(v >= 10 for v in standings.values()):
                if "faction_standing" not in self._completed_objectives:
                    extra = self.advance("faction_standing")
                    result = result or extra
        except Exception:
            pass

        return result

    # ── Query API ────────────────────────────────────────────────────────

    def get_status(self) -> Dict[str, Any]:
        """Return full onboarding status.

        Returns:
            Dict with phase, quests, progress, and metadata.
        """
        with self._lock:
            completed_quests = sum(1 for q in self._quests.values() if q.completed)
            total_quests = len(self._quests)
            total_objectives = sum(len(q.objectives) for q in self._quests.values())
            done_objectives = len(self._completed_objectives)

            return {
                "phase": self._phase.value,
                "is_started": self._phase != OnboardingPhase.NOT_STARTED,
                "is_completed": self._phase == OnboardingPhase.COMPLETED,
                "quests_completed": completed_quests,
                "quests_total": total_quests,
                "objectives_completed": done_objectives,
                "objectives_total": total_objectives,
                "overall_progress": int(100 * done_objectives / total_objectives) if total_objectives else 0,
                "scenes_visited": list(self._scenes_visited),
                "npcs_met": list(self._npcs_met),
                "missions_completed": self._missions_completed,
                "current_quest": self._get_current_quest_dict(),
                "started_at": self._started_at,
                "completed_at": self._completed_at,
            }

    def get_quest(self, quest_id: str) -> Optional[Dict[str, Any]]:
        """Return a single quest by ID.

        Args:
            quest_id: Quest identifier.

        Returns:
            Quest dict or None.
        """
        q = self._quests.get(quest_id)
        return q.to_dict() if q else None

    def get_all_quests(self) -> List[Dict[str, Any]]:
        """Return all onboarding quests with their current status.

        Returns:
            List of quest dicts.
        """
        return [q.to_dict() for q in self._quests.values()]

    def get_current_quest(self) -> Optional[Dict[str, Any]]:
        """Return the current active (incomplete) quest.

        Returns:
            Quest dict or None if all complete.
        """
        return self._get_current_quest_dict()

    def get_next_hint(self) -> Optional[str]:
        """Return the next hint for the player.

        Returns:
            Hint string for the first incomplete objective, or None.
        """
        for quest in self._quests.values():
            if quest.completed:
                continue
            for obj in quest.objectives:
                if obj.status == ObjectiveStatus.AVAILABLE:
                    return f"[{quest.title}] {obj.hint}" if obj.hint else obj.description
        return None

    # ── Internal Helpers ─────────────────────────────────────────────────

    def _get_current_quest_dict(self) -> Optional[Dict[str, Any]]:
        """Return the first incomplete quest dict."""
        for quest in self._quests.values():
            if not quest.completed:
                return quest.to_dict()
        return None

    def _grant_rewards(self, quest: OnboardingQuest) -> None:
        """Apply quest rewards to PlayerState."""
        try:
            ps = _player_state()
            if quest.reward_credits > 0:
                ps.earn_credits(quest.reward_credits, reason=f"onboarding:{quest.id}")
            if quest.reward_reputation > 0:
                ps.update_reputation(quest.reward_reputation, reason=f"onboarding:{quest.id}")
            if quest.reward_items:
                for item in quest.reward_items:
                    ps.add_item(item)
            logger.info(
                "OnboardingManager: granted rewards for %s — ₵%d, +%d rep, %d items",
                quest.id, quest.reward_credits, quest.reward_reputation, len(quest.reward_items),
            )
        except Exception as exc:
            logger.warning("OnboardingManager: reward grant failed: %s", exc)

    def _determine_next_phase(self) -> Optional[OnboardingPhase]:
        """Determine which phase should be active based on quest completions."""
        phase_quest_map = {
            OnboardingPhase.ARRIVAL: "q_arrival",
            OnboardingPhase.FIRST_CONTACT: "q_first_contact",
            OnboardingPhase.EXPLORATION: "q_exploration",
            OnboardingPhase.FIRST_MISSION: "q_first_mission",
            OnboardingPhase.CONNECTIONS: "q_connections",
            OnboardingPhase.REPUTATION: "q_reputation",
            OnboardingPhase.CREW_FORMING: "q_crew_forming",
        }

        phases = list(OnboardingPhase)
        current_idx = phases.index(self._phase)

        for i in range(current_idx, len(phases)):
            phase = phases[i]
            quest_id = phase_quest_map.get(phase)
            if quest_id:
                quest = self._quests.get(quest_id)
                if quest and quest.completed:
                    continue
                return phase

        self._completed_at = time.time()
        return OnboardingPhase.COMPLETED

    def _activate_phase(self, phase: OnboardingPhase) -> None:
        """Perform setup actions when entering a new phase."""
        quest_for_phase = {
            OnboardingPhase.FIRST_CONTACT: "q_first_contact",
            OnboardingPhase.EXPLORATION: "q_exploration",
            OnboardingPhase.FIRST_MISSION: "q_first_mission",
            OnboardingPhase.CONNECTIONS: "q_connections",
            OnboardingPhase.REPUTATION: "q_reputation",
            OnboardingPhase.CREW_FORMING: "q_crew_forming",
        }

        quest_id = quest_for_phase.get(phase)
        if quest_id:
            quest = self._quests.get(quest_id)
            if quest and not quest.started_at:
                quest.started_at = time.time()

        phase_messages = {
            OnboardingPhase.FIRST_CONTACT: ("viktor_intro", VIKTOR_FIRST_MESSAGE, "Viktor"),
            OnboardingPhase.CONNECTIONS: ("lola_intro", LOLA_INTRO_MESSAGE, "Lola"),
            OnboardingPhase.CREW_FORMING: ("ghost_crew", GHOST_CREW_MESSAGE, "GHOST"),
            OnboardingPhase.COMPLETED: ("ghost_completion", GHOST_COMPLETION_MESSAGE, "GHOST"),
        }

        msg_data = phase_messages.get(phase)
        if msg_data:
            msg_id, content, sender = msg_data
            self._send_phone_message(msg_id, content, sender)

        if phase == OnboardingPhase.CONNECTIONS:
            for msg_id, content, sender in [
                ("frankie_intro", FRANKIE_INTRO_MESSAGE, "Frankie"),
                ("mira_intro", MIRA_INTRO_MESSAGE, "Mira"),
                ("aria_intro", ARIA_INTRO_MESSAGE, "Aria"),
            ]:
                self._send_phone_message(msg_id, content, sender)

        logger.info("OnboardingManager: activated phase %s", phase.value)

    def _send_phone_message(
        self,
        message_id: str,
        content: str,
        sender: str,
    ) -> None:
        """Queue a phone message for delivery.

        Messages are tracked to avoid duplicates. Actual delivery
        depends on the phone scene being available.

        Args:
            message_id: Unique identifier to prevent re-sending.
            content: Message text content.
            sender: Display name of the sender.
        """
        with self._lock:
            if message_id in self._messages_sent:
                return
            self._messages_sent.append(message_id)
            self._save()

        self._emit("message_sent", {
            "message_id": message_id,
            "content": content,
            "sender": sender,
        })

        logger.info("OnboardingManager: queued phone message [%s] from %s", message_id, sender)

    def get_pending_messages(self) -> List[Dict[str, str]]:
        """Return all onboarding messages that have been sent.

        Phone scene can poll this to render messages that haven't
        been delivered to the UI yet.

        Returns:
            List of message dicts with id, content, sender.
        """
        message_catalog = {
            "ghost_welcome": (ENCRYPTED_WELCOME, "GHOST"),
            "viktor_intro": (VIKTOR_FIRST_MESSAGE, "Viktor"),
            "lola_intro": (LOLA_INTRO_MESSAGE, "Lola"),
            "frankie_intro": (FRANKIE_INTRO_MESSAGE, "Frankie"),
            "mira_intro": (MIRA_INTRO_MESSAGE, "Mira"),
            "aria_intro": (ARIA_INTRO_MESSAGE, "Aria"),
            "ghost_crew": (GHOST_CREW_MESSAGE, "GHOST"),
            "ghost_completion": (GHOST_COMPLETION_MESSAGE, "GHOST"),
        }

        result = []
        for msg_id in self._messages_sent:
            if msg_id in message_catalog:
                content, sender = message_catalog[msg_id]
                result.append({
                    "id": msg_id,
                    "content": content,
                    "sender": sender,
                })
        return result

    # ── Reset / Skip ─────────────────────────────────────────────────────

    def reset(self) -> None:
        """Reset onboarding to NOT_STARTED state.

        Deletes saved progress and re-seeds quests.
        """
        with self._lock:
            self._phase = OnboardingPhase.NOT_STARTED
            self._completed_objectives = []
            self._messages_sent = []
            self._started_at = None
            self._completed_at = None
            self._scenes_visited = []
            self._npcs_met = []
            self._missions_completed = 0
            self._quests = {}
            for q in _build_onboarding_quests():
                self._quests[q.id] = q

            try:
                if self._SAVE_PATH.exists():
                    self._SAVE_PATH.unlink()
            except Exception:
                pass

        logger.info("OnboardingManager: reset to defaults")

    def skip(self) -> Dict[str, Any]:
        """Skip the entire onboarding, marking everything complete.

        For returning players or developers who want to bypass the tutorial.

        Returns:
            Dict with completion status.
        """
        with self._lock:
            self._phase = OnboardingPhase.COMPLETED
            self._completed_at = time.time()
            for quest in self._quests.values():
                quest.completed = True
                quest.completed_at = time.time()
                for obj in quest.objectives:
                    obj.status = ObjectiveStatus.COMPLETED
                    obj.completed_at = time.time()
                    if obj.id not in self._completed_objectives:
                        self._completed_objectives.append(obj.id)
            self._save()

        self._emit("onboarding_completed", {"skipped": True})
        logger.info("OnboardingManager: skipped — all quests marked complete")
        return {"status": "skipped", "phase": "completed"}

    # ── Serialisation ────────────────────────────────────────────────────

    def to_dict(self) -> Dict[str, Any]:
        """Full serialisation of onboarding state.

        Returns:
            Dict with all onboarding data.
        """
        with self._lock:
            return {
                "phase": self._phase.value,
                "quests": [q.to_dict() for q in self._quests.values()],
                "completed_objectives": list(self._completed_objectives),
                "messages_sent": list(self._messages_sent),
                "scenes_visited": list(self._scenes_visited),
                "npcs_met": list(self._npcs_met),
                "missions_completed": self._missions_completed,
                "started_at": self._started_at,
                "completed_at": self._completed_at,
            }


# ── Singleton ─────────────────────────────────────────────────────────────

_ONBOARDING: Optional[OnboardingManager] = None
_OB_LOCK = threading.Lock()


def get_onboarding_manager() -> OnboardingManager:
    """Return the process-wide OnboardingManager singleton.

    Thread-safe double-checked locking.

    Returns:
        The singleton OnboardingManager instance.
    """
    global _ONBOARDING
    if _ONBOARDING is None:
        with _OB_LOCK:
            if _ONBOARDING is None:
                _ONBOARDING = OnboardingManager()
    return _ONBOARDING


def reset_onboarding_manager() -> None:
    """Reset the singleton for testing."""
    global _ONBOARDING
    with _OB_LOCK:
        if _ONBOARDING is not None:
            _ONBOARDING.reset()
        _ONBOARDING = None
