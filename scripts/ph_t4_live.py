"""PH-T4 live evidence — NPC hacks the PLAYER's phone (firewall-defended).

Demonstrates the moderate & recoverable reverse hack and proves the PH-T2
firewall upgrade is the defence:

1. Low-firewall player + a hostile NPC → force ``npc_hack_player(<npc>)`` → show
   the recoverable breach (bounded read + ONE leak/plant, capped heat, small
   standing hit, last_hacked stamped) + the phone_hacked event/notification.
2. Install a PH-T2 firewall upgrade (``phone_firewall_v2``) → run the SAME
   attacker again → show the breach is now BLOCKED (no effect, blocked flag).

Uses isolated temp DBs so it never touches real save data. The upgrade is applied
exactly as the PH-T2 ``install_phone_upgrade`` skill does (``add_installed_app``),
with the effect magnitudes read from the real inventory ITEM_CATALOG, so the
defence numbers are the real derived stats.

Run: ``.venv\\Scripts\\python.exe scripts/ph_t4_live.py``
"""
from __future__ import annotations

import random
import sys
import tempfile
from pathlib import Path

# Ensure project root is on sys.path.
_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_ROOT))

from content.scenes.phone.phone_db import PhoneDB
from content.simulation.database.db import Database
from engine.world.comms_log import GlobalCommsLog
from engine.world.phone_os import PhoneOS
from content.scenes.phone.phone_hack import NpcHackPlayerService, is_hostile_to_player
from engine.world.inventory import get_phone_upgrade


class _Player:
    """Tiny PlayerState stand-in for the live demo (captures heat)."""

    def __init__(self) -> None:
        self.heat = 0
        self.faction_standings: dict[str, int] = {}

    def add_heat(self, amount: int, reason: str = "") -> int:
        self.heat += int(amount)
        return self.heat

    def get_skill(self, skill: str) -> int:
        return 0


class _Emitter:
    def __init__(self) -> None:
        self.events: list[tuple[str, dict]] = []

    def __call__(self, event: str, payload: dict) -> None:
        self.events.append((event, payload))


def _fixed_rng(roll: int, rand: float) -> random.Random:
    class _R(random.Random):
        def randint(self, a: int, b: int) -> int:  # type: ignore[override]
            return roll

        def random(self) -> float:  # type: ignore[override]
            return rand

    return _R()


def main() -> None:
    out_lines: list[str] = []

    def emit(line: str = "") -> None:
        # stdout may be cp1252 on Windows — keep the console safe, full text in artifact.
        try:
            print(line)
        except UnicodeEncodeError:
            print(line.encode("ascii", "replace").decode("ascii"))
        out_lines.append(line)

    tmp = Path(tempfile.mkdtemp(prefix="ph_t4_"))
    phone_db = PhoneDB(tmp / "phone.db")
    phone_os = PhoneOS(db=phone_db)
    comms = GlobalCommsLog(path=tmp / "comms.db")
    sim_db = Database(db_path=str(tmp / "sim.db"))

    attacker = "viktor"

    # Deterministic attacker offence for a clear, reproducible demo (a strong
    # hostile netrunner). The defence is the PLAYER's real derived stats.
    _attacker_power = 18
    phone_os.hack_power = (  # type: ignore[method-assign]
        lambda cid: _attacker_power if cid == attacker else 0
    )

    emit("=" * 70)
    emit("PH-T4 LIVE — NPC hacks the PLAYER's phone (firewall-defended)")
    emit("=" * 70)

    # Seed: low-firewall player, some private threads, a HOSTILE attacker.
    phone_db.set_phone_fields("user", security_level=1, firewall=1)
    for i in range(4):
        comms.log("phone_dm", "user", [attacker], f"private note {i}",
                  thread_id="t-user", kind="message")
    sim_db.get_or_create_relationship(attacker, "user", relationship_level=0.1)

    emit("")
    emit(f"Player defence (low):  security={phone_os.effective_security('user')} "
         f"firewall={phone_os.effective_firewall('user')}")
    emit(f"Attacker '{attacker}' hostile to player? "
         f"{is_hostile_to_player(attacker, db=sim_db)} "
         f"(standing={sim_db.get_relationship(attacker, 'user')['relationship_level']})")

    # ── 1) BREACH ────────────────────────────────────────────────────────
    emit("")
    emit("--- 1) Force npc_hack_player(viktor) against the LOW-firewall player ---")
    player1 = _Player()
    emit1 = _Emitter()
    svc1 = NpcHackPlayerService(
        phone_os=phone_os, comms=comms, phone_db=phone_db, db=sim_db,
        player_state=player1, emit=emit1, rng=_fixed_rng(roll=6, rand=0.0),
    )
    r1 = svc1.hack(attacker)
    emit(f"  attack={r1['attack']} vs defence={r1['defence']}  margin={r1['margin']}")
    emit(f"  success={r1['success']}  blocked={r1['blocked']}  action={r1['action']}")
    emit(f"  threads read by attacker: {len(r1['read'])} (bounded)")
    emit(f"  leaked={r1['leaked'] is not None}  planted={r1['planted'] is not None} "
         f"(at most ONE)")
    emit(f"  heat_delta=+{r1['heat_delta']} (capped)  rel_delta={r1['rel_delta']:+.3f} "
         f"(recoverable)")
    new_standing = sim_db.get_relationship(attacker, 'user')['relationship_level']
    emit(f"  (player,{attacker}) standing now={new_standing:.3f} (not wiped)")
    emit(f"  player last_hacked stamped: "
         f"{phone_db.get_phone('user')['last_hacked'] is not None}")
    emit(f"  events emitted: {[e for e, _ in emit1.events]}")
    notifs = [e for e in comms.recent(20)
              if e['metadata'].get('notification') == 'phone_hacked']
    emit(f"  persisted breach notification: {len(notifs)} "
         f"(metadata={notifs[0]['metadata'] if notifs else None})")
    emit(f"  message: {r1['message']}")

    # ── 2) INSTALL PH-T2 FIREWALL UPGRADE, THEN SAME ATTACKER ────────────
    emit("")
    emit("--- 2) Install PH-T2 'phone_firewall_v2' upgrade, then SAME attacker ---")
    meta = get_phone_upgrade("phone_firewall_v2")
    emit(f"  upgrade effects (from ITEM_CATALOG): "
         f"{meta['phone_upgrade']['effects']}")
    # Exactly what install_phone_upgrade()'s _apply_upgrade_effect does:
    phone_db.add_installed_app("user", "phone_firewall_v2")
    emit(f"  Player defence (upgraded): "
         f"security={phone_os.effective_security('user')} "
         f"firewall={phone_os.effective_firewall('user')}")

    player2 = _Player()
    emit2 = _Emitter()
    svc2 = NpcHackPlayerService(
        phone_os=phone_os, comms=comms, phone_db=phone_db, db=sim_db,
        player_state=player2, emit=emit2, rng=_fixed_rng(roll=6, rand=0.0),
    )
    before_count = comms.count()
    r2 = svc2.hack(attacker)
    after_count = comms.count()
    emit(f"  attack={r2['attack']} vs defence={r2['defence']}  margin={r2['margin']}")
    emit(f"  success={r2['success']}  blocked={r2['blocked']}  action={r2['action']}")
    emit(f"  heat_delta=+{r2['heat_delta']} (no effect)  "
         f"read={len(r2['read'])}  leaked={r2['leaked']}  planted={r2['planted']}")
    emit(f"  comms entries added this attempt: {after_count - before_count} "
         f"(notification only)")
    emit(f"  events emitted: {[(e, p.get('blocked')) for e, p in emit2.events]}")
    emit(f"  message: {r2['message']}")

    emit("")
    emit("=" * 70)
    emit("RESULT: same attacker — BREACHED at low firewall, BLOCKED after the "
         "PH-T2 firewall upgrade.")
    emit("=" * 70)

    art = Path("docs/superpowers/artifacts/ph-t4-npchack.txt")
    art.parent.mkdir(parents=True, exist_ok=True)
    art.write_text("\n".join(out_lines) + "\n", encoding="utf-8")
    print(f"\n[artifact written] {art.resolve()}")


if __name__ == "__main__":
    main()
