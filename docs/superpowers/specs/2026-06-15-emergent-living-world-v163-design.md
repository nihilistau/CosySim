# CosySim v1.63 — "Emergent Living World" — Design Spec

**Date:** 2026-06-15
**Status:** Awaiting review
**Builds on:** v1.62 "Living City" (GlobalCommsLog, `npc_comms` hybrid scheduler, `relationship_effects`, `phone_hack`, faction standings, Executive Suite OS) + existing `engine/world/` (`WorldSim`, `Crew`, `PlayerState`, `Inventory`).

## Premise
v1.62 made the city **talk to itself**. v1.63 makes it **act**: NPCs pursue their own goals, form and betray crews, factions win and lose territory, the economy moves on its own — and it all **persists**. The player walks this living world (The Sprawl), commands a faction within it (War Room), and trades in its economy (The Exchange).

## Decisions locked
- NPC decision-making: **hybrid** — a fast utility/rule planner for most actions; LLM used sparingly for flavor + pivotal beats (scales to a whole city, like v1.62's NPC comms).
- War Room: player **picks one faction** and rises within / runs it against the other five.
- The Sprawl: player has an **avatar** that walks the city and can be caught up in emergent events.
- Consequences are **fully persistent** (territory, deaths, crews, economy stick in the save).

## Conventions (apply throughout)
Module headers + Change Log + `# v1.63.0 [date]` stamps; Oracle log format; `get_config()` not hardcode; reuse existing code (extend `WorldSim`/`Crew`/factions, don't reinvent); pytest + mock at boundary; proof-before-done (`launcher.py`, `browser_test.py`/headless, `oracle.py`); hybrid generation + own-thread schedulers with config cadence to protect the local model (the v1.62 lesson).

---

## Decomposition (4 sub-projects; build A first)

### A · Emergent Simulation Engine  *(foundation — B/C/D all read & drive it)*
The brain. New `engine/world/emergent/` (or extend `WorldSim`): a persistent, tick-driven simulation.
- **Goals/agendas:** each NPC carries a small prioritized goal set derived from stats/neurochemistry/relationships/faction — e.g. `wealth`, `rank` (climb a faction), `romance(target)`, `revenge(target)`, `lay_low` (when heat high), `territory`. Goals have progress + satisfaction; completing/failing one reshuffles priorities.
- **Hybrid planner:** on a world tick, each "active" NPC selects an action via a **utility function** over its goals + context; the action vocabulary REUSES v1.62 systems so behavior is already wired: message / leave-message (`npc_comms`), hack (`phone_hack`), trade/take-contract (Exchange, D), form/join/leave/**betray** crew (`Crew`), move district, contest/raid territory, romance gesture (`relationship_effects`). LLM is invoked only for pivotal decisions + the occasional flavor line (gated by a `chance`, on its own thread/lock + TaskQueue limits).
- **Factions:** extend the existing faction-standing model into a `FactionState` per faction (6): `territory` (set of district ids), `power`, `treasury`, `goals`, `relations` (ally/war with other factions). NPC/crew/player actions shift territory & power; alliances and wars form from faction relations.
- **Crews & betrayal:** reuse/extend `engine/world` `Crew`: NPCs form crews around a shared goal, run **jobs** (heist/op/smuggle) whose success rolls off member skills + loyalty; low loyalty + a tempting payoff → **betrayal** (relationship-driven, surfaced as an event).
- **Consequence ripples:** every significant action emits a **world event** → applies persistent state deltas (territory flip, NPC death/exit, standing/relationship shifts, economic moves) + can schedule delayed consequences (reuse the v1.62 consequence pattern). Events stream to a shared **world-event feed** (reuse/extend `GlobalCommsLog` or a `world_events` table) that all scenes subscribe to.
- **Persistence:** a sim store (SQLite under `data/`, WAL, like `comms_log`) for faction/territory/goal/crew/economy state; a world tick (config cadence; real-time ambient + on player actions) advances it. Singleton `get_emergent_sim()`; defensive (failures log, never crash a scene).
- **Verify:** unit tests for goal selection, planner utility, faction/territory deltas, crew-job + betrayal resolution, consequence application, persistence round-trip. Live: run the sim headless for a window → territory/relationships/economy visibly evolve, model not hammered.

### B · The Sprawl  *(new scene — living city map)*
A new neon city-map scene (registered like `executive_suite`: SCENE_DEFS + port_registry + launcher + hub). A stylized district map with: NPC tokens moving between districts pursuing goals, **faction territory shaded** (and visibly shifting), a **live event ticker** (crews forming, deals, betrayals, raids, deaths), and the **player avatar** that travels district→district. Click a district/NPC/event to **intervene**: travel there, intercept comms, recruit, deal, hack, or fight. Reads the engine's state + event feed; player actions feed back into the engine. Themed neon-noir, faithful to the design system.
- **Verify:** boots + registered; map renders live NPC movement + territory; an emergent event appears and the player can act on it; 0 console errors.

### C · The Faction War Room  *(new scene — play as a faction)*
A new command scene. Player picks an allegiance (one of 6); a faction dashboard shows **territory map, power, treasury, crew roster, rivals/allies, and the rank ladder**. The player **commands**: assign crews goals/jobs/targets, contest a district, broker an alliance or declare war, spend treasury, and **rise in rank** as the faction gains. The other five factions are emergent rivals driven by the engine. Drives the sim from one faction's POV; outcomes persist.
- **Verify:** boots + registered; pick a faction; issue a crew a job + contest a district → engine resolves it and territory/power update; rival factions act back; 0 console errors.

### D · The Exchange  *(emergent economy — into TWO existing surfaces)*
The economy engine (part of A's sim, broken out for clarity): NPC-driven supply/demand, **contracts/jobs**, a fluctuating black-market, and broker deals — and crucially it ties money into NPC `wealth` goals (NPCs trade/work to get rich, which moves prices). Surfaced in **two** places over ONE economy model:
- **The Grid** (deepen the existing marketplace): prices move from real NPC supply/demand; live contracts board; broker deals with NPCs.
- **Executive Suite OS** — a new **Markets app**: live tickers, your positions/contracts, broker from the desktop alongside Mail/Breach/Oracle.
- **Verify:** one economy model, two UIs in sync; NPC trading visibly moves prices; a contract can be taken in either surface; tests for the price/contract model.

---

## Cross-cutting design notes
- **One brain, many lenses:** A is the only source of truth; B/C/D render and nudge it. No scene owns world state.
- **Performance:** hybrid planner + own-thread tick + config caps (active-NPC budget per tick, `llm_chance`) so the local model stays responsive — the explicit v1.62 lesson.
- **Player agency without dependence:** the world runs whether the player watches or not; the player is a powerful participant, not the motor.
- **Surfacing reuse:** event feed via the existing comms/event infrastructure; the Oracle (v1.62) naturally becomes a way to *hear* emergent plots; phone-hacking becomes a way to *act* on them — the systems compound.

## Risks
- **Model load** — mitigated by hybrid + caps (proven pattern).
- **Simulation runaway / dead-ends** — fully-persistent world could trend to a monopoly or wipe out NPCs; add gentle rebalancing pressure (faction recovery floors, NPC replacement via `genNPC`-style spawns) WITHOUT undoing player-meaningful consequences.
- **Balance/tuning** — utility weights + economy elasticity need config knobs + playtesting.
- **Scope** — this is another multi-sub-project engagement; A must land + be tuned before B/C/D feel alive.

## Verification (whole release)
Engine evolves the world headless (territory/economy/relationships shift, model calm); The Sprawl shows it live and lets the avatar intervene; the War Room lets the player run a faction and rivals respond; The Exchange moves prices from NPC trade in both Grid + OS Markets; suite stays green; CHANGELOG `## [1.63.0]` + README Features row.
