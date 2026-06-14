/**
 * Character Bridge — Wires CharModels avatars into the Penthouse 3D scene
 * =====================================================================
 * This module bridges the gap between:
 *   - penthouse_3d.js  (room environment, scene object, animation loop)
 *   - character_models.js  (CharModels API — create, animate, outfit, expression, pose)
 *   - penthouse.js  (Socket.IO events, scene_state, director UI)
 *
 * It listens for scene state updates and spawns/updates/removes 3D character
 * models in the penthouse scene at the correct location zones.
 *
 * Dependencies (load order):
 *   1. Three.js (CDN)
 *   2. penthouse_3d.js  (exposes window.penthouse3D)
 *   3. character_models.js  (exposes window.CharModels)
 *   4. THIS FILE
 *   5. penthouse.js (calls CharacterBridge.syncCharacters)
 */

'use strict';

window.CharacterBridge = (function () {

  // ── Configuration ──
  const BRIDGE_CONFIG = {
    colors: ['#ff6b9d', '#51cf66', '#ffd43b', '#74c0fc', '#ff922b', '#da77f2'],
    labelHeight: 2.0,
    bubbleHeight: 2.5,
    maxBubbleTextLength: 60,
    occupantOffset2P: 0.6,
    occupantOffsetNP: 0.7,
    bubbleDurationMs: 6000,
    labelCanvas: { width: 256, height: 64 },
    bubbleCanvas: { width: 512, height: 128 },
    labelFontSize: 32,
    bubbleFontSize: 16,
  };

  // ─── State ───────────────────────────────────────────────────────
  const characters = {};   // charId → { model, targetPos, currentOutfit, bubble }
  const CHAR_COLORS = BRIDGE_CONFIG.colors;
  let _scene = null;
  let _locationPositions = {};
  let _animRegistered = false;
  let _directorSprite = null;
  // v1.62.0 [2026-06-15] — director avatar render/persist fix:
  //   holds a director descriptor that arrived before the 3D scene was ready.
  let _pendingDirector = null;

  /**
   * Feet-origin Y for a location entry. Delegates to penthouse3D.resolveAnchorY
   * so the posed body rests ON the surface; falls back to the raw surface Y if
   * the helper is unavailable (older penthouse_3d.js).
   * v1.62.0 [2026-06-15] — anchor-aware placement (fix furniture sink).
   */
  function _anchorY(locPos) {
    const p3d = window.penthouse3D;
    if (p3d && typeof p3d.resolveAnchorY === 'function') return p3d.resolveAnchorY(locPos);
    return (locPos && locPos.y) || 0;
  }

  // ─── Initialise ──────────────────────────────────────────────────
  // v1.49.2 [2026-03-22] — Use onReady() callback instead of blind setTimeout polling
  let _initAttempts = 0;
  const _MAX_INIT_ATTEMPTS = 10;

  // v1.53.0 [2026-03-26] — Enhanced diagnostic logging for character model debugging
  function init() {
    console.info('[CharBridge] init() — CharModels=%s, penthouse3D=%s, penthouse3D.init=%s',
      typeof CharModels !== 'undefined' ? 'loaded' : 'MISSING',
      window.penthouse3D ? 'exists' : 'MISSING',
      window.penthouse3D && window.penthouse3D.isInitialized() ? 'true' : 'false');

    // Wait for CharModels (loaded via separate script)
    if (typeof CharModels === 'undefined') {
      _initAttempts++;
      if (_initAttempts > _MAX_INIT_ATTEMPTS) {
        console.error('[CharBridge] CharModels not available after %d attempts — disabling 3D characters', _MAX_INIT_ATTEMPTS);
        return;
      }
      console.debug('[CharBridge] CharModels not loaded — retrying in 500ms (attempt %d)', _initAttempts);
      setTimeout(init, 500);
      return;
    }

    // Use onReady if penthouse3D exists but isn't initialized yet
    if (window.penthouse3D && !window.penthouse3D.isInitialized()) {
      console.info('[CharBridge] penthouse3D exists but not initialized — registering onReady callback');
      window.penthouse3D.onReady(_onPenthouseReady);
      return;
    }
    if (!window.penthouse3D) {
      console.warn('[CharBridge] penthouse3D not found — listening for penthouse3d:ready event');
      // Listen for the ready event as fallback
      document.addEventListener('penthouse3d:ready', () => _onPenthouseReady(window.penthouse3D), { once: true });
      document.addEventListener('penthouse3d:error', () => {
        console.error('[CharBridge] Penthouse 3D init failed — disabling 3D characters');
      }, { once: true });
      return;
    }
    _onPenthouseReady(window.penthouse3D);
  }

  function _onPenthouseReady(p3d) {
    _scene = p3d.getScene();
    _locationPositions = p3d.getLocationPositions();

    if (!_scene) {
      console.error('[CharBridge] Could not get Three.js scene from penthouse3D');
      return;
    }

    // Register our animation tick into the penthouse render loop
    if (!_animRegistered) {
      window.penthouse3D.addToAnimationLoop(animationTick);
      _animRegistered = true;
    }

    console.info('[CharBridge] Initialised — scene acquired, %d locations mapped',
      Object.keys(_locationPositions).length);

    // v1.51.1 [2026-03-25] — Replay any queued character syncs that arrived before init
    if (_pendingSync) {
      console.info('[CharBridge] Replaying queued character sync (%d chars)',
        Object.keys(_pendingSync.chars || {}).length);
      syncCharacters(_pendingSync.chars, _pendingSync.locs);
      _pendingSync = null;
    }

    // v1.62.0 [2026-06-15] — director avatar render/persist fix:
    //   replay a director descriptor that arrived before the scene was ready.
    if (_pendingDirector) {
      console.info('[CharBridge] Replaying queued director avatar placement');
      const pd = _pendingDirector;
      _pendingDirector = null;
      placeDirectorAvatar(pd);
    }
  }

  // v1.51.1 [2026-03-25] — Queue for characters that arrive before 3D scene is ready
  let _pendingSync = null;

  // ─── Sync characters from scene_state ────────────────────────────

  /**
   * Called by penthouse.js whenever scene_state arrives via Socket.IO.
   * @param {Object} stateChars  - data.characters from scene_state
   * @param {Object} stateLocations - data.locations from scene_state (optional)
   */
  // v1.53.0 [2026-03-26] — Added diagnostic logging
  function syncCharacters(stateChars, stateLocations) {
    const charCount = Object.keys(stateChars || {}).length;

    if (!_scene) {
      // v1.51.1 — Queue sync instead of dropping it; init will replay when ready
      console.info('[CharBridge] syncCharacters called but _scene is null — queuing %d chars', charCount);
      _pendingSync = { chars: stateChars, locs: stateLocations };
      init();
      return;
    }

    console.info('[CharBridge] syncCharacters — processing %d chars, _scene=%s',
      charCount, _scene ? 'set' : 'null');

    const chars = stateChars || {};
    const locs = stateLocations || {};

    // Build occupant index for position offsets
    const occupantIndex = {};
    for (const [cid, info] of Object.entries(chars)) {
      const locId = info.location_id || 'bed';
      if (!occupantIndex[locId]) occupantIndex[locId] = [];
      occupantIndex[locId].push(cid);
    }

    let colorIdx = 0;
    for (const [cid, info] of Object.entries(chars)) {
      const sprite = ensureCharacter(cid, info.name || cid, colorIdx, info);
      colorIdx++;

      // v1.53.0 — Skip if model creation failed
      if (!sprite) continue;

      // Update outfit if changed
      const outfit = info.outfit || 'casual';
      if (sprite.currentOutfit !== outfit) {
        CharModels.updateOutfit(sprite.model, outfit);
        sprite.currentOutfit = outfit;
      }

      // Update expression from mood/feeling (via AnimManager if available)
      const mood = info.feeling || info.mood || 'neutral';
      if (sprite.currentMood !== mood) {
        if (window.PenthouseAnim) {
          PenthouseAnim.AnimManager.setMood(info.name || cid, mood);
        } else {
          CharModels.setExpression(sprite.model, mood);
        }
        sprite.currentMood = mood;
      }

      // Infer animation state from location
      const locId = info.location_id || 'bed';
      if (window.PenthouseAnim) {
        const inferredState = PenthouseAnim.inferAnimState(locId, info.activity);
        PenthouseAnim.AnimManager.setState(info.name || cid, inferredState);
      }

      // Calculate target position from location
      const locPos = _locationPositions[locId] || locs[locId]?.pos || { x: 0, y: 0, z: 0 };

      // Offset for multiple occupants at same location
      const occ = occupantIndex[locId] || [];
      const idx = occ.indexOf(cid);
      const count = occ.length;
      let offsetX = 0;
      if (count === 2) offsetX = (idx === 0) ? -BRIDGE_CONFIG.occupantOffset2P : BRIDGE_CONFIG.occupantOffset2P;
      else if (count >= 3) offsetX = (idx - 1) * BRIDGE_CONFIG.occupantOffsetNP;

      // v1.62.0 [2026-06-15] — anchor-aware placement (fix furniture sink):
      //   target the feet-origin Y for this location's anchor, and refresh the
      //   pose system's base Y so its per-pose offset lands the body on-surface.
      const baseY = _anchorY(locPos);
      sprite.targetPos.set(locPos.x + offsetX, baseY, locPos.z);
      if (sprite.model) sprite.model._baseY = baseY;
    }

    // Remove characters no longer in state
    // v1.62.0 [2026-06-15] — director avatar render/persist fix:
    //   the Director is tracked in this same `characters` map under 'director'
    //   but is NEVER part of scene_state.characters (it lives in
    //   scene_state.director_avatar). Skip it here, otherwise every scene_state
    //   reaps the director right after it is placed.
    for (const cid of Object.keys(characters)) {
      if (cid === 'director') continue;
      if (!chars[cid]) removeCharacter(cid);
    }
  }

  // ─── Character CRUD ──────────────────────────────────────────────

  // v1.53.0 [2026-03-26] — try/catch for model creation, fix duplicate labels, diagnostic logging
  function ensureCharacter(charId, name, colorIdx, info) {
    if (characters[charId]) return characters[charId];

    const color = CHAR_COLORS[colorIdx % CHAR_COLORS.length];
    const gender = info?.gender || undefined;

    let model;
    try {
      model = CharModels.create({
        name: name,
        charColor: color,
        gender: gender,
      });
    } catch (err) {
      console.error('[CharBridge] CharModels.create() FAILED for %s: %s', name, err.message, err);
      return null;
    }

    if (!model || !model.group) {
      console.error('[CharBridge] CharModels.create() returned invalid model for %s:', name, model);
      return null;
    }

    console.info('[CharBridge] Model created for %s — group.children=%d, gender=%s',
      name, model.group.children.length, gender || 'auto');

    // Remove built-in name label from CharModels to avoid duplicates
    // (CharModels adds a Sprite label; we create our own styled one below)
    const builtinLabels = [];
    model.group.children.forEach(child => {
      if (child.isSprite && child.position.y > 1.5) builtinLabels.push(child);
    });
    builtinLabels.forEach(lbl => model.group.remove(lbl));

    // Apply initial outfit
    const outfit = info?.outfit || 'casual';
    CharModels.updateOutfit(model, outfit);

    // Register with animation state machine
    if (window.PenthouseAnim) {
      const animState = PenthouseAnim.AnimManager.register(name, model);
      const locId = info?.location_id || 'bed';
      animState.setState(PenthouseAnim.inferAnimState(locId));
      if (info?.feeling || info?.mood) {
        animState.setMood(info.feeling || info.mood);
      }
    }

    // Add to scene
    _scene.add(model.group);

    // Position at initial location
    // v1.62.0 [2026-06-15] — anchor-aware placement (fix furniture sink):
    //   place the GROUP at the feet-origin Y for the anchor, and (re)seed
    //   model._baseY — AnimManager.register() captured it BEFORE this position
    //   was applied, so without this the pose offset would sink the body.
    const locId = info?.location_id || 'bed';
    const locPos = _locationPositions[locId] || { x: 0, y: 0, z: 0 };
    const baseY = _anchorY(locPos);
    model.group.position.set(locPos.x, baseY, locPos.z);
    model._baseY = baseY;

    // Create name label sprite
    const label = createNameLabel(name, color);
    if (label) model.group.add(label);

    const entry = {
      model: model,
      targetPos: new THREE.Vector3(locPos.x, baseY, locPos.z),
      currentOutfit: outfit,
      currentMood: 'neutral',
      label: label,
      bubble: null,
      bubbleTimer: 0,
    };

    characters[charId] = entry;
    console.info('[CharBridge] Spawned character: %s at %s', name, locId);
    return entry;
  }

  function removeCharacter(charId) {
    const entry = characters[charId];
    if (!entry) return;

    // Unregister from animation state machine
    if (window.PenthouseAnim) {
      PenthouseAnim.AnimManager.unregister(charId);
    }

    _scene.remove(entry.model.group);
    delete characters[charId];
    console.info('[CharBridge] Removed character: %s', charId);
  }

  // ─── Name Labels ─────────────────────────────────────────────────

  function createNameLabel(name, color) {
    const canvas = document.createElement('canvas');
    const ctx = canvas.getContext('2d');
    canvas.width = BRIDGE_CONFIG.labelCanvas.width;
    canvas.height = BRIDGE_CONFIG.labelCanvas.height;

    // Background pill
    ctx.fillStyle = 'rgba(0, 0, 0, 0.6)';
    const radius = 12;
    const w = canvas.width, h = canvas.height;
    ctx.beginPath();
    ctx.moveTo(radius, 0);
    ctx.lineTo(w - radius, 0);
    ctx.quadraticCurveTo(w, 0, w, radius);
    ctx.lineTo(w, h - radius);
    ctx.quadraticCurveTo(w, h, w - radius, h);
    ctx.lineTo(radius, h);
    ctx.quadraticCurveTo(0, h, 0, h - radius);
    ctx.lineTo(0, radius);
    ctx.quadraticCurveTo(0, 0, radius, 0);
    ctx.closePath();
    ctx.fill();

    // Border accent
    ctx.strokeStyle = color || '#ff6b9d';
    ctx.lineWidth = 2;
    ctx.stroke();

    // Text
    ctx.fillStyle = '#ffffff';
    ctx.font = 'bold 28px sans-serif';
    ctx.textAlign = 'center';
    ctx.textBaseline = 'middle';
    ctx.fillText(name, w / 2, h / 2);

    const texture = new THREE.CanvasTexture(canvas);
    const mat = new THREE.SpriteMaterial({
      map: texture,
      transparent: true,
      depthTest: false,
    });
    const sprite = new THREE.Sprite(mat);
    sprite.scale.set(1.0, 0.25, 1);
    sprite.position.set(0, BRIDGE_CONFIG.labelHeight, 0);  // above head
    return sprite;
  }

  // ─── Chat Bubbles ────────────────────────────────────────────────

  function showChatBubble(charId, text, duration) {
    const entry = characters[charId];
    if (!entry) return;

    // Remove existing bubble
    if (entry.bubble) {
      entry.model.group.remove(entry.bubble);
      entry.bubble = null;
    }

    const canvas = document.createElement('canvas');
    const ctx = canvas.getContext('2d');
    canvas.width = BRIDGE_CONFIG.bubbleCanvas.width;
    canvas.height = BRIDGE_CONFIG.bubbleCanvas.height;

    // Bubble background
    ctx.fillStyle = 'rgba(20, 20, 40, 0.85)';
    const r = 16, w = canvas.width, h = canvas.height;
    ctx.beginPath();
    ctx.moveTo(r, 0);
    ctx.lineTo(w - r, 0);
    ctx.quadraticCurveTo(w, 0, w, r);
    ctx.lineTo(w, h - r);
    ctx.quadraticCurveTo(w, h, w - r, h);
    ctx.lineTo(r, h);
    ctx.quadraticCurveTo(0, h, 0, h - r);
    ctx.lineTo(0, r);
    ctx.quadraticCurveTo(0, 0, r, 0);
    ctx.closePath();
    ctx.fill();

    // Border
    ctx.strokeStyle = '#667eea';
    ctx.lineWidth = 2;
    ctx.stroke();

    // Truncate text
    const maxLen = BRIDGE_CONFIG.maxBubbleTextLength;
    const display = text.length > maxLen ? text.substring(0, maxLen) + '…' : text;

    ctx.fillStyle = '#e0e0e0';
    ctx.font = '22px sans-serif';
    ctx.textAlign = 'center';
    ctx.textBaseline = 'middle';

    // Word wrap into 2 lines
    const words = display.split(' ');
    let line1 = '', line2 = '';
    for (const word of words) {
      const test = line1 + (line1 ? ' ' : '') + word;
      if (ctx.measureText(test).width < w - 40) {
        line1 = test;
      } else {
        line2 += (line2 ? ' ' : '') + word;
      }
    }

    if (line2) {
      ctx.fillText(line1, w / 2, h / 2 - 14);
      ctx.fillText(line2, w / 2, h / 2 + 14);
    } else {
      ctx.fillText(line1, w / 2, h / 2);
    }

    const texture = new THREE.CanvasTexture(canvas);
    const mat = new THREE.SpriteMaterial({
      map: texture,
      transparent: true,
      depthTest: false,
    });
    const sprite = new THREE.Sprite(mat);
    sprite.scale.set(2.0, 0.5, 1);
    sprite.position.set(0, BRIDGE_CONFIG.bubbleHeight, 0);  // above name label
    entry.model.group.add(sprite);
    entry.bubble = sprite;
    entry.bubbleTimer = duration || (BRIDGE_CONFIG.bubbleDurationMs / 1000);
  }

  // ─── Director Avatar ─────────────────────────────────────────────

  /**
   * Place (or replace) the Director's 3D avatar in the scene.
   * @param {Object} opts - avatar descriptor. Accepts BOTH the manual-click
   *   shape (`location`/`skin`/`hair`) and the scene_state shape emitted by the
   *   backend (`location_id`/`skin_tone`/`hair_color`), so persistence on
   *   reload/reconnect renders identically to the manual placement.
   * v1.62.0 [2026-06-15] — director avatar render/persist fix.
   */
  function placeDirectorAvatar(opts) {
    opts = opts || {};

    // v1.62.0 [2026-06-15] — director avatar render/persist fix:
    //   scene_state can arrive before the 3D scene is ready (e.g. on reload).
    //   Mirror the syncCharacters() queue so the director is not silently
    //   dropped (and so _scene.add() below never throws on null).
    if (!_scene) {
      console.info('[CharBridge] placeDirectorAvatar called but _scene is null — queuing');
      _pendingDirector = opts;
      init();
      return;
    }

    removeDirectorAvatar();

    // Accept both the manual-click and scene_state key shapes.
    const gender = opts.gender || 'male';
    const skin = opts.skin || opts.skin_tone || 'fair';
    const hair = opts.hair || opts.hair_color || 'brown';
    const outfit = opts.outfit || 'casual';
    const locationId = opts.location || opts.location_id || 'couch';

    const model = CharModels.create({
      name: 'Director',
      charColor: '#ffd700',
      gender: gender,
    });

    CharModels.updateOutfit(model, outfit);
    _scene.add(model.group);

    // v1.62.0 [2026-06-15] — anchor-aware placement (fix furniture sink)
    const locPos = _locationPositions[locationId] || { x: 0, y: 0, z: 0 };
    const baseY = _anchorY(locPos);
    model.group.position.set(locPos.x + 1.2, baseY, locPos.z);
    model._baseY = baseY;

    const label = createNameLabel('Director', '#ffd700');
    if (label) model.group.add(label);

    // Register with AnimManager for full animation support
    if (window.PenthouseAnim && PenthouseAnim.AnimManager) {
      PenthouseAnim.AnimManager.register('Director', model);
      model._baseY = baseY;  // re-seed: register() captures _baseY at call time
      const inferredState = PenthouseAnim.inferAnimState(locationId, 'idle');
      if (inferredState) {
        PenthouseAnim.AnimManager.setState('Director', inferredState);
      }
    }

    // Track in characters map so director participates like agents
    characters['director'] = {
      model: model,
      targetPos: new THREE.Vector3(locPos.x + 1.2, baseY, locPos.z),
      locationId: locationId,
      currentMood: 'neutral',
      label: label,
      bubble: null,
      bubbleTimer: 0,
      isDirector: true,
    };

    _directorSprite = characters['director'];

    console.info('[CharBridge] Director avatar placed at %s (registered with AnimManager)', locationId);
  }

  function removeDirectorAvatar() {
    if (_directorSprite) {
      _scene.remove(_directorSprite.model.group);
      // Unregister from AnimManager
      if (window.PenthouseAnim && PenthouseAnim.AnimManager) {
        PenthouseAnim.AnimManager.unregister('Director');
      }
      delete characters['director'];
      _directorSprite = null;
      console.info('[CharBridge] Director avatar removed');
    }
  }

  // ─── Animation Tick ──────────────────────────────────────────────
  // Called every frame by penthouse3D animation loop

  function animationTick(dt, t) {
    // Update animation state machine for all characters
    const useAnimManager = window.PenthouseAnim && PenthouseAnim.AnimManager;

    if (useAnimManager) {
      PenthouseAnim.AnimManager.updateAll(t);
    }

    // Per-character updates
    for (const entry of Object.values(characters)) {
      // Smooth position lerp
      if (!CharModels.isPoseActive()) {
        entry.model.group.position.lerp(entry.targetPos, Math.min(1, dt * 3));
      }

      // Fallback idle animation (if AnimManager not available)
      if (!useAnimManager && entry.model.bodyGroup && !CharModels.isPoseActive()) {
        CharModels.animate(entry.model, t);
      }

      // Name label bob
      if (entry.label) {
        entry.label.position.y = BRIDGE_CONFIG.labelHeight + Math.sin(t * 1.5) * 0.03;
      }

      // Chat bubble timer
      if (entry.bubble && entry.bubbleTimer > 0) {
        entry.bubbleTimer -= dt;
        if (entry.bubbleTimer <= 0) {
          entry.model.group.remove(entry.bubble);
          entry.bubble = null;
        } else if (entry.bubbleTimer < 1.0) {
          entry.bubble.material.opacity = entry.bubbleTimer;
        }
      }
    }

    // Director avatar: position lerp handled in main loop above since director
    // is now in the characters map. Only need fallback if not in map for some reason.
    if (_directorSprite && !characters['director'] && _directorSprite.model.bodyGroup) {
      _directorSprite.model.group.position.lerp(
        _directorSprite.targetPos, Math.min(1, dt * 3)
      );
      if (!useAnimManager) {
        CharModels.animate(_directorSprite.model, t);
      }
    }

    // Sex pose animation (overrides individual when active)
    CharModels.animatePose(dt, t);
  }

  // ─── Pose Control (exposed for director UI) ──────────────────────

  function startPose(poseName, participantCharIds) {
    const participants = participantCharIds
      .map(cid => characters[cid])
      .filter(Boolean)
      .map(entry => ({
        model: entry.model,
        mood: entry.currentMood || 'neutral',
      }));

    if (participants.length === 0) {
      console.warn('[CharBridge] No valid participants for pose: %s', poseName);
      return;
    }

    // Set expressions for pose
    for (const p of participants) {
      const expressionMood = p.mood === 'neutral' ? 'aroused' : p.mood;
      if (window.PenthouseAnim) {
        PenthouseAnim.AnimManager.setMood(p.model.name || '', expressionMood);
      } else {
        CharModels.setExpression(p.model, expressionMood);
      }
    }

    CharModels.startPose(poseName, participants);
    console.info('[CharBridge] Started pose: %s with %d participants', poseName, participants.length);
  }

  function stopPose() {
    CharModels.stopPose(false);
  }

  // ─── Public API ──────────────────────────────────────────────────

  return {
    init,
    syncCharacters,
    showChatBubble,
    placeDirectorAvatar,
    removeDirectorAvatar,
    startPose,
    stopPose,
    getCharacter: (id) => characters[id] || null,
    getCharacterIds: () => Object.keys(characters),
    getCharacterCount: () => Object.keys(characters).length,
    // Animation state machine access
    setAnimState: (name, state) => {
      if (window.PenthouseAnim) PenthouseAnim.AnimManager.setState(name, state);
    },
    setMood: (name, mood) => {
      if (window.PenthouseAnim) PenthouseAnim.AnimManager.setMood(name, mood);
    },
    setExpression: (name, expression) => {
      if (window.PenthouseAnim) PenthouseAnim.AnimManager.setMood(name, expression);
    },
    setOutfit: (charId, outfit) => {
      const char = characters[charId];
      if (char && char.model && window.CharModels) {
        CharModels.updateOutfit(char.model, outfit);
      }
    },
    setLookTarget:(name, target) => {
      if (window.PenthouseAnim) PenthouseAnim.AnimManager.setLookTarget(name, target);
    },
    getAnimDebug: () => {
      if (window.PenthouseAnim) return PenthouseAnim.AnimManager.getDebugInfo();
      return {};
    },
    // Director-specific controls
    moveDirectorTo: (locationId) => {
      const dir = characters['director'];
      if (!dir) return;
      // v1.62.0 [2026-06-15] — anchor-aware placement (fix furniture sink)
      const locPos = _locationPositions[locationId] || { x: 0, y: 0, z: 0 };
      const baseY = _anchorY(locPos);
      dir.targetPos.set(locPos.x + 1.2, baseY, locPos.z);
      if (dir.model) dir.model._baseY = baseY;
      dir.locationId = locationId;
      if (window.PenthouseAnim) {
        const state = PenthouseAnim.inferAnimState(locationId, 'idle');
        if (state) PenthouseAnim.AnimManager.setState('Director', state);
      }
    },
    setDirectorState: (state) => {
      if (window.PenthouseAnim) PenthouseAnim.AnimManager.setState('Director', state);
    },
    setDirectorOutfit: (outfit) => {
      const dir = characters['director'];
      if (dir && dir.model && window.CharModels) {
        CharModels.updateOutfit(dir.model, outfit);
      }
    },
    isDirectorPlaced: () => !!characters['director'],
  };

})();

// Auto-initialise when DOM is ready
if (document.readyState === 'loading') {
  document.addEventListener('DOMContentLoaded', () => CharacterBridge.init());
} else {
  CharacterBridge.init();
}
