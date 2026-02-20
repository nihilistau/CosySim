/**
 * Bedroom Scene — Multi-Agent 3D Playground
 * Two characters move between 7 locations, converse, flirt, and exhibit
 * emergent behaviour.  The user can observe or direct via whispers.
 */

// ─── Three.js globals ──────────────────────────────────────────────────
let scene, camera, renderer, controls;
let ambientLight, directionalLight, pointLights = [];
let clock = new THREE.Clock();
let timeOfDay = 'evening';

// Location 3D markers  { id → THREE.Mesh }
const locationMarkers = {};
// Character sprites { charId → { mesh, targetPos, currentLoc } }
const charSprites = {};
// Color palette for characters
const CHAR_COLORS = ['#ff6b9d', '#51cf66'];

// ─── App state ─────────────────────────────────────────────────────────
let sceneState = {};
let agentRunning = false;
let currentMode = 'observe';
let socket = null;
let allCharacters = [];  // from /api/characters/list

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
    fetchState();

    animate();
    console.log('Bedroom scene initialized!');
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
        document.querySelectorAll('.time-btn').forEach(b => b.classList.toggle('active', b.dataset.time === data.time));
    });

    // Agent events
    socket.on('agent_action', (data) => addFeedEntry(data));
    socket.on('agent_tick', (data) => {
        if (data.actions) data.actions.forEach(a => addFeedEntry(a));
    });
    socket.on('chat_message', (data) => {
        addFeedEntry({ character_name: data.name, action: 'speak', message: data.message, timestamp: data.timestamp });
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
    currentMode = st.mode || 'observe';

    // Locations
    if (st.locations) buildLocationMarkers(st.locations);

    // Characters
    if (st.characters) {
        updateCharPositions(st.characters, st.locations || {});
        renderCharList(st.characters);
    }

    // Lighting
    if (st.lighting) applyLighting(st.lighting);
    timeOfDay = st.time_of_day || 'evening';

    // UI sync
    document.querySelectorAll('.time-btn').forEach(b => b.classList.toggle('active', b.dataset.time === timeOfDay));
    document.querySelectorAll('.mode-btn').forEach(b => b.classList.toggle('active', b.dataset.mode === currentMode));
    updateAgentBtn();
    updateWhisperBox();
    renderModelConfig();
    document.getElementById('charCount').textContent = '(' + Object.keys(st.characters || {}).length + '/2)';
}

// ═══════════════════════════════════════════════════════════════════════
//  SIDE-PANEL: Characters
// ═══════════════════════════════════════════════════════════════════════
function renderCharList(chars) {
    const el = document.getElementById('charList');
    el.innerHTML = '';
    let idx = 0;
    for (const [cid, info] of Object.entries(chars)) {
        const color = CHAR_COLORS[idx % CHAR_COLORS.length];
        const arousalPct = Math.round((info.arousal || 0) * 100);
        const card = document.createElement('div');
        card.className = 'char-card';
        card.innerHTML =
            '<div class="char-dot" style="background:' + color + '"></div>' +
            '<div class="char-info">' +
                '<strong>' + esc(info.name) + '</strong>' +
                '<span class="char-mood">' + esc(info.mood || 'neutral') + '</span>' +
                '<span class="char-loc">📍 ' + esc(info.location || '—') + '</span>' +
                '<div class="mini-bar"><div class="mini-fill" style="width:' + arousalPct + '%;background:' + color + '"></div></div>' +
            '</div>' +
            '<button class="btn-x" onclick="removeChar(\'' + cid + '\')">✕</button>';
        el.appendChild(card);
        idx++;
    }
}

async function removeChar(cid) {
    await fetch('/api/character/remove', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ character_id: cid }) });
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
    const r = await fetch('/api/character/load', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ character_id: cid }) });
    if (r.ok) closeCharPicker();
    else {
        const e = await r.json();
        alert(e.error || 'Failed');
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
        const r = await fetch('/api/agents/start', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ interval: 30 }) });
        if (r.ok) agentRunning = true;
        else {
            const e = await r.json();
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
    const btn = document.getElementById('btnStartAgents');
    const status = document.getElementById('agentStatus');
    if (agentRunning) {
        btn.textContent = '⏹ Stop';
        status.textContent = '● Agents Running';
        status.className = 'agent-status on';
    } else {
        btn.textContent = '▶ Start';
        status.textContent = '● Agents Off';
        status.className = 'agent-status off';
    }
}

// ═══════════════════════════════════════════════════════════════════════
//  TIME & MODE
// ═══════════════════════════════════════════════════════════════════════
async function setTime(t) {
    await fetch('/api/scene/time', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ time: t }) });
}

async function setMode(m) {
    await fetch('/api/mode', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ mode: m }) });
    currentMode = m;
    document.querySelectorAll('.mode-btn').forEach(b => b.classList.toggle('active', b.dataset.mode === m));
    updateWhisperBox();
}

function updateWhisperBox() {
    const box = document.getElementById('whisperBox');
    if (!box) return;
    box.style.display = (currentMode === 'direct') ? 'flex' : 'none';
    // Update target dropdown
    const sel = document.getElementById('whisperTarget');
    if (sel) {
        sel.innerHTML = '';
        for (const [cid, info] of Object.entries(sceneState.characters || {})) {
            const opt = document.createElement('option');
            opt.value = cid;
            opt.textContent = info.name;
            sel.appendChild(opt);
        }
    }
}

// ═══════════════════════════════════════════════════════════════════════
//  AGENT MODEL CONFIG
// ═══════════════════════════════════════════════════════════════════════
let availableModels = [];

async function refreshModels() {
    try {
        const r = await fetch('/api/models/available');
        const data = await r.json();
        availableModels = [
            ...(data.loaded || []).map(m => ({ id: m.id, label: m.id + ' (loaded)' })),
            ...(data.available || []).filter(m => !(data.loaded || []).find(l => l.id === m.id))
                .map(m => ({ id: m.id, label: m.id })),
        ];
    } catch { availableModels = []; }
    renderModelConfig();
}

async function renderModelConfig() {
    const container = document.getElementById('modelConfigList');
    if (!container) return;

    // Get current config
    let config = {};
    try {
        const r = await fetch('/api/agents/model');
        config = await r.json();
    } catch {}

    const chars = sceneState.characters || {};
    if (Object.keys(chars).length === 0) {
        container.innerHTML = '<p style="color:#888;font-size:12px">Load characters first</p>';
        return;
    }

    let html = '';
    for (const [cid, info] of Object.entries(chars)) {
        const cfg = config[cid] || {};
        const currentModel = cfg.model || '(default — loaded)';
        const currentMode = cfg.mode || 'default';

        html += `<div class="model-config-card">
            <div class="mcc-name">${info.name}</div>
            <select class="mcc-select" id="modelSel_${cid}" onchange="setAgentModel('${cid}')">
                <option value="">Default (loaded model)</option>
                ${availableModels.map(m =>
                    `<option value="${m.id}" ${m.id === cfg.model ? 'selected' : ''}>${m.label}</option>`
                ).join('')}
            </select>
            <div class="mcc-modes">
                <label><input type="radio" name="mode_${cid}" value="default" ${currentMode === 'default' ? 'checked' : ''} onchange="setAgentModel('${cid}')"> Standard</label>
                <label><input type="radio" name="mode_${cid}" value="speculative" ${currentMode === 'speculative' ? 'checked' : ''} onchange="setAgentModel('${cid}')"> Speculative</label>
                <label><input type="radio" name="mode_${cid}" value="concurrent" ${currentMode === 'concurrent' ? 'checked' : ''} onchange="setAgentModel('${cid}')"> Concurrent</label>
            </div>
        </div>`;
    }
    container.innerHTML = html;
}

async function setAgentModel(cid) {
    const modelSel = document.getElementById(`modelSel_${cid}`);
    const modeRadio = document.querySelector(`input[name="mode_${cid}"]:checked`);
    const model = modelSel ? modelSel.value : '';
    const mode = modeRadio ? modeRadio.value : 'default';

    await fetch('/api/agents/model', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ character_id: cid, model: model || null, mode }),
    });
}

async function sendWhisper() {
    const input = document.getElementById('whisperInput');
    const target = document.getElementById('whisperTarget').value;
    const msg = input.value.trim();
    if (!msg || !target) return;
    await fetch('/api/agents/whisper', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ character_id: target, message: msg }) });
    addFeedEntry({ character_name: '(Director)', action: 'whisper', message: msg, timestamp: new Date().toISOString() });
    input.value = '';
}

// ═══════════════════════════════════════════════════════════════════════
//  ACTIVITY FEED
// ═══════════════════════════════════════════════════════════════════════
const ACTION_ICONS = {
    speak: '💬', move: '🚶', idle: '😌', flirt: '😏', touch: '✋',
    kiss: '💋', cuddle: '🤗', intimate: '🔥', interact: '🎯', whisper: '🤫',
    menace: '😈',
};

function addFeedEntry(data) {
    const feed = document.getElementById('feedMessages');
    if (!feed) return;

    const action = data.action || 'speak';
    const icon = ACTION_ICONS[action] || '▪';
    const name = data.character_name || data.name || '?';
    const msg = data.message || data.detail || action;
    const loc = data.location ? (' @ ' + data.location) : '';

    const div = document.createElement('div');
    div.className = 'feed-entry feed-' + action;
    div.innerHTML = '<span class="feed-icon">' + icon + '</span>' +
        '<span class="feed-name">' + esc(name) + '</span>' +
        '<span class="feed-msg">' + esc(msg) + loc + '</span>';
    feed.appendChild(div);
    feed.scrollTop = feed.scrollHeight;

    // Cap at 200 entries
    while (feed.children.length > 200) feed.removeChild(feed.firstChild);

    // Also refresh location list
    if (sceneState.locations) renderLocations(sceneState.locations);
}

function clearFeed() {
    document.getElementById('feedMessages').innerHTML = '';
}

// ═══════════════════════════════════════════════════════════════════════
//  HELPERS
// ═══════════════════════════════════════════════════════════════════════
function esc(str) {
    const d = document.createElement('div');
    d.textContent = str || '';
    return d.innerHTML;
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

// ═══════════════════════════════════════════════════════════════════════
//  MENACE MENU — GOD MODE ENVIRONMENTAL PRANKS
// ═══════════════════════════════════════════════════════════════════════
const MENACE_EFFECTS = {
    flicker_lights() {
        const orig = renderer.toneMappingExposure;
        let flicks = 0;
        const iv = setInterval(() => {
            renderer.toneMappingExposure = flicks % 2 === 0 ? 0.05 : orig * 1.5;
            flicks++;
            if (flicks > 8) { clearInterval(iv); renderer.toneMappingExposure = orig; }
        }, 100);
    },
    cold_draft() {
        // Shift lighting to cold blue temporarily
        scene.fog = new THREE.FogExp2(0x1a2040, 0.08);
        setTimeout(() => { scene.fog = null; }, 4000);
    },
    move_object() {
        // Shake a random furniture piece
        const furniture = scene.children.filter(c => c.userData?.furniture);
        if (furniture.length === 0) return;
        const obj = furniture[Math.floor(Math.random() * furniture.length)];
        const origPos = obj.position.clone();
        let shakes = 0;
        const iv = setInterval(() => {
            obj.position.x = origPos.x + (Math.random() - 0.5) * 0.15;
            obj.position.z = origPos.z + (Math.random() - 0.5) * 0.15;
            shakes++;
            if (shakes > 12) { clearInterval(iv); obj.position.copy(origPos); }
        }, 60);
    },
    power_out() {
        const origBg = scene.background;
        scene.background = new THREE.Color(0x000000);
        scene.children.filter(c => c.isLight).forEach(l => { l.userData._origInt = l.intensity; l.intensity = 0; });
        setTimeout(() => {
            scene.background = origBg;
            scene.children.filter(c => c.isLight).forEach(l => { l.intensity = l.userData._origInt || 1; });
        }, 2500);
    },
    romantic_mood() {
        scene.children.filter(c => c.isLight && c.isPointLight).forEach(l => {
            l.color.set(0xff6644);
            l.intensity *= 0.6;
        });
        setTimeout(() => applyLighting({}), 8000);
    },
    thunder() {
        const flash = new THREE.PointLight(0xffffff, 5, 50);
        flash.position.set(0, 10, 0);
        scene.add(flash);
        setTimeout(() => { flash.intensity = 0; }, 100);
        setTimeout(() => { flash.intensity = 3; }, 200);
        setTimeout(() => { scene.remove(flash); }, 400);
    },
};

async function menace(type) {
    // Visual effect in the browser
    if (MENACE_EFFECTS[type]) MENACE_EFFECTS[type]();

    // Also notify backend so agents perceive the event
    try {
        await fetch('/api/menace', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ type }),
        });
    } catch (e) { /* ok */ }

    addFeedEntry({
        character_name: '(God)',
        action: 'menace',
        message: '😈 ' + type.replace(/_/g, ' '),
        timestamp: new Date().toISOString(),
    });
}

// Load ambient tracks on init
loadAmbientTracks();
