/**
 * Bedroom Scene v4 — Director Control Center
 * Three.js 3D room + full Director UI (stats, scenarios, props, events)
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
    roomSize: { w: 14, h: 4, d: 12 },
};

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
    controls.minDistance = 5;
    controls.maxDistance = 25;
    controls.maxPolarAngle = Math.PI / 2.1;
    controls.update();

    createLighting();
    createRoom();
    connectSocket();
    loadConstants();
    fetchState();
    loadAmbientTracks();

    animate();
    console.log('Bedroom v4 initialized');
}

// ═══════════════════════════════════════════════════════════════════════
//  LIGHTING
// ═══════════════════════════════════════════════════════════════════════
function createLighting() {
    ambientLight = new THREE.AmbientLight(0xffffff, 0.2);
    scene.add(ambientLight);

    directionalLight = new THREE.DirectionalLight(0xffeedd, 0.5);
    directionalLight.position.set(5, 10, 5);
    directionalLight.castShadow = true;
    directionalLight.shadow.mapSize.set(1024, 1024);
    scene.add(directionalLight);

    // Warm lamps at key locations
    const lampPositions = [
        { x: -3, y: 2.5, z: -3, color: 0xffaa66, intensity: 0.6 },  // bedside
        { x: 3, y: 2.5, z: 0, color: 0xffd4a3, intensity: 0.4 },    // couch area
        { x: -5, y: 2.5, z: 2, color: 0xddaaff, intensity: 0.3 },   // vanity
        { x: 0, y: 3.2, z: -4, color: 0xffccaa, intensity: 0.5 },   // bar
        { x: 5, y: 2.5, z: -4, color: 0x88bbff, intensity: 0.25 },  // bathroom cool
        { x: 5, y: 2, z: 4, color: 0x667eea, intensity: 0.3 },      // balcony moonlight
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

    // ── Area rug ──
    const rugGeo = new THREE.PlaneGeometry(6, 4);
    const rugMat = new THREE.MeshStandardMaterial({ color: 0x4a2040, roughness: 0.95 });
    const rug = new THREE.Mesh(rugGeo, rugMat);
    rug.rotation.x = -Math.PI / 2;
    rug.position.set(0, 0.01, -1);
    scene.add(rug);

    // ── Build furniture ──
    buildBed();
    buildCouch();
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
    // Frame
    _box(3.2, 0.4, 2.4, 0x5c3a1e, -3, 0.2, -3);          // base
    _box(3.2, 0.2, 2.4, 0xeeeeee, -3, 0.5, -3, false);    // mattress (white)
    _box(3.2, 0.12, 2.4, 0xcc4466, -3, 0.62, -3, false);   // bedspread
    _box(3.2, 0.8, 0.12, 0x5c3a1e, -3, 0.6, -4.15);       // headboard
    // Pillows
    _box(0.6, 0.15, 0.4, 0xffeeff, -3.5, 0.72, -3.8, false);
    _box(0.6, 0.15, 0.4, 0xffeeff, -2.5, 0.72, -3.8, false);
    // Bedside table
    _box(0.5, 0.6, 0.5, 0x4a3520, -4.8, 0.3, -3.8);
    // Lamp on bedside table
    _box(0.12, 0.4, 0.12, 0xddccaa, -4.8, 0.8, -3.8, false);
    const lampShade = new THREE.Mesh(
        new THREE.CylinderGeometry(0.08, 0.18, 0.2, 16),
        new THREE.MeshStandardMaterial({ color: 0xffeecc, emissive: 0xffaa44, emissiveIntensity: 0.4, transparent: true, opacity: 0.8 })
    );
    lampShade.position.set(-4.8, 1.1, -3.8);
    scene.add(lampShade);
}

function buildCouch() {
    // Base
    _box(2.5, 0.45, 1.0, 0x3a2244, 3, 0.22, 0);
    // Back
    _box(2.5, 0.6, 0.15, 0x3a2244, 3, 0.6, -0.45);
    // Armrests
    _box(0.15, 0.35, 1.0, 0x3a2244, 1.82, 0.5, 0);
    _box(0.15, 0.35, 1.0, 0x3a2244, 4.18, 0.5, 0);
    // Cushions
    _box(1.1, 0.12, 0.8, 0x5c3060, 2.5, 0.5, 0.05, false);
    _box(1.1, 0.12, 0.8, 0x5c3060, 3.5, 0.5, 0.05, false);
    // Coffee table
    _box(1.4, 0.35, 0.6, 0x2a1a15, 3, 0.17, 1.3);
    // TV on back wall
    _box(2.0, 1.2, 0.06, 0x111111, 3, 2.6, -5.9);
    const screenMat = new THREE.MeshStandardMaterial({ color: 0x222244, emissive: 0x112244, emissiveIntensity: 0.15 });
    const screen = new THREE.Mesh(new THREE.BoxGeometry(1.8, 1.0, 0.02), screenMat);
    screen.position.set(3, 2.6, -5.85);
    scene.add(screen);
}

function buildBar() {
    // Counter
    _box(2.0, 1.1, 0.5, 0x2a1810, 0, 0.55, -4.5);
    // Top surface (darker polished)
    _box(2.1, 0.06, 0.55, 0x1a0e08, 0, 1.12, -4.5, false);
    // Stools
    for (let i = -0.5; i <= 0.5; i += 1.0) {
        // Stool leg
        const legMat = new THREE.MeshStandardMaterial({ color: 0x888888, metalness: 0.8, roughness: 0.3 });
        const leg = new THREE.Mesh(new THREE.CylinderGeometry(0.04, 0.04, 0.7, 8), legMat);
        leg.position.set(i, 0.35, -3.8);
        scene.add(leg);
        // Stool seat
        const seat = new THREE.Mesh(
            new THREE.CylinderGeometry(0.2, 0.18, 0.08, 16),
            new THREE.MeshStandardMaterial({ color: 0x333333 })
        );
        seat.position.set(i, 0.72, -3.8);
        seat.castShadow = true;
        scene.add(seat);
    }
    // Bottles
    [0xaa3333, 0x33aa33, 0x3333aa].forEach((c, i) => {
        const bottle = new THREE.Mesh(
            new THREE.CylinderGeometry(0.05, 0.06, 0.3, 8),
            new THREE.MeshStandardMaterial({ color: c, transparent: true, opacity: 0.7 })
        );
        bottle.position.set(-0.5 + i * 0.4, 1.3, -4.7);
        scene.add(bottle);
    });
}

function buildVanity() {
    // Table
    _box(1.6, 0.8, 0.5, 0x4a3520, -5.5, 0.4, 2);
    // Mirror (reflective plane)
    const mirrorMat = new THREE.MeshStandardMaterial({ color: 0xaabbcc, metalness: 0.9, roughness: 0.1 });
    const mirror = new THREE.Mesh(new THREE.BoxGeometry(1.2, 1.0, 0.04), mirrorMat);
    mirror.position.set(-5.5, 1.5, 2);
    mirror.rotation.y = Math.PI / 2;
    scene.add(mirror);
    // Mirror frame
    _box(0.04, 1.1, 1.3, 0x8b7355, -5.5, 1.5, 2, false);
    // Stool
    const stool = new THREE.Mesh(
        new THREE.CylinderGeometry(0.2, 0.2, 0.45, 16),
        new THREE.MeshStandardMaterial({ color: 0xcc88aa })
    );
    stool.position.set(-4.8, 0.22, 2);
    stool.castShadow = true;
    scene.add(stool);
}

function buildBathroomFixtures() {
    // Partition wall (half wall)
    _box(0.1, 2.5, 3, 0x2a2a3d, 4.5, 1.25, -4);
    // Bathtub
    const tubMat = new THREE.MeshStandardMaterial({ color: 0xdddddd, roughness: 0.3 });
    const tub = new THREE.Mesh(new THREE.BoxGeometry(1.8, 0.6, 0.8), tubMat);
    tub.position.set(5.8, 0.3, -4);
    tub.castShadow = true;
    scene.add(tub);
    // Water
    const water = new THREE.Mesh(
        new THREE.BoxGeometry(1.6, 0.02, 0.6),
        new THREE.MeshStandardMaterial({ color: 0x4488bb, transparent: true, opacity: 0.5 })
    );
    water.position.set(5.8, 0.55, -4);
    scene.add(water);
    // Sink
    _box(0.5, 0.05, 0.4, 0xdddddd, 5.8, 0.9, -2.5, false);
    _box(0.1, 0.9, 0.3, 0xaaaaaa, 5.8, 0.45, -2.5);
}

function buildBalcony() {
    // Balcony floor (slightly elevated)
    _box(3, 0.1, 2, 0x555555, 5, 0.05, 4, false);
    // Railing
    const railMat = new THREE.MeshStandardMaterial({ color: 0x888888, metalness: 0.7, roughness: 0.3 });
    // Front rail
    const frontRail = new THREE.Mesh(new THREE.BoxGeometry(3, 0.06, 0.06), railMat);
    frontRail.position.set(5, 1.0, 5);
    scene.add(frontRail);
    // Side rails
    const sideRail1 = new THREE.Mesh(new THREE.BoxGeometry(0.06, 0.06, 2), railMat);
    sideRail1.position.set(3.5, 1.0, 4);
    scene.add(sideRail1);
    const sideRail2 = new THREE.Mesh(new THREE.BoxGeometry(0.06, 0.06, 2), railMat);
    sideRail2.position.set(6.5, 1.0, 4);
    scene.add(sideRail2);
    // Vertical posts
    for (let x = 3.5; x <= 6.5; x += 0.75) {
        const post = new THREE.Mesh(new THREE.CylinderGeometry(0.02, 0.02, 1, 6), railMat);
        post.position.set(x, 0.5, 5);
        scene.add(post);
    }
    // Small table + chairs
    _box(0.6, 0.5, 0.6, 0x5a4a3a, 5, 0.25, 3.8);
    const chairMat = new THREE.MeshStandardMaterial({ color: 0x444444 });
    [-0.6, 0.6].forEach(off => {
        const chair = new THREE.Mesh(new THREE.BoxGeometry(0.4, 0.4, 0.4), chairMat);
        chair.position.set(5 + off, 0.2, 3.3);
        chair.castShadow = true;
        scene.add(chair);
    });
}

function buildDecorations() {
    // Ceiling light fixture
    const fixtureMat = new THREE.MeshStandardMaterial({ color: 0xddccaa, emissive: 0xffddaa, emissiveIntensity: 0.3 });
    const fixture = new THREE.Mesh(new THREE.SphereGeometry(0.3, 16, 16), fixtureMat);
    fixture.position.set(0, 3.7, -1);
    scene.add(fixture);

    // Picture frames on back wall
    [{ x: -2, c: 0x663344 }, { x: 2, c: 0x334466 }].forEach(p => {
        _box(0.8, 0.6, 0.03, 0x5c3a1e, p.x, 2.5, -5.9, false);  // frame
        _box(0.7, 0.5, 0.02, p.c, p.x, 2.5, -5.88, false);       // canvas
    });

    // Potted plant near doorway
    _box(0.3, 0.3, 0.3, 0x4a3520, -1, 0.15, 4.5, false);  // pot
    const leavesGeo = new THREE.SphereGeometry(0.35, 8, 8);
    const leavesMat = new THREE.MeshStandardMaterial({ color: 0x2d6b2d, roughness: 0.9 });
    const leaves = new THREE.Mesh(leavesGeo, leavesMat);
    leaves.position.set(-1, 0.6, 4.5);
    scene.add(leaves);

    // Candles on bar
    for (let i = 0; i < 2; i++) {
        const candle = new THREE.Mesh(
            new THREE.CylinderGeometry(0.03, 0.03, 0.15, 8),
            new THREE.MeshStandardMaterial({ color: 0xeeeecc })
        );
        candle.position.set(0.7 + i * 0.3, 1.2, -4.7);
        scene.add(candle);
        // Flame glow
        const flame = new THREE.PointLight(0xff8800, 0.15, 2);
        flame.position.set(0.7 + i * 0.3, 1.32, -4.7);
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

// ═══════════════════════════════════════════════════════════════════════
//  CHARACTER SPRITES
// ═══════════════════════════════════════════════════════════════════════
function ensureCharSprite(charId, name, colorIdx) {
    if (charSprites[charId]) return charSprites[charId];

    const color = new THREE.Color(CHAR_COLORS[colorIdx % CHAR_COLORS.length]);
    const group = new THREE.Group();

    // Body — tapered cylinder with emissive outline
    const bodyGeo = new THREE.CylinderGeometry(0.22, 0.3, 1.3, 16);
    const bodyMat = new THREE.MeshStandardMaterial({ color, roughness: 0.4, metalness: 0.1 });
    const body = new THREE.Mesh(bodyGeo, bodyMat);
    body.position.y = 0.65;
    body.castShadow = true;
    group.add(body);

    // Shoulders
    const shoulderGeo = new THREE.SphereGeometry(0.28, 12, 8, 0, Math.PI * 2, 0, Math.PI / 2);
    const shoulderMat = new THREE.MeshStandardMaterial({ color, roughness: 0.5 });
    const shoulders = new THREE.Mesh(shoulderGeo, shoulderMat);
    shoulders.position.y = 1.3;
    group.add(shoulders);

    // Head
    const headGeo = new THREE.SphereGeometry(0.22, 16, 16);
    const headMat = new THREE.MeshStandardMaterial({ color: 0xffd5b4, roughness: 0.6 });
    const head = new THREE.Mesh(headGeo, headMat);
    head.position.y = 1.6;
    head.castShadow = true;
    group.add(head);

    // Hair (half-sphere on top)
    const hairGeo = new THREE.SphereGeometry(0.24, 16, 8, 0, Math.PI * 2, 0, Math.PI / 2);
    const hairColor = colorIdx === 0 ? 0x2a1a0a : 0x4a3020;
    const hairMat = new THREE.MeshStandardMaterial({ color: hairColor, roughness: 0.8 });
    const hair = new THREE.Mesh(hairGeo, hairMat);
    hair.position.y = 1.68;
    group.add(hair);

    // Glow ring at feet (subtle)
    const ringGeo = new THREE.RingGeometry(0.35, 0.5, 32);
    const ringMat = new THREE.MeshBasicMaterial({ color, transparent: true, opacity: 0.3, side: THREE.DoubleSide });
    const ring = new THREE.Mesh(ringGeo, ringMat);
    ring.rotation.x = -Math.PI / 2;
    ring.position.y = 0.02;
    group.add(ring);

    // Name label
    const label = makeTextSprite(name, 0.5);
    label.position.y = 2.2;
    group.add(label);

    scene.add(group);
    charSprites[charId] = {
        group, ring, targetPos: new THREE.Vector3(0, 0, 0),
        currentPos: new THREE.Vector3(0, 0, 0),
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
        const sprite = ensureCharSprite(cid, info.name, colorIdx);
        colorIdx++;

        const locId = info.location_id;
        if (!locId || !locations[locId]) continue;
        const pos = locations[locId].pos || { x: 0, y: 0, z: 0 };

        // Offset for multiple occupants
        const idx = (occupantIndex[locId] || []).indexOf(cid);
        const off = (idx === 0) ? -0.6 : 0.6;

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

    // Smooth character movement + glow pulse
    for (const s of Object.values(charSprites)) {
        s.group.position.lerp(s.targetPos, Math.min(1, dt * 3));
        if (s.ring) s.ring.material.opacity = 0.2 + 0.15 * Math.sin(t * 3);
    }

    // Pulse location markers
    for (const m of Object.values(locationMarkers)) {
        m.material.opacity = 0.5 + 0.2 * Math.sin(t * 2 + m.position.x);
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

    socket.on('agent_action', (data) => addFeedEntry(data));
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
    await postJSON('/api/character/stats/adjust', { character_id: cid, adjustments: { [stat]: delta } });
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
            ...(data.loaded  || []).map(m => ({ id: m.id, label: m.id + ' (loaded)' })),
            ...(data.available || [])
                .filter(m => !(data.loaded || []).find(l => l.id === m.id))
                .map(m => ({ id: m.id, label: m.id })),
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
        const cfg = config[cid] || {};
        const currentModel = cfg.model || '(default — loaded)';
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
    await postJSON('/api/story/beat', { text });
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
    await postJSON('/api/event/fire', { type: 'custom', description: desc });
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
//  RESIZE + INIT
// ═══════════════════════════════════════════════════════════════════════
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
