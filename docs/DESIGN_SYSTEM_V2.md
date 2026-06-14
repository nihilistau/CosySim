# Design System v2 — "Dark Renaissance"

Version: v1.58.0 [2026-06-11]
Source material: `artifacts/new-assets/` (12 `ui_kits_v2` kits, `colors_and_type.css`, `_ds_manifest.json`, 5 component kits, `landing.html`)

## What shipped in Phase 2 (foundation)

| File | Role |
|------|------|
| `content/shared/static/css/design_tokens_v2.css` | Delta layer over `design_tokens.css` — Orbitron display voice, Inter body voice, Share Tech Mono terminal voice, `--cs-scene-accent-rgb` defaults, `[data-scene]` accent blocks for all 24 scene keys |
| `content/shared/static/css/fonts.css` + `content/shared/static/fonts/*.woff2` | Locally vendored latin woff2 for Orbitron / Inter / JetBrains Mono / Share Tech Mono / Press Start 2P (replaces the Google Fonts `<link>`; offline-safe) |
| `content/shared/static/css/cosysim-components.css` | + `.cs-chat-bubble` (npc / `--player` / `--system`) and `.cs-chat-log` shared dialogue components |
| `content/shared/templates/neon_base.html` | Loads `fonts.css` and `design_tokens_v2.css` (immediately after `design_tokens.css` — cascade order matters) |

Existing utilities to REUSE (do not re-implement): `stagger-in`, `pulse-glow`,
`scan-sweep`, `border-trace` (cosysim-animations.css), `glass-subtle/medium/deep`,
`.cs-btn-scene`, `.cs-stat-bar` family, `.cs-glass-panel` (cosysim-components.css).

## Kit → scene mapping

| ui_kits_v2 kit | Production scene | Accent |
|---|---|---|
| penthouse | penthouse (5556) | `#fb7185` rose |
| oracle | oracle (5572) | `#a855f7` violet |
| heist | heist (5565) | `#f59e0b` (kit shows `#e11d48` — template wins) |
| grid | grid (5569) | `#22d3ee` |
| neoncity | neoncity (5563) | `#06b6d4` cyan |
| signal | phone (5555) | `#10b981` emerald |
| hub | hub (8500) | `#3b82f6` blue |
| briefing | intel_hub (5580) | `#8b5cf6` violet |
| neonos + executive_suite | neonos (5593) | `#00e5ff` |
| admin | admin (8502, streamlit) | `#00ff41` hack green |
| asset_studio | asset_studio (5568) | `#a855f7` |
| landing.html | hub `/` route (Phase 5) | NEONCITY pink/cyan |

Scenes WITHOUT a kit extrapolate from their `[data-scene]` accent + the
4-layer background recipe (black `#02030a` → 80px drift grid → radial accent
glow → CRT scanlines) defined in `artifacts/new-assets/styles.css`.

## Per-scene glow-up recipe (Phase 4)

1. Read the kit's `index.html`; extract its inline `<style>` into
   `content/scenes/<name>/static/css/<name>_v2.css`, rewriting kit-local hex
   values to `var(--cs-*)` tokens.
2. Re-skin INSIDE the existing Jinja blocks — the scene keeps
   `{% extends 'neon_base.html' %}` + `scene_key`/`scene_accent` vars.
   Never copy kit `<html>/<head>` scaffolding.
3. **Contract preservation** (hard rule): do not rename/remove element IDs or
   classes referenced by the scene's JS, `cosysim-telemetry.js`,
   `navbar_v2.js`, `cosysim-neon-hud.js` (`#cs-hud`, `#hud-credits`,
   `#hud-location`, `#hud-heat`, …) or Socket.IO event names.
4. Apply shared utilities (stagger-in on lists, pulse-glow on CTAs, glass
   tiers on panels) instead of duplicating keyframes.
5. Stamp version, run `python scripts/browser_test.py --scene <name>`,
   compare screenshot against `data/baseline/`.

## Accent source of truth

Scene accents are injected inline by each scene template (`scene_accent` /
`scene_accent_rgb` vars). The `[data-scene]` blocks in `design_tokens_v2.css`
are a synchronized fallback for pages without template injection (previews,
standalone tools). If you change a scene's accent, change BOTH.
