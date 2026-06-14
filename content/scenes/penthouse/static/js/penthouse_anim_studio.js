/**
 * PenthouseAnimStudio — Animation Studio UI for the Penthouse scene.
 *
 * Provides five tabs: Poses, Expressions, Sequences, Library, Models.
 * Communicates with PenthouseAnim, CharacterBridge, and CharModels APIs.
 * Persists poses/sequences to the backend via /api/anim/* routes.
 *
 * @module PenthouseAnimStudio
 */
(function () {
  'use strict';

  // ── State ──────────────────────────────────────────────────────────
  let _panel = null;
  let _isOpen = false;
  let _selectedCharId = null;

  // Pose library (local cache synced with server)
  let _poseLibrary = {};
  let _sequenceLibrary = {};
  let _customExpressions = {};

  // Sequence playback state
  let _seqPlaying = false;
  let _seqPaused = false;
  let _seqLoop = false;
  let _seqSpeed = 1.0;
  let _seqKeyframes = [];
  let _seqStartTime = 0;
  let _seqRafId = null;
  let _seqCurrentIdx = 0;

  // Model browser state
  let _modelCatalog = {};
  let _modelFilter = 'all';
  let _modelSearch = '';

  // Joint editing defaults (radians stored internally)
  const BONE_NAMES = [
    'head', 'torso',
    'arm_l', 'arm_r', 'forearm_l', 'forearm_r', 'hand_l', 'hand_r',
    'thigh_l', 'thigh_r', 'shin_l', 'shin_r'
  ];

  const BONE_LABELS = {
    head: 'Head', torso: 'Torso',
    arm_l: 'L Arm', arm_r: 'R Arm',
    forearm_l: 'L Forearm', forearm_r: 'R Forearm',
    hand_l: 'L Hand', hand_r: 'R Hand',
    thigh_l: 'L Thigh', thigh_r: 'R Thigh',
    shin_l: 'L Shin', shin_r: 'R Shin'
  };

  const EXPRESSION_PRESETS = [
    'neutral', 'happy', 'aroused', 'seductive', 'orgasm', 'sad', 'angry',
    'fear', 'surprised', 'shy', 'drunk', 'sleepy', 'dominant', 'flirty',
    'pleased', 'disgusted'
  ];

  const EXPRESSION_PROPS = ['browY', 'browRot', 'mouthSX', 'mouthSY', 'pupilS', 'headTilt', 'blush'];

  const DEG2RAD = Math.PI / 180;
  const RAD2DEG = 180 / Math.PI;

  // ── CSS ────────────────────────────────────────────────────────────
  const STUDIO_CSS = `
    #ph-anim-studio {
      position: fixed;
      top: 80px;
      left: 20px;
      width: 380px;
      max-height: 85vh;
      background: rgba(10, 10, 30, 0.95);
      border: 1px solid rgba(102, 126, 234, 0.4);
      border-radius: 12px;
      box-shadow: 0 8px 32px rgba(0,0,0,0.6), 0 0 20px rgba(102,126,234,0.15);
      z-index: 10001;
      font-family: 'Segoe UI', system-ui, sans-serif;
      color: #e0e0e0;
      overflow: hidden;
      display: none;
      backdrop-filter: blur(12px);
    }
    .as-header {
      display: flex;
      justify-content: space-between;
      align-items: center;
      padding: 10px 14px;
      background: rgba(102,126,234,0.15);
      border-bottom: 1px solid rgba(102,126,234,0.3);
      cursor: grab;
    }
    .as-title {
      font-size: 14px;
      font-weight: 600;
      letter-spacing: 0.5px;
    }
    .as-close {
      background: none;
      border: none;
      color: #888;
      font-size: 16px;
      cursor: pointer;
      padding: 2px 6px;
      border-radius: 4px;
    }
    .as-close:hover { color: #ff6b9d; background: rgba(255,107,157,0.1); }
    .as-body {
      padding: 10px 12px;
      overflow-y: auto;
      max-height: calc(85vh - 90px);
    }
    .as-char-select {
      margin-bottom: 8px;
    }
    .as-char-select label {
      font-size: 11px;
      color: #888;
      text-transform: uppercase;
      letter-spacing: 1px;
      display: block;
      margin-bottom: 3px;
    }
    .as-char-select select {
      width: 100%;
      padding: 5px 8px;
      background: rgba(30,30,60,0.8);
      border: 1px solid rgba(102,126,234,0.3);
      border-radius: 6px;
      color: #e0e0e0;
      font-size: 13px;
    }
    .as-tabs {
      display: flex;
      gap: 2px;
      margin-bottom: 8px;
      background: rgba(20,20,40,0.5);
      border-radius: 8px;
      padding: 2px;
    }
    .as-tab {
      flex: 1;
      padding: 5px 4px;
      background: none;
      border: none;
      color: #888;
      font-size: 11px;
      cursor: pointer;
      border-radius: 6px;
      transition: all 0.2s;
      white-space: nowrap;
    }
    .as-tab.active {
      background: rgba(102,126,234,0.25);
      color: #e0e0e0;
    }
    .as-tab:hover { color: #ccc; }

    /* ── Bone slider group ─────────────────────────────────────────── */
    .as-bone-group {
      margin-bottom: 6px;
      border: 1px solid rgba(102,126,234,0.12);
      border-radius: 6px;
      overflow: hidden;
    }
    .as-bone-header {
      display: flex;
      justify-content: space-between;
      align-items: center;
      padding: 4px 8px;
      background: rgba(30,30,60,0.4);
      cursor: pointer;
      font-size: 12px;
      font-weight: 500;
      user-select: none;
    }
    .as-bone-header:hover { background: rgba(102,126,234,0.15); }
    .as-bone-sliders {
      display: none;
      padding: 4px 8px 6px;
    }
    .as-bone-sliders.open { display: block; }
    .as-slider-row {
      display: flex;
      align-items: center;
      gap: 6px;
      margin-bottom: 2px;
    }
    .as-slider-row label {
      font-size: 11px;
      color: #aaa;
      width: 14px;
      text-align: right;
      flex-shrink: 0;
    }
    .as-slider-row input[type="range"] {
      flex: 1;
      height: 4px;
      -webkit-appearance: none;
      appearance: none;
      background: rgba(102,126,234,0.2);
      border-radius: 2px;
      outline: none;
    }
    .as-slider-row input[type="range"]::-webkit-slider-thumb {
      -webkit-appearance: none;
      width: 12px; height: 12px;
      border-radius: 50%;
      background: #667eea;
      cursor: pointer;
    }
    .as-slider-val {
      font-size: 10px;
      color: #888;
      width: 32px;
      text-align: right;
      flex-shrink: 0;
    }

    /* ── Buttons ───────────────────────────────────────────────────── */
    .as-btn {
      padding: 6px 10px;
      background: rgba(102,126,234,0.15);
      border: 1px solid rgba(102,126,234,0.3);
      border-radius: 6px;
      color: #ccc;
      font-size: 11px;
      cursor: pointer;
      transition: all 0.2s;
    }
    .as-btn:hover {
      background: rgba(102,126,234,0.3);
      border-color: #667eea;
      color: #fff;
    }
    .as-btn--accent {
      background: rgba(244,63,94,0.15);
      border-color: rgba(244,63,94,0.3);
    }
    .as-btn--accent:hover {
      background: rgba(244,63,94,0.3);
      border-color: #f43f5e;
    }
    .as-btn--sm { padding: 3px 6px; font-size: 10px; }
    .as-btn-row {
      display: flex;
      gap: 4px;
      margin-top: 6px;
      flex-wrap: wrap;
    }

    /* ── Expression presets grid ────────────────────────────────────── */
    .as-expr-grid {
      display: grid;
      grid-template-columns: repeat(4, 1fr);
      gap: 4px;
      margin-bottom: 8px;
    }
    .as-expr-btn {
      padding: 5px 2px;
      background: rgba(30,30,60,0.4);
      border: 1px solid rgba(102,126,234,0.15);
      border-radius: 6px;
      color: #ccc;
      font-size: 10px;
      cursor: pointer;
      text-align: center;
      transition: all 0.2s;
    }
    .as-expr-btn:hover {
      background: rgba(102,126,234,0.2);
      border-color: rgba(102,126,234,0.4);
    }
    .as-expr-btn.active {
      background: rgba(244,63,94,0.2);
      border-color: #f43f5e;
      color: #fff;
    }

    /* ── Sequence timeline ─────────────────────────────────────────── */
    .as-kf-list {
      max-height: 180px;
      overflow-y: auto;
      margin-bottom: 6px;
    }
    .as-kf-item {
      display: flex;
      align-items: center;
      gap: 6px;
      padding: 4px 6px;
      border: 1px solid rgba(102,126,234,0.1);
      border-radius: 4px;
      margin-bottom: 3px;
      font-size: 11px;
      background: rgba(20,20,40,0.3);
    }
    .as-kf-item:hover { background: rgba(102,126,234,0.1); }
    .as-kf-idx { color: #667eea; font-weight: 600; width: 20px; }
    .as-kf-name {
      flex: 1;
      background: none;
      border: none;
      border-bottom: 1px solid rgba(102,126,234,0.2);
      color: #e0e0e0;
      font-size: 11px;
      padding: 1px 2px;
    }
    .as-kf-time {
      width: 42px;
      background: rgba(30,30,60,0.5);
      border: 1px solid rgba(102,126,234,0.2);
      border-radius: 3px;
      color: #e0e0e0;
      font-size: 10px;
      text-align: center;
      padding: 1px 2px;
    }
    .as-kf-del {
      background: none;
      border: none;
      color: #666;
      cursor: pointer;
      font-size: 12px;
      padding: 0 2px;
    }
    .as-kf-del:hover { color: #f43f5e; }

    /* ── Playback controls ─────────────────────────────────────────── */
    .as-playback {
      display: flex;
      align-items: center;
      gap: 4px;
      margin-bottom: 6px;
    }
    .as-playback .as-btn { font-size: 14px; padding: 4px 8px; }
    .as-speed-lbl { font-size: 10px; color: #888; margin-left: auto; }
    .as-speed-val { font-size: 11px; color: #e0e0e0; width: 32px; text-align: center; }

    /* ── Library grid ──────────────────────────────────────────────── */
    .as-lib-grid {
      display: grid;
      grid-template-columns: repeat(2, 1fr);
      gap: 6px;
      max-height: 300px;
      overflow-y: auto;
    }
    .as-lib-card {
      padding: 8px;
      background: rgba(30,30,60,0.4);
      border: 1px solid rgba(102,126,234,0.15);
      border-radius: 8px;
      cursor: pointer;
      transition: all 0.2s;
    }
    .as-lib-card:hover {
      background: rgba(102,126,234,0.15);
      border-color: rgba(102,126,234,0.4);
    }
    .as-lib-name { font-size: 12px; font-weight: 500; margin-bottom: 2px; }
    .as-lib-meta { font-size: 10px; color: #888; }
    .as-lib-actions {
      display: flex;
      gap: 3px;
      margin-top: 4px;
    }

    /* ── Section dividers ──────────────────────────────────────────── */
    .as-section-title {
      font-size: 11px;
      color: #667eea;
      text-transform: uppercase;
      letter-spacing: 1px;
      margin: 8px 0 4px;
      padding-bottom: 2px;
      border-bottom: 1px solid rgba(102,126,234,0.15);
    }
    .as-section-title:first-child { margin-top: 0; }

    /* ── Library category sections ────────────────────────────────── */
    .as-lib-section { margin-bottom: 8px; }
    .as-lib-section-title {
      font-size: 11px;
      color: #b794f4;
      text-transform: uppercase;
      letter-spacing: 0.8px;
      margin: 6px 0 4px;
      padding: 3px 6px;
      background: rgba(102,126,234,0.08);
      border-radius: 4px;
    }
    .as-lib-section:first-child .as-lib-section-title { margin-top: 0; }
    .as-lib-builtin {
      border-left: 2px solid #b794f4;
    }
    .as-badge {
      display: inline-block;
      font-size: 9px;
      padding: 1px 4px;
      background: rgba(183,148,244,0.2);
      border: 1px solid rgba(183,148,244,0.4);
      border-radius: 3px;
      color: #b794f4;
      vertical-align: middle;
      margin-left: 4px;
    }

    /* ── Loop toggle ───────────────────────────────────────────────── */
    .as-toggle {
      display: inline-flex;
      align-items: center;
      gap: 4px;
      font-size: 11px;
      color: #888;
      cursor: pointer;
      user-select: none;
    }
    .as-toggle input { display: none; }
    .as-toggle-track {
      width: 28px; height: 14px;
      background: rgba(60,60,80,0.6);
      border-radius: 7px;
      position: relative;
      transition: background 0.2s;
    }
    .as-toggle input:checked + .as-toggle-track { background: rgba(102,126,234,0.5); }
    .as-toggle-thumb {
      position: absolute;
      top: 2px; left: 2px;
      width: 10px; height: 10px;
      background: #aaa;
      border-radius: 50%;
      transition: all 0.2s;
    }
    .as-toggle input:checked + .as-toggle-track .as-toggle-thumb {
      left: 16px;
      background: #667eea;
    }

    /* ── Empty state ───────────────────────────────────────────────── */
    .as-empty {
      text-align: center;
      color: #666;
      font-size: 12px;
      padding: 20px 10px;
    }

    /* ── Import/Export file input ───────────────────────────────────── */
    .as-file-input { display: none; }

    /* ── Model Browser Tab ─────────────────────────────────────────── */
    .as-model-search {
      width: 100%;
      padding: 6px 10px;
      background: rgba(30, 30, 60, 0.8);
      border: 1px solid rgba(102, 126, 234, 0.3);
      border-radius: 6px;
      color: #e0e0e0;
      font-size: 12px;
      margin-bottom: 8px;
      box-sizing: border-box;
    }
    .as-model-search::placeholder { color: #555; }
    .as-model-search:focus {
      outline: none;
      border-color: rgba(102, 126, 234, 0.6);
    }
    .as-model-filters {
      display: flex;
      gap: 3px;
      margin-bottom: 8px;
      flex-wrap: wrap;
    }
    .as-model-filter-btn {
      padding: 3px 8px;
      background: rgba(30, 30, 60, 0.6);
      border: 1px solid rgba(102, 126, 234, 0.2);
      border-radius: 4px;
      color: #888;
      font-size: 10px;
      cursor: pointer;
      transition: all 0.2s;
    }
    .as-model-filter-btn:hover { color: #ccc; }
    .as-model-filter-btn.active {
      background: rgba(102, 126, 234, 0.3);
      border-color: rgba(102, 126, 234, 0.5);
      color: #e0e0e0;
    }
    .as-model-stats {
      font-size: 10px;
      color: #666;
      margin-bottom: 6px;
      text-align: right;
    }
    .as-model-grid {
      display: grid;
      grid-template-columns: repeat(2, 1fr);
      gap: 6px;
      max-height: 280px;
      overflow-y: auto;
      margin-bottom: 8px;
    }
    .as-model-card {
      padding: 8px;
      background: rgba(30, 30, 60, 0.6);
      border: 1px solid rgba(102, 126, 234, 0.15);
      border-radius: 8px;
      cursor: pointer;
      transition: all 0.2s;
    }
    .as-model-card:hover {
      background: rgba(102, 126, 234, 0.2);
      border-color: rgba(102, 126, 234, 0.4);
      transform: translateY(-1px);
    }
    .as-model-card.selected {
      border-color: rgba(102, 126, 234, 0.7);
      background: rgba(102, 126, 234, 0.15);
    }
    .as-model-card-icon {
      width: 100%;
      height: 52px;
      background: rgba(0, 0, 0, 0.4);
      border-radius: 4px;
      display: flex;
      align-items: center;
      justify-content: center;
      font-size: 22px;
      margin-bottom: 4px;
    }
    .as-model-card-name {
      font-size: 10px;
      font-weight: 600;
      color: #d0d0d0;
      white-space: nowrap;
      overflow: hidden;
      text-overflow: ellipsis;
      margin-bottom: 2px;
    }
    .as-model-card-meta {
      font-size: 9px;
      color: #777;
    }
    .as-model-detail {
      background: rgba(15, 15, 35, 0.9);
      border: 1px solid rgba(102, 126, 234, 0.25);
      border-radius: 8px;
      padding: 10px;
      margin-top: 4px;
    }
    .as-model-detail-hdr {
      display: flex;
      justify-content: space-between;
      align-items: center;
      margin-bottom: 8px;
      padding-bottom: 6px;
      border-bottom: 1px solid rgba(102, 126, 234, 0.15);
    }
    .as-model-detail-hdr h4 { margin: 0; font-size: 13px; color: #e0e0e0; }
    .as-model-detail-close {
      background: none; border: none; color: #888; cursor: pointer; font-size: 14px;
    }
    .as-model-detail-close:hover { color: #ccc; }
    .as-model-detail-icon {
      width: 100%;
      height: 70px;
      background: rgba(0, 0, 0, 0.5);
      border-radius: 6px;
      display: flex;
      align-items: center;
      justify-content: center;
      font-size: 28px;
      margin-bottom: 8px;
    }
    .as-model-detail-row {
      display: flex;
      justify-content: space-between;
      font-size: 11px;
      padding: 3px 0;
      border-bottom: 1px solid rgba(255,255,255,0.03);
    }
    .as-model-detail-row .label { color: #888; }
    .as-model-detail-row .value { color: #ccc; font-weight: 500; }
    .as-model-detail-tags {
      display: flex;
      flex-wrap: wrap;
      gap: 3px;
      margin-top: 6px;
    }
    .as-model-tag {
      padding: 2px 6px;
      background: rgba(102, 126, 234, 0.15);
      border: 1px solid rgba(102, 126, 234, 0.2);
      border-radius: 3px;
      font-size: 9px;
      color: #aaa;
    }
    .as-model-empty {
      text-align: center;
      color: #555;
      font-size: 12px;
      padding: 24px 10px;
    }
  `;

  // ── Helpers ────────────────────────────────────────────────────────

  function getCharIds() {
    if (window.CharacterBridge) return CharacterBridge.getCharacterIds();
    return [];
  }

  function getCharEntry(id) {
    if (window.CharacterBridge) return CharacterBridge.getCharacter(id);
    return null;
  }

  function getBoneRotation(charId, boneName) {
    const entry = getCharEntry(charId);
    if (!entry || !entry.model || !entry.model.bodyGroup) return { x: 0, y: 0, z: 0 };
    let rot = { x: 0, y: 0, z: 0 };
    entry.model.bodyGroup.traverse(function (child) {
      if (child.name === boneName) {
        rot = { x: child.rotation.x, y: child.rotation.y, z: child.rotation.z };
      }
    });
    return rot;
  }

  function setBoneRotation(charId, boneName, x, y, z) {
    const entry = getCharEntry(charId);
    if (!entry || !entry.model || !entry.model.bodyGroup) return;
    entry.model.bodyGroup.traverse(function (child) {
      if (child.name === boneName) {
        child.rotation.set(x, y, z);
      }
    });
  }

  function getAllBoneRotations(charId) {
    const result = {};
    BONE_NAMES.forEach(function (bone) {
      result[bone] = getBoneRotation(charId, bone);
    });
    return result;
  }

  function applyAllBoneRotations(charId, joints) {
    if (!joints) return;
    Object.keys(joints).forEach(function (bone) {
      const r = joints[bone];
      if (r) setBoneRotation(charId, bone, r.x || 0, r.y || 0, r.z || 0);
    });
  }

  function getCurrentExpression(charId) {
    if (!window.PenthouseAnim) return {};
    const debug = PenthouseAnim.AnimManager.getDebug
      ? PenthouseAnim.AnimManager.getDebug(charId)
      : null;
    if (debug && debug.currentExpression) return Object.assign({}, debug.currentExpression);
    let defaults = {};
    EXPRESSION_PROPS.forEach(function (p) { defaults[p] = 0; });
    return defaults;
  }

  function lerp(a, b, t) {
    return a + (b - a) * t;
  }

  function lerpJoints(jointsA, jointsB, t) {
    let result = {};
    BONE_NAMES.forEach(function (bone) {
      let a = jointsA[bone] || { x: 0, y: 0, z: 0 };
      let b = jointsB[bone] || { x: 0, y: 0, z: 0 };
      result[bone] = {
        x: lerp(a.x, b.x, t),
        y: lerp(a.y, b.y, t),
        z: lerp(a.z, b.z, t)
      };
    });
    return result;
  }

  // ── Fetch helpers ──────────────────────────────────────────────────

  function fetchJSON(url, opts) {
    return fetch(url, Object.assign({ headers: { 'Content-Type': 'application/json' } }, opts || {}))
      .then(function (r) { return r.json(); });
  }

  function loadPoseLibrary() {
    fetchJSON('/api/anim/poses').then(function (d) {
      _poseLibrary = d.poses || {};
      refreshLibraryTab();
    }).catch(function () {});
  }

  function loadSequenceLibrary() {
    fetchJSON('/api/anim/sequences').then(function (d) {
      _sequenceLibrary = d.sequences || {};
    }).catch(function () {});
  }

  // ── Panel creation ─────────────────────────────────────────────────

  function createPanel() {
    if (_panel) return _panel;

    // Inject CSS
    if (!document.getElementById('as-styles')) {
      let style = document.createElement('style');
      style.id = 'as-styles';
      style.textContent = STUDIO_CSS;
      document.head.appendChild(style);
    }

    _panel = document.createElement('div');
    _panel.id = 'ph-anim-studio';
    _panel.innerHTML = buildPanelHTML();
    document.body.appendChild(_panel);

    wireEvents();
    makeDraggable(_panel, _panel.querySelector('.as-header'));

    return _panel;
  }

  function buildPanelHTML() {
    return [
      '<div class="as-header">',
      '  <span class="as-title">\uD83C\uDFAC Animation Studio</span>',
      '  <button class="as-close" title="Close">\u2715</button>',
      '</div>',
      '<div class="as-body">',
      '  <div class="as-char-select">',
      '    <label>Character</label>',
      '    <select id="as-char-picker"></select>',
      '  </div>',
      '  <div class="as-tabs">',
      '    <button class="as-tab active" data-tab="poses">Poses</button>',
      '    <button class="as-tab" data-tab="expressions">Expressions</button>',
      '    <button class="as-tab" data-tab="sequences">Sequences</button>',
      '    <button class="as-tab" data-tab="library">Library</button>',
      '    <button class="as-tab" data-tab="models">Models</button>',
      '  </div>',
      buildPosesTab(),
      buildExpressionsTab(),
      buildSequencesTab(),
      buildLibraryTab(),
      buildModelsTab(),
      '</div>'
    ].join('\n');
  }

  // ── Poses Tab ──────────────────────────────────────────────────────

  function buildPosesTab() {
    let html = '<div class="as-tab-content" id="as-tab-poses">';
    html += '<div class="as-section-title">Joint Rotations</div>';
    html += '<div id="as-bone-list">';
    BONE_NAMES.forEach(function (bone) {
      let label = BONE_LABELS[bone] || bone;
      html += '<div class="as-bone-group" data-bone="' + bone + '">';
      html += '  <div class="as-bone-header">';
      html += '    <span>' + label + '</span>';
      html += '    <span style="font-size:10px;color:#667eea">\u25B6</span>';
      html += '  </div>';
      html += '  <div class="as-bone-sliders">';
      ['X', 'Y', 'Z'].forEach(function (axis) {
        let id = 'as-bone-' + bone + '-' + axis.toLowerCase();
        html += '  <div class="as-slider-row">';
        html += '    <label>' + axis + '</label>';
        html += '    <input type="range" id="' + id + '" min="-180" max="180" value="0" step="1">';
        html += '    <span class="as-slider-val" id="' + id + '-val">0\u00B0</span>';
        html += '  </div>';
      });
      html += '  </div>';
      html += '</div>';
    });
    html += '</div>';
    html += '<div class="as-btn-row">';
    html += '  <button class="as-btn" id="as-reset-pose">Reset Pose</button>';
    html += '  <button class="as-btn" id="as-mirror-pose">Mirror Pose</button>';
    html += '  <button class="as-btn as-btn--accent" id="as-save-pose">Save Pose</button>';
    html += '</div>';
    html += '</div>';
    return html;
  }

  // ── Expressions Tab ────────────────────────────────────────────────

  function buildExpressionsTab() {
    let html = '<div class="as-tab-content" id="as-tab-expressions" style="display:none">';
    html += '<div class="as-section-title">Presets</div>';
    html += '<div class="as-expr-grid">';
    EXPRESSION_PRESETS.forEach(function (name) {
      html += '<button class="as-expr-btn" data-expr="' + name + '">' + name + '</button>';
    });
    html += '</div>';
    html += '<div class="as-section-title">Custom Expression</div>';
    EXPRESSION_PROPS.forEach(function (prop) {
      let id = 'as-expr-' + prop;
      html += '<div class="as-slider-row">';
      html += '  <label style="width:50px;text-align:left;font-size:10px">' + prop + '</label>';
      html += '  <input type="range" id="' + id + '" min="-100" max="100" value="0" step="1">';
      html += '  <span class="as-slider-val" id="' + id + '-val">0.00</span>';
      html += '</div>';
    });
    html += '<div class="as-btn-row">';
    html += '  <button class="as-btn" id="as-reset-expr">Reset</button>';
    html += '  <button class="as-btn as-btn--accent" id="as-save-expr">Save Expression</button>';
    html += '</div>';
    html += '</div>';
    return html;
  }

  // ── Sequences Tab ──────────────────────────────────────────────────

  function buildSequencesTab() {
    let html = '<div class="as-tab-content" id="as-tab-sequences" style="display:none">';
    html += '<div class="as-section-title">Timeline</div>';
    html += '<div class="as-kf-list" id="as-kf-list">';
    html += '  <div class="as-empty">No keyframes. Add one below.</div>';
    html += '</div>';
    html += '<div class="as-btn-row" style="margin-bottom:8px">';
    html += '  <button class="as-btn" id="as-add-kf">\u2795 Add Keyframe</button>';
    html += '  <button class="as-btn" id="as-clear-kfs">Clear All</button>';
    html += '</div>';
    html += '<div class="as-section-title">Playback</div>';
    html += '<div class="as-playback">';
    html += '  <button class="as-btn" id="as-seq-play" title="Play">\u25B6</button>';
    html += '  <button class="as-btn" id="as-seq-pause" title="Pause">\u23F8</button>';
    html += '  <button class="as-btn" id="as-seq-stop" title="Stop">\u23F9</button>';
    html += '  <label class="as-toggle" title="Loop">';
    html += '    <input type="checkbox" id="as-seq-loop">';
    html += '    <span class="as-toggle-track"><span class="as-toggle-thumb"></span></span>';
    html += '    Loop';
    html += '  </label>';
    html += '  <span class="as-speed-lbl">Speed</span>';
    html += '  <button class="as-btn as-btn--sm" id="as-speed-down">\u2212</button>';
    html += '  <span class="as-speed-val" id="as-speed-val">1.0x</span>';
    html += '  <button class="as-btn as-btn--sm" id="as-speed-up">\u002B</button>';
    html += '</div>';
    html += '<div class="as-btn-row">';
    html += '  <button class="as-btn as-btn--accent" id="as-save-seq">Save Sequence</button>';
    html += '  <button class="as-btn" id="as-export-seq">Export JSON</button>';
    html += '</div>';
    html += '</div>';
    return html;
  }

  // ── Library Tab ────────────────────────────────────────────────────

  function buildLibraryTab() {
    let html = '<div class="as-tab-content" id="as-tab-library" style="display:none">';
    html += '<div class="as-section-title">Saved Poses</div>';
    html += '<div class="as-lib-grid" id="as-lib-poses">';
    html += '  <div class="as-empty">No saved poses yet.</div>';
    html += '</div>';
    html += '<div class="as-btn-row" style="margin-top:8px">';
    html += '  <button class="as-btn" id="as-import-lib">\u{1F4C2} Import</button>';
    html += '  <button class="as-btn" id="as-export-lib">\u{1F4E4} Export</button>';
    html += '  <input type="file" class="as-file-input" id="as-import-file" accept=".json">';
    html += '</div>';
    html += '</div>';
    return html;
  }

  // ── Models Tab ─────────────────────────────────────────────────────

  function buildModelsTab() {
    let h = '<div class="as-tab-content" id="as-tab-models" style="display:none">';
    h += '<div class="as-section-title">\uD83D\uDCE6 Model Browser</div>';
    h += '<input type="text" class="as-model-search" id="as-model-search" placeholder="Search models by name, type, or tag\u2026">';
    h += '<div class="as-model-filters" id="as-model-filters">';
    h += '  <button class="as-model-filter-btn active" data-mfilter="all">All</button>';
    h += '  <button class="as-model-filter-btn" data-mfilter="character">\uD83D\uDC64 Characters</button>';
    h += '  <button class="as-model-filter-btn" data-mfilter="prop">\uD83C\uDF81 Props</button>';
    h += '  <button class="as-model-filter-btn" data-mfilter="clothing">\uD83D\uDC57 Clothing</button>';
    h += '  <button class="as-model-filter-btn" data-mfilter="environment">\uD83C\uDFE0 Environment</button>';
    h += '</div>';
    h += '<div class="as-model-stats" id="as-model-stats"></div>';
    h += '<div class="as-model-grid" id="as-model-grid">';
    h += '  <div class="as-model-empty">Loading models\u2026</div>';
    h += '</div>';
    h += '<div class="as-model-detail" id="as-model-detail" style="display:none">';
    h += '  <div class="as-model-detail-hdr">';
    h += '    <h4 id="as-model-detail-name">Model</h4>';
    h += '    <button class="as-model-detail-close" id="as-model-detail-close">\u2715</button>';
    h += '  </div>';
    h += '  <div class="as-model-detail-icon" id="as-model-detail-icon">\uD83D\uDCE6</div>';
    h += '  <div id="as-model-detail-body"></div>';
    h += '</div>';
    h += '</div>';
    return h;
  }

  const _MODEL_TYPE_ICONS = {
    character: '\uD83D\uDC64', prop: '\uD83C\uDF81',
    clothing: '\uD83D\uDC57', environment: '\uD83C\uDFE0', unknown: '\uD83D\uDCE6'
  };

  function loadModelCatalog() {
    fetchJSON('/api/config/models').then(function (data) {
      _modelCatalog = data.catalog || data || {};
      // Remove non-model keys
      delete _modelCatalog.categories;
      delete _modelCatalog.bone_mapping;
      delete _modelCatalog.import_settings;
      renderModelGrid();
    }).catch(function () {
      let grid = document.getElementById('as-model-grid');
      if (grid) grid.innerHTML = '<div class="as-model-empty">Failed to load catalog.</div>';
    });
  }

  function getFilteredModels() {
    let result = {};
    let q = _modelSearch.toLowerCase();
    Object.keys(_modelCatalog).forEach(function (id) {
      let entry = _modelCatalog[id];
      if (!entry || typeof entry !== 'object' || !entry.file) return;
      if (_modelFilter !== 'all' && entry.type !== _modelFilter) return;
      if (q) {
        let haystack = (id + ' ' + (entry.description || '') + ' ' + (entry.file || '') +
          ' ' + (entry.tags || []).join(' ') + ' ' + (entry.type || '') + ' ' + (entry.gender || '')).toLowerCase();
        if (haystack.indexOf(q) === -1) return;
      }
      result[id] = entry;
    });
    return result;
  }

  function renderModelGrid() {
    let grid = document.getElementById('as-model-grid');
    if (!grid) return;
    let filtered = getFilteredModels();
    let keys = Object.keys(filtered);

    let stats = document.getElementById('as-model-stats');
    if (stats) {
      let total = Object.keys(_modelCatalog).filter(function (k) {
        let e = _modelCatalog[k]; return e && typeof e === 'object' && e.file;
      }).length;
      stats.textContent = keys.length + ' of ' + total + ' models';
    }

    if (keys.length === 0) {
      grid.innerHTML = '<div class="as-model-empty">No models match your search.</div>';
      return;
    }

    let html = '';
    keys.forEach(function (id) {
      let m = filtered[id];
      let icon = _MODEL_TYPE_ICONS[m.type] || '\uD83D\uDCE6';
      let skel = m.has_skeleton ? '\u2699' : '';
      let displayName = id.replace(/_/g, ' ');
      html += '<div class="as-model-card" data-mid="' + id + '">';
      html += '  <div class="as-model-card-icon">' + icon + '</div>';
      html += '  <div class="as-model-card-name" title="' + id + '">' + displayName + '</div>';
      html += '  <div class="as-model-card-meta">' + (m.size_mb || '?') + ' MB ' + skel + '</div>';
      html += '</div>';
    });
    grid.innerHTML = html;

    grid.querySelectorAll('.as-model-card').forEach(function (card) {
      card.addEventListener('click', function () {
        grid.querySelectorAll('.as-model-card').forEach(function (c) { c.classList.remove('selected'); });
        card.classList.add('selected');
        showModelDetail(card.dataset.mid);
      });
    });
  }

  function showModelDetail(modelId) {
    let m = _modelCatalog[modelId];
    if (!m) return;
    let icon = _MODEL_TYPE_ICONS[m.type] || '\uD83D\uDCE6';
    document.getElementById('as-model-detail-name').textContent = modelId.replace(/_/g, ' ');
    document.getElementById('as-model-detail-icon').textContent = icon;

    let body = document.getElementById('as-model-detail-body');
    let rows = [
      ['Type', (icon + ' ' + (m.type || 'unknown'))],
      ['Gender', m.gender || '\u2014'],
      ['File', m.file || '\u2014'],
      ['Size', (m.size_mb || '?') + ' MB'],
      ['Skeleton', m.has_skeleton ? '\u2705 Yes' : '\u274C No'],
      ['Animations', m.has_animations ? '\u2705 Yes' : '\u274C No'],
      ['Poly Estimate', m.poly_estimate || '\u2014'],
      ['Description', m.description || '\u2014'],
    ];
    let html = '';
    rows.forEach(function (r) {
      html += '<div class="as-model-detail-row">';
      html += '  <span class="label">' + r[0] + '</span>';
      html += '  <span class="value">' + r[1] + '</span>';
      html += '</div>';
    });
    if (m.tags && m.tags.length) {
      html += '<div class="as-model-detail-tags">';
      m.tags.forEach(function (tag) {
        html += '<span class="as-model-tag">' + tag + '</span>';
      });
      html += '</div>';
    }
    body.innerHTML = html;
    document.getElementById('as-model-detail').style.display = '';
  }

  function closeModelDetail() {
    document.getElementById('as-model-detail').style.display = 'none';
    let grid = document.getElementById('as-model-grid');
    if (grid) grid.querySelectorAll('.as-model-card').forEach(function (c) { c.classList.remove('selected'); });
  }

  // ── Event wiring ───────────────────────────────────────────────────

  function wireEvents() {
    // Close
    _panel.querySelector('.as-close').addEventListener('click', close);

    // Tab switching
    _panel.querySelectorAll('.as-tab').forEach(function (tab) {
      tab.addEventListener('click', function () {
        _panel.querySelectorAll('.as-tab').forEach(function (t) { t.classList.remove('active'); });
        _panel.querySelectorAll('.as-tab-content').forEach(function (c) { c.style.display = 'none'; });
        tab.classList.add('active');
        let target = document.getElementById('as-tab-' + tab.dataset.tab);
        if (target) target.style.display = '';
        if (tab.dataset.tab === 'library') refreshLibraryTab();
        if (tab.dataset.tab === 'models') loadModelCatalog();
      });
    });

    // Character picker
    document.getElementById('as-char-picker').addEventListener('change', function (e) {
      _selectedCharId = e.target.value;
      syncSlidersFromCharacter();
    });

    // Bone group accordions
    _panel.querySelectorAll('.as-bone-header').forEach(function (header) {
      header.addEventListener('click', function () {
        let sliders = header.nextElementSibling;
        sliders.classList.toggle('open');
        let arrow = header.querySelector('span:last-child');
        arrow.textContent = sliders.classList.contains('open') ? '\u25BC' : '\u25B6';
      });
    });

    // Bone sliders
    BONE_NAMES.forEach(function (bone) {
      ['x', 'y', 'z'].forEach(function (axis) {
        let slider = document.getElementById('as-bone-' + bone + '-' + axis);
        let valSpan = document.getElementById('as-bone-' + bone + '-' + axis + '-val');
        if (!slider) return;
        slider.addEventListener('input', function () {
          let deg = parseFloat(slider.value);
          valSpan.textContent = deg + '\u00B0';
          if (_selectedCharId) {
            let rad = deg * DEG2RAD;
            let rot = getBoneRotation(_selectedCharId, bone);
            if (axis === 'x') rot.x = rad;
            else if (axis === 'y') rot.y = rad;
            else rot.z = rad;
            setBoneRotation(_selectedCharId, bone, rot.x, rot.y, rot.z);
          }
        });
      });
    });

    // Reset / Mirror / Save pose
    document.getElementById('as-reset-pose').addEventListener('click', resetPose);
    document.getElementById('as-mirror-pose').addEventListener('click', mirrorPose);
    document.getElementById('as-save-pose').addEventListener('click', savePosePrompt);

    // Expression presets
    _panel.querySelectorAll('.as-expr-btn').forEach(function (btn) {
      btn.addEventListener('click', function () {
        _panel.querySelectorAll('.as-expr-btn').forEach(function (b) { b.classList.remove('active'); });
        btn.classList.add('active');
        applyExpressionPreset(btn.dataset.expr);
      });
    });

    // Expression sliders
    EXPRESSION_PROPS.forEach(function (prop) {
      let slider = document.getElementById('as-expr-' + prop);
      let valSpan = document.getElementById('as-expr-' + prop + '-val');
      if (!slider) return;
      slider.addEventListener('input', function () {
        let val = parseFloat(slider.value) / 100;
        valSpan.textContent = val.toFixed(2);
        applyCustomExpression();
      });
    });

    // Reset / Save expression
    document.getElementById('as-reset-expr').addEventListener('click', resetExpression);
    document.getElementById('as-save-expr').addEventListener('click', saveExpressionPrompt);

    // Keyframe controls
    document.getElementById('as-add-kf').addEventListener('click', addKeyframe);
    document.getElementById('as-clear-kfs').addEventListener('click', clearKeyframes);

    // Playback controls
    document.getElementById('as-seq-play').addEventListener('click', playSequence);
    document.getElementById('as-seq-pause').addEventListener('click', pauseSequence);
    document.getElementById('as-seq-stop').addEventListener('click', stopSequence);
    document.getElementById('as-seq-loop').addEventListener('change', function (e) {
      _seqLoop = e.target.checked;
    });
    document.getElementById('as-speed-down').addEventListener('click', function () {
      _seqSpeed = Math.max(0.25, _seqSpeed - 0.25);
      document.getElementById('as-speed-val').textContent = _seqSpeed.toFixed(1) + 'x';
    });
    document.getElementById('as-speed-up').addEventListener('click', function () {
      _seqSpeed = Math.min(4.0, _seqSpeed + 0.25);
      document.getElementById('as-speed-val').textContent = _seqSpeed.toFixed(1) + 'x';
    });

    // Save / Export sequence
    document.getElementById('as-save-seq').addEventListener('click', saveSequencePrompt);
    document.getElementById('as-export-seq').addEventListener('click', exportSequenceJSON);

    // Library import/export
    document.getElementById('as-import-lib').addEventListener('click', function () {
      document.getElementById('as-import-file').click();
    });
    document.getElementById('as-import-file').addEventListener('change', importLibrary);
    document.getElementById('as-export-lib').addEventListener('click', exportLibrary);

    // Model browser events
    let modelSearchInput = document.getElementById('as-model-search');
    if (modelSearchInput) {
      modelSearchInput.addEventListener('input', function (e) {
        _modelSearch = e.target.value;
        renderModelGrid();
      });
    }
    _panel.querySelectorAll('.as-model-filter-btn').forEach(function (btn) {
      btn.addEventListener('click', function () {
        _panel.querySelectorAll('.as-model-filter-btn').forEach(function (b) {
          b.classList.remove('active');
        });
        btn.classList.add('active');
        _modelFilter = btn.dataset.mfilter;
        renderModelGrid();
      });
    });
    let detailClose = document.getElementById('as-model-detail-close');
    if (detailClose) {
      detailClose.addEventListener('click', closeModelDetail);
    }
  }

  // ── Draggable ──────────────────────────────────────────────────────

  function makeDraggable(el, handle) {
    let isDragging = false;
    let startX, startY, origX, origY;
    handle.style.cursor = 'grab';

    handle.addEventListener('mousedown', function (e) {
      isDragging = true;
      startX = e.clientX;
      startY = e.clientY;
      let rect = el.getBoundingClientRect();
      origX = rect.left;
      origY = rect.top;
      handle.style.cursor = 'grabbing';
      e.preventDefault();
    });

    document.addEventListener('mousemove', function (e) {
      if (!isDragging) return;
      el.style.left = (origX + e.clientX - startX) + 'px';
      el.style.top = (origY + e.clientY - startY) + 'px';
      el.style.right = 'auto';
    });

    document.addEventListener('mouseup', function () {
      if (!isDragging) return;
      isDragging = false;
      handle.style.cursor = 'grab';
    });
  }

  // ── Character picker ───────────────────────────────────────────────

  function populateCharPicker() {
    let picker = document.getElementById('as-char-picker');
    if (!picker) return;
    let ids = getCharIds();
    picker.innerHTML = '';
    if (ids.length === 0) {
      picker.innerHTML = '<option value="">No characters loaded</option>';
      return;
    }
    ids.forEach(function (id) {
      let entry = getCharEntry(id);
      let label = entry && entry.name ? entry.name : id;
      let opt = document.createElement('option');
      opt.value = id;
      opt.textContent = label;
      picker.appendChild(opt);
    });
    if (!_selectedCharId || ids.indexOf(_selectedCharId) === -1) {
      _selectedCharId = ids[0];
    }
    picker.value = _selectedCharId;
  }

  // ── Sync sliders from character ────────────────────────────────────

  function syncSlidersFromCharacter() {
    if (!_selectedCharId) return;
    BONE_NAMES.forEach(function (bone) {
      let rot = getBoneRotation(_selectedCharId, bone);
      ['x', 'y', 'z'].forEach(function (axis) {
        let slider = document.getElementById('as-bone-' + bone + '-' + axis);
        let valSpan = document.getElementById('as-bone-' + bone + '-' + axis + '-val');
        if (!slider) return;
        let deg = Math.round(rot[axis] * RAD2DEG);
        slider.value = deg;
        valSpan.textContent = deg + '\u00B0';
      });
    });
  }

  // ── Pose actions ───────────────────────────────────────────────────

  function resetPose() {
    if (!_selectedCharId) return;
    BONE_NAMES.forEach(function (bone) {
      setBoneRotation(_selectedCharId, bone, 0, 0, 0);
    });
    syncSlidersFromCharacter();
  }

  function mirrorPose() {
    if (!_selectedCharId) return;
    let joints = getAllBoneRotations(_selectedCharId);
    let MIRROR_PAIRS = [
      ['arm_l', 'arm_r'], ['forearm_l', 'forearm_r'],
      ['hand_l', 'hand_r'], ['thigh_l', 'thigh_r'],
      ['shin_l', 'shin_r']
    ];
    MIRROR_PAIRS.forEach(function (pair) {
      let l = joints[pair[0]] || { x: 0, y: 0, z: 0 };
      let r = joints[pair[1]] || { x: 0, y: 0, z: 0 };
      // Swap and negate Y/Z for mirroring
      setBoneRotation(_selectedCharId, pair[0], r.x, -r.y, -r.z);
      setBoneRotation(_selectedCharId, pair[1], l.x, -l.y, -l.z);
    });
    syncSlidersFromCharacter();
  }

  function savePosePrompt() {
    if (!_selectedCharId) return;
    let name = prompt('Pose name:');
    if (!name) return;
    let joints = getAllBoneRotations(_selectedCharId);
    fetchJSON('/api/anim/poses', {
      method: 'POST',
      body: JSON.stringify({ name: name, joints: joints, character_id: _selectedCharId })
    }).then(function (d) {
      if (d.success) {
        loadPoseLibrary();
      }
    });
  }

  // ── Expression actions ─────────────────────────────────────────────

  function applyExpressionPreset(presetName) {
    if (!_selectedCharId) return;
    if (window.PenthouseAnim) {
      PenthouseAnim.AnimManager.setMood(_selectedCharId, presetName);
    } else if (window.CharacterBridge) {
      CharacterBridge.setMood(_selectedCharId, presetName);
    }
  }

  function applyCustomExpression() {
    if (!_selectedCharId) return;
    let values = {};
    EXPRESSION_PROPS.forEach(function (prop) {
      let slider = document.getElementById('as-expr-' + prop);
      values[prop] = slider ? parseFloat(slider.value) / 100 : 0;
    });
    if (window.PenthouseAnim && PenthouseAnim.AnimManager.setExpression) {
      PenthouseAnim.AnimManager.setExpression(_selectedCharId, values);
    }
  }

  function resetExpression() {
    EXPRESSION_PROPS.forEach(function (prop) {
      let slider = document.getElementById('as-expr-' + prop);
      let valSpan = document.getElementById('as-expr-' + prop + '-val');
      if (slider) { slider.value = 0; }
      if (valSpan) { valSpan.textContent = '0.00'; }
    });
    _panel.querySelectorAll('.as-expr-btn').forEach(function (b) { b.classList.remove('active'); });
    if (_selectedCharId) applyExpressionPreset('neutral');
  }

  function saveExpressionPrompt() {
    let name = prompt('Expression name:');
    if (!name) return;
    let values = {};
    EXPRESSION_PROPS.forEach(function (prop) {
      let slider = document.getElementById('as-expr-' + prop);
      values[prop] = slider ? parseFloat(slider.value) / 100 : 0;
    });
    fetchJSON('/api/anim/expressions', {
      method: 'POST',
      body: JSON.stringify({ name: name, values: values })
    }).then(function (d) {
      if (d.success) loadPoseLibrary();
    });
  }

  // ── Keyframe / Sequence actions ────────────────────────────────────

  function addKeyframe() {
    if (!_selectedCharId) return;
    let pose = getAllBoneRotations(_selectedCharId);
    let exprVals = {};
    EXPRESSION_PROPS.forEach(function (prop) {
      let slider = document.getElementById('as-expr-' + prop);
      exprVals[prop] = slider ? parseFloat(slider.value) / 100 : 0;
    });
    let time = _seqKeyframes.length > 0
      ? _seqKeyframes[_seqKeyframes.length - 1].time + 1.0
      : 0;
    _seqKeyframes.push({
      name: 'Key ' + (_seqKeyframes.length + 1),
      time: time,
      pose: pose,
      expression: exprVals
    });
    renderKeyframeList();
  }

  function clearKeyframes() {
    _seqKeyframes = [];
    stopSequence();
    renderKeyframeList();
  }

  function renderKeyframeList() {
    let container = document.getElementById('as-kf-list');
    if (!container) return;
    if (_seqKeyframes.length === 0) {
      container.innerHTML = '<div class="as-empty">No keyframes. Add one below.</div>';
      return;
    }
    let html = '';
    _seqKeyframes.forEach(function (kf, i) {
      html += '<div class="as-kf-item" data-idx="' + i + '">';
      html += '  <span class="as-kf-idx">' + (i + 1) + '</span>';
      html += '  <input class="as-kf-name" value="' + kf.name + '" data-idx="' + i + '">';
      html += '  <input class="as-kf-time" type="number" value="' + kf.time.toFixed(1) + '" step="0.1" min="0" data-idx="' + i + '">';
      html += '  <span style="font-size:9px;color:#666">s</span>';
      html += '  <button class="as-kf-del" data-idx="' + i + '" title="Remove">\u2716</button>';
      html += '</div>';
    });
    container.innerHTML = html;

    // Wire keyframe events
    container.querySelectorAll('.as-kf-name').forEach(function (input) {
      input.addEventListener('change', function () {
        let idx = parseInt(input.dataset.idx);
        if (_seqKeyframes[idx]) _seqKeyframes[idx].name = input.value;
      });
    });
    container.querySelectorAll('.as-kf-time').forEach(function (input) {
      input.addEventListener('change', function () {
        let idx = parseInt(input.dataset.idx);
        if (_seqKeyframes[idx]) _seqKeyframes[idx].time = parseFloat(input.value) || 0;
      });
    });
    container.querySelectorAll('.as-kf-del').forEach(function (btn) {
      btn.addEventListener('click', function () {
        let idx = parseInt(btn.dataset.idx);
        _seqKeyframes.splice(idx, 1);
        renderKeyframeList();
      });
    });
  }

  // ── Sequence playback ──────────────────────────────────────────────

  function playSequence() {
    if (_seqKeyframes.length < 2 || !_selectedCharId) return;
    if (_seqPaused) {
      _seqPaused = false;
      _seqStartTime = performance.now() - (_seqPauseElapsed || 0);
      _seqRafId = requestAnimationFrame(sequenceTick);
      return;
    }
    // Sort keyframes by time
    _seqKeyframes.sort(function (a, b) { return a.time - b.time; });
    _seqPlaying = true;
    _seqPaused = false;
    _seqStartTime = performance.now();
    _seqCurrentIdx = 0;
    _seqRafId = requestAnimationFrame(sequenceTick);
  }

  let _seqPauseElapsed = 0;

  function pauseSequence() {
    if (!_seqPlaying) return;
    _seqPaused = true;
    _seqPauseElapsed = performance.now() - _seqStartTime;
    if (_seqRafId) cancelAnimationFrame(_seqRafId);
  }

  function stopSequence() {
    _seqPlaying = false;
    _seqPaused = false;
    _seqPauseElapsed = 0;
    if (_seqRafId) cancelAnimationFrame(_seqRafId);
    _seqRafId = null;
  }

  function sequenceTick(now) {
    if (!_seqPlaying || _seqPaused) return;
    let elapsed = ((now - _seqStartTime) / 1000) * _seqSpeed;
    let totalDuration = _seqKeyframes[_seqKeyframes.length - 1].time;
    if (totalDuration <= 0) { stopSequence(); return; }

    if (elapsed >= totalDuration) {
      if (_seqLoop) {
        _seqStartTime = now;
        elapsed = 0;
      } else {
        // Apply final keyframe
        let lastKf = _seqKeyframes[_seqKeyframes.length - 1];
        applyAllBoneRotations(_selectedCharId, lastKf.pose);
        stopSequence();
        return;
      }
    }

    // Find surrounding keyframes
    let kfA = _seqKeyframes[0];
    let kfB = _seqKeyframes[1];
    for (let i = 0; i < _seqKeyframes.length - 1; i++) {
      if (elapsed >= _seqKeyframes[i].time && elapsed <= _seqKeyframes[i + 1].time) {
        kfA = _seqKeyframes[i];
        kfB = _seqKeyframes[i + 1];
        break;
      }
    }

    let segDuration = kfB.time - kfA.time;
    let t = segDuration > 0 ? (elapsed - kfA.time) / segDuration : 0;
    t = Math.max(0, Math.min(1, t));

    // Interpolate pose
    let interpJoints = lerpJoints(kfA.pose, kfB.pose, t);
    applyAllBoneRotations(_selectedCharId, interpJoints);

    // Interpolate expression
    if (kfA.expression && kfB.expression) {
      let interpExpr = {};
      EXPRESSION_PROPS.forEach(function (prop) {
        interpExpr[prop] = lerp(kfA.expression[prop] || 0, kfB.expression[prop] || 0, t);
      });
      if (window.PenthouseAnim && PenthouseAnim.AnimManager.setExpression) {
        PenthouseAnim.AnimManager.setExpression(_selectedCharId, interpExpr);
      }
    }

    _seqRafId = requestAnimationFrame(sequenceTick);
  }

  function saveSequencePrompt() {
    if (_seqKeyframes.length === 0) return;
    let name = prompt('Sequence name:');
    if (!name) return;
    fetchJSON('/api/anim/sequences', {
      method: 'POST',
      body: JSON.stringify({
        name: name,
        keyframes: _seqKeyframes,
        loop: _seqLoop,
        speed: _seqSpeed
      })
    }).then(function (d) {
      if (d.success) loadSequenceLibrary();
    });
  }

  function exportSequenceJSON() {
    if (_seqKeyframes.length === 0) return;
    let data = {
      name: 'Untitled Sequence',
      keyframes: _seqKeyframes,
      loop: _seqLoop,
      speed: _seqSpeed,
      exportedAt: new Date().toISOString()
    };
    downloadJSON(data, 'anim-sequence.json');
  }

  // ── Library tab ────────────────────────────────────────────────────

  function refreshLibraryTab() {
    let container = document.getElementById('as-lib-poses');
    if (!container) return;
    let keys = Object.keys(_poseLibrary).filter(function (k) {
      return !_poseLibrary[k].type || _poseLibrary[k].type !== 'expression';
    });
    if (keys.length === 0) {
      container.innerHTML = '<div class="as-empty">No saved poses yet.</div>';
      return;
    }

    // Group poses by category
    let groups = {};
    keys.forEach(function (id) {
      let pose = _poseLibrary[id];
      let cat = pose.category || (pose.builtin ? 'built-in' : 'custom');
      if (!groups[cat]) groups[cat] = [];
      groups[cat].push({ id: id, pose: pose });
    });

    // Render order: furniture first, then basic, gesture, social, then custom
    let catOrder = ['furniture', 'basic', 'gesture', 'social', 'custom'];
    let catLabels = {
      furniture: '🪑 Furniture Interactions',
      basic: '🧍 Basic Poses',
      gesture: '👋 Gestures',
      social: '💃 Social',
      custom: '✏️ Custom Poses'
    };
    // Include any categories not in the predefined order
    Object.keys(groups).forEach(function (cat) {
      if (catOrder.indexOf(cat) === -1) catOrder.push(cat);
    });

    let html = '';
    catOrder.forEach(function (cat) {
      let items = groups[cat];
      if (!items || items.length === 0) return;
      html += '<div class="as-lib-section">';
      html += '  <div class="as-lib-section-title">' + (catLabels[cat] || cat) + '</div>';
      items.forEach(function (item) {
        let pose = item.pose;
        let isBuiltin = pose.builtin;
        html += '<div class="as-lib-card' + (isBuiltin ? ' as-lib-builtin' : '') + '" data-pose-id="' + item.id + '">';
        html += '  <div class="as-lib-name">' + (pose.name || 'Unnamed');
        if (isBuiltin) html += ' <span class="as-badge">built-in</span>';
        html += '</div>';
        html += '  <div class="as-lib-meta">';
        html += '    ' + (pose.joint_count || Object.keys(pose.joints || {}).length) + ' joints';
        if (pose.location && pose.location !== 'any') html += ' \u2022 ' + pose.location;
        if (!isBuiltin && pose.created_at) html += ' \u2022 ' + pose.created_at.substring(0, 10);
        html += '  </div>';
        html += '  <div class="as-lib-actions">';
        html += '    <button class="as-btn as-btn--sm as-lib-load" data-pose-id="' + item.id + '">Load</button>';
        if (!isBuiltin) {
          html += '    <button class="as-btn as-btn--sm as-btn--accent as-lib-del" data-pose-id="' + item.id + '">Del</button>';
        }
        html += '  </div>';
        html += '</div>';
      });
      html += '</div>';
    });
    container.innerHTML = html;

    // Wire load/delete
    container.querySelectorAll('.as-lib-load').forEach(function (btn) {
      btn.addEventListener('click', function (e) {
        e.stopPropagation();
        loadPoseFromLibrary(btn.dataset.poseId);
      });
    });
    container.querySelectorAll('.as-lib-del').forEach(function (btn) {
      btn.addEventListener('click', function (e) {
        e.stopPropagation();
        deletePoseFromLibrary(btn.dataset.poseId);
      });
    });
  }

  function loadPoseFromLibrary(poseId) {
    if (!_selectedCharId) return;
    let pose = _poseLibrary[poseId];
    if (!pose || !pose.joints) return;
    applyAllBoneRotations(_selectedCharId, pose.joints);
      // Set animation state to 'pose' so state machine doesn't overwrite bones
      if (window.CharacterBridge) {
        const charIds = CharacterBridge.getCharacterIds();
        if (charIds.length > 0) {
          CharacterBridge.setAnimState(charIds[0], 'pose');
        }
      }
    syncSlidersFromCharacter();
  }

  function deletePoseFromLibrary(poseId) {
    fetchJSON('/api/anim/poses/' + poseId, { method: 'DELETE' })
      .then(function (d) {
        if (d.success) {
          delete _poseLibrary[poseId];
          refreshLibraryTab();
        }
      });
  }

  function importLibrary(e) {
    let file = e.target.files && e.target.files[0];
    if (!file) return;
    let reader = new FileReader();
    reader.onload = function () {
      try {
        let data = JSON.parse(reader.result);
        let poses = data.poses || data;
        let count = 0;
        let keys = Object.keys(poses);
        let total = keys.length;
        keys.forEach(function (key) {
          let pose = poses[key];
          if (pose.name && pose.joints) {
            fetchJSON('/api/anim/poses', {
              method: 'POST',
              body: JSON.stringify({ name: pose.name, joints: pose.joints })
            }).then(function () {
              count++;
              if (count >= total) loadPoseLibrary();
            });
          }
        });
      } catch (err) {
        console.error('[AnimStudio] Import failed:', err);
      }
    };
    reader.readAsText(file);
    e.target.value = '';
  }

  function exportLibrary() {
    if (Object.keys(_poseLibrary).length === 0) return;
    downloadJSON({ poses: _poseLibrary }, 'pose-library.json');
  }

  // ── Utility ────────────────────────────────────────────────────────

  function downloadJSON(data, filename) {
    let blob = new Blob([JSON.stringify(data, null, 2)], { type: 'application/json' });
    let url = URL.createObjectURL(blob);
    let a = document.createElement('a');
    a.href = url;
    a.download = filename;
    document.body.appendChild(a);
    a.click();
    document.body.removeChild(a);
    URL.revokeObjectURL(url);
  }

  // ── Open / Close / Toggle ──────────────────────────────────────────

  function open() {
    createPanel();
    _isOpen = true;
    _panel.style.display = 'block';
    populateCharPicker();
    syncSlidersFromCharacter();
    loadPoseLibrary();
    loadSequenceLibrary();
  }

  function close() {
    _isOpen = false;
    if (_panel) _panel.style.display = 'none';
    stopSequence();
  }

  function toggle() {
    if (_isOpen) close();
    else open();
  }

  // ── Public API ─────────────────────────────────────────────────────

  window.PenthouseAnimStudio = {
    open: open,
    close: close,
    toggle: toggle,
    isOpen: function () { return _isOpen; }
  };

})();
