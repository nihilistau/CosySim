"""NPCCommsScheduler — autonomous NPC↔NPC phone messaging (CB-T3).

This module gives non-player characters their own phones and lets them text
*each other* on a background cadence, independent of the player. It is the
headline feature of the "living comms" sub-project: the city's social graph
keeps buzzing whether or not the player is looking.

Design
------
* **Own thread, own lock.** The scheduler runs on its OWN daemon thread with
  its OWN :class:`threading.Lock` and a :class:`threading.Event` for sleeping.
  It deliberately does NOT touch the phone scene's ``_tick_lock`` (an RLock
  shared by the autotext ticker and the player-reply worker). Decoupling here
  is the "_tick_lock fix" for NPC traffic: NPC↔NPC volume can grow without
  ever contending with player-facing messaging.
* **Hybrid generation.** Most exchanges are cheap TEMPLATE lines drawn from a
  tone-varied in-world pool — no LLM, no GPU. Only "important" exchanges (a
  close pair, the player being the topic, or a recent event involving them)
  request a LIVE LLM turn via the NPC's :class:`VirtualAgentManager`
  ``infer_processed`` path, and even those are gated by ``comms.npc.llm_chance``
  so the local model is never hammered. If the LLM path fails (e.g. LMStudio
  is down) it degrades to a template line.
* **Single source of truth.** Every exchange is written through
  :func:`engine.world.comms_log.get_comms_log` on channel ``npc_dm`` with the
  pair's stable thread id, AND persisted into a real ``npc_dm`` phone thread so
  it is a readable conversation. A Socket.IO event is emitted best-effort.
* **Selection signals.** Pairs are weighted by co-presence (same location in
  the city map), recent interaction (from the comms log), and a pair-affinity
  signal (``character_relationships.relationship_level``, defaulting when the
  pair has no formal relationship yet — CB-T6 will populate these). Recently
  used pairs are penalised to avoid spamming the same two NPCs.

Configuration (read via ``get_config().get("comms.npc.<key>")``)::

    comms.npc.enabled            bool   master toggle
    comms.npc.tick_interval      float  seconds between ticks
    comms.npc.max_pairs_per_tick int    pairs processed per tick
    comms.npc.llm_chance         float  P(important exchange uses the LLM)
    comms.npc.recent_pair_window int    pairs to remember as "recent"

Version: v1.62.0 [2026-06-15]
Author:  CosySim Team

Change Log:
    v1.62.0 [2026-06-15] — Initial NPC↔NPC hybrid messaging scheduler (CB-T3):
        NPC-owned phones, weighted pair selection, template/LLM hybrid routing,
        write-through to GlobalCommsLog + npc_dm phone threads, own-thread/own-
        lock lifecycle decoupled from the phone _tick_lock.
"""
from __future__ import annotations

import logging
import random
import threading
from typing import Any, Dict, List, Optional, Sequence, Tuple

logger = logging.getLogger(__name__)

# ══════════════════════════════════════════════════════════════════════
#  DEFAULTS
# ══════════════════════════════════════════════════════════════════════

_DEFAULT_TICK_INTERVAL = 30.0
_DEFAULT_MAX_PAIRS = 2
_DEFAULT_LLM_CHANCE = 0.25
_DEFAULT_RECENT_WINDOW = 6
_DEFAULT_NPCS = ["lola", "viktor", "aria", "frankie", "mira"]
_DEFAULT_PAIR_AFFINITY = 0.5   # used when no formal relationship exists yet

# Tone-varied, in-world NPC-to-NPC snippets. Selection picks a bucket from the
# pair's affinity so close pairs sound warm and distant pairs sound curt.
# These are intentionally generic (no player references) so they read as
# plausible ambient chatter for any cast member.
TEMPLATE_POOL: Dict[str, List[str]] = {
    "warm": [
        "hey you, thinking about you 💕",
        "we still on for later? wouldn't miss it",
        "you always know how to make my night better 😏",
        "miss your face. drinks soon?",
        "ugh today was long. wish you were here",
        "you free? could use your company",
    ],
    "neutral": [
        "you around tonight?",
        "heard anything new lately?",
        "city's quiet for once. weird.",
        "saw you earlier, didn't get a chance to say hi",
        "let me know if plans change",
        "you good? haven't heard from you",
    ],
    "cool": [
        "we need to talk. not here.",
        "keep my name out of it.",
        "don't make this complicated.",
        "i'll deal with it. stay out of the way.",
        "noted. that's all.",
        "you owe me. don't forget.",
    ],
}


# ══════════════════════════════════════════════════════════════════════
#  SCHEDULER
# ══════════════════════════════════════════════════════════════════════


class NPCCommsScheduler:
    """Drives autonomous NPC↔NPC phone messaging on its own background thread.

    The scheduler owns a daemon thread and an internal lock; it never reuses the
    phone scene's ``_tick_lock``. Each tick selects a few NPC pairs (weighted by
    co-presence, recent interaction, and pair affinity), generates an exchange
    via the template/LLM hybrid router, and writes it to the comms log and the
    pair's ``npc_dm`` phone thread.

    Attributes:
        phone_db: The :class:`PhoneDB` used to persist npc_dm threads.
    """

    def __init__(
        self,
        *,
        phone_db: Any = None,
        db: Any = None,
        comms_log: Any = None,
        emit: Optional[Any] = None,
    ) -> None:
        """Initialise the scheduler from config, wiring optional collaborators.

        Args:
            phone_db: A ``PhoneDB`` for npc_dm thread persistence. Constructed
                lazily on first use when ``None``.
            db: The main ``Database`` for character + relationship lookups.
                Constructed lazily when ``None``.
            comms_log: An explicit ``GlobalCommsLog`` (tests pass an isolated
                one). Falls back to ``get_comms_log()`` when ``None``.
            emit: Optional ``callable(event, payload)`` used to push Socket.IO
                events. Best-effort; failures are swallowed.
        """
        from engine.config import get_config
        cfg = get_config()
        self._enabled: bool = bool(cfg.get("comms.npc.enabled", True))
        self._tick_interval: float = float(
            cfg.get("comms.npc.tick_interval", _DEFAULT_TICK_INTERVAL)
        )
        self._max_pairs: int = int(
            cfg.get("comms.npc.max_pairs_per_tick", _DEFAULT_MAX_PAIRS)
        )
        self._llm_chance: float = float(
            cfg.get("comms.npc.llm_chance", _DEFAULT_LLM_CHANCE)
        )
        self._recent_window: int = int(
            cfg.get("comms.npc.recent_pair_window", _DEFAULT_RECENT_WINDOW)
        )
        self._roster: List[str] = list(
            cfg.get("comms.npc.roster", _DEFAULT_NPCS)
        )

        self._phone_db = phone_db
        self._db = db
        self._comms_log = comms_log
        self._emit = emit

        # Own thread + own lock — NOT the phone _tick_lock.
        self._lock = threading.Lock()
        self._stop_event = threading.Event()
        self._thread: Optional[threading.Thread] = None
        self._running = False

        # Rolling memory of recently messaged pairs (penalise to avoid spam).
        self._recent_pairs: List[Tuple[str, str]] = []
        self._template_count = 0
        self._llm_count = 0

    # ── lazy collaborators ─────────────────────────────────────────────

    def _get_comms_log(self):
        """Return the comms log, preferring an injected instance."""
        if self._comms_log is not None:
            return self._comms_log
        from engine.world.comms_log import get_comms_log
        return get_comms_log()

    def _get_phone_db(self):
        """Return the phone DB, constructing one lazily if needed."""
        if self._phone_db is None:
            from content.scenes.phone.phone_db import PhoneDB
            self._phone_db = PhoneDB()
        return self._phone_db

    def _get_db(self):
        """Return the main DB, constructing one lazily if needed."""
        if self._db is None:
            try:
                from content.simulation.database.db import Database
                self._db = Database()
            except Exception as exc:  # DB optional in minimal builds/tests
                logger.debug("[npc_comms] Database unavailable (operation=get_db): %s", exc)
                self._db = None
        return self._db

    # ── lifecycle ──────────────────────────────────────────────────────

    def start(self) -> bool:
        """Start the background tick loop if enabled and a cast is available.

        Returns:
            ``True`` if the loop was started, ``False`` if it was skipped
            (disabled, already running, or fewer than two known NPCs).
        """
        if not self._enabled:
            logger.info("[npc_comms] disabled by config (operation=start)")
            return False
        if self._running:
            logger.warning("[npc_comms] already running (operation=start)")
            return False
        if len(self._known_npcs()) < 2:
            logger.info("[npc_comms] fewer than 2 known NPCs; not starting (operation=start)")
            return False
        self._stop_event.clear()
        self._running = True
        self._thread = threading.Thread(
            target=self._run_loop, daemon=True, name="npc-comms-scheduler"
        )
        self._thread.start()
        logger.info(
            "[npc_comms] started (operation=start, interval=%.0fs, max_pairs=%d, llm_chance=%.2f)",
            self._tick_interval, self._max_pairs, self._llm_chance,
        )
        return True

    def stop(self) -> None:
        """Signal the loop to stop and join the thread cleanly."""
        if not self._running:
            return
        self._running = False
        self._stop_event.set()
        if self._thread is not None:
            self._thread.join(timeout=5.0)
            self._thread = None
        logger.info(
            "[npc_comms] stopped (operation=stop, templates=%d, llm=%d)",
            self._template_count, self._llm_count,
        )

    def _run_loop(self) -> None:
        """Thread target: tick, then wait on the stop event (no busy-wait)."""
        while not self._stop_event.is_set():
            try:
                self.tick()
            except Exception as exc:
                logger.error("[npc_comms] tick error (operation=run_loop): %s", exc)
            # Event-based sleep so stop() interrupts immediately.
            self._stop_event.wait(self._tick_interval)

    # ── tick ────────────────────────────────────────────────────────────

    def tick(self) -> int:
        """Run one scheduling cycle: select pairs and generate exchanges.

        Returns:
            The number of exchanges written this tick.
        """
        npcs = self._known_npcs()
        if len(npcs) < 2:
            return 0
        pairs = self.select_pairs(npcs, self._max_pairs)
        written = 0
        for a, b in pairs:
            try:
                self.run_exchange(a, b)
                written += 1
            except Exception as exc:
                logger.error(
                    "[npc_comms] exchange failed (operation=tick, pair=%s/%s): %s",
                    a, b, exc,
                )
        return written

    # ── roster ──────────────────────────────────────────────────────────

    def _known_npcs(self) -> List[str]:
        """Return the list of known NPC ids, preferring the live character DB.

        Falls back to the configured roster when the DB is unavailable or
        empty so the scheduler still works in minimal/test environments.

        Returns:
            A de-duplicated list of NPC character ids.
        """
        db = self._get_db()
        ids: List[str] = []
        if db is not None:
            try:
                for row in db.get_all_characters():
                    cid = str(row.get("id") or row.get("character_id") or "")
                    if cid:
                        ids.append(cid)
            except Exception as exc:
                logger.debug("[npc_comms] character enumeration failed: %s", exc)
        if not ids:
            ids = list(self._roster)
        # de-dup, preserve order
        seen: set = set()
        out: List[str] = []
        for cid in ids:
            if cid not in seen:
                seen.add(cid)
                out.append(cid)
        return out

    # ── pair selection ──────────────────────────────────────────────────

    def select_pairs(
        self, npcs: Sequence[str], count: int
    ) -> List[Tuple[str, str]]:
        """Select up to ``count`` distinct NPC pairs weighted by relevance.

        Each candidate pair is scored by:

        * co-presence — both NPCs in the same city-map location,
        * recent interaction — recent ``npc_dm`` comms-log entries between them,
        * pair affinity — ``relationship_level`` (default when none),

        and penalised if the pair was used recently. Selection is randomised in
        proportion to score so the same high-scoring pair does not monopolise
        every tick.

        Args:
            npcs: The pool of NPC ids to draw from.
            count: Maximum number of distinct pairs to return.

        Returns:
            A list of ordered ``(sender, recipient)`` tuples; distinct pairs,
            no immediate repeats while alternatives exist.
        """
        candidates: List[Tuple[Tuple[str, str], float]] = []
        for i in range(len(npcs)):
            for j in range(i + 1, len(npcs)):
                a, b = npcs[i], npcs[j]
                candidates.append(((a, b), self._score_pair(a, b)))
        if not candidates:
            return []

        chosen: List[Tuple[str, str]] = []
        pool = list(candidates)
        for _ in range(min(count, len(pool))):
            total = sum(w for _, w in pool)
            if total <= 0:
                pick_idx = random.randrange(len(pool))
            else:
                r = random.uniform(0, total)
                acc = 0.0
                pick_idx = len(pool) - 1
                for idx, (_, w) in enumerate(pool):
                    acc += w
                    if acc >= r:
                        pick_idx = idx
                        break
            (a, b), _ = pool.pop(pick_idx)
            # Randomise who speaks first so threads feel two-sided.
            if random.random() < 0.5:
                a, b = b, a
            chosen.append((a, b))
        return chosen

    def _score_pair(self, a: str, b: str) -> float:
        """Compute a positive selection weight for an NPC pair.

        Args:
            a: First NPC id.
            b: Second NPC id.

        Returns:
            A strictly positive weight (higher = more likely to be picked).
        """
        score = 0.1  # floor so every pair has a chance
        score += self._affinity(a, b)
        if self._co_present(a, b):
            score += 0.5
        score += min(self._recent_interaction(a, b), 0.5)
        if self._is_recent_pair(a, b):
            score *= 0.2  # heavy penalty to avoid spamming the same pair
        return max(score, 0.01)

    def _affinity(self, a: str, b: str) -> float:
        """Return the pair-affinity signal in ``[0, 1]``.

        Uses ``character_relationships.relationship_level`` when present; falls
        back to :data:`_DEFAULT_PAIR_AFFINITY` (NPC↔NPC relationships are not
        formally seeded yet — CB-T6 will populate them).

        Args:
            a: First NPC id.
            b: Second NPC id.

        Returns:
            Affinity in ``[0, 1]``.
        """
        db = self._get_db()
        if db is not None:
            try:
                rel = db.get_relationship(a, b)
                if rel and rel.get("relationship_level") is not None:
                    return float(rel["relationship_level"])
            except Exception as exc:
                logger.debug("[npc_comms] affinity lookup failed: %s", exc)
        return _DEFAULT_PAIR_AFFINITY

    def _co_present(self, a: str, b: str) -> bool:
        """Return whether both NPCs are at the same city-map location.

        Args:
            a: First NPC id.
            b: Second NPC id.

        Returns:
            ``True`` when both locations are known and equal.
        """
        try:
            from engine.world.city_map import get_city_map
            cm = get_city_map()
            la = cm.get_npc_location(a)
            lb = cm.get_npc_location(b)
            return bool(la and lb and la == lb)
        except Exception:
            return False

    def _recent_interaction(self, a: str, b: str) -> float:
        """Return a small recency bonus from prior npc_dm log entries.

        Args:
            a: First NPC id.
            b: Second NPC id.

        Returns:
            ``0.0``–``0.5`` proportional to recent exchanges between the pair.
        """
        try:
            cl = self._get_comms_log()
            entries = cl.query(
                channel="npc_dm", participants=[a, b], limit=10
            )
            hits = 0
            for e in entries:
                sender = e.get("sender_id")
                recips = e.get("recipient_ids") or []
                if (sender == a and b in recips) or (sender == b and a in recips):
                    hits += 1
            return min(hits * 0.1, 0.5)
        except Exception:
            return 0.0

    def _is_recent_pair(self, a: str, b: str) -> bool:
        """Return whether this unordered pair was messaged recently."""
        key = tuple(sorted((a, b)))
        return key in [tuple(sorted(p)) for p in self._recent_pairs]

    def _remember_pair(self, a: str, b: str) -> None:
        """Record a pair as recently used, bounded by the recent window."""
        with self._lock:
            self._recent_pairs.append((a, b))
            if len(self._recent_pairs) > self._recent_window:
                self._recent_pairs = self._recent_pairs[-self._recent_window:]

    # ── hybrid generation ───────────────────────────────────────────────

    def _is_important(self, a: str, b: str) -> bool:
        """Decide whether a pair's exchange warrants a live LLM turn.

        An exchange is "important" when the pair is close (high affinity), the
        player is a recent topic in their thread, or a recent event involves
        them. Importance only makes the LLM path *eligible*; the actual LLM call
        is still gated by ``comms.npc.llm_chance``.

        Args:
            a: Sender NPC id.
            b: Recipient NPC id.

        Returns:
            ``True`` if the exchange is important.
        """
        if self._affinity(a, b) >= 0.7:
            return True
        try:
            cl = self._get_comms_log()
            entries = cl.query(channel="npc_dm", participants=[a, b], limit=5)
            for e in entries:
                content = (e.get("content") or "").lower()
                meta = e.get("metadata") or {}
                if "player" in content or "user" in content:
                    return True
                if meta.get("event"):
                    return True
        except Exception:
            pass
        return False

    def _affinity_tone(self, a: str, b: str) -> str:
        """Map a pair's affinity to a template tone bucket.

        Args:
            a: First NPC id.
            b: Second NPC id.

        Returns:
            One of ``'warm'``, ``'neutral'``, ``'cool'``.
        """
        aff = self._affinity(a, b)
        if aff >= 0.66:
            return "warm"
        if aff <= 0.33:
            return "cool"
        return "neutral"

    def _template_line(self, a: str, b: str) -> str:
        """Return a tone-appropriate template line for a pair (no LLM).

        Args:
            a: Sender NPC id.
            b: Recipient NPC id.

        Returns:
            A template snippet drawn from :data:`TEMPLATE_POOL`.
        """
        tone = self._affinity_tone(a, b)
        return random.choice(TEMPLATE_POOL.get(tone, TEMPLATE_POOL["neutral"]))

    def _llm_line(self, a: str, b: str) -> Optional[str]:
        """Generate a live LLM line from ``a`` to ``b`` via the agent path.

        Uses :meth:`VirtualAgentManager.infer_processed` (the same path the
        phone and executive-suite assistants use), NOT the MCP ``reply()``
        route. Returns ``None`` on any failure so the caller can fall back to a
        template (e.g. when LMStudio is down).

        Args:
            a: Sender NPC id.
            b: Recipient NPC id.

        Returns:
            The generated line, or ``None`` on failure / empty output.
        """
        try:
            from engine.agents.virtual_agent_manager import get_virtual_agent_manager
            from engine.agents.virtual_agent import InferenceRequest
            from engine.agents.stream_processor import strip_token_artifacts

            db = self._get_db()
            sender = db.get_character(a) if db is not None else None
            recip = db.get_character(b) if db is not None else None
            sender_name = (sender or {}).get("name", a)
            recip_name = (recip or {}).get("name", b)
            persona = (sender or {}).get("personality", "")

            system = (
                f"You are {sender_name}. {persona}\n"
                f"You are texting {recip_name} privately, NPC-to-NPC, on your phone. "
                "The player is not in this chat. Write ONE short, natural text "
                "message that advances your relationship or shares something on "
                "your mind. Keep it under 25 words. No quotation marks, no "
                "narration — just the message body."
            )
            msgs = [
                {"role": "system", "content": system},
                {"role": "user", "content": f"Text {recip_name} now."},
            ]
            mgr = get_virtual_agent_manager()
            req = InferenceRequest(
                agent_id=a,
                messages=msgs,
                temperature=0.9,
                max_output_tokens=120,
                store=False,
                metadata={"scene": "npc_comms", "character_name": sender_name},
            )
            response = mgr.infer_processed(req)
            text = (getattr(response, "clean_text", "") or "").strip()
            text = strip_token_artifacts(text)
            return text or None
        except Exception as exc:
            logger.debug("[npc_comms] LLM line failed (operation=llm_line): %s", exc)
            return None

    # ── exchange ────────────────────────────────────────────────────────

    def run_exchange(self, a: str, b: str) -> Dict[str, Any]:
        """Generate and persist one NPC→NPC exchange from ``a`` to ``b``.

        Routing:
            * ambient (default) → a TEMPLATE line, no LLM call;
            * important AND a ``llm_chance`` roll succeeds → a LIVE LLM line,
              falling back to a template if generation fails.

        The result is written to the comms log (channel ``npc_dm``) and the
        pair's ``npc_dm`` phone thread, and a Socket.IO event is emitted
        best-effort.

        Args:
            a: Sender NPC id.
            b: Recipient NPC id.

        Returns:
            A dict describing the exchange: ``sender``, ``recipient``,
            ``thread_id``, ``generated`` (``'template'``/``'llm'``),
            ``content``, ``comms_id``.
        """
        important = self._is_important(a, b)
        use_llm = important and random.random() < self._llm_chance

        generated = "template"
        content: Optional[str] = None
        if use_llm:
            content = self._llm_line(a, b)
            if content:
                generated = "llm"
        if not content:
            content = self._template_line(a, b)
            generated = "template"

        if generated == "llm":
            self._llm_count += 1
        else:
            self._template_count += 1

        thread_id = self._get_phone_db().npc_pair_thread_id(a, b)

        # Persist into a real, readable npc_dm phone thread.
        try:
            pdb = self._get_phone_db()
            pdb.mark_npc_phone(a)
            pdb.mark_npc_phone(b)
            pdb.get_or_create_npc_dm(a, b)
            pdb.save_message(
                thread_id=thread_id,
                sender_id=a,
                content=content,
                metadata={"generated": generated, "channel": "npc_dm"},
            )
        except Exception as exc:
            logger.error(
                "[npc_comms] phone persist failed (operation=run_exchange, pair=%s/%s): %s",
                a, b, exc,
            )

        # Single source of truth: the global comms log.
        comms_id = self._get_comms_log().log(
            "npc_dm",
            a,
            [b],
            content,
            thread_id=thread_id,
            kind="message",
            metadata={"generated": generated, "important": important},
        )

        self._remember_pair(a, b)
        self._emit_event(a, b, thread_id, content, generated)

        logger.info(
            "[npc_comms] exchange (operation=run_exchange, sender=%s, recipient=%s, generated=%s, thread=%s)",
            a, b, generated, thread_id,
        )
        return {
            "sender": a,
            "recipient": b,
            "thread_id": thread_id,
            "generated": generated,
            "content": content,
            "comms_id": comms_id,
        }

    def _emit_event(
        self, a: str, b: str, thread_id: str, content: str, generated: str
    ) -> None:
        """Emit a best-effort Socket.IO event for a fresh NPC↔NPC message."""
        payload = {
            "thread_id": thread_id,
            "sender_id": a,
            "recipient_id": b,
            "content": content,
            "generated": generated,
        }
        if self._emit is not None:
            try:
                self._emit("npc_dm_message", payload)
                return
            except Exception as exc:
                logger.debug("[npc_comms] injected emit failed: %s", exc)
        try:
            from engine.mcp import get_framework
            get_framework().emit("npc_dm_message", payload)
        except Exception as exc:
            logger.debug("[npc_comms] framework emit unavailable: %s", exc)

    # ── status ──────────────────────────────────────────────────────────

    def get_status(self) -> Dict[str, Any]:
        """Return a monitoring snapshot of the scheduler.

        Returns:
            Dict with ``running``, ``enabled``, ``tick_interval``,
            ``templates``, ``llm`` counts.
        """
        return {
            "running": self._running,
            "enabled": self._enabled,
            "tick_interval": self._tick_interval,
            "templates": self._template_count,
            "llm": self._llm_count,
        }


# ══════════════════════════════════════════════════════════════════════
#  SINGLETON
# ══════════════════════════════════════════════════════════════════════

_scheduler: Optional[NPCCommsScheduler] = None
_singleton_lock = threading.Lock()


def get_npc_comms_scheduler() -> NPCCommsScheduler:
    """Return the process-wide :class:`NPCCommsScheduler` singleton.

    Tests that need isolation should construct ``NPCCommsScheduler(...)``
    directly with explicit collaborators instead.

    Returns:
        The shared :class:`NPCCommsScheduler` instance.
    """
    global _scheduler
    if _scheduler is None:
        with _singleton_lock:
            if _scheduler is None:
                _scheduler = NPCCommsScheduler()
    return _scheduler
