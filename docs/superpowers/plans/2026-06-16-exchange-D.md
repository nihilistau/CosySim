# The Exchange (v1.63 sub-project D) — Implementation Plan

> REQUIRED SUB-SKILL: superpowers:subagent-driven-development. The FINAL v1.63 piece. Reuse-first: there is NO new economy — surface the EXISTING `engine/world/market.py` `Market` (the one the emergent agency's `wealth` trades already move) in TWO places: **The Grid** (existing scene) + a new **Markets app** in the Executive Suite OS. One Market singleton, two UIs.

**Goal:** Live, NPC-driven economy visible + tradable in The Grid and in an Executive Suite Markets app — prices that move from real supply/demand (incl. agency NPC trades), a contracts board, and player buy/sell — all over `get_market()`.

**Architecture:** `Market` (`get_market()`) is the single source of truth: `get_goods(category)`, `get_prices(district, category)`, `buy(district, good_id, qty, player_id, shop_id)`, `sell(district, good_id, qty, player_id)`, `tick()`, `apply_event(...)`, `get_history(limit, player_id)`, `get_stats()`. Both surfaces read/write it; the running `LivingWorld` already ticks it. No new scene/port.

**Tech Stack:** Flask/Socket.IO (existing grid + executive_suite scenes), vanilla JS + design system. Live against the running core stack.

**Conventions:** reuse-first (no parallel market); `# v1.63.0 [2026-06-16]` stamps; Oracle log format; `get_config()`; proof-before-done (boot the scenes, headless, 0 console errors) against the live world.

---

### D-T1: The Grid surfaces the engine Market
**Files:** `content/scenes/grid/grid_scene.py` + its templates/static.
READ `grid_scene.py` first — it currently has its OWN `MARKET_CATALOGUE` + `_GridState.buy_item` (a static catalogue, separate from engine `Market`). Reconcile: make The Grid display the LIVE engine-`Market` prices (the economy NPC trades move) and route player buy/sell through `get_market().buy/sell`. Keep the Grid's existing UI/theme + the phone-upgrade items added in PH-T2 (those can remain as Grid-vendor specials layered on top, OR be represented in Market — pick the minimal coherent approach and document it). Add a **contracts/board** view if Market exposes one (else skip). Show price + recent change (▲/▼) per good. Live-update via the Market/world tick (Socket.IO or poll).
- [ ] Verify: Grid shows live engine-Market prices matching `get_market().get_prices(...)`; a player buy/sell goes through `get_market()` (credits/inventory settle); an NPC/agency trade (or a `Market.tick()`/`apply_event`) moves a price visible in the Grid. 0 console errors. Commit `feat(grid): surface live engine Market (Exchange) (v1.63.0)`.

### D-T2: Executive Suite "Markets" app
**Files:** new `content/scenes/executive_suite/static/js/apps/markets.js` + backend `/api/markets/*` routes in `executive_suite_scene.py` + add the `<script>` include in `executive_suite.html` (and a dock/app entry).
Reuse the ES app-registry (`ES.registerApp` — DEFER registration to DOMContentLoaded per the known ES ordering caveat, like the other apps). The app shows: a **live ticker** of goods (name, price, ▲/▼ change) from `get_market().get_goods()`/`get_prices()`, the player's **positions/inventory** + credits, a **contracts** list if available, and **broker buy/sell** wired to `/api/markets/buy|sell` → `get_market()`. Backend routes defensive (never 500). Neon OS aesthetic consistent with the other apps. Live-refresh (poll `/api/markets/state` or socket).
- [ ] Verify (boot executive_suite on its port alongside the stack): open Markets → live prices matching the Grid/`get_market()`; buy/sell works (credits/inventory change); prices move when the market ticks. 0 console errors. Screenshot. Commit `feat(executive_suite): Markets app over engine Market (v1.63.0)`.

### D-T3: Integration verify + changelog (v1.63 complete)
- [ ] Both surfaces over ONE Market: boot grid + executive_suite alongside the running world; confirm prices match between them and reflect `get_market()`; an agency NPC `wealth` trade (or `Market.tick()`) moves a price visible in BOTH; player buy/sell works in each surface and settles the same wallet/inventory.
- [ ] `pytest tests/test_market*.py tests/test_emergent_*.py -q` (+ any grid/exec-suite market tests you add) green; headless 0 console errors; `oracle.py --errors` clean.
- [ ] CHANGELOG `## [1.63.0]` — add "The Exchange" subsection (live engine-Market surfaced in The Grid + Executive Suite Markets app; NPC-driven prices). README Features row. Mark v1.63 sub-projects A–D all shipped.
- [ ] Commit `docs(exchange): v1.63.0 changelog — The Exchange (v1.63.0)`.

## Self-review
- Reuse-first: one `Market` singleton; both UIs surface it; no parallel economy (reconcile the Grid's static catalogue onto engine Market). ✓
- Closes v1.63: A (engine) → B (Sprawl) → C (War Room) → D (Exchange). ✓
- Verification proves the two surfaces stay in sync over the live, NPC-driven Market. ✓
