/**
 * 3D Bedroom Scene - Three.js Implementation
 * Penthouse bedroom with character interaction
 */

// Scene variables
let scene, camera, renderer, controls;
let character, characterSprite;
let roomMesh, floorMesh, bedMesh;
let ambientLight, directionalLight, pointLights = [];
let skybox;
let particles = [];
let socket;
let clock = new THREE.Clock();
let currentAnimation = 'idle';
let timeOfDay = 'afternoon';

// FPS counter
let lastTime = performance.now();
let frames = 0;

// Configuration
const CONFIG = {
    cameraPosition: { x: 8, y: 5, z: 8 },
    cameraTarget: { x: 0, y: 2, z: 0 },
    characterPosition: { x: 0, y: 0, z: 0 },
    roomSize: { width: 12, height: 4, depth: 10 }
};

/**
 * Initialize the scene
 */
function init() {
    console.log('Initializing 3D Bedroom Scene...');
    
    // Setup renderer
    const canvas = document.getElementById('bedroom-canvas');
    renderer = new THREE.WebGLRenderer({ 
        canvas: canvas, 
        antialias: true,
        alpha: false
    });
    renderer.setSize(window.innerWidth, window.innerHeight);
    renderer.setPixelRatio(window.devicePixelRatio);
    renderer.shadowMap.enabled = true;
    renderer.shadowMap.type = THREE.PCFSoftShadowMap;
    
    // Create scene
    scene = new THREE.Scene();
    scene.background = new THREE.Color(0x87ceeb);
    scene.fog = new THREE.Fog(0x87ceeb, 20, 50);
    
    // Setup camera
    camera = new THREE.PerspectiveCamera(
        60,
        window.innerWidth / window.innerHeight,
        0.1,
        1000
    );
    camera.position.set(CONFIG.cameraPosition.x, CONFIG.cameraPosition.y, CONFIG.cameraPosition.z);
    
    // Setup controls
    controls = new THREE.OrbitControls(camera, renderer.domElement);
    controls.target.set(CONFIG.cameraTarget.x, CONFIG.cameraTarget.y, CONFIG.cameraTarget.z);
    controls.enableDamping = true;
    controls.dampingFactor = 0.05;
    controls.minDistance = 3;
    controls.maxDistance = 20;
    controls.maxPolarAngle = Math.PI / 2;
    controls.update();
    
    // Create lighting
    createLighting();
    
    // Create room
    createRoom();
    
    // Create furniture
    createFurniture();
    
    // Create windows and skybox
    createWindows();
    
    // Create character
    createCharacter();
    
    // Setup interactions
    setupInteractions();
    
    // Connect to server
    connectSocket();
    
    // Start animation loop
    animate();
    
    // Hide loading screen
    hideLoadingScreen();
    
    console.log('Scene initialized successfully!');
}

/**
 * Create lighting system
 */
function createLighting() {
    // Ambient light
    ambientLight = new THREE.AmbientLight(0xffffff, 0.6);
    scene.add(ambientLight);
    
    // Directional light (sun)
    directionalLight = new THREE.DirectionalLight(0xffffff, 0.8);
    directionalLight.position.set(5, 10, 5);
    directionalLight.castShadow = true;
    directionalLight.shadow.mapSize.width = 2048;
    directionalLight.shadow.mapSize.height = 2048;
    directionalLight.shadow.camera.near = 0.5;
    directionalLight.shadow.camera.far = 50;
    directionalLight.shadow.camera.left = -15;
    directionalLight.shadow.camera.right = 15;
    directionalLight.shadow.camera.top = 15;
    directionalLight.shadow.camera.bottom = -15;
    scene.add(directionalLight);
    
    // Point lights (room lighting)
    const pointLight1 = new THREE.PointLight(0xfff5e6, 0.5, 10);
    pointLight1.position.set(3, 3.5, 0);
    scene.add(pointLight1);
    pointLights.push(pointLight1);
    
    const pointLight2 = new THREE.PointLight(0xfff5e6, 0.5, 10);
    pointLight2.position.set(-3, 3.5, 0);
    scene.add(pointLight2);
    pointLights.push(pointLight2);
}

/**
 * Update lighting based on time of day
 */
function updateLighting(lighting) {
    const color = new THREE.Color(lighting.color);
    ambientLight.intensity = lighting.ambient;
    directionalLight.intensity = lighting.directional;
    directionalLight.color = color;
    
    // Update point lights for night time
    const nightIntensity = timeOfDay === 'night' ? 0.8 : 0.3;
    pointLights.forEach(light => {
        light.intensity = nightIntensity;
    });
}

/**
 * Create the bedroom
 */
function createRoom() {
    const { width, height, depth } = CONFIG.roomSize;
    
    // Floor
    const floorGeometry = new THREE.PlaneGeometry(width, depth);
    const floorMaterial = new THREE.MeshStandardMaterial({
        color: 0x8b7355,
        roughness: 0.8,
        metalness: 0.2
    });
    floorMesh = new THREE.Mesh(floorGeometry, floorMaterial);
    floorMesh.rotation.x = -Math.PI / 2;
    floorMesh.receiveShadow = true;
    scene.add(floorMesh);
    
    // Add wood texture effect
    const floorTexture = createWoodTexture();
    floorMaterial.map = floorTexture;
    floorMaterial.needsUpdate = true;
    
    // Walls
    const wallMaterial = new THREE.MeshStandardMaterial({
        color: 0xf5f5dc,
        roughness: 0.9,
        metalness: 0.1
    });
    
    // Back wall
    const backWallGeometry = new THREE.BoxGeometry(width, height, 0.2);
    const backWall = new THREE.Mesh(backWallGeometry, wallMaterial);
    backWall.position.set(0, height / 2, -depth / 2);
    backWall.receiveShadow = true;
    scene.add(backWall);
    
    // Left wall
    const sideWallGeometry = new THREE.BoxGeometry(0.2, height, depth);
    const leftWall = new THREE.Mesh(sideWallGeometry, wallMaterial);
    leftWall.position.set(-width / 2, height / 2, 0);
    leftWall.receiveShadow = true;
    scene.add(leftWall);
    
    // Right wall (partial - windows)
    const rightWall = new THREE.Mesh(sideWallGeometry, wallMaterial);
    rightWall.position.set(width / 2, height / 2, 0);
    rightWall.receiveShadow = true;
    scene.add(rightWall);
    
    // Ceiling
    const ceilingGeometry = new THREE.PlaneGeometry(width, depth);
    const ceilingMaterial = new THREE.MeshStandardMaterial({
        color: 0xffffff,
        roughness: 0.7,
        metalness: 0.1
    });
    const ceiling = new THREE.Mesh(ceilingGeometry, ceilingMaterial);
    ceiling.rotation.x = Math.PI / 2;
    ceiling.position.y = height;
    ceiling.receiveShadow = true;
    scene.add(ceiling);
}

/**
 * Create furniture
 */
function createFurniture() {
    // Bed
    const bedFrame = new THREE.BoxGeometry(3, 0.3, 4);
    const bedMaterial = new THREE.MeshStandardMaterial({
        color: 0x654321,
        roughness: 0.7,
        metalness: 0.3
    });
    bedMesh = new THREE.Mesh(bedFrame, bedMaterial);
    bedMesh.position.set(-3, 0.15, -3);
    bedMesh.castShadow = true;
    scene.add(bedMesh);
    
    // Mattress
    const mattressGeometry = new THREE.BoxGeometry(2.8, 0.4, 3.8);
    const mattressMaterial = new THREE.MeshStandardMaterial({
        color: 0xf0f0f0,
        roughness: 0.8,
        metalness: 0.1
    });
    const mattress = new THREE.Mesh(mattressGeometry, mattressMaterial);
    mattress.position.set(-3, 0.55, -3);
    mattress.castShadow = true;
    scene.add(mattress);
    
    // Pillow
    const pillowGeometry = new THREE.BoxGeometry(0.8, 0.2, 0.6);
    const pillowMaterial = new THREE.MeshStandardMaterial({
        color: 0xffffff,
        roughness: 0.9
    });
    const pillow = new THREE.Mesh(pillowGeometry, pillowMaterial);
    pillow.position.set(-3, 0.85, -4.2);
    pillow.castShadow = true;
    scene.add(pillow);
    
    // Nightstand
    const nightstandGeometry = new THREE.BoxGeometry(0.8, 1, 0.6);
    const nightstandMaterial = new THREE.MeshStandardMaterial({
        color: 0x8b4513,
        roughness: 0.5,
        metalness: 0.2
    });
    const nightstand = new THREE.Mesh(nightstandGeometry, nightstandMaterial);
    nightstand.position.set(-5, 0.5, -3);
    nightstand.castShadow = true;
    scene.add(nightstand);
    
    // Lamp on nightstand
    const lampBaseGeometry = new THREE.CylinderGeometry(0.1, 0.15, 0.5, 8);
    const lampMaterial = new THREE.MeshStandardMaterial({
        color: 0xccaa77,
        roughness: 0.3,
        metalness: 0.7
    });
    const lampBase = new THREE.Mesh(lampBaseGeometry, lampMaterial);
    lampBase.position.set(-5, 1.25, -3);
    scene.add(lampBase);
    
    // Lamp shade
    const lampShadeGeometry = new THREE.ConeGeometry(0.3, 0.4, 8);
    const lampShadeMaterial = new THREE.MeshStandardMaterial({
        color: 0xffffee,
        roughness: 0.8,
        emissive: 0xffffaa,
        emissiveIntensity: 0.2
    });
    const lampShade = new THREE.Mesh(lampShadeGeometry, lampShadeMaterial);
    lampShade.position.set(-5, 1.7, -3);
    scene.add(lampShade);
    
    // Dresser
    const dresserGeometry = new THREE.BoxGeometry(2, 1.5, 0.8);
    const dresserMaterial = new THREE.MeshStandardMaterial({
        color: 0x8b4513,
        roughness: 0.5,
        metalness: 0.2
    });
    const dresser = new THREE.Mesh(dresserGeometry, dresserMaterial);
    dresser.position.set(4, 0.75, -4.5);
    dresser.castShadow = true;
    scene.add(dresser);
    
    // Rug
    const rugGeometry = new THREE.PlaneGeometry(4, 3);
    const rugMaterial = new THREE.MeshStandardMaterial({
        color: 0xaa6644,
        roughness: 1.0,
        metalness: 0.0
    });
    const rug = new THREE.Mesh(rugGeometry, rugMaterial);
    rug.rotation.x = -Math.PI / 2;
    rug.position.set(0, 0.01, 0);
    rug.receiveShadow = true;
    scene.add(rug);
}

/**
 * Create windows with city skyline
 */
function createWindows() {
    const windowGeometry = new THREE.PlaneGeometry(4, 3);
    
    // Create gradient sky texture
    const canvas = document.createElement('canvas');
    canvas.width = 512;
    canvas.height = 512;
    const ctx = canvas.getContext('2d');
    
    // Sky gradient
    const gradient = ctx.createLinearGradient(0, 0, 0, 512);
    gradient.addColorStop(0, '#87ceeb');
    gradient.addColorStop(0.5, '#b0d4f1');
    gradient.addColorStop(1, '#e0f2ff');
    ctx.fillStyle = gradient;
    ctx.fillRect(0, 0, 512, 512);
    
    // Add simple city silhouette
    ctx.fillStyle = '#333333';
    for (let i = 0; i < 20; i++) {
        const x = (i * 30) % 512;
        const height = Math.random() * 200 + 100;
        const width = 25;
        ctx.fillRect(x, 512 - height, width, height);
        
        // Add windows to buildings
        ctx.fillStyle = '#ffee88';
        for (let y = 512 - height + 10; y < 512; y += 20) {
            for (let wx = x + 5; wx < x + width - 5; wx += 8) {
                if (Math.random() > 0.3) {
                    ctx.fillRect(wx, y, 4, 8);
                }
            }
        }
        ctx.fillStyle = '#333333';
    }
    
    const texture = new THREE.CanvasTexture(canvas);
    
    const windowMaterial = new THREE.MeshBasicMaterial({
        map: texture,
        side: THREE.DoubleSide
    });
    
    // Window 1
    const window1 = new THREE.Mesh(windowGeometry, windowMaterial);
    window1.position.set(0, 2, 4.9);
    scene.add(window1);
    
    // Window 2
    const window2 = new THREE.Mesh(windowGeometry, windowMaterial.clone());
    window2.position.set(4, 2, 4.9);
    scene.add(window2);
    
    // Window frame
    const frameMaterial = new THREE.MeshStandardMaterial({
        color: 0x444444,
        roughness: 0.3,
        metalness: 0.7
    });
    
    const frameGeometry = new THREE.BoxGeometry(4.2, 0.1, 0.1);
    const frame1Top = new THREE.Mesh(frameGeometry, frameMaterial);
    frame1Top.position.set(0, 3.5, 4.95);
    scene.add(frame1Top);
    
    const frame1Bottom = new THREE.Mesh(frameGeometry, frameMaterial);
    frame1Bottom.position.set(0, 0.5, 4.95);
    scene.add(frame1Bottom);
}

/**
 * Create character
 */
function createCharacter() {
    // Create a simple character using a sprite
    const canvas = document.createElement('canvas');
    canvas.width = 256;
    canvas.height = 256;
    const ctx = canvas.getContext('2d');
    
    // Draw character sprite
    ctx.fillStyle = '#ffdbac';
    ctx.beginPath();
    ctx.arc(128, 80, 40, 0, Math.PI * 2);
    ctx.fill();
    
    // Body
    ctx.fillStyle = '#4a90e2';
    ctx.fillRect(98, 120, 60, 80);
    
    // Arms
    ctx.fillStyle = '#ffdbac';
    ctx.fillRect(80, 130, 18, 50);
    ctx.fillRect(158, 130, 18, 50);
    
    // Legs
    ctx.fillStyle = '#2c3e50';
    ctx.fillRect(100, 200, 25, 50);
    ctx.fillRect(131, 200, 25, 50);
    
    // Eyes
    ctx.fillStyle = '#000000';
    ctx.beginPath();
    ctx.arc(115, 75, 5, 0, Math.PI * 2);
    ctx.arc(141, 75, 5, 0, Math.PI * 2);
    ctx.fill();
    
    // Smile
    ctx.strokeStyle = '#000000';
    ctx.lineWidth = 2;
    ctx.beginPath();
    ctx.arc(128, 85, 15, 0, Math.PI);
    ctx.stroke();
    
    const texture = new THREE.CanvasTexture(canvas);
    const spriteMaterial = new THREE.SpriteMaterial({ 
        map: texture,
        transparent: true
    });
    
    characterSprite = new THREE.Sprite(spriteMaterial);
    characterSprite.scale.set(2, 2, 1);
    characterSprite.position.set(
        CONFIG.characterPosition.x,
        1.5,
        CONFIG.characterPosition.z
    );
    characterSprite.userData.interactive = true;
    scene.add(characterSprite);
    
    character = characterSprite;
}

/**
 * Create wood texture
 */
function createWoodTexture() {
    const canvas = document.createElement('canvas');
    canvas.width = 512;
    canvas.height = 512;
    const ctx = canvas.getContext('2d');
    
    // Base wood color
    ctx.fillStyle = '#8b7355';
    ctx.fillRect(0, 0, 512, 512);
    
    // Wood grain lines
    ctx.strokeStyle = '#6b5345';
    ctx.lineWidth = 2;
    for (let i = 0; i < 512; i += 40) {
        ctx.beginPath();
        ctx.moveTo(0, i);
        ctx.lineTo(512, i + Math.random() * 10 - 5);
        ctx.stroke();
    }
    
    return new THREE.CanvasTexture(canvas);
}

/**
 * Setup interactions
 */
function setupInteractions() {
    const raycaster = new THREE.Raycaster();
    const mouse = new THREE.Vector2();
    
    renderer.domElement.addEventListener('click', (event) => {
        // Calculate mouse position
        mouse.x = (event.clientX / window.innerWidth) * 2 - 1;
        mouse.y = -(event.clientY / window.innerHeight) * 2 + 1;
        
        // Raycast
        raycaster.setFromCamera(mouse, camera);
        const intersects = raycaster.intersectObjects([character]);
        
        if (intersects.length > 0) {
            showInteractionPanel();
        }
    });
}

/**
 * Create particle effect
 */
function createParticles(type) {
    const particleCount = 20;
    const particleGeometry = new THREE.BufferGeometry();
    const positions = new Float32Array(particleCount * 3);
    
    for (let i = 0; i < particleCount * 3; i++) {
        positions[i] = (Math.random() - 0.5) * 2;
    }
    
    particleGeometry.setAttribute('position', new THREE.BufferAttribute(positions, 3));
    
    let color = 0xff69b4;
    if (type === 'hug') color = 0xffff00;
    if (type === 'wave') color = 0x00ffff;
    if (type === 'kiss') color = 0xff1493;
    
    const particleMaterial = new THREE.PointsMaterial({
        color: color,
        size: 0.2,
        transparent: true,
        opacity: 1
    });
    
    const particleSystem = new THREE.Points(particleGeometry, particleMaterial);
    particleSystem.position.copy(character.position);
    particleSystem.userData.velocity = [];
    particleSystem.userData.lifetime = 2;
    particleSystem.userData.age = 0;
    
    for (let i = 0; i < particleCount; i++) {
        particleSystem.userData.velocity.push({
            x: (Math.random() - 0.5) * 2,
            y: Math.random() * 3,
            z: (Math.random() - 0.5) * 2
        });
    }
    
    scene.add(particleSystem);
    particles.push(particleSystem);
}

/**
 * Update particles
 */
function updateParticles(delta) {
    for (let i = particles.length - 1; i >= 0; i--) {
        const particle = particles[i];
        particle.userData.age += delta;
        
        if (particle.userData.age >= particle.userData.lifetime) {
            scene.remove(particle);
            particles.splice(i, 1);
            continue;
        }
        
        // Update positions
        const positions = particle.geometry.attributes.position.array;
        const velocities = particle.userData.velocity;
        
        for (let j = 0; j < positions.length / 3; j++) {
            positions[j * 3] += velocities[j].x * delta;
            positions[j * 3 + 1] += velocities[j].y * delta;
            positions[j * 3 + 2] += velocities[j].z * delta;
            
            velocities[j].y -= 2 * delta;
        }
        
        particle.geometry.attributes.position.needsUpdate = true;
        
        // Fade out
        const fadeProgress = particle.userData.age / particle.userData.lifetime;
        particle.material.opacity = 1 - fadeProgress;
    }
}

/**
 * Animate character
 */
function animateCharacter() {
    const time = clock.getElapsedTime();
    
    switch (currentAnimation) {
        case 'idle':
            character.position.y = 1.5 + Math.sin(time * 2) * 0.05;
            break;
        case 'waving':
            character.position.y = 1.5 + Math.sin(time * 4) * 0.1;
            character.rotation.z = Math.sin(time * 8) * 0.2;
            break;
        case 'talking':
            character.scale.y = 2 + Math.sin(time * 10) * 0.05;
            break;
        case 'hugging':
            character.scale.x = 2 + Math.sin(time * 3) * 0.1;
            break;
        case 'kissing':
            character.rotation.y = Math.sin(time * 2) * 0.1;
            break;
    }
}

/**
 * Animation loop
 */
function animate() {
    requestAnimationFrame(animate);
    
    const delta = clock.getDelta();
    
    // Update controls
    controls.update();
    
    // Animate character
    animateCharacter();
    
    // Update particles
    updateParticles(delta);
    
    // Render scene
    renderer.render(scene, camera);
    
    // Update FPS
    updateFPS();
}

/**
 * Update FPS counter
 */
function updateFPS() {
    frames++;
    const time = performance.now();
    
    if (time >= lastTime + 1000) {
        const fps = Math.round((frames * 1000) / (time - lastTime));
        document.getElementById('fps-counter').textContent = `FPS: ${fps}`;
        frames = 0;
        lastTime = time;
    }
}

/**
 * Connect to Socket.IO server
 */
function connectSocket() {
    socket = io('http://localhost:5003');
    
    socket.on('connect', () => {
        console.log('Connected to server');
        updateStatus('Connected', true);
        socket.emit('request_state');
    });
    
    socket.on('disconnect', () => {
        console.log('Disconnected from server');
        updateStatus('Disconnected', false);
    });
    
    socket.on('scene_state', (state) => {
        console.log('Received scene state:', state);
        if (state.time_of_day) {
            timeOfDay = state.time_of_day;
            updateTimeButtons(timeOfDay);
        }
        if (state.lighting) {
            updateLighting(state.lighting);
        }
    });
    
    socket.on('time_changed', (data) => {
        timeOfDay = data.time;
        updateLighting(data.lighting);
        updateTimeButtons(timeOfDay);
        showToast(`Time changed to ${timeOfDay}`);
    });
    
    socket.on('character_animation', (data) => {
        currentAnimation = data.animation;
        if (data.type !== 'reset') {
            createParticles(data.type);
            showToast(`Character is ${data.animation}!`);
        }
    });
    
    socket.on('character_moved', (data) => {
        character.position.set(data.position.x, 1.5, data.position.z);
    });
    
    socket.on('chat_message', (data) => {
        addChatMessage(data.message, data.timestamp);
    });
}

/**
 * Update status indicator
 */
function updateStatus(text, connected) {
    document.getElementById('status-text').textContent = text;
    const dot = document.querySelector('.status-dot');
    dot.style.backgroundColor = connected ? '#4caf50' : '#f44336';
}

/**
 * UI Event Handlers
 */

// Back button
document.getElementById('back-btn').addEventListener('click', () => {
    window.location.href = 'http://localhost:5001';
});

// Time selector
document.querySelectorAll('.time-btn').forEach(btn => {
    btn.addEventListener('click', async () => {
        const time = btn.dataset.time;
        
        try {
            const response = await fetch('/api/scene/time', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ time: time })
            });
            
            if (response.ok) {
                updateTimeButtons(time);
            }
        } catch (error) {
            console.error('Error setting time:', error);
            showToast('Failed to change time', 'error');
        }
    });
});

function updateTimeButtons(activeTime) {
    document.querySelectorAll('.time-btn').forEach(btn => {
        btn.classList.toggle('active', btn.dataset.time === activeTime);
    });
}

// Interaction buttons
document.querySelectorAll('.interaction-btn').forEach(btn => {
    btn.addEventListener('click', async () => {
        const action = btn.dataset.action;
        
        if (action === 'talk') {
            showChatPanel();
            hideInteractionPanel();
            return;
        }
        
        try {
            const response = await fetch('/api/character/interact', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ type: action })
            });
            
            if (response.ok) {
                hideInteractionPanel();
            }
        } catch (error) {
            console.error('Error interacting:', error);
            showToast('Failed to interact', 'error');
        }
    });
});

// Close interaction panel
document.getElementById('close-interaction').addEventListener('click', hideInteractionPanel);

// Chat functionality
document.getElementById('send-chat').addEventListener('click', sendChatMessage);
document.getElementById('chat-input').addEventListener('keypress', (e) => {
    if (e.key === 'Enter') sendChatMessage();
});
document.getElementById('close-chat').addEventListener('click', hideChatPanel);

function sendChatMessage() {
    const input = document.getElementById('chat-input');
    const message = input.value.trim();
    
    if (message && socket) {
        socket.emit('chat_message', { message: message });
        input.value = '';
    }
}

function addChatMessage(message, timestamp) {
    const messagesDiv = document.getElementById('chat-messages');
    const messageDiv = document.createElement('div');
    messageDiv.className = 'chat-message';
    messageDiv.innerHTML = `
        <div class="message-content">${escapeHtml(message)}</div>
        <div class="message-time">${new Date(timestamp).toLocaleTimeString()}</div>
    `;
    messagesDiv.appendChild(messageDiv);
    messagesDiv.scrollTop = messagesDiv.scrollHeight;
}

function escapeHtml(text) {
    const div = document.createElement('div');
    div.textContent = text;
    return div.innerHTML;
}

// Panel visibility
function showInteractionPanel() {
    document.getElementById('interaction-panel').classList.add('visible');
}

function hideInteractionPanel() {
    document.getElementById('interaction-panel').classList.remove('visible');
}

function showChatPanel() {
    document.getElementById('chat-panel').classList.add('visible');
}

function hideChatPanel() {
    document.getElementById('chat-panel').classList.remove('visible');
}

// ============= CHARACTER SELECTION =============

let allCharacters = [];

// Load characters on init
async function loadCharacters() {
    try {
        const response = await fetch('/api/characters/list');
        if (response.ok) {
            const data = await response.json();
            allCharacters = data.characters || [];
            renderCharacterList(allCharacters);
        }
    } catch (error) {
        console.error('Error loading characters:', error);
    }
}

// Render character list
function renderCharacterList(characters) {
    const listDiv = document.getElementById('character-list');
    listDiv.innerHTML = '';
    
    if (characters.length === 0) {
        listDiv.innerHTML = '<div class="no-characters">No characters available</div>';
        return;
    }
    
    characters.forEach(char => {
        const charDiv = document.createElement('div');
        charDiv.className = 'character-item';
        charDiv.innerHTML = `
            <div class="character-name">${char.name}</div>
            <div class="character-desc">${char.description || 'No description'}</div>
            <div class="character-source">${char.source}</div>
        `;
        charDiv.addEventListener('click', () => selectCharacter(char));
        listDiv.appendChild(charDiv);
    });
}

// Character selector button
document.getElementById('character-selector-btn').addEventListener('click', (e) => {
    e.stopPropagation();
    const dropdown = document.getElementById('character-dropdown');
    dropdown.classList.toggle('hidden');
});

// Character search
document.getElementById('character-search').addEventListener('input', (e) => {
    const query = e.target.value.toLowerCase();
    const filtered = allCharacters.filter(char => 
        char.name.toLowerCase().includes(query) || 
        (char.description && char.description.toLowerCase().includes(query))
    );
    renderCharacterList(filtered);
});

// Click outside to close
document.addEventListener('click', (e) => {
    const dropdown = document.getElementById('character-dropdown');
    const btn = document.getElementById('character-selector-btn');
    if (!dropdown.contains(e.target) && !btn.contains(e.target)) {
        dropdown.classList.add('hidden');
    }
});

// Select character
async function selectCharacter(char) {
    try {
        const endpoint = char.source === 'asset' ? '/api/character/load_asset' : '/api/character/set';
        const response = await fetch(endpoint, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ character_id: char.id })
        });
        
        if (response.ok) {
            document.getElementById('selected-character-name').textContent = char.name;
            document.getElementById('character-dropdown').classList.add('hidden');
            showToast(`Character ${char.name} loaded`, 'success');
        } else {
            const error = await response.json();
            showToast(error.error || 'Failed to load character', 'error');
        }
    } catch (error) {
        console.error('Error selecting character:', error);
        showToast('Failed to load character', 'error');
    }
}

// ============= SCENE MANAGEMENT =============

// Save scene
document.getElementById('save-scene-btn').addEventListener('click', async () => {
    const name = prompt('Enter scene name:');
    if (!name) return;
    
    try {
        const response = await fetch('/api/scene/save', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ name: name })
        });
        
        if (response.ok) {
            const data = await response.json();
            showToast(`Scene saved: ${data.scene_id}`, 'success');
        } else {
            const error = await response.json();
            showToast(error.error || 'Failed to save scene', 'error');
        }
    } catch (error) {
        console.error('Error saving scene:', error);
        showToast('Failed to save scene', 'error');
    }
});

// Load scene
document.getElementById('load-scene-btn').addEventListener('click', async () => {
    try {
        // Get list of scenes
        const listResponse = await fetch('/api/scene/list');
        if (!listResponse.ok) {
            showToast('Failed to load scene list', 'error');
            return;
        }
        
        const listData = await listResponse.json();
        const scenes = listData.scenes || [];
        
        if (scenes.length === 0) {
            showToast('No saved scenes available', 'info');
            return;
        }
        
        // Create selection prompt
        const sceneList = scenes.map((s, i) => `${i + 1}. ${s.name || s.id}`).join('\n');
        const selection = prompt(`Select scene to load:\n${sceneList}\n\nEnter number:`);
        
        if (!selection) return;
        
        const index = parseInt(selection) - 1;
        if (index < 0 || index >= scenes.length) {
            showToast('Invalid selection', 'error');
            return;
        }
        
        const sceneId = scenes[index].id;
        
        // Load scene
        const response = await fetch('/api/scene/load', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ scene_id: sceneId })
        });
        
        if (response.ok) {
            showToast('Scene loaded successfully', 'success');
            // Refresh the page to apply all scene settings
            setTimeout(() => window.location.reload(), 1000);
        } else {
            const error = await response.json();
            showToast(error.error || 'Failed to load scene', 'error');
        }
    } catch (error) {
        console.error('Error loading scene:', error);
        showToast('Failed to load scene', 'error');
    }
});

// Toast notifications
function showToast(message, type = 'info') {
    const container = document.getElementById('toast-container');
    const toast = document.createElement('div');
    toast.className = `toast toast-${type}`;
    toast.textContent = message;
    container.appendChild(toast);
    
    setTimeout(() => toast.classList.add('show'), 10);
    setTimeout(() => {
        toast.classList.remove('show');
        setTimeout(() => container.removeChild(toast), 300);
    }, 3000);
}

// Loading screen
function hideLoadingScreen() {
    const loadingScreen = document.getElementById('loading-screen');
    setTimeout(() => {
        loadingScreen.style.opacity = '0';
        setTimeout(() => {
            loadingScreen.style.display = 'none';
        }, 500);
    }, 500);
    
    // Load characters after scene is initialized
    loadCharacters();
}

// Window resize
window.addEventListener('resize', () => {
    camera.aspect = window.innerWidth / window.innerHeight;
    camera.updateProjectionMatrix();
    renderer.setSize(window.innerWidth, window.innerHeight);
});

// Initialize scene when page loads
window.addEventListener('load', init);
