# CosySim Scene Visual Polish — Design Spec
**Date:** 2026-05-12  
**Scope:** Visual polish only (no functional changes)  
**Aesthetic:** Stay within existing dark cyberpunk/neon — tighten and refine  
**Approach:** Hybrid — Phase 1 shared system foundation, Phase 2 top-5 scene deep dives  

---

## Goals

- Stronger visual hierarchy so every scene feels intentional, not generic
- Each of the top 5 scenes gets a signature "wow moment" — something memorable on load/interaction
- All 28 scenes benefit from Phase 1 without individual changes

### Out of scope
- Functional changes, new features, layout restructuring
- Scenes outside the top 5 (Phase 2 only applies to NeonCity, Phone, Tavern, Oracle, Penthouse)
- Backend changes of any kind

---

## Phase 1 — Shared System Pass

Changes to shared CSS files only. All 28 scenes inherit these automatically.

### 1.1 Typography Scale (`design_tokens.css`)

Three-tier hierarchy — every element must belong to exactly one tier:

| Tier | Element | Changes |
|------|---------|---------|
| **Display** | Scene titles, section headings (Orbitron) | +4px size, weight 700, subtle color glow via `text-shadow: 0 0 20px rgba(var(--scene-accent-rgb), 0.5)` |
| **Body** | Paragraph text, chat messages | `line-height: 1.6` (up from ~1.4), `color: #d1d5db` |
| **Label** | Tags, status indicators, small caps | `font-weight: 600`, `color: var(--scene-accent)`, `letter-spacing: 0.12em` |

### 1.2 Animation Library (`cosysim-animations.css`)

Four new reusable keyframe animations. Applied via utility classes:

| Class | Keyframe | Duration | Trigger | Description |
|-------|----------|----------|---------|-------------|
| `.anim-stagger-in` | `staggerIn` | 0.4s + `--delay` CSS var | Page load | Child elements glide up 12px + fade in. Parent sets `--delay` per child via `nth-child`. |
| `.anim-pulse-glow` | `pulseGlow` | 2.4s loop | Always-on accent elements | box-shadow/text-shadow breathes 40%→100% opacity |
| `.anim-scan-sweep` | `scanSweep` | 0.6s | Hover or data refresh | Single horizontal light band sweeps panel top→bottom |
| `.anim-border-trace` | `borderTrace` | 0.4s | On mount / on select | Border draws itself via a `::before` pseudo-element: `width` animates 0%→100% (top edge), then `height` 0%→100% (right edge) in sequence. Uses `--scene-accent` color. No clip-path — wider browser support. |

### 1.3 Glass Panel Depth (`cosysim-components.css`)

Three standardized classes replacing 20+ ad-hoc `backdrop-filter` values across scenes:

| Class | `backdrop-filter` | `background` opacity | `border` opacity | Use |
|-------|------------------|---------------------|-----------------|-----|
| `.glass-subtle` | `blur(8px)` | 0.03 | 0.06 | Sidebars, secondary panels — recedes |
| `.glass-medium` | `blur(20px)` | 0.06 | 0.10 | Main content panels — default |
| `.glass-deep` | `blur(40px)` | 0.10 | 0.16 | Modals, focus panels, HUD overlays — comes forward |

All three classes use `rgba(255,255,255, <opacity>)` for background and border so they work with any scene accent color.

### 1.4 Button States (`cosysim-components.css`)

Standardized across all 28 scenes. All buttons inject `--scene-accent` for color so no scene-specific overrides needed:

| State | Treatment |
|-------|-----------|
| Default | `border: 1px solid rgba(var(--scene-accent-rgb), 0.4)`, transparent background |
| Hover | `background: rgba(var(--scene-accent-rgb), 0.15)`, border opacity → 0.6 |
| Active fill | `background: rgba(var(--scene-accent-rgb), 0.9)`, weight 600, glow shadow |
| Danger | Red variant — independent of accent |
| Disabled | `color: #4b5563`, `border-color: rgba(255,255,255,0.08)` |

All buttons: `transition: all 150ms`, consistent focus ring, `letter-spacing: 0.06em`.

---

## Phase 2 — Top 5 Scene Deep Dives

Each scene gets: a signature wow moment, atmosphere improvements, animation passes, typography tightening, and component polish. All changes are scene-scoped (scene-specific CSS/JS only).

---

### Scene 1 — NeonCity `:5563` (cyan `#06b6d4`)

**Files:** `neoncity.css`, `neoncity.js`

#### Wow Moment
District cards: on hover, a cyan scanline sweeps the card surface (`anim-scan-sweep`). On click/selection, `anim-border-trace` draws the accent border around the selected card in 0.4s.

#### Changes

| Area | Change |
|------|--------|
| **Logo** | NEON text gets `anim-pulse-glow` on a 3s loop. Glow spread increases from 20px to 30px. |
| **Header** | Add ambient city-light gradient bleeding from top-left: `radial-gradient(ellipse at top left, rgba(6,182,212,0.08) 0%, transparent 60%)` |
| **Faction bars** | On page load: bars start at 0%, count up to their value with `cubic-bezier(0.4, 0, 0.2, 1)` easing over 1.2s. Staggered 100ms per faction. |
| **District cards** | `anim-stagger-in` on page load (6 cards, 60ms delay each). Each card gets a 3px left-border in its faction color. |
| **Stat bars** (HP/EN/HT/REP) | Fill animation from 0% on load, 800ms, staggered 80ms per bar. |
| **Section titles** | `text-shadow: 0 0 16px rgba(6,182,212,0.4)` added. Labels upgraded to Phase 1 label tier. |

---

### Scene 2 — Phone / SIGNAL `:5555` (emerald `#10b981`)

**Files:** `phone_ui_v2.html` (inline CSS + JS)

#### Wow Moment
Incoming messages materialize character-by-character with a faint emerald scan underneath — feels like a transmission through static. Implemented as a JS `typewriter` effect on new `.bubble-in` elements, with a `::after` scan pseudo-element that sweeps once on entry.

#### Changes — Gallery

| Area | Change |
|------|--------|
| **Layout** | Most recent image: featured large (2/3 width), next 2 in a side-stack (1/3 width, half height each). Remaining images in standard 3-col below. |
| **Grid gap** | 2px → 6px |
| **Outer padding** | 0 → 6px |
| **Item style** | `border-radius: 6px`, `border: 1px solid rgba(16,185,129,0.12)`, hover: border brightens to 0.4 opacity |

#### Changes — Chat Threads

| Area | Change |
|------|--------|
| **Unread indicator** | `border-left: 3px solid var(--contact-accent, #10b981)` on unread threads. Read threads: no left border. |
| **Avatar** | Unread: `border: 1px solid rgba(var(--contact-accent-rgb, 16 185 129), 0.4)` + matching glow. |
| **Unread background** | Slightly lighter background tinted toward contact accent. |
| **Contact accent theming** | JS sets `--contact-accent` and `--contact-accent-rgb` as inline CSS custom properties on each `.thread-item` element when rendering the list. Default falls back to emerald if no contact color defined. |
| **Name weight** | Unread: `font-weight: 700`. Read: `font-weight: 500`, muted color. |
| **Preview text** | Unread: `color: rgba(192,216,204,0.75)`. Read: `color: rgba(192,216,204,0.4)`. |
| **Unread badge** | Exists in current code — ensure it renders with contact accent color (not always red). |

#### Changes — Chat Bubbles

| Element | Change |
|---------|--------|
| **Outgoing** | `background: rgba(16,185,129,0.18)` (up from 0.10), `border-color: rgba(16,185,129,0.35)` (up from 0.15), `color: #d1fae5`, `border-radius: 12px 12px 2px 12px` |
| **Incoming** | `background: rgba(6,182,212,0.12)` (up from 0.06), `border-color: rgba(6,182,212,0.28)` (up from 0.12), `color: #cffafe`, `border-radius: 12px 12px 12px 2px` |
| **System** | `background: rgba(168,85,247,0.08)`, `border-color: rgba(168,85,247,0.18)`, `color: rgba(168,85,247,0.7)`, `border-radius: 10px` |
| **Avatar initials** | 24×24px avatar shown next to incoming messages. Initial character from contact name. Accent-tinted border. |
| **Timestamps** | Added to outgoing messages (10px, 35% opacity, right-aligned) |

#### Other Phone Changes

| Area | Change |
|------|--------|
| **Background** | Subtle noise texture overlay (SVG data URI, 3% opacity) + deep green ambient fog via radial-gradient |
| **Typing indicator** | Replace 3-dot blink with wave animation (dots animate sequentially, not simultaneously) |
| **Input focus** | On focus: `border-color` transitions to accent, subtle glow, input bar expands 2px height |
| **Investigation board** | Pin/thread lines get `opacity: 0.6` to differentiate from content layer |

---

### Scene 3 — Tavern / The Rusty Anchor `:5558` (amber `#d97706`)

**Files:** scene-specific CSS + JS (to be confirmed on read)

#### Wow Moment
Dice roll: full-scene `@keyframes screenShake` (3 rapid translate oscillations over 0.3s), followed by a bloom flash — `::after` pseudo-overlay flashing amber at 20% opacity for 0.15s. The rolled value number scales up to 1.4× then settles.

#### Changes

| Area | Change |
|------|--------|
| **Background** | Warm amber/brown vignette: `radial-gradient(ellipse at center, transparent 40%, rgba(120,53,15,0.25) 100%)`. Corners darker. |
| **Panel borders** | Tint from cool blue-gray to warm amber: `rgba(217,119,6,0.12)` base, `rgba(217,119,6,0.30)` on hover |
| **Quest cards** | Top strip: `background: rgba(217,119,6,0.08)` with subtle texture feel (repeating-linear-gradient at 45deg, fine lines). Rank badge gets `anim-pulse-glow`. |
| **Stat bars** | Fill from 0 on page load with stagger (same pattern as NeonCity). Warmth: orange, Courage: red, Clarity: blue, Charm: purple. |
| **Chat messages** | System messages: `color: rgba(217,119,6,0.6)`. NPC responses: `color: #f5f0e8` (warm white, not cool gray). |
| **Rumor items** | Each rumor fades in with 200ms delay per item — `anim-stagger-in` — as if being overheard one by one. |

---

### Scene 4 — Oracle `:5572` (violet `#a855f7`)

**Files:** scene-specific CSS + JS (to be confirmed on read)

#### Wow Moment
Page load awakening sequence:
1. Aura rings start at `transform: scale(0.4)`, expand outward in sequence (3 rings × 200ms stagger)
2. Oracle title types itself letter by letter (JS typewriter, 60ms per character)
3. First fortune text appears with a shimmer sweep (`background: linear-gradient(90deg, transparent, rgba(168,85,247,0.3), transparent)` scrolling across the text)

Total sequence duration: ~1.8s.

#### Changes

| Area | Change |
|------|--------|
| **Aura rings** | Each ring rotates at a different speed (8s, 12s, 20s). Opacity breathes on a 4s loop between 0.3 and 0.7. Counter-rotate alternating rings. |
| **Background** | Deep cosmic gradient: `radial-gradient(ellipse at 50% 30%, rgba(168,85,247,0.12) 0%, #050008 60%)`. Add faint star-field: 50–80 tiny white dots via `box-shadow` on a pseudo-element. |
| **Health gauges** | SVG `stroke-dashoffset` animates from full offset (empty) to final value on load. 1s duration, ease-out. |
| **Tab switch** | Crossfade: `opacity` transition 300ms. Consciousness → Eye: brief iris-wipe using `clip-path: circle()` expanding from center. |
| **Error feed entries** | New entries: `translateX(100%)` → `translateX(0)` slide in from right, 250ms. Removed entries: slide out left. |
| **Section labels** | Purple glow on active state. Fortune text uses `letter-spacing: 0.04em` for a slightly ethereal feel. |

---

### Scene 5 — Penthouse `:5556` (purple `#8b5cf6` → warm `#9d71ea`)

**Files:** scene-specific CSS + JS (to be confirmed on read)

#### Wow Moment
Elevator reveal on page load: main content panel starts at `transform: translateY(40px)`, slides up to `translateY(0)` over 0.6s with `cubic-bezier(0.16, 1, 0.3, 1)` (spring-like ease). Background cityscape parallaxes 10px in the opposite direction as it settles.

#### Changes

| Area | Change |
|------|--------|
| **Accent color** | `#8b5cf6` → `#9d71ea` (warmer purple, luxury over neon) |
| **Background** | Dark skyline silhouette SVG layer at bottom of viewport (20% opacity). Rain streak particle layer: thin vertical lines, slow downward animation, 10% opacity. |
| **Panel style** | `glass-deep` class (40px blur). Add subtle purple tint: `background: rgba(157,113,234,0.04)` layered under the white glass. Padding +20% vs other scenes. |
| **Character cards** | Portrait `border: 2px solid rgba(157,113,234,0.3)`. Soft vignette on portrait image: `box-shadow: inset 0 0 20px rgba(0,0,0,0.5)`. |
| **Hover states** | Cards: `transform: translateY(-4px)` + `box-shadow` depth increase. Transition 200ms ease. |
| **Typography** | Display font +2px larger than other scenes. Body text `color: #e5e7eb` (brighter than default #d1d5db) for luxury contrast. |

---

## Implementation Order

```
Phase 1 (shared — do first, all scenes benefit)
  1. design_tokens.css      — typography scale
  2. cosysim-animations.css — 4 new keyframes
  3. cosysim-components.css — glass depth classes + button states

Phase 2 (scene order — top visibility first)
  4. NeonCity   — neoncity.css + neoncity.js
  5. Phone      — phone_ui_v2.html (inline)
  6. Tavern     — tavern CSS + JS (confirm filenames)
  7. Oracle     — oracle CSS + JS (confirm filenames)
  8. Penthouse  — penthouse CSS + JS (confirm filenames)
```

## Files to Confirm Before Phase 2 Work

Scenes 3–5 (Tavern, Oracle, Penthouse) need a quick file read before starting each to confirm exact CSS/JS filenames and current class names. The pattern from NeonCity (scene-prefixed classes, inline vars) likely holds.

## Testing

After each scene: run `python scripts/browser_test.py` and verify:
- Wow moment triggers correctly on load/interaction
- No layout breaks vs current state
- Animations don't fire on every re-render (only on mount)
- Phase 1 glass/button classes don't conflict with scene-specific overrides
