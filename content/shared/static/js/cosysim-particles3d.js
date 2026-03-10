/**
 * CosySim 3D Particle System — v0.68 "Dark Renaissance"
 * ======================================================
 * Full volumetric Three.js particle system using InstancedMesh.
 * 10,000+ particles at 60fps target.
 *
 * Usage:
 *   const ps = new ParticleSystem3D(container, 'neon_rain');
 *   ps.start();
 *   // later:
 *   ps.setPreset('rose_petals');
 *   ps.stop();
 *   ps.destroy();
 *
 * Presets:
 *   neon_rain       — vertical cyan/blue neon streaks (NeonCity, Penthouse)
 *   rose_petals     — 3D spinning petals with physics (penthouse romantic)
 *   champagne       — rising bubbles with shimmer (celebration)
 *   embers          — fire sparks drifting upward (Tavern, Heist)
 *   sparks          — burst celebration (Casino, Arena win)
 *   matrix_code     — falling green character columns (Admin/Nexus loft)
 *   smoke           — volumetric smoke rings (Lounge, Tavern)
 *   card_shards     — Arena spell destruction shattering
 *   hologram_static — NeonCity holographic glitch fragments
 *   blood_mist      — Arena/combat red volumetric fog
 *   neon_dust       — ambient floating pixels (NeonCity streets)
 *   data_stream     — fast horizontal data lines (Intel Hub)
 */

(function (root, factory) {
  if (typeof module !== 'undefined' && module.exports) {
    module.exports = factory();
  } else {
    root.ParticleSystem3D = factory();
  }
}(typeof self !== 'undefined' ? self : this, function () {
  'use strict';

  // ── Preset Definitions ───────────────────────────────────────────────────

  const PRESETS = {

    neon_rain: {
      count: 2500,
      color: [0x00e5ff, 0x0088ff, 0x00a8ff],
      size: { min: 0.04, max: 0.12 },
      velocity: { x: [-0.02, 0.02], y: [-3.0, -1.5], z: [-0.1, 0.1] },
      spawn: { x: [-8, 8], y: [6, 10], z: [-4, 4] },
      wrap: true,
      wrapY: -8,
      opacity: { min: 0.3, max: 0.9 },
      emissive: true,
      elongated: { axis: 'y', scale: 8 },
      bloom: 0.8,
    },

    rose_petals: {
      count: 400,
      color: [0xff6b9d, 0xff85a1, 0xffb3c6, 0xe91e8c],
      size: { min: 0.1, max: 0.25 },
      velocity: { x: [-0.15, 0.15], y: [-0.4, 0.1], z: [-0.1, 0.1] },
      spawn: { x: [-5, 5], y: [3, 8], z: [-2, 2] },
      wrap: true,
      wrapY: -6,
      rotation: { x: [-0.02, 0.02], y: [-0.03, 0.03], z: [-0.02, 0.02] },
      opacity: { min: 0.5, max: 0.95 },
      disc: true,
    },

    champagne: {
      count: 800,
      color: [0xffd700, 0xffecb3, 0xfff9c4, 0xffeb3b],
      size: { min: 0.03, max: 0.08 },
      velocity: { x: [-0.05, 0.05], y: [0.5, 1.5], z: [-0.05, 0.05] },
      spawn: { x: [-1, 1], y: [-3, -5], z: [-0.5, 0.5] },
      wrap: true,
      wrapY: 8,
      wobble: { x: 0.3, frequency: 0.8 },
      opacity: { min: 0.4, max: 0.9 },
      emissive: true,
      fadeTop: true,
    },

    embers: {
      count: 600,
      color: [0xff6b35, 0xff8c00, 0xffd700, 0xff4500],
      size: { min: 0.04, max: 0.10 },
      velocity: { x: [-0.2, 0.2], y: [0.3, 1.2], z: [-0.2, 0.2] },
      spawn: { x: [-1.5, 1.5], y: [-4, -3], z: [-0.5, 0.5] },
      wrap: false,
      lifespan: { min: 2.0, max: 5.0 },
      wobble: { x: 0.5, frequency: 1.2 },
      opacity: { min: 0.6, max: 1.0 },
      emissive: true,
      fadeOut: true,
      gravity: -0.02,
    },

    sparks: {
      count: 1200,
      color: [0xffff00, 0xffaa00, 0xffd700, 0xffffff],
      size: { min: 0.03, max: 0.09 },
      velocity: { x: [-2.0, 2.0], y: [0.5, 3.0], z: [-1.0, 1.0] },
      spawn: { x: [-0.5, 0.5], y: [0, 1], z: [-0.5, 0.5] },
      wrap: false,
      lifespan: { min: 0.5, max: 2.0 },
      gravity: 0.08,
      fadeOut: true,
      emissive: true,
      burst: true,
    },

    matrix_code: {
      count: 3000,
      color: [0x00ff41, 0x00cc33, 0x39ff14, 0x00ff00],
      size: { min: 0.06, max: 0.14 },
      velocity: { x: [0, 0], y: [-2.5, -0.8], z: [0, 0] },
      spawn: { x: [-8, 8], y: [8, 12], z: [-2, 2] },
      wrap: true,
      wrapY: -10,
      opacity: { min: 0.2, max: 0.85 },
      emissive: true,
      elongated: { axis: 'y', scale: 4 },
      columns: { enabled: true, spacing: 0.5, speedVariation: 0.6 },
      bloom: 1.2,
    },

    smoke: {
      count: 300,
      color: [0x555566, 0x444455, 0x666677, 0x333344],
      size: { min: 0.3, max: 1.2 },
      velocity: { x: [-0.05, 0.05], y: [0.15, 0.4], z: [-0.05, 0.05] },
      spawn: { x: [-3, 3], y: [-2, 0], z: [-1, 1] },
      wrap: false,
      lifespan: { min: 4.0, max: 8.0 },
      rotation: { z: [-0.008, 0.008] },
      opacity: { min: 0.0, max: 0.25 },
      fadeOut: true,
      fadeIn: true,
      grow: { rate: 0.05, max: 2.0 },
    },

    card_shards: {
      count: 500,
      color: [0x8b0000, 0xff1744, 0xffd700, 0xffffff],
      size: { min: 0.05, max: 0.18 },
      velocity: { x: [-3.0, 3.0], y: [1.0, 4.0], z: [-2.0, 2.0] },
      spawn: { x: [-0.5, 0.5], y: [0, 0.5], z: [-0.5, 0.5] },
      wrap: false,
      lifespan: { min: 1.0, max: 3.0 },
      gravity: 0.12,
      rotation: { x: [-0.1, 0.1], y: [-0.1, 0.1], z: [-0.1, 0.1] },
      fadeOut: true,
      emissive: true,
      burst: true,
    },

    hologram_static: {
      count: 1500,
      color: [0x00e5ff, 0x7c3aed, 0x06b6d4, 0x4f46e5],
      size: { min: 0.02, max: 0.08 },
      velocity: { x: [-0.5, 0.5], y: [-0.2, 0.2], z: [-0.3, 0.3] },
      spawn: { x: [-4, 4], y: [-3, 3], z: [-1, 1] },
      wrap: true,
      wrapY: null,
      glitch: { probability: 0.02, magnitude: 1.5 },
      opacity: { min: 0.1, max: 0.6 },
      emissive: true,
      flicker: { probability: 0.01, duration: 0.1 },
    },

    blood_mist: {
      count: 800,
      color: [0x8b0000, 0xb71c1c, 0x7f0000, 0x660000],
      size: { min: 0.2, max: 0.8 },
      velocity: { x: [-0.08, 0.08], y: [-0.05, 0.15], z: [-0.1, 0.1] },
      spawn: { x: [-4, 4], y: [-2, 2], z: [-2, 2] },
      wrap: false,
      lifespan: { min: 3.0, max: 7.0 },
      opacity: { min: 0.0, max: 0.35 },
      fadeIn: true,
      fadeOut: true,
      grow: { rate: 0.03, max: 1.5 },
      rotation: { z: [-0.005, 0.005] },
    },

    neon_dust: {
      count: 1200,
      color: [0x00a8ff, 0xff006e, 0x00e5ff, 0xffab00, 0x39ff14],
      size: { min: 0.02, max: 0.05 },
      velocity: { x: [-0.08, 0.08], y: [-0.05, 0.05], z: [-0.03, 0.03] },
      spawn: { x: [-7, 7], y: [-4, 4], z: [-2, 2] },
      wrap: true,
      wrapY: null,
      wobble: { x: 0.15, y: 0.15, frequency: 0.3 },
      opacity: { min: 0.2, max: 0.7 },
      emissive: true,
      multicolor: true,
    },

    data_stream: {
      count: 600,
      color: [0x00e5ff, 0x22c55e, 0x06b6d4, 0x4ade80],
      size: { min: 0.04, max: 0.10 },
      velocity: { x: [2.0, 5.0], y: [0, 0], z: [0, 0] },
      spawn: { x: [-12, -8], y: [-2, 2], z: [-0.5, 0.5] },
      wrap: false,
      wrapX: 12,
      lifespan: { min: 1.5, max: 4.0 },
      opacity: { min: 0.3, max: 0.8 },
      emissive: true,
      elongated: { axis: 'x', scale: 6 },
      fadeOut: true,
    },
  };

  // ── Particle System ──────────────────────────────────────────────────────

  class ParticleSystem3D {
    /**
     * Creates a new 3D particle system.
     * @param {HTMLElement} container - DOM element to render into
     * @param {string} preset - One of the preset names
     * @param {object} options - Override options
     * @param {THREE.WebGLRenderer} [options.renderer] - Existing renderer to share
     * @param {THREE.Scene} [options.scene] - Existing scene to add to
     * @param {THREE.Camera} [options.camera] - Existing camera
     * @param {boolean} [options.overlay] - Render as CSS overlay (position:absolute)
     */
    constructor(container, preset = 'neon_rain', options = {}) {
      this._container = typeof container === 'string'
        ? document.querySelector(container)
        : container;

      if (!this._container) {
        console.warn('[ParticleSystem3D] Container not found');
        return;
      }

      this._preset = preset;
      this._options = options;
      this._config = this._mergeConfig(PRESETS[preset] || PRESETS.neon_rain);
      this._running = false;
      this._frameId = null;
      this._clock = null;
      this._elapsed = 0;
      this._shared = !!(options.renderer && options.scene && options.camera);

      // Check Three.js availability
      if (typeof THREE === 'undefined') {
        this._loadThree(() => this._init());
      } else {
        this._init();
      }
    }

    // ── Lifecycle ──────────────────────────────────────────────────────────

    start() {
      if (this._running || !this._renderer) return this;
      this._running = true;
      this._clock.start();
      this._animate();
      return this;
    }

    stop() {
      this._running = false;
      if (this._frameId) {
        cancelAnimationFrame(this._frameId);
        this._frameId = null;
      }
      return this;
    }

    destroy() {
      this.stop();
      if (this._mesh) {
        this._scene.remove(this._mesh);
        this._mesh.geometry.dispose();
        this._mesh.material.dispose();
      }
      if (!this._shared && this._renderer) {
        this._renderer.dispose();
        if (this._canvas && this._canvas.parentNode) {
          this._canvas.parentNode.removeChild(this._canvas);
        }
      }
    }

    setPreset(presetName, transitionMs = 500) {
      if (!PRESETS[presetName]) {
        console.warn(`[ParticleSystem3D] Unknown preset: ${presetName}`);
        return this;
      }
      // Fade out, swap, fade in
      this._fadeOut(transitionMs / 2, () => {
        this._preset = presetName;
        this._config = this._mergeConfig(PRESETS[presetName]);
        this._reinitParticles();
        this._fadeIn(transitionMs / 2);
      });
      return this;
    }

    burst(count = 100, presetOverride = null) {
      const cfg = presetOverride
        ? this._mergeConfig(PRESETS[presetOverride] || this._config)
        : { ...this._config, burst: true, count };
      this._spawnBurst(cfg, count);
      return this;
    }

    resize() {
      if (!this._renderer || this._shared) return;
      const w = this._container.clientWidth;
      const h = this._container.clientHeight;
      this._renderer.setSize(w, h);
      if (this._camera && this._camera.aspect !== undefined) {
        this._camera.aspect = w / h;
        this._camera.updateProjectionMatrix();
      }
    }

    // ── Init ───────────────────────────────────────────────────────────────

    _init() {
      if (this._shared) {
        this._renderer = this._options.renderer;
        this._scene    = this._options.scene;
        this._camera   = this._options.camera;
        this._canvas   = null;
      } else {
        this._initRenderer();
      }

      this._clock = new THREE.Clock(false);
      this._initParticles();
      this._initResizeObserver();

      if (this._options.autoStart !== false) {
        this.start();
      }
    }

    _initRenderer() {
      const w = this._container.clientWidth || 400;
      const h = this._container.clientHeight || 300;

      this._scene = new THREE.Scene();

      this._camera = new THREE.PerspectiveCamera(60, w / h, 0.1, 1000);
      this._camera.position.set(0, 0, 10);
      this._camera.lookAt(0, 0, 0);

      this._renderer = new THREE.WebGLRenderer({
        antialias: false,
        alpha: true,
        powerPreference: 'high-performance',
      });
      this._renderer.setPixelRatio(Math.min(window.devicePixelRatio, 1.5));
      this._renderer.setSize(w, h);
      this._renderer.setClearColor(0x000000, 0);

      this._canvas = this._renderer.domElement;
      this._canvas.style.cssText =
        'position:absolute;inset:0;width:100%;height:100%;pointer-events:none;z-index:0;';
      this._container.style.position = this._container.style.position || 'relative';
      this._container.prepend(this._canvas);
    }

    _initParticles() {
      const cfg = this._config;
      const count = cfg.count;

      // Geometry: a flat quad (PlaneGeometry) per particle via InstancedMesh
      const geo = new THREE.PlaneGeometry(1, 1);
      const mat = new THREE.MeshBasicMaterial({
        color: Array.isArray(cfg.color) ? cfg.color[0] : cfg.color,
        transparent: true,
        opacity: 1.0,
        depthWrite: false,
        blending: cfg.emissive
          ? THREE.AdditiveBlending
          : THREE.NormalBlending,
        side: THREE.DoubleSide,
      });

      this._mesh = new THREE.InstancedMesh(geo, mat, count);
      this._mesh.instanceMatrix.setUsage(THREE.DynamicDrawUsage);
      this._scene.add(this._mesh);

      // Per-particle state arrays
      this._pos   = new Float32Array(count * 3);
      this._vel   = new Float32Array(count * 3);
      this._rot   = new Float32Array(count * 3); // euler x,y,z
      this._rotVel= new Float32Array(count * 3);
      this._size  = new Float32Array(count);
      this._life  = new Float32Array(count);   // current life
      this._maxLife = new Float32Array(count); // max life (or -1 for infinite)
      this._alpha = new Float32Array(count);
      this._colorIdx = new Uint8Array(count);

      // InstancedMesh color buffer
      this._colors = new THREE.InstancedBufferAttribute(
        new Float32Array(count * 3), 3
      );
      this._mesh.geometry.setAttribute('color', this._colors);

      // Instance matrix dummy
      this._dummy = new THREE.Object3D();

      this._spawnAll();
    }

    _reinitParticles() {
      if (this._mesh) {
        this._scene.remove(this._mesh);
        this._mesh.geometry.dispose();
        this._mesh.material.dispose();
      }
      this._initParticles();
    }

    _spawnAll() {
      const count = this._config.count;
      for (let i = 0; i < count; i++) {
        this._spawnParticle(i, true);
      }
      this._updateMatrix();
    }

    _spawnParticle(i, initial = false) {
      const cfg = this._config;
      const s = cfg.spawn;

      // Position
      this._pos[i*3+0] = this._rand(s.x[0], s.x[1]);
      this._pos[i*3+1] = this._rand(s.y[0], s.y[1]);
      this._pos[i*3+2] = this._rand(s.z[0], s.z[1]);

      // Velocity
      const v = cfg.velocity;
      this._vel[i*3+0] = this._rand(v.x[0], v.x[1]);
      this._vel[i*3+1] = this._rand(v.y[0], v.y[1]);
      this._vel[i*3+2] = this._rand(v.z[0], v.z[1]);

      // Rotation velocity
      if (cfg.rotation) {
        const r = cfg.rotation;
        this._rotVel[i*3+0] = r.x ? this._rand(r.x[0], r.x[1]) : 0;
        this._rotVel[i*3+1] = r.y ? this._rand(r.y[0], r.y[1]) : 0;
        this._rotVel[i*3+2] = r.z ? this._rand(r.z[0], r.z[1]) : 0;
      }

      // Initial rotation
      this._rot[i*3+0] = Math.random() * Math.PI * 2;
      this._rot[i*3+1] = Math.random() * Math.PI * 2;
      this._rot[i*3+2] = Math.random() * Math.PI * 2;

      // Size
      const sz = cfg.size;
      let baseSize = this._rand(sz.min, sz.max);
      this._size[i] = baseSize;

      // Life
      if (cfg.lifespan) {
        const lMax = this._rand(cfg.lifespan.min, cfg.lifespan.max);
        this._maxLife[i] = lMax;
        this._life[i] = initial ? Math.random() * lMax : 0;
      } else {
        this._maxLife[i] = -1;
        this._life[i] = 0;
      }

      // Alpha
      const op = cfg.opacity || { min: 0.5, max: 0.9 };
      this._alpha[i] = this._rand(op.min, op.max);

      // Color
      const colors = Array.isArray(cfg.color) ? cfg.color : [cfg.color];
      const cIdx = Math.floor(Math.random() * colors.length);
      this._colorIdx[i] = cIdx;
      this._setInstanceColor(i, colors[cIdx]);
    }

    _spawnBurst(cfg, count) {
      // Temporarily spawn count extra particles in burst position
      const geo = new THREE.PlaneGeometry(0.1, 0.1);
      const mat = new THREE.MeshBasicMaterial({
        transparent: true, depthWrite: false,
        blending: THREE.AdditiveBlending,
        color: Array.isArray(cfg.color) ? cfg.color[0] : cfg.color,
      });
      const burst = new THREE.InstancedMesh(geo, mat, count);
      this._scene.add(burst);

      const dummy = new THREE.Object3D();
      const colors = Array.isArray(cfg.color) ? cfg.color : [cfg.color];

      // Animate burst in RAF loop for 2 seconds then remove
      let elapsed = 0;
      const particles = Array.from({ length: count }, (_, i) => ({
        x: this._rand(-0.5, 0.5),
        y: this._rand(-0.5, 0.5),
        z: this._rand(-0.5, 0.5),
        vx: this._rand(-3, 3),
        vy: this._rand(0.5, 4),
        vz: this._rand(-1.5, 1.5),
        life: 0,
        maxLife: this._rand(0.5, 2.0),
        size: this._rand(cfg.size.min, cfg.size.max),
        color: colors[Math.floor(Math.random() * colors.length)],
      }));

      const tick = (dt) => {
        elapsed += dt;
        let allDead = true;
        particles.forEach((p, i) => {
          p.life += dt;
          if (p.life >= p.maxLife) {
            dummy.scale.set(0, 0, 0);
          } else {
            allDead = false;
            p.vy -= 0.1; // gravity
            p.x += p.vx * dt;
            p.y += p.vy * dt;
            p.z += p.vz * dt;
            const t = p.life / p.maxLife;
            const s = p.size * (1 - t);
            dummy.position.set(p.x, p.y, p.z);
            dummy.scale.set(s, s, s);
          }
          dummy.updateMatrix();
          burst.setMatrixAt(i, dummy.matrix);
        });
        burst.instanceMatrix.needsUpdate = true;
        if (allDead || elapsed > 3) {
          this._scene.remove(burst);
          burst.geometry.dispose();
          burst.material.dispose();
        }
      };

      // Hook into main loop
      const origAnim = this._burstTick;
      this._burstTick = (dt) => {
        tick(dt);
        if (origAnim) origAnim(dt);
      };
    }

    // ── Animation Loop ─────────────────────────────────────────────────────

    _animate() {
      if (!this._running) return;
      this._frameId = requestAnimationFrame(() => this._animate());

      const dt = Math.min(this._clock.getDelta(), 0.05);
      this._elapsed += dt;

      this._update(dt);
      if (this._burstTick) this._burstTick(dt);

      if (!this._shared) {
        this._renderer.render(this._scene, this._camera);
      }
    }

    _update(dt) {
      const cfg = this._config;
      const count = cfg.count;

      for (let i = 0; i < count; i++) {
        const ix = i * 3;
        const iy = i * 3 + 1;
        const iz = i * 3 + 2;

        // Life tracking
        if (this._maxLife[i] > 0) {
          this._life[i] += dt;
          if (this._life[i] >= this._maxLife[i]) {
            this._spawnParticle(i);
            continue;
          }
        }

        // Gravity
        if (cfg.gravity) {
          this._vel[iy] -= cfg.gravity * dt * 60;
        }

        // Wobble
        if (cfg.wobble) {
          const w = cfg.wobble;
          const freq = (w.frequency || 1.0) * this._elapsed + i * 0.3;
          if (w.x) this._pos[ix] += Math.sin(freq) * w.x * dt;
          if (w.y) this._pos[iy] += Math.cos(freq * 0.7) * w.y * dt;
        }

        // Glitch
        if (cfg.glitch && Math.random() < cfg.glitch.probability) {
          this._pos[ix] += this._rand(-cfg.glitch.magnitude, cfg.glitch.magnitude);
          this._pos[iy] += this._rand(-cfg.glitch.magnitude * 0.5, cfg.glitch.magnitude * 0.5);
        }

        // Move
        this._pos[ix] += this._vel[ix] * dt * 60;
        this._pos[iy] += this._vel[iy] * dt * 60;
        this._pos[iz] += this._vel[iz] * dt * 60;

        // Rotate
        this._rot[ix] += this._rotVel[ix];
        this._rot[iy] += this._rotVel[iy];
        this._rot[iz] += this._rotVel[iz];

        // Wrap / bounds
        if (cfg.wrap) {
          if (cfg.wrapY !== null && cfg.wrapY !== undefined) {
            const s = cfg.spawn;
            if (this._pos[iy] < cfg.wrapY) {
              this._pos[iy] = s.y[1];
              this._pos[ix] = this._rand(s.x[0], s.x[1]);
            }
            if (this._pos[iy] > (s.y[1] + 2)) {
              this._pos[iy] = cfg.wrapY;
            }
          }
          if (cfg.wrapX !== null && cfg.wrapX !== undefined) {
            if (this._pos[ix] > cfg.wrapX) this._pos[ix] = -cfg.wrapX;
          }
        }
      }

      this._updateMatrix();
    }

    _updateMatrix() {
      const cfg = this._config;
      const count = cfg.count;

      for (let i = 0; i < count; i++) {
        const ix = i * 3;
        this._dummy.position.set(this._pos[ix], this._pos[ix+1], this._pos[ix+2]);

        let sz = this._size[i];

        // Grow
        if (cfg.grow && this._maxLife[i] > 0) {
          const t = this._life[i] / this._maxLife[i];
          sz = Math.min(sz + this._life[i] * cfg.grow.rate, cfg.grow.max || 2.0);
        }

        // Elongated
        if (cfg.elongated) {
          const e = cfg.elongated;
          if (e.axis === 'y') {
            this._dummy.scale.set(sz, sz * e.scale, sz);
          } else if (e.axis === 'x') {
            this._dummy.scale.set(sz * e.scale, sz, sz);
          }
        } else {
          this._dummy.scale.set(sz, sz, sz);
        }

        this._dummy.rotation.set(this._rot[ix], this._rot[ix+1], this._rot[ix+2]);

        // Alpha
        let alpha = this._alpha[i];
        if (cfg.lifespan && this._maxLife[i] > 0) {
          const t = this._life[i] / this._maxLife[i];
          if (cfg.fadeIn && t < 0.2) alpha *= t / 0.2;
          if (cfg.fadeOut && t > 0.7) alpha *= 1 - (t - 0.7) / 0.3;
          if (cfg.fadeTop && t > 0.8) alpha *= 1 - (t - 0.8) / 0.2;
        }

        // Flicker
        if (cfg.flicker && Math.random() < cfg.flicker.probability) {
          alpha = 0;
        }

        this._mesh.setColorAt(i, this._tempColor(this._getColor(i), alpha));
        this._dummy.updateMatrix();
        this._mesh.setMatrixAt(i, this._dummy.matrix);
      }

      this._mesh.instanceMatrix.needsUpdate = true;
      if (this._mesh.instanceColor) this._mesh.instanceColor.needsUpdate = true;
    }

    // ── Helpers ────────────────────────────────────────────────────────────

    _mergeConfig(preset) {
      return Object.assign({}, preset, this._options.config || {});
    }

    _rand(min, max) {
      return min + Math.random() * (max - min);
    }

    _getColor(i) {
      const colors = Array.isArray(this._config.color)
        ? this._config.color
        : [this._config.color];
      return colors[this._colorIdx[i] % colors.length];
    }

    _tempColor(hex, alpha) {
      if (!this._colorCache) this._colorCache = new THREE.Color();
      this._colorCache.setHex(hex);
      // Multiply by alpha for additive blending effect
      this._colorCache.multiplyScalar(alpha);
      return this._colorCache;
    }

    _setInstanceColor(i, hex) {
      // Colors stored in instanceColor after THREE r128
      // Will be updated in updateMatrix
    }

    _fadeOut(ms, cb) {
      // Simple tween on material opacity
      const start = performance.now();
      const tick = () => {
        const t = (performance.now() - start) / ms;
        if (t >= 1) { if (cb) cb(); return; }
        this._mesh.material.opacity = 1 - t;
        requestAnimationFrame(tick);
      };
      requestAnimationFrame(tick);
    }

    _fadeIn(ms) {
      const start = performance.now();
      const tick = () => {
        const t = (performance.now() - start) / ms;
        if (t >= 1) { this._mesh.material.opacity = 1; return; }
        this._mesh.material.opacity = t;
        requestAnimationFrame(tick);
      };
      requestAnimationFrame(tick);
    }

    _initResizeObserver() {
      if (typeof ResizeObserver === 'undefined') return;
      this._resizeObs = new ResizeObserver(() => this.resize());
      this._resizeObs.observe(this._container);
    }

    _loadThree(cb) {
      if (typeof THREE !== 'undefined') { cb(); return; }
      const script = document.createElement('script');
      script.src = 'https://cdnjs.cloudflare.com/ajax/libs/three.js/r128/three.min.js';
      script.onload = cb;
      document.head.appendChild(script);
    }
  }

  // ── Static helpers ───────────────────────────────────────────────────────

  ParticleSystem3D.PRESETS = Object.keys(PRESETS);

  /**
   * Quick-attach to an element.
   * @param {string|HTMLElement} selector
   * @param {string} preset
   * @param {object} options
   * @returns {ParticleSystem3D}
   */
  ParticleSystem3D.attach = function (selector, preset, options = {}) {
    return new ParticleSystem3D(selector, preset, { autoStart: true, ...options });
  };

  /**
   * Scene-to-preset mapping for automatic scene theming.
   */
  ParticleSystem3D.SCENE_PRESETS = {
    penthouse:  'rose_petals',
    lounge:   'smoke',
    tavern:   'embers',
    casino:   'sparks',
    gallery:  'hologram_static',
    heist:    'embers',
    realm:    'embers',
    neoncity: 'neon_rain',
    arena:    'blood_mist',
    phone:    'neon_dust',
    coders:   'matrix_code',
    games:    'sparks',
    hub:      'neon_dust',
    intel:    'data_stream',
    admin:    'matrix_code',
  };

  return ParticleSystem3D;
}));
