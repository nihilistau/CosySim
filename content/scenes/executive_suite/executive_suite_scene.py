"""Executive Suite — neon corporate OS desktop scene.
=====================================================

A full-screen neon "operating system" desktop for the executive pillar — a
windowed NeonOS shell (animated skyline + office bezel, left app dock,
draggable windows, bottom taskbar) that later hosts mail, files, notes,
music, code, terminal and a live in-world AI assistant.

This module ships the OS SHELL (ES-T2): the backend that serves the desktop
template and a minimal ``/api/state`` endpoint feeding the system tray
(game clock from :class:`WorldState`, plus config-driven heat / network /
battery readouts). Individual apps register themselves client-side via the
``window.ES`` app-registry API and add their own backend routes in later
v1.62 tasks.

The scene mirrors the canonical FlaskScene template (see
``content/scenes/lab_break/lab_break_scene.py``): FlaskScene base class with
Socket.IO, a one-route full-screen desktop UI, a ``/api/state`` endpoint,
and minimal lifecycle hooks.

Version: v1.62.1 [2026-06-15]
Author:  CosySim Team

Change Log:
    v1.62.1 [2026-06-15] — Unified comms backbone wiring (L1): Mail now reads
                            the :class:`~engine.world.comms_log.GlobalCommsLog`
                            as the single source of truth — the inbox is built
                            from the player's conversations (``query(participants=
                            ['user'])`` grouped by thread) and a new INTERCEPTS
                            folder surfaces comms the player obtained via phone
                            hacking (entries the player wasn't a party to but
                            ``observed_by`` includes ``'user'``, plus
                            ``metadata.planted by user``). Send still persists to
                            the phone thread AND logs to the comms backbone.
                            Added a desktop Intel surface: ``/api/intel/breaches``
                            (``kind='notification' metadata.notification=
                            'phone_hacked'``) → breach toasts/badge, and
                            ``/api/intel/oracle`` → the Oracle ``read_the_signal``
                            cryptic line. Defensive throughout (empty states,
                            comms-log failure degrades gracefully).
    v1.62.0 [2026-06-15] — Final polish (ES-T5): module-level
                            ``_sanitize_assistant_reply`` strips leaked model
                            meta/instruction artifacts (``<<DOC|...>>`` blocks,
                            leading system/metadata markdown headers, stray role
                            prefixes) from the agent reply BEFORE it is stored /
                            emitted / returned; assistant system prompt tightened
                            to discourage markdown/meta/stage-direction leakage.
    v1.62.0 [2026-06-15] — Live AI assistant + live system tray (ES-T4): adds the
                            assistant dispatch (socket ``assistant_message`` →
                            ``assistant_reply``/``assistant_typing`` + REST
                            ``POST /api/assistant/send`` + ``/api/assistant/agents``)
                            reusing the engine CharacterAgent/VirtualAgentManager
                            pipeline; tray ``heat`` now reads live PlayerState.
    v1.62.0 [2026-06-15] — Functional OS app backends (ES-T3): /api/files/*,
                            /api/mail/*, /api/notes, /api/console. Read real
                            data (inventory/catalog, phone comms, notes JSON);
                            sandboxed file roots + whitelisted console commands.
    v1.62.0 [2026-06-15] — OS desktop shell (ES-T2): window manager + dock +
                            taskbar + skyline; /api/state returns live clock +
                            tray readouts (replaces ES-T1 placeholder)
    v1.62.0 [2026-06-15] — Initial scaffold (ES-T1): bootable placeholder scene,
                            registered for launcher/TUI/hub + auto-start

CONNECTS: FlaskScene, SocketIO, WorldState, get_config
CALLED BY: launcher.py, TUI, hub
EMITS: state_update Socket.IO event
"""
from __future__ import annotations

import json
import logging
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

from flask import jsonify, render_template, request
from flask_socketio import emit

from engine.scenes.flask_scene import FlaskScene

logger = logging.getLogger(__name__)

SCENE_ID = "executive_suite"
# v1.62.0 [2026-06-15] — Structured logging context (SCENE_ID prefix + operation tags)

# v1.62.0 [2026-06-15] — App backend constants (ES-T3 functional OS apps)
# Whitelisted, read-only roots the Files app may browse (no arbitrary FS).
_SAFE_FILE_ROOTS = {"inventory", "catalog", "data"}
# Whitelist of console commands the sandboxed Terminal app accepts. NO shell
# exec, NO arbitrary code — each maps to a small read-only handler.
_CONSOLE_COMMANDS = ("help", "status", "whoami", "scenes", "world", "inbox", "clear")

# v1.62.1 [2026-06-15] — Mail/Intel (L1) constants. The player is 'user' in the
# comms log; player conversations live on the phone channels; NPC↔NPC chatter
# (which the player can only see by hacking) lives on 'npc_dm'.
_PLAYER_ID = "user"
_PLAYER_CHANNELS = ("phone_dm", "phone_group")
# Channels whose entries, when observed_by 'user', count as a HACK intercept
# (comms the player was never originally a party to).
_INTERCEPT_CHANNELS = ("npc_dm", "npc_group")
# How many comms-log rows to scan when building the inbox / intercepts views.
_MAIL_SCAN_LIMIT = 400

# v1.62.0 [2026-06-15] — Assistant (ES-T4) constants. Seeded companions the
# "Add my Agent" picker may drive the live AI assistant with; default is aria.
_ASSISTANT_AGENTS = ("aria", "lola", "mira", "frankie", "viktor")
_ASSISTANT_DEFAULT_AGENT = "aria"
# Friendly fallback line when the LLM (LMStudio) is unreachable — never a 500.
_ASSISTANT_FALLBACK = "(comms link to my agent is down — try me again in a moment.)"

# v1.62.0 [2026-06-15] — Assistant reply sanitizer (ES-T5 polish). The local
# LMStudio model occasionally leaks instruction/meta artifacts into in-character
# replies (``<<DOC|...>>`` / ``<<...>>`` blocks, leading ``### System Metadata``
# markdown headers, role-leak prefixes). These patterns strip that noise while
# being conservative about normal prose / emoji.
# Markdown header lines that look like leaked system/meta sections.
_RE_META_HEADER = re.compile(
    r"^\s{0,3}#{1,6}\s*(system\s*metadata|metadata|instructions?|doc|document|"
    r"system\s*prompt|context|notes?\s*to\s*self)\b.*$",
    re.IGNORECASE | re.MULTILINE,
)
# A leading role-leak prefix at the very start ("assistant:", "Aria:", etc.).
_RE_ROLE_PREFIX = re.compile(
    r"^\s*(assistant|system|user|ai|bot|[A-Z][\w'’-]{1,24})\s*:\s+",
)
# A single leading markdown list-bullet marker ("- ", "* ", "• ") on the reply.
_RE_LEADING_BULLET = re.compile(r"^\s*[-*•]\s+")
# Three or more blank lines collapse to a single blank line.
_RE_EXCESS_BLANKS = re.compile(r"\n{3,}")
# Trailing whitespace on each line.
_RE_TRAILING_WS = re.compile(r"[ \t]+$", re.MULTILINE)


def _sanitize_assistant_reply(text: str) -> str:
    """Strip leaked model meta/instruction artifacts from an assistant reply.

    The local LMStudio model sometimes contaminates in-character replies with
    leaked scaffolding — ``<<DOC|...>>`` / ``<<...>>`` blocks, leading markdown
    metadata/system headers (``### System Metadata``, ``# Instructions`` …) and
    stray role prefixes (``assistant:`` / ``Aria:`` at the very start). This
    helper removes that noise while staying conservative: it does NOT touch
    normal prose, mid-sentence punctuation, ordinary ``#hashtags`` or emoji.

    Steps (in order):
      1. drop ``<<...>>`` / ``<<DOC...>>`` style blocks,
      2. remove leading markdown meta/system header lines (only while they sit
         at the very top of the reply — never headers buried in real prose),
      3. trim a single leading role-leak prefix (``assistant:`` / ``Name:``)
         and a single leading markdown list-bullet on an otherwise-single-line
         reply,
      4. collapse excess whitespace / blank lines and strip.

    Version: v1.62.0 [2026-06-15]
    """
    if not text:
        return text

    # 1) Bracketed meta/doc blocks anywhere in the text. Absorb a single space on
    # each side so removing an inline block doesn't leave a double space.
    cleaned = re.sub(r" ?<<[^>]*?>> ?", " ", text, flags=re.DOTALL)

    # 2) Strip leading meta/system markdown headers — only consume them while
    # they remain at the top, so we never delete a ``#`` line inside real prose.
    lines = cleaned.split("\n")
    while lines:
        head = lines[0]
        if not head.strip():
            lines.pop(0)
            continue
        if _RE_META_HEADER.match(head):
            lines.pop(0)
            # Also drop an immediately-following indented/bullet meta body until
            # the next blank line, so the header's content goes with it.
            while lines and lines[0].strip() and (
                lines[0].lstrip().startswith(("-", "*", ">", "|"))
                or lines[0][:1] in (" ", "\t")
            ):
                lines.pop(0)
            continue
        break
    cleaned = "\n".join(lines)

    # 3) Trim a single stray role-leak prefix at the very start.
    cleaned = _RE_ROLE_PREFIX.sub("", cleaned, count=1)

    # 3b) Drop a single leading markdown list-bullet, but ONLY when the reply is
    # a single bullet (not a genuine multi-item list) — conversational replies
    # should never start with "- "/"* "/"• ".
    if "\n" not in cleaned.strip():
        cleaned = _RE_LEADING_BULLET.sub("", cleaned, count=1)

    # 4) Collapse excess whitespace.
    cleaned = _RE_TRAILING_WS.sub("", cleaned)
    cleaned = _RE_EXCESS_BLANKS.sub("\n\n", cleaned)
    return cleaned.strip()


# ──── Markets (D-T2 "The Exchange") helpers ───────────────────
# v1.63.0 [2026-06-16] — The Executive Suite Markets app trades the ONE engine
# economy (engine.world.market.get_market) — the SAME Market The Grid surfaces
# in D-T1. No parallel market. Player id matches the Grid ("player1") so trade
# records, wallet and inventory line up across both surfaces.
_MARKETS_PLAYER_ID = "player1"
# Last-seen good_id -> shop_price per district, used to derive the ▲/▼/▬ trend
# on the next /api/markets/state read so prices visibly move as the economy ticks.
_MARKETS_LAST_PRICES: Dict[str, Dict[str, int]] = {}


def _markets_district() -> str:
    """Return the engine-Market district the Markets app trades (config-driven).

    Reads ``executive_suite.market_district`` (default ``"DOWNTOWN"`` — the same
    default the Grid uses, so the two surfaces show parity prices). Never raises.

    Returns:
        The configured district id, or ``"DOWNTOWN"`` on any config failure.
    """
    try:
        from engine.config import get_config  # noqa: PLC0415
        return str(get_config().get("executive_suite.market_district", "DOWNTOWN")) or "DOWNTOWN"
    except Exception:
        return "DOWNTOWN"


# ──── Scene Implementation ────────────────────────────────────

# v1.62.0 [2026-06-15] — OS desktop shell on FlaskScene base
class ExecutiveSuiteScene(FlaskScene):
    """Executive Suite: a neon corporate OS desktop (the NeonOS shell).

    Serves a full-screen windowed desktop — animated skyline, office bezel,
    left app dock, draggable windows and a bottom taskbar. The shell defines
    the ``window.ES`` app-registry API; mail / files / notes / music / code /
    terminal / assistant apps register against it in later v1.62 tasks.

    CONNECTS: FlaskScene, SocketIO, WorldState, get_config
    CALLED BY: launcher.py, TUI, hub
    EMITS: state_update Socket.IO event
    """

    SCENE_METADATA = {
        "name": "executive_suite",
        "display_name": "EXECUTIVE SUITE",
        "port": 5596,
        "type": "game",
        "accent_color": "#06b6d4",
        "description": "A full neon OS desktop — mail, files, your live AI assistant.",
        "version": "1.62.1",
    }

    def __init__(self, config: Optional[Dict[str, Any]] = None,
                 host: str = "0.0.0.0") -> None:
        super().__init__(host=host, port=self.SCENE_METADATA["port"])
        self.config = config or {}

        # v1.62.0 [2026-06-15] — Assistant (ES-T4): per-agent CharacterAgent cache
        # (reuses the existing engine agent pipeline) + per-agent chat history so
        # the live companion keeps short-term context between messages.
        self._assistant_agents: Dict[str, Any] = {}
        self._assistant_history: Dict[str, List[Dict[str, str]]] = {}

        # Scene-specific secret key
        self.app.config["SECRET_KEY"] = "executive-suite-scene"

        # Scene-specific route registrations
        self.register_bench_route(self.app, self.socketio)
        self._register_routes()
        self._setup_socketio_handlers()

    # ── Routes ─────────────────────────────────────────────────────

    def _register_routes(self) -> None:
        """Register all Flask API routes."""
        app = self.app

        @app.route("/")
        def index():
            return render_template(
                "executive_suite.html",
                scene_data=self._get_scene_state(),
            )

        @app.route("/api/state")
        def get_state():
            return jsonify(self._get_scene_state())

        # ── App backends (ES-T3) — each app owns its /api/<app>/* namespace ──
        # v1.62.0 [2026-06-15] — Functional OS app routes; read real game data,
        # log in Oracle format, and return JSON errors (never 500 silently).

        # ── files ──────────────────────────────────────────────────────
        @app.route("/api/files/tree")
        def files_tree():
            try:
                return jsonify(self._files_tree())
            except Exception as exc:
                logger.error("[%s] files tree failed (operation=files): %s", SCENE_ID, exc)
                return jsonify({"error": "tree unavailable", "sections": []}), 200

        @app.route("/api/files/read")
        def files_read():
            path = request.args.get("path", "")
            try:
                return jsonify(self._files_read(path))
            except Exception as exc:
                logger.error("[%s] files read failed (operation=files, path=%s): %s",
                             SCENE_ID, path, exc)
                return jsonify({"error": "read unavailable"}), 200

        # ── mail (unified GlobalCommsLog — inbox + intercepts) ──────────────
        # v1.62.1 [2026-06-15] — L1: reads the comms backbone (single source of
        # truth). /api/mail/intercepts surfaces hacked/planted comms.
        @app.route("/api/mail/threads")
        def mail_threads():
            try:
                return jsonify(self._mail_threads())
            except Exception as exc:
                logger.error("[%s] mail threads failed (operation=mail): %s", SCENE_ID, exc)
                return jsonify({"threads": [], "unread": 0, "empty": True}), 200

        @app.route("/api/mail/intercepts")
        def mail_intercepts():
            try:
                return jsonify(self._mail_intercepts())
            except Exception as exc:
                logger.error("[%s] mail intercepts failed (operation=mail): %s", SCENE_ID, exc)
                return jsonify({"intercepts": [], "count": 0, "empty": True}), 200

        @app.route("/api/mail/thread/<thread_id>")
        def mail_thread(thread_id: str):
            try:
                return jsonify(self._mail_thread(thread_id))
            except Exception as exc:
                logger.error("[%s] mail thread failed (operation=mail, thread=%s): %s",
                             SCENE_ID, thread_id, exc)
                return jsonify({"error": "thread unavailable", "messages": []}), 200

        @app.route("/api/mail/send", methods=["POST"])
        def mail_send():
            body = request.get_json(silent=True) or {}
            try:
                return jsonify(self._mail_send(body))
            except Exception as exc:
                logger.error("[%s] mail send failed (operation=mail): %s", SCENE_ID, exc)
                return jsonify({"success": False, "error": "send failed"}), 200

        # ── notes ──────────────────────────────────────────────────────
        @app.route("/api/notes", methods=["GET"])
        def notes_get():
            try:
                return jsonify(self._notes_get())
            except Exception as exc:
                logger.error("[%s] notes get failed (operation=notes): %s", SCENE_ID, exc)
                return jsonify({"notes": [], "error": "notes unavailable"}), 200

        @app.route("/api/notes", methods=["POST"])
        def notes_post():
            body = request.get_json(silent=True) or {}
            try:
                return jsonify(self._notes_save(body))
            except Exception as exc:
                logger.error("[%s] notes save failed (operation=notes): %s", SCENE_ID, exc)
                return jsonify({"success": False, "error": "save failed"}), 200

        # ── terminal (sandboxed console) ───────────────────────────────
        @app.route("/api/console", methods=["POST"])
        def console():
            body = request.get_json(silent=True) or {}
            cmd = str(body.get("command", "")).strip()
            try:
                return jsonify(self._console(cmd))
            except Exception as exc:
                logger.error("[%s] console failed (operation=terminal, cmd=%s): %s",
                             SCENE_ID, cmd, exc)
                return jsonify({"ok": False, "lines": ["error: command failed"]}), 200

        # ── assistant (ES-T4) — live in-world AI companion ─────────────
        # v1.62.0 [2026-06-15] — REST fallback for the Assistant app. The primary
        # path is the Socket.IO ``assistant_message`` handler; this mirrors it so
        # the panel still works when the socket is unavailable. Reuses the engine
        # CharacterAgent pipeline (never calls LMStudio raw); degrades to a
        # friendly fallback line (never a 500) when the LLM is unreachable.
        @app.route("/api/assistant/agents")
        def assistant_agents():
            return jsonify(self._assistant_roster())

        @app.route("/api/assistant/send", methods=["POST"])
        def assistant_send():
            body = request.get_json(silent=True) or {}
            text = str(body.get("text", "")).strip()
            agent_id = str(body.get("agent_id", "") or _ASSISTANT_DEFAULT_AGENT).strip()
            try:
                return jsonify(self._assistant_reply(agent_id, text))
            except Exception as exc:
                logger.error("[%s] assistant send failed (operation=assistant, agent=%s): %s",
                             SCENE_ID, agent_id, exc)
                return jsonify({
                    "text": _ASSISTANT_FALLBACK, "agent_id": agent_id,
                    "fallback": True, "error": "assistant unavailable",
                }), 200

        # ── intel (L1) — breach alerts + oracle signal on the desktop ──────
        # v1.62.1 [2026-06-15] — Surface the phone-hacking + oracle features in
        # the OS. Both routes read the unified GlobalCommsLog / oracle pack and
        # degrade gracefully (never a 500).
        @app.route("/api/intel/breaches")
        def intel_breaches():
            since = request.args.get("since")
            try:
                return jsonify(self._intel_breaches(since))
            except Exception as exc:
                logger.error("[%s] intel breaches failed (operation=intel): %s", SCENE_ID, exc)
                return jsonify({"breaches": [], "count": 0}), 200

        @app.route("/api/intel/oracle", methods=["POST"])
        def intel_oracle():
            try:
                return jsonify(self._intel_oracle())
            except Exception as exc:
                logger.error("[%s] intel oracle failed (operation=intel): %s", SCENE_ID, exc)
                return jsonify({
                    "text": "The streams writhe and refuse me. Return when the static settles.",
                    "ok": False,
                }), 200

        # ── markets (D-T2 "The Exchange") — the ONE engine economy ─────────
        # v1.63.0 [2026-06-16] — Markets app surfaces the SAME live engine
        # Market (engine.world.market.get_market) The Grid trades (D-T1), for
        # the configured executive_suite.market_district (default DOWNTOWN — the
        # Grid's default, so prices/trades match across both surfaces). Buy/sell
        # route straight through get_market().buy/sell so credits, inventory and
        # heat settle via the one economy. Defensive throughout — never 500.
        @app.route("/api/markets/state")
        def markets_state():
            try:
                return jsonify(self._markets_state())
            except Exception as exc:
                logger.error("[%s] markets state failed (operation=markets): %s", SCENE_ID, exc)
                return jsonify({
                    "district": _markets_district(), "goods": [], "inventory": [],
                    "credits": 0, "stats": {}, "error": "markets offline",
                }), 200

        @app.route("/api/markets/buy", methods=["POST"])
        def markets_buy():
            body = request.get_json(silent=True) or {}
            try:
                return jsonify(self._markets_trade("buy", body))
            except Exception as exc:
                logger.error("[%s] markets buy failed (operation=markets): %s", SCENE_ID, exc)
                return jsonify({"success": False, "error": "trade failed"}), 200

        @app.route("/api/markets/sell", methods=["POST"])
        def markets_sell():
            body = request.get_json(silent=True) or {}
            try:
                return jsonify(self._markets_trade("sell", body))
            except Exception as exc:
                logger.error("[%s] markets sell failed (operation=markets): %s", SCENE_ID, exc)
                return jsonify({"success": False, "error": "trade failed"}), 200

    # ── App backend helpers (ES-T3) ─────────────────────────────────────
    # v1.62.0 [2026-06-15]

    def _files_tree(self) -> Dict[str, Any]:
        """Build the Files browser tree + grid from REAL game data.

        Sources: player inventory + the item catalog (read-only), plus a
        sandboxed view of safe JSON artifacts under ``data/``. All grid entries
        are read-only; paths are confined to the whitelisted roots.
        """
        from engine.world.inventory import get_inventory, ITEM_CATALOG

        sections: List[Dict[str, Any]] = []

        # PINNED — live inventory
        inv = get_inventory()
        snap = inv.to_dict()
        inv_files = []
        for it in snap.get("items", []):
            inv_files.append({
                "name": it.get("name", it.get("item_id")),
                "path": "inventory/" + it.get("item_id", ""),
                "kind": "doc",
                "size": "x%d" % it.get("quantity", 1),
                "meta": it.get("rarity", ""),
            })
        sections.append({
            "label": "PINNED", "id": "inventory", "icon": "📦",
            "title": "inventory · %d items" % len(inv_files),
            "files": inv_files,
        })

        # DEVICES — full item catalog (read-only reference)
        cat_files = []
        for item_id, meta in ITEM_CATALOG.items():
            cat_files.append({
                "name": meta.get("name", item_id),
                "path": "catalog/" + item_id,
                "kind": "code" if meta.get("category") in ("software", "cyberdeck") else "doc",
                "size": "₵%s" % meta.get("price", "?"),
                "meta": meta.get("category", ""),
            })
        sections.append({
            "label": "DEVICES", "id": "catalog", "icon": "🗂",
            "title": "item catalog · %d entries" % len(cat_files),
            "files": cat_files,
        })

        # DATA — safe JSON artifacts under data/ (sandboxed, read-only)
        data_files = []
        try:
            from engine.paths import DATA_DIR
            for safe_name in ("inventory.json", "executive_suite_notes.json"):
                fp = DATA_DIR / safe_name
                if fp.exists():
                    data_files.append({
                        "name": safe_name,
                        "path": "data/" + safe_name,
                        "kind": "code",
                        "size": "%dB" % fp.stat().st_size,
                        "meta": "json",
                    })
        except Exception as exc:
            logger.debug("[%s] data scan skipped (operation=files): %s", SCENE_ID, exc)
        sections.append({
            "label": "SYSTEM", "id": "data", "icon": "💾",
            "title": "data · %d files" % len(data_files),
            "files": data_files,
        })

        logger.info("[%s] files tree served (operation=files, sections=%d)",
                    SCENE_ID, len(sections))
        return {"sections": sections}

    def _files_read(self, path: str) -> Dict[str, Any]:
        """Return the contents of a single sandboxed file entry.

        Only paths under the whitelisted roots are honoured; anything else is
        rejected (no arbitrary filesystem access).
        """
        root = path.split("/", 1)[0] if "/" in path else path
        if root not in _SAFE_FILE_ROOTS:
            logger.warning("[%s] files read rejected (operation=files, path=%s)",
                           SCENE_ID, path)
            return {"error": "path not allowed"}

        from engine.world.inventory import get_inventory, ITEM_CATALOG
        rest = path.split("/", 1)[1] if "/" in path else ""

        if root == "catalog":
            meta = ITEM_CATALOG.get(rest)
            if not meta:
                return {"error": "not found"}
            return {"name": meta.get("name", rest), "kind": "doc",
                    "body": json.dumps(meta, indent=2)}

        if root == "inventory":
            inv = get_inventory()
            item = inv.get_item(rest)
            if not item:
                return {"error": "not found"}
            return {"name": item.to_dict().get("name", rest), "kind": "doc",
                    "body": json.dumps(item.to_dict(), indent=2)}

        if root == "data":
            from engine.paths import DATA_DIR
            name = Path(rest).name  # strip any traversal
            if name not in ("inventory.json", "executive_suite_notes.json"):
                return {"error": "path not allowed"}
            fp = DATA_DIR / name
            if not fp.exists():
                return {"error": "not found"}
            text = fp.read_text(encoding="utf-8")[:20000]
            return {"name": name, "kind": "code", "body": text}

        return {"error": "not found"}

    def _phone_db(self):
        """Return a PhoneDB instance (lazy import — phone is an optional peer)."""
        from content.scenes.phone.phone_db import PhoneDB
        return PhoneDB()

    def _comms_log(self):
        """Return the GlobalCommsLog singleton (lazy import — optional peer)."""
        from engine.world.comms_log import get_comms_log
        return get_comms_log()

    def _char_name(self, char_id: str, cache: Dict[str, str]) -> str:
        """Resolve a character id to a display name (cached per request)."""
        if not char_id:
            return "unknown"
        if char_id in cache:
            return cache[char_id]
        name = char_id
        try:
            from content.simulation.database.db import Database
            row = Database().get_character(char_id)
            if row and row.get("name"):
                name = row["name"]
        except Exception:
            pass
        cache[char_id] = name
        return name

    # ── Mail (L1) — reads the unified GlobalCommsLog ─────────────────────
    # v1.62.1 [2026-06-15] — The Mail app is now backed by the single source of
    # truth (GlobalCommsLog) instead of raw PhoneDB. The inbox is the player's
    # conversations; the INTERCEPTS folder surfaces comms the player obtained by
    # hacking. Compose/send still persists to the phone thread (so NPC replies
    # keep flowing) AND logs to the comms backbone.

    @staticmethod
    def _is_intercept(entry: Dict[str, Any]) -> bool:
        """Return whether a comms entry is a player HACK intercept/plant.

        An entry is an intercept when the player ``observed_by`` it on a channel
        the player was never a party to (NPC↔NPC), or when the player planted it
        (``metadata.planted`` with ``by == 'user'``). Player-facing breach
        notifications are surfaced separately (Intel), not in the Mail folder.

        Args:
            entry: A deserialized comms-log entry dict.

        Returns:
            ``True`` if the entry should appear in the INTERCEPTS folder.
        """
        meta = entry.get("metadata") or {}
        if meta.get("planted") and meta.get("by") == _PLAYER_ID:
            return True
        observed = entry.get("observed_by") or []
        if _PLAYER_ID in observed and entry.get("channel") in _INTERCEPT_CHANNELS:
            # The player only "owns" this exchange because they hacked it —
            # they are neither sender nor a listed recipient.
            recipients = entry.get("recipient_ids") or []
            if entry.get("sender_id") != _PLAYER_ID and _PLAYER_ID not in recipients:
                return True
        return False

    def _mail_threads(self) -> Dict[str, Any]:
        """Inbox list from the unified GlobalCommsLog (player conversations).

        Builds one inbox row per ``thread_id`` from the player's conversations
        (``query(participants=['user'])``), newest entry per thread. Unread is
        derived from the phone DB read-receipts when available (the comms log is
        append-only and carries no per-user read state). Degrades to an empty
        inbox if the comms log is unavailable.
        """
        try:
            cl = self._comms_log()
            entries = cl.query(participants=[_PLAYER_ID], limit=_MAIL_SCAN_LIMIT)
        except Exception as exc:
            logger.error("[%s] mail threads comms-log read failed (operation=mail): %s",
                         SCENE_ID, exc)
            entries = []

        cache: Dict[str, str] = {}
        # entries are newest-first; first time we see a thread is its latest msg.
        threads: Dict[str, Dict[str, Any]] = {}
        loose: List[Dict[str, Any]] = []
        for e in entries:
            # Breach/system notifications are surfaced via Intel, not the inbox;
            # hacked/planted comms live in the INTERCEPTS folder.
            if e.get("kind") == "notification" or self._is_intercept(e):
                continue
            tid = e.get("thread_id")
            sender = e.get("sender_id", "")
            frm = "You" if sender == _PLAYER_ID else self._char_name(sender, cache)
            row = {
                "id": tid or ("dm:" + sender),
                "from": frm if sender != _PLAYER_ID else self._counterparty(e, cache),
                "preview": (e.get("content") or "")[:120],
                "time": e.get("ts", ""),
                "channel": e.get("channel", ""),
            }
            if tid:
                if tid not in threads:
                    threads[tid] = row
            else:
                loose.append(row)

        out = list(threads.values()) + loose
        out.sort(key=lambda r: r.get("time", ""), reverse=True)

        # Unread counts from the phone read-receipts (best-effort; comms log has none).
        total_unread = self._apply_unread(out)
        logger.info("[%s] mail threads served (operation=mail, threads=%d, unread=%d)",
                    SCENE_ID, len(out), total_unread)
        return {"threads": out, "unread": total_unread, "empty": not out}

    def _counterparty(self, entry: Dict[str, Any], cache: Dict[str, str]) -> str:
        """Resolve the non-player display name for a player-sent entry."""
        for rid in entry.get("recipient_ids") or []:
            if rid != _PLAYER_ID:
                return self._char_name(rid, cache)
        return "thread"

    def _apply_unread(self, rows: List[Dict[str, Any]]) -> int:
        """Annotate inbox rows with a per-thread unread count; return the total.

        The comms log is append-only with no per-user read state, so unread is
        sourced from the phone DB read-receipts when available. Any failure
        leaves unread at 0 (never blocks the inbox).
        """
        total = 0
        try:
            db = self._phone_db()
        except Exception:
            for r in rows:
                r["unread"] = 0
            return 0
        for r in rows:
            n = 0
            tid = r.get("id", "")
            if tid and not tid.startswith("dm:"):
                try:
                    n = int(db.thread_unread(tid))
                except Exception:
                    n = 0
            r["unread"] = n
            total += n
        return total

    def _mail_thread(self, thread_id: str) -> Dict[str, Any]:
        """Full message list for one thread (the preview pane), from the comms log.

        Reads ``comms_log.thread(thread_id)`` (chronological). Marks the matching
        phone thread read (best-effort) so unread counts settle. Intercept-folder
        rows (planted/no real thread) are handled by :meth:`_mail_intercepts`.
        """
        try:
            cl = self._comms_log()
            entries = cl.thread(thread_id, limit=200)
        except Exception as exc:
            logger.error("[%s] mail thread comms-log read failed (operation=mail, thread=%s): %s",
                         SCENE_ID, thread_id, exc)
            entries = []
        if not entries:
            return {"error": "not found", "messages": []}

        cache: Dict[str, str] = {}
        msgs = []
        counterparties: List[str] = []
        for m in entries:
            sid = m.get("sender_id", "")
            if sid and sid != _PLAYER_ID and sid not in counterparties:
                counterparties.append(sid)
            msgs.append({
                "id": m.get("id"),
                "sender_id": sid,
                "from": "You" if sid == _PLAYER_ID else self._char_name(sid, cache),
                "mine": sid == _PLAYER_ID,
                "content": m.get("content", ""),
                "time": m.get("ts", ""),
            })
        try:
            self._phone_db().mark_read(thread_id)
        except Exception:
            pass
        title = self._char_name(counterparties[0], cache) if counterparties else "thread"
        logger.info("[%s] mail thread served (operation=mail, thread=%s, msgs=%d)",
                    SCENE_ID, thread_id, len(msgs))
        return {"id": thread_id, "title": title, "messages": msgs}

    def _mail_intercepts(self) -> Dict[str, Any]:
        """Return the INTERCEPTS folder — comms the player obtained by hacking.

        Scans the comms log for entries the player ``observed_by`` on NPC↔NPC
        channels (comms they weren't a party to) plus messages the player
        planted (``metadata.planted by user``). Each row is clearly labelled
        ``intercepted`` / ``planted`` so the OS makes the payoff of phone hacking
        visible. Degrades to an empty list on any comms-log failure.
        """
        try:
            cl = self._comms_log()
            entries = cl.query(limit=_MAIL_SCAN_LIMIT)
        except Exception as exc:
            logger.error("[%s] mail intercepts comms-log read failed (operation=mail): %s",
                         SCENE_ID, exc)
            entries = []

        cache: Dict[str, str] = {}
        out = []
        for e in entries:
            if not self._is_intercept(e):
                continue
            meta = e.get("metadata") or {}
            planted = bool(meta.get("planted"))
            sender = e.get("sender_id", "")
            recipients = [r for r in (e.get("recipient_ids") or []) if r != _PLAYER_ID]
            out.append({
                "id": e.get("id"),
                "label": "planted" if planted else "intercepted",
                "from": self._char_name(sender, cache),
                "to": ", ".join(self._char_name(r, cache) for r in recipients) or "—",
                "content": e.get("content", ""),
                "channel": e.get("channel", ""),
                "time": e.get("ts", ""),
            })
        out.sort(key=lambda r: r.get("time", ""), reverse=True)
        logger.info("[%s] mail intercepts served (operation=mail, count=%d)",
                    SCENE_ID, len(out))
        return {"intercepts": out, "count": len(out), "empty": not out}

    def _mail_send(self, body: Dict[str, Any]) -> Dict[str, Any]:
        """Persist an outbound message into the phone thread AND the comms log.

        Writing to the phone thread keeps NPC replies flowing (the phone scene
        owns reply generation); logging to the GlobalCommsLog keeps the unified
        backbone — and therefore this Mail inbox — consistent. The comms-log
        write is best-effort and never blocks the send.
        """
        thread_id = str(body.get("thread_id", "")).strip()
        content = str(body.get("content", "")).strip()
        if not thread_id or not content:
            return {"success": False, "error": "thread_id and content required"}
        db = self._phone_db()
        meta = db.get_thread(thread_id)
        if not meta:
            return {"success": False, "error": "unknown thread"}
        msg = db.save_message(thread_id, _PLAYER_ID, content)

        # Mirror the send into the unified comms backbone (single source of truth)
        # so the Mail inbox + Oracle + any observer see it. Best-effort.
        try:
            members = [c for c in (meta.get("members") or []) if c != _PLAYER_ID]
            channel = "phone_group" if (meta.get("type") == "group") else "phone_dm"
            self._comms_log().log(
                channel, _PLAYER_ID, members, content,
                thread_id=thread_id, kind="message",
                metadata={"scene": SCENE_ID},
            )
        except Exception as exc:
            logger.error("[%s] mail send comms-log mirror failed (operation=mail, thread=%s): %s",
                         SCENE_ID, thread_id, exc)

        logger.info("[%s] mail sent (operation=mail, thread=%s, msg=%s)",
                    SCENE_ID, thread_id, msg.get("id"))
        return {"success": True, "message": {
            "id": msg["id"], "from": "You", "mine": True,
            "content": content, "time": msg["created_at"],
        }}

    # ── Intel (L1) — breach alerts + oracle signal ───────────────────────
    # v1.62.1 [2026-06-15] — Surface the phone-hacking + oracle features on the
    # desktop. Breaches read the player's persisted breach notifications from the
    # comms log; the oracle action runs the existing read_the_signal skill.

    def _intel_breaches(self, since: Optional[str] = None) -> Dict[str, Any]:
        """Return persisted phone-breach notifications addressed to the player.

        Reads ``kind='notification'`` entries with
        ``metadata.notification='phone_hacked'`` from the comms log (newest
        first). ``since`` (an entry id) lets the client poll only for breaches it
        hasn't surfaced yet so toasts don't repeat. Degrades to empty on failure.
        """
        try:
            cl = self._comms_log()
            entries = cl.query(participants=[_PLAYER_ID], limit=_MAIL_SCAN_LIMIT)
        except Exception as exc:
            logger.error("[%s] intel breaches comms-log read failed (operation=intel): %s",
                         SCENE_ID, exc)
            return {"breaches": [], "count": 0}

        try:
            since_id = int(since) if since not in (None, "") else None
        except (TypeError, ValueError):
            since_id = None

        cache: Dict[str, str] = {}
        out = []
        for e in entries:
            meta = e.get("metadata") or {}
            if e.get("kind") != "notification" or meta.get("notification") != "phone_hacked":
                continue
            eid = e.get("id")
            if since_id is not None and isinstance(eid, int) and eid <= since_id:
                continue
            out.append({
                "id": eid,
                "attacker": self._char_name(meta.get("attacker") or e.get("sender_id", ""), cache),
                "content": e.get("content", ""),
                "blocked": bool(meta.get("blocked")),
                "success": bool(meta.get("success")),
                "action": meta.get("action", ""),
                "time": e.get("ts", ""),
            })
        logger.info("[%s] intel breaches served (operation=intel, count=%d)",
                    SCENE_ID, len(out))
        return {"breaches": out, "count": len(out)}

    def _intel_oracle(self) -> Dict[str, Any]:
        """Run the Oracle ``read_the_signal`` skill and return its cryptic line.

        Reuses the existing oracle pack (which reads the comms log and grants a
        small bounded reward) rather than re-implementing intel here. Any failure
        returns a graceful in-world line (never a 500).
        """
        from engine.skills.builtin.oracle_skills import read_the_signal
        text = read_the_signal()
        logger.info("[%s] intel oracle served (operation=intel, chars=%d)",
                    SCENE_ID, len(text or ""))
        return {"text": text, "ok": True}

    def _notes_path(self) -> Path:
        from engine.paths import DATA_DIR
        return DATA_DIR / "executive_suite_notes.json"

    def _notes_get(self) -> Dict[str, Any]:
        """Load persisted notes from data/executive_suite_notes.json."""
        fp = self._notes_path()
        if not fp.exists():
            return {"notes": []}
        try:
            data = json.loads(fp.read_text(encoding="utf-8"))
            notes = data.get("notes", []) if isinstance(data, dict) else []
        except Exception:
            notes = []
        logger.info("[%s] notes loaded (operation=notes, count=%d)", SCENE_ID, len(notes))
        return {"notes": notes}

    def _notes_save(self, body: Dict[str, Any]) -> Dict[str, Any]:
        """Persist the full notes list (client sends the whole document set)."""
        notes = body.get("notes")
        if not isinstance(notes, list):
            return {"success": False, "error": "notes must be a list"}
        fp = self._notes_path()
        fp.parent.mkdir(parents=True, exist_ok=True)
        payload = {"notes": notes, "_saved_at": datetime.now(timezone.utc).isoformat()}
        fp.write_text(json.dumps(payload, indent=2), encoding="utf-8")
        logger.info("[%s] notes saved (operation=notes, count=%d)", SCENE_ID, len(notes))
        return {"success": True, "count": len(notes), "saved_at": payload["_saved_at"]}

    def _console(self, cmd: str) -> Dict[str, Any]:
        """Run a whitelisted, read-only console command. No shell exec.

        Unknown commands return a 'command not found' line. Each handler reads
        live game/scene data only.
        """
        word = cmd.split()[0].lower() if cmd else ""
        if not word:
            return {"ok": True, "lines": []}
        if word not in _CONSOLE_COMMANDS:
            logger.info("[%s] console unknown (operation=terminal, cmd=%s)", SCENE_ID, word)
            return {"ok": False, "lines": ["neonsh: command not found: %s" % word,
                                           "type 'help' for available commands"]}

        lines: List[str] = []
        if word == "help":
            lines = ["available commands:",
                     "  status   system + tray readouts",
                     "  whoami   current operator",
                     "  scenes   registered scene roster",
                     "  world    in-game clock / time of day",
                     "  inbox    unread comms summary",
                     "  clear    clear the screen"]
        elif word == "clear":
            return {"ok": True, "clear": True, "lines": []}
        elif word == "whoami":
            lines = ["root@neoncity", "role: operator · clearance F-87"]
        elif word == "status":
            st = self._get_scene_state()
            tray = st.get("tray", {})
            lines = ["NEONOS %s · %s" % (st.get("version", "?"), st.get("status", "?")),
                     "heat     %s%%" % tray.get("heat", "?"),
                     "battery  %s%%" % tray.get("battery", "?"),
                     "network  %s" % tray.get("network", "?"),
                     "volume   %s%%" % tray.get("volume", "?")]
        elif word == "world":
            clk = self._read_clock()
            lines = ["game time: %s" % (clk.get("display") or "—"),
                     "day %s (%s) · hour %s · %s" % (
                         clk.get("game_day"), clk.get("game_day_name"),
                         clk.get("game_hour"), clk.get("time_of_day"))]
        elif word == "scenes":
            try:
                from engine.paths import SCENES_DIR  # noqa: PLC0415
                ids = sorted(p.name for p in SCENES_DIR.iterdir()
                             if p.is_dir() and not p.name.startswith("_"))
                lines = ["registered scenes (%d):" % len(ids)] + ["  " + s for s in ids]
            except Exception:
                lines = ["scene roster unavailable"]
        elif word == "inbox":
            try:
                db = self._phone_db()
                lines = ["unread comms: %d" % db.total_unread(),
                         "threads: %d" % len(db.list_threads())]
            except Exception:
                lines = ["comms offline"]
        logger.info("[%s] console ran (operation=terminal, cmd=%s)", SCENE_ID, word)
        return {"ok": True, "lines": lines}

    # ── Assistant helpers (ES-T4) ───────────────────────────────────────
    # v1.62.0 [2026-06-15] — Live in-world AI companion. Reuses the EXISTING
    # engine agent pipeline (CharacterAgent → VirtualAgentManager), mirroring how
    # the phone scene drives characters. NEVER calls LMStudio raw; handles the
    # LLM being down with a friendly fallback line (no 500s).

    def _assistant_roster(self) -> Dict[str, Any]:
        """Return the seeded companions the 'Add my Agent' picker can choose."""
        from content.simulation.database.db import Database  # noqa: PLC0415
        db = Database()
        agents = []
        for cid in _ASSISTANT_AGENTS:
            row = db.get_character(cid)
            if not row:
                continue
            meta = row.get("metadata") or {}
            agents.append({
                "id": cid,
                "name": row.get("name", cid),
                "tagline": (meta.get("backstory") or "")[:80],
            })
        logger.info("[%s] assistant roster served (operation=assistant, agents=%d)",
                    SCENE_ID, len(agents))
        return {"agents": agents, "default": _ASSISTANT_DEFAULT_AGENT}

    def _get_assistant_agent(self, agent_id: str):
        """Get (or lazily build + cache) the CharacterAgent for a companion.

        Reuses the engine agent pipeline exactly as the other scenes do
        (Character → CharacterAgent), so the assistant inherits persona, RAG
        memory and the shared VirtualAgentManager. Returns ``None`` if the
        character can't be loaded.
        """
        if agent_id in self._assistant_agents:
            return self._assistant_agents[agent_id]
        try:
            from content.simulation.character_system.character import Character  # noqa: PLC0415
            from content.simulation.database.db import Database  # noqa: PLC0415
            from engine.agents.character_agent import CharacterAgent  # noqa: PLC0415
            db = Database()
            char = Character(agent_id, db=db)
            agent = CharacterAgent(char, db=db, scene=SCENE_ID)
            self._assistant_agents[agent_id] = agent
            return agent
        except Exception as exc:
            logger.warning("[%s] assistant agent build failed (operation=assistant, agent=%s): %s",
                           SCENE_ID, agent_id, exc)
            return None

    def _assistant_reply(self, agent_id: str, text: str) -> Dict[str, Any]:
        """Run one user turn through the companion agent and return its reply.

        Mirrors the phone scene's proven path: drive the character through the
        shared :class:`VirtualAgentManager` with a plain message list (no raw
        integrations, which LMStudio rejects). Keeps short per-agent history for
        context. On any LLM error returns ``fallback=True`` with a friendly line.
        """
        if agent_id not in _ASSISTANT_AGENTS:
            agent_id = _ASSISTANT_DEFAULT_AGENT
        if not text:
            return {"text": "(say something and I'll reply.)", "agent_id": agent_id,
                    "fallback": False, "empty": True}

        agent = self._get_assistant_agent(agent_id)
        name = agent_id.title()
        try:
            from content.simulation.database.db import Database  # noqa: PLC0415
            row = Database().get_character(agent_id) or {}
            name = row.get("name", name)
            persona = (row.get("metadata") or {}).get("backstory", "")
        except Exception:
            persona = ""

        hist = self._assistant_history.setdefault(agent_id, [])

        # System prompt: in-world AI assistant framing on the executive desktop.
        # v1.62.0 [2026-06-15] — ES-T5: tightened to discourage the local model's
        # meta/markdown leakage (headers, <<DOC>> blocks, stage directions).
        system = (
            "You are %s, the operator's live in-world AI assistant inside the "
            "NEONOS executive suite — a neon-noir cyberpunk corporate OS. %s\n"
            "Reply in-character as %s, plain conversational text only — no "
            "markdown headers, no meta, no system/instruction notes, no "
            "<<...>> blocks, and no stage directions in brackets unless emotive. "
            "Keep it concise (1-3 sentences), helpful, a little flirty and "
            "street-smart. Never break character or mention being a language "
            "model." % (name, persona, name)
        )

        reply_text = ""
        fallback = False
        try:
            from engine.agents.virtual_agent_manager import get_virtual_agent_manager  # noqa: PLC0415
            from engine.agents.virtual_agent import InferenceRequest  # noqa: PLC0415
            from engine.agents.stream_processor import strip_token_artifacts  # noqa: PLC0415

            msgs: List[Dict[str, str]] = [{"role": "system", "content": system}]
            msgs.extend(hist[-12:])  # short rolling window for context
            msgs.append({"role": "user", "content": text})

            mgr = get_virtual_agent_manager()
            req = InferenceRequest(
                agent_id=agent_id,
                messages=msgs,
                temperature=0.9,
                max_output_tokens=400,
                conversation_id="executive_suite_%s" % agent_id,
                store=True,
                metadata={"scene": SCENE_ID, "character_name": name},
            )
            response = mgr.infer_processed(req)
            reply_text = strip_token_artifacts((response.clean_text or "").strip())
            # v1.62.0 [2026-06-15] — ES-T5: strip leaked meta/instruction
            # artifacts (<<DOC>> blocks, system headers, role prefixes) BEFORE
            # the reply is stored in history / emitted / returned.
            reply_text = _sanitize_assistant_reply(reply_text)
            # Keep the cached agent warm for parity with the engine pipeline.
            _ = agent
        except Exception as exc:
            logger.error("[%s] assistant inference failed (operation=assistant, agent=%s): %s",
                         SCENE_ID, agent_id, exc)
            reply_text = ""

        if not reply_text:
            reply_text = _ASSISTANT_FALLBACK
            fallback = True
        else:
            # Persist the turn into the rolling history (only real replies).
            hist.append({"role": "user", "content": text})
            hist.append({"role": "assistant", "content": reply_text})
            del hist[:-24]  # cap memory growth

        logger.info("[%s] assistant reply (operation=assistant, agent=%s, fallback=%s, chars=%d)",
                    SCENE_ID, agent_id, fallback, len(reply_text))
        return {
            "text": reply_text, "agent_id": agent_id, "name": name,
            "fallback": fallback,
            "time": datetime.now(timezone.utc).isoformat(),
        }

    def _setup_socketio_handlers(self) -> None:
        """Register Socket.IO event handlers."""
        sio = self.socketio

        @sio.on("connect")
        def on_connect():
            emit("state_update", self._get_scene_state())

        # v1.62.0 [2026-06-15] — Clients can poll fresh state over the socket
        @sio.on("request_state")
        def on_request_state():
            emit("state_update", self._get_scene_state())

        # v1.62.0 [2026-06-15] — Assistant (ES-T4): live companion chat over the
        # socket. Emits a typing indicator, runs the message through the engine
        # agent pipeline, then emits the reply. Mirrored by POST /api/assistant/send.
        @sio.on("assistant_message")
        def on_assistant_message(data):
            data = data or {}
            text = str(data.get("text", "")).strip()
            agent_id = str(data.get("agent_id", "") or _ASSISTANT_DEFAULT_AGENT).strip()
            emit("assistant_typing", {"agent_id": agent_id, "typing": True})
            try:
                result = self._assistant_reply(agent_id, text)
            except Exception as exc:
                logger.error("[%s] assistant socket failed (operation=assistant, agent=%s): %s",
                             SCENE_ID, agent_id, exc)
                result = {"text": _ASSISTANT_FALLBACK, "agent_id": agent_id, "fallback": True}
            emit("assistant_typing", {"agent_id": agent_id, "typing": False})
            emit("assistant_reply", result)

    # ── Markets app backend (D-T2 "The Exchange") ───────────────────────
    # v1.63.0 [2026-06-16]
    # CONNECTS: engine.world.market.get_market (the ONE economy — same Market
    #           The Grid surfaces in D-T1), engine.world.player_state,
    #           engine.world.inventory
    # CALLED BY: /api/markets/state, /api/markets/buy, /api/markets/sell

    @staticmethod
    def _markets_get_market() -> Any:
        """Return the live singleton engine Market, or ``None`` if unavailable.

        The Markets app trades the *one* NPC-driven economy — the exact same
        :class:`~engine.world.market.Market` The Grid surfaces (D-T1). Degrades
        to ``None`` (never raises) so the app shows an offline state, not a 500.
        """
        try:
            from engine.world.market import get_market  # noqa: PLC0415
            return get_market()
        except Exception as exc:
            logger.warning("[%s] engine Market unavailable (operation=markets): %s", SCENE_ID, exc)
            return None

    @staticmethod
    def _markets_trend(district: str, good_id: str, price: int) -> str:
        """Return the ▲/▼/▬ trend glyph vs. the last /api/markets/state read.

        Args:
            district: District the price belongs to.
            good_id: Engine good id.
            price: Current shop price.

        Returns:
            ``"▲"`` (rising), ``"▼"`` (falling) or ``"▬"`` (stable / first read).
        """
        prev = _MARKETS_LAST_PRICES.get(district, {}).get(good_id)
        if prev is None or price == prev:
            return "▬"
        return "▲" if price > prev else "▼"

    def _markets_state(self) -> Dict[str, Any]:
        """Build the Markets app live state from the engine Market.

        Reads ``get_market().get_prices(district)`` for the configured district
        (the same call/district the Grid uses, so prices MATCH across both
        surfaces), one row per good (cheapest shop wins, mirroring buy()). Adds a
        ▲/▼/▬ trend vs. the previous read, the player's positions (inventory
        holdings that are tradable here), live credits, and market stats.

        Returns:
            ``{district, goods:[...], inventory:[...], credits, stats}``. Every
            sub-lookup degrades gracefully — never raises (the route never 500s).
        """
        district = _markets_district()
        market = self._markets_get_market()
        goods: List[Dict[str, Any]] = []
        good_ids: set = set()
        if market is not None:
            try:
                prices = market.get_prices(district)
            except Exception as exc:
                logger.warning("[%s] price fetch failed (operation=markets, district=%s): %s",
                               SCENE_ID, district, exc)
                prices = []
            snapshot: Dict[str, int] = {}
            seen: set = set()
            for row in prices:
                try:
                    gid = row["good_id"]
                    if gid in seen:  # one row per good (cheapest shop wins on buy)
                        continue
                    seen.add(gid)
                    good_ids.add(gid)
                    price = int(row.get("shop_price", row.get("current_price", 0)))
                    snapshot[gid] = price
                    goods.append({
                        "good_id": gid,
                        "name": row.get("name", gid),
                        "category": str(row.get("category", "")),
                        "price": price,
                        "trend": self._markets_trend(district, gid, price),
                        "illegal": bool(row.get("illegal", False)),
                        "rarity": int(row.get("rarity", 1) or 1),
                        "supply": row.get("supply"),
                        "demand": row.get("demand"),
                        "shop_name": row.get("shop_name", ""),
                    })
                except Exception as exc:  # one bad row never sinks the table
                    logger.debug("[%s] skipped malformed market row (operation=markets): %s",
                                 SCENE_ID, exc)
                    continue
            _MARKETS_LAST_PRICES[district] = snapshot

        # Player positions — inventory holdings that are tradable in this market,
        # priced at the current market price for a live P/L feel.
        inventory: List[Dict[str, Any]] = []
        price_by_id = {g["good_id"]: g["price"] for g in goods}
        try:
            from engine.world.inventory import get_inventory  # noqa: PLC0415
            snap = get_inventory().to_dict()
            for it in snap.get("items", []):
                iid = it.get("item_id", "")
                if iid not in good_ids:
                    continue  # only show positions the player can trade here
                qty = int(it.get("quantity", 0) or 0)
                unit = int(price_by_id.get(iid, 0) or 0)
                inventory.append({
                    "good_id": iid,
                    "name": it.get("name", iid),
                    "quantity": qty,
                    "price": unit,
                    "value": unit * qty,
                    "category": it.get("category", ""),
                })
        except Exception as exc:
            logger.debug("[%s] inventory read failed (operation=markets): %s", SCENE_ID, exc)

        # Live credits from the one PlayerState wallet (same the Grid spends).
        credits = 0
        try:
            from engine.world.player_state import get_player_state  # noqa: PLC0415
            credits = int(get_player_state().credits)
        except Exception as exc:
            logger.debug("[%s] credits read failed (operation=markets): %s", SCENE_ID, exc)

        stats: Dict[str, Any] = {}
        if market is not None:
            try:
                stats = market.get_stats()
            except Exception as exc:
                logger.debug("[%s] stats read failed (operation=markets): %s", SCENE_ID, exc)

        return {
            "district": district,
            "goods": goods,
            "inventory": inventory,
            "credits": credits,
            "stats": stats,
        }

    def _markets_trade(self, action: str, body: Dict[str, Any]) -> Dict[str, Any]:
        """Execute a buy/sell through the engine Market and return result + state.

        Routes straight through ``get_market().buy/sell(...)`` with the Grid's
        player id, so credits, inventory and heat settle via the ONE economy. The
        engine result is merged with a fresh :meth:`_markets_state` snapshot so
        the UI can refresh in one round-trip. Defensive — never raises.

        Args:
            action: ``"buy"`` or ``"sell"``.
            body: Request JSON with ``good_id`` and optional ``quantity``.

        Returns:
            ``{success, ...engine result..., state}`` (``success=False`` with an
            ``error`` string on any failure — the route never 500s).
        """
        good_id = str(body.get("good_id", "")).strip()
        try:
            quantity = max(1, int(body.get("quantity", 1) or 1))
        except (TypeError, ValueError):
            quantity = 1
        if not good_id:
            return {"success": False, "error": "good_id required", "state": self._markets_state()}

        market = self._markets_get_market()
        if market is None:
            return {"success": False, "error": "Market offline.", "state": self._markets_state()}

        district = _markets_district()
        try:
            if action == "sell":
                res = market.sell(district, good_id, quantity=quantity,
                                  player_id=_MARKETS_PLAYER_ID)
            else:
                res = market.buy(district, good_id, quantity=quantity,
                                 player_id=_MARKETS_PLAYER_ID)
        except Exception as exc:
            logger.warning("[%s] %s failed (operation=markets, good=%s): %s",
                           SCENE_ID, action, good_id, exc)
            return {"success": False, "error": "Trade failed.", "state": self._markets_state()}

        ok = res.get("status") == "ok"
        if ok:
            logger.info("[%s] %s settled (operation=markets, good=%s, qty=%d, total=%s)",
                        SCENE_ID, action, good_id, quantity, res.get("total"))
        out: Dict[str, Any] = {
            "success": ok,
            "action": action,
            "good_id": good_id,
            "quantity": res.get("quantity", quantity),
            "good_name": res.get("good_name", good_id),
            "unit_price": res.get("unit_price", 0),
            "total": res.get("total", 0),
            "balance": res.get("balance"),
            "heat": res.get("heat"),
            "shop": res.get("shop", ""),
            "illegal": res.get("illegal", False),
        }
        if not ok:
            out["error"] = self._markets_reason(res)
        out["state"] = self._markets_state()
        return out

    @staticmethod
    def _markets_reason(res: Dict[str, Any]) -> str:
        """Map an engine Market error result onto a player-facing message."""
        reason = str(res.get("reason", "") or "")
        table = {
            "insufficient_credits": "Insufficient credits.",
            "not_in_inventory": "You don't hold enough to sell.",
        }
        if reason in table:
            return table[reason]
        return reason or "Trade rejected."

    # ── State ──────────────────────────────────────────────────────

    def _get_scene_state(self) -> Dict[str, Any]:
        """Return the desktop shell state for the template + tray.

        Pulls the live game clock from :class:`WorldState` when available and
        the system-tray readouts (heat / network / battery) from config so
        nothing is hardcoded. All lookups degrade gracefully — the shell must
        boot even when the world/config subsystems are offline.
        """
        state: Dict[str, Any] = {
            "scene": SCENE_ID,
            "display_name": self.SCENE_METADATA["display_name"],
            "status": "online",
            "accent_color": self.SCENE_METADATA["accent_color"],
            "version": self.SCENE_METADATA["version"],
        }
        state["clock"] = self._read_clock()
        state["tray"] = self._read_tray()
        return state

    def _read_clock(self) -> Dict[str, Any]:
        """Return the current in-game clock (falls back to a static label)."""
        try:
            from engine.world.world_state import get_world_state  # noqa: PLC0415
            wt = get_world_state().get_time()
            return {
                "game_hour": wt.game_hour,
                "game_day": wt.game_day,
                "game_day_name": wt.game_day_name,
                "time_of_day": wt.time_of_day,
                "display": wt.to_display(),
            }
        except Exception as exc:  # WorldState optional — never block boot
            logger.debug("[%s] clock unavailable (operation=state): %s", SCENE_ID, exc)
            return {
                "game_hour": 0,
                "game_day": 0,
                "game_day_name": "Mon",
                "time_of_day": "night",
                "display": "",
            }

    def _read_tray(self) -> Dict[str, Any]:
        """Return system-tray readouts.

        v1.62.0 [2026-06-15] — ES-T4: ``heat`` is now LIVE — read from the real
        :class:`PlayerState` so the tray reflects the player's in-world heat
        (reuses ``get_player_state().heat`` as the city HUD does). Battery /
        network / volume stay config-driven / cosmetic (no hardcoded values).
        All lookups degrade gracefully so the tray never blocks the shell.
        """
        try:
            from engine.config import get_config  # noqa: PLC0415
            cfg = get_config()
        except Exception:  # config optional — fall back to defaults below
            cfg = None

        def _cfg(key: str, default: Any) -> Any:
            if cfg is None:
                return default
            try:
                return cfg.get(key, default)
            except Exception:
                return default

        # LIVE heat from the real WorldState/PlayerState (fall back to config).
        heat = _cfg("executive_suite.tray.heat", 14)
        try:
            from engine.world.player_state import get_player_state  # noqa: PLC0415
            heat = int(get_player_state().heat)
        except Exception as exc:  # world optional — never block the tray
            logger.debug("[%s] live heat unavailable (operation=state): %s", SCENE_ID, exc)

        return {
            "heat": heat,
            "battery": _cfg("executive_suite.tray.battery", 87),
            "network": _cfg("executive_suite.tray.network", "nexus"),
            "volume": _cfg("executive_suite.tray.volume", 60),
        }

    # ──── FlaskScene Lifecycle Hooks ─────────────────────────────
    # v1.62.0 [2026-06-15] — FlaskScene handles start()/stop(); use hooks

    def on_before_serve(self) -> None:
        """Pre-serve setup (shell has no background services of its own)."""
        logger.info("[%s] OS shell online (operation=lifecycle)", SCENE_ID)

    def on_shutdown(self) -> None:
        """Cleanup on shutdown."""
        logger.info("[%s] Scene stopping (operation=lifecycle)", SCENE_ID)
