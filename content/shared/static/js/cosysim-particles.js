/**
 * CosySim Unified Particle Engine
 * Auto-starts on DOMContentLoaded if window.SCENE_PARTICLE_CONFIG is set.
 * Falls back to preset lookup via document.body.dataset.scene.
 *
 * Usage:
 *   <canvas id="cs-particles"></canvas>
 *   <script src="/static/js/cosysim-particles.js"></script>
 *
 *   Optional — set before script loads:
 *     window.SCENE_PARTICLE_CONFIG = { effect: 'float', color: '#8b5cf6', count: 40, speed: 0.3 }
 *
 *   Or set scene via body data attribute:
 *     <body data-scene="tavern">
 *
 * Scene configs:
 *   bedroom:  { effect: 'float',     color: '#8b5cf6', count: 40,  speed: 0.3  }
 *   phone:    { effect: 'signal',    color: '#22d3ee', count: 30,  speed: 1.5  }
 *   lounge:   { effect: 'smoke',     color: '#a3a3a3', count: 60,  speed: 0.2  }
 *   tavern:   { effect: 'ember',     color: '#f97316', count: 50,  speed: 0.8  }
 *   casino:   { effect: 'glint',     color: '#f59e0b', count: 35,  speed: 0.5  }
 *   gallery:  { effect: 'ink',       color: '#6366f1', count: 25,  speed: 0.15 }
 *   arena:    { effect: 'blood',     color: '#dc2626', count: 80,  speed: 0.6  }
 *   realm:    { effect: 'energy',    color: '#7c3aed', count: 45,  speed: 0.4  }
 *   neoncity: { effect: 'neon_rain', color: '#06b6d4', count: 100, speed: 2.0  }
 */

'use strict';

// ──── Scene Presets ────

const PARTICLE_PRESETS = {
  bedroom:  { count: 40,  color: '#8b5cf6', effect: 'float',     size: 2, speed: 0.3,  opacity: 0.5  },
  phone:    { count: 30,  color: '#22d3ee', effect: 'signal',    size: 1, speed: 1.5,  opacity: 0.4  },
  lounge:   { count: 60,  color: '#a3a3a3', effect: 'smoke',     size: 5, speed: 0.2,  opacity: 0.3  },
  tavern:   { count: 50,  color: '#f97316', effect: 'ember',     size: 2, speed: 0.8,  opacity: 0.8  },
  casino:   { count: 35,  color: '#f59e0b', effect: 'glint',     size: 1, speed: 0.5,  opacity: 0.9  },
  gallery:  { count: 25,  color: '#6366f1', effect: 'ink',       size: 4, speed: 0.15, opacity: 0.25 },
  arena:    { count: 80,  color: '#dc2626', effect: 'blood',     size: 2, speed: 0.6,  opacity: 0.7  },
  realm:    { count: 45,  color: '#7c3aed', effect: 'energy',    size: 2, speed: 0.4,  opacity: 0.6  },
  neoncity: { count: 100, color: '#06b6d4', effect: 'neon_rain', size: 1, speed: 2.0,  opacity: 0.5  },
};

// ──── Helpers ────

function hexToRgb(hex) {
  const clean = hex.replace('#', '');
  const int = parseInt(clean.length === 3
    ? clean.split('').map(c => c + c).join('')
    : clean, 16);
  return { r: (int >> 16) & 255, g: (int >> 8) & 255, b: int & 255 };
}

function rand(min, max) {
  return min + Math.random() * (max - min);
}

function randInt(min, max) {
  return Math.floor(rand(min, max + 1));
}

// ──── ParticleEngine ────

class ParticleEngine {
  /**
   * @param {HTMLCanvasElement} [canvas]
   * @param {Object} [config]  - { count, color, effect, size, speed, opacity }
   */
  constructor(canvas, config) {
    this._canvas = null;
    this._ctx = null;
    this._config = {};
    this._particles = [];
    this._raf = null;
    this._running = false;
    this._rgb = { r: 139, g: 92, b: 246 };
    this._w = 0;
    this._h = 0;
    this._resizeObserver = null;

    if (canvas) {
      this.init(canvas, config || {});
    }
  }

  /**
   * Initialise (or re-initialise) the engine with a canvas and config.
   * @param {HTMLCanvasElement} canvas
   * @param {Object} config  - { count, color, effect, size, speed, opacity }
   * @returns {ParticleEngine} this
   */
  init(canvas, config) {
    if (this._resizeObserver) {
      this._resizeObserver.disconnect();
    }

    this._canvas = canvas;
    this._ctx = canvas.getContext('2d');
    this._config = Object.assign(
      { count: 40, color: '#8b5cf6', effect: 'float', size: 2, speed: 0.3, opacity: 0.6 },
      config
    );
    this._rgb = hexToRgb(this._config.color);

    this._applyCanvasStyle();
    this.resize();

    this._resizeObserver = new ResizeObserver(() => this.resize());
    this._resizeObserver.observe(document.documentElement);

    return this;
  }

  _applyCanvasStyle() {
    const s = this._canvas.style;
    s.position = 'fixed';
    s.top = '0';
    s.left = '0';
    s.width = '100vw';
    s.height = '100vh';
    s.zIndex = '0';
    s.pointerEvents = 'none';
  }

  /** Synchronise canvas pixel dimensions to the viewport. */
  resize() {
    this._canvas.width = window.innerWidth;
    this._canvas.height = window.innerHeight;
    this._w = this._canvas.width;
    this._h = this._canvas.height;
    // Respawn all particles so they cover the new dimensions immediately.
    this._particles = [];
    for (let i = 0; i < this._config.count; i++) {
      this._particles.push(this._spawnParticle(true));
    }
  }

  start() {
    if (this._running) return;
    this._running = true;
    this._tick();
  }

  stop() {
    this._running = false;
    if (this._raf !== null) {
      cancelAnimationFrame(this._raf);
      this._raf = null;
    }
  }

  _tick() {
    if (!this._running) return;
    this._raf = requestAnimationFrame(() => this._tick());

    const ctx = this._ctx;
    ctx.clearRect(0, 0, this._w, this._h);

    for (let i = 0; i < this._particles.length; i++) {
      const p = this._particles[i];
      this._updateParticle(p);
      this._drawParticle(ctx, p);

      // Respawn dead particles.
      if (p.dead) {
        this._particles[i] = this._spawnParticle(false);
      }
    }
  }

  // ──── Spawn ────

  /**
   * Create a fresh particle.  When `spread` is true the particle is
   * placed anywhere in the canvas (used for initial fill on resize);
   * otherwise it spawns at its natural entry point.
   */
  _spawnParticle(spread = false) {
    const { effect, size, speed, opacity } = this._config;
    const w = this._w, h = this._h;

    // Base template — each effect populates what it needs.
    const p = {
      x: 0, y: 0,
      vx: 0, vy: 0,
      radius: size * rand(0.6, 1.6),
      alpha: 0,
      targetAlpha: opacity * rand(0.7, 1.0),
      age: 0,
      maxAge: 0,
      phase: rand(0, Math.PI * 2),  // for oscillations
      dead: false,
      // effect-specific extras
      extra: {},
    };

    switch (effect) {
      case 'float':
        p.x = spread ? rand(0, w) : rand(0, w);
        p.y = spread ? rand(0, h) : h + p.radius;
        p.vy = -speed * rand(0.4, 1.0);
        p.maxAge = rand(120, 300);
        p.alpha = spread ? opacity * rand(0.2, 0.8) : 0;
        break;

      case 'smoke':
        p.x = spread ? rand(0, w) : rand(w * 0.1, w * 0.9);
        p.y = spread ? rand(0, h) : h + p.radius;
        p.vy = -speed * rand(0.3, 0.7);
        p.vx = rand(-0.2, 0.2) * speed;
        p.radius = size * rand(1.5, 3.5);
        p.maxAge = rand(200, 400);
        p.alpha = spread ? opacity * rand(0.1, 0.5) : 0;
        p.extra.growRate = rand(0.008, 0.02);
        break;

      case 'ember':
        p.x = spread ? rand(0, w) : rand(0, w);
        p.y = spread ? rand(0, h) : h + p.radius;
        p.vy = -speed * rand(0.6, 1.8);
        p.vx = rand(-0.8, 0.8) * speed;
        p.maxAge = rand(80, 200);
        p.alpha = spread ? opacity * rand(0.3, 1.0) : 0;
        p.extra.flickerRate = rand(0.12, 0.28);
        p.extra.arc = rand(-0.015, 0.015);
        break;

      case 'glint':
        p.x = spread ? rand(0, w) : rand(0, w);
        p.y = spread ? rand(0, h) : rand(0, h);
        p.maxAge = rand(30, 90);
        p.radius = size * rand(0.5, 1.8);
        p.alpha = 0;
        p.extra.peakAge = Math.floor(p.maxAge * rand(0.3, 0.6));
        break;

      case 'ink':
        p.x = spread ? rand(0, w) : rand(w * 0.15, w * 0.85);
        p.y = spread ? rand(0, h) : rand(h * 0.2, h * 0.8);
        p.vx = rand(-0.25, 0.25) * speed;
        p.vy = rand(-0.1, 0.1) * speed;
        p.radius = size * rand(2, 5);
        p.maxAge = rand(250, 500);
        p.alpha = 0;
        p.extra.growRate = rand(0.003, 0.01);
        break;

      case 'blood':
        p.x = spread ? rand(0, w) : rand(0, w);
        p.y = spread ? rand(0, h) : -p.radius;
        p.vy = speed * rand(2.0, 4.5);
        p.vx = rand(-0.3, 0.3) * speed;
        p.maxAge = rand(60, 140);
        p.alpha = opacity * rand(0.7, 1.0);
        p.extra.drag = rand(0.96, 0.99);
        break;

      case 'energy':
        {
          // Spawn from a point near-centre then radiate outward.
          const angle = rand(0, Math.PI * 2);
          const cx = w / 2, cy = h / 2;
          const dist = rand(0, Math.min(w, h) * 0.08);
          p.x = spread ? rand(0, w) : cx + Math.cos(angle) * dist;
          p.y = spread ? rand(0, h) : cy + Math.sin(angle) * dist;
          const spd = speed * rand(0.8, 2.0);
          p.vx = Math.cos(angle) * spd;
          p.vy = Math.sin(angle) * spd;
          p.maxAge = rand(50, 130);
          p.alpha = spread ? opacity * rand(0.2, 0.9) : opacity;
          p.extra.angle = angle;
          p.extra.cx = cx;
          p.extra.cy = cy;
          break;
        }

      case 'neon_rain':
        p.x = spread ? rand(0, w) : rand(0, w);
        p.y = spread ? rand(0, h) : -rand(10, h * 0.5);
        p.vy = speed * rand(8, 16);
        p.vx = rand(-0.5, 0.5);
        p.radius = size;
        p.maxAge = rand(40, 120);
        p.alpha = opacity * rand(0.5, 1.0);
        p.extra.len = rand(6, 20);
        break;

      case 'signal':
        p.x = rand(0, w);
        p.y = rand(0, h);
        p.maxAge = randInt(4, 18);
        p.alpha = opacity * rand(0.4, 1.0);
        p.radius = size * rand(0.5, 1.2);
        break;

      default:
        // Fallback to float
        p.x = rand(0, w);
        p.y = spread ? rand(0, h) : h + p.radius;
        p.vy = -speed * rand(0.4, 1.0);
        p.maxAge = rand(120, 300);
        p.alpha = spread ? opacity * rand(0.2, 0.8) : 0;
    }

    return p;
  }

  // ──── Update ────

  _updateParticle(p) {
    const { effect, speed, opacity } = this._config;
    const w = this._w, h = this._h;
    p.age++;

    switch (effect) {
      case 'float': {
        const progress = p.age / p.maxAge;
        // Sine horizontal wobble
        p.x += Math.sin(p.age * 0.04 + p.phase) * 0.5;
        p.y += p.vy;
        // Fade in during first 20%, fade out during last 20%
        if (progress < 0.2) {
          p.alpha = p.targetAlpha * (progress / 0.2);
        } else if (progress > 0.8) {
          p.alpha = p.targetAlpha * ((1 - progress) / 0.2);
        } else {
          p.alpha = p.targetAlpha;
        }
        if (p.age >= p.maxAge || p.y < -p.radius) p.dead = true;
        break;
      }

      case 'smoke': {
        const progress = p.age / p.maxAge;
        p.x += p.vx + Math.sin(p.age * 0.02 + p.phase) * 0.3;
        p.y += p.vy;
        p.radius += p.extra.growRate * p.radius;
        if (progress < 0.25) {
          p.alpha = p.targetAlpha * (progress / 0.25);
        } else if (progress > 0.65) {
          p.alpha = p.targetAlpha * ((1 - progress) / 0.35);
        } else {
          p.alpha = p.targetAlpha;
        }
        if (p.age >= p.maxAge || p.y < -p.radius * 2) p.dead = true;
        break;
      }

      case 'ember': {
        // Arc trajectory
        p.vx += p.extra.arc;
        p.vy += 0.012 * speed;  // slight gravity pull
        p.x += p.vx;
        p.y += p.vy;
        // Flicker
        p.alpha = p.targetAlpha * (0.5 + 0.5 * Math.sin(p.age * p.extra.flickerRate + p.phase));
        if (p.age >= p.maxAge || p.y < -p.radius || p.x < -10 || p.x > w + 10) p.dead = true;
        break;
      }

      case 'glint': {
        // Appear, peak, then fade
        if (p.age < p.extra.peakAge) {
          p.alpha = p.targetAlpha * (p.age / p.extra.peakAge);
        } else {
          p.alpha = p.targetAlpha * (1 - (p.age - p.extra.peakAge) / (p.maxAge - p.extra.peakAge));
        }
        if (p.age >= p.maxAge) p.dead = true;
        break;
      }

      case 'ink': {
        const progress = p.age / p.maxAge;
        p.x += p.vx;
        p.y += p.vy;
        p.radius += p.extra.growRate * p.radius;
        if (progress < 0.15) {
          p.alpha = p.targetAlpha * (progress / 0.15);
        } else if (progress > 0.6) {
          p.alpha = p.targetAlpha * ((1 - progress) / 0.4);
        } else {
          p.alpha = p.targetAlpha;
        }
        if (p.age >= p.maxAge) p.dead = true;
        break;
      }

      case 'blood': {
        p.vy *= p.extra.drag;
        p.x += p.vx;
        p.y += p.vy;
        // Slight elongation handled in draw; alpha stays high then drops fast
        if (p.age > p.maxAge * 0.7) {
          const tail = (p.age - p.maxAge * 0.7) / (p.maxAge * 0.3);
          p.alpha = p.targetAlpha * (1 - tail);
        }
        if (p.age >= p.maxAge || p.y > h + p.radius) p.dead = true;
        break;
      }

      case 'energy': {
        const progress = p.age / p.maxAge;
        p.x += p.vx;
        p.y += p.vy;
        // Speed up slightly
        p.vx *= 1.015;
        p.vy *= 1.015;
        p.alpha = p.targetAlpha * (1 - progress);
        if (p.age >= p.maxAge || p.x < -20 || p.x > w + 20 || p.y < -20 || p.y > h + 20) p.dead = true;
        break;
      }

      case 'neon_rain': {
        p.x += p.vx;
        p.y += p.vy;
        if (p.age >= p.maxAge || p.y > h + p.extra.len) p.dead = true;
        break;
      }

      case 'signal': {
        // Stationary static noise — just counts age
        if (p.age >= p.maxAge) p.dead = true;
        break;
      }

      default:
        p.y += p.vy;
        if (p.age >= p.maxAge || p.y < -p.radius) p.dead = true;
    }
  }

  // ──── Draw ────

  _drawParticle(ctx, p) {
    const { effect } = this._config;
    const { r, g, b } = this._rgb;
    const alpha = Math.max(0, Math.min(1, p.alpha));
    if (alpha <= 0) return;

    ctx.save();

    switch (effect) {
      case 'float': {
        const grad = ctx.createRadialGradient(p.x, p.y, 0, p.x, p.y, p.radius);
        grad.addColorStop(0, `rgba(${r},${g},${b},${alpha})`);
        grad.addColorStop(1, `rgba(${r},${g},${b},0)`);
        ctx.fillStyle = grad;
        ctx.beginPath();
        ctx.arc(p.x, p.y, p.radius, 0, Math.PI * 2);
        ctx.fill();
        break;
      }

      case 'smoke': {
        const grad = ctx.createRadialGradient(p.x, p.y, 0, p.x, p.y, p.radius);
        grad.addColorStop(0,   `rgba(${r},${g},${b},${alpha * 0.6})`);
        grad.addColorStop(0.5, `rgba(${r},${g},${b},${alpha * 0.25})`);
        grad.addColorStop(1,   `rgba(${r},${g},${b},0)`);
        ctx.fillStyle = grad;
        ctx.beginPath();
        ctx.arc(p.x, p.y, p.radius, 0, Math.PI * 2);
        ctx.fill();
        break;
      }

      case 'ember': {
        // Bright core with glow
        ctx.shadowColor = `rgb(${r},${g},${b})`;
        ctx.shadowBlur = p.radius * 3;
        ctx.fillStyle = `rgba(255,220,100,${alpha})`;
        ctx.beginPath();
        ctx.arc(p.x, p.y, p.radius * 0.6, 0, Math.PI * 2);
        ctx.fill();
        // Outer ember colour
        ctx.shadowBlur = 0;
        ctx.fillStyle = `rgba(${r},${g},${b},${alpha * 0.5})`;
        ctx.beginPath();
        ctx.arc(p.x, p.y, p.radius, 0, Math.PI * 2);
        ctx.fill();
        break;
      }

      case 'glint': {
        // Star burst: four lines + central dot
        ctx.strokeStyle = `rgba(${r},${g},${b},${alpha})`;
        ctx.lineWidth = p.radius * 0.5;
        ctx.shadowColor = `rgba(${r},${g},${b},${alpha})`;
        ctx.shadowBlur = p.radius * 4;
        const len = p.radius * 3;
        for (let a = 0; a < Math.PI; a += Math.PI / 2) {
          ctx.beginPath();
          ctx.moveTo(p.x - Math.cos(a) * len, p.y - Math.sin(a) * len);
          ctx.lineTo(p.x + Math.cos(a) * len, p.y + Math.sin(a) * len);
          ctx.stroke();
        }
        ctx.shadowBlur = 0;
        ctx.fillStyle = `rgba(255,255,255,${alpha})`;
        ctx.beginPath();
        ctx.arc(p.x, p.y, p.radius * 0.8, 0, Math.PI * 2);
        ctx.fill();
        break;
      }

      case 'ink': {
        // Irregular blob — approximate with scaled ellipse
        const rx = p.radius;
        const ry = p.radius * rand(0.6, 1.0);
        ctx.fillStyle = `rgba(${r},${g},${b},${alpha})`;
        ctx.beginPath();
        ctx.ellipse(p.x, p.y, rx, ry, p.phase, 0, Math.PI * 2);
        ctx.fill();
        break;
      }

      case 'blood': {
        // Elongated teardrop — tall ellipse
        ctx.fillStyle = `rgba(${r},${g},${b},${alpha})`;
        ctx.beginPath();
        ctx.ellipse(p.x, p.y, p.radius * 0.5, p.radius * 1.4, 0, 0, Math.PI * 2);
        ctx.fill();
        break;
      }

      case 'energy': {
        // Dot with electric glow
        ctx.shadowColor = `rgba(${r},${g},${b},${alpha})`;
        ctx.shadowBlur = p.radius * 5;
        ctx.fillStyle = `rgba(${r},${g},${b},${alpha})`;
        ctx.beginPath();
        ctx.arc(p.x, p.y, p.radius, 0, Math.PI * 2);
        ctx.fill();
        ctx.shadowBlur = 0;
        break;
      }

      case 'neon_rain': {
        // Thin vertical streak with neon glow
        ctx.shadowColor = `rgba(${r},${g},${b},${alpha})`;
        ctx.shadowBlur = 4;
        ctx.strokeStyle = `rgba(${r},${g},${b},${alpha})`;
        ctx.lineWidth = p.radius * 0.6;
        ctx.lineCap = 'round';
        ctx.beginPath();
        ctx.moveTo(p.x, p.y);
        ctx.lineTo(p.x + p.vx * 2, p.y - p.extra.len);
        ctx.stroke();
        ctx.shadowBlur = 0;
        break;
      }

      case 'signal': {
        // Single pixel / tiny rectangle noise — rapid static
        ctx.fillStyle = `rgba(${r},${g},${b},${alpha})`;
        ctx.fillRect(
          p.x - p.radius * 0.5,
          p.y - p.radius * 0.5,
          p.radius,
          p.radius
        );
        break;
      }

      default: {
        ctx.fillStyle = `rgba(${r},${g},${b},${alpha})`;
        ctx.beginPath();
        ctx.arc(p.x, p.y, p.radius, 0, Math.PI * 2);
        ctx.fill();
      }
    }

    ctx.restore();
  }
}

// ──── Expose globally ────

window.ParticleEngine = ParticleEngine;

// ──── Auto-init on DOMContentLoaded ────

document.addEventListener('DOMContentLoaded', () => {
  const canvas = document.getElementById('cs-particles');
  if (!canvas) return;

  const scene = document.body ? document.body.dataset.scene : null;
  const config = window.SCENE_PARTICLE_CONFIG
    || (scene && PARTICLE_PRESETS[scene])
    || PARTICLE_PRESETS.bedroom;

  window.particleEngine = new ParticleEngine(canvas, config);
  window.particleEngine.start();
});
