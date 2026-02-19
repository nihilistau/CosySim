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
    ambientLight = new THREE.AmbientLight(0xffffff, 0.25);
    scene.add(ambientLight);

    directionalLight = new THREE.DirectionalLight(0xffeedd, 0.6);
    directionalLight.position.set(5, 10, 5);
    directionalLight.castShadow = true;
    scene.add(directionalLight);

    // Warm room point lights
    [{ x: -3, z: -3 }, { x: 3, z: 0 }, { x: 0, z: -5 }].forEach(p => {
        const pl = new THREE.PointLight(0xffddaa, 0.4, 10);
        pl.position.set(p.x, 3, p.z);
        scene.add(pl);
        pointLights.push(pl);
    });
}

function applyLighting(preset) {
    if (!preset) return;
    const c = new THREE.Color(preset.color);
    ambientLight.intensity = preset.ambient * 0.6;
    directionalLight.intensity = preset.directional;
    directionalLight.color = c;
    const nightMul = (timeOfDay === 'night') ? 0.7 : 0.4;
    pointLights.forEach(l => l.intensity = nightMul);
}

// ═══════════════════════════════════════════════════════════════════════
//  ROOM GEOMETRY
// ═══════════════════════════════════════════════════════════════════════
function createRoom() {
    const { w, h, d } = CONFIG.roomSize;

    // Floor
    const floorGeo = new THREE.PlaneGeometry(w, d);
    const floorMat = new THREE.MeshStandardMaterial({ color: 0x3d2b1f, roughness: 0.85 });
    const floor = new THREE.Mesh(floorGeo, floorMat);
    floor.rotation.x = -Math.PI / 2;
    floor.receiveShadow = true;
    scene.add(floor);

    // Walls (3 sides — front open for camera)
    const wallMat = new THREE.MeshStandardMaterial({ color: 0x2a2a3d, roughness: 0.9 });
    const addWall = (geo, x, y, z) => {
        const m = new THREE.Mesh(geo, wallMat);
        m.position.set(x, y, z);
        m.receiveShadow = true;
        scene.add(m);
    };
    addWall(new THREE.BoxGeometry(w, h, 0.15), 0, h / 2, -d / 2); // back
    addWall(new THREE.BoxGeometry(0.15, h, d), -w / 2, h / 2, 0); // left
    addWall(new THREE.BoxGeometry(0.15, h, d), w / 2, h / 2, 0);  // right
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

    // Body (capsule approximation)
    const bodyGeo = new THREE.CylinderGeometry(0.3, 0.35, 1.4, 16);
    const bodyMat = new THREE.MeshStandardMaterial({ color, roughness: 0.5 });
    const body = new THREE.Mesh(bodyGeo, bodyMat);
    body.position.y = 0.7;
    body.castShadow = true;

    // Head
    const headGeo = new THREE.SphereGeometry(0.25, 16, 16);
    const headMat = new THREE.MeshStandardMaterial({ color: 0xffd5b4, roughness: 0.6 });
    const head = new THREE.Mesh(headGeo, headMat);
    head.position.y = 1.6;
    head.castShadow = true;

    const group = new THREE.Group();
    group.add(body);
    group.add(head);

    // Name label
    const label = makeTextSprite(name, 0.5);
    label.position.y = 2.1;
    group.add(label);

    scene.add(group);
    charSprites[charId] = { group, targetPos: new THREE.Vector3(0, 0, 0), currentPos: new THREE.Vector3(0, 0, 0) };
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

    // Smooth character movement
    for (const s of Object.values(charSprites)) {
        s.group.position.lerp(s.targetPos, Math.min(1, dt * 3));
    }

    // Pulse location markers
    const t = clock.elapsedTime;
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
    sel.innerHTML = '';
    for (const [cid, info] of Object.entries(sceneState.characters || {})) {
        const opt = document.createElement('option');
        opt.value = cid;
        opt.textContent = info.name;
        sel.appendChild(opt);
    }
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
