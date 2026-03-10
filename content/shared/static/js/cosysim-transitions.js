/**
 * CosySim Cyberpunk Transitions — premium scene-navigation effects.
 *
 * Effects: glitch dissolve, neon wipe, digital rain, circuit trace, hex grid.
 * Intercepts [data-scene-nav] links. Overlay sits at z-index 99999.
 * Entry animation plays a 300ms "materialize from noise" on first page load.
 *
 * API exposed on window.CosyTransitions:
 *   setStyle(name)         — set active transition style
 *   getStyles()            — list available style names
 *   navigate(url, style?)  — programmatic navigation with optional style
 */
(function () {
  'use strict';

  // ── Constants ──────────────────────────────────────────────────────────────
  const STYLES = ['glitch', 'neon_wipe', 'digital_rain', 'circuit', 'hex_grid'];
  const TRANSITION_MS = 500;
  const ENTRY_MS = 300;
  const RAIN_CHARS = 'アイウエオカキクケコサシスセソタチツテトナニヌネノ0123456789ABCDEF<>{}[]=/\\';

  let _activeStyle = 'random';
  let _transitioning = false;
  let _entryPlayed = false;

  // ── Accent colour detection ────────────────────────────────────────────────
  function getAccentColor() {
    const css = getComputedStyle(document.documentElement);
    const fromVar = css.getPropertyValue('--accent-color').trim()
      || css.getPropertyValue('--scene-accent').trim()
      || css.getPropertyValue('--primary-color').trim();
    if (fromVar) return fromVar;
    const scene = document.body.dataset.scene || '';
    const map = {
      bedroom: '#ff44cc', bar: '#ff6622', spa: '#44ffcc',
      lounge: '#aa66ff', hub: '#00ccff'
    };
    return map[scene] || '#00f0ff';
  }

  function hexToRgb(hex) {
    const m = /^#?([\da-f]{2})([\da-f]{2})([\da-f]{2})$/i.exec(hex);
    return m ? { r: parseInt(m[1], 16), g: parseInt(m[2], 16), b: parseInt(m[3], 16) } : { r: 0, g: 240, b: 255 };
  }

  // ── Sound-ready event emitter ──────────────────────────────────────────────
  function emitTransitionEvent(phase, detail) {
    document.dispatchEvent(new CustomEvent('cosytransition', {
      detail: { phase, style: detail.style, ts: performance.now(), ...detail }
    }));
  }

  // ── Overlay helpers ────────────────────────────────────────────────────────
  function createOverlay(tag) {
    const el = document.createElement(tag || 'div');
    el.className = 'cs-transition-overlay';
    Object.assign(el.style, {
      position: 'fixed', top: '0', left: '0',
      width: '100vw', height: '100vh',
      zIndex: '99999', pointerEvents: 'none'
    });
    document.body.appendChild(el);
    return el;
  }

  function removeOverlay(el) {
    if (el && el.parentNode) el.parentNode.removeChild(el);
  }

  function createCanvas() {
    const c = createOverlay('canvas');
    c.width = window.innerWidth;
    c.height = window.innerHeight;
    return c;
  }

  // ── Inject CSS keyframes (once) ────────────────────────────────────────────
  let _stylesInjected = false;
  function injectStyles() {
    if (_stylesInjected) return;
    _stylesInjected = true;
    const style = document.createElement('style');
    style.textContent = `
      @keyframes cs-hex-flip {
        0%   { transform: scale(1) rotateY(0deg); opacity: 1; }
        50%  { transform: scale(0.8) rotateY(90deg); opacity: 0.4; }
        100% { transform: scale(1) rotateY(180deg); opacity: 1; }
      }
      @keyframes cs-neon-glow {
        0%, 100% { box-shadow: 0 0 8px var(--cs-accent), 0 0 20px var(--cs-accent); }
        50%      { box-shadow: 0 0 16px var(--cs-accent), 0 0 40px var(--cs-accent), 0 0 60px var(--cs-accent); }
      }
      @keyframes cs-materialize {
        0%   { filter: contrast(2) brightness(1.4); opacity: 0; }
        40%  { filter: contrast(1.3) brightness(1.1); opacity: 0.7; }
        100% { filter: contrast(1) brightness(1); opacity: 1; }
      }
      .cs-page-materialize {
        animation: cs-materialize ${ENTRY_MS}ms ease-out forwards;
      }
    `;
    document.head.appendChild(style);
  }

  // ── Resolve which style to run ─────────────────────────────────────────────
  function resolveStyle(override) {
    const s = override || _activeStyle;
    if (s === 'random') return STYLES[Math.floor(Math.random() * STYLES.length)];
    return STYLES.includes(s) ? s : 'glitch';
  }

  // ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
  //  EFFECT: Glitch Dissolve
  // ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
  function glitchDissolve(cb) {
    const canvas = createCanvas();
    const ctx = canvas.getContext('2d');
    const w = canvas.width, h = canvas.height;
    const accent = hexToRgb(getAccentColor());
    const stripCount = 24;
    const stripH = Math.ceil(h / stripCount);
    const start = performance.now();
    const dur = TRANSITION_MS;

    emitTransitionEvent('start', { style: 'glitch' });

    function frame(now) {
      const t = Math.min((now - start) / dur, 1);
      ctx.clearRect(0, 0, w, h);

      // Noise base
      const noise = ctx.createImageData(w, h);
      const d = noise.data;
      const noiseIntensity = t < 0.5 ? t * 2 : (1 - t) * 2;
      for (let i = 0; i < d.length; i += 4) {
        if (Math.random() < noiseIntensity * 0.3) {
          d[i] = Math.random() * 255;
          d[i + 1] = Math.random() * 255;
          d[i + 2] = Math.random() * 255;
          d[i + 3] = Math.floor(noiseIntensity * 120);
        }
      }
      ctx.putImageData(noise, 0, 0);

      // Horizontal strip offsets with RGB separation
      for (let i = 0; i < stripCount; i++) {
        const y = i * stripH;
        const offset = (Math.random() - 0.5) * 60 * noiseIntensity;
        const glitchChance = noiseIntensity * 0.6;
        if (Math.random() < glitchChance) {
          // Red channel strip
          ctx.fillStyle = `rgba(${accent.r}, 0, 0, ${noiseIntensity * 0.3})`;
          ctx.fillRect(offset - 3, y, w, stripH);
          // Blue channel strip
          ctx.fillStyle = `rgba(0, 0, ${accent.b}, ${noiseIntensity * 0.3})`;
          ctx.fillRect(offset + 3, y, w, stripH);
        }
      }

      // Scanlines
      ctx.fillStyle = `rgba(0,0,0,${0.08 * noiseIntensity})`;
      for (let y = 0; y < h; y += 2) {
        ctx.fillRect(0, y, w, 1);
      }

      // Final black fill for navigation
      if (t > 0.7) {
        const blackAlpha = (t - 0.7) / 0.3;
        ctx.fillStyle = `rgba(0,0,0,${blackAlpha})`;
        ctx.fillRect(0, 0, w, h);
      }

      if (t < 1) {
        requestAnimationFrame(frame);
      } else {
        emitTransitionEvent('mid', { style: 'glitch' });
        cb();
        setTimeout(() => removeOverlay(canvas), 50);
      }
    }
    requestAnimationFrame(frame);
  }

  // ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
  //  EFFECT: Neon Wipe
  // ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
  function neonWipe(cb) {
    const canvas = createCanvas();
    const ctx = canvas.getContext('2d');
    const w = canvas.width, h = canvas.height;
    const accent = getAccentColor();
    const rgb = hexToRgb(accent);
    const start = performance.now();
    const dur = TRANSITION_MS;
    const lineWidth = 4;

    emitTransitionEvent('start', { style: 'neon_wipe' });

    function frame(now) {
      const t = Math.min((now - start) / dur, 1);
      const eased = t < 0.5 ? 2 * t * t : 1 - Math.pow(-2 * t + 2, 2) / 2;
      const lineX = eased * (w + 60) - 30;
      ctx.clearRect(0, 0, w, h);

      // Dissolve fill behind the wipe line
      if (lineX > 0) {
        const grd = ctx.createLinearGradient(Math.max(0, lineX - 80), 0, lineX, 0);
        grd.addColorStop(0, 'rgba(0,0,0,1)');
        grd.addColorStop(1, `rgba(${rgb.r},${rgb.g},${rgb.b},0.15)`);
        ctx.fillStyle = grd;
        ctx.fillRect(0, 0, lineX, h);

        // Solid black behind the gradient
        ctx.fillStyle = 'rgba(0,0,0,1)';
        ctx.fillRect(0, 0, Math.max(0, lineX - 80), h);
      }

      // Neon wipe line
      ctx.shadowColor = accent;
      ctx.shadowBlur = 30;
      ctx.fillStyle = accent;
      ctx.fillRect(lineX - lineWidth / 2, 0, lineWidth, h);

      // Outer glow layers
      for (let g = 0; g < 3; g++) {
        const glowW = (g + 1) * 8;
        ctx.fillStyle = `rgba(${rgb.r},${rgb.g},${rgb.b},${0.12 - g * 0.03})`;
        ctx.fillRect(lineX - glowW / 2, 0, glowW, h);
      }
      ctx.shadowBlur = 0;

      // Pixel scatter ahead of wipe
      const scatterZone = 60;
      for (let i = 0; i < 40; i++) {
        const px = lineX + Math.random() * scatterZone;
        const py = Math.random() * h;
        if (px < w && Math.random() < 0.5) {
          ctx.fillStyle = `rgba(${rgb.r},${rgb.g},${rgb.b},${Math.random() * 0.5})`;
          ctx.fillRect(px, py, 2, 2);
        }
      }

      if (t < 1) {
        requestAnimationFrame(frame);
      } else {
        emitTransitionEvent('mid', { style: 'neon_wipe' });
        cb();
        setTimeout(() => removeOverlay(canvas), 50);
      }
    }
    requestAnimationFrame(frame);
  }

  // ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
  //  EFFECT: Digital Rain
  // ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
  function digitalRain(cb) {
    const canvas = createCanvas();
    const ctx = canvas.getContext('2d');
    const w = canvas.width, h = canvas.height;
    const accent = getAccentColor();
    const rgb = hexToRgb(accent);
    const fontSize = 14;
    const cols = Math.ceil(w / fontSize);
    const drops = new Array(cols).fill(0).map(() => -Math.random() * 20);
    const speeds = new Array(cols).fill(0).map(() => 0.6 + Math.random() * 0.8);
    const start = performance.now();
    const dur = TRANSITION_MS + 100;

    emitTransitionEvent('start', { style: 'digital_rain' });

    function frame(now) {
      const t = Math.min((now - start) / dur, 1);

      // Trailing fade
      ctx.fillStyle = `rgba(0,0,0,${0.08 + t * 0.12})`;
      ctx.fillRect(0, 0, w, h);

      ctx.font = `${fontSize}px monospace`;

      for (let i = 0; i < cols; i++) {
        const char = RAIN_CHARS[Math.floor(Math.random() * RAIN_CHARS.length)];
        const x = i * fontSize;
        const y = drops[i] * fontSize;

        // Head character — bright accent
        ctx.fillStyle = `rgba(${rgb.r},${rgb.g},${rgb.b},1)`;
        ctx.shadowColor = accent;
        ctx.shadowBlur = 8;
        ctx.fillText(char, x, y);
        ctx.shadowBlur = 0;

        // Trail character — dimmer
        if (drops[i] > 1) {
          const trailChar = RAIN_CHARS[Math.floor(Math.random() * RAIN_CHARS.length)];
          ctx.fillStyle = `rgba(${rgb.r},${rgb.g},${rgb.b},0.35)`;
          ctx.fillText(trailChar, x, y - fontSize);
        }

        drops[i] += speeds[i];

        // Reset columns that pass the bottom
        if (y > h + 40) {
          drops[i] = -Math.random() * 8;
        }
      }

      // Progressive darkening for final fill
      if (t > 0.65) {
        const blackAlpha = (t - 0.65) / 0.35;
        ctx.fillStyle = `rgba(0,0,0,${blackAlpha * 0.6})`;
        ctx.fillRect(0, 0, w, h);
      }

      if (t < 1) {
        requestAnimationFrame(frame);
      } else {
        ctx.fillStyle = 'rgba(0,0,0,1)';
        ctx.fillRect(0, 0, w, h);
        emitTransitionEvent('mid', { style: 'digital_rain' });
        cb();
        setTimeout(() => removeOverlay(canvas), 50);
      }
    }
    requestAnimationFrame(frame);
  }

  // ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
  //  EFFECT: Circuit Trace
  // ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
  function circuitTrace(cb, originX, originY) {
    const canvas = createCanvas();
    const ctx = canvas.getContext('2d');
    const w = canvas.width, h = canvas.height;
    const accent = getAccentColor();
    const rgb = hexToRgb(accent);
    const cx = typeof originX === 'number' ? originX : w / 2;
    const cy = typeof originY === 'number' ? originY : h / 2;
    const maxRadius = Math.sqrt(w * w + h * h);
    const start = performance.now();
    const dur = TRANSITION_MS;

    // Pre-generate circuit node positions
    const nodes = [];
    const spacing = 40;
    for (let x = 0; x < w; x += spacing) {
      for (let y = 0; y < h; y += spacing) {
        const jx = x + (Math.random() - 0.5) * 12;
        const jy = y + (Math.random() - 0.5) * 12;
        const dist = Math.sqrt((jx - cx) ** 2 + (jy - cy) ** 2);
        nodes.push({ x: jx, y: jy, dist });
      }
    }
    nodes.sort((a, b) => a.dist - b.dist);

    emitTransitionEvent('start', { style: 'circuit' });

    function frame(now) {
      const t = Math.min((now - start) / dur, 1);
      const eased = 1 - Math.pow(1 - t, 3);
      const radius = eased * maxRadius;
      ctx.clearRect(0, 0, w, h);

      // Dark background fill following the radius
      ctx.fillStyle = `rgba(0,0,0,${0.85 * eased})`;
      ctx.fillRect(0, 0, w, h);

      // Draw circuit traces for nodes within radius
      ctx.lineWidth = 1.5;
      const activeNodes = nodes.filter(n => n.dist < radius);

      for (let i = 0; i < activeNodes.length; i++) {
        const node = activeNodes[i];
        const nearEdge = Math.abs(node.dist - radius) < 60;
        const alpha = nearEdge ? 0.9 : 0.25;

        // Node dot
        ctx.fillStyle = `rgba(${rgb.r},${rgb.g},${rgb.b},${alpha})`;
        ctx.beginPath();
        ctx.arc(node.x, node.y, nearEdge ? 2.5 : 1.5, 0, Math.PI * 2);
        ctx.fill();

        // Trace lines to nearby nodes (orthogonal circuit style)
        if (i > 0 && Math.random() < 0.3) {
          const prev = activeNodes[Math.max(0, i - 1 - Math.floor(Math.random() * 3))];
          ctx.strokeStyle = `rgba(${rgb.r},${rgb.g},${rgb.b},${alpha * 0.5})`;
          ctx.beginPath();
          ctx.moveTo(node.x, node.y);
          // Orthogonal path: horizontal then vertical
          if (Math.random() < 0.5) {
            ctx.lineTo(prev.x, node.y);
            ctx.lineTo(prev.x, prev.y);
          } else {
            ctx.lineTo(node.x, prev.y);
            ctx.lineTo(prev.x, prev.y);
          }
          ctx.stroke();
        }
      }

      // Expanding ring at the frontier
      if (t < 0.9) {
        ctx.strokeStyle = accent;
        ctx.shadowColor = accent;
        ctx.shadowBlur = 15;
        ctx.lineWidth = 2;
        ctx.beginPath();
        ctx.arc(cx, cy, radius, 0, Math.PI * 2);
        ctx.stroke();
        ctx.shadowBlur = 0;
      }

      // Final blackout
      if (t > 0.8) {
        const fade = (t - 0.8) / 0.2;
        ctx.fillStyle = `rgba(0,0,0,${fade})`;
        ctx.fillRect(0, 0, w, h);
      }

      if (t < 1) {
        requestAnimationFrame(frame);
      } else {
        emitTransitionEvent('mid', { style: 'circuit' });
        cb();
        setTimeout(() => removeOverlay(canvas), 50);
      }
    }
    requestAnimationFrame(frame);
  }

  // ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
  //  EFFECT: Hex Grid
  // ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
  function hexGrid(cb) {
    const container = createOverlay('div');
    const w = window.innerWidth, h = window.innerHeight;
    const accent = getAccentColor();
    const hexSize = 48;
    const hexW = hexSize * 2;
    const hexH = Math.sqrt(3) * hexSize;
    const cols = Math.ceil(w / (hexW * 0.75)) + 2;
    const rows = Math.ceil(h / hexH) + 2;
    const cx = w / 2, cy = h / 2;
    container.style.background = 'transparent';
    container.style.overflow = 'hidden';
    container.style.perspective = '800px';

    const hexElements = [];
    const dur = TRANSITION_MS;

    emitTransitionEvent('start', { style: 'hex_grid' });

    for (let col = 0; col < cols; col++) {
      for (let row = 0; row < rows; row++) {
        const x = col * hexW * 0.75;
        const y = row * hexH + (col % 2 ? hexH / 2 : 0);
        const dist = Math.sqrt((x - cx) ** 2 + (y - cy) ** 2);

        const hex = document.createElement('div');
        const delay = (dist / Math.sqrt(cx * cx + cy * cy)) * dur * 0.6;
        const flipDur = dur * 0.4;

        hex.style.cssText = `
          position:absolute;
          left:${x - hexSize}px; top:${y - hexSize}px;
          width:${hexSize * 2}px; height:${hexSize * 2}px;
          clip-path: polygon(50% 0%, 100% 25%, 100% 75%, 50% 100%, 0% 75%, 0% 25%);
          background: rgba(0,0,0,0);
          transform-origin: center;
          will-change: transform, background;
          transition: none;
        `;

        container.appendChild(hex);
        hexElements.push({ el: hex, delay, flipDur });
      }
    }

    // Trigger hex flips with staggered delays
    requestAnimationFrame(() => {
      hexElements.forEach(({ el, delay, flipDur }) => {
        setTimeout(() => {
          el.style.transition = `background ${flipDur}ms ease, transform ${flipDur}ms ease`;
          el.style.background = `rgba(0,0,0,0.95)`;
          el.style.borderColor = accent;
          el.style.animation = `cs-hex-flip ${flipDur}ms ease forwards`;
        }, delay);
      });
    });

    // After all hexes have flipped, fill black and navigate
    const totalTime = dur + 80;
    setTimeout(() => {
      container.style.background = '#000';
      emitTransitionEvent('mid', { style: 'hex_grid' });
      cb();
      setTimeout(() => removeOverlay(container), 50);
    }, totalTime);
  }

  // ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
  //  EFFECT DISPATCHER
  // ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
  function runTransition(style, cb, clickX, clickY) {
    switch (style) {
      case 'glitch':       return glitchDissolve(cb);
      case 'neon_wipe':    return neonWipe(cb);
      case 'digital_rain': return digitalRain(cb);
      case 'circuit':      return circuitTrace(cb, clickX, clickY);
      case 'hex_grid':     return hexGrid(cb);
      default:             return glitchDissolve(cb);
    }
  }

  // ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
  //  ENTRY ANIMATION — materialize from noise
  // ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
  function playEntryAnimation() {
    if (_entryPlayed) return;
    _entryPlayed = true;

    const canvas = createCanvas();
    const ctx = canvas.getContext('2d');
    const w = canvas.width, h = canvas.height;
    const accent = hexToRgb(getAccentColor());
    const start = performance.now();

    // Start with full noise coverage
    emitTransitionEvent('entry_start', { style: 'materialize' });

    function frame(now) {
      const t = Math.min((now - start) / ENTRY_MS, 1);
      // Ease out — fast start, smooth finish
      const eased = 1 - Math.pow(1 - t, 2.5);

      ctx.clearRect(0, 0, w, h);

      // Noise that fades out
      const remaining = 1 - eased;
      if (remaining > 0.01) {
        const noise = ctx.createImageData(w, h);
        const d = noise.data;
        const pixelDensity = remaining * 0.5;
        for (let i = 0; i < d.length; i += 4) {
          if (Math.random() < pixelDensity) {
            const bright = Math.random() < 0.15;
            d[i] = bright ? accent.r : Math.floor(Math.random() * 60);
            d[i + 1] = bright ? accent.g : Math.floor(Math.random() * 60);
            d[i + 2] = bright ? accent.b : Math.floor(Math.random() * 60);
            d[i + 3] = Math.floor(remaining * 200);
          }
        }
        ctx.putImageData(noise, 0, 0);

        // Scanlines
        ctx.fillStyle = `rgba(0,0,0,${remaining * 0.1})`;
        for (let y = 0; y < h; y += 3) {
          ctx.fillRect(0, y, w, 1);
        }
      }

      if (t < 1) {
        requestAnimationFrame(frame);
      } else {
        removeOverlay(canvas);
        emitTransitionEvent('entry_end', { style: 'materialize' });
      }
    }
    requestAnimationFrame(frame);

    // Also add CSS class for body-level animation
    document.body.classList.add('cs-page-materialize');
    setTimeout(() => document.body.classList.remove('cs-page-materialize'), ENTRY_MS + 50);
  }

  // ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
  //  NAVIGATION HANDLER
  // ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
  function navigateTo(href, styleOverride, clickX, clickY) {
    if (_transitioning) return;
    if (!href || href.startsWith('#') || href.startsWith('javascript:')) return;

    // Same-page link guard
    const target = new URL(href, window.location.href);
    if (target.href === window.location.href) return;

    _transitioning = true;
    const style = resolveStyle(styleOverride);

    document.body.classList.add('cs-page-exit');
    emitTransitionEvent('navigate', { style, href });

    runTransition(style, function () {
      emitTransitionEvent('end', { style, href });
      window.location.href = href;
    }, clickX, clickY);
  }

  // ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
  //  INIT
  // ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
  function init() {
    injectStyles();
    playEntryAnimation();

    // Intercept all [data-scene-nav] link clicks
    document.addEventListener('click', function (e) {
      const link = e.target.closest('[data-scene-nav]');
      if (!link) return;

      const href = link.getAttribute('href');
      e.preventDefault();
      navigateTo(href, null, e.clientX, e.clientY);
    });
  }

  // ── Boot ───────────────────────────────────────────────────────────────────
  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', init);
  } else {
    init();
  }

  // ── Public API ─────────────────────────────────────────────────────────────
  window.CosyTransitions = {
    setStyle: function (name) {
      if (name === 'random' || STYLES.includes(name)) {
        _activeStyle = name;
      }
    },
    getStyles: function () {
      return STYLES.slice();
    },
    navigate: function (url, style) {
      navigateTo(url, style);
    }
  };
})();
