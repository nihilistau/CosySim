# Scene Visual Polish Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Polish the CosySim visual system in two phases — shared CSS foundation first (all 28 scenes benefit), then deep dives on the top 5 scenes with signature wow moments.

**Architecture:** Phase 1 adds utility classes and keyframes to three shared CSS files. Phase 2 modifies scene-specific CSS/JS files only. All changes are purely presentational — no Python, no socket events, no layout restructuring.

**Tech Stack:** Vanilla CSS (custom properties, keyframes, backdrop-filter), vanilla JS (class toggling, requestAnimationFrame), Jinja2 templates. No build step. Test via `python scripts/browser_test.py`.

---

## File Map

```
Phase 1 — Shared (all 28 scenes benefit)
  MODIFY  content/shared/static/css/design_tokens.css
  MODIFY  content/shared/static/css/cosysim-animations.css
  MODIFY  content/shared/static/css/cosysim-components.css

Phase 2 — Scenes
  MODIFY  content/scenes/neoncity/static/neoncity.css
  MODIFY  content/scenes/neoncity/static/neoncity.js
  MODIFY  content/scenes/phone/templates/phone_ui_v2.html   (inline CSS+JS)
  MODIFY  content/scenes/tavern/static/tavern.css
  MODIFY  content/scenes/tavern/static/tavern.js
  MODIFY  content/scenes/oracle/static/oracle.css
  MODIFY  content/scenes/oracle/static/oracle.js
  MODIFY  content/scenes/penthouse/static/penthouse.css
  MODIFY  content/scenes/penthouse/static/penthouse.js
```

**Key context:**
- `--cs-scene-accent-rgb` is already injected by `neon_base.html` into `:root` for all Flask scenes — safe to use in shared CSS.
- `phone_ui_v2.html` is standalone (does not extend `neon_base.html`) — changes go into its inline `<style>` block.
- Existing keyframes already in `cosysim-animations.css` that we reuse: `cs-slide-up`, `cs-bar-fill`, `cs-pulse-glow-text`, `cs-shake`. Do NOT duplicate these.
- After each scene task: run `python scripts/browser_test.py` and confirm no regressions.

---

## Task 1: Typography Tokens

**Files:**
- Modify: `content/shared/static/css/design_tokens.css`

- [ ] **Step 1: Add relaxed line-height token and 3-tier typography utility classes**

Open `design_tokens.css`. After the existing `--cs-leading-loose: 1.8;` line (currently line ~215), add:

```css
    --cs-leading-relaxed: 1.6;
```

Then at the bottom of the file, after the last `[data-scene]` block, append:

```css
/* ── 3-Tier Typography Utilities ──────────────────────────────── */
/* Display: scene titles, section headings */
.cs-typo-display {
    font-family: 'Orbitron', var(--cs-font-mono);
    font-size: calc(var(--cs-text-2xl) + 4px);   /* 28px */
    font-weight: 700;
    letter-spacing: 0.06em;
    line-height: var(--cs-leading-tight);
    text-shadow: 0 0 20px rgba(var(--cs-scene-accent-rgb, 59 130 246), 0.5);
}

/* Body: paragraph text, chat messages */
.cs-typo-body {
    font-size: var(--cs-text-base);
    line-height: var(--cs-leading-relaxed);
    color: #d1d5db;
}

/* Label: tags, status indicators, small caps */
.cs-typo-label {
    font-size: var(--cs-text-xs);
    font-weight: 600;
    color: var(--cs-scene-accent, var(--cs-accent));
    letter-spacing: 0.12em;
    text-transform: uppercase;
}
```

- [ ] **Step 2: Verify no syntax errors**

```bash
python -c "
import re, pathlib
css = pathlib.Path('content/shared/static/css/design_tokens.css').read_text()
opens = css.count('{')
closes = css.count('}')
print('OK' if opens == closes else f'MISMATCH {opens} {{ vs {closes} }}')
"
```

Expected: `OK`

- [ ] **Step 3: Commit**

```bash
git add content/shared/static/css/design_tokens.css
git commit -m "style: add 3-tier typography utility classes + --cs-leading-relaxed token"
```

---

## Task 2: Animation Library

**Files:**
- Modify: `content/shared/static/css/cosysim-animations.css`

- [ ] **Step 1: Add stagger-in utility classes**

The `cs-slide-up` keyframe already exists. Append after the last existing keyframe/class in the file:

```css
/* ── Polish Additions — v1.57.3 [2026-05-12] ──────────────────── */

/* Stagger-in: apply to container; children animate in sequence */
.anim-stagger-in > * {
    opacity: 0;
    animation: cs-slide-up 0.4s var(--cs-ease, cubic-bezier(0.4,0,0.2,1)) var(--stagger-delay, 0ms) both;
}
.anim-stagger-in > *:nth-child(1)  { --stagger-delay: 0ms;   }
.anim-stagger-in > *:nth-child(2)  { --stagger-delay: 60ms;  }
.anim-stagger-in > *:nth-child(3)  { --stagger-delay: 120ms; }
.anim-stagger-in > *:nth-child(4)  { --stagger-delay: 180ms; }
.anim-stagger-in > *:nth-child(5)  { --stagger-delay: 240ms; }
.anim-stagger-in > *:nth-child(6)  { --stagger-delay: 300ms; }
.anim-stagger-in > *:nth-child(7)  { --stagger-delay: 360ms; }
.anim-stagger-in > *:nth-child(8)  { --stagger-delay: 420ms; }
.anim-stagger-in > *:nth-child(9)  { --stagger-delay: 480ms; }
.anim-stagger-in > *:nth-child(10) { --stagger-delay: 540ms; }
```

- [ ] **Step 2: Add pulse-glow utility class**

`cs-pulse-glow-text` keyframe already exists. Add the utility class:

```css
/* Pulse-glow: breathing glow on text elements (uses existing cs-pulse-glow-text keyframe) */
.anim-pulse-glow {
    animation: cs-pulse-glow-text 2.4s ease-in-out infinite;
}
```

- [ ] **Step 3: Add scan-sweep keyframe + utility class**

```css
/* Scan-sweep: light band sweeps top→bottom on hover or .scanning class */
@keyframes cs-scan-sweep-anim {
    0%   { transform: translateY(-100%); opacity: 0; }
    10%  { opacity: 1; }
    90%  { opacity: 1; }
    100% { transform: translateY(300%);  opacity: 0; }
}

.anim-scan-sweep {
    position: relative;
    overflow: hidden;
}
.anim-scan-sweep::after {
    content: '';
    position: absolute;
    left: 0;
    right: 0;
    top: 0;
    height: 35%;
    background: linear-gradient(
        180deg,
        transparent 0%,
        rgba(var(--cs-scene-accent-rgb, 59 130 246), 0.14) 40%,
        rgba(var(--cs-scene-accent-rgb, 59 130 246), 0.07) 70%,
        transparent 100%
    );
    pointer-events: none;
    z-index: 1;
    opacity: 0;
}
.anim-scan-sweep:hover::after,
.anim-scan-sweep.scanning::after {
    animation: cs-scan-sweep-anim 0.6s ease-in-out forwards;
}
```

- [ ] **Step 4: Add border-trace keyframe + utility class**

```css
/* Border-trace: border draws itself (top then right edge) on .tracing class */
@keyframes cs-border-h {
    from { width: 0; }
    to   { width: 100%; }
}
@keyframes cs-border-v {
    from { height: 0; }
    to   { height: 100%; }
}

.anim-border-trace {
    position: relative;
}
/* Top edge */
.anim-border-trace.tracing::before {
    content: '';
    position: absolute;
    top: -1px;
    left: -1px;
    height: 1.5px;
    width: 0;
    background: var(--cs-scene-accent, #3b82f6);
    pointer-events: none;
    z-index: 2;
    animation: cs-border-h 0.2s ease-out 0s forwards;
    box-shadow: 0 0 6px var(--cs-scene-accent, #3b82f6);
}
/* Right edge */
.anim-border-trace.tracing::after {
    content: '';
    position: absolute;
    top: -1px;
    right: -1px;
    width: 1.5px;
    height: 0;
    background: var(--cs-scene-accent, #3b82f6);
    pointer-events: none;
    z-index: 2;
    animation: cs-border-v 0.2s ease-out 0.2s forwards;
    box-shadow: 0 0 6px var(--cs-scene-accent, #3b82f6);
}
```

- [ ] **Step 5: Verify brace balance**

```bash
python -c "
import pathlib
css = pathlib.Path('content/shared/static/css/cosysim-animations.css').read_text()
opens = css.count('{')
closes = css.count('}')
print('OK' if opens == closes else f'MISMATCH {opens} {{ vs {closes} }}')
"
```

Expected: `OK`

- [ ] **Step 6: Commit**

```bash
git add content/shared/static/css/cosysim-animations.css
git commit -m "style: add stagger-in, pulse-glow, scan-sweep, border-trace animation utilities"
```

---

## Task 3: Glass Depth Levels + Button Standardization

**Files:**
- Modify: `content/shared/static/css/cosysim-components.css`

- [ ] **Step 1: Add 3 glass depth classes**

After the existing `.cs-glass-panel--light` block (around line ~40), append:

```css
/* ── Glass Depth Levels — v1.57.3 [2026-05-12] ────────────────── */
/* Replaces ad-hoc backdrop-filter values. 3 levels: subtle / medium / deep */

.glass-subtle {
    background: rgba(255, 255, 255, 0.03);
    backdrop-filter: blur(8px);
    -webkit-backdrop-filter: blur(8px);
    border: 1px solid rgba(255, 255, 255, 0.06);
    box-shadow: var(--cs-shadow-sm);
}

.glass-medium {
    background: rgba(255, 255, 255, 0.06);
    backdrop-filter: blur(20px);
    -webkit-backdrop-filter: blur(20px);
    border: 1px solid rgba(255, 255, 255, 0.10);
    box-shadow: var(--cs-shadow-md);
}

.glass-deep {
    background: rgba(255, 255, 255, 0.10);
    backdrop-filter: blur(40px);
    -webkit-backdrop-filter: blur(40px);
    border: 1px solid rgba(255, 255, 255, 0.16);
    box-shadow: var(--cs-shadow-lg);
}
```

- [ ] **Step 2: Add standardized button base class**

Find the existing button section in cosysim-components.css and append after it (or at the end of the file if no button section exists):

```css
/* ── Standardized Button — v1.57.3 [2026-05-12] ───────────────── */
/* Scene-aware button using --cs-scene-accent-rgb. Does not override
   existing .cs-btn — this is an additive .cs-btn-scene variant.      */

.cs-btn-scene {
    font-size: var(--cs-text-sm);
    font-weight: 600;
    letter-spacing: 0.06em;
    text-transform: uppercase;
    padding: 6px 14px;
    background: transparent;
    border: 1px solid rgba(var(--cs-scene-accent-rgb, 59 130 246), 0.4);
    border-radius: var(--cs-radius-sm);
    color: var(--cs-scene-accent, var(--cs-accent));
    cursor: pointer;
    transition: background var(--cs-duration-fast) var(--cs-ease),
                border-color var(--cs-duration-fast) var(--cs-ease),
                box-shadow var(--cs-duration-fast) var(--cs-ease);
    white-space: nowrap;
}
.cs-btn-scene:hover {
    background: rgba(var(--cs-scene-accent-rgb, 59 130 246), 0.15);
    border-color: rgba(var(--cs-scene-accent-rgb, 59 130 246), 0.6);
}
.cs-btn-scene:active,
.cs-btn-scene.active {
    background: rgba(var(--cs-scene-accent-rgb, 59 130 246), 0.9);
    border-color: var(--cs-scene-accent, var(--cs-accent));
    color: #fff;
    font-weight: 700;
    box-shadow: 0 0 20px rgba(var(--cs-scene-accent-rgb, 59 130 246), 0.5);
}
.cs-btn-scene:focus-visible {
    outline: 2px solid var(--cs-scene-accent, var(--cs-accent));
    outline-offset: 2px;
}
.cs-btn-scene:disabled,
.cs-btn-scene[disabled] {
    color: var(--cs-text-dim);
    border-color: rgba(255, 255, 255, 0.08);
    cursor: not-allowed;
    background: transparent;
    box-shadow: none;
}
```

- [ ] **Step 3: Verify brace balance**

```bash
python -c "
import pathlib
css = pathlib.Path('content/shared/static/css/cosysim-components.css').read_text()
opens = css.count('{')
closes = css.count('}')
print('OK' if opens == closes else f'MISMATCH {opens} {{ vs {closes} }}')
"
```

Expected: `OK`

- [ ] **Step 4: Commit**

```bash
git add content/shared/static/css/cosysim-components.css
git commit -m "style: add glass-subtle/medium/deep depth classes + cs-btn-scene standardized button"
```

---

## Task 4: NeonCity Polish

**Files:**
- Modify: `content/scenes/neoncity/static/neoncity.css`
- Modify: `content/scenes/neoncity/static/neoncity.js`

- [ ] **Step 1: Logo pulse-glow + header ambient gradient**

In `neoncity.css`, find the `.nc-logo__neon` rule (~line 57) and update its `text-shadow`:

```css
.nc-logo__neon {
  color: var(--nc);
  text-shadow: 0 0 20px var(--nc-glow), 0 0 40px rgba(6,182,212,0.1);
  animation: cs-pulse-glow-text 3s ease-in-out infinite;
}
```

Find the `.nc-header` rule (~line 35) and update `background`:

```css
.nc-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 8px 16px;
  background:
    radial-gradient(ellipse at top left, rgba(6,182,212,0.07) 0%, transparent 55%),
    linear-gradient(180deg, rgba(6,182,212,0.06) 0%, transparent 100%);
  border-bottom: 1px solid var(--nc-border);
  gap: 16px;
}
```

- [ ] **Step 2: District cards — stagger-in + faction left-border + scan-sweep**

In `neoncity.css`, add `.anim-stagger-in` and `.anim-scan-sweep` to the districts container and cards. Find `.nc-districts` and add:

```css
/* v1.57.3 [2026-05-12] — District stagger + scan-sweep */
.nc-districts {
  /* existing flex/grid rules stay — just add: */
}
.nc-district {
  /* existing rules stay — add: */
  border-left: 3px solid var(--dc, var(--nc));
  transition: border-color 0.2s, box-shadow 0.2s;
}
.nc-district:hover {
  box-shadow: 0 0 16px rgba(var(--nc-rgb), 0.15), -2px 0 12px rgba(var(--nc-rgb), 0.1);
}
```

Add the `anim-stagger-in` class to the `.nc-districts` div in `neoncity.html`. Open `content/scenes/neoncity/templates/neoncity.html`, find:

```html
<div class="nc-districts district-cards">
```

Change to:

```html
<div class="nc-districts district-cards anim-stagger-in">
```

Add `anim-scan-sweep` to each district card. Find:

```html
<div class="nc-district district-card" data-district="{{ d.key }}"
```

Change to:

```html
<div class="nc-district district-card anim-scan-sweep" data-district="{{ d.key }}"
```

- [ ] **Step 3: Section titles — accent glow + label upgrade**

In `neoncity.css`, find `.nc-section-title` and `.nc-panel__title` and add glow:

```css
/* v1.57.3 [2026-05-12] — Section title glow */
.nc-section-title {
  /* existing rules + add: */
  text-shadow: 0 0 16px rgba(var(--nc-rgb), 0.4);
}

.nc-panel__title {
  /* existing rules + add: */
  text-shadow: 0 0 12px rgba(var(--nc-rgb), 0.3);
  font-weight: 700;
  letter-spacing: 0.1em;
}
```

- [ ] **Step 4: Stat bars and faction bars — JS fill animation on load**

In `neoncity.js`, find the method that populates stat bars (look for `stat-health`, `stat-energy`, etc.) and add animation. Add this helper at the top of the `NeonCityApp` class or as a module-level function:

```javascript
// v1.57.3 [2026-05-12] — Animate a bar fill from 0 to target width
function animateBarFill(el, targetPct, delayMs = 0) {
  if (!el) return;
  el.style.width = '0%';
  el.style.transition = 'none';
  setTimeout(() => {
    el.style.transition = `width 0.8s cubic-bezier(0.4, 0, 0.2, 1) ${delayMs}ms`;
    el.style.width = targetPct + '%';
  }, 20);
}
```

Then find where stat bars are initially set (search for `stat-health` or `updateStats`) and wrap the width set:

```javascript
// Replace: el.style.width = pct + '%';
// With:
animateBarFill(el, pct, index * 80);
```

For faction bars, find where `bar-${fname}` is set and apply the same pattern with staggered delay. Typical pattern — find `bar.style.width = ` and replace:

```javascript
// Replace: document.getElementById(`bar-${fname}`).style.width = power + '%';
// With:
animateBarFill(document.getElementById(`bar-${fname}`), power, idx * 100);
```

(Wrap the faction loop with an index counter `let idx = 0;` and increment per iteration.)

- [ ] **Step 5: Border-trace on district card select**

In `neoncity.js`, find `NeonCityApp.visitDistrict` (~line for district click handler). After the click, add/remove the `.tracing` class:

```javascript
visitDistrict(key) {
  // existing code...

  // v1.57.3 [2026-05-12] — Border trace on selected card
  document.querySelectorAll('.nc-district').forEach(el => el.classList.remove('tracing'));
  const card = document.querySelector(`.nc-district[data-district="${key}"]`);
  if (card) {
    card.classList.add('anim-border-trace');
    // Remove and re-add to re-trigger animation
    card.classList.remove('tracing');
    void card.offsetWidth; // force reflow
    card.classList.add('tracing');
  }
}
```

- [ ] **Step 6: Browser test NeonCity**

```bash
python launcher.py neoncity &
python scripts/browser_test.py --scene neoncity
```

Expected: no errors, animations visible on load.

- [ ] **Step 7: Commit**

```bash
git add content/scenes/neoncity/static/neoncity.css content/scenes/neoncity/static/neoncity.js content/scenes/neoncity/templates/neoncity.html
git commit -m "style(neoncity): logo pulse, ambient header, district stagger+scan, faction/stat bar animations, border-trace on select"
```

---

## Task 5: Phone / SIGNAL Polish

**Files:**
- Modify: `content/scenes/phone/templates/phone_ui_v2.html` (all changes inline)

All changes in this task go inside the `<style>` block in `phone_ui_v2.html`.

- [ ] **Step 1: Gallery layout — featured-first with 6px gap**

Find the `.gallery-grid` CSS rule (~line 212):

```css
/* BEFORE: */
.gallery-grid{display:grid;grid-template-columns:repeat(3,1fr);gap:2px;padding:2px;overflow-y:auto;max-height:calc(100vh - 160px)}
```

Replace with:

```css
.gallery-grid{overflow-y:auto;max-height:calc(100vh - 160px);padding:6px;display:flex;flex-direction:column;gap:6px}
.gallery-featured-row{display:grid;grid-template-columns:2fr 1fr;gap:6px;margin-bottom:0}
.gallery-featured-main{aspect-ratio:unset;height:130px}
.gallery-featured-side{display:flex;flex-direction:column;gap:6px}
.gallery-featured-sm{flex:1}
.gallery-grid-row{display:grid;grid-template-columns:repeat(3,1fr);gap:6px}
```

Find `.gallery-item` (~line 213) and update:

```css
.gallery-item{aspect-ratio:1;overflow:hidden;cursor:pointer;background:var(--bg3);position:relative;border-radius:6px;border:1px solid rgba(16,185,129,0.12);transition:border-color 0.2s}
.gallery-item:hover{border-color:rgba(16,185,129,0.4)}
```

Then find the `renderGallery` or `loadGallery` JS function that populates the gallery. Replace the grid population logic with:

```javascript
// v1.57.3 [2026-05-12] — Featured-first gallery layout
function renderGalleryItems(container, items) {
  container.innerHTML = '';
  if (!items || items.length === 0) return;

  // Featured row: first image large, next 2 side-stack
  if (items.length >= 1) {
    const featRow = document.createElement('div');
    featRow.className = 'gallery-featured-row';

    const mainEl = _makeGalleryItem(items[0]);
    mainEl.classList.add('gallery-featured-main');
    featRow.appendChild(mainEl);

    if (items.length >= 2) {
      const side = document.createElement('div');
      side.className = 'gallery-featured-side';
      side.appendChild(_makeGalleryItemSm(items[1]));
      if (items.length >= 3) side.appendChild(_makeGalleryItemSm(items[2]));
      featRow.appendChild(side);
    }
    container.appendChild(featRow);
  }

  // Regular 3-col grid for remaining items
  const remaining = items.slice(items.length >= 3 ? 3 : items.length >= 2 ? 2 : 1);
  if (remaining.length > 0) {
    const gridRow = document.createElement('div');
    gridRow.className = 'gallery-grid-row';
    remaining.forEach(item => gridRow.appendChild(_makeGalleryItem(item)));
    container.appendChild(gridRow);
  }
}

function _makeGalleryItem(item) {
  const div = document.createElement('div');
  div.className = 'gallery-item';
  div.onclick = () => openGalleryViewer(item);
  const media = item.type === 'video'
    ? Object.assign(document.createElement('video'), {src: item.url, muted: true})
    : Object.assign(document.createElement('img'), {src: item.url, alt: '', loading: 'lazy'});
  div.appendChild(media);
  return div;
}

function _makeGalleryItemSm(item) {
  const el = _makeGalleryItem(item);
  el.classList.add('gallery-featured-sm');
  return el;
}
```

- [ ] **Step 2: Chat threads — unread differentiation**

In the `<style>` block, find `.thread-item` (~line 147) and update:

```css
.thread-item{display:flex;align-items:center;gap:12px;padding:10px 14px;background:var(--bg2);border-bottom:.5px solid var(--sep);cursor:pointer;transition:background .15s;border-left:3px solid transparent;border-radius:4px;margin:1px 4px}
.thread-item.unread{background:rgba(var(--contact-accent-rgb,16 185 129),.06);border-left-color:var(--contact-accent,var(--accent))}
.thread-item.unread .thread-name{font-weight:700;color:var(--label)}
.thread-item:not(.unread) .thread-name{font-weight:500;color:var(--label2)}
.thread-item.unread .thread-preview{color:rgba(192,216,204,.75)}
.thread-item:not(.unread) .thread-preview{color:var(--label3)}
```

Find `.avatar` (the contact avatar in thread list, ~line 150):

```css
/* Add to existing avatar rule: */
.thread-item.unread .avatar{border:1px solid rgba(var(--contact-accent-rgb,16 185 129),.45);box-shadow:0 0 8px rgba(var(--contact-accent-rgb,16 185 129),.15)}
```

In the JS, find where thread items are rendered (look for `thread-item`, `thread-name`). When building each thread element, add:

```javascript
// v1.57.3 [2026-05-12] — Per-contact accent theming + unread state
if (thread.unread_count > 0) {
  el.classList.add('unread');
}
const accentHex = thread.accent_color || '#10b981';
const accentRgb = hexToRgb(accentHex);
if (accentRgb) {
  el.style.setProperty('--contact-accent', accentHex);
  el.style.setProperty('--contact-accent-rgb', `${accentRgb.r} ${accentRgb.g} ${accentRgb.b}`);
}
```

Add the `hexToRgb` helper in the JS (if not already present):

```javascript
function hexToRgb(hex) {
  const m = /^#?([a-f\d]{2})([a-f\d]{2})([a-f\d]{2})$/i.exec(hex);
  return m ? { r: parseInt(m[1],16), g: parseInt(m[2],16), b: parseInt(m[3],16) } : null;
}
```

- [ ] **Step 3: Chat bubbles — stronger contrast + rounded tails + avatar initials**

Find `.bubble` (~line 172) and update the outgoing, incoming, and system variants:

```css
/* Replace existing bubble rules with: */
.bubble{max-width:75%;padding:8px 12px;font-size:14px;line-height:1.5;word-break:break-word;position:relative;border:1px solid transparent}
.msg-row.out .bubble{background:rgba(16,185,129,.18);color:#d1fae5;border-color:rgba(16,185,129,.35);border-radius:12px 12px 2px 12px;box-shadow:0 0 12px rgba(16,185,129,.1)}
.msg-row.in  .bubble{background:rgba(6,182,212,.12);color:#cffafe;border-color:rgba(6,182,212,.28);border-radius:12px 12px 12px 2px;box-shadow:0 0 10px rgba(6,182,212,.08)}
.msg-row.sys .bubble{background:rgba(168,85,247,.08);color:rgba(168,85,247,.75);font-size:12px;max-width:85%;border-radius:10px;text-align:center;border-color:rgba(168,85,247,.2)}
.msg-row.game .bubble{background:linear-gradient(135deg,rgba(168,85,247,.12),rgba(236,72,153,.12));color:var(--label);max-width:80%;border-radius:12px;border-color:rgba(168,85,247,.2)}
```

Add avatar initials on incoming rows. Find `.msg-row.in` CSS and add:

```css
.msg-row.in{display:flex;align-items:flex-end;gap:6px}
.msg-avatar{width:24px;height:24px;border-radius:50%;background:rgba(6,182,212,.12);border:1px solid rgba(6,182,212,.3);display:flex;align-items:center;justify-content:center;font-size:11px;font-weight:700;color:var(--teal);flex-shrink:0;text-transform:uppercase}
```

In the JS, find `addMessage` or `appendBubble` and for incoming messages wrap in:

```javascript
// v1.57.3 [2026-05-12] — Avatar initial on incoming messages
if (type === 'in') {
  const row = document.createElement('div');
  row.className = 'msg-row in';
  const avatarEl = document.createElement('div');
  avatarEl.className = 'msg-avatar';
  avatarEl.textContent = (senderName || '?')[0].toUpperCase();
  row.appendChild(avatarEl);
  row.appendChild(bubbleEl);
  return row;
}
```

- [ ] **Step 4: Ghost-signal wow moment — typewriter on incoming messages**

In the JS, find or create the function that appends new incoming bubble elements. Add typewriter effect:

```javascript
// v1.57.3 [2026-05-12] — Ghost-signal: incoming messages type in character by character
function typewriterAppend(bubbleEl, text, speedMs = 22) {
  bubbleEl.textContent = '';
  bubbleEl.classList.add('typing-in');
  let i = 0;
  const tick = () => {
    bubbleEl.textContent += text[i++];
    if (i < text.length) setTimeout(tick, speedMs);
    else bubbleEl.classList.remove('typing-in');
  };
  setTimeout(tick, 0);
}
```

Add CSS for the scan effect during typing:

```css
/* Typewriter scan underlay */
@keyframes signal-scan {
  0%   { transform: translateY(-100%); opacity: 0.6; }
  100% { transform: translateY(200%);  opacity: 0; }
}
.typing-in {
  position: relative;
  overflow: hidden;
}
.typing-in::after {
  content: '';
  position: absolute;
  left: 0; right: 0; top: 0;
  height: 40%;
  background: linear-gradient(180deg, transparent, rgba(16,185,129,.1), transparent);
  animation: signal-scan 0.8s ease-out;
  pointer-events: none;
}
```

Call `typewriterAppend(bubbleEl, text)` instead of `bubbleEl.textContent = text` for new incoming messages from the socket.

- [ ] **Step 5: Typing indicator wave + input focus glow**

Find the typing indicator CSS and update the dots:

```css
/* Replace existing typing dot animation */
@keyframes wave-dot {
  0%, 60%, 100% { transform: translateY(0);   opacity: 0.4; }
  30%            { transform: translateY(-4px); opacity: 1;   }
}
.typing-indicator .dot:nth-child(1) { animation: wave-dot 1.2s ease-in-out infinite 0s;    }
.typing-indicator .dot:nth-child(2) { animation: wave-dot 1.2s ease-in-out infinite 0.2s;  }
.typing-indicator .dot:nth-child(3) { animation: wave-dot 1.2s ease-in-out infinite 0.4s;  }
```

Find `#chat-input-wrap` and update:

```css
#chat-input-wrap{flex:1;background:var(--bg3);border-radius:20px;border:.5px solid var(--sep);display:flex;align-items:flex-end;padding:6px 12px;transition:border-color .2s,box-shadow .2s}
#chat-text-input:focus ~ #chat-input-wrap,
#chat-input-wrap:focus-within{border-color:var(--accent);box-shadow:0 0 0 2px rgba(16,185,129,.15)}
```

- [ ] **Step 6: Browser test Phone**

```bash
python launcher.py phone &
python scripts/browser_test.py --scene phone
```

Expected: no errors in console, gallery shows featured layout, bubbles clearly distinct.

- [ ] **Step 7: Commit**

```bash
git add content/scenes/phone/templates/phone_ui_v2.html
git commit -m "style(phone): featured gallery, unread thread differentiation, bubble contrast, ghost-signal typewriter, wave typing indicator"
```

---

## Task 6: Tavern Polish

**Files:**
- Modify: `content/scenes/tavern/static/tavern.css`
- Modify: `content/scenes/tavern/static/tavern.js`

- [ ] **Step 1: Warm ambient background vignette**

In `tavern.css`, find the `:root` or body/scene background rule. Append to `body` or the main scene container:

```css
/* v1.57.3 [2026-05-12] — Warm amber vignette */
body::before,
.tavern-scene::before {
  content: '';
  position: fixed;
  inset: 0;
  background: radial-gradient(ellipse at center, transparent 40%, rgba(120,53,15,0.22) 100%);
  pointer-events: none;
  z-index: 0;
}
```

- [ ] **Step 2: Panel borders — warm amber tint**

Find all `.ck-glass-panel` or `.tavern-panel` border rules. Add/override:

```css
/* v1.57.3 [2026-05-12] — Amber tinted panels */
.ck-glass-panel,
.tavern-panel,
.nc-panel {
  border-color: rgba(217,119,6,0.14);
  transition: border-color 0.2s;
}
.ck-glass-panel:hover,
.tavern-panel:hover {
  border-color: rgba(217,119,6,0.30);
}
```

- [ ] **Step 3: Quest cards — parchment strip + badge glow**

Find `.quest-card` or the quest board card class. Append:

```css
/* v1.57.3 [2026-05-12] — Quest card parchment strip */
.quest-card,
.ck-quest-item {
  position: relative;
  overflow: hidden;
}
.quest-card::before,
.ck-quest-item::before {
  content: '';
  position: absolute;
  top: 0; left: 0; right: 0;
  height: 4px;
  background: repeating-linear-gradient(
    45deg,
    rgba(217,119,6,0.08) 0px,
    rgba(217,119,6,0.08) 2px,
    rgba(217,119,6,0.04) 2px,
    rgba(217,119,6,0.04) 4px
  );
  border-bottom: 1px solid rgba(217,119,6,0.2);
}
```

Find rank badges (`.rank-badge`, `.quest-rank`, or similar) and add:

```css
.rank-badge,
.quest-rank {
  animation: cs-pulse-glow-text 2.4s ease-in-out infinite;
}
```

- [ ] **Step 4: Stat bars — fill animation on load**

Find the stat bar fill elements (`.stat-fill`, `.ck-stat-fill`, or similar). Add to their CSS:

```css
/* v1.57.3 [2026-05-12] — Stat bar fill animation */
.stat-fill,
.ck-stat-bar__fill {
  width: 0;
  animation: cs-bar-fill 0.8s cubic-bezier(0.4,0,0.2,1) var(--bar-delay, 0ms) forwards;
}
```

In the JS that sets stat bar widths (find `style.width =` on stat bars), replace direct width assignment:

```javascript
// Replace: el.style.width = pct + '%';
// With:
el.style.setProperty('--cs-bar-target', pct + '%');
el.style.setProperty('--bar-delay', (index * 120) + 'ms');
// Remove the width: 0 default if previously set (the animation handles it)
```

- [ ] **Step 5: Chat message color differentiation**

Find `.chat-entry.system` and NPC response chat entry rules. Update:

```css
/* v1.57.3 [2026-05-12] — Warm chat message tones */
.chat-entry.system,
.msg-system {
  color: rgba(217,119,6,0.65);
}
.chat-entry.npc,
.msg-npc,
.chat-entry.assistant {
  color: #f5f0e8;  /* warm white */
}
```

- [ ] **Step 6: Rumors stagger-in**

Find the rumors container (`.rumors-list`, `#rumors-list`, or `#rumor-list`). In the HTML template, add:

```html
<div id="rumor-list" class="anim-stagger-in">
```

If rumors are added dynamically via JS, instead apply delays in the JS when appending rumor items:

```javascript
// v1.57.3 [2026-05-12] — Stagger rumor entries
items.forEach((rumor, i) => {
  const el = buildRumorEl(rumor);
  el.style.setProperty('--stagger-delay', (i * 150) + 'ms');
  el.style.opacity = '0';
  el.style.animation = `cs-slide-up 0.4s cubic-bezier(0.4,0,0.2,1) ${i * 150}ms both`;
  rumorList.appendChild(el);
});
```

- [ ] **Step 7: Dice roll wow moment — screen shake + bloom**

In `tavern.css`, find `.dice-3d.rolling` and the dice result rules. Add after them:

```css
/* v1.57.3 [2026-05-12] — Dice wow: screen shake + bloom */
@keyframes tavern-screen-shake {
  0%, 100% { transform: translate(0,0) rotate(0deg); }
  15%       { transform: translate(-5px,2px) rotate(-0.3deg); }
  30%       { transform: translate(5px,-2px) rotate(0.3deg); }
  45%       { transform: translate(-4px,1px) rotate(-0.2deg); }
  60%       { transform: translate(4px,-1px) rotate(0.2deg); }
  75%       { transform: translate(-2px,1px); }
  90%       { transform: translate(2px,-1px); }
}
@keyframes tavern-bloom-flash {
  0%   { opacity: 0; }
  15%  { opacity: 0.18; }
  100% { opacity: 0; }
}

.tavern-roll-shake {
  animation: tavern-screen-shake 0.35s cubic-bezier(0.36,0.07,0.19,0.97);
}
.tavern-bloom-overlay {
  position: fixed;
  inset: 0;
  background: radial-gradient(ellipse at center, rgba(217,119,6,0.4) 0%, transparent 70%);
  pointer-events: none;
  z-index: 9999;
  opacity: 0;
  animation: tavern-bloom-flash 0.45s ease-out forwards;
}

/* Dice result value scale-up */
@keyframes dice-value-pop {
  0%   { transform: scale(1); }
  40%  { transform: scale(1.4); }
  70%  { transform: scale(1.1); }
  100% { transform: scale(1); }
}
.dice-result-pop {
  animation: dice-value-pop 0.5s cubic-bezier(0.34,1.56,0.64,1);
}
```

In `tavern.js`, find where `dice_result` socket event is handled (~line 353). After `diceEl.classList.add('rolling')` and before showing the result, add:

```javascript
// v1.57.3 [2026-05-12] — Dice wow moment
const sceneEl = document.querySelector('.tavern-scene') || document.body;

// Screen shake
sceneEl.classList.add('tavern-roll-shake');
sceneEl.addEventListener('animationend', () => sceneEl.classList.remove('tavern-roll-shake'), { once: true });

// Bloom overlay
const bloom = document.createElement('div');
bloom.className = 'tavern-bloom-overlay';
document.body.appendChild(bloom);
bloom.addEventListener('animationend', () => bloom.remove(), { once: true });

// Value pop on result display (add after result is shown)
setTimeout(() => {
  const totalEl = document.getElementById('dice-total');
  if (totalEl) {
    totalEl.classList.remove('dice-result-pop');
    void totalEl.offsetWidth;
    totalEl.classList.add('dice-result-pop');
  }
}, 350);
```

- [ ] **Step 8: Browser test Tavern**

```bash
python launcher.py tavern &
python scripts/browser_test.py --scene tavern
```

Expected: warm vignette visible, amber panel borders, dice roll triggers shake + bloom.

- [ ] **Step 9: Commit**

```bash
git add content/scenes/tavern/static/tavern.css content/scenes/tavern/static/tavern.js
git commit -m "style(tavern): warm vignette, amber panels, quest parchment, stat bar fill, dice shake+bloom wow"
```

---

## Task 7: Oracle Polish

**Files:**
- Modify: `content/scenes/oracle/static/oracle.css`
- Modify: `content/scenes/oracle/static/oracle.js`

- [ ] **Step 1: Cosmic background + star-field**

In `oracle.css`, find the body or `.oracle-scene` background rule. Append:

```css
/* v1.57.3 [2026-05-12] — Cosmic atmosphere */
.oracle-scene,
body {
  background: radial-gradient(ellipse at 50% 30%, rgba(168,85,247,0.10) 0%, #050008 60%) fixed;
}

/* Star-field via pseudo-element box-shadow */
.oracle-scene::before {
  content: '';
  position: fixed;
  inset: 0;
  pointer-events: none;
  z-index: 0;
  background-image:
    radial-gradient(1px 1px at 10% 15%, rgba(255,255,255,0.5) 0%, transparent 100%),
    radial-gradient(1px 1px at 25% 40%, rgba(255,255,255,0.3) 0%, transparent 100%),
    radial-gradient(1px 1px at 40% 8%,  rgba(255,255,255,0.4) 0%, transparent 100%),
    radial-gradient(1px 1px at 60% 20%, rgba(255,255,255,0.35) 0%, transparent 100%),
    radial-gradient(1px 1px at 75% 55%, rgba(255,255,255,0.25) 0%, transparent 100%),
    radial-gradient(1px 1px at 85% 12%, rgba(255,255,255,0.4) 0%, transparent 100%),
    radial-gradient(1px 1px at 92% 70%, rgba(255,255,255,0.3) 0%, transparent 100%),
    radial-gradient(1.5px 1.5px at 18% 80%, rgba(168,85,247,0.6) 0%, transparent 100%),
    radial-gradient(1.5px 1.5px at 50% 65%, rgba(168,85,247,0.4) 0%, transparent 100%),
    radial-gradient(1.5px 1.5px at 70% 85%, rgba(168,85,247,0.5) 0%, transparent 100%);
}
```

- [ ] **Step 2: Aura rings — multi-speed rotation + opacity breathing**

Find `.oracle-aura__ring` rules (~line 150) and update:

```css
/* v1.57.3 [2026-05-12] — Multi-speed ring rotation + opacity breathing */
@keyframes oracle-ring-breathe {
  0%, 100% { opacity: 0.3; }
  50%       { opacity: 0.7; }
}

.oracle-aura__ring {
  /* existing rules — update animation: */
  animation: oracle-ring-spin 8s linear infinite, oracle-ring-breathe 4s ease-in-out infinite;
}
.oracle-aura__ring--2 {
  animation: oracle-ring-spin 12s linear infinite reverse, oracle-ring-breathe 4s ease-in-out infinite 0.8s;
}
.oracle-aura__ring--3 {
  animation: oracle-ring-spin 20s linear infinite, oracle-ring-breathe 4s ease-in-out infinite 1.6s;
}
```

- [ ] **Step 3: Awakening sequence on load**

In `oracle.css`, add the awakening keyframe and initial ring states:

```css
/* v1.57.3 [2026-05-12] — Awakening: rings start collapsed */
@keyframes oracle-ring-awaken {
  from { transform: scale(0.35) rotate(0deg); opacity: 0; }
  to   { transform: scale(1) rotate(0deg); opacity: var(--ring-opacity, 0.5); }
}

.oracle-awakening .oracle-aura__ring {
  animation: oracle-ring-awaken 0.5s cubic-bezier(0.34,1.56,0.64,1) var(--awaken-delay, 0ms) both,
             oracle-ring-spin 8s linear var(--awaken-delay, 500ms) infinite,
             oracle-ring-breathe 4s ease-in-out var(--awaken-delay, 500ms) infinite;
}
.oracle-awakening .oracle-aura__ring--2 { --awaken-delay: 200ms; }
.oracle-awakening .oracle-aura__ring--3 { --awaken-delay: 400ms; }
```

In `oracle.js`, add the awakening sequence in the `init()` or `onConnect` method:

```javascript
// v1.57.3 [2026-05-12] — Awakening sequence on load
_runAwakeningSequence() {
  const scene = document.querySelector('.oracle-aura') || document.querySelector('.oracle-scene');
  if (!scene) return;

  // 1. Ring expand stagger
  scene.closest('.oracle-scene')?.classList.add('oracle-awakening');

  // 2. Title typewriter (after rings start)
  setTimeout(() => {
    const titleEl = document.querySelector('.oracle-title') || document.querySelector('h1.oracle-name');
    if (titleEl) {
      const original = titleEl.textContent;
      titleEl.textContent = '';
      let i = 0;
      const type = () => {
        titleEl.textContent += original[i++];
        if (i < original.length) setTimeout(type, 60);
      };
      type();
    }
  }, 600);

  // 3. Fortune shimmer
  setTimeout(() => {
    const fortuneEl = document.getElementById('fortune-result');
    if (fortuneEl && fortuneEl.textContent.trim()) {
      fortuneEl.classList.add('oracle-fortune-shimmer');
    }
  }, 1200);
}
```

Call `this._runAwakeningSequence()` inside the existing `init()` method.

Add the fortune shimmer CSS:

```css
/* Fortune text shimmer */
@keyframes oracle-fortune-shimmer {
  0%   { background-position: -200% center; }
  100% { background-position: 200% center; }
}
.oracle-fortune-shimmer {
  background: linear-gradient(90deg, var(--cs-text-primary) 30%, rgba(168,85,247,0.8) 50%, var(--cs-text-primary) 70%);
  background-size: 200% auto;
  -webkit-background-clip: text;
  -webkit-text-fill-color: transparent;
  background-clip: text;
  animation: oracle-fortune-shimmer 1.4s ease-out forwards;
}
```

- [ ] **Step 4: Health gauge fill animation**

The health ring uses a div-based design (not SVG). Find `.ase-health-ring` and check how the score is set. In `oracle.js`, find where health ring values are updated and add animation:

```javascript
// v1.57.3 [2026-05-12] — Health ring fill animation
function animateHealthRing(ringEl, targetScore) {
  if (!ringEl) return;
  // Health ring uses a conic-gradient set via JS
  let current = 0;
  const target = Math.min(100, Math.max(0, targetScore));
  const step = () => {
    current = Math.min(current + 3, target);
    ringEl.style.background = `conic-gradient(var(--ring-color, #22c55e) ${current * 3.6}deg, rgba(255,255,255,0.05) 0deg)`;
    if (current < target) requestAnimationFrame(step);
  };
  requestAnimationFrame(step);
}
```

Find where health ring score is set (look for `.ase-health-ring`, `health-score`, `healthRing`) and wrap with `animateHealthRing(ringEl, score)`.

- [ ] **Step 5: Tab switch crossfade + error feed slide**

Find the tab switching logic in `oracle.js` (look for `OracleTabs`, `switchTab`, `data-tab`):

```javascript
// v1.57.3 [2026-05-12] — Crossfade tab content
switchTab(tabId) {
  const panels = document.querySelectorAll('[data-tab-panel]');
  panels.forEach(p => {
    if (p.dataset.tabPanel === tabId) {
      p.style.opacity = '0';
      p.style.display = 'block';
      requestAnimationFrame(() => {
        p.style.transition = 'opacity 0.3s ease';
        p.style.opacity = '1';
      });
    } else {
      p.style.transition = 'opacity 0.2s ease';
      p.style.opacity = '0';
      setTimeout(() => { p.style.display = 'none'; }, 200);
    }
  });
  // update active tab button (existing logic)
}
```

Find where error feed entries are appended (look for `addErrorEntry`, `error-feed`, `alert-entry`) and add slide-in:

```javascript
// v1.57.3 [2026-05-12] — Error feed slide-in from right
function appendErrorEntry(container, el) {
  el.style.transform = 'translateX(100%)';
  el.style.opacity = '0';
  el.style.transition = 'transform 0.25s ease-out, opacity 0.25s ease-out';
  container.prepend(el);
  requestAnimationFrame(() => {
    el.style.transform = 'translateX(0)';
    el.style.opacity = '1';
  });
}
```

- [ ] **Step 6: Browser test Oracle**

```bash
python launcher.py oracle &
python scripts/browser_test.py --scene oracle
```

Expected: cosmic background visible, rings animate on load, fortune text shimmer.

- [ ] **Step 7: Commit**

```bash
git add content/scenes/oracle/static/oracle.css content/scenes/oracle/static/oracle.js
git commit -m "style(oracle): cosmic bg+stars, multi-speed aura rings, awakening sequence, fortune shimmer, health ring animation, tab crossfade"
```

---

## Task 8: Penthouse Polish

**Files:**
- Modify: `content/scenes/penthouse/static/penthouse.css`
- Modify: `content/scenes/penthouse/static/penthouse.js`

- [ ] **Step 1: Update accent color to warmer purple**

In `penthouse.css`, find where `#8b5cf6` is hardcoded or `--cs-scene-penthouse` is used. Update the accent token at the top of the file:

```css
/* v1.57.3 [2026-05-12] — Warmer luxury purple (replaces neon violet) */
:root,
[data-scene="penthouse"] {
  --cs-scene-accent: #9d71ea;
  --cs-scene-glow: rgba(157, 113, 234, 0.35);
  --cs-scene-accent-rgb: 157 113 234;
  --ph-accent: #9d71ea;
  --ph-accent-rgb: 157 113 234;
}
```

- [ ] **Step 2: Dark skyline background + rain streaks**

```css
/* v1.57.3 [2026-05-12] — Penthouse skyline + rain */
body,
.penthouse-scene {
  background:
    radial-gradient(ellipse at 50% 100%, rgba(157,113,234,0.06) 0%, transparent 60%),
    linear-gradient(180deg, #070510 0%, #0a0818 60%, #0d0c1a 100%);
}

/* SVG skyline silhouette at bottom */
.penthouse-scene::before {
  content: '';
  position: fixed;
  bottom: 0; left: 0; right: 0;
  height: 35vh;
  background:
    url("data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 1440 200' preserveAspectRatio='xMidYMax meet'%3E%3Cpath fill='rgba(10,8,24,0.85)' d='M0,200 L0,140 L40,140 L40,100 L60,100 L60,80 L80,80 L80,120 L120,120 L120,60 L140,60 L140,40 L160,40 L160,60 L180,60 L180,100 L220,100 L220,70 L240,70 L240,50 L260,50 L260,70 L280,70 L280,110 L320,110 L320,80 L350,80 L350,40 L370,40 L370,80 L400,80 L400,120 L440,120 L440,90 L460,90 L460,60 L480,60 L480,90 L520,90 L520,130 L560,130 L560,100 L580,100 L580,70 L600,70 L600,50 L620,50 L620,70 L640,70 L640,100 L680,100 L680,120 L720,120 L720,80 L750,80 L750,50 L770,50 L770,80 L800,80 L800,110 L840,110 L840,130 L880,130 L880,90 L900,90 L900,60 L920,60 L920,90 L960,90 L960,120 L1000,120 L1000,80 L1020,80 L1020,40 L1040,40 L1040,80 L1060,80 L1060,100 L1100,100 L1100,130 L1140,130 L1140,100 L1160,100 L1160,70 L1180,70 L1180,100 L1200,100 L1200,130 L1240,130 L1240,110 L1260,110 L1260,80 L1280,80 L1280,110 L1320,110 L1320,140 L1360,140 L1360,120 L1400,120 L1400,140 L1440,140 L1440,200 Z'/%3E%3C/svg%3E") bottom/cover no-repeat;
  pointer-events: none;
  z-index: 0;
}

/* Rain streaks */
@keyframes ph-rain {
  from { transform: translateY(-100vh); }
  to   { transform: translateY(100vh); }
}
.penthouse-scene::after {
  content: '';
  position: fixed;
  inset: 0;
  pointer-events: none;
  z-index: 0;
  background-image:
    linear-gradient(180deg, rgba(157,113,234,0.08) 0%, transparent 100%),
    repeating-linear-gradient(
      175deg,
      transparent 0px,
      transparent 40px,
      rgba(255,255,255,0.025) 40px,
      rgba(255,255,255,0.025) 41px
    );
  animation: ph-rain 4s linear infinite;
  opacity: 0.6;
}
```

- [ ] **Step 3: Panel luxury styling + character card portrait**

Find `.ph-character-panel` or the main content panel class. Apply glass-deep treatment:

```css
/* v1.57.3 [2026-05-12] — Luxury panel styling */
.ph-character-panel,
.penthouse-panel {
  background: rgba(255,255,255,0.10);
  backdrop-filter: blur(40px);
  -webkit-backdrop-filter: blur(40px);
  border: 1px solid rgba(255,255,255,0.16);
  /* Add purple tint layer: */
  box-shadow:
    inset 0 0 30px rgba(157,113,234,0.04),
    0 8px 32px rgba(0,0,0,0.7);
  /* +20% padding from base */
  padding: 20px;
}
```

Find `.ph-mi-card` (model/character card ~line 572) and update hover:

```css
/* v1.57.3 [2026-05-12] — Character card lift hover */
.ph-mi-card {
  transition: transform 0.2s ease, box-shadow 0.2s ease, border-color 0.2s ease;
}
.ph-mi-card:hover {
  transform: translateY(-4px);
  box-shadow: 0 12px 40px rgba(157,113,234,0.25), 0 4px 16px rgba(0,0,0,0.5);
  border-color: rgba(157,113,234,0.4);
}
```

Find portrait image containers and add vignette:

```css
/* Portrait vignette + border */
.cs-portrait-frame img,
.ph-mi-card img,
.ph-portrait {
  border: 2px solid rgba(157,113,234,0.3);
  box-shadow: inset 0 0 20px rgba(0,0,0,0.5);
}
```

- [ ] **Step 4: Elevator reveal on page load**

In `penthouse.css`, add the keyframe:

```css
/* v1.57.3 [2026-05-12] — Elevator reveal */
@keyframes ph-elevator-rise {
  from { transform: translateY(40px); opacity: 0; }
  to   { transform: translateY(0);    opacity: 1; }
}
@keyframes ph-bg-counter {
  from { transform: translateY(-10px); }
  to   { transform: translateY(0); }
}

.ph-elevator-reveal {
  animation: ph-elevator-rise 0.6s cubic-bezier(0.16, 1, 0.3, 1) both;
}
```

In `penthouse.js`, add elevator reveal in the init/ready handler:

```javascript
// v1.57.3 [2026-05-12] — Elevator reveal on page load
_runElevatorReveal() {
  // Reveal main content
  const main = document.querySelector('.penthouse-main') ||
               document.querySelector('.ph-character-panel') ||
               document.querySelector('main');
  if (main) {
    main.classList.add('ph-elevator-reveal');
  }

  // Reveal model cards with stagger
  const cards = document.querySelectorAll('.ph-mi-card');
  cards.forEach((card, i) => {
    card.style.opacity = '0';
    card.style.animation = `ph-elevator-rise 0.5s cubic-bezier(0.16,1,0.3,1) ${200 + i * 80}ms both`;
  });
}
```

Call `this._runElevatorReveal()` in the init method after the DOM is ready.

- [ ] **Step 5: Browser test Penthouse**

```bash
python launcher.py penthouse &
python scripts/browser_test.py --scene penthouse
```

Expected: warm purple accent, skyline visible, rain streaks, cards lift on hover, elevator reveal on load.

- [ ] **Step 6: Commit**

```bash
git add content/scenes/penthouse/static/penthouse.css content/scenes/penthouse/static/penthouse.js
git commit -m "style(penthouse): warmer accent, skyline+rain bg, luxury glass panels, card hover lift, elevator reveal wow"
```

---

## Self-Review Checklist

**Spec coverage:**
- [x] Phase 1: typography scale (Task 1), animation library (Task 2), glass depth + buttons (Task 3)
- [x] NeonCity: logo pulse, ambient header, district stagger+scan+border-trace, faction/stat bars (Task 4)
- [x] Phone: gallery featured layout, thread unread differentiation, bubble contrast, ghost-signal typewriter, wave typing, input focus (Task 5)
- [x] Tavern: warm vignette, amber panels, quest parchment, stat bars, chat tones, rumors stagger, dice shake+bloom (Task 6)
- [x] Oracle: cosmic bg+stars, multi-speed rings, awakening sequence, health ring animation, tab crossfade, error feed slide (Task 7)
- [x] Penthouse: warmer accent, skyline+rain, luxury panels, portrait vignette, card hover lift, elevator reveal (Task 8)

**Notes:**
- `cs-bar-fill` keyframe already exists in `cosysim-animations.css` — Task 6 reuses it via `--cs-bar-target` var (which is how it was designed).
- `renderGallery` function name in Task 5 may differ — find the actual function name by grepping `phone_ui_v2.html` for `gallery` before implementing.
- Tavern scene root element class (`.tavern-scene`) may differ — grep `tavern.html` template to confirm before implementing Task 6 Step 1.
- Oracle's health ring uses CSS conic-gradient set inline — confirm approach by reading `oracle.js` health update method before Task 7 Step 4.
