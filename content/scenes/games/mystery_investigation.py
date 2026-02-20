"""
Mystery Investigation game — CosySim scene module
===================================================
Exposes a Flask Blueprint (``mystery_bp``) that can be registered on any
existing Flask app.

The player (or a character driven by AgentGovernor) works through a 5-clue
mystery.  The active character uses the MCP tools ``search_memory``,
``get_random_topic("mystery_clues")``, ``set_game_state``, and
``get_game_state`` to progress.  When all clues are found the player must name
the culprit to win.

Game flow
---------
1. ``POST /games/mystery/start``       – choose a case and reset state.
2. ``GET  /games/mystery/clue``        – reveal the next clue (advances
                                         ``clues_found``).
3. ``POST /games/mystery/accuse``      – name the culprit.
4. ``GET  /games/mystery/state``       – poll current state.
5. ``POST /games/mystery/end``         – abandon the case early.

Game state keys (stored in GameState under ``mystery_<character_id>``)
----------------------------------------------------------------------
- ``active``          bool
- ``scene``           str  "mystery"
- ``character_id``    str
- ``case_title``      str
- ``culprit``         str  (secret — only revealed on win/end)
- ``clues_total``     int  (always 5)
- ``clues_found``     int
- ``clues_revealed``  list[str]
- ``accusation``      str | None
- ``won``             bool
- ``started_at``      float
- ``ended_at``        float | None
"""

from __future__ import annotations

import random
import time
import logging

from flask import Blueprint, jsonify, request

logger = logging.getLogger(__name__)

# ── Mystery cases ─────────────────────────────────────────────────────────────

CASES = [
    {
        "title":   "The Vanishing Heirloom",
        "culprit": "Sebastian the butler",
        "setting": "A grand manor house during a dinner party",
        "victim":  "Lady Ashworth",
        "clues": [
            "A muddy boot print was found near the safe that perfectly matches a size 11.",
            "Sebastian was overheard arguing with Lady Ashworth about unpaid wages earlier.",
            "The safe key was last seen on it's hook at 7 PM; now it's gone.",
            "A torn piece of fabric from a butler's uniform was caught on the safe door.",
            "Sebastian's room contains a hidden compartment behind the mirror.",
        ],
        "red_herrings": [
            "The gardener was seen near the manor at 8 PM but was trimming hedges.",
            "Lady Ashworth's niece recently updated her will but has a solid alibi.",
        ],
    },
    {
        "title":   "The Midnight Poisoning",
        "culprit": "Dr. Harlow",
        "setting": "An exclusive members' club in the city",
        "victim":  "Lord Pennington",
        "clues": [
            "A vial labelled 'harmless tonic' was found in a waste bin near table 7.",
            "Dr. Harlow had prescribed Lord Pennington medication for six months.",
            "The club's CCTV shows a figure in a grey coat visiting table 7 at 11:40 PM.",
            "Dr. Harlow's grey coat has a faint chemical stain on the left sleeve.",
            "A pharmacy receipt in Dr. Harlow's name lists an unusual compound not on any prescription.",
        ],
        "red_herrings": [
            "The head waiter had a heated argument with Lord Pennington about a tip.",
            "An anonymous letter was sent to Lord Pennington warning him of enemies.",
        ],
    },
    {
        "title":   "The Stolen Masterpiece",
        "culprit": "Vivienne the art curator",
        "setting": "The Harrington Gallery on the night of a gala",
        "victim":  "The gallery — a Monet worth £2 million went missing",
        "clues": [
            "One security camera was mysteriously offline between 9 PM and 10 PM.",
            "Vivienne has the access code that can disable individual cameras.",
            "Packing foam matching the Monet's frame was found in the loading bay.",
            "A delivery manifest signed 'V. Crane' — Vivienne's maiden name — approved a late van.",
            "A private buyer in Geneva has already been contacted about a 'newly available' Monet.",
        ],
        "red_herrings": [
            "A protestor was removed from the gala for shouting about art commercialisation.",
            "The night security guard fell asleep for 20 minutes but was on the other wing.",
        ],
    },
]

CLUES_PER_GAME = 5


def _game_id(character_id: str) -> str:
    return f"mystery_{character_id}"


def _get_gs():
    from engine.mcp.comms_framework import get_game_state
    return get_game_state()


# ── Flask Blueprint ───────────────────────────────────────────────────────────

mystery_bp = Blueprint(
    "mystery",
    __name__,
    url_prefix="/games/mystery",
)


@mystery_bp.route("/start", methods=["POST"])
def start():
    """Start a new mystery investigation."""
    body = request.get_json(silent=True) or {}
    character_id: str = body.get("character_id", "default")
    case_index: int   = int(body.get("case_index", random.randint(0, len(CASES) - 1)))
    case_index        = max(0, min(case_index, len(CASES) - 1))

    gid  = _game_id(character_id)
    gs   = _get_gs()
    case = CASES[case_index]

    gs.reset(gid)
    gs.set(gid, "active", True)
    gs.set(gid, "scene", "mystery")
    gs.set(gid, "character_id", character_id)
    gs.set(gid, "case_title", case["title"])
    gs.set(gid, "setting", case["setting"])
    gs.set(gid, "victim", case["victim"])
    gs.set(gid, "culprit", case["culprit"])        # secret
    gs.set(gid, "clues_total", CLUES_PER_GAME)
    gs.set(gid, "clues_found", 0)
    gs.set(gid, "clues_revealed", [])
    gs.set(gid, "red_herrings_revealed", [])
    gs.set(gid, "accusation", None)
    gs.set(gid, "won", False)
    gs.set(gid, "started_at", time.time())
    gs.set(gid, "ended_at", None)

    # store case clues for sequential reveal
    gs.set(gid, "_clues_pool", case["clues"])
    gs.set(gid, "_red_herrings_pool", case["red_herrings"])

    logger.info(
        "Mystery started: character=%s case='%s' game_id=%s",
        character_id, case["title"], gid,
    )

    return jsonify({
        "status":      "started",
        "game_id":     gid,
        "case_title":  case["title"],
        "setting":     case["setting"],
        "victim":      case["victim"],
        "clues_total": CLUES_PER_GAME,
    })


@mystery_bp.route("/clue", methods=["GET"])
def next_clue():
    """Reveal the next clue (or a red herring every 3rd request)."""
    character_id = request.args.get("character_id", "default")
    gid = _game_id(character_id)
    gs  = _get_gs()

    if not gs.get(gid, "active"):
        return jsonify({"error": "No active case. Call /start first."}), 400

    clues_found: int = gs.get(gid, "clues_found") or 0
    clues_pool: list = gs.get(gid, "_clues_pool") or []
    revealed: list   = gs.get(gid, "clues_revealed") or []
    rh_pool: list    = gs.get(gid, "_red_herrings_pool") or []
    rh_revealed: list = gs.get(gid, "red_herrings_revealed") or []

    if clues_found >= CLUES_PER_GAME:
        return jsonify({
            "message":     "All clues found! Make your accusation.",
            "clues_found": clues_found,
            "clues_total": CLUES_PER_GAME,
        })

    # Every 3rd clue request, slip in a red herring
    give_red_herring = (clues_found > 0) and (clues_found % 3 == 2) and rh_pool

    if give_red_herring and rh_pool:
        clue_text = rh_pool.pop(0)
        rh_revealed.append(clue_text)
        gs.set(gid, "_red_herrings_pool", rh_pool)
        gs.set(gid, "red_herrings_revealed", rh_revealed)
        return jsonify({
            "clue":        clue_text,
            "type":        "red_herring",
            "clues_found": clues_found,
            "clues_total": CLUES_PER_GAME,
        })

    if not clues_pool:
        return jsonify({"error": "No more clues available."}), 400

    clue_text = clues_pool.pop(0)
    revealed.append(clue_text)
    clues_found += 1

    gs.set(gid, "_clues_pool", clues_pool)
    gs.set(gid, "clues_revealed", revealed)
    gs.set(gid, "clues_found", clues_found)

    return jsonify({
        "clue":        clue_text,
        "type":        "real",
        "clues_found": clues_found,
        "clues_total": CLUES_PER_GAME,
        "all_found":   clues_found >= CLUES_PER_GAME,
    })


@mystery_bp.route("/accuse", methods=["POST"])
def accuse():
    """Make an accusation.  Returns win/loss and the real culprit."""
    body = request.get_json(silent=True) or {}
    character_id: str = body.get("character_id", "default")
    suspect: str      = (body.get("suspect") or "").strip().lower()
    gid = _game_id(character_id)
    gs  = _get_gs()

    if not gs.get(gid, "active"):
        return jsonify({"error": "No active case."}), 400

    culprit: str    = (gs.get(gid, "culprit") or "").lower()
    clues_found     = gs.get(gid, "clues_found") or 0
    gs.set(gid, "accusation", suspect)

    # Fuzzy match — accept if the suspect string is contained in the culprit str or vice-versa
    correct = suspect and (suspect in culprit or culprit in suspect)
    gs.set(gid, "won", correct)
    gs.set(gid, "active", False)
    gs.set(gid, "ended_at", time.time())

    logger.info(
        "Mystery accusation: character=%s suspect='%s' culprit='%s' correct=%s",
        character_id, suspect, culprit, correct,
    )

    return jsonify({
        "correct":       correct,
        "suspect":       suspect,
        "real_culprit":  gs.get(gid, "culprit"),
        "clues_found":   clues_found,
        "message": (
            "Correct! You solved the mystery!" if correct
            else f"Wrong! The real culprit was {gs.get(gid, 'culprit')}."
        ),
    })


@mystery_bp.route("/state", methods=["GET"])
def state():
    character_id = request.args.get("character_id", "default")
    gid  = _game_id(character_id)
    gs   = _get_gs()
    data = {k: v for k, v in (gs.all_games().get(gid) or {}).items()
            if not k.startswith("_")}           # hide internal pools
    # hide culprit until game ends
    if data.get("active"):
        data.pop("culprit", None)
    return jsonify(data)


@mystery_bp.route("/end", methods=["POST"])
def end():
    body = request.get_json(silent=True) or {}
    character_id: str = body.get("character_id", "default")
    gid = _game_id(character_id)
    gs  = _get_gs()

    real_culprit = gs.get(gid, "culprit")
    clues_found  = gs.get(gid, "clues_found") or 0
    gs.set(gid, "active", False)
    gs.set(gid, "ended_at", time.time())

    return jsonify({
        "status":      "abandoned",
        "real_culprit": real_culprit,
        "clues_found":  clues_found,
    })


# ── Standalone helper (importable without Flask) ──────────────────────────────

class MysteryGame:
    """
    Programmatic wrapper — useful for agent integration or testing.
    """

    def __init__(self, character_id: str = "default") -> None:
        self.character_id = character_id
        self.game_id = _game_id(character_id)

    def start(self, case_index: int | None = None) -> dict:
        idx = case_index if case_index is not None else random.randint(0, len(CASES) - 1)
        case = CASES[max(0, min(idx, len(CASES) - 1))]
        gs = _get_gs()
        gs.reset(self.game_id)
        for k, v in {
            "active": True, "scene": "mystery",
            "character_id": self.character_id,
            "case_title": case["title"],
            "setting": case["setting"],
            "victim": case["victim"],
            "culprit": case["culprit"],
            "clues_total": CLUES_PER_GAME,
            "clues_found": 0,
            "clues_revealed": [],
            "accusation": None,
            "won": False,
            "started_at": time.time(),
            "_clues_pool": list(case["clues"]),
            "_red_herrings_pool": list(case["red_herrings"]),
        }.items():
            gs.set(self.game_id, k, v)
        return {"case_title": case["title"], "setting": case["setting"]}

    def next_clue(self) -> dict:
        gs = _get_gs()
        pool: list = gs.get(self.game_id, "_clues_pool") or []
        if not pool:
            return {"message": "No more clues."}
        clue = pool.pop(0)
        gs.set(self.game_id, "_clues_pool", pool)
        revealed = gs.get(self.game_id, "clues_revealed") or []
        revealed.append(clue)
        gs.set(self.game_id, "clues_revealed", revealed)
        gs.increment(self.game_id, "clues_found")
        return {"clue": clue, "clues_found": gs.get(self.game_id, "clues_found")}

    def accuse(self, suspect: str) -> dict:
        gs = _get_gs()
        culprit = (gs.get(self.game_id, "culprit") or "").lower()
        correct = suspect.lower() in culprit or culprit in suspect.lower()
        gs.set(self.game_id, "won", correct)
        gs.set(self.game_id, "active", False)
        gs.set(self.game_id, "accusation", suspect)
        return {"correct": correct, "real_culprit": gs.get(self.game_id, "culprit")}

    @property
    def state(self) -> dict:
        return {
            k: v for k, v in (_get_gs().all_games().get(self.game_id) or {}).items()
            if not k.startswith("_")
        }
