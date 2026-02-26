/**
 * Bedroom Scene v5 — Director Control Center
 * Three.js 3D room + full Director UI (stats, scenarios, props, events, interactions, settings)
 */

// ─── Three.js globals ──────────────────────────────────────────────────
let scene, camera, renderer, controls;
let ambientLight, directionalLight, pointLights = [];
let clock = new THREE.Clock();

// Location 3D markers  { id → THREE.Mesh }
const locationMarkers = {};
// Character sprites { charId → { group, ring, targetPos } }
const charSprites = {};
// Color palette for characters
const CHAR_COLORS = ['#ff6b9d', '#51cf66', '#64b5f6', '#ffd54f'];

// ─── App state ─────────────────────────────────────────────────────────
let sceneState = {};
let agentRunning = false;
let socket = null;
let allCharacters = [];     // from /api/characters/list
let timeOfDay = 'evening';

// Director-side constants (loaded from /api/meta/constants)
let POSITIONS = [];
let OUTFITS = [];
let SCENARIOS = {};
let PERSONALITIES = {};

// Feed filter state
let activeFeedFilter = '';

// FPS
let lastFpsTime = performance.now();
let fpsFrames = 0;

// ─── Configuration ─────────────────────────────────────────────────────
const CONFIG = {
    cameraPos: { x: 10, y: 8, z: 10 },
    cameraTarget: { x: 0, y: 1, z: 0 },
    roomSize: { w: 16, h: 4, d: 14 },
};

// Camera view presets — each wall/area of the room gets a dedicated close-up
const CAMERA_VIEWS = {
    overview:  { pos: { x: 10, y: 9, z: 10 }, target: { x: 0, y: 0.5, z: 0 }, fov: 55, label: '🏠 Overview' },
    bed:       { pos: { x: -1, y: 3, z: -1 },  target: { x: -5, y: 0.6, z: -1 }, fov: 48, label: '🛏 Bed' },
    couch:     { pos: { x: 1, y: 3, z: 0 },    target: { x: 5.5, y: 0.6, z: 0 }, fov: 48, label: '🛋 Couch' },
    bath:      { pos: { x: 3, y: 2.5, z: -3 }, target: { x: 6.5, y: 0.5, z: -4.5 }, fov: 46, label: '🛁 Bath' },
    fireplace: { pos: { x: 2, y: 2.5, z: 2 },  target: { x: -2, y: 0.6, z: 4.5 }, fov: 48, label: '🔥 Fireplace' },
    vanity:    { pos: { x: 0, y: 2.5, z: -3 }, target: { x: 3, y: 0.8, z: -5.8 }, fov: 45, label: '💄 Vanity' },
    bar:       { pos: { x: 0, y: 2.5, z: -2 }, target: { x: -3, y: 0.8, z: -5.5 }, fov: 46, label: '🍸 Bar' },
    balcony:   { pos: { x: 2, y: 2.5, z: 3 },  target: { x: 5, y: 0.5, z: 5.5 }, fov: 48, label: '🌙 Balcony' },
};
let currentView = 'overview';
let cameraAnimating = false;

// ═══════════════════════════════════════════════════════════════════════
//  INIT
// ═══════════════════════════════════════════════════════════════════════
function init() {
    const canvas = document.getElementById('bedroom-canvas');
    renderer = new THREE.WebGLRenderer({ canvas, antialias: true });
    renderer.setSize(window.innerWidth, window.innerHeight);
    renderer.setPixelRatio(Math.min(window.devicePixelRatio, 2));
    renderer.shadowMap.enabled = true;
    renderer.shadowMap.type = THREE.PCFSoftShadowMap;

    scene = new THREE.Scene();
    scene.background = new THREE.Color(0x1a1a2e);

    camera = new THREE.PerspectiveCamera(55, window.innerWidth / window.innerHeight, 0.1, 500);
    camera.position.set(CONFIG.cameraPos.x, CONFIG.cameraPos.y, CONFIG.cameraPos.z);

    controls = new THREE.OrbitControls(camera, renderer.domElement);
    controls.target.set(CONFIG.cameraTarget.x, CONFIG.cameraTarget.y, CONFIG.cameraTarget.z);
    controls.enableDamping = true;
    controls.dampingFactor = 0.08;
    controls.minDistance = 2;
    controls.maxDistance = 30;
    controls.maxPolarAngle = Math.PI / 2.05;
    controls.minPolarAngle = 0.2;
    controls.zoomSpeed = 1.2;
    controls.rotateSpeed = 0.8;
    controls.panSpeed = 0.8;
    controls.enablePan = true;
    controls.update();

    createLighting();
    createRoom();
    connectSocket();
    loadConstants();
    fetchState();
    loadAmbientTracks();
    loadInteractLocations();
    buildViewPresetButtons();

    animate();
    console.log('Bedroom v6 initialized');
}

// ═══════════════════════════════════════════════════════════════════════
//  LIGHTING
// ═══════════════════════════════════════════════════════════════════════
function createLighting() {
    ambientLight = new THREE.AmbientLight(0xffffff, 0.15);
    scene.add(ambientLight);

    directionalLight = new THREE.DirectionalLight(0xffeedd, 0.4);
    directionalLight.position.set(5, 10, 5);
    directionalLight.castShadow = true;
    directionalLight.shadow.mapSize.set(2048, 2048);
    directionalLight.shadow.camera.near = 0.5;
    directionalLight.shadow.camera.far = 25;
    directionalLight.shadow.bias = -0.001;
    scene.add(directionalLight);

    // Warm lamps at key locations
    const lampPositions = [
        { x: -5, y: 2.5, z: -1, color: 0xffaa66, intensity: 0.5 },    // bed area
        { x: 5.5, y: 2.5, z: 0, color: 0xffd4a3, intensity: 0.35 },   // couch area
        { x: 3, y: 2.0, z: -5.8, color: 0xddaaff, intensity: 0.25 },  // vanity
        { x: -3, y: 3.2, z: -5.5, color: 0xffccaa, intensity: 0.4 },  // bar
        { x: -2, y: 1.5, z: 5.5, color: 0xff6622, intensity: 0.6 },   // fireplace
        { x: 6.5, y: 1.5, z: -4.5, color: 0xaaddff, intensity: 0.25 },// bathroom
        { x: 5, y: 2, z: 5.5, color: 0x667eea, intensity: 0.3 },      // balcony moonlight
        { x: -5, y: 2.5, z: -4.5, color: 0xffaa44, intensity: 0.15 }, // bed nightstand
    ];
    lampPositions.forEach(p => {
        const pl = new THREE.PointLight(p.color, p.intensity, 8);
        pl.position.set(p.x, p.y, p.z);
        pl.castShadow = true;
        scene.add(pl);
        pointLights.push(pl);
    });
}

function applyLighting(preset) {
    if (!preset) return;
    const c = new THREE.Color(preset.color);
    ambientLight.intensity = preset.ambient * 0.5;
    directionalLight.intensity = preset.directional * 0.8;
    directionalLight.color = c;
    const mul = (timeOfDay === 'night') ? 0.8 : (timeOfDay === 'morning') ? 0.3 : 0.5;
    pointLights.forEach(l => { l.intensity = l.userData?.baseIntensity * mul || mul * 0.5; });
}

// ═══════════════════════════════════════════════════════════════════════
//  ROOM GEOMETRY + FURNITURE
// ═══════════════════════════════════════════════════════════════════════
function createRoom() {
    const { w, h, d } = CONFIG.roomSize;

    // ── Floor: dark hardwood ──
    const floorGeo = new THREE.PlaneGeometry(w, d);
    const floorMat = new THREE.MeshStandardMaterial({ color: 0x3d2b1f, roughness: 0.85 });
    const floor = new THREE.Mesh(floorGeo, floorMat);
    floor.rotation.x = -Math.PI / 2;
    floor.receiveShadow = true;
    scene.add(floor);

    // ── Ceiling ──
    const ceilMat = new THREE.MeshStandardMaterial({ color: 0x222233, roughness: 0.95 });
    const ceil = new THREE.Mesh(new THREE.PlaneGeometry(w, d), ceilMat);
    ceil.rotation.x = Math.PI / 2;
    ceil.position.y = h;
    scene.add(ceil);

    // ── Walls ──
    const wallMat = new THREE.MeshStandardMaterial({ color: 0x2a2a3d, roughness: 0.9, side: THREE.DoubleSide });
    const addWall = (geo, x, y, z, ry) => {
        const m = new THREE.Mesh(geo, wallMat);
        m.position.set(x, y, z);
        if (ry) m.rotation.y = ry;
        m.receiveShadow = true;
        scene.add(m);
    };
    addWall(new THREE.BoxGeometry(w, h, 0.12), 0, h/2, -d/2);        // back
    addWall(new THREE.BoxGeometry(0.12, h, d), -w/2, h/2, 0);        // left
    addWall(new THREE.BoxGeometry(0.12, h, d), w/2, h/2, 0);         // right
    addWall(new THREE.BoxGeometry(w, h, 0.12), 0, h/2, d/2);         // front (glass wall with balcony door)

    // ── Area rug under bed ──
    const rugGeo = new THREE.PlaneGeometry(7, 5);
    const rugMat = new THREE.MeshStandardMaterial({ color: 0x4a2040, roughness: 0.95 });
    const rug = new THREE.Mesh(rugGeo, rugMat);
    rug.rotation.x = -Math.PI / 2;
    rug.position.set(-4.5, 0.01, -1);
    scene.add(rug);

    // ── Centre rug ──
    const rug2Geo = new THREE.PlaneGeometry(5, 4);
    const rug2 = new THREE.Mesh(rug2Geo, new THREE.MeshStandardMaterial({ color: 0x3a1838, roughness: 0.95 }));
    rug2.rotation.x = -Math.PI / 2;
    rug2.position.set(0, 0.008, 1);
    scene.add(rug2);

    // ── Build furniture (wall assignments) ──
    // Left wall:  Bed
    // Right wall: Couch/TV + Bathroom
    // Back wall:  Bar + Vanity
    // Front wall: Fireplace + Balcony
    buildBed();
    buildCouch();
    buildFireplace();
    buildBar();
    buildVanity();
    buildBathroomFixtures();
    buildBalcony();
    buildDecorations();
}

function _box(w, h, d, color, x, y, z, castShadow = true) {
    const mat = new THREE.MeshStandardMaterial({ color, roughness: 0.7 });
    const mesh = new THREE.Mesh(new THREE.BoxGeometry(w, h, d), mat);
    mesh.position.set(x, y, z);
    mesh.castShadow = castShadow;
    mesh.receiveShadow = true;
    scene.add(mesh);
    return mesh;
}

function buildBed() {
    // Large king bed — focal point, against left wall (4.5 x 3.5)
    const BX = -5, BZ = -1;  // bed centre
    const bedWood = new THREE.MeshStandardMaterial({ color: 0x4a2a12, roughness: 0.6, metalness: 0.05 });

    // Platform base with trim
    _box(3.6, 0.12, 4.8, 0x3a1e0e, BX, 0.06, BZ);         // floor plinth
    _box(3.4, 0.35, 4.6, 0x4a2a12, BX, 0.24, BZ);          // base frame
    // Mattress
    const mattGeo = new THREE.BoxGeometry(3.2, 0.28, 4.4);
    const mattMat = new THREE.MeshStandardMaterial({ color: 0xf5f0e8, roughness: 0.95 });
    const mattress = new THREE.Mesh(mattGeo, mattMat);
    mattress.position.set(BX, 0.56, BZ);
    mattress.castShadow = true; mattress.receiveShadow = true;
    scene.add(mattress);
    // Duvet
    _box(3.2, 0.08, 3.0, 0x8b2252, BX, 0.72, BZ + 0.5, false);
    // Silk sheet
    _box(3.0, 0.04, 0.6, 0xd4a0b8, BX, 0.74, BZ - 1.6, false);

    // Headboard — against left wall
    _box(0.14, 1.8, 4.6, 0x3a1e0e, -7.85, 1.32, BZ);       // wood frame
    const hbPadGeo = new THREE.BoxGeometry(0.08, 1.5, 4.2);
    const hbPadMat = new THREE.MeshStandardMaterial({ color: 0x5c2040, roughness: 0.9 });
    const hbPad = new THREE.Mesh(hbPadGeo, hbPadMat);
    hbPad.position.set(-7.78, 1.22, BZ);
    scene.add(hbPad);
    // Headboard finials
    [BZ - 2.3, BZ + 2.3].forEach(zOff => {
        const finial = new THREE.Mesh(
            new THREE.SphereGeometry(0.09, 12, 12),
            new THREE.MeshStandardMaterial({ color: 0xccaa66, metalness: 0.7, roughness: 0.3 })
        );
        finial.position.set(-7.85, 2.26, zOff);
        scene.add(finial);
    });

    // Footboard (low, right side of bed)
    _box(0.10, 0.5, 4.6, 0x3a1e0e, BX + 1.82, 0.46, BZ);

    // Pillows (4 across, along headboard)
    const pillowMat = new THREE.MeshStandardMaterial({ color: 0xfff0f5, roughness: 0.95 });
    [BZ - 1.5, BZ - 0.5, BZ + 0.5, BZ + 1.5].forEach(z => {
        const pill = new THREE.Mesh(new THREE.BoxGeometry(0.35, 0.18, 0.55), pillowMat);
        pill.position.set(-7.3, 0.79, z);
        pill.rotation.y = (Math.random() - 0.5) * 0.15;
        scene.add(pill);
    });
    // Throw pillow
    const throwPill = new THREE.Mesh(
        new THREE.BoxGeometry(0.4, 0.15, 0.4),
        new THREE.MeshStandardMaterial({ color: 0xddaa55, roughness: 0.85 })
    );
    throwPill.position.set(-6.5, 0.78, BZ);
    throwPill.rotation.y = 0.3;
    scene.add(throwPill);

    // Bedside tables (both ends of the bed)
    [BZ - 2.8, BZ + 2.8].forEach(z => {
        _box(0.55, 0.6, 0.55, 0x3a1e0e, BX, 0.3, z);
        // Drawer handle
        const handle = new THREE.Mesh(
            new THREE.CylinderGeometry(0.015, 0.015, 0.12, 8),
            new THREE.MeshStandardMaterial({ color: 0xccaa66, metalness: 0.8, roughness: 0.2 })
        );
        handle.position.set(BX + 0.3, 0.35, z);
        handle.rotation.z = Math.PI / 2;
        scene.add(handle);
        // Lamp
        _box(0.08, 0.35, 0.08, 0x888888, BX, 0.78, z, false);
        const shade = new THREE.Mesh(
            new THREE.CylinderGeometry(0.06, 0.16, 0.18, 16),
            new THREE.MeshStandardMaterial({ color: 0xffeecc, emissive: 0xffaa44, emissiveIntensity: 0.5, transparent: true, opacity: 0.8 })
        );
        shade.position.set(BX, 1.06, z);
        scene.add(shade);
    });
}

function buildCouch() {
    // Couch against right wall (upper section)
    const CX = 5.5, CZ = 0;
    const couchFabric = new THREE.MeshStandardMaterial({ color: 0x3a2244, roughness: 0.88 });
    // Base
    _box(1.2, 0.5, 3.2, 0x3a2244, CX, 0.25, CZ);
    // Back (against right wall)
    const backGeo = new THREE.BoxGeometry(0.18, 0.75, 3.2);
    const back = new THREE.Mesh(backGeo, couchFabric);
    back.position.set(CX + 0.52, 0.72, CZ);
    back.rotation.z = -0.05;
    back.castShadow = true;
    scene.add(back);
    // Armrests
    [CZ - 1.6, CZ + 1.6].forEach(z => {
        _box(1.2, 0.4, 0.18, 0x3a2244, CX, 0.55, z);
        const cap = new THREE.Mesh(
            new THREE.CylinderGeometry(0.09, 0.09, 1.2, 12),
            couchFabric
        );
        cap.position.set(CX, 0.76, z);
        cap.rotation.z = Math.PI / 2;
        scene.add(cap);
    });
    // Seat cushions (3 along length)
    [-0.9, 0, 0.9].forEach(off => {
        const cush = new THREE.Mesh(
            new THREE.BoxGeometry(0.9, 0.14, 0.9),
            new THREE.MeshStandardMaterial({ color: 0x5c3060, roughness: 0.9 })
        );
        cush.position.set(CX - 0.04, 0.54, CZ + off);
        scene.add(cush);
    });
    // Back pillows (2)
    [-0.6, 0.6].forEach(off => {
        const bp = new THREE.Mesh(
            new THREE.BoxGeometry(0.14, 0.4, 0.5),
            new THREE.MeshStandardMaterial({ color: 0x6a3570, roughness: 0.9 })
        );
        bp.position.set(CX + 0.35, 0.75, CZ + off);
        bp.rotation.z = 0.15;
        scene.add(bp);
    });
    // Coffee table (glass top)
    const glassTop = new THREE.Mesh(
        new THREE.BoxGeometry(0.7, 0.04, 1.6),
        new THREE.MeshStandardMaterial({ color: 0xaabbcc, transparent: true, opacity: 0.4, metalness: 0.3, roughness: 0.1 })
    );
    glassTop.position.set(CX - 1.5, 0.42, CZ);
    scene.add(glassTop);
    // Table legs
    [[-0.25, -0.65], [0.25, -0.65], [-0.25, 0.65], [0.25, 0.65]].forEach(([ox, oz]) => {
        const leg = new THREE.Mesh(
            new THREE.CylinderGeometry(0.025, 0.025, 0.4, 8),
            new THREE.MeshStandardMaterial({ color: 0x888888, metalness: 0.6, roughness: 0.3 })
        );
        leg.position.set(CX - 1.5 + ox, 0.2, CZ + oz);
        scene.add(leg);
    });
    // TV on right wall
    _box(0.06, 1.5, 2.8, 0x111111, 7.85, 2.6, CZ);
    const screenMat = new THREE.MeshStandardMaterial({ color: 0x222244, emissive: 0x112244, emissiveIntensity: 0.15 });
    const tv = new THREE.Mesh(new THREE.BoxGeometry(0.02, 1.3, 2.6), screenMat);
    tv.position.set(7.82, 2.6, CZ);
    scene.add(tv);
}

function buildFireplace() {
    // Fireplace against front wall, centre
    const FX = -2, FZ = 5.5;
    const stoneMat = new THREE.MeshStandardMaterial({ color: 0x4a4a52, roughness: 0.85 });

    // Hearth base (stone slab)
    _box(3.0, 0.08, 1.6, 0x5a5a62, FX, 0.04, FZ);

    // Fireplace surround pillars
    const surrL = new THREE.Mesh(new THREE.BoxGeometry(0.35, 2.2, 0.8), stoneMat);
    surrL.position.set(FX - 1.2, 1.1, FZ);
    surrL.castShadow = true;
    scene.add(surrL);
    const surrR = new THREE.Mesh(new THREE.BoxGeometry(0.35, 2.2, 0.8), stoneMat);
    surrR.position.set(FX + 1.2, 1.1, FZ);
    surrR.castShadow = true;
    scene.add(surrR);
    // Mantel
    const mantel = new THREE.Mesh(
        new THREE.BoxGeometry(3.0, 0.12, 0.9),
        new THREE.MeshStandardMaterial({ color: 0x3a2215, roughness: 0.6 })
    );
    mantel.position.set(FX, 2.26, FZ);
    mantel.castShadow = true;
    scene.add(mantel);
    // Firebox
    _box(2.0, 1.7, 0.1, 0x3a2018, FX, 0.95, FZ + 0.4, false);
    _box(2.0, 0.06, 0.7, 0x333338, FX, 0.11, FZ + 0.05, false);
    [-0.95, 0.95].forEach(x => {
        _box(0.08, 1.7, 0.7, 0x3a2018, FX + x, 0.95, FZ + 0.05, false);
    });

    // Logs
    const logMat = new THREE.MeshStandardMaterial({ color: 0x5a3a20, roughness: 0.9 });
    const logGeo = new THREE.CylinderGeometry(0.07, 0.08, 0.9, 8);
    [{ y: 0.2, z: FZ, r: 0 }, { y: 0.2, z: FZ + 0.15, r: 0.1 }, { y: 0.34, z: FZ + 0.07, r: -0.05 }].forEach(p => {
        const log = new THREE.Mesh(logGeo, logMat);
        log.position.set(FX, p.y, p.z);
        log.rotation.z = Math.PI / 2;
        log.rotation.x = p.r;
        scene.add(log);
    });

    // Fire glow
    const fireLight1 = new THREE.PointLight(0xff6622, 0.8, 5);
    fireLight1.position.set(FX, 0.5, FZ);
    scene.add(fireLight1);
    pointLights.push(fireLight1);
    const fireLight2 = new THREE.PointLight(0xff4400, 0.4, 3);
    fireLight2.position.set(FX - 0.2, 0.35, FZ + 0.05);
    scene.add(fireLight2);
    pointLights.push(fireLight2);

    // Ember glow
    const emberGeo = new THREE.PlaneGeometry(0.9, 0.5);
    const emberMat = new THREE.MeshStandardMaterial({ color: 0xff3300, emissive: 0xff4400, emissiveIntensity: 0.6, transparent: true, opacity: 0.5 });
    const embers = new THREE.Mesh(emberGeo, emberMat);
    embers.rotation.x = -Math.PI / 2;
    embers.position.set(FX, 0.13, FZ + 0.05);
    scene.add(embers);

    // Mantel candelabra
    [-0.9, 0.9].forEach(x => {
        const candleBase = new THREE.Mesh(
            new THREE.CylinderGeometry(0.06, 0.08, 0.04, 12),
            new THREE.MeshStandardMaterial({ color: 0xccaa55, metalness: 0.7, roughness: 0.3 })
        );
        candleBase.position.set(FX + x, 2.34, FZ);
        scene.add(candleBase);
        const candleStick = new THREE.Mesh(
            new THREE.CylinderGeometry(0.015, 0.015, 0.15, 8),
            new THREE.MeshStandardMaterial({ color: 0xfff5e0 })
        );
        candleStick.position.set(FX + x, 2.43, FZ);
        scene.add(candleStick);
        const flame = new THREE.PointLight(0xff8800, 0.15, 1.5);
        flame.position.set(FX + x, 2.53, FZ);
        scene.add(flame);
        pointLights.push(flame);
    });

    // Fur rug in front of fireplace
    const rugGeo = new THREE.CircleGeometry(1.4, 24);
    const rugMat = new THREE.MeshStandardMaterial({ color: 0x8b7355, roughness: 0.95, side: THREE.DoubleSide });
    const furRug = new THREE.Mesh(rugGeo, rugMat);
    furRug.rotation.x = -Math.PI / 2;
    furRug.position.set(FX, 0.015, FZ - 1.5);
    scene.add(furRug);
}

function buildBar() {
    // Bar against back wall, left portion
    const BRX = -3, BRZ = -5.5;
    // Counter (along z-axis, against back wall)
    _box(2.4, 1.1, 0.55, 0x2a1810, BRX, 0.55, BRZ);
    _box(2.5, 0.06, 0.6, 0x1a0e08, BRX, 1.12, BRZ, false);
    // Stools (in front of counter)
    for (let i = -0.6; i <= 0.6; i += 1.2) {
        const legMat = new THREE.MeshStandardMaterial({ color: 0x888888, metalness: 0.8, roughness: 0.3 });
        const leg = new THREE.Mesh(new THREE.CylinderGeometry(0.04, 0.04, 0.7, 8), legMat);
        leg.position.set(BRX + i, 0.35, BRZ + 1.0);
        scene.add(leg);
        const seat = new THREE.Mesh(
            new THREE.CylinderGeometry(0.2, 0.18, 0.08, 16),
            new THREE.MeshStandardMaterial({ color: 0x333333 })
        );
        seat.position.set(BRX + i, 0.72, BRZ + 1.0);
        seat.castShadow = true;
        scene.add(seat);
    }
    // Bottles on counter
    [0xaa3333, 0x33aa33, 0x3333aa, 0xaa8833].forEach((c, i) => {
        const bottle = new THREE.Mesh(
            new THREE.CylinderGeometry(0.05, 0.06, 0.3, 8),
            new THREE.MeshStandardMaterial({ color: c, transparent: true, opacity: 0.7 })
        );
        bottle.position.set(BRX - 0.6 + i * 0.35, 1.3, BRZ - 0.15);
        scene.add(bottle);
    });
    // Shelf behind bar (on wall)
    _box(2.0, 0.06, 0.2, 0x3a2215, BRX, 1.6, BRZ - 0.3, false);
}

function buildVanity() {
    // Vanity against back wall, right portion
    const VX = 3, VZ = -5.8;
    const vanityWood = new THREE.MeshStandardMaterial({ color: 0x4a3520, roughness: 0.6 });
    _box(1.8, 0.06, 0.6, 0x4a3520, VX, 0.82, VZ);   // top surface
    // Front panel with drawers
    _box(1.7, 0.5, 0.04, 0x3a2a18, VX, 0.55, VZ + 0.3);
    // Drawer knobs
    [-0.4, 0.4].forEach(off => {
        const knob = new THREE.Mesh(
            new THREE.SphereGeometry(0.02, 8, 8),
            new THREE.MeshStandardMaterial({ color: 0xccaa55, metalness: 0.8, roughness: 0.2 })
        );
        knob.position.set(VX + off, 0.55, VZ + 0.33);
        scene.add(knob);
    });
    // Legs
    [[-0.82, -0.24], [0.82, -0.24], [-0.82, 0.24], [0.82, 0.24]].forEach(([ox, oz]) => {
        const leg = new THREE.Mesh(
            new THREE.CylinderGeometry(0.03, 0.04, 0.8, 8),
            vanityWood
        );
        leg.position.set(VX + ox, 0.4, VZ + oz);
        scene.add(leg);
    });

    // Tri-fold mirror against back wall
    const mirrorMat = new THREE.MeshStandardMaterial({ color: 0xaabbcc, metalness: 0.9, roughness: 0.08 });
    const frameMat = new THREE.MeshStandardMaterial({ color: 0x8b7355, roughness: 0.5 });
    const centerMirror = new THREE.Mesh(new THREE.BoxGeometry(0.8, 1.0, 0.03), mirrorMat);
    centerMirror.position.set(VX, 1.4, VZ - 0.12);
    scene.add(centerMirror);
    _box(0.84, 1.04, 0.04, 0x8b7355, VX, 1.4, VZ - 0.14, false);
    [-1, 1].forEach(s => {
        const sideFrame = new THREE.Group();
        const sideMirror = new THREE.Mesh(new THREE.BoxGeometry(0.35, 0.9, 0.03), mirrorMat);
        const sideFrameBox = new THREE.Mesh(new THREE.BoxGeometry(0.38, 0.94, 0.04), frameMat);
        sideFrameBox.position.z = -0.005;
        sideFrame.add(sideFrameBox);
        sideFrame.add(sideMirror);
        sideFrame.position.set(VX + s * 0.57, 1.4, VZ - 0.12);
        sideFrame.rotation.y = s * 0.25;
        scene.add(sideFrame);
    });

    // Ring light
    const ringLight = new THREE.Mesh(
        new THREE.TorusGeometry(0.45, 0.012, 8, 32),
        new THREE.MeshStandardMaterial({ color: 0xffffff, emissive: 0xffeedd, emissiveIntensity: 0.5 })
    );
    ringLight.position.set(VX, 1.4, VZ - 0.10);
    scene.add(ringLight);

    // Stool
    const stoolBase = new THREE.Mesh(
        new THREE.CylinderGeometry(0.03, 0.03, 0.4, 8),
        new THREE.MeshStandardMaterial({ color: 0x888888, metalness: 0.6, roughness: 0.3 })
    );
    stoolBase.position.set(VX, 0.2, VZ + 0.9);
    scene.add(stoolBase);
    const stoolSeat = new THREE.Mesh(
        new THREE.CylinderGeometry(0.22, 0.22, 0.06, 16),
        new THREE.MeshStandardMaterial({ color: 0xcc88aa, roughness: 0.85 })
    );
    stoolSeat.position.set(VX, 0.43, VZ + 0.9);
    stoolSeat.castShadow = true;
    scene.add(stoolSeat);

    // Perfume bottles on vanity top
    [0, 0.15, 0.3].forEach((off, i) => {
        const bottle = new THREE.Mesh(
            new THREE.CylinderGeometry(0.02, 0.025, 0.08 + i * 0.02, 8),
            new THREE.MeshStandardMaterial({ color: [0xddaaff, 0xffccdd, 0xaaddff][i], transparent: true, opacity: 0.6 })
        );
        bottle.position.set(VX - 0.3 + off, 0.90, VZ + 0.1);
        scene.add(bottle);
    });
}

function buildBathroomFixtures() {
    // Bathroom area — right wall, lower section
    const BTX = 6.5, BTZ = -4.5;
    // Partition wall
    _box(0.1, 3.0, 4.0, 0x2a2a3d, 4.5, 1.5, BTZ);
    // Frosted glass upper panel
    const frostGeo = new THREE.BoxGeometry(0.04, 1.2, 3.0);
    const frostMat = new THREE.MeshStandardMaterial({ color: 0xaabbcc, transparent: true, opacity: 0.25, roughness: 0.9 });
    const frost = new THREE.Mesh(frostGeo, frostMat);
    frost.position.set(4.5, 2.6, BTZ);
    scene.add(frost);

    // Bathtub — larger freestanding clawfoot (along z-axis)
    const tubMat = new THREE.MeshStandardMaterial({ color: 0xeeeeee, roughness: 0.2, metalness: 0.15 });
    const tubOuter = new THREE.Mesh(
        new THREE.CylinderGeometry(0.65, 0.6, 0.75, 24),
        tubMat
    );
    tubOuter.position.set(BTX, 0.38, BTZ);
    tubOuter.scale.set(1.0, 1.0, 2.2);
    tubOuter.castShadow = true;
    scene.add(tubOuter);
    const tubInner = new THREE.Mesh(
        new THREE.CylinderGeometry(0.60, 0.55, 0.65, 24),
        new THREE.MeshStandardMaterial({ color: 0xf8f8f8, roughness: 0.15 })
    );
    tubInner.position.set(BTX, 0.43, BTZ);
    tubInner.scale.set(0.95, 1.0, 2.1);
    scene.add(tubInner);
    // Water surface
    const waterGeo = new THREE.CylinderGeometry(0.55, 0.55, 0.02, 24);
    const waterMat = new THREE.MeshStandardMaterial({ color: 0x4488bb, transparent: true, opacity: 0.45, roughness: 0.1 });
    const water = new THREE.Mesh(waterGeo, waterMat);
    water.position.set(BTX, 0.68, BTZ);
    water.scale.set(0.9, 1.0, 2.0);
    scene.add(water);
    // Clawfeet
    const footMat = new THREE.MeshStandardMaterial({ color: 0xccaa55, metalness: 0.8, roughness: 0.3 });
    [[-0.4, -1.0], [0.4, -1.0], [-0.4, 1.0], [0.4, 1.0]].forEach(([ox, oz]) => {
        const foot = new THREE.Mesh(new THREE.SphereGeometry(0.06, 8, 8), footMat);
        foot.position.set(BTX + ox, 0.06, BTZ + oz);
        scene.add(foot);
    });
    // Faucet
    const faucetMat = new THREE.MeshStandardMaterial({ color: 0xbbbbbb, metalness: 0.9, roughness: 0.15 });
    const faucetPost = new THREE.Mesh(new THREE.CylinderGeometry(0.02, 0.02, 0.35, 8), faucetMat);
    faucetPost.position.set(BTX, 0.92, BTZ - 1.2);
    scene.add(faucetPost);
    const faucetSpout = new THREE.Mesh(new THREE.CylinderGeometry(0.015, 0.015, 0.15, 8), faucetMat);
    faucetSpout.position.set(BTX, 1.08, BTZ - 1.1);
    faucetSpout.rotation.x = Math.PI / 2.5;
    scene.add(faucetSpout);

    // Sink with pedestal
    const sinkBowl = new THREE.Mesh(
        new THREE.SphereGeometry(0.22, 12, 8, 0, Math.PI * 2, 0, Math.PI * 0.5),
        new THREE.MeshStandardMaterial({ color: 0xeeeeee, roughness: 0.15 })
    );
    sinkBowl.position.set(BTX, 0.92, BTZ + 2.3);
    sinkBowl.rotation.x = Math.PI;
    scene.add(sinkBowl);
    _box(0.08, 0.9, 0.2, 0xdddddd, BTX, 0.45, BTZ + 2.3);
    // Sink mirror on right wall
    const sinkMirror = new THREE.Mesh(
        new THREE.BoxGeometry(0.03, 0.8, 0.6),
        new THREE.MeshStandardMaterial({ color: 0xaabbcc, metalness: 0.9, roughness: 0.1 })
    );
    sinkMirror.position.set(7.85, 1.5, BTZ + 2.3);
    scene.add(sinkMirror);

    // Bath candles on tub rim
    [[-0.45, -0.8], [0.45, -0.8]].forEach(([ox, oz]) => {
        const candle = new THREE.Mesh(
            new THREE.CylinderGeometry(0.04, 0.04, 0.12, 8),
            new THREE.MeshStandardMaterial({ color: 0xfff5e6 })
        );
        candle.position.set(BTX + ox, 0.82, BTZ + oz);
        scene.add(candle);
        const glow = new THREE.PointLight(0xff8800, 0.12, 1.5);
        glow.position.set(BTX + ox, 0.90, BTZ + oz);
        scene.add(glow);
        pointLights.push(glow);
    });
}

function buildBalcony() {
    // Balcony — front wall, right side
    const BAX = 5, BAZ = 5.5;
    // Balcony floor
    _box(3.5, 0.1, 2.2, 0x555555, BAX, 0.05, BAZ, false);
    // Railing
    const railMat = new THREE.MeshStandardMaterial({ color: 0x888888, metalness: 0.7, roughness: 0.3 });
    // Front rail
    const frontRail = new THREE.Mesh(new THREE.BoxGeometry(3.5, 0.06, 0.06), railMat);
    frontRail.position.set(BAX, 1.0, BAZ + 1.1);
    scene.add(frontRail);
    // Side rails
    const sideRail1 = new THREE.Mesh(new THREE.BoxGeometry(0.06, 0.06, 2.2), railMat);
    sideRail1.position.set(BAX - 1.7, 1.0, BAZ);
    scene.add(sideRail1);
    const sideRail2 = new THREE.Mesh(new THREE.BoxGeometry(0.06, 0.06, 2.2), railMat);
    sideRail2.position.set(BAX + 1.7, 1.0, BAZ);
    scene.add(sideRail2);
    // Vertical posts
    for (let x = BAX - 1.7; x <= BAX + 1.7; x += 0.75) {
        const post = new THREE.Mesh(new THREE.CylinderGeometry(0.02, 0.02, 1, 6), railMat);
        post.position.set(x, 0.5, BAZ + 1.1);
        scene.add(post);
    }
    // Small table + chairs
    _box(0.65, 0.5, 0.65, 0x5a4a3a, BAX, 0.25, BAZ - 0.2);
    const chairMat = new THREE.MeshStandardMaterial({ color: 0x444444 });
    [-0.7, 0.7].forEach(off => {
        const chair = new THREE.Mesh(new THREE.BoxGeometry(0.45, 0.4, 0.45), chairMat);
        chair.position.set(BAX + off, 0.2, BAZ - 0.8);
        chair.castShadow = true;
        scene.add(chair);
    });
}

function buildDecorations() {
    // Ceiling chandelier (crystal-style, centered)
    const chandelierMat = new THREE.MeshStandardMaterial({ color: 0xddccaa, emissive: 0xffddaa, emissiveIntensity: 0.35, metalness: 0.4, roughness: 0.3 });
    const chanFrame = new THREE.Mesh(new THREE.TorusGeometry(0.5, 0.02, 8, 24), chandelierMat);
    chanFrame.position.set(0, 3.5, 0);
    chanFrame.rotation.x = Math.PI / 2;
    scene.add(chanFrame);
    const chain = new THREE.Mesh(
        new THREE.CylinderGeometry(0.01, 0.01, 0.4, 6),
        new THREE.MeshStandardMaterial({ color: 0xccaa66, metalness: 0.8, roughness: 0.2 })
    );
    chain.position.set(0, 3.8, 0);
    scene.add(chain);
    for (let i = 0; i < 10; i++) {
        const angle = (i / 10) * Math.PI * 2;
        const crystal = new THREE.Mesh(
            new THREE.OctahedronGeometry(0.04, 0),
            new THREE.MeshStandardMaterial({ color: 0xffffff, transparent: true, opacity: 0.5, roughness: 0.05, metalness: 0.3 })
        );
        crystal.position.set(Math.cos(angle) * 0.5, 3.4, Math.sin(angle) * 0.5);
        scene.add(crystal);
    }
    const chanLight = new THREE.PointLight(0xffeecc, 0.5, 10);
    chanLight.position.set(0, 3.4, 0);
    scene.add(chanLight);
    pointLights.push(chanLight);

    // Picture frames on back wall
    [{ x: -5, c: 0x663344, w: 1.0, h: 0.7 }, { x: 0, c: 0x334466, w: 0.8, h: 1.0 }, { x: 5.5, c: 0x446644, w: 0.9, h: 0.6 }].forEach(p => {
        _box(p.w + 0.15, p.h + 0.15, 0.04, 0x8b7355, p.x, 2.8, -6.92, false);
        _box(p.w, p.h, 0.02, p.c, p.x, 2.8, -6.88, false);
    });

    // Floor vase near doorway
    const vaseMat = new THREE.MeshStandardMaterial({ color: 0x445566, roughness: 0.3, metalness: 0.1 });
    const vase = new THREE.Mesh(
        new THREE.CylinderGeometry(0.12, 0.15, 0.5, 12),
        vaseMat
    );
    vase.position.set(2, 0.25, 5.5);
    scene.add(vase);
    const stem = new THREE.Mesh(
        new THREE.CylinderGeometry(0.01, 0.01, 0.6, 6),
        new THREE.MeshStandardMaterial({ color: 0x2d5a2d })
    );
    stem.position.set(2, 0.7, 5.5);
    scene.add(stem);
    const leavesGeo = new THREE.SphereGeometry(0.3, 8, 8);
    const leavesMat = new THREE.MeshStandardMaterial({ color: 0x2d6b2d, roughness: 0.9 });
    const leaves = new THREE.Mesh(leavesGeo, leavesMat);
    leaves.position.set(2, 1.0, 5.5);
    scene.add(leaves);

    // Wall sconces
    [-1, 1].forEach(side => {
        const sconce = new THREE.Mesh(
            new THREE.BoxGeometry(0.08, 0.15, 0.1),
            new THREE.MeshStandardMaterial({ color: 0xccaa55, metalness: 0.7, roughness: 0.3 })
        );
        sconce.position.set(side * 7.9, 2.2, -2);
        scene.add(sconce);
        const sconceLight = new THREE.PointLight(0xffddaa, 0.2, 4);
        sconceLight.position.set(side * 7.8, 2.3, -2);
        scene.add(sconceLight);
        pointLights.push(sconceLight);
    });

    // Crown moulding
    const mouldingMat = new THREE.MeshStandardMaterial({ color: 0x333345, roughness: 0.7 });
    // Back wall
    const mouldBack = new THREE.Mesh(new THREE.BoxGeometry(16, 0.08, 0.08), mouldingMat);
    mouldBack.position.set(0, 3.96, -6.96);
    scene.add(mouldBack);
    // Side walls
    [-1, 1].forEach(s => {
        const mouldSide = new THREE.Mesh(new THREE.BoxGeometry(0.08, 0.08, 14), mouldingMat);
        mouldSide.position.set(s * 7.96, 3.96, 0);
        scene.add(mouldSide);
    });

    // Candles on bar
    for (let i = 0; i < 2; i++) {
        const candle = new THREE.Mesh(
            new THREE.CylinderGeometry(0.03, 0.03, 0.15, 8),
            new THREE.MeshStandardMaterial({ color: 0xeeeecc })
        );
        candle.position.set(-2.3 + i * 0.3, 1.2, -5.65);
        scene.add(candle);
        const flame = new THREE.PointLight(0xff8800, 0.15, 2);
        flame.position.set(-2.3 + i * 0.3, 1.32, -5.65);
        scene.add(flame);
        pointLights.push(flame);
    }
}

// ═══════════════════════════════════════════════════════════════════════
//  LOCATION MARKERS  (created dynamically from server state)
// ═══════════════════════════════════════════════════════════════════════
function buildLocationMarkers(locations) {
    // Remove old markers
    Object.values(locationMarkers).forEach(m => scene.remove(m));
    for (const k in locationMarkers) delete locationMarkers[k];

    for (const [id, loc] of Object.entries(locations)) {
        const pos = loc.pos || { x: 0, y: 0, z: 0 };

        // Glowing disc on floor
        const geo = new THREE.CylinderGeometry(0.8, 0.8, 0.05, 32);
        const hue = (loc.spiciness || 1) / 5;
        const col = new THREE.Color().setHSL(0.0 + hue * 0.08, 0.6, 0.35 + hue * 0.1);
        const mat = new THREE.MeshStandardMaterial({ color: col, emissive: col, emissiveIntensity: 0.3, transparent: true, opacity: 0.7 });
        const mesh = new THREE.Mesh(geo, mat);
        mesh.position.set(pos.x, 0.03, pos.z);
        mesh.userData = { locId: id, locName: loc.name };
        scene.add(mesh);
        locationMarkers[id] = mesh;

        // Label (CSS would be nicer, but a simple sprite works)
        const label = makeTextSprite(loc.name, 0.6);
        label.position.set(pos.x, 0.6, pos.z);
        scene.add(label);
    }
}

function makeTextSprite(text, scale) {
    const canvas = document.createElement('canvas');
    canvas.width = 256; canvas.height = 64;
    const ctx = canvas.getContext('2d');
    ctx.fillStyle = 'rgba(0,0,0,0)';
    ctx.fillRect(0, 0, 256, 64);
    ctx.font = 'bold 28px sans-serif';
    ctx.fillStyle = '#ffffff';
    ctx.textAlign = 'center';
    ctx.fillText(text, 128, 40);
    const tex = new THREE.CanvasTexture(canvas);
    const mat = new THREE.SpriteMaterial({ map: tex, transparent: true, depthTest: false });
    const sp = new THREE.Sprite(mat);
    sp.scale.set(scale * 2, scale * 0.5, 1);
    return sp;
}

function makeBubbleSprite(text) {
    const maxLen = 44;
    const display = text.length > maxLen ? text.slice(0, maxLen - 1) + '…' : text;
    const canvas = document.createElement('canvas');
    canvas.width = 512; canvas.height = 80;
    const ctx = canvas.getContext('2d');
    // Rounded background
    const r = 14;
    ctx.fillStyle = 'rgba(20, 20, 30, 0.82)';
    ctx.beginPath();
    ctx.moveTo(r, 0); ctx.lineTo(canvas.width - r, 0);
    ctx.arcTo(canvas.width, 0, canvas.width, r, r);
    ctx.lineTo(canvas.width, canvas.height - r);
    ctx.arcTo(canvas.width, canvas.height, canvas.width - r, canvas.height, r);
    ctx.lineTo(r, canvas.height);
    ctx.arcTo(0, canvas.height, 0, canvas.height - r, r);
    ctx.lineTo(0, r);
    ctx.arcTo(0, 0, r, 0, r);
    ctx.closePath();
    ctx.fill();
    // Text
    ctx.font = 'bold 26px sans-serif';
    ctx.fillStyle = '#f0f0f0';
    ctx.textAlign = 'center';
    ctx.fillText(display, canvas.width / 2, 50);
    const tex = new THREE.CanvasTexture(canvas);
    const mat = new THREE.SpriteMaterial({ map: tex, transparent: true, depthTest: false });
    const sp = new THREE.Sprite(mat);
    sp.scale.set(2.4, 0.48, 1);
    return sp;
}

function showSpeechBubble(charId, text, durationMs) {
    const s = charSprites[charId];
    if (!s) return;
    // Remove any existing bubble
    if (s.bubble) { s.group.remove(s.bubble); s.bubble.material.map.dispose(); s.bubble.material.dispose(); s.bubble = null; }
    const sprite = CharModels.makeBubble(text, s.charColor || '#ff6b9d');
    sprite.position.y = s.bubbleY || 2.2;
    s.group.add(sprite);
    s.bubble = sprite;
    setTimeout(() => {
        if (s && s.bubble === sprite) {
            s.group.remove(sprite);
            sprite.material.map.dispose();
            sprite.material.dispose();
            s.bubble = null;
        }
    }, durationMs || 6000);
}

// ═══════════════════════════════════════════════════════════════════════
//  CHARACTER MODELS (detailed humanoids via CharModels API)
// ═══════════════════════════════════════════════════════════════════════
function ensureCharSprite(charId, name, colorIdx, info) {
    if (charSprites[charId]) return charSprites[charId];

    const color = CHAR_COLORS[colorIdx % CHAR_COLORS.length];
    const gender = (info && info.gender) ? info.gender : undefined;
    const model = CharModels.create({
        name: name,
        charColor: color,
        gender: gender,
    });

    // Apply initial outfit
    const outfit = (info && info.outfit) ? info.outfit : 'casual';
    CharModels.updateOutfit(model, outfit);

    scene.add(model.group);
    charSprites[charId] = {
        ...model,
        targetPos: new THREE.Vector3(0, 0, 0),
        currentPos: new THREE.Vector3(0, 0, 0),
        bubble: null,
        currentOutfit: outfit,
    };
    return charSprites[charId];
}

function removeCharSprite(charId) {
    const s = charSprites[charId];
    if (s) {
        scene.remove(s.group);
        delete charSprites[charId];
    }
}

function updateCharPositions(characters, locations) {
    // Compute a small offset per occupant so they don't overlap
    const occupantIndex = {};
    for (const [cid, info] of Object.entries(characters)) {
        const locId = info.location_id;
        if (!locId) continue;
        if (!occupantIndex[locId]) occupantIndex[locId] = [];
        occupantIndex[locId].push(cid);
    }

    let colorIdx = 0;
    for (const [cid, info] of Object.entries(characters)) {
        const sprite = ensureCharSprite(cid, info.name, colorIdx, info);
        colorIdx++;

        // Update outfit if changed
        const outfit = info.outfit || 'casual';
        if (sprite.currentOutfit !== outfit) {
            CharModels.updateOutfit(sprite, outfit);
            sprite.currentOutfit = outfit;
        }

        // Update facial expression from mood/feeling
        CharModels.setExpression(sprite, info.feeling || info.mood || 'neutral');

        const locId = info.location_id;
        if (!locId || !locations[locId]) continue;
        const pos = locations[locId].pos || { x: 0, y: 0, z: 0 };

        // Offset for multiple occupants (spread up to 3)
        const occ = occupantIndex[locId] || [];
        const idx = occ.indexOf(cid);
        const count = occ.length;
        let off = 0;
        if (count === 2) off = (idx === 0) ? -0.6 : 0.6;
        else if (count >= 3) off = (idx - 1) * 0.7;

        sprite.targetPos.set(pos.x + off, 0, pos.z);
    }

    // Remove sprites for characters no longer present
    for (const cid of Object.keys(charSprites)) {
        if (!characters[cid]) removeCharSprite(cid);
    }
}

// ═══════════════════════════════════════════════════════════════════════
//  ANIMATION LOOP
// ═══════════════════════════════════════════════════════════════════════
function animate() {
    requestAnimationFrame(animate);
    const dt = clock.getDelta();
    controls.update();
    const t = clock.elapsedTime;

    // Smooth character movement + glow pulse + detailed animation
    for (const s of Object.values(charSprites)) {
        // Skip position lerp for characters in an active sex pose
        if (!CharModels.isPoseActive()) {
            s.group.position.lerp(s.targetPos, Math.min(1, dt * 3));
        }
        if (s.ring) s.ring.material.opacity = 0.2 + 0.15 * Math.sin(t * 3);
        // Detailed humanoid animation (breathing, sway) — skipped during pose (pose handles it)
        if (s.bodyGroup && !CharModels.isPoseActive()) CharModels.animate(s, t);
    }

    // Director avatar animation
    if (directorSprite && directorSprite.bodyGroup) {
        directorSprite.group.position.lerp(directorSprite.targetPos, Math.min(1, dt * 3));
        CharModels.animate(directorSprite, t);
    }

    // Sex pose animation (overrides individual character animation when active)
    CharModels.animatePose(dt, t);

    // Pulse location markers
    for (const m of Object.values(locationMarkers)) {
        m.material.opacity = 0.5 + 0.2 * Math.sin(t * 2 + m.position.x);
    }

    // Fireplace flicker — animate fire-related point lights
    for (let i = 0; i < pointLights.length; i++) {
        const pl = pointLights[i];
        if (pl.color.r > 0.8 && pl.position.y < 1.0) {
            pl.intensity = 0.4 + 0.4 * Math.random() + 0.2 * Math.sin(t * 8 + i);
        }
    }

    renderer.render(scene, camera);
    updateFps();
}

function updateFps() {
    fpsFrames++;
    const now = performance.now();
    if (now - lastFpsTime >= 1000) {
        const el = document.getElementById('fps-counter');
        if (el) el.textContent = 'FPS: ' + fpsFrames;
        fpsFrames = 0;
        lastFpsTime = now;
    }
}

// ═══════════════════════════════════════════════════════════════════════
//  SOCKET.IO
// ═══════════════════════════════════════════════════════════════════════
function connectSocket() {
    socket = io({ transports: ['websocket', 'polling'] });

    socket.on('connect', () => {
        document.getElementById('status-text').textContent = 'Connected';
        document.querySelector('.status-dot').style.background = '#4caf50';
        refreshModels();
    });
    socket.on('disconnect', () => {
        document.getElementById('status-text').textContent = 'Disconnected';
        document.querySelector('.status-dot').style.background = '#f44336';
    });

    socket.on('scene_state', (data) => applyState(data));

    socket.on('time_changed', (data) => {
        timeOfDay = data.time;
        applyLighting(data.lighting);
        document.querySelectorAll('.light-btn').forEach(b =>
            b.classList.toggle('active', b.dataset.key === data.time));
    });

    socket.on('agent_action', (data) => {
        addFeedEntry(data);
        if (data.action === 'speak' && data.message && data.character_id) {
            showSpeechBubble(data.character_id, data.message, 5000);
        }
    });
    socket.on('agent_tick', (data) => {
        if (data.actions) data.actions.forEach(a => addFeedEntry(a));
    });
    socket.on('chat_message', (data) => {
        addFeedEntry({ character_name: data.name, action: 'speak', message: data.message,
                       timestamp: data.timestamp });
    });

    // v4 additions
    socket.on('director_speaks', (data) => {
        addFeedEntry({ character_name: data.name || '(Director)', action: 'director',
                       message: data.message, timestamp: data.timestamp }, 'director');
    });
    socket.on('scene_event', (data) => {
        addFeedEntry({ character_name: '(Event)', action: 'environment',
                       message: data.description || data.type, timestamp: data.timestamp }, 'environment');
        triggerEventEffect(data.type);
    });
    socket.on('constants', (data) => {
        if (data.positions)     POSITIONS = data.positions;
        if (data.outfits)       OUTFITS = data.outfits;
        if (data.scenarios)     SCENARIOS = data.scenarios;
        if (data.personalities) PERSONALITIES = data.personalities;
    });
    socket.on('quick_stat', (data) => {
        // Server pushed a single stat update — re-render stat sheets from current sceneState
        if (sceneState.characters && sceneState.characters[data.character_id]) {
            const st = sceneState.characters[data.character_id].stats || {};
            st[data.stat] = data.value;
            renderCharStatSheets(sceneState.characters);
        }
    });

    // ── Bed game → sex pose integration ──────────────────────────────
    socket.on('bedgame_started', (data) => {
        console.log('[BedGame] Started:', data);
        // Poses are applied per-action, not on start
    });
    socket.on('bedgame_action', (data) => {
        console.log('[BedGame] Action:', data);
        _applyBedGamePose(data);
    });
    socket.on('bedgame_ended', (data) => {
        console.log('[BedGame] Ended');
        CharModels.stopPose(false); // smooth return to standing
    });
}

// ═══════════════════════════════════════════════════════════════════════
//  BED GAME → SEX POSE BRIDGE
// ═══════════════════════════════════════════════════════════════════════

/**
 * Map a bedgame_action socket event to a 3D sex pose on the character models.
 * Resolves participant models from charSprites, computes the anchor point
 * (bed location centre), and invokes CharModels.startPose().
 */
function _applyBedGamePose(data) {
    const actionName = data.action || data.description || '';
    const playerId = data.player_id;
    const targetId = data.target_id;

    // Resolve character model objects from charSprites
    const participants = [];

    // Determine bed anchor position (from scene state locations)
    let anchorX = 0, anchorZ = 0;
    const locs = sceneState.locations || {};
    if (locs.bed && locs.bed.pos) {
        anchorX = locs.bed.pos.x || 0;
        anchorZ = locs.bed.pos.z || 0;
    }

    // A = active player (initiator)
    const spriteA = charSprites[playerId];
    if (spriteA && spriteA.bodyGroup) {
        participants.push({ model: spriteA, anchorX, anchorZ });
    }

    // B = target
    if (targetId && targetId !== playerId) {
        const spriteB = charSprites[targetId];
        if (spriteB && spriteB.bodyGroup) {
            participants.push({ model: spriteB, anchorX, anchorZ });
        }
    } else {
        // If no explicit target, pick the other character in the game
        for (const [cid, sp] of Object.entries(charSprites)) {
            if (cid !== playerId && sp.bodyGroup && participants.length < 2) {
                participants.push({ model: sp, anchorX, anchorZ });
            }
        }
    }

    // C = third participant for threesome actions (any remaining character)
    if (actionName.startsWith('threesome')) {
        const usedIds = new Set(participants.map(p => {
            for (const [cid, sp] of Object.entries(charSprites)) {
                if (sp === p.model || sp.group === p.model.group) return cid;
            }
            return null;
        }));
        for (const [cid, sp] of Object.entries(charSprites)) {
            if (!usedIds.has(cid) && sp.bodyGroup && participants.length < 3) {
                participants.push({ model: sp, anchorX, anchorZ });
            }
        }
    }

    if (participants.length >= 2) {
        // Set expression based on mood hint from server (aroused, moaning, ecstasy, flirty)
        const mood = data.mood_hint || 'aroused';
        for (const p of participants) {
            CharModels.setExpression(p.model, mood);
        }
        CharModels.startPose(actionName, participants);
    }
}

// ═══════════════════════════════════════════════════════════════════════
//  STATE MANAGEMENT
// ═══════════════════════════════════════════════════════════════════════
async function fetchState() {
    try {
        const r = await fetch('/api/scene/state');
        if (r.ok) applyState(await r.json());
    } catch (e) { console.error('fetchState error', e); }
}

function applyState(st) {
    sceneState = st;
    agentRunning = st.agent_loop_running || false;

    // 3D
    if (st.locations) buildLocationMarkers(st.locations);
    if (st.characters) updateCharPositions(st.characters, st.locations || {});
    if (st.lighting)   applyLighting(st.lighting);
    timeOfDay = st.time_of_day || 'evening';

    // Scene tab
    if (st.characters) renderCompactCharList(st.characters);
    document.getElementById('charCount').textContent = '(' + Object.keys(st.characters || {}).length + '/2)';
    document.querySelectorAll('.light-btn').forEach(b =>
        b.classList.toggle('active', b.dataset.key === timeOfDay));
    if (st.locations) renderLocations(st.locations);

    // Cast tab
    if (st.characters) renderCharStatSheets(st.characters);

    // Storyline tab
    const activeEl = document.getElementById('activeScenarioDisplay');
    const badgeEl  = document.getElementById('scenarioLabel');
    if (activeEl) {
        const sc = st.active_scenario;
        activeEl.textContent = sc ? (SCENARIOS[sc]?.label || sc) : 'None';
        if (badgeEl) {
            badgeEl.textContent  = sc ? (SCENARIOS[sc]?.emoji + ' ' + (SCENARIOS[sc]?.label || sc)) : '';
            badgeEl.style.display = sc ? 'inline-block' : 'none';
        }
    }
    if (Array.isArray(st.story_beats)) renderStoryBeats(st.story_beats);

    // Props tab
    if (Array.isArray(st.room_props)) renderPropGrid(st.room_props);

    // Director tab — populate char dropdowns
    populateCharacterDropdowns(st.characters || {});

    // Director avatar
    updateDirectorAvatar(st.director_avatar || null);

    // Interact tab — populate move dropdown
    const moveCharSel = document.getElementById('moveCharSelect');
    if (moveCharSel && st.characters) {
        const current = moveCharSel.value;
        moveCharSel.innerHTML = '<option value="">— character —</option>';
        for (const [cid, info] of Object.entries(st.characters)) {
            moveCharSel.innerHTML += '<option value="' + cid + '">' + esc(info.name) + '</option>';
        }
        if (current) moveCharSel.value = current;
    }

    // Agent button
    updateAgentBtn();
    renderModelConfig();
}

// ═══════════════════════════════════════════════════════════════════════
//  SIDE-PANEL: Scene tab — compact char list
// ═══════════════════════════════════════════════════════════════════════
function renderCompactCharList(chars) {
    const el = document.getElementById('charListCompact');
    if (!el) return;
    el.innerHTML = '';
    let idx = 0;
    for (const [cid, info] of Object.entries(chars)) {
        const color = CHAR_COLORS[idx % CHAR_COLORS.length];
        const feeling = info.feeling || info.mood || 'neutral';
        const loc = info.location || '—';
        const div = document.createElement('div');
        div.className = 'char-compact';
        div.innerHTML =
            '<div class="char-dot" style="background:' + color + '"></div>' +
            '<strong>' + esc(info.name) + '</strong>' +
            '<span class="char-feeling">' + esc(feeling) + '</span>' +
            '<span class="char-loc">📍' + esc(loc) + '</span>' +
            '<button class="btn-x" onclick="removeChar(\'' + cid + '\')">✕</button>';
        el.appendChild(div);
        idx++;
    }
}

async function removeChar(cid) {
    await fetch('/api/character/remove', { method: 'POST', headers: { 'Content-Type': 'application/json' },
                                            body: JSON.stringify({ character_id: cid }) });
}

// ═══════════════════════════════════════════════════════════════════════
//  SIDE-PANEL: Cast tab — full stat sheets
// ═══════════════════════════════════════════════════════════════════════
const STAT_LIST = ['arousal','horniness','drunkenness','tiredness','happiness','anger','fear','pleasure','explicitness','openness'];

function renderCharStatSheets(chars) {
    const container = document.getElementById('charStatSheets');
    const noMsg = document.getElementById('noCharsMsg');
    if (!container) return;

    const hasChars = Object.keys(chars).length > 0;
    if (noMsg) noMsg.style.display = hasChars ? 'none' : 'block';
    if (!hasChars) { container.innerHTML = ''; return; }

    container.innerHTML = '';
    let idx = 0;
    for (const [cid, info] of Object.entries(chars)) {
        const color = CHAR_COLORS[idx % CHAR_COLORS.length];
        const stats = info.stats || {};
        const compliance = info.compliance_score != null ? info.compliance_score : 50;
        const feeling = info.feeling || info.mood || 'neutral';

        const sheet = document.createElement('div');
        sheet.className = 'stat-sheet';
        sheet.id = 'sheet-' + cid;

        // Header
        sheet.innerHTML =
            '<div class="stat-sheet-header">' +
                '<div class="char-dot" style="background:' + color + '"></div>' +
                '<span class="stat-sheet-name">' + esc(info.name) + '</span>' +
                '<span class="stat-sheet-feeling">' + esc(feeling) + '</span>' +
            '</div>';

        // Compliance
        sheet.innerHTML +=
            '<div class="compliance-label">Compliance: ' + Math.round(compliance) + '%</div>' +
            '<div class="compliance-bar"><div class="compliance-fill" style="width:' + compliance + '%"></div></div>';

        // Stat rows
        let rowsHtml = '<div class="stat-rows">';
        for (const stat of STAT_LIST) {
            const val = Math.round(stats[stat] != null ? stats[stat] : 0);
            rowsHtml +=
                '<div class="stat-row">' +
                    '<span class="stat-name">' + stat + '</span>' +
                    '<div class="stat-bar-track">' +
                        '<div class="stat-bar-fill stat-bar-' + stat + '" style="width:' + val + '%"></div>' +
                    '</div>' +
                    '<span class="stat-val">' + val + '</span>' +
                    '<div class="stat-quick">' +
                        '<button class="sq-btn" onclick="quickStat(\'' + cid + '\',\'' + stat + '\',-10)">-</button>' +
                        '<button class="sq-btn" onclick="quickStat(\'' + cid + '\',\'' + stat + '\',10)">+</button>' +
                    '</div>' +
                '</div>';
        }
        rowsHtml += '</div>';
        sheet.innerHTML += rowsHtml;

        // Outfit / position dropdowns
        const outfitOpts = (OUTFITS.length ? OUTFITS : (info.outfit ? [info.outfit] : []));
        const posOpts    = (POSITIONS.length ? POSITIONS : (info.position ? [info.position] : []));
        let selHtml = '<div class="stat-sheet-selects">';
        selHtml += '<select onchange="setOutfit(\'' + cid + '\',this.value)" title="Outfit">';
        outfitOpts.forEach(o => {
            selHtml += '<option value="' + esc(o) + '"' + (o === info.outfit ? ' selected' : '') + '>' + esc(o) + '</option>';
        });
        selHtml += '</select>';
        selHtml += '<select onchange="setPosition(\'' + cid + '\',this.value)" title="Position">';
        posOpts.forEach(p => {
            selHtml += '<option value="' + esc(p) + '"' + (p === info.position ? ' selected' : '') + '>' + esc(p) + '</option>';
        });
        selHtml += '</select>';
        selHtml += '</div>';
        sheet.innerHTML += selHtml;

        container.appendChild(sheet);
        idx++;
    }
}

async function quickStat(cid, stat, delta) {
    await postJSON('/api/character/stats/adjust', { character_id: cid, stat: stat, delta: delta });
}

async function setOutfit(cid, outfit) {
    await postJSON('/api/character/outfit', { character_id: cid, outfit });
}

async function setPosition(cid, position) {
    await postJSON('/api/character/position', { character_id: cid, position });
}

// ═══════════════════════════════════════════════════════════════════════
//  SIDE-PANEL: Locations
// ═══════════════════════════════════════════════════════════════════════
function renderLocations(locs) {
    const el = document.getElementById('locationList');
    if (!el) return;
    el.innerHTML = '';
    for (const [id, loc] of Object.entries(locs || {})) {
        const occ = (loc.occupants || []).length;
        const div = document.createElement('div');
        div.className = 'loc-item';
        div.innerHTML = '<span>' + esc(loc.name) + '</span><span class="loc-occ">' + occ + '</span>';
        el.appendChild(div);
    }
}

// ═══════════════════════════════════════════════════════════════════════
//  CHARACTER PICKER MODAL
// ═══════════════════════════════════════════════════════════════════════
async function openCharPicker() {
    try {
        const r = await fetch('/api/characters/list');
        const data = await r.json();
        allCharacters = data.characters || [];
    } catch (e) { console.error(e); return; }

    const list = document.getElementById('charPickerList');
    list.innerHTML = '';
    allCharacters.forEach(c => {
        const div = document.createElement('div');
        div.className = 'picker-item' + (c.loaded ? ' loaded' : '');
        div.innerHTML = '<strong>' + esc(c.name) + '</strong><small>' + esc(c.description || '') + '</small>';
        if (!c.loaded) div.onclick = () => pickChar(c.id);
        list.appendChild(div);
    });
    document.getElementById('charPickerModal').style.display = 'flex';
}

function closeCharPicker() { document.getElementById('charPickerModal').style.display = 'none'; }

async function pickChar(cid) {
    const personalityEl = document.getElementById('charPickerPersonality');
    const personality = personalityEl ? personalityEl.value : '';
    const body = { character_id: cid };
    if (personality) body.personality = personality;
    const r = await postJSON('/api/character/load', body);
    if (r.ok) closeCharPicker();
    else {
        const e = await r.json().catch(() => ({}));
        alert(e.error || 'Failed to load character');
    }
}

// ═══════════════════════════════════════════════════════════════════════
//  AGENT LOOP CONTROLS
// ═══════════════════════════════════════════════════════════════════════
async function toggleAgentLoop() {
    if (agentRunning) {
        await fetch('/api/agents/stop', { method: 'POST' });
        agentRunning = false;
    } else {
        const r = await postJSON('/api/agents/start', { interval: 30 });
        if (r.ok) agentRunning = true;
        else {
            const e = await r.json().catch(() => ({}));
            alert(e.error || 'Cannot start');
        }
    }
    updateAgentBtn();
}

async function manualTick() {
    const r = await fetch('/api/agents/tick', { method: 'POST' });
    if (r.ok) {
        const data = await r.json();
        (data.actions || []).forEach(a => addFeedEntry(a));
    }
}

function updateAgentBtn() {
    const btn    = document.getElementById('btnStartAgents');
    const status = document.getElementById('agentStatus');
    if (!btn) return;
    if (agentRunning) {
        btn.textContent    = '⏹ Stop';
        status.textContent = '● Agents Running';
        status.className   = 'agent-status on';
    } else {
        btn.textContent    = '▶ Start';
        status.textContent = '● Agents Off';
        status.className   = 'agent-status off';
    }
}

function toggleSidePanel() {
    const p = document.getElementById('sidePanel');
    if (p) p.style.display = p.style.display === 'none' ? '' : 'none';
}

// ═══════════════════════════════════════════════════════════════════════
//  TIME (lighting) & MODEL CONFIG
// ═══════════════════════════════════════════════════════════════════════
async function setTime(t) {
    await postJSON('/api/scene/time', { time: t });
}

let availableModels = [];

async function refreshModels() {
    try {
        const r = await fetch('/api/models/available');
        const data = await r.json();
        availableModels = [
            ...(data.loaded  || []).map(m => ({ id: m.id, label: (m.display_name || m.id) + ' (loaded)' })),
            ...(data.available || [])
                .filter(m => !(data.loaded || []).find(l => l.id === m.id))
                .map(m => ({ id: m.id, label: m.display_name || m.id })),
        ];
    } catch { availableModels = []; }
    renderModelConfig();
}

async function renderModelConfig() {
    const container = document.getElementById('modelConfigList');
    if (!container) return;
    let config = {};
    try { config = await (await fetch('/api/agents/model')).json(); } catch {}
    const chars = sceneState.characters || {};
    if (Object.keys(chars).length === 0) {
        container.innerHTML = '<p style="color:#888;font-size:12px">Load characters first</p>';
        return;
    }
    let html = '';
    for (const [cid, info] of Object.entries(chars)) {
        const cfg = config[cid] || {};
        const curMode = cfg.mode || 'default';
        html += `<div class="model-config-card">
            <div class="mcc-name">${esc(info.name)}</div>
            <select class="mcc-select" id="modelSel_${cid}" onchange="setAgentModel('${cid}')">
                <option value="">Default (loaded model)</option>
                ${availableModels.map(m =>
                    `<option value="${m.id}" ${m.id === cfg.model ? 'selected' : ''}>${esc(m.label)}</option>`
                ).join('')}
            </select>
            <div class="mcc-modes">
                <label><input type="radio" name="mode_${cid}" value="default" ${curMode==='default'?'checked':''} onchange="setAgentModel('${cid}')"> Standard</label>
                <label><input type="radio" name="mode_${cid}" value="speculative" ${curMode==='speculative'?'checked':''} onchange="setAgentModel('${cid}')"> Speculative</label>
                <label><input type="radio" name="mode_${cid}" value="concurrent" ${curMode==='concurrent'?'checked':''} onchange="setAgentModel('${cid}')"> Concurrent</label>
            </div>
        </div>`;
    }
    container.innerHTML = html;
}

async function setAgentModel(cid) {
    const modelSel  = document.getElementById(`modelSel_${cid}`);
    const modeRadio = document.querySelector(`input[name="mode_${cid}"]:checked`);
    const model = modelSel  ? modelSel.value  : '';
    const mode  = modeRadio ? modeRadio.value : 'default';
    await postJSON('/api/agents/model', { character_id: cid, model: model || null, mode });
}

async function sendWhisper() {
    const input  = document.getElementById('whisperInput');
    const target = document.getElementById('whisperTarget')?.value || '';
    const msg    = input?.value.trim();
    if (!msg) return;
    const body = { message: msg };
    if (target) body.character_id = target;
    await postJSON('/api/director/whisper', body);
    addFeedEntry({ character_name: '(Director ↯)', action: 'whisper', message: msg }, 'director');
    if (input) input.value = '';
}

// ═══════════════════════════════════════════════════════════════════════
//  DIRECTOR CONTROLS — Direct tab
// ═══════════════════════════════════════════════════════════════════════
async function enterScene() {
    const nameEl = document.getElementById('directorNameInput');
    const name   = nameEl ? nameEl.value.trim() || 'The Director' : 'The Director';
    const r = await postJSON('/api/director/enter_scene', { in_scene: true, name });
    const statusEl = document.getElementById('directorStatus');
    if (statusEl) {
        statusEl.textContent = r.ok ? '✅ In scene as ' + name : '❌ Failed';
    }
    addFeedEntry({ character_name: '(Director)', action: 'director',
                   message: name + ' entered the scene' });
}

async function exitScene() {
    await postJSON('/api/director/enter_scene', { in_scene: false });
    const statusEl = document.getElementById('directorStatus');
    if (statusEl) statusEl.textContent = '';
    addFeedEntry({ character_name: '(Director)', action: 'director', message: 'Director left the scene' });
}

async function giveLine() {
    const target  = document.getElementById('giveLineTarget')?.value;
    const lineEl  = document.getElementById('giveLineInput');
    const line    = lineEl?.value.trim();
    if (!line || !target) return alert('Pick a character and enter a line.');
    const r = await postJSON('/api/director/give_line', { character_id: target, line });
    const data = r.ok ? await r.json().catch(() => ({})) : {};
    const hintEl = document.getElementById('complianceHint');
    if (hintEl) hintEl.textContent = data.compliance_note || '';
    addFeedEntry({ character_name: '(Director → ' + (getCharName(target) || target) + ')',
                   action: 'director', message: '"' + line + '"' }, 'director');
    if (lineEl) lineEl.value = '';
}

async function giveAction() {
    const target = document.getElementById('giveActionTarget')?.value || '';
    const actEl  = document.getElementById('giveActionInput');
    const action = actEl?.value.trim();
    if (!action) return;
    const body = { action };
    if (target) body.character_id = target;
    await postJSON('/api/director/give_action', body);
    addFeedEntry({ character_name: '(Director)', action: 'director', message: '→ ' + action }, 'director');
    if (actEl) actEl.value = '';
}

async function startConversation(type) {
    const chars = Object.keys(sceneState.characters || {});
    await postJSON('/api/conversation/start', { type, character_ids: chars });
    addFeedEntry({ character_name: '(Director)', action: 'scenario', message: 'Conversation started: ' + type }, 'scenario');
}

// Update compliance hint when target changes
function updateComplianceHint(selectEl) {
    const cid = selectEl.value;
    const info = (sceneState.characters || {})[cid];
    const hint = document.getElementById('complianceHint');
    if (!hint) return;
    if (info && info.compliance_score != null) {
        const score = Math.round(info.compliance_score);
        const note  = score >= 70 ? 'Likely to comply ✓' : score >= 40 ? 'Might resist' : 'Will probably resist ✗';
        hint.textContent = 'Compliance: ' + score + '% — ' + note;
    } else {
        hint.textContent = '';
    }
}

function getCharName(cid) {
    return (sceneState.characters || {})[cid]?.name || null;
}

// ═══════════════════════════════════════════════════════════════════════
//  DIRECTOR CONTROLS — Storyline tab
// ═══════════════════════════════════════════════════════════════════════
function scenarioChanged() {
    const picker  = document.getElementById('scenarioPicker');
    const preview = document.getElementById('scenarioPreview');
    if (!picker || !preview) return;
    const key = picker.value;
    if (!key) { preview.style.display = 'none'; return; }
    const sc = SCENARIOS[key] || {};
    preview.style.display = 'block';
    preview.innerHTML = '<strong>' + esc(sc.emoji || '') + ' ' + esc(sc.label || key) + '</strong><br>' +
                        esc(sc.opening || '') + (sc.beats ? '<br><em>Beats: ' + sc.beats.length + '</em>' : '');
}

async function activateScenario() {
    const key = document.getElementById('scenarioPicker')?.value;
    if (!key) return alert('Pick a scenario first.');
    await postJSON('/api/scenario/set', { scenario_key: key });
    addFeedEntry({ character_name: '(Director)', action: 'scenario',
                   message: 'Scenario activated: ' + (SCENARIOS[key]?.label || key) }, 'scenario');
}

async function clearScenario() {
    await postJSON('/api/scenario/clear', {});
    addFeedEntry({ character_name: '(Director)', action: 'scenario', message: 'Scenario cleared' }, 'scenario');
}

async function injectBeat() {
    const beatEl = document.getElementById('newBeatInput');
    const text   = beatEl?.value.trim();
    if (!text) return;
    await postJSON('/api/story/beat', { beat: text });
    addFeedEntry({ character_name: '(Director)', action: 'scenario', message: '📌 Beat: ' + text }, 'scenario');
    if (beatEl) beatEl.value = '';
}

function renderStoryBeats(beats) {
    const list = document.getElementById('storyBeatsList');
    if (!list) return;
    list.innerHTML = '';
    if (!beats.length) {
        list.innerHTML = '<span class="muted-hint">No beats queued</span>';
        return;
    }
    beats.forEach((b, i) => {
        const item = document.createElement('div');
        item.className = 'beat-item';
        item.innerHTML =
            '<span class="beat-text">' + esc(b) + '</span>' +
            '<button class="beat-remove" onclick="removeBeat(' + i + ')">✕</button>';
        list.appendChild(item);
    });
}

async function removeBeat(index) {
    await postJSON('/api/story/clear_beat', { index });
}

async function directorBroadcast() {
    const el  = document.getElementById('broadcastInput');
    const msg = el?.value.trim();
    if (!msg) return;
    await postJSON('/api/director/broadcast', { message: msg });
    addFeedEntry({ character_name: '(Director → ALL)', action: 'director', message: msg }, 'director');
    if (el) el.value = '';
}

async function directorSend() {
    const el  = document.getElementById('directorChatInput');
    const msg = el?.value.trim();
    if (!msg) return;
    await postJSON('/api/director/broadcast', { message: msg });
    addFeedEntry({ character_name: '(Director)', action: 'director', message: msg }, 'director');
    if (el) el.value = '';
}

// ═══════════════════════════════════════════════════════════════════════
//  DIRECTOR CONTROLS — Props tab
// ═══════════════════════════════════════════════════════════════════════
async function toggleProp(pid) {
    const btn = document.getElementById('prop-' + pid);
    const active = btn && btn.classList.contains('active');
    if (active) {
        await postJSON('/api/props/remove', { prop_id: pid });
    } else {
        await postJSON('/api/props/add', { prop_id: pid });
    }
}

function renderPropGrid(roomProps) {
    document.querySelectorAll('.prop-btn').forEach(btn => {
        const pid = btn.dataset.pid;
        btn.classList.toggle('active', roomProps.includes(pid));
    });
}

async function givePropToChar() {
    const charEl = document.getElementById('givePropChar');
    const itemEl = document.getElementById('givePropItem');
    const cid    = charEl?.value;
    const pid    = itemEl?.value;
    if (!cid || !pid) return alert('Pick a character and a prop.');
    await postJSON('/api/props/give', { character_id: cid, prop_id: pid });
    addFeedEntry({ character_name: '(Director)', action: 'director',
                   message: 'Gave ' + pid + ' to ' + (getCharName(cid) || cid) }, 'director');
}

// ═══════════════════════════════════════════════════════════════════════
//  DIRECTOR CONTROLS — Events tab
// ═══════════════════════════════════════════════════════════════════════
async function fireEvent(type) {
    await postJSON('/api/event/fire', { type });
    addFeedEntry({ character_name: '(Event)', action: 'environment', message: type.replace(/_/g, ' ') }, 'environment');
    triggerEventEffect(type);
}

async function fireCustomEvent() {
    const el   = document.getElementById('customEventInput');
    const desc = el?.value.trim();
    if (!desc) return;
    await postJSON('/api/event/fire', { type: 'custom', custom: desc });
    addFeedEntry({ character_name: '(Event)', action: 'environment', message: desc }, 'environment');
    if (el) el.value = '';
}

// ═══════════════════════════════════════════════════════════════════════
//  THREE.JS VISUAL EVENT EFFECTS
// ═══════════════════════════════════════════════════════════════════════
function triggerEventEffect(type) {
    switch (type) {
        case 'flicker_lights':
            (function() {
                const orig = renderer.toneMappingExposure;
                let n = 0;
                const iv = setInterval(() => {
                    renderer.toneMappingExposure = n++ % 2 === 0 ? 0.05 : orig * 1.5;
                    if (n > 8) { clearInterval(iv); renderer.toneMappingExposure = orig; }
                }, 100);
            })();
            break;
        case 'cold_draft':
            scene.fog = new THREE.FogExp2(0x1a2040, 0.08);
            setTimeout(() => { scene.fog = null; }, 4000);
            break;
        case 'power_out':
            const origBg = scene.background.clone();
            scene.background = new THREE.Color(0x000000);
            scene.children.filter(c => c.isLight).forEach(l => { l.userData._oi = l.intensity; l.intensity = 0; });
            setTimeout(() => {
                scene.background = origBg;
                scene.children.filter(c => c.isLight).forEach(l => { l.intensity = l.userData._oi || 1; });
            }, 2500);
            break;
        case 'romantic_mood':
            scene.children.filter(c => c.isPointLight).forEach(l => {
                l.color.set(0xff6644); l.intensity *= 0.6;
            });
            setTimeout(() => applyLighting(sceneState.lighting || {}), 8000);
            break;
        case 'thunder':
            const flash = new THREE.PointLight(0xffffff, 5, 50);
            flash.position.set(0, 10, 0);
            scene.add(flash);
            setTimeout(() => { flash.intensity = 0; }, 100);
            setTimeout(() => { flash.intensity = 3; }, 200);
            setTimeout(() => { scene.remove(flash); }, 400);
            break;
        case 'candles_light':
            scene.children.filter(c => c.isPointLight).forEach(l => {
                l.color.set(0xff8800); l.intensity = Math.min(l.intensity * 1.4, 2);
            });
            break;
        case 'move_object':
            const objs = scene.children.filter(c => c.isMesh && c.castShadow && c !== ambientLight);
            if (objs.length) {
                const obj = objs[Math.floor(Math.random() * objs.length)];
                const op = obj.position.clone();
                let s = 0;
                const iv2 = setInterval(() => {
                    obj.position.x = op.x + (Math.random() - 0.5) * 0.15;
                    obj.position.z = op.z + (Math.random() - 0.5) * 0.15;
                    if (++s > 12) { clearInterval(iv2); obj.position.copy(op); }
                }, 60);
            }
            break;
    }
}

// ═══════════════════════════════════════════════════════════════════════
//  TAB SYSTEM
// ═══════════════════════════════════════════════════════════════════════
function showTab(name) {
    document.querySelectorAll('.tab-content').forEach(el => el.classList.remove('active'));
    document.querySelectorAll('.tab-btn').forEach(b => b.classList.remove('active'));
    const content = document.getElementById('tab-' + name);
    if (content) content.classList.add('active');
    document.querySelectorAll('.tab-btn').forEach(b => {
        if (b.dataset.tab === name) b.classList.add('active');
    });
}

// ═══════════════════════════════════════════════════════════════════════
//  FEED
// ═══════════════════════════════════════════════════════════════════════
const ACTION_ICONS = {
    speak: '💬', move: '🚶', idle: '😌', flirt: '😏', touch: '✋',
    kiss: '💋', cuddle: '🤗', intimate: '🔥', interact: '🎯', whisper: '🤫',
    director: '🎬', scenario: '📖', environment: '🌐', system: '⚙️',
};

function addFeedEntry(data, feedType) {
    const feed = document.getElementById('feedMessages');
    if (!feed) return;

    const action = feedType || data.action || 'speak';
    const icon   = ACTION_ICONS[action] || ACTION_ICONS[data.action] || '▪';
    const name   = data.character_name || data.name || '?';
    const msg    = data.message || data.detail || data.action || '';

    const div = document.createElement('div');
    div.className    = 'feed-entry feed-' + action;
    div.dataset.feedType = action;
    div.innerHTML =
        '<span class="feed-icon">' + icon + '</span>' +
        '<span class="feed-name">' + esc(name) + '</span>' +
        '<span class="feed-msg">' + esc(msg) + '</span>';

    if (activeFeedFilter && activeFeedFilter !== action) {
        div.dataset.feedType = 'hidden';
    }

    feed.appendChild(div);
    feed.scrollTop = feed.scrollHeight;
    while (feed.children.length > 300) feed.removeChild(feed.firstChild);

    if (sceneState.locations) renderLocations(sceneState.locations);
}

function clearFeed() {
    const feed = document.getElementById('feedMessages');
    if (feed) feed.innerHTML = '';
}

function filterFeed(type) {
    activeFeedFilter = type;
    const feed = document.getElementById('feedMessages');
    if (!feed) return;
    feed.querySelectorAll('.feed-entry').forEach(el => {
        const t = el.dataset.feedType;
        if (!type || t === type) {
            el.style.display = '';
        } else {
            el.style.display = 'none';
        }
    });
}

// ═══════════════════════════════════════════════════════════════════════
//  POPULATE CHARACTER DROPDOWNS
// ═══════════════════════════════════════════════════════════════════════
function populateCharacterDropdowns(chars) {
    const ids = ['whisperTarget', 'giveLineTarget', 'giveActionTarget', 'givePropChar'];
    ids.forEach(elId => {
        const sel = document.getElementById(elId);
        if (!sel) return;
        const cur = sel.value;
        // Keep a blank option for multi-target
        sel.innerHTML = '<option value="">All / —</option>';
        for (const [cid, info] of Object.entries(chars)) {
            const opt = document.createElement('option');
            opt.value = cid;
            opt.textContent = info.name;
            sel.appendChild(opt);
        }
        if (cur) sel.value = cur;
    });
}

// ═══════════════════════════════════════════════════════════════════════
//  CONSTANTS LOADER
// ═══════════════════════════════════════════════════════════════════════
async function loadConstants() {
    try {
        const r = await fetch('/api/meta/constants');
        if (r.ok) {
            const data = await r.json();
            if (data.positions)     POSITIONS = data.positions;
            if (data.outfits)       OUTFITS = data.outfits;
            if (data.scenarios)     SCENARIOS = data.scenarios;
            if (data.personalities) PERSONALITIES = data.personalities;
        }
    } catch (e) { console.warn('loadConstants failed', e); }
}

// ═══════════════════════════════════════════════════════════════════════
//  HELPERS
// ═══════════════════════════════════════════════════════════════════════
function esc(str) {
    const d = document.createElement('div');
    d.textContent = str || '';
    return d.innerHTML;
}

async function postJSON(url, body) {
    return fetch(url, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(body),
    });
}

// ═══════════════════════════════════════════════════════════════════════
//  DIRECTOR AVATAR
// ═══════════════════════════════════════════════════════════════════════
let directorSprite = null;

async function placeDirectorAvatar() {
    const name = document.getElementById('directorNameInput')?.value || 'Director';
    const gender = document.getElementById('dirAvatarGender')?.value || 'male';
    const skinTone = document.getElementById('dirAvatarSkin')?.value || 'fair';
    const hairColor = document.getElementById('dirAvatarHair')?.value || 'brown';
    const outfit = document.getElementById('dirAvatarOutfit')?.value || 'casual';
    const locationId = document.getElementById('dirAvatarLocation')?.value || 'bed';

    const resp = await fetch('/api/director/avatar', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ action: 'place', name, gender, skin_tone: skinTone, hair_color: hairColor, outfit, location_id: locationId })
    });
    if (!resp.ok) return;
    addFeedEntry({ character_name: '(Director)', action: 'director', message: `${name}'s avatar placed at ${locationId}` }, 'director');
}

async function removeDirectorAvatar() {
    await fetch('/api/director/avatar', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ action: 'remove' })
    });
    if (directorSprite) {
        scene.remove(directorSprite.group);
        directorSprite = null;
    }
    addFeedEntry({ character_name: '(Director)', action: 'director', message: 'Director avatar removed' }, 'director');
}

function updateDirectorAvatar(avatarData) {
    if (!avatarData) {
        if (directorSprite) {
            scene.remove(directorSprite.group);
            directorSprite = null;
        }
        return;
    }
    if (!directorSprite) {
        directorSprite = CharModels.create({
            name: avatarData.name || 'Director',
            charColor: '#ffcc00',
            gender: avatarData.gender || 'male',
        });
        scene.add(directorSprite.group);
        directorSprite.targetPos = new THREE.Vector3(0, 0, 0);
        directorSprite.currentOutfit = null;
    }
    // Update outfit
    const outfit = avatarData.outfit || 'casual';
    if (directorSprite.currentOutfit !== outfit) {
        CharModels.updateOutfit(directorSprite, outfit);
        directorSprite.currentOutfit = outfit;
    }
    // Position based on location
    const locId = avatarData.location_id || 'bed';
    const locations = sceneState.locations || {};
    const loc = locations[locId];
    if (loc && loc.pos) {
        directorSprite.targetPos.set(loc.pos.x + 1.0, 0, loc.pos.z);
    }
}

// ═══════════════════════════════════════════════════════════════════════
//  FURNITURE INTERACTION BUTTONS
// ═══════════════════════════════════════════════════════════════════════
const LOCATION_EMOJIS = {
    bed: '🛏', couch: '🛋', fireplace: '🔥', bar: '🍸',
    bathroom: '🛁', vanity: '💄', balcony: '🌙', doorway: '🚪',
};
let interactLocationsData = null;
let selectedInteractLocation = null;

async function loadInteractLocations() {
    try {
        const resp = await fetch('/api/scene/locations');
        interactLocationsData = await resp.json();
        renderInteractGrid();
    } catch (e) {
        console.warn('Failed to load locations:', e);
    }
}

function renderInteractGrid() {
    const el = document.getElementById('interactLocationGrid');
    if (!el || !interactLocationsData) return;
    el.innerHTML = '';
    for (const [id, loc] of Object.entries(interactLocationsData)) {
        const btn = document.createElement('button');
        btn.className = 'interact-loc-btn' + (selectedInteractLocation === id ? ' active' : '');
        btn.innerHTML = (LOCATION_EMOJIS[id] || '📍') + ' ' + esc(loc.name);
        btn.onclick = () => selectInteractLocation(id);
        el.appendChild(btn);
    }
}

function selectInteractLocation(locId) {
    selectedInteractLocation = locId;
    renderInteractGrid();
    const loc = interactLocationsData?.[locId];
    const titleEl = document.getElementById('interactLocationTitle');
    const actionsEl = document.getElementById('interactActions');
    if (!loc || !actionsEl) return;
    if (titleEl) { titleEl.textContent = loc.name; titleEl.style.display = 'block'; }
    actionsEl.innerHTML = '';
    (loc.interactions || []).forEach(action => {
        const btn = document.createElement('button');
        btn.className = 'interact-action-btn';
        btn.textContent = action;
        btn.onclick = () => doFurnitureInteract(locId, action);
        actionsEl.appendChild(btn);
    });
}

async function doFurnitureInteract(locationId, interaction) {
    await fetch('/api/scene/furniture_interact', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ location_id: locationId, interaction, actor: 'director' })
    });
    addFeedEntry({ character_name: '(Director)', action: 'director', message: `${interaction} at the ${locationId}` }, 'director');
}

async function quickMoveChar() {
    const cid = document.getElementById('moveCharSelect')?.value;
    const locId = document.getElementById('moveLocSelect')?.value;
    if (!cid || !locId) return;
    await fetch('/api/director/mount', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ character_id: cid, location_id: locId, position: 'standing' })
    });
}

// ═══════════════════════════════════════════════════════════════════════
//  SETTINGS
// ═══════════════════════════════════════════════════════════════════════
function updateSetting(key, value) {
    switch (key) {
        case 'cameraSpeed':
            controls.rotateSpeed = parseFloat(value) / 5;
            break;
        case 'fov':
            camera.fov = parseInt(value);
            camera.updateProjectionMatrix();
            break;
        case 'ambient':
            ambientLight.intensity = parseInt(value) / 100;
            break;
        case 'shadows':
            if (value === 'off') {
                renderer.shadowMap.enabled = false;
            } else {
                renderer.shadowMap.enabled = true;
                const size = { high: 2048, medium: 1024, low: 512 }[value] || 1024;
                directionalLight.shadow.mapSize.set(size, size);
                directionalLight.shadow.map?.dispose();
                directionalLight.shadow.map = null;
            }
            break;
        case 'fireIntensity':
            // Adjust fireplace-related point lights
            pointLights.forEach(pl => {
                if (pl.position.y < 1.0 && pl.position.z > 2.0) {
                    pl.intensity = (parseInt(value) / 100) * 0.8;
                }
            });
            break;
        case 'wallColor':
            scene.children.forEach(c => {
                if (c.isMesh && c.material?.color && c.position.y > 1 && (Math.abs(c.position.x) > 6 || Math.abs(c.position.z) > 5.5)) {
                    c.material.color.set(value);
                }
            });
            break;
        case 'floorColor':
            scene.children.forEach(c => {
                if (c.isMesh && c.rotation.x < -1.5 && c.position.y < 0.02 && !c.position.z) {
                    c.material.color.set(value);
                }
            });
            break;
        case 'rugColor':
            scene.children.forEach(c => {
                if (c.isMesh && c.rotation.x < -1.5 && c.position.y > 0.005 && c.position.y < 0.02) {
                    c.material.color.set(value);
                }
            });
            break;
        case 'zoom': {
            const dist = parseFloat(value);
            const dir = new THREE.Vector3().subVectors(camera.position, controls.target).normalize();
            camera.position.copy(controls.target).addScaledVector(dir, dist);
            break;
        }
    }
}

// ═══════════════════════════════════════════════════════════════════════
//  CAMERA VIEW SYSTEM
// ═══════════════════════════════════════════════════════════════════════
function switchCameraView(viewName) {
    const view = CAMERA_VIEWS[viewName];
    if (!view) return;
    currentView = viewName;
    cameraAnimating = true;

    // Smoothly animate camera position and target
    const startPos = camera.position.clone();
    const startTarget = controls.target.clone();
    const endPos = new THREE.Vector3(view.pos.x, view.pos.y, view.pos.z);
    const endTarget = new THREE.Vector3(view.target.x, view.target.y, view.target.z);
    const startFov = camera.fov;
    const endFov = view.fov || 55;
    const duration = 800;
    const startTime = performance.now();

    function animateCamera(now) {
        const elapsed = now - startTime;
        const t = Math.min(elapsed / duration, 1);
        // Smooth ease-in-out
        const ease = t < 0.5 ? 2 * t * t : 1 - Math.pow(-2 * t + 2, 2) / 2;

        camera.position.lerpVectors(startPos, endPos, ease);
        controls.target.lerpVectors(startTarget, endTarget, ease);
        camera.fov = startFov + (endFov - startFov) * ease;
        camera.updateProjectionMatrix();
        controls.update();

        if (t < 1) {
            requestAnimationFrame(animateCamera);
        } else {
            cameraAnimating = false;
        }
    }
    requestAnimationFrame(animateCamera);

    // Update the view preset buttons
    document.querySelectorAll('.view-preset-btn').forEach(b => {
        b.classList.toggle('active', b.dataset.view === viewName);
    });
    // Update FOV slider
    const fovSlider = document.getElementById('settingFov');
    if (fovSlider) fovSlider.value = view.fov || 55;
}

function cycleView(direction) {
    const keys = Object.keys(CAMERA_VIEWS);
    const idx = keys.indexOf(currentView);
    const next = (idx + direction + keys.length) % keys.length;
    switchCameraView(keys[next]);
}

function buildViewPresetButtons() {
    const grid = document.getElementById('viewPresetsGrid');
    if (!grid) return;
    grid.innerHTML = '';
    for (const [key, view] of Object.entries(CAMERA_VIEWS)) {
        const btn = document.createElement('button');
        btn.className = 'view-preset-btn' + (key === currentView ? ' active' : '');
        btn.dataset.view = key;
        btn.textContent = view.label;
        btn.onclick = () => switchCameraView(key);
        grid.appendChild(btn);
    }
}

window.addEventListener('resize', () => {
    camera.aspect = window.innerWidth / window.innerHeight;
    camera.updateProjectionMatrix();
    renderer.setSize(window.innerWidth, window.innerHeight);
});

window.addEventListener('load', init);

// ═══════════════════════════════════════════════════════════════════════
//  AMBIENT AUDIO SYSTEM
// ═══════════════════════════════════════════════════════════════════════
let ambientAudio = null;

async function loadAmbientTracks() {
    try {
        const res = await fetch('/api/ambient/tracks');
        const tracks = await res.json();
        const sel = document.getElementById('ambientTrack');
        if (!sel) return;
        sel.innerHTML = '<option value="">Off</option>';
        tracks.forEach(t => {
            const opt = document.createElement('option');
            opt.value = t;
            opt.textContent = t.replace(/\.[^.]+$/, '').replace(/[-_]/g, ' ');
            sel.appendChild(opt);
        });
    } catch (e) { /* no ambient tracks available */ }
}

function setAmbientTrack(track) {
    if (ambientAudio) { ambientAudio.pause(); ambientAudio = null; }
    if (!track) return;
    ambientAudio = new Audio('/static/audio/' + track);
    ambientAudio.loop = true;
    ambientAudio.volume = (document.getElementById('ambientVolume')?.value || 30) / 100;
    ambientAudio.play().catch(() => {});
}

function setAmbientVolume(val) {
    if (ambientAudio) ambientAudio.volume = val / 100;
}

// ─── Legacy menace() kept for backwards compatibility ──────────────────
async function menace(type) {
    triggerEventEffect(type);
    await fireEvent(type);
}
