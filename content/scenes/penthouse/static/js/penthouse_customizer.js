/**
 * penthouse_customizer.js — Character Clothing & Appearance Customizer
 *
 * Floating panel UI for:
 * - Outfit selection with category tabs
 * - Color picker for outfit primary/accent colors
 * - Skin tone, hair color, eye color selectors
 * - Live 3D preview (changes apply in real-time)
 * - Save/load custom presets
 *
 * Loads after penthouse_config.js, reads outfit/character config from YAML.
 */

(function () {
  'use strict';

  let _panel = null;
  let _selectedCharId = null;
  let _configData = null;
  let _isOpen = false;

  // ═══════════════════════════════════════════════════════════════════
  //  BUILD UI
  // ═══════════════════════════════════════════════════════════════════

  function createPanel() {
    if (_panel) return _panel;

    _panel = document.createElement('div');
    _panel.id = 'ph-customizer';
    _panel.innerHTML = `
      <div class="cust-header">
        <span class="cust-title">✨ Character Customizer</span>
        <button class="cust-close" title="Close">✕</button>
      </div>
      <div class="cust-body">
        <div class="cust-char-select">
          <label>Character</label>
          <select id="cust-char-picker"></select>
        </div>

        <div class="cust-tabs">
          <button class="cust-tab active" data-tab="outfit">Outfit</button>
          <button class="cust-tab" data-tab="colors">Colors</button>
          <button class="cust-tab" data-tab="appearance">Appearance</button>
        </div>

        <!-- Outfit Tab -->
        <div class="cust-tab-content" id="cust-tab-outfit">
          <div class="cust-outfit-categories" id="cust-outfit-cats"></div>
          <div class="cust-outfit-grid" id="cust-outfit-grid"></div>
        </div>

        <!-- Colors Tab -->
        <div class="cust-tab-content" id="cust-tab-colors" style="display:none">
          <div class="cust-color-row">
            <label>Primary Color</label>
            <input type="color" id="cust-color-primary" value="#1a1a1a">
          </div>
          <div class="cust-color-row">
            <label>Accent Color</label>
            <input type="color" id="cust-color-accent" value="#cc2244">
          </div>
          <button class="cust-apply-btn" id="cust-apply-colors">Apply Colors</button>
        </div>

        <!-- Appearance Tab -->
        <div class="cust-tab-content" id="cust-tab-appearance" style="display:none">
          <div class="cust-palette-section">
            <label>Skin Tone</label>
            <div class="cust-palette" id="cust-skin-palette"></div>
          </div>
          <div class="cust-palette-section">
            <label>Hair Color</label>
            <div class="cust-palette" id="cust-hair-palette"></div>
          </div>
          <div class="cust-palette-section">
            <label>Eye Color</label>
            <div class="cust-palette" id="cust-eye-palette"></div>
          </div>
        </div>
      </div>
    `;

    // Inject styles
    if (!document.getElementById('cust-styles')) {
      const style = document.createElement('style');
      style.id = 'cust-styles';
      style.textContent = CUSTOMIZER_CSS;
      document.head.appendChild(style);
    }

    document.body.appendChild(_panel);

    // Wire events
    _panel.querySelector('.cust-close').addEventListener('click', close);

    // Tab switching
    _panel.querySelectorAll('.cust-tab').forEach(tab => {
      tab.addEventListener('click', () => {
        _panel.querySelectorAll('.cust-tab').forEach(t => t.classList.remove('active'));
        _panel.querySelectorAll('.cust-tab-content').forEach(c => c.style.display = 'none');
        tab.classList.add('active');
        const target = document.getElementById('cust-tab-' + tab.dataset.tab);
        if (target) target.style.display = '';
      });
    });

    // Character picker
    document.getElementById('cust-char-picker').addEventListener('change', (e) => {
      _selectedCharId = e.target.value;
      refreshOutfitGrid();
    });

    // Color apply
    document.getElementById('cust-apply-colors').addEventListener('click', applyColors);

    // Draggable
    makeDraggable(_panel, _panel.querySelector('.cust-header'));

    return _panel;
  }

  // ═══════════════════════════════════════════════════════════════════
  //  OPEN / CLOSE
  // ═══════════════════════════════════════════════════════════════════

  function open(charId) {
    createPanel();
    _isOpen = true;
    _panel.style.display = 'block';
    _selectedCharId = charId || null;

    // Load config if available
    if (window.PenthouseConfig && PenthouseConfig.get('outfits')) {
      _configData = {
        outfits: PenthouseConfig.get('outfits'),
        characters: PenthouseConfig.get('characters'),
      };
    } else {
      // Fetch directly
      fetch('/api/config/all').then(r => r.json()).then(data => {
        _configData = data;
        populateAll();
      }).catch(() => {});
    }

    populateAll();
  }

  function close() {
    _isOpen = false;
    if (_panel) _panel.style.display = 'none';
  }

  function toggle(charId) {
    if (_isOpen) close();
    else open(charId);
  }

  // ═══════════════════════════════════════════════════════════════════
  //  POPULATE
  // ═══════════════════════════════════════════════════════════════════

  function populateAll() {
    populateCharacterPicker();
    populateOutfitCategories();
    refreshOutfitGrid();
    populatePalettes();
  }

  function populateCharacterPicker() {
    const picker = document.getElementById('cust-char-picker');
    if (!picker) return;

    picker.innerHTML = '<option value="">Select character...</option>';

    if (window.CharacterBridge) {
      const ids = CharacterBridge.getCharacterIds();
      ids.forEach(id => {
        const entry = CharacterBridge.getCharacter(id);
        const name = entry?.model?.group?.name || id;
        const opt = document.createElement('option');
        opt.value = id;
        opt.textContent = name || id;
        if (id === _selectedCharId) opt.selected = true;
        picker.appendChild(opt);
      });
    }
  }

  function populateOutfitCategories() {
    const container = document.getElementById('cust-outfit-cats');
    if (!container) return;

    const categories = _configData?.outfits?.categories || {
      casual: { label: 'Casual', order: 1 },
      formal: { label: 'Formal', order: 2 },
      intimate: { label: 'Intimate', order: 3 },
      bold: { label: 'Bold', order: 4 },
      costume: { label: 'Costume', order: 5 },
      explicit: { label: 'Explicit', order: 6 },
    };

    const sorted = Object.entries(categories).sort((a, b) => (a[1].order || 0) - (b[1].order || 0));

    container.innerHTML = '<button class="cust-cat active" data-cat="all">All</button>';
    sorted.forEach(([key, cat]) => {
      const btn = document.createElement('button');
      btn.className = 'cust-cat';
      btn.dataset.cat = key;
      btn.textContent = cat.label;
      container.appendChild(btn);
    });

    container.querySelectorAll('.cust-cat').forEach(btn => {
      btn.addEventListener('click', () => {
        container.querySelectorAll('.cust-cat').forEach(b => b.classList.remove('active'));
        btn.classList.add('active');
        refreshOutfitGrid(btn.dataset.cat);
      });
    });
  }

  function refreshOutfitGrid(filterCat) {
    const grid = document.getElementById('cust-outfit-grid');
    if (!grid) return;

    const outfits = _configData?.outfits?.outfits || {};
    grid.innerHTML = '';

    // Fallback to known outfit names if no config
    const outfitList = Object.keys(outfits).length > 0
      ? Object.entries(outfits)
      : Object.keys(window.CharModels?.OUTFIT_MAP || {}).map(k => [k, { label: k, emoji: '', category: 'casual' }]);

    outfitList.forEach(([name, def]) => {
      const category = def.category || 'casual';
      if (filterCat && filterCat !== 'all' && category !== filterCat) return;

      const btn = document.createElement('button');
      btn.className = 'cust-outfit-btn';
      btn.dataset.outfit = name;
      btn.innerHTML = `<span class="outfit-emoji">${def.emoji || '👔'}</span><span class="outfit-name">${def.label || name}</span>`;
      btn.addEventListener('click', () => selectOutfit(name));
      grid.appendChild(btn);
    });
  }

  function populatePalettes() {
    const skinPalette = document.getElementById('cust-skin-palette');
    const hairPalette = document.getElementById('cust-hair-palette');
    const eyePalette = document.getElementById('cust-eye-palette');

    const skinTones = _configData?.characters?.skin_tones || window.CharModels?.SKIN_TONES || {};
    const hairColors = _configData?.characters?.hair_colors || window.CharModels?.HAIR_COLORS || {};
    const eyeColors = _configData?.characters?.eye_colors || {};

    if (skinPalette) {
      skinPalette.innerHTML = '';
      Object.entries(skinTones).forEach(([name, hex]) => {
        const swatch = createSwatch(name, hex, 'skin');
        skinPalette.appendChild(swatch);
      });
    }

    if (hairPalette) {
      hairPalette.innerHTML = '';
      Object.entries(hairColors).forEach(([name, hex]) => {
        const swatch = createSwatch(name, hex, 'hair_color');
        hairPalette.appendChild(swatch);
      });
    }

    if (eyePalette) {
      eyePalette.innerHTML = '';
      Object.entries(eyeColors).forEach(([name, hex]) => {
        const swatch = createSwatch(name, hex, 'eye_color');
        eyePalette.appendChild(swatch);
      });
    }
  }

  function createSwatch(name, hex, type) {
    const color = typeof hex === 'string' ? hex.replace('0x', '#') : '#' + hex.toString(16).padStart(6, '0');
    const el = document.createElement('button');
    el.className = 'cust-swatch';
    el.style.backgroundColor = color;
    el.title = name;
    el.addEventListener('click', () => setAppearance(type, name));
    return el;
  }

  // ═══════════════════════════════════════════════════════════════════
  //  ACTIONS
  // ═══════════════════════════════════════════════════════════════════

  function selectOutfit(outfitName) {
    if (!_selectedCharId) return;

    fetch('/api/character/outfit', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ character_id: _selectedCharId, outfit: outfitName }),
    }).catch(console.error);

    // Highlight selected
    document.querySelectorAll('.cust-outfit-btn').forEach(btn => {
      btn.classList.toggle('selected', btn.dataset.outfit === outfitName);
    });
  }

  function applyColors() {
    if (!_selectedCharId) return;

    const primary = document.getElementById('cust-color-primary').value;
    const accent = document.getElementById('cust-color-accent').value;

    fetch('/api/character/outfit/color', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        character_id: _selectedCharId,
        color: primary,
        accent: accent,
      }),
    }).catch(console.error);

    // Also apply locally for instant preview
    const entry = window.CharacterBridge?.getCharacter(_selectedCharId);
    if (entry && entry.model.clothingGroup) {
      const hexPrimary = parseInt(primary.replace('#', ''), 16);
      const hexAccent = parseInt(accent.replace('#', ''), 16);
      entry.model.clothingGroup.traverse(child => {
        if (child.material) {
          child.material.color.setHex(hexPrimary);
        }
      });
    }
  }

  function setAppearance(key, value) {
    if (!_selectedCharId) return;

    const body = { character_id: _selectedCharId };
    body[key] = value;

    fetch('/api/character/appearance', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body),
    }).catch(console.error);
  }

  // ═══════════════════════════════════════════════════════════════════
  //  DRAGGABLE
  // ═══════════════════════════════════════════════════════════════════

  function makeDraggable(el, handle) {
    let isDragging = false;
    let startX, startY, origX, origY;

    handle.style.cursor = 'grab';

    handle.addEventListener('mousedown', (e) => {
      isDragging = true;
      startX = e.clientX;
      startY = e.clientY;
      const rect = el.getBoundingClientRect();
      origX = rect.left;
      origY = rect.top;
      handle.style.cursor = 'grabbing';
      e.preventDefault();
    });

    document.addEventListener('mousemove', (e) => {
      if (!isDragging) return;
      const dx = e.clientX - startX;
      const dy = e.clientY - startY;
      el.style.left = (origX + dx) + 'px';
      el.style.top = (origY + dy) + 'px';
      el.style.right = 'auto';
    });

    document.addEventListener('mouseup', () => {
      isDragging = false;
      handle.style.cursor = 'grab';
    });
  }

  // ═══════════════════════════════════════════════════════════════════
  //  STYLES
  // ═══════════════════════════════════════════════════════════════════

  const CUSTOMIZER_CSS = `
    #ph-customizer {
      position: fixed;
      top: 80px;
      right: 20px;
      width: 320px;
      max-height: 80vh;
      background: rgba(10, 10, 30, 0.95);
      border: 1px solid rgba(102, 126, 234, 0.4);
      border-radius: 12px;
      box-shadow: 0 8px 32px rgba(0, 0, 0, 0.6), 0 0 20px rgba(102, 126, 234, 0.15);
      z-index: 10000;
      font-family: 'Segoe UI', system-ui, sans-serif;
      color: #e0e0e0;
      overflow: hidden;
      display: none;
      backdrop-filter: blur(12px);
    }
    .cust-header {
      display: flex;
      justify-content: space-between;
      align-items: center;
      padding: 10px 14px;
      background: rgba(102, 126, 234, 0.15);
      border-bottom: 1px solid rgba(102, 126, 234, 0.3);
    }
    .cust-title {
      font-size: 14px;
      font-weight: 600;
      letter-spacing: 0.5px;
    }
    .cust-close {
      background: none;
      border: none;
      color: #888;
      font-size: 16px;
      cursor: pointer;
      padding: 2px 6px;
      border-radius: 4px;
    }
    .cust-close:hover { color: #ff6b9d; background: rgba(255,107,157,0.1); }
    .cust-body {
      padding: 12px;
      overflow-y: auto;
      max-height: calc(80vh - 50px);
    }
    .cust-char-select {
      margin-bottom: 10px;
    }
    .cust-char-select label {
      font-size: 11px;
      color: #888;
      text-transform: uppercase;
      letter-spacing: 1px;
      display: block;
      margin-bottom: 4px;
    }
    .cust-char-select select {
      width: 100%;
      padding: 6px 8px;
      background: rgba(30, 30, 60, 0.8);
      border: 1px solid rgba(102, 126, 234, 0.3);
      border-radius: 6px;
      color: #e0e0e0;
      font-size: 13px;
    }
    .cust-tabs {
      display: flex;
      gap: 2px;
      margin-bottom: 10px;
      background: rgba(20, 20, 40, 0.5);
      border-radius: 8px;
      padding: 2px;
    }
    .cust-tab {
      flex: 1;
      padding: 6px 8px;
      background: none;
      border: none;
      color: #888;
      font-size: 12px;
      cursor: pointer;
      border-radius: 6px;
      transition: all 0.2s;
    }
    .cust-tab.active {
      background: rgba(102, 126, 234, 0.25);
      color: #e0e0e0;
    }
    .cust-tab:hover { color: #ccc; }
    .cust-outfit-categories {
      display: flex;
      flex-wrap: wrap;
      gap: 4px;
      margin-bottom: 8px;
    }
    .cust-cat {
      padding: 4px 10px;
      background: rgba(30, 30, 60, 0.5);
      border: 1px solid rgba(102, 126, 234, 0.2);
      border-radius: 12px;
      color: #aaa;
      font-size: 11px;
      cursor: pointer;
      transition: all 0.2s;
    }
    .cust-cat.active {
      background: rgba(102, 126, 234, 0.3);
      border-color: rgba(102, 126, 234, 0.5);
      color: #e0e0e0;
    }
    .cust-cat:hover { border-color: rgba(102, 126, 234, 0.4); color: #ccc; }
    .cust-outfit-grid {
      display: grid;
      grid-template-columns: repeat(3, 1fr);
      gap: 6px;
    }
    .cust-outfit-btn {
      display: flex;
      flex-direction: column;
      align-items: center;
      padding: 8px 4px;
      background: rgba(30, 30, 60, 0.4);
      border: 1px solid rgba(102, 126, 234, 0.15);
      border-radius: 8px;
      color: #ccc;
      cursor: pointer;
      transition: all 0.2s;
    }
    .cust-outfit-btn:hover {
      background: rgba(102, 126, 234, 0.2);
      border-color: rgba(102, 126, 234, 0.4);
    }
    .cust-outfit-btn.selected {
      background: rgba(102, 126, 234, 0.3);
      border-color: #667eea;
      color: #fff;
    }
    .outfit-emoji { font-size: 20px; margin-bottom: 2px; }
    .outfit-name { font-size: 10px; text-align: center; line-height: 1.2; }
    .cust-color-row {
      display: flex;
      align-items: center;
      justify-content: space-between;
      margin-bottom: 10px;
    }
    .cust-color-row label {
      font-size: 12px;
      color: #aaa;
    }
    .cust-color-row input[type="color"] {
      width: 50px;
      height: 30px;
      border: 1px solid rgba(102, 126, 234, 0.3);
      border-radius: 6px;
      background: rgba(20, 20, 40, 0.8);
      cursor: pointer;
    }
    .cust-apply-btn {
      width: 100%;
      padding: 8px;
      background: linear-gradient(135deg, #667eea, #764ba2);
      border: none;
      border-radius: 8px;
      color: #fff;
      font-size: 13px;
      font-weight: 600;
      cursor: pointer;
      transition: opacity 0.2s;
    }
    .cust-apply-btn:hover { opacity: 0.85; }
    .cust-palette-section {
      margin-bottom: 12px;
    }
    .cust-palette-section label {
      font-size: 11px;
      color: #888;
      text-transform: uppercase;
      letter-spacing: 1px;
      display: block;
      margin-bottom: 6px;
    }
    .cust-palette {
      display: flex;
      flex-wrap: wrap;
      gap: 4px;
    }
    .cust-swatch {
      width: 28px;
      height: 28px;
      border-radius: 50%;
      border: 2px solid rgba(255,255,255,0.1);
      cursor: pointer;
      transition: all 0.2s;
    }
    .cust-swatch:hover {
      border-color: rgba(102, 126, 234, 0.8);
      transform: scale(1.15);
      box-shadow: 0 0 8px rgba(102, 126, 234, 0.4);
    }
  `;

  // ═══════════════════════════════════════════════════════════════════
  //  PUBLIC API
  // ═══════════════════════════════════════════════════════════════════

  window.PenthouseCustomizer = {
    open,
    close,
    toggle,
    isOpen: () => _isOpen,
  };

})();
