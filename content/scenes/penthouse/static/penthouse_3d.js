/**
 * THE PENTHOUSE — 3D Room Background  v3.0  (Dark Renaissance)
 * =============================================================
 * Premium Three.js r184 penthouse: physically-based materials with
 * RoomEnvironment IBL, transmission glass, rose/violet luxury palette,
 * instanced exterior skyline with rain curtain, animated fireplace,
 * interactive raycasting, simulated bloom + vignette, and smooth LERP
 * camera transitions.
 *
 * Requires window.THREE (r184 + addons) provided by three_boot.js.
 * Canvas: #penthouse-canvas  |  Container: #scene-container
 *
 * API contract (consumed by character_bridge.js, penthouse.js):
 *   window.penthouse3D.switchView(name)
 *   window.penthouse3D.getViewNames() → string[]
 *
 * Version: v1.58.0 [2026-06-11]
 *
 * Change Log:
 *   v1.58.0 [2026-06-11] — r128→r184 migration (physical lights, sRGB
 *                           default); Dark Renaissance overhaul: rose
 *                           #fb7185 accent, RoomEnvironment IBL,
 *                           MeshPhysicalMaterial transmission glass,
 *                           instanced exterior skyline + rain curtain,
 *                           rose emissive furniture trim; fixed
 *                           setCameraViews position/pos shape bug
 *   v2.0    [2026-03-2x]  — AAA++ rewrite (8 zones, 14 lights, post-FX)
 */

'use strict';

(function () {

  // ─── Core refs ───────────────────────────────────────────────────
  let scene, camera, renderer, controls;
  const clock = new THREE.Clock();
  const raycaster = new THREE.Raycaster();
  const mouse = new THREE.Vector2(-9, -9);

  // Animation buckets
  const neonStrips = [];      // { mesh, baseHue }
  const fireLights = [];      // PointLight[]
  const emberParticles = [];  // { mesh, vel, life }
  const cityDots = [];        // { mesh, phase }
  const pendantGroup = { group: null };
  const clockHands = { minute: null, hour: null };
  const rainDrops = [];       // { mesh, speed }
  const hoverables = [];      // { mesh, zone }
  let hoveredObj = null;
  let autoOrbitAngle = 0;

  // Post-processing overlays
  let vignetteQuad = null;
  let grainQuad = null;
  const bloomCopies = [];

  const ROOM = { w: 16, h: 4, d: 14 };
  // v1.58.0 [2026-06-11] — Dark Renaissance palette (matches ui_kits_v2/penthouse)
  const ACCENT = 0xfb7185;        // rose — scene neon accent
  const ACCENT2 = 0x9d71ea;       // violet — secondary accent
  const ROSE_HUE = 0.985;         // HSL hue for neon strip pulse

  // ─── Camera views ────────────────────────────────────────────────
  const CAMERA_VIEWS = {
    overview:  { pos: { x: 10, y: 9, z: 10 },   target: { x: 0, y: 0.5, z: 0 },     fov: 55 },
    bed:       { pos: { x: -1, y: 3, z: -1 },    target: { x: -5, y: 0.6, z: -1 },   fov: 48 },
    couch:     { pos: { x: 1, y: 3, z: 0 },      target: { x: 5.5, y: 0.6, z: 0 },   fov: 48 },
    bath:      { pos: { x: 3, y: 2.5, z: -3 },   target: { x: 6.5, y: 0.5, z: -4.5 },fov: 46 },
    fireplace: { pos: { x: 2, y: 2.5, z: 2 },    target: { x: -2, y: 0.6, z: 4.5 },  fov: 48 },
    vanity:    { pos: { x: 0, y: 2.5, z: -3 },   target: { x: 3, y: 0.8, z: -5.8 },  fov: 45 },
    bar:       { pos: { x: 0, y: 2.5, z: -2 },   target: { x: -3, y: 0.8, z: -5.5 }, fov: 46 },
    balcony:   { pos: { x: 2, y: 2.5, z: 3 },    target: { x: 5, y: 0.5, z: 5.5 },   fov: 48 },
  };
  let currentView = 'overview';
  let cameraAnimating = false;
  let _cameraAnim = null;

  // ─── Material library ────────────────────────────────────────────
  const MAT = {};

  function buildMaterials() {
    // v1.58.0 [2026-06-11] — Dark Renaissance re-grade: rose/violet luxury
    // palette tuned for RoomEnvironment IBL; window/partition glass upgraded
    // to MeshPhysicalMaterial transmission (real refraction, r184).
    MAT.hardwood   = new THREE.MeshStandardMaterial({ color: 0x2e1d14, roughness: 0.28, metalness: 0.08 });
    MAT.wall       = new THREE.MeshStandardMaterial({ color: 0x262033, roughness: 0.85, side: THREE.DoubleSide });
    MAT.ceiling    = new THREE.MeshStandardMaterial({ color: 0x1b1726, roughness: 0.92 });
    MAT.gold       = new THREE.MeshStandardMaterial({ color: 0xd4b36a, metalness: 0.9, roughness: 0.18 });
    MAT.chrome     = new THREE.MeshStandardMaterial({ color: 0xd5d5dd, metalness: 0.95, roughness: 0.1 });
    MAT.glass      = new THREE.MeshPhysicalMaterial({
      color: 0xd6e4f5, transparent: true, opacity: 1.0,
      transmission: 0.92, roughness: 0.06, metalness: 0.0,
      ior: 1.5, thickness: 0.08, envMapIntensity: 1.2,
    });
    // Cheap glass for secondary panes (railings, partitions, table tops) —
    // transmission costs a full extra render pass, so only the curtain wall
    // pays for it. v1.58.0 [2026-06-11]
    MAT.glassLite  = new THREE.MeshStandardMaterial({
      color: 0xaaccee, transparent: true, opacity: 0.22, metalness: 0.3, roughness: 0.06,
    });
    MAT.mirror     = new THREE.MeshStandardMaterial({ color: 0xc8d2dd, metalness: 1.0, roughness: 0.03 });
    MAT.fabric     = new THREE.MeshStandardMaterial({ color: 0x46243f, roughness: 0.9, metalness: 0.0 });   // velvet plum-rose
    MAT.silk       = new THREE.MeshStandardMaterial({ color: 0xf6e9e4, roughness: 0.4, metalness: 0.02 });  // blush silk
    MAT.stone      = new THREE.MeshStandardMaterial({ color: 0x46434e, roughness: 0.88, metalness: 0.02 });
    MAT.darkWood   = new THREE.MeshStandardMaterial({ color: 0x32190c, roughness: 0.5, metalness: 0.05 });
    MAT.granite    = new THREE.MeshStandardMaterial({ color: 0x17151e, roughness: 0.3, metalness: 0.15 });
    MAT.marble     = new THREE.MeshStandardMaterial({ color: 0xece2dc, roughness: 0.22, metalness: 0.06 });
    MAT.whiteCeram = new THREE.MeshStandardMaterial({ color: 0xf2f0ee, roughness: 0.16, metalness: 0.05 });
    MAT.rug        = new THREE.MeshStandardMaterial({ color: 0x521f3e, roughness: 0.95 });                  // deep rose
    MAT.neon       = new THREE.MeshBasicMaterial({ color: ACCENT, transparent: true, opacity: 0.9 });
    // Rose emissive trim for furniture accent lines (pulsed in animate())
    MAT.roseTrim   = new THREE.MeshStandardMaterial({
      color: 0x33121a, emissive: ACCENT, emissiveIntensity: 1.6, roughness: 0.4,
    });
    // Violet emissive trim (secondary accent zones: vanity, bath)
    MAT.violetTrim = new THREE.MeshStandardMaterial({
      color: 0x1d1430, emissive: ACCENT2, emissiveIntensity: 1.3, roughness: 0.4,
    });
  }

  // ─── Helpers ─────────────────────────────────────────────────────

  function _mesh(geo, mat, x, y, z, opts) {
    const m = new THREE.Mesh(geo, mat);
    m.position.set(x, y, z);
    if (opts) {
      if (opts.rx) m.rotation.x = opts.rx;
      if (opts.ry) m.rotation.y = opts.ry;
      if (opts.rz) m.rotation.z = opts.rz;
      if (opts.sx) m.scale.set(opts.sx, opts.sy || opts.sx, opts.sz || opts.sx);
      if (opts.cast !== false) m.castShadow = true;
      if (opts.recv !== false) m.receiveShadow = true;
      if (opts.name) m.name = opts.name;
    } else {
      m.castShadow = true;
      m.receiveShadow = true;
    }
    scene.add(m);
    return m;
  }

  function _box(w, h, d, mat, x, y, z, opts) {
    return _mesh(new THREE.BoxGeometry(w, h, d), mat, x, y, z, opts);
  }

  function cubicEase(t) {
    return t < 0.5 ? 4 * t * t * t : 1 - Math.pow(-2 * t + 2, 3) / 2;
  }

  // v1.58.0 [2026-06-11] — r184 lighting is physically correct only
  // (useLegacyLights removed r165). LPI converts the hand-tuned legacy
  // intensities to physical units; apply to EVERY light creation.
  const LPI = Math.PI;

  // Map zone name → camera view for click navigation
  const ZONE_MAP = {
    bed: 'bed', couch: 'couch', fireplace: 'fireplace',
    bar: 'bar', vanity: 'vanity', bath: 'bath', balcony: 'balcony',
  };

  // ═══════════════════════════════════════════════════════════════════
  //  INIT
  // ═══════════════════════════════════════════════════════════════════

  function init() {
    const canvas = document.getElementById('penthouse-canvas');
    if (!canvas) return;

    buildMaterials();

    renderer = new THREE.WebGLRenderer({ canvas, antialias: true, alpha: true });
    renderer.setPixelRatio(Math.min(window.devicePixelRatio, 2));
    renderer.shadowMap.enabled = true;
    renderer.shadowMap.type = THREE.PCFSoftShadowMap;
    renderer.toneMapping = THREE.ACESFilmicToneMapping;
    renderer.toneMappingExposure = 1.35;  // v1.58.0 — re-tuned for physical lights
    // v1.58.0 [2026-06-11] — r184: outputEncoding removed; sRGB output is the
    // default (renderer.outputColorSpace = SRGBColorSpace).

    scene = new THREE.Scene();
    scene.background = new THREE.Color(0x07050f);
    scene.fog = new THREE.FogExp2(0x07050f, 0.014);

    // v1.58.0 [2026-06-11] — Image-based lighting: RoomEnvironment via PMREM
    // gives glass/chrome/gold believable reflections and lifts the PBR
    // materials without extra runtime lights. Big visual win, one-time cost.
    if (THREE.RoomEnvironment) {
      const pmrem = new THREE.PMREMGenerator(renderer);
      scene.environment = pmrem.fromScene(new THREE.RoomEnvironment(), 0.04).texture;
      scene.environmentIntensity = 0.4;   // lifted after eye-tune (was 0.22)
      pmrem.dispose();
    }

    camera = new THREE.PerspectiveCamera(55, 1, 0.1, 500);
    camera.position.set(10, 9, 10);

    controls = new THREE.OrbitControls(camera, renderer.domElement);
    controls.target.set(0, 0.5, 0);
    controls.enableDamping = true;
    controls.dampingFactor = 0.06;
    controls.minDistance = 2;
    controls.maxDistance = 25;
    controls.maxPolarAngle = Math.PI / 2.05;
    controls.minPolarAngle = 0.15;
    controls.zoomSpeed = 1.0;
    controls.rotateSpeed = 0.7;
    controls.panSpeed = 0.6;
    controls.enablePan = true;
    controls.update();

    createLighting();
    createRoom();
    createNeonStrips();
    buildBed();
    buildCouch();
    buildFireplace();
    buildBar();
    buildVanity();
    buildBathroom();
    buildBalcony();
    buildDecorations();
    buildCitySkyline();
    buildWallClock();
    buildRainEffect();
    buildAccentTrim();  // v1.58.0 — rose/violet emissive furniture trim
    createPostFX();

    canvas.addEventListener('mousemove', onMouseMove, false);
    canvas.addEventListener('click', onMouseClick, false);
    window.addEventListener('resize', onResize);
    onResize();

    animate();
    console.debug('[Penthouse3D] v2.0 AAA++ initialised');
  }

  // v1.53.0 [2026-03-26] — Moved to IIFE scope (was inside init(), causing ReferenceError in _safeInit)

  // External animation callbacks (used by character_bridge.js)
  const _externalAnimCallbacks = [];

  // Mutable location positions (overridable from YAML config)
  // v1.53.1 [2026-03-26] — Y at furniture surface; X/Z offset from center to avoid clipping
  //   Bed headboard at local x=-2.85, footboard at x=1.82 → place near foot (local x=0.8)
  //   Anim system handles pose: bed→lie, couch→lounge, bar→drink, vanity→primp, bath→bathe
  let _locationPositions = {
    bed:       { x: -4.2, y: 0.70, z: -1 },
    couch:     { x:  5.5, y: 0.50, z:  0.5 },
    fireplace: { x: -2,   y: 0,    z:  4.5 },
    bar:       { x: -3,   y: 0.55, z: -4.8 },
    vanity:    { x:  3,   y: 0.40, z: -5.2 },
    bath:      { x:  6.2, y: 0.45, z: -4.5 },
    balcony:   { x:  5,   y: 0,    z:  5.5 },
    doorway:   { x:  0,   y: 0,    z: -6.5 },
  };

  // v1.49.2 [2026-03-22] — Initialization tracking + onReady callback for race condition fix
  let _initialized = false;
  let _initError = null;
  const _readyCallbacks = [];

  window.penthouse3D = {
    switchView,
    getViewNames: () => Object.keys(CAMERA_VIEWS),
    toggleFirstPerson: toggleFirstPersonMode,
    isFirstPerson: () => fpsMode,

    // ── Initialization state API ────────────────────────────────
    isInitialized: () => _initialized,
    getInitError: () => _initError,
    onReady: (cb) => {
      if (_initialized) { cb(window.penthouse3D); return; }
      if (_initError) { console.warn('[Penthouse3D] init failed, callback skipped:', _initError); return; }
      _readyCallbacks.push(cb);
    },

    // ── Character integration API ─────────────────────────────────
    getScene: () => scene,
    getCamera: () => camera,
    getRenderer: () => renderer,

    getLocationPositions: () => ({ ..._locationPositions }),

    addToAnimationLoop: (cb) => {
      if (typeof cb === 'function') _externalAnimCallbacks.push(cb);
    },

    removeFromAnimationLoop: (cb) => {
      const idx = _externalAnimCallbacks.indexOf(cb);
      if (idx !== -1) _externalAnimCallbacks.splice(idx, 1);
    },

    // ── YAML Config setters ───────────────────────────────────────
    setLocationPositions: (positions) => {
      Object.assign(_locationPositions, positions);
    },

    setCameraViews: (views) => {
      // v1.58.0 [2026-06-11] — Normalize YAML shape: config/penthouse YAML
      // uses `position`, switchView reads `pos`. The raw assignment made
      // every camera preset crash ("Cannot read properties of undefined
      // (reading 'x')") once PenthouseConfig loaded — root cause of the
      // long-standing "penthouse 3D broken" issue.
      for (const [name, view] of Object.entries(views)) {
        const pos = view.pos || view.position;
        if (!pos || !view.target) continue;  // skip malformed entries
        CAMERA_VIEWS[name] = {
          pos: { x: pos.x, y: pos.y, z: pos.z },
          target: { x: view.target.x, y: view.target.y, z: view.target.z },
          fov: view.fov || 55,
          label: view.label,
        };
      }
    },

    setLightingPresets: (presets) => {
      // Store for runtime switching
      window._penthouse3D_lightingPresets = presets;
    },

    setEffectsConfig: (effects) => {
      // Store for runtime access
      window._penthouse3D_effectsConfig = effects;
    },
  };

  // Store reference for animate() to call external callbacks
  window._penthouse3D_animCallbacks = _externalAnimCallbacks;

  // ═══════════════════════════════════════════════════════════════════
  //  LIGHTING  (14 lights total)
  // ═══════════════════════════════════════════════════════════════════

  function createLighting() {
    // v1.58.0 [2026-06-11] — warmer plum ambient + slight raise (physical
    // falloff dims mid-room vs legacy), plus a rose city-glow wash from the
    // curtain wall so the skyline tints the interior.
    scene.add(new THREE.AmbientLight(0x2c2030, 0.6 * LPI));

    const cityWash = new THREE.PointLight(0xfb7185, 0.35 * LPI, 14, 1.6);
    cityWash.position.set(0, 2.2, 6.4);
    scene.add(cityWash);

    // Key directional — only shadow caster #1
    const dir = new THREE.DirectionalLight(0xffeedd, 0.5 * LPI);
    dir.position.set(5, 10, 5);
    dir.castShadow = true;
    dir.shadow.mapSize.set(2048, 2048);
    dir.shadow.camera.near = 0.5;
    dir.shadow.camera.far = 25;
    dir.shadow.camera.left = -10;
    dir.shadow.camera.right = 10;
    dir.shadow.camera.top = 10;
    dir.shadow.camera.bottom = -10;
    dir.shadow.bias = -0.0005;
    scene.add(dir);

    // Warm zone lights (bed, fireplace)
    const warmCfg = [
      { x: -5, y: 2.5, z: -1,   c: 0xffaa66, i: 0.85 },
      { x: -2, y: 1.5, z: 5.5,  c: 0xff6622, i: 1.0 },
      { x: -5, y: 2.5, z: -4.5, c: 0xffaa44, i: 0.4 },
    ];
    warmCfg.forEach(p => {
      const pl = new THREE.PointLight(p.c, p.i * LPI, 8);
      pl.position.set(p.x, p.y, p.z);
      scene.add(pl);
    });

    // Cool zone lights (bar, bathroom)
    const coolCfg = [
      { x: -3,  y: 3.2, z: -5.5, c: 0x88aaff, i: 0.6 },
      { x: 6.5, y: 1.5, z: -4.5, c: 0xaaddff, i: 0.55 },
    ];
    coolCfg.forEach(p => {
      const pl = new THREE.PointLight(p.c, p.i * LPI, 8);
      pl.position.set(p.x, p.y, p.z);
      scene.add(pl);
    });

    // Couch / living area
    const couchPl = new THREE.PointLight(0xffd4a3, 0.55 * LPI, 8);
    couchPl.position.set(5.5, 2.5, 0);
    scene.add(couchPl);

    // Vanity
    const vanityPl = new THREE.PointLight(0xddaaff, 0.45 * LPI, 6);
    vanityPl.position.set(3, 2.0, -5.8);
    scene.add(vanityPl);

    // Balcony moonlight
    const balcPl = new THREE.PointLight(0x9d71ea, 0.5 * LPI, 10);
    balcPl.position.set(5, 2, 5.5);
    scene.add(balcPl);

    // Ceiling spot lights — shadow caster #2
    const spot = new THREE.SpotLight(0xffeedd, 0.65 * LPI, 12, Math.PI / 6, 0.5, 1);
    spot.position.set(0, 3.95, 0);
    spot.target.position.set(0, 0, 0);
    spot.castShadow = true;
    spot.shadow.mapSize.set(1024, 1024);
    scene.add(spot);
    scene.add(spot.target);

    // Volumetric light cones from ceiling spots
    const coneMat = new THREE.MeshBasicMaterial({
      color: 0xffeedd, transparent: true, opacity: 0.04, side: THREE.DoubleSide,
    });
    [[-3, 0], [3, 0], [0, -3], [0, 3]].forEach(([x, z]) => {
      const cone = new THREE.Mesh(new THREE.ConeGeometry(1.5, 3.5, 16, 1, true), coneMat);
      cone.position.set(x, 2.2, z);
      cone.rotation.x = Math.PI;
      scene.add(cone);
    });

    // Hemisphere fill
    const hemi = new THREE.HemisphereLight(0x2a2a4e, 0x1a0a05, 0.15 * LPI);
    scene.add(hemi);
  }

  // ═══════════════════════════════════════════════════════════════════
  //  NEON STRIP LIGHTING
  // ═══════════════════════════════════════════════════════════════════

  function createNeonStrips() {
    const hw = ROOM.w / 2;
    const hd = ROOM.d / 2;
    const h = ROOM.h - 0.05;
    const thick = 0.03;
    const depth = 0.04;

    const strips = [
      { geo: [ROOM.w, thick, depth], pos: [0, h, -hd + 0.08] },
      { geo: [ROOM.w, thick, depth], pos: [0, h, hd - 0.08] },
      { geo: [depth, thick, ROOM.d], pos: [-hw + 0.08, h, 0] },
      { geo: [depth, thick, ROOM.d], pos: [hw - 0.08, h, 0] },
    ];

    strips.forEach(s => {
      const mat = new THREE.MeshBasicMaterial({
        color: ACCENT, transparent: true, opacity: 0.85,
      });
      const m = new THREE.Mesh(new THREE.BoxGeometry(...s.geo), mat);
      m.position.set(...s.pos);
      scene.add(m);
      neonStrips.push({ mesh: m, baseHue: ROSE_HUE });  // v1.58.0 — rose base

      // Bloom copy (additive glow)
      const glowMat = new THREE.MeshBasicMaterial({
        color: ACCENT, transparent: true, opacity: 0.15,
        blending: THREE.AdditiveBlending, depthWrite: false,
      });
      const glow = new THREE.Mesh(new THREE.BoxGeometry(s.geo[0] * 1.3, s.geo[1] * 5, s.geo[2] * 5), glowMat);
      glow.position.copy(m.position);
      scene.add(glow);
      bloomCopies.push(glow);
    });
  }

  // ═══════════════════════════════════════════════════════════════════
  //  ROOM SHELL
  // ═══════════════════════════════════════════════════════════════════

  function createRoom() {
    const { w, h, d } = ROOM;
    const hw = w / 2, hd = d / 2;

    // Floor — dark hardwood with reflection
    const floor = _mesh(new THREE.PlaneGeometry(w, d), MAT.hardwood, 0, 0, 0, { rx: -Math.PI / 2, cast: false });
    floor.receiveShadow = true;

    // Ceiling with recessed lighting spots (emissive circles)
    _mesh(new THREE.PlaneGeometry(w, d), MAT.ceiling, 0, h, 0, { rx: Math.PI / 2, cast: false });
    const spotMat = new THREE.MeshStandardMaterial({
      color: 0x222233, emissive: 0xffeedd, emissiveIntensity: 0.3,
    });
    [[-3, -3], [3, -3], [-3, 3], [3, 3], [0, 0]].forEach(([x, z]) => {
      const spot = new THREE.Mesh(new THREE.CircleGeometry(0.3, 16), spotMat);
      spot.position.set(x, h - 0.01, z);
      spot.rotation.x = Math.PI / 2;
      scene.add(spot);
    });

    // Walls — north + sides solid; south is a floor-to-ceiling glass
    // curtain wall (v1.58.0 [2026-06-11]) so the skyline + rain curtain
    // are visible from inside, matching the ui_kits_v2 panoramic window.
    _box(w, h, 0.12, MAT.wall, 0, h / 2, -hd, { cast: false });
    _box(0.12, h, d, MAT.wall, -hw, h / 2, 0, { cast: false });
    _box(0.12, h, d, MAT.wall, hw, h / 2, 0, { cast: false });

    // South curtain wall: transmission glass + champagne-gold mullions
    const curtain = _box(w, h, 0.06, MAT.glass, 0, h / 2, hd, { cast: false });
    curtain.receiveShadow = false;
    for (let mx = -hw + 2; mx < hw; mx += 2.6) {
      _box(0.07, h, 0.1, MAT.gold, mx, h / 2, hd, { cast: false });
    }
    _box(w, 0.1, 0.1, MAT.gold, 0, 0.05, hd, { cast: false });      // sill
    _box(w, 0.08, 0.1, MAT.gold, 0, h - 0.04, hd, { cast: false }); // header

    // Crown moulding — gold accent
    const mouldGeo = new THREE.BoxGeometry(1, 0.06, 0.06);
    const moldW = new THREE.Mesh(new THREE.BoxGeometry(w, 0.06, 0.06), MAT.gold);
    moldW.position.set(0, h - 0.03, -hd + 0.06);
    scene.add(moldW);
    const moldW2 = moldW.clone();
    moldW2.position.z = hd - 0.06;
    scene.add(moldW2);
    [-1, 1].forEach(s => {
      const side = new THREE.Mesh(new THREE.BoxGeometry(0.06, 0.06, d), MAT.gold);
      side.position.set(s * (hw - 0.06), h - 0.03, 0);
      scene.add(side);
    });

    // Rugs
    const rug1 = _mesh(new THREE.PlaneGeometry(7, 5), MAT.rug, -4.5, 0.01, -1, { rx: -Math.PI / 2, cast: false });
    const rug2Mat = new THREE.MeshStandardMaterial({ color: 0x3a1838, roughness: 0.95 });
    _mesh(new THREE.PlaneGeometry(5, 4), rug2Mat, 0, 0.008, 1, { rx: -Math.PI / 2, cast: false });

    // Floor-level ambient fog plane
    const fogMat = new THREE.MeshBasicMaterial({
      color: 0x1a1a2e, transparent: true, opacity: 0.12, depthWrite: false,
    });
    const fogPlane = new THREE.Mesh(new THREE.PlaneGeometry(w, d), fogMat);
    fogPlane.rotation.x = -Math.PI / 2;
    fogPlane.position.y = 0.15;
    scene.add(fogPlane);
  }

  // ═══════════════════════════════════════════════════════════════════
  //  BED — luxurious king with tufted headboard
  // ═══════════════════════════════════════════════════════════════════

  function buildBed() {
    const BX = -5, BZ = -1;
    const bedGroup = new THREE.Group();
    bedGroup.userData.zone = 'bed';

    // Platform + frame with gold legs
    const platform = new THREE.Mesh(new THREE.BoxGeometry(3.6, 0.12, 4.8), MAT.darkWood);
    platform.position.set(0, 0.06, 0);
    platform.receiveShadow = true;
    bedGroup.add(platform);

    const frame = new THREE.Mesh(new THREE.BoxGeometry(3.4, 0.35, 4.6), MAT.darkWood);
    frame.position.set(0, 0.24, 0);
    frame.castShadow = true;
    bedGroup.add(frame);

    // Gold legs
    [[-1.6, -2.1], [1.6, -2.1], [-1.6, 2.1], [1.6, 2.1]].forEach(([ox, oz]) => {
      const leg = new THREE.Mesh(new THREE.CylinderGeometry(0.04, 0.05, 0.12, 8), MAT.gold);
      leg.position.set(ox, 0.02, oz);
      bedGroup.add(leg);
    });

    // Mattress — silk
    const mattress = new THREE.Mesh(new THREE.BoxGeometry(3.2, 0.28, 4.4), MAT.silk);
    mattress.position.set(0, 0.56, 0);
    mattress.castShadow = true;
    bedGroup.add(mattress);

    // Sheets — deep wine silk
    const sheetMat = new THREE.MeshStandardMaterial({ color: 0x8b2252, roughness: 0.45, metalness: 0.02 });
    const sheet = new THREE.Mesh(new THREE.BoxGeometry(3.2, 0.06, 3.0), sheetMat);
    sheet.position.set(0, 0.73, 0.5);
    bedGroup.add(sheet);

    // Fold line
    const foldMat = new THREE.MeshStandardMaterial({ color: 0xd4a0b8, roughness: 0.5 });
    const fold = new THREE.Mesh(new THREE.BoxGeometry(3.0, 0.04, 0.5), foldMat);
    fold.position.set(0, 0.75, -1.5);
    bedGroup.add(fold);

    // Tufted headboard — grid of small bumps
    const hbFrame = new THREE.Mesh(new THREE.BoxGeometry(0.14, 1.8, 4.6), MAT.darkWood);
    hbFrame.position.set(-2.85, 1.32, 0);
    bedGroup.add(hbFrame);

    const tufterMat = new THREE.MeshStandardMaterial({ color: 0x5c2040, roughness: 0.9, metalness: 0.0 });
    const tufterPad = new THREE.Mesh(new THREE.BoxGeometry(0.08, 1.5, 4.2), tufterMat);
    tufterPad.position.set(-2.78, 1.22, 0);
    bedGroup.add(tufterPad);

    // Tuft bumps (grid 5×8)
    const tuftGeo = new THREE.SphereGeometry(0.05, 6, 4);
    for (let row = 0; row < 5; row++) {
      for (let col = 0; col < 8; col++) {
        const bump = new THREE.Mesh(tuftGeo, tufterMat);
        bump.position.set(-2.73, 0.55 + row * 0.3, -1.75 + col * 0.5);
        bedGroup.add(bump);
      }
    }

    // Gold finials
    [- 2.3, 2.3].forEach(zOff => {
      const finial = new THREE.Mesh(new THREE.SphereGeometry(0.09, 12, 12), MAT.gold);
      finial.position.set(-2.85, 2.26, zOff);
      bedGroup.add(finial);
    });

    // Footboard
    const footboard = new THREE.Mesh(new THREE.BoxGeometry(0.10, 0.5, 4.6), MAT.darkWood);
    footboard.position.set(1.82, 0.46, 0);
    bedGroup.add(footboard);

    // Pillows — InstancedMesh for 4 matching + 1 accent
    const pillowGeo = new THREE.BoxGeometry(0.35, 0.2, 0.55);
    const pillowMat = new THREE.MeshStandardMaterial({ color: 0xfff0f5, roughness: 0.92, metalness: 0.0 });
    const pillowPositions = [-1.5, -0.5, 0.5, 1.5];
    const pillowInst = new THREE.InstancedMesh(pillowGeo, pillowMat, 4);
    const dummy = new THREE.Object3D();
    pillowPositions.forEach((z, i) => {
      dummy.position.set(-2.3, 0.82, z);
      dummy.rotation.set(0, (Math.random() - 0.5) * 0.15, 0);
      dummy.updateMatrix();
      pillowInst.setMatrixAt(i, dummy.matrix);
    });
    bedGroup.add(pillowInst);

    // Decorative accent pillows (sphere-modified boxes)
    const accentPillowMat = new THREE.MeshStandardMaterial({ color: 0xddaa55, roughness: 0.85, metalness: 0.0 });
    [-0.5, 0.5].forEach(z => {
      const ap = new THREE.Mesh(new THREE.SphereGeometry(0.18, 8, 6), accentPillowMat);
      ap.scale.set(1.2, 0.6, 1.0);
      ap.position.set(-1.8, 0.82, z);
      ap.rotation.y = z * 0.4;
      bedGroup.add(ap);
    });

    // Bedside tables + lamps
    [-2.8, 2.8].forEach(z => {
      const table = new THREE.Mesh(new THREE.BoxGeometry(0.55, 0.6, 0.55), MAT.darkWood);
      table.position.set(0, 0.3, z);
      table.castShadow = true;
      bedGroup.add(table);

      const handle = new THREE.Mesh(new THREE.CylinderGeometry(0.015, 0.015, 0.12, 8), MAT.gold);
      handle.position.set(0.3, 0.35, z);
      handle.rotation.z = Math.PI / 2;
      bedGroup.add(handle);

      const pole = new THREE.Mesh(new THREE.CylinderGeometry(0.02, 0.02, 0.35, 8), MAT.chrome);
      pole.position.set(0, 0.78, z);
      bedGroup.add(pole);

      const shadeMat = new THREE.MeshStandardMaterial({
        color: 0xffeecc, emissive: 0xffaa44, emissiveIntensity: 0.5,
        transparent: true, opacity: 0.8,
      });
      const shade = new THREE.Mesh(new THREE.CylinderGeometry(0.06, 0.16, 0.18, 16), shadeMat);
      shade.position.set(0, 1.06, z);
      bedGroup.add(shade);

      // Bloom copy for lamp shade
      const glowShade = new THREE.Mesh(
        new THREE.SphereGeometry(0.22, 8, 8),
        new THREE.MeshBasicMaterial({ color: 0xffaa44, transparent: true, opacity: 0.08, blending: THREE.AdditiveBlending, depthWrite: false })
      );
      glowShade.position.set(0, 1.06, z);
      bedGroup.add(glowShade);
    });

    bedGroup.position.set(BX, 0, BZ);
    scene.add(bedGroup);
    hoverables.push({ mesh: bedGroup, zone: 'bed' });
  }

  // ═══════════════════════════════════════════════════════════════════
  //  COUCH — L-shaped sectional with coffee table + TV
  // ═══════════════════════════════════════════════════════════════════

  function buildCouch() {
    const CX = 5.5, CZ = 0;
    const couchGroup = new THREE.Group();
    couchGroup.userData.zone = 'couch';

    // Main seat
    const seatMat = new THREE.MeshStandardMaterial({ color: 0x3a2244, roughness: 0.92, metalness: 0.0 });
    const seat = new THREE.Mesh(new THREE.BoxGeometry(1.2, 0.5, 3.2), seatMat);
    seat.position.set(0, 0.25, 0);
    seat.castShadow = true;
    couchGroup.add(seat);

    // L-extension (perpendicular)
    const lExt = new THREE.Mesh(new THREE.BoxGeometry(1.8, 0.5, 1.0), seatMat);
    lExt.position.set(-0.9, 0.25, -1.6);
    lExt.castShadow = true;
    couchGroup.add(lExt);

    // Backrest
    const back = new THREE.Mesh(new THREE.BoxGeometry(0.18, 0.75, 3.2), seatMat);
    back.position.set(0.52, 0.72, 0);
    back.rotation.z = -0.05;
    back.castShadow = true;
    couchGroup.add(back);

    // L-section backrest
    const lBack = new THREE.Mesh(new THREE.BoxGeometry(1.8, 0.65, 0.16), seatMat);
    lBack.position.set(-0.9, 0.68, -2.1);
    couchGroup.add(lBack);

    // Armrests
    [1.6, -1.1].forEach((z, i) => {
      if (i === 1) return; // L-section covers this side
      const arm = new THREE.Mesh(new THREE.BoxGeometry(1.2, 0.4, 0.18), seatMat);
      arm.position.set(0, 0.55, z);
      couchGroup.add(arm);
    });

    // Cushion gaps — 3 seat cushions
    const cushMat = new THREE.MeshStandardMaterial({ color: 0x5c3060, roughness: 0.9, metalness: 0.0 });
    [-0.9, 0, 0.9].forEach(off => {
      const cush = new THREE.Mesh(new THREE.BoxGeometry(0.9, 0.14, 0.9), cushMat);
      cush.position.set(-0.04, 0.54, off);
      couchGroup.add(cush);
    });

    // Throw pillows — InstancedMesh
    const throwGeo = new THREE.BoxGeometry(0.14, 0.4, 0.5);
    const throwMat = new THREE.MeshStandardMaterial({ color: 0x6a3570, roughness: 0.9, metalness: 0.0 });
    const throwInst = new THREE.InstancedMesh(throwGeo, throwMat, 3);
    const d3 = new THREE.Object3D();
    [[-0.6, 0], [0.6, 0], [0, -1.4]].forEach(([oz, ox], i) => {
      d3.position.set(0.35 + ox, 0.75, oz);
      d3.rotation.set(0, 0, 0.15);
      d3.updateMatrix();
      throwInst.setMatrixAt(i, d3.matrix);
    });
    couchGroup.add(throwInst);

    // Glass coffee table
    const glassTop = new THREE.Mesh(new THREE.BoxGeometry(0.7, 0.04, 1.6), MAT.glassLite);
    glassTop.position.set(-1.5, 0.42, 0);
    couchGroup.add(glassTop);

    const tableLegMat = MAT.chrome;
    [[-0.25, -0.65], [0.25, -0.65], [-0.25, 0.65], [0.25, 0.65]].forEach(([ox, oz]) => {
      const leg = new THREE.Mesh(new THREE.CylinderGeometry(0.025, 0.025, 0.4, 8), tableLegMat);
      leg.position.set(-1.5 + ox, 0.2, oz);
      couchGroup.add(leg);
    });

    // TV
    const tvFrame = new THREE.Mesh(new THREE.BoxGeometry(0.06, 1.5, 2.8), new THREE.MeshStandardMaterial({ color: 0x111111, roughness: 0.3 }));
    tvFrame.position.set(2.35, 2.6, 0);
    couchGroup.add(tvFrame);
    const tvScreen = new THREE.Mesh(
      new THREE.BoxGeometry(0.02, 1.3, 2.6),
      new THREE.MeshStandardMaterial({ color: 0x111122, emissive: 0x112244, emissiveIntensity: 0.12 })
    );
    tvScreen.position.set(2.32, 2.6, 0);
    couchGroup.add(tvScreen);

    couchGroup.position.set(CX, 0, CZ);
    scene.add(couchGroup);
    hoverables.push({ mesh: couchGroup, zone: 'couch' });
  }

  // ═══════════════════════════════════════════════════════════════════
  //  FIREPLACE — stone surround, logs, fire, ember particles
  // ═══════════════════════════════════════════════════════════════════

  function buildFireplace() {
    const FX = -2, FZ = 5.5;
    const fpGroup = new THREE.Group();
    fpGroup.userData.zone = 'fireplace';

    // Hearth
    const hearth = new THREE.Mesh(new THREE.BoxGeometry(3.0, 0.08, 1.6), MAT.stone);
    hearth.position.set(0, 0.04, 0);
    hearth.receiveShadow = true;
    fpGroup.add(hearth);

    // Stone pillars
    [-1.2, 1.2].forEach(x => {
      const pillar = new THREE.Mesh(new THREE.BoxGeometry(0.35, 2.2, 0.8), MAT.stone);
      pillar.position.set(x, 1.1, 0);
      pillar.castShadow = true;
      fpGroup.add(pillar);
    });

    // Mantel — dark wood
    const mantelMat = new THREE.MeshStandardMaterial({ color: 0x3a2215, roughness: 0.5, metalness: 0.05 });
    const mantel = new THREE.Mesh(new THREE.BoxGeometry(3.0, 0.12, 0.9), mantelMat);
    mantel.position.set(0, 2.26, 0);
    mantel.castShadow = true;
    fpGroup.add(mantel);

    // Fire box interior
    const darkMat = new THREE.MeshStandardMaterial({ color: 0x1a1008, roughness: 0.95 });
    fpGroup.add(new THREE.Mesh(new THREE.BoxGeometry(2.0, 1.7, 0.1), darkMat).translateY(0.95).translateZ(0.4));
    fpGroup.add(new THREE.Mesh(new THREE.BoxGeometry(2.0, 0.06, 0.7), new THREE.MeshStandardMaterial({ color: 0x222228 })).translateY(0.11).translateZ(0.05));
    [-0.95, 0.95].forEach(x => {
      fpGroup.add(new THREE.Mesh(new THREE.BoxGeometry(0.08, 1.7, 0.7), darkMat).translateX(x).translateY(0.95).translateZ(0.05));
    });

    // Logs
    const logMat = new THREE.MeshStandardMaterial({ color: 0x5a3a20, roughness: 0.9 });
    const logGeo = new THREE.CylinderGeometry(0.07, 0.08, 0.9, 8);
    [{ y: 0.2, z: 0, r: 0 }, { y: 0.2, z: 0.15, r: 0.1 }, { y: 0.34, z: 0.07, r: -0.05 }].forEach(p => {
      const log = new THREE.Mesh(logGeo, logMat);
      log.position.set(0, p.y, p.z);
      log.rotation.z = Math.PI / 2;
      log.rotation.x = p.r;
      fpGroup.add(log);
    });

    // Animated fire geometry (layered orange/yellow triangles)
    const fireMats = [
      new THREE.MeshBasicMaterial({ color: 0xff4400, transparent: true, opacity: 0.7, blending: THREE.AdditiveBlending, depthWrite: false }),
      new THREE.MeshBasicMaterial({ color: 0xff8800, transparent: true, opacity: 0.5, blending: THREE.AdditiveBlending, depthWrite: false }),
      new THREE.MeshBasicMaterial({ color: 0xffcc22, transparent: true, opacity: 0.4, blending: THREE.AdditiveBlending, depthWrite: false }),
    ];
    fireMats.forEach((fm, i) => {
      const w = 0.7 - i * 0.15;
      const h = 0.6 - i * 0.1;
      const fireGeo = new THREE.ConeGeometry(w / 2, h, 6);
      const fireMesh = new THREE.Mesh(fireGeo, fm);
      fireMesh.position.set((i - 1) * 0.1, 0.18 + h / 2, 0.05);
      fpGroup.add(fireMesh);
    });

    // Embers (hot bed glow)
    const emberMat = new THREE.MeshStandardMaterial({
      color: 0xff3300, emissive: 0xff4400, emissiveIntensity: 0.7,
      transparent: true, opacity: 0.5,
    });
    const embers = new THREE.Mesh(new THREE.PlaneGeometry(0.9, 0.5), emberMat);
    embers.rotation.x = -Math.PI / 2;
    embers.position.set(0, 0.13, 0.05);
    fpGroup.add(embers);

    // Fire lights
    const fl1 = new THREE.PointLight(0xff6622, 0.8 * LPI, 5);
    fl1.position.set(0, 0.5, 0);
    fpGroup.add(fl1);
    fireLights.push(fl1);
    const fl2 = new THREE.PointLight(0xff4400, 0.4 * LPI, 3);
    fl2.position.set(-0.2, 0.35, 0.05);
    fpGroup.add(fl2);
    fireLights.push(fl2);

    // Ember particles — small spheres that rise
    const emberGeo = new THREE.SphereGeometry(0.015, 4, 4);
    const eMat = new THREE.MeshBasicMaterial({ color: 0xff6600, transparent: true, opacity: 0.8 });
    for (let i = 0; i < 12; i++) {
      const em = new THREE.Mesh(emberGeo, eMat.clone());
      em.position.set((Math.random() - 0.5) * 0.6, 0.2 + Math.random() * 0.8, (Math.random() - 0.5) * 0.3);
      fpGroup.add(em);
      emberParticles.push({
        mesh: em,
        vel: 0.15 + Math.random() * 0.25,
        life: Math.random(),
        baseX: (Math.random() - 0.5) * 0.6,
      });
    }

    // Candelabra on mantel
    [-0.9, 0.9].forEach(x => {
      const base = new THREE.Mesh(new THREE.CylinderGeometry(0.06, 0.08, 0.04, 12), MAT.gold);
      base.position.set(x, 2.34, 0);
      fpGroup.add(base);
      const stick = new THREE.Mesh(new THREE.CylinderGeometry(0.015, 0.015, 0.15, 8), new THREE.MeshStandardMaterial({ color: 0xfff5e0 }));
      stick.position.set(x, 2.43, 0);
      fpGroup.add(stick);
      const flame = new THREE.PointLight(0xff8800, 0.15 * LPI, 1.5);
      flame.position.set(x, 2.53, 0);
      fpGroup.add(flame);
      fireLights.push(flame);
    });

    // Fur rug in front
    const furMat = new THREE.MeshStandardMaterial({ color: 0x8b7355, roughness: 0.95, side: THREE.DoubleSide });
    const fur = new THREE.Mesh(new THREE.CircleGeometry(1.4, 24), furMat);
    fur.rotation.x = -Math.PI / 2;
    fur.position.set(0, 0.015, -1.5);
    fpGroup.add(fur);

    fpGroup.position.set(FX, 0, FZ);
    scene.add(fpGroup);
    hoverables.push({ mesh: fpGroup, zone: 'fireplace' });
  }

  // ═══════════════════════════════════════════════════════════════════
  //  BAR — granite counter, chrome stools, backlit shelving
  // ═══════════════════════════════════════════════════════════════════

  function buildBar() {
    const BRX = -3, BRZ = -5.5;
    const barGroup = new THREE.Group();
    barGroup.userData.zone = 'bar';

    // Counter body
    const counterBody = new THREE.Mesh(new THREE.BoxGeometry(2.4, 1.1, 0.55), MAT.granite);
    counterBody.position.set(0, 0.55, 0);
    counterBody.castShadow = true;
    barGroup.add(counterBody);

    // Granite countertop
    const topMat = new THREE.MeshStandardMaterial({ color: 0x0e0e14, roughness: 0.25, metalness: 0.2 });
    const top = new THREE.Mesh(new THREE.BoxGeometry(2.5, 0.06, 0.65), topMat);
    top.position.set(0, 1.12, 0);
    barGroup.add(top);

    // Chrome bar stools — InstancedMesh
    const seatGeo = new THREE.CylinderGeometry(0.2, 0.18, 0.08, 16);
    const seatMat = new THREE.MeshStandardMaterial({ color: 0x2a2a2a, roughness: 0.7 });
    const stoolSeatInst = new THREE.InstancedMesh(seatGeo, seatMat, 3);
    const legGeo = new THREE.CylinderGeometry(0.035, 0.035, 0.7, 8);
    const stoolLegInst = new THREE.InstancedMesh(legGeo, MAT.chrome, 3);
    const sd = new THREE.Object3D();
    [-0.7, 0, 0.7].forEach((ox, i) => {
      sd.position.set(ox, 0.72, 1.0);
      sd.updateMatrix();
      stoolSeatInst.setMatrixAt(i, sd.matrix);
      sd.position.set(ox, 0.35, 1.0);
      sd.updateMatrix();
      stoolLegInst.setMatrixAt(i, sd.matrix);
    });
    stoolSeatInst.castShadow = true;
    barGroup.add(stoolSeatInst);
    barGroup.add(stoolLegInst);

    // Backlit shelving panel (emissive)
    const shelfBackMat = new THREE.MeshStandardMaterial({
      color: 0x1a1a22, emissive: 0x334466, emissiveIntensity: 0.4,
    });
    const shelfBack = new THREE.Mesh(new THREE.BoxGeometry(2.0, 1.2, 0.08), shelfBackMat);
    shelfBack.position.set(0, 1.8, -0.25);
    barGroup.add(shelfBack);

    // Shelf surfaces
    const shelfMat = new THREE.MeshStandardMaterial({ color: 0x3a2215, roughness: 0.6 });
    [1.35, 1.65, 1.95].forEach(y => {
      const shelf = new THREE.Mesh(new THREE.BoxGeometry(2.0, 0.04, 0.2), shelfMat);
      shelf.position.set(0, y, -0.15);
      barGroup.add(shelf);
    });

    // Bottles
    [0xaa3333, 0x33aa33, 0x3333aa, 0xaa8833, 0x88aaaa, 0xaa55aa].forEach((c, i) => {
      const bottleMat = new THREE.MeshStandardMaterial({ color: c, transparent: true, opacity: 0.65, roughness: 0.15 });
      const bottle = new THREE.Mesh(new THREE.CylinderGeometry(0.04, 0.05, 0.22 + (i % 3) * 0.04, 8), bottleMat);
      bottle.position.set(-0.5 + i * 0.2, 1.48 + ((i < 3) ? 0 : 0.3), -0.15);
      barGroup.add(bottle);
    });

    barGroup.position.set(BRX, 0, BRZ);
    scene.add(barGroup);
    hoverables.push({ mesh: barGroup, zone: 'bar' });
  }

  // ═══════════════════════════════════════════════════════════════════
  //  VANITY — circular mirror, LED ring, marble countertop
  // ═══════════════════════════════════════════════════════════════════

  function buildVanity() {
    const VX = 3, VZ = -5.8;
    const vanGroup = new THREE.Group();
    vanGroup.userData.zone = 'vanity';

    // Marble countertop
    const counter = new THREE.Mesh(new THREE.BoxGeometry(1.8, 0.06, 0.6), MAT.marble);
    counter.position.set(0, 0.82, 0);
    vanGroup.add(counter);

    // Drawer body
    const drawer = new THREE.Mesh(new THREE.BoxGeometry(1.7, 0.5, 0.04), MAT.darkWood);
    drawer.position.set(0, 0.55, 0.3);
    vanGroup.add(drawer);

    // Gold drawer knobs
    [-0.4, 0.4].forEach(off => {
      const knob = new THREE.Mesh(new THREE.SphereGeometry(0.025, 8, 8), MAT.gold);
      knob.position.set(off, 0.55, 0.33);
      vanGroup.add(knob);
    });

    // Legs
    [[-0.82, -0.24], [0.82, -0.24], [-0.82, 0.24], [0.82, 0.24]].forEach(([ox, oz]) => {
      const leg = new THREE.Mesh(new THREE.CylinderGeometry(0.03, 0.04, 0.8, 8), MAT.darkWood);
      leg.position.set(ox, 0.4, oz);
      vanGroup.add(leg);
    });

    // Large circular mirror
    const mirrorGeo = new THREE.CircleGeometry(0.5, 32);
    const mirrorMesh = new THREE.Mesh(mirrorGeo, MAT.mirror);
    mirrorMesh.position.set(0, 1.45, -0.12);
    vanGroup.add(mirrorMesh);

    // Mirror gold frame (torus)
    const frameGeo = new THREE.TorusGeometry(0.52, 0.03, 8, 32);
    const frameMesh = new THREE.Mesh(frameGeo, MAT.gold);
    frameMesh.position.set(0, 1.45, -0.13);
    vanGroup.add(frameMesh);

    // LED ring light (emissive torus)
    const ringMat = new THREE.MeshStandardMaterial({
      color: 0xffffff, emissive: 0xffeedd, emissiveIntensity: 0.6,
    });
    const ring = new THREE.Mesh(new THREE.TorusGeometry(0.55, 0.012, 8, 32), ringMat);
    ring.position.set(0, 1.45, -0.11);
    vanGroup.add(ring);

    // Ring bloom
    const ringBloom = new THREE.Mesh(
      new THREE.TorusGeometry(0.55, 0.06, 8, 32),
      new THREE.MeshBasicMaterial({ color: 0xffeedd, transparent: true, opacity: 0.1, blending: THREE.AdditiveBlending, depthWrite: false })
    );
    ringBloom.position.copy(ring.position);
    vanGroup.add(ringBloom);

    // Stool
    const stoolPole = new THREE.Mesh(new THREE.CylinderGeometry(0.03, 0.03, 0.4, 8), MAT.chrome);
    stoolPole.position.set(0, 0.2, 0.9);
    vanGroup.add(stoolPole);
    const stoolSeat = new THREE.Mesh(
      new THREE.CylinderGeometry(0.22, 0.22, 0.06, 16),
      new THREE.MeshStandardMaterial({ color: 0xcc88aa, roughness: 0.85 })
    );
    stoolSeat.position.set(0, 0.43, 0.9);
    stoolSeat.castShadow = true;
    vanGroup.add(stoolSeat);

    // Perfume bottles
    [0, 0.15, 0.3].forEach((off, i) => {
      const bColor = [0xddaaff, 0xffccdd, 0xaaddff][i];
      const bMat = new THREE.MeshStandardMaterial({ color: bColor, transparent: true, opacity: 0.55, roughness: 0.1 });
      const bottle = new THREE.Mesh(new THREE.CylinderGeometry(0.02, 0.025, 0.08 + i * 0.02, 8), bMat);
      bottle.position.set(-0.3 + off, 0.90, 0.1);
      vanGroup.add(bottle);
    });

    vanGroup.position.set(VX, 0, VZ);
    scene.add(vanGroup);
    hoverables.push({ mesh: vanGroup, zone: 'vanity' });
  }

  // ═══════════════════════════════════════════════════════════════════
  //  BATHROOM — freestanding tub, glass shower, floor heating glow
  // ═══════════════════════════════════════════════════════════════════

  function buildBathroom() {
    const BTX = 6.5, BTZ = -4.5;
    const bathGroup = new THREE.Group();
    bathGroup.userData.zone = 'bath';

    // Partition wall
    const partMat = new THREE.MeshStandardMaterial({ color: 0x2a2a3d, roughness: 0.85 });
    const part = new THREE.Mesh(new THREE.BoxGeometry(0.1, 3.0, 4.0), partMat);
    part.position.set(-2.0, 1.5, 0);
    part.receiveShadow = true;
    bathGroup.add(part);

    // Frosted glass panel above partition
    const frost = new THREE.Mesh(new THREE.BoxGeometry(0.04, 1.2, 3.0), MAT.glassLite);
    frost.position.set(-2.0, 2.6, 0);
    bathGroup.add(frost);

    // Freestanding tub
    const tubMat = new THREE.MeshStandardMaterial({ color: 0xeeeeee, roughness: 0.15, metalness: 0.08 });
    const tubOuter = new THREE.Mesh(new THREE.CylinderGeometry(0.65, 0.6, 0.75, 24), tubMat);
    tubOuter.position.set(0, 0.38, 0);
    tubOuter.scale.set(1.0, 1.0, 2.2);
    tubOuter.castShadow = true;
    bathGroup.add(tubOuter);

    const tubInner = new THREE.Mesh(new THREE.CylinderGeometry(0.60, 0.55, 0.65, 24), MAT.whiteCeram);
    tubInner.position.set(0, 0.43, 0);
    tubInner.scale.set(0.95, 1.0, 2.1);
    bathGroup.add(tubInner);

    // Water surface
    const waterMat = new THREE.MeshStandardMaterial({ color: 0x4488bb, transparent: true, opacity: 0.4, roughness: 0.05, metalness: 0.1 });
    const water = new THREE.Mesh(new THREE.CylinderGeometry(0.55, 0.55, 0.02, 24), waterMat);
    water.position.set(0, 0.68, 0);
    water.scale.set(0.9, 1.0, 2.0);
    bathGroup.add(water);

    // Gold claw feet
    [[-0.4, -1.0], [0.4, -1.0], [-0.4, 1.0], [0.4, 1.0]].forEach(([ox, oz]) => {
      const foot = new THREE.Mesh(new THREE.SphereGeometry(0.06, 8, 8), MAT.gold);
      foot.position.set(ox, 0.06, oz);
      bathGroup.add(foot);
    });

    // Chrome faucet
    const fPost = new THREE.Mesh(new THREE.CylinderGeometry(0.02, 0.02, 0.35, 8), MAT.chrome);
    fPost.position.set(0, 0.92, -1.2);
    bathGroup.add(fPost);
    const fSpout = new THREE.Mesh(new THREE.CylinderGeometry(0.015, 0.015, 0.15, 8), MAT.chrome);
    fSpout.position.set(0, 1.08, -1.1);
    fSpout.rotation.x = Math.PI / 2.5;
    bathGroup.add(fSpout);

    // Glass shower enclosure
    const showerGlass = MAT.glassLite.clone();
    showerGlass.opacity = 0.18;
    // Two glass panels forming corner
    const sp1 = new THREE.Mesh(new THREE.BoxGeometry(0.03, 2.2, 1.2), showerGlass);
    sp1.position.set(-1.2, 1.1, 1.8);
    bathGroup.add(sp1);
    const sp2 = new THREE.Mesh(new THREE.BoxGeometry(1.0, 2.2, 0.03), showerGlass);
    sp2.position.set(-0.7, 1.1, 2.4);
    bathGroup.add(sp2);
    // Shower head
    const shHead = new THREE.Mesh(new THREE.CylinderGeometry(0.12, 0.12, 0.03, 12), MAT.chrome);
    shHead.position.set(-0.9, 2.1, 1.8);
    bathGroup.add(shHead);

    // Sink
    const sinkBowl = new THREE.Mesh(
      new THREE.SphereGeometry(0.22, 12, 8, 0, Math.PI * 2, 0, Math.PI * 0.5),
      MAT.whiteCeram
    );
    sinkBowl.position.set(0, 0.92, 2.3);
    sinkBowl.rotation.x = Math.PI;
    bathGroup.add(sinkBowl);
    const sinkPed = new THREE.Mesh(new THREE.BoxGeometry(0.08, 0.9, 0.2), MAT.whiteCeram);
    sinkPed.position.set(0, 0.45, 2.3);
    bathGroup.add(sinkPed);

    // Bathroom mirror
    const sinkMirror = new THREE.Mesh(new THREE.BoxGeometry(0.03, 0.8, 0.6), MAT.mirror);
    sinkMirror.position.set(1.35, 1.5, 2.3);
    bathGroup.add(sinkMirror);

    // Floor heating glow
    const heatMat = new THREE.MeshBasicMaterial({
      color: 0xff4400, transparent: true, opacity: 0.04, depthWrite: false,
    });
    const heatPlane = new THREE.Mesh(new THREE.PlaneGeometry(3, 4), heatMat);
    heatPlane.rotation.x = -Math.PI / 2;
    heatPlane.position.set(0, 0.02, 0);
    bathGroup.add(heatPlane);

    // Bath candles
    [[-0.45, -0.8], [0.45, -0.8]].forEach(([ox, oz]) => {
      const candle = new THREE.Mesh(new THREE.CylinderGeometry(0.04, 0.04, 0.12, 8), new THREE.MeshStandardMaterial({ color: 0xfff5e6 }));
      candle.position.set(ox, 0.82, oz);
      bathGroup.add(candle);
      const glow = new THREE.PointLight(0xff8800, 0.12 * LPI, 1.5);
      glow.position.set(ox, 0.90, oz);
      bathGroup.add(glow);
      fireLights.push(glow);
    });

    bathGroup.position.set(BTX, 0, BTZ);
    scene.add(bathGroup);
    hoverables.push({ mesh: bathGroup, zone: 'bath' });
  }

  // ═══════════════════════════════════════════════════════════════════
  //  BALCONY — glass railing, skyline silhouettes, outdoor furniture
  // ═══════════════════════════════════════════════════════════════════

  function buildBalcony() {
    const BAX = 5, BAZ = 5.5;
    const balcGroup = new THREE.Group();
    balcGroup.userData.zone = 'balcony';

    // Floor
    const balcFloor = new THREE.Mesh(
      new THREE.BoxGeometry(3.5, 0.1, 2.2),
      new THREE.MeshStandardMaterial({ color: 0x555555, roughness: 0.6 })
    );
    balcFloor.position.set(0, 0.05, 0);
    balcFloor.receiveShadow = true;
    balcGroup.add(balcFloor);

    // Glass railing panels
    const railGlass = MAT.glassLite.clone();
    railGlass.opacity = 0.2;
    // Front
    const frontPanel = new THREE.Mesh(new THREE.BoxGeometry(3.5, 0.9, 0.04), railGlass);
    frontPanel.position.set(0, 0.55, 1.1);
    balcGroup.add(frontPanel);
    // Sides
    [-1, 1].forEach(s => {
      const sidePanel = new THREE.Mesh(new THREE.BoxGeometry(0.04, 0.9, 2.2), railGlass);
      sidePanel.position.set(s * 1.7, 0.55, 0);
      balcGroup.add(sidePanel);
    });

    // Chrome rail top
    const railTop = new THREE.Mesh(new THREE.BoxGeometry(3.5, 0.04, 0.04), MAT.chrome);
    railTop.position.set(0, 1.02, 1.1);
    balcGroup.add(railTop);
    [-1, 1].forEach(s => {
      const sideRail = new THREE.Mesh(new THREE.BoxGeometry(0.04, 0.04, 2.2), MAT.chrome);
      sideRail.position.set(s * 1.7, 1.02, 0);
      balcGroup.add(sideRail);
    });

    // Outdoor table
    const oTableMat = new THREE.MeshStandardMaterial({ color: 0x4a4a4a, roughness: 0.5, metalness: 0.3 });
    const oTable = new THREE.Mesh(new THREE.BoxGeometry(0.65, 0.04, 0.65), oTableMat);
    oTable.position.set(0, 0.5, -0.2);
    balcGroup.add(oTable);
    const oLeg = new THREE.Mesh(new THREE.CylinderGeometry(0.03, 0.03, 0.4, 8), MAT.chrome);
    oLeg.position.set(0, 0.28, -0.2);
    balcGroup.add(oLeg);

    // Outdoor chairs
    const chairMat = new THREE.MeshStandardMaterial({ color: 0x3a3a3a, roughness: 0.6 });
    [-0.6, 0.6].forEach(off => {
      const chSeat = new THREE.Mesh(new THREE.BoxGeometry(0.4, 0.04, 0.4), chairMat);
      chSeat.position.set(off, 0.38, -0.7);
      balcGroup.add(chSeat);
      const chBack = new THREE.Mesh(new THREE.BoxGeometry(0.4, 0.4, 0.04), chairMat);
      chBack.position.set(off, 0.6, -0.9);
      balcGroup.add(chBack);
      // Legs
      [[-0.15, -0.15], [0.15, -0.15], [-0.15, 0.15], [0.15, 0.15]].forEach(([lx, lz]) => {
        const leg = new THREE.Mesh(new THREE.CylinderGeometry(0.015, 0.015, 0.36, 6), MAT.chrome);
        leg.position.set(off + lx, 0.18, -0.7 + lz);
        balcGroup.add(leg);
      });
    });

    // v1.58.0 [2026-06-11] — flat silhouette buildings removed; the full
    // instanced city now lives in buildCitySkyline().

    balcGroup.position.set(BAX, 0, BAZ);
    scene.add(balcGroup);
    hoverables.push({ mesh: balcGroup, zone: 'balcony' });
  }

  // ═══════════════════════════════════════════════════════════════════
  //  CITY LIGHTS — twinkling dots on skyline buildings
  // ═══════════════════════════════════════════════════════════════════

  function buildCitySkyline() {
    // v1.58.0 [2026-06-11] — Full NEONCITY exterior: two instanced building
    // rings (near + far) below the penthouse horizon, 220 twinkling window
    // lights, and a neon smog glow band. Visible through the south curtain
    // wall; replaces the old 80-floating-dots placeholder.

    // ── Building instances ──
    const bldgGeo = new THREE.BoxGeometry(1, 1, 1);
    const bldgMat = new THREE.MeshStandardMaterial({ color: 0x10131f, roughness: 0.9, metalness: 0.1, emissive: 0x131a33, emissiveIntensity: 0.55 });
    const NEAR = 26, FAR = 38;
    const inst = new THREE.InstancedMesh(bldgGeo, bldgMat, NEAR + FAR);
    const m = new THREE.Object3D();
    let bi = 0;
    // The penthouse is high up: buildings drop BELOW floor level, tops peeking
    // at varying heights — sells altitude + expanse.
    for (let i = 0; i < NEAR; i++) {
      const x = -22 + (i / NEAR) * 44 + (Math.random() - 0.5) * 1.2;
      const hgt = 3 + Math.random() * 9;
      const z = 10 + Math.random() * 5;
      m.position.set(x, hgt / 2 - 7 + Math.random() * 2.5, z);
      m.scale.set(1.4 + Math.random() * 1.8, hgt, 1.4 + Math.random() * 1.2);
      m.updateMatrix();
      inst.setMatrixAt(bi++, m.matrix);
    }
    for (let i = 0; i < FAR; i++) {
      const x = -34 + (i / FAR) * 68 + (Math.random() - 0.5) * 1.5;
      const hgt = 4 + Math.random() * 13;
      const z = 18 + Math.random() * 10;
      m.position.set(x, hgt / 2 - 8 + Math.random() * 3, z);
      m.scale.set(2 + Math.random() * 2.4, hgt, 1.8 + Math.random() * 1.6);
      m.updateMatrix();
      inst.setMatrixAt(bi++, m.matrix);
    }
    scene.add(inst);

    // ── Window lights (twinkle, animated in animate()) ──
    const dotGeo = new THREE.SphereGeometry(0.055, 4, 4);
    const count = 320;
    const dotInst = new THREE.InstancedMesh(
      dotGeo,
      new THREE.MeshBasicMaterial({ color: 0xffeebb }),
      count
    );
    const dm = new THREE.Object3D();
    for (let i = 0; i < count; i++) {
      const x = (Math.random() - 0.5) * 56;
      const y = -7 + Math.random() * 12;
      const z = 9.5 + Math.random() * 17;
      dm.position.set(x, y, z);
      dm.updateMatrix();
      dotInst.setMatrixAt(i, dm.matrix);
      cityDots.push({ idx: i, phase: Math.random() * Math.PI * 2 });
    }
    scene.add(dotInst);
    cityDots._inst = dotInst;

    // ── Neon smog band on the horizon (rose + violet + cyan washes) ──
    const glowColors = [0xfb7185, 0x9d71ea, 0x22d3ee];
    glowColors.forEach((c, i) => {
      const glow = new THREE.Mesh(
        new THREE.PlaneGeometry(70, 7),
        new THREE.MeshBasicMaterial({
          color: c, transparent: true, opacity: 0.13,
          blending: THREE.AdditiveBlending, depthWrite: false,
          side: THREE.DoubleSide,
        })
      );
      glow.position.set((i - 1) * 18, -2.5 + i * 0.8, 30 - i * 1.5);
      scene.add(glow);
    });
    // Night-sky gradient backdrop so silhouettes read against violet haze
    const skyMat = new THREE.ShaderMaterial({
      depthWrite: false,
      uniforms: {},
      vertexShader: 'varying vec2 vUv; void main(){ vUv = uv; gl_Position = projectionMatrix * modelViewMatrix * vec4(position,1.0); }',
      fragmentShader: 'varying vec2 vUv; void main(){ vec3 top = vec3(0.013,0.008,0.045); vec3 hor = vec3(0.16,0.05,0.14); vec3 c = mix(hor, top, smoothstep(0.0,0.55,vUv.y)); gl_FragColor = vec4(c,1.0); }',
    });
    const sky = new THREE.Mesh(new THREE.PlaneGeometry(160, 60), skyMat);
    sky.position.set(0, 8, 48);
    sky.rotation.y = Math.PI;
    scene.add(sky);
  }

  // ═══════════════════════════════════════════════════════════════════
  //  WALL CLOCK — rotating hands
  // ═══════════════════════════════════════════════════════════════════

  function buildWallClock() {
    const cx = 0, cy = 3.0, cz = -ROOM.d / 2 + 0.08;
    // Face
    const face = new THREE.Mesh(new THREE.CircleGeometry(0.35, 24), new THREE.MeshStandardMaterial({ color: 0x1a1a22, roughness: 0.5 }));
    face.position.set(cx, cy, cz);
    scene.add(face);
    // Rim
    const rim = new THREE.Mesh(new THREE.TorusGeometry(0.36, 0.02, 8, 24), MAT.gold);
    rim.position.set(cx, cy, cz);
    scene.add(rim);
    // Hour marks
    for (let i = 0; i < 12; i++) {
      const a = (i / 12) * Math.PI * 2;
      const mark = new THREE.Mesh(
        new THREE.BoxGeometry(0.02, 0.06, 0.01),
        MAT.gold
      );
      mark.position.set(cx + Math.sin(a) * 0.3, cy + Math.cos(a) * 0.3, cz + 0.01);
      mark.rotation.z = -a;
      scene.add(mark);
    }
    // Hands
    const handMat = new THREE.MeshStandardMaterial({ color: 0xcccccc, metalness: 0.6 });
    const minuteHand = new THREE.Mesh(new THREE.BoxGeometry(0.012, 0.25, 0.008), handMat);
    minuteHand.geometry.translate(0, 0.125, 0);
    minuteHand.position.set(cx, cy, cz + 0.02);
    scene.add(minuteHand);
    clockHands.minute = minuteHand;

    const hourHand = new THREE.Mesh(new THREE.BoxGeometry(0.016, 0.18, 0.008), handMat);
    hourHand.geometry.translate(0, 0.09, 0);
    hourHand.position.set(cx, cy, cz + 0.025);
    scene.add(hourHand);
    clockHands.hour = hourHand;

    // Center dot
    const dot = new THREE.Mesh(new THREE.SphereGeometry(0.02, 8, 8), MAT.gold);
    dot.position.set(cx, cy, cz + 0.03);
    scene.add(dot);
  }

  // ═══════════════════════════════════════════════════════════════════
  //  RAIN EFFECT — animated drops on window glass
  // ═══════════════════════════════════════════════════════════════════

  let rainCurtain = null;  // v1.58.0 — exterior GPU rain (shader uniform time)

  function buildRainEffect() {
    // Rain drops running down the curtain-wall glass (interior side)
    const dropGeo = new THREE.CylinderGeometry(0.004, 0.004, 0.06, 4);
    const dropMat = new THREE.MeshBasicMaterial({ color: 0x88bbee, transparent: true, opacity: 0.35 });
    for (let i = 0; i < 40; i++) {
      const drop = new THREE.Mesh(dropGeo, dropMat);
      const x = (Math.random() - 0.5) * (ROOM.w - 2);
      const y = 0.5 + Math.random() * 3;
      const z = ROOM.d / 2 - 0.08;
      drop.position.set(x, y, z);
      scene.add(drop);
      rainDrops.push({ mesh: drop, speed: 0.8 + Math.random() * 1.2, startX: x });
    }

    // v1.58.0 [2026-06-11] — Exterior rain curtain: 600 GPU streaks falling
    // over the city. Static LineSegments; a vertex shader wraps Y by time,
    // so the per-frame cost is one uniform write.
    const COUNT = 600;
    const SPAN_Y = 18;
    const positions = new Float32Array(COUNT * 2 * 3);
    const seeds = new Float32Array(COUNT * 2);
    for (let i = 0; i < COUNT; i++) {
      const x = (Math.random() - 0.5) * 50;
      const y = Math.random() * SPAN_Y;
      const z = 8.5 + Math.random() * 16;
      const len = 0.35 + Math.random() * 0.45;
      positions.set([x, y, z, x, y - len, z], i * 6);
      const seed = Math.random();
      seeds[i * 2] = seed;
      seeds[i * 2 + 1] = seed;
    }
    const geo = new THREE.BufferGeometry();
    geo.setAttribute('position', new THREE.BufferAttribute(positions, 3));
    geo.setAttribute('seed', new THREE.BufferAttribute(seeds, 1));
    const mat = new THREE.ShaderMaterial({
      transparent: true,
      depthWrite: false,
      uniforms: { uTime: { value: 0 } },
      vertexShader: `
        uniform float uTime;
        attribute float seed;
        varying float vAlpha;
        void main() {
          vec3 p = position;
          float speed = 6.0 + seed * 5.0;
          p.y = mod(p.y - uTime * speed, ${SPAN_Y.toFixed(1)}) - 8.0;
          vAlpha = 0.12 + seed * 0.18;
          gl_Position = projectionMatrix * modelViewMatrix * vec4(p, 1.0);
        }`,
      fragmentShader: `
        varying float vAlpha;
        void main() { gl_FragColor = vec4(0.62, 0.74, 0.95, vAlpha); }`,
    });
    rainCurtain = new THREE.LineSegments(geo, mat);
    rainCurtain.frustumCulled = false;
    scene.add(rainCurtain);
  }

  // ═══════════════════════════════════════════════════════════════════
  //  ACCENT TRIM — v1.58.0 [2026-06-11] rose/violet emissive light-lines
  //  on the key furniture zones (Dark Renaissance luxury signature).
  //  Intensity breathes in animate() via MAT.roseTrim / MAT.violetTrim.
  // ═══════════════════════════════════════════════════════════════════

  function buildAccentTrim() {
    const trims = [
      // Bed platform underglow (zone center -5,-1; platform 3.6×4.8)
      { mat: 'roseTrim',   size: [3.7, 0.025, 0.05], pos: [-5, 0.05, -1 + 2.42] },
      { mat: 'roseTrim',   size: [3.7, 0.025, 0.05], pos: [-5, 0.05, -1 - 2.42] },
      { mat: 'roseTrim',   size: [0.05, 0.025, 4.9], pos: [-5 + 1.87, 0.05, -1] },
      { mat: 'roseTrim',   size: [0.05, 0.025, 4.9], pos: [-5 - 1.87, 0.05, -1] },
      // Couch base glow (zone 5.5, 0)
      { mat: 'roseTrim',   size: [3.0, 0.02, 0.04],  pos: [5.5, 0.07, 0.95] },
      // Bar counter edge (zone -3, -5.5)
      { mat: 'violetTrim', size: [2.6, 0.025, 0.04], pos: [-3, 1.08, -4.95] },
      // Vanity mirror halo strips (zone 3, -5.8)
      { mat: 'violetTrim', size: [0.04, 0.9, 0.03],  pos: [2.35, 1.7, -5.85] },
      { mat: 'violetTrim', size: [0.04, 0.9, 0.03],  pos: [3.65, 1.7, -5.85] },
      // Bath rim glow (zone 6.5, -4.5)
      { mat: 'violetTrim', size: [1.7, 0.02, 0.04],  pos: [6.4, 0.62, -3.7] },
    ];
    trims.forEach(tr => {
      const mesh = new THREE.Mesh(new THREE.BoxGeometry(...tr.size), MAT[tr.mat]);
      mesh.position.set(...tr.pos);
      scene.add(mesh);
    });
  }

  // ═══════════════════════════════════════════════════════════════════
  //  DECORATIONS — chandelier, pictures, vase, sconces
  // ═══════════════════════════════════════════════════════════════════

  function buildDecorations() {
    // Pendant chandelier (with subtle sway)
    const chanGroup = new THREE.Group();

    const chanMat = new THREE.MeshStandardMaterial({
      color: 0xddccaa, emissive: 0xffddaa, emissiveIntensity: 0.35,
      metalness: 0.4, roughness: 0.3,
    });
    const chanFrame = new THREE.Mesh(new THREE.TorusGeometry(0.5, 0.02, 8, 24), chanMat);
    chanFrame.rotation.x = Math.PI / 2;
    chanGroup.add(chanFrame);

    // Chain
    const chainMat = new THREE.MeshStandardMaterial({ color: 0xccaa66, metalness: 0.8, roughness: 0.2 });
    const chain = new THREE.Mesh(new THREE.CylinderGeometry(0.01, 0.01, 0.5, 6), chainMat);
    chain.position.y = 0.35;
    chanGroup.add(chain);

    // Crystals
    const crystalMat = new THREE.MeshStandardMaterial({
      color: 0xffffff, transparent: true, opacity: 0.45, roughness: 0.05, metalness: 0.3,
    });
    for (let i = 0; i < 12; i++) {
      const a = (i / 12) * Math.PI * 2;
      const crystal = new THREE.Mesh(new THREE.OctahedronGeometry(0.04, 0), crystalMat);
      crystal.position.set(Math.cos(a) * 0.5, -0.1, Math.sin(a) * 0.5);
      chanGroup.add(crystal);
    }

    // Chandelier bloom
    const chanBloom = new THREE.Mesh(
      new THREE.SphereGeometry(0.6, 8, 8),
      new THREE.MeshBasicMaterial({ color: 0xffddaa, transparent: true, opacity: 0.06, blending: THREE.AdditiveBlending, depthWrite: false })
    );
    chanBloom.position.y = -0.05;
    chanGroup.add(chanBloom);

    const chanLight = new THREE.PointLight(0xffeecc, 0.5 * LPI, 10);
    chanLight.position.y = -0.1;
    chanGroup.add(chanLight);

    chanGroup.position.set(0, 3.55, 0);
    scene.add(chanGroup);
    pendantGroup.group = chanGroup;

    // Picture frames on back wall
    [{ x: -5, c: 0x663344, w: 1.0, h: 0.7 },
     { x: 0.0, c: 0x334466, w: 0.8, h: 1.0 },
     { x: 5.5, c: 0x446644, w: 0.9, h: 0.6 }].forEach(p => {
      const frameMat = new THREE.MeshStandardMaterial({ color: 0x8b7355, roughness: 0.5 });
      _box(p.w + 0.15, p.h + 0.15, 0.04, frameMat, p.x, 2.8, -ROOM.d / 2 + 0.08, { cast: false });
      const artMat = new THREE.MeshStandardMaterial({ color: p.c, roughness: 0.7 });
      _box(p.w, p.h, 0.02, artMat, p.x, 2.8, -ROOM.d / 2 + 0.12, { cast: false });
    });

    // Floor vase near balcony
    const vaseMat = new THREE.MeshStandardMaterial({ color: 0x445566, roughness: 0.25, metalness: 0.15 });
    _mesh(new THREE.CylinderGeometry(0.12, 0.15, 0.5, 12), vaseMat, 2, 0.25, 5.5);
    const stemMat = new THREE.MeshStandardMaterial({ color: 0x2d5a2d });
    _mesh(new THREE.CylinderGeometry(0.01, 0.01, 0.6, 6), stemMat, 2, 0.7, 5.5);
    const leafMat = new THREE.MeshStandardMaterial({ color: 0x2d6b2d, roughness: 0.9 });
    _mesh(new THREE.SphereGeometry(0.3, 8, 8), leafMat, 2, 1.0, 5.5);

    // Wall sconces
    [-1, 1].forEach(side => {
      const sconceBracket = new THREE.Mesh(
        new THREE.BoxGeometry(0.08, 0.15, 0.1),
        MAT.gold
      );
      sconceBracket.position.set(side * 7.9, 2.2, -2);
      scene.add(sconceBracket);
      const sLight = new THREE.PointLight(0xffddaa, 0.2 * LPI, 4);
      sLight.position.set(side * 7.8, 2.3, -2);
      scene.add(sLight);
    });
  }

  // ═══════════════════════════════════════════════════════════════════
  //  POST-PROCESSING SIMULATION (bloom copies, vignette, grain)
  // ═══════════════════════════════════════════════════════════════════

  function createPostFX() {
    // Vignette overlay — a plane near camera with radial gradient via vertex colors
    const vigGeo = new THREE.PlaneGeometry(2, 2, 16, 16);
    const positions = vigGeo.attributes.position;
    const colors = new Float32Array(positions.count * 3);
    for (let i = 0; i < positions.count; i++) {
      const x = positions.getX(i);
      const y = positions.getY(i);
      const dist = Math.sqrt(x * x + y * y);
      const alpha = Math.pow(Math.min(dist / 1.2, 1.0), 2.5);
      colors[i * 3] = alpha * 0.02;
      colors[i * 3 + 1] = alpha * 0.02;
      colors[i * 3 + 2] = alpha * 0.03;
    }
    vigGeo.setAttribute('color', new THREE.BufferAttribute(colors, 3));
    const vigMat = new THREE.MeshBasicMaterial({
      vertexColors: true, transparent: true, opacity: 0.7,
      depthTest: false, depthWrite: false,
    });
    vignetteQuad = new THREE.Mesh(vigGeo, vigMat);
    vignetteQuad.renderOrder = 999;
    vignetteQuad.frustumCulled = false;

    // Grain overlay — noise texture simulated via many tiny random dots
    const grainGeo = new THREE.PlaneGeometry(2, 2);
    const grainMat = new THREE.MeshBasicMaterial({
      color: 0x888888, transparent: true, opacity: 0.02,
      depthTest: false, depthWrite: false,
    });
    grainQuad = new THREE.Mesh(grainGeo, grainMat);
    grainQuad.renderOrder = 1000;
    grainQuad.frustumCulled = false;
  }

  // ═══════════════════════════════════════════════════════════════════
  //  INTERACTIVE RAYCASTING
  // ═══════════════════════════════════════════════════════════════════

  function onMouseMove(ev) {
    const rect = renderer.domElement.getBoundingClientRect();
    mouse.x = ((ev.clientX - rect.left) / rect.width) * 2 - 1;
    mouse.y = -((ev.clientY - rect.top) / rect.height) * 2 + 1;
  }

  function onMouseClick() {
    if (hoveredObj && ZONE_MAP[hoveredObj]) {
      switchView(ZONE_MAP[hoveredObj]);
    }
  }

  function updateRaycast() {
    raycaster.setFromCamera(mouse, camera);
    let hit = null;
    for (let i = 0; i < hoverables.length; i++) {
      const h = hoverables[i];
      const targets = [];
      h.mesh.traverse(c => { if (c.isMesh) targets.push(c); });
      const intersects = raycaster.intersectObjects(targets, false);
      if (intersects.length > 0) {
        hit = h.zone;
        break;
      }
    }

    if (hit !== hoveredObj) {
      // Unhighlight old
      if (hoveredObj) {
        const old = hoverables.find(h => h.zone === hoveredObj);
        if (old) {
          old.mesh.traverse(c => {
            if (c.isMesh && c.material && c.material.emissive && !c.material._origEmissive) {
              c.material.emissiveIntensity = c.material._savedEI || 0;
            }
          });
        }
      }
      hoveredObj = hit;
      // Highlight new
      if (hoveredObj) {
        const cur = hoverables.find(h => h.zone === hoveredObj);
        if (cur) {
          cur.mesh.traverse(c => {
            if (c.isMesh && c.material && c.material.emissive) {
              if (c.material._savedEI === undefined) c.material._savedEI = c.material.emissiveIntensity;
              c.material.emissiveIntensity = (c.material._savedEI || 0) + 0.15;
            }
          });
        }
      }
      renderer.domElement.style.cursor = hoveredObj ? 'pointer' : '';
    }
  }

  // ═══════════════════════════════════════════════════════════════════
  //  ANIMATION LOOP
  // ═══════════════════════════════════════════════════════════════════

  function animate() {
    requestAnimationFrame(animate);
    const dt = Math.min(clock.getDelta(), 0.05); // cap for tab-away
    const t = clock.elapsedTime;

    // ── Camera transitions ──
    if (cameraAnimating && _cameraAnim) {
      _cameraAnim.progress += dt / 1.5; // 1.5s transition
      if (_cameraAnim.progress >= 1) {
        _cameraAnim.progress = 1;
        cameraAnimating = false;
      }
      const p = cubicEase(_cameraAnim.progress);
      camera.position.lerpVectors(_cameraAnim.fromPos, _cameraAnim.toPos, p);
      controls.target.lerpVectors(_cameraAnim.fromTarget, _cameraAnim.toTarget, p);
      if (_cameraAnim.fromFov !== _cameraAnim.toFov) {
        camera.fov = _cameraAnim.fromFov + (_cameraAnim.toFov - _cameraAnim.fromFov) * p;
        camera.updateProjectionMatrix();
      }
    }

    // ── First-person movement ──
    updateFPS(dt);

    // ── Auto-orbit in overview ──
    if (currentView === 'overview' && !cameraAnimating) {
      autoOrbitAngle += dt * 0.05;
      const radius = camera.position.length();
      const baseAngle = Math.atan2(camera.position.z, camera.position.x);
      // Very subtle — just nudge the controls autoRotate
      controls.autoRotate = true;
      controls.autoRotateSpeed = 0.3;
    } else {
      controls.autoRotate = false;
    }

    controls.update();

    // ── Fireplace flicker ──
    for (let i = 0; i < fireLights.length; i++) {
      const fl = fireLights[i];
      fl.intensity = fl.intensity * 0.85 + (0.3 + 0.5 * Math.random() + 0.2 * Math.sin(t * 10 + i * 1.7)) * 0.15 * LPI;  // v1.58.0 — physical units
      // Slight color shift
      const warmth = 0.9 + 0.1 * Math.sin(t * 6 + i);
      fl.color.setRGB(1.0, warmth * 0.45, warmth * 0.15);
    }

    // ── Ember particles ──
    for (let i = 0; i < emberParticles.length; i++) {
      const em = emberParticles[i];
      em.life += dt * em.vel;
      if (em.life > 1.0) {
        em.life = 0;
        em.mesh.position.set(em.baseX, 0.2, (Math.random() - 0.5) * 0.3);
      }
      em.mesh.position.y = 0.2 + em.life * 1.2;
      em.mesh.position.x = em.baseX + Math.sin(t * 3 + i) * 0.08;
      em.mesh.material.opacity = 0.8 * (1.0 - em.life);
    }

    // ── Neon strip pulse — v1.58.0: rose hue drifting toward violet ──
    const neonPulse = 0.75 + 0.15 * Math.sin(t * 1.2);
    for (let i = 0; i < neonStrips.length; i++) {
      const ns = neonStrips[i];
      ns.mesh.material.opacity = neonPulse;
      // Drift between rose (0.985) and violet (~0.78) per-strip phase
      const hue = (ns.baseHue + Math.sin(t * 0.25 + i * 0.8) * 0.045) % 1;
      ns.mesh.material.color.setHSL(hue, 0.78, 0.62);
    }
    // Furniture rose trim breathing
    if (MAT.roseTrim)   MAT.roseTrim.emissiveIntensity   = 1.4 + 0.5 * Math.sin(t * 1.6);
    if (MAT.violetTrim) MAT.violetTrim.emissiveIntensity = 1.1 + 0.4 * Math.sin(t * 1.3 + 1.5);
    // Bloom copies track neon
    for (let i = 0; i < bloomCopies.length; i++) {
      bloomCopies[i].material.opacity = 0.08 + 0.04 * Math.sin(t * 1.2);
    }

    // ── City lights twinkle ──
    if (cityDots._inst) {
      const col = new THREE.Color();
      for (let i = 0; i < cityDots.length; i++) {
        const cd = cityDots[i];
        const brightness = 0.3 + 0.7 * (0.5 + 0.5 * Math.sin(t * (0.5 + (cd.phase % 1) * 2) + cd.phase));
        col.setRGB(brightness, brightness * 0.9, brightness * 0.7);
        cityDots._inst.setColorAt(cd.idx, col);
      }
      cityDots._inst.instanceColor.needsUpdate = true;
    }

    // ── Chandelier sway ──
    if (pendantGroup.group) {
      pendantGroup.group.rotation.x = Math.sin(t * 0.4) * 0.008;
      pendantGroup.group.rotation.z = Math.cos(t * 0.3) * 0.006;
    }

    // ── Clock hands ──
    if (clockHands.minute) {
      clockHands.minute.rotation.z = -t * 0.1;
      clockHands.hour.rotation.z = -t * 0.008;
    }

    // ── Rain drops (glass) + exterior curtain ──
    for (let i = 0; i < rainDrops.length; i++) {
      const rd = rainDrops[i];
      rd.mesh.position.y -= rd.speed * dt;
      if (rd.mesh.position.y < 0.1) {
        rd.mesh.position.y = 3.5 + Math.random() * 0.5;
        rd.mesh.position.x = rd.startX + (Math.random() - 0.5) * 0.5;
      }
    }
    if (rainCurtain) rainCurtain.material.uniforms.uTime.value = t;  // v1.58.0

    // ── Grain flicker ──
    if (grainQuad) {
      grainQuad.material.opacity = 0.015 + Math.random() * 0.01;
    }

    // ── Raycasting (throttled) ──
    if (Math.floor(t * 10) % 2 === 0) {
      updateRaycast();
    }

    // ── Post-FX overlays attach to camera ──
    if (vignetteQuad) {
      vignetteQuad.position.copy(camera.position);
      vignetteQuad.quaternion.copy(camera.quaternion);
      vignetteQuad.translateZ(-0.11);
      if (!vignetteQuad.parent) scene.add(vignetteQuad);
    }
    if (grainQuad) {
      grainQuad.position.copy(camera.position);
      grainQuad.quaternion.copy(camera.quaternion);
      grainQuad.translateZ(-0.105);
      if (!grainQuad.parent) scene.add(grainQuad);
    }

    // ── External animation callbacks (character models, etc.) ──
    const cbs = window._penthouse3D_animCallbacks;
    if (cbs) {
      for (let i = 0; i < cbs.length; i++) {
        try { cbs[i](dt, t); } catch (e) { console.warn('[Penthouse3D] anim callback error:', e); }
      }
    }

    renderer.render(scene, camera);
  }

  // ═══════════════════════════════════════════════════════════════════
  //  CAMERA VIEW SWITCHING
  // ═══════════════════════════════════════════════════════════════════

  function switchView(viewName) {
    const view = CAMERA_VIEWS[viewName];
    if (!view) return;

    _cameraAnim = {
      fromPos:    camera.position.clone(),
      toPos:      new THREE.Vector3(view.pos.x, view.pos.y, view.pos.z),
      fromTarget: controls.target.clone(),
      toTarget:   new THREE.Vector3(view.target.x, view.target.y, view.target.z),
      fromFov:    camera.fov,
      toFov:      view.fov || 55,
      progress:   0,
    };
    cameraAnimating = true;
    currentView = viewName;
  }

  // ═══════════════════════════════════════════════════════════════════
  //  FIRST-PERSON CAMERA MODE
  // ═══════════════════════════════════════════════════════════════════

  let fpsMode = false;
  const fpsState = {
    euler: new THREE.Euler(0, 0, 0, 'YXZ'),
    moveForward: false,
    moveBackward: false,
    moveLeft: false,
    moveRight: false,
    moveUp: false,
    moveDown: false,
    speed: 4.0,
    lookSensitivity: 0.002,
    playerHeight: 1.7,
  };
  const fpsDirection = new THREE.Vector3();
  const fpsSideDir = new THREE.Vector3();

  function enterFirstPerson() {
    fpsMode = true;
    controls.enabled = false;
    camera.fov = 70;
    camera.updateProjectionMatrix();
    camera.position.set(0, fpsState.playerHeight, 0);
    fpsState.euler.set(0, 0, 0, 'YXZ');

    const canvas = renderer.domElement;
    canvas.requestPointerLock = canvas.requestPointerLock || canvas.mozRequestPointerLock;
    canvas.requestPointerLock();

    document.addEventListener('mousemove', fpsMouseMove, false);
    document.addEventListener('keydown', fpsKeyDown, false);
    document.addEventListener('keyup', fpsKeyUp, false);
    document.addEventListener('pointerlockchange', fpsPointerLockChange, false);
    document.addEventListener('mozpointerlockchange', fpsPointerLockChange, false);
  }

  function exitFirstPerson() {
    fpsMode = false;
    controls.enabled = true;
    fpsState.moveForward = fpsState.moveBackward = fpsState.moveLeft = fpsState.moveRight = false;
    fpsState.moveUp = fpsState.moveDown = false;

    if (document.pointerLockElement) {
      document.exitPointerLock = document.exitPointerLock || document.mozExitPointerLock;
      document.exitPointerLock();
    }

    document.removeEventListener('mousemove', fpsMouseMove, false);
    document.removeEventListener('keydown', fpsKeyDown, false);
    document.removeEventListener('keyup', fpsKeyUp, false);
    document.removeEventListener('pointerlockchange', fpsPointerLockChange, false);
    document.removeEventListener('mozpointerlockchange', fpsPointerLockChange, false);

    switchView('overview');
  }

  function fpsPointerLockChange() {
    if (!document.pointerLockElement && !document.mozPointerLockElement) {
      if (fpsMode) exitFirstPerson();
    }
  }

  function fpsMouseMove(ev) {
    if (!fpsMode) return;
    fpsState.euler.setFromQuaternion(camera.quaternion);
    fpsState.euler.y -= ev.movementX * fpsState.lookSensitivity;
    fpsState.euler.x -= ev.movementY * fpsState.lookSensitivity;
    fpsState.euler.x = Math.max(-Math.PI / 2.2, Math.min(Math.PI / 2.2, fpsState.euler.x));
    camera.quaternion.setFromEuler(fpsState.euler);
  }

  function fpsKeyDown(ev) {
    switch (ev.code) {
      case 'KeyW': case 'ArrowUp':    fpsState.moveForward  = true; break;
      case 'KeyS': case 'ArrowDown':  fpsState.moveBackward = true; break;
      case 'KeyA': case 'ArrowLeft':  fpsState.moveLeft     = true; break;
      case 'KeyD': case 'ArrowRight': fpsState.moveRight    = true; break;
      case 'Space':                   fpsState.moveUp       = true; ev.preventDefault(); break;
      case 'ShiftLeft':               fpsState.moveDown     = true; break;
      case 'Escape':                  exitFirstPerson(); break;
    }
  }

  function fpsKeyUp(ev) {
    switch (ev.code) {
      case 'KeyW': case 'ArrowUp':    fpsState.moveForward  = false; break;
      case 'KeyS': case 'ArrowDown':  fpsState.moveBackward = false; break;
      case 'KeyA': case 'ArrowLeft':  fpsState.moveLeft     = false; break;
      case 'KeyD': case 'ArrowRight': fpsState.moveRight    = false; break;
      case 'Space':                   fpsState.moveUp       = false; break;
      case 'ShiftLeft':               fpsState.moveDown     = false; break;
    }
  }

  function updateFPS(dt) {
    if (!fpsMode) return;
    camera.getWorldDirection(fpsDirection);
    fpsDirection.y = 0;
    fpsDirection.normalize();
    fpsSideDir.crossVectors(camera.up, fpsDirection).normalize();

    const speed = fpsState.speed * dt;
    if (fpsState.moveForward)  camera.position.addScaledVector(fpsDirection, speed);
    if (fpsState.moveBackward) camera.position.addScaledVector(fpsDirection, -speed);
    if (fpsState.moveLeft)     camera.position.addScaledVector(fpsSideDir, speed);
    if (fpsState.moveRight)    camera.position.addScaledVector(fpsSideDir, -speed);
    if (fpsState.moveUp)       camera.position.y += speed * 0.6;
    if (fpsState.moveDown)     camera.position.y -= speed * 0.6;

    // Clamp to room bounds
    const hw = ROOM.w / 2 - 0.3;
    const hd = ROOM.d / 2 - 0.3;
    camera.position.x = Math.max(-hw, Math.min(hw, camera.position.x));
    camera.position.z = Math.max(-hd, Math.min(hd, camera.position.z));
    camera.position.y = Math.max(0.5, Math.min(ROOM.h - 0.2, camera.position.y));
  }

  function toggleFirstPersonMode() {
    if (fpsMode) {
      exitFirstPerson();
      return false;
    } else {
      enterFirstPerson();
      return true;
    }
  }

  // ═══════════════════════════════════════════════════════════════════
  //  RESIZE
  // ═══════════════════════════════════════════════════════════════════

  function onResize() {
    const container = document.getElementById('scene-container');
    if (!container || !renderer) return;
    const w = container.clientWidth;
    const h = container.clientHeight;
    camera.aspect = w / h;
    camera.updateProjectionMatrix();
    renderer.setSize(w, h);
  }

  // ═══════════════════════════════════════════════════════════════════
  //  BOOTSTRAP
  // v1.49.2 [2026-03-22] — Wrapped in try/catch, fires penthouse3d:ready event
  // ═══════════════════════════════════════════════════════════════════

  function _safeInit() {
    try {
      init();
      _initialized = true;
      // Fire queued callbacks
      for (const cb of _readyCallbacks) {
        try { cb(window.penthouse3D); } catch (e) { console.warn('[Penthouse3D] onReady callback error:', e); }
      }
      _readyCallbacks.length = 0;
      // Emit custom event for listeners
      document.dispatchEvent(new CustomEvent('penthouse3d:ready', { detail: window.penthouse3D }));
      console.debug('[Penthouse3D] Initialized successfully');
    } catch (err) {
      _initError = err;
      console.error('[Penthouse3D] Initialization FAILED:', err);
      document.dispatchEvent(new CustomEvent('penthouse3d:error', { detail: err }));
    }
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', _safeInit);
  } else {
    _safeInit();
  }

})();
