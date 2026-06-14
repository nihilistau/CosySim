/**
 * Penthouse Model Import — GLB / VRM / GLTF model upload & assignment UI.
 *
 * Exposes window.PenthouseModelImport with:
 *   .toggle()          – show/hide the panel
 *   .show() / .hide()  – explicit open/close
 *   .refresh()         – reload library from server
 *
 * Depends on: Three.js r184 (window.THREE via three_boot.js — includes
 * GLTFLoader as a vendored addon), CharacterBridge (optional).
 */
(function () {
  'use strict';

  /* ── Constants ────────────────────────────────────────────────── */
  const ALLOWED_EXT = ['glb', 'vrm', 'gltf'];
  const MAX_MB = 50;

  /* ── State ────────────────────────────────────────────────────── */
  let panel = null;
  let visible = false;
  let library = [];       // [{id, filename, format, size_mb, uploaded_at, ...}]
  let assignments = {};   // character_id → model_id
  const previewRenderers = {};  // model_id → {renderer, scene, camera, animId}

  /* ── GLTFLoader availability ──────────────────────────────────── */
  // v1.58.0 [2026-06-11] — GLTFLoader is bundled on window.THREE by
  // three_boot.js (vendored r184 addon); the old on-demand CDN bootstrap
  // (examples/js was deleted upstream in r148) is gone.
  function ensureGLTFLoader(cb) {
    if (window.THREE && window.THREE.GLTFLoader) {
      if (cb) cb();
      return;
    }
    console.error('[ModelImport] THREE.GLTFLoader missing (operation=gltf_loader) — three_boot.js not loaded?');
  }

  /* ── Utility ──────────────────────────────────────────────────── */
  function el(tag, attrs, children) {
    let e = document.createElement(tag);
    if (attrs) {
      Object.keys(attrs).forEach(function (k) {
        if (k === 'className') e.className = attrs[k];
        else if (k === 'style' && typeof attrs[k] === 'object') {
          Object.keys(attrs[k]).forEach(function (sk) { e.style[sk] = attrs[k][sk]; });
        } else if (k.indexOf('on') === 0) e.addEventListener(k.slice(2).toLowerCase(), attrs[k]);
        else e.setAttribute(k, attrs[k]);
      });
    }
    if (children) {
      (Array.isArray(children) ? children : [children]).forEach(function (c) {
        if (typeof c === 'string') e.appendChild(document.createTextNode(c));
        else if (c) e.appendChild(c);
      });
    }
    return e;
  }

  function formatBytes(bytes) {
    if (bytes < 1024) return bytes + ' B';
    if (bytes < 1048576) return (bytes / 1024).toFixed(1) + ' KB';
    return (bytes / 1048576).toFixed(2) + ' MB';
  }

  function fileExtension(name) {
    let parts = name.split('.');
    return parts.length > 1 ? parts[parts.length - 1].toLowerCase() : '';
  }

  /* ── API helpers ──────────────────────────────────────────────── */
  function apiGet(url, cb) {
    fetch(url).then(function (r) { return r.json(); }).then(cb).catch(function (e) {
      console.error('[ModelImport] GET', url, e);
    });
  }

  function apiPost(url, body, cb) {
    fetch(url, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body),
    }).then(function (r) { return r.json(); }).then(cb).catch(function (e) {
      console.error('[ModelImport] POST', url, e);
    });
  }

  function apiDelete(url, cb) {
    fetch(url, { method: 'DELETE' }).then(function (r) { return r.json(); }).then(cb).catch(function (e) {
      console.error('[ModelImport] DELETE', url, e);
    });
  }

  /* ── Upload file ──────────────────────────────────────────────── */
  function uploadFile(file) {
    if (!file) return;
    let ext = fileExtension(file.name);
    if (ALLOWED_EXT.indexOf(ext) === -1) {
      setStatus('Unsupported format: .' + ext, true);
      return;
    }
    if (file.size > MAX_MB * 1048576) {
      setStatus('File too large (' + formatBytes(file.size) + '). Max ' + MAX_MB + ' MB.', true);
      return;
    }

    let form = new FormData();
    form.append('file', file);

    setStatus('Uploading ' + file.name + '…');
    showProgress(0);

    let xhr = new XMLHttpRequest();
    xhr.open('POST', '/api/models/upload');
    xhr.upload.onprogress = function (e) {
      if (e.lengthComputable) showProgress(Math.round(e.loaded / e.total * 100));
    };
    xhr.onload = function () {
      hideProgress();
      try {
        let res = JSON.parse(xhr.responseText);
        if (xhr.status >= 200 && xhr.status < 300 && res.success) {
          setStatus('Uploaded: ' + file.name);
          refreshLibrary();
        } else {
          setStatus(res.error || 'Upload failed', true);
        }
      } catch (e) {
        setStatus('Upload error', true);
      }
    };
    xhr.onerror = function () {
      hideProgress();
      setStatus('Network error during upload', true);
    };
    xhr.send(form);
  }

  /* ── Build panel DOM ──────────────────────────────────────────── */
  function buildPanel() {
    if (panel) return panel;

    panel = el('div', {
      id: 'ph-model-import-panel',
      className: 'ph-model-import-panel',
    });

    // Header
    let header = el('div', { className: 'ph-mi-header' }, [
      el('span', { className: 'ph-mi-title' }, '📦 Model Library'),
      el('button', {
        className: 'ph-mi-close',
        onClick: function () { hide(); },
        title: 'Close',
      }, '×'),
    ]);
    panel.appendChild(header);

    // Status bar
    let statusBar = el('div', { id: 'ph-mi-status', className: 'ph-mi-status' });
    panel.appendChild(statusBar);

    // Progress bar
    let progressWrap = el('div', {
      id: 'ph-mi-progress-wrap',
      className: 'ph-mi-progress-wrap',
      style: { display: 'none' },
    }, [
      el('div', { id: 'ph-mi-progress-bar', className: 'ph-mi-progress-bar' }),
    ]);
    panel.appendChild(progressWrap);

    // Drop zone
    let dropZone = el('div', {
      id: 'ph-mi-dropzone',
      className: 'ph-mi-dropzone',
    }, [
      el('div', { className: 'ph-mi-dropzone-icon' }, '⬆️'),
      el('div', { className: 'ph-mi-dropzone-text' }, 'Drag & drop .glb / .vrm / .gltf'),
      el('div', { className: 'ph-mi-dropzone-sub' }, 'or'),
      el('button', {
        className: 'btn-action ph-mi-browse-btn',
        onClick: function () { fileInput.click(); },
      }, 'Browse Files'),
    ]);

    // Wire up drag events
    dropZone.addEventListener('dragover', function (e) {
      e.preventDefault();
      e.stopPropagation();
      dropZone.classList.add('dragover');
    });
    dropZone.addEventListener('dragleave', function (e) {
      e.preventDefault();
      dropZone.classList.remove('dragover');
    });
    dropZone.addEventListener('drop', function (e) {
      e.preventDefault();
      dropZone.classList.remove('dragover');
      if (e.dataTransfer.files.length) uploadFile(e.dataTransfer.files[0]);
    });

    panel.appendChild(dropZone);

    // Hidden file input
    let fileInput = el('input', {
      type: 'file',
      accept: '.glb,.vrm,.gltf',
      style: { display: 'none' },
    });
    fileInput.addEventListener('change', function () {
      if (fileInput.files.length) uploadFile(fileInput.files[0]);
      fileInput.value = '';
    });
    panel.appendChild(fileInput);

    // Library grid container
    let libSection = el('div', { className: 'ph-mi-lib-section' }, [
      el('div', { className: 'ph-mi-lib-header' }, 'Uploaded Models'),
      el('div', { id: 'ph-mi-lib-grid', className: 'ph-mi-lib-grid' }),
    ]);
    panel.appendChild(libSection);

    document.body.appendChild(panel);
    return panel;
  }

  /* ── Status / progress helpers ─────────────────────────────────── */
  function setStatus(msg, isError) {
    let bar = document.getElementById('ph-mi-status');
    if (!bar) return;
    bar.textContent = msg;
    bar.style.color = isError ? '#ef4444' : '#a78bfa';
    if (msg) {
      clearTimeout(bar._tid);
      bar._tid = setTimeout(function () { bar.textContent = ''; }, 5000);
    }
  }

  function showProgress(pct) {
    let wrap = document.getElementById('ph-mi-progress-wrap');
    let bar = document.getElementById('ph-mi-progress-bar');
    if (wrap) wrap.style.display = 'block';
    if (bar) bar.style.width = pct + '%';
  }

  function hideProgress() {
    let wrap = document.getElementById('ph-mi-progress-wrap');
    let bar = document.getElementById('ph-mi-progress-bar');
    if (wrap) wrap.style.display = 'none';
    if (bar) bar.style.width = '0%';
  }

  /* ── 3D Preview ────────────────────────────────────────────────── */
  function createPreview(canvas, modelMeta) {
    // v1.58.0 [2026-06-11] — r184: GLTFLoader rides on window.THREE;
    // outputEncoding removed (sRGB output is the default); light
    // intensities converted to physical units (×π).
    if (!window.THREE || !window.THREE.GLTFLoader) return;

    let w = canvas.clientWidth || 120;
    let h = canvas.clientHeight || 120;

    let renderer = new THREE.WebGLRenderer({ canvas: canvas, alpha: true, antialias: true });
    renderer.setSize(w, h);
    renderer.setPixelRatio(Math.min(window.devicePixelRatio, 2));

    let scene = new THREE.Scene();

    let camera = new THREE.PerspectiveCamera(40, w / h, 0.01, 50);
    camera.position.set(0, 1.2, 3);
    camera.lookAt(0, 0.8, 0);

    // Lighting (physical units)
    let amb = new THREE.AmbientLight(0xffffff, 0.6 * Math.PI);
    scene.add(amb);
    let dir = new THREE.DirectionalLight(0xffffff, 0.8 * Math.PI);
    dir.position.set(2, 3, 2);
    scene.add(dir);
    let rim = new THREE.DirectionalLight(0x8888ff, 0.3 * Math.PI);
    rim.position.set(-2, 1, -2);
    scene.add(rim);

    // Load model
    let loader = new THREE.GLTFLoader();
    let fileUrl = '/api/models/file/' + modelMeta.stored_as;

    loader.load(fileUrl, function (gltf) {
      let model = gltf.scene;

      // Auto-fit: compute bounding box and normalize
      let box = new THREE.Box3().setFromObject(model);
      let size = new THREE.Vector3();
      let center = new THREE.Vector3();
      box.getSize(size);
      box.getCenter(center);

      let maxDim = Math.max(size.x, size.y, size.z);
      if (maxDim > 0) {
        let targetHeight = 2.0;
        let s = targetHeight / maxDim;
        model.scale.setScalar(s);
      }

      // Center model
      model.position.sub(center.multiplyScalar(model.scale.x));
      model.position.y -= box.min.y * model.scale.y;

      scene.add(model);

      // Spin animation
      let animId;
      function animate() {
        animId = requestAnimationFrame(animate);
        model.rotation.y += 0.008;
        renderer.render(scene, camera);
      }
      animate();

      previewRenderers[modelMeta.id] = {
        renderer: renderer,
        scene: scene,
        camera: camera,
        animId: animId,
      };
    }, undefined, function (err) {
      console.warn('[ModelImport] Preview load failed:', err);
    });
  }

  function destroyPreview(modelId) {
    let pr = previewRenderers[modelId];
    if (pr) {
      if (pr.animId) cancelAnimationFrame(pr.animId);
      if (pr.renderer) pr.renderer.dispose();
      delete previewRenderers[modelId];
    }
  }

  /* ── Build model card ──────────────────────────────────────────── */
  function buildModelCard(model) {
    let card = el('div', { className: 'ph-mi-card' });

    // Preview canvas
    let canvasWrap = el('div', { className: 'ph-mi-preview-wrap' });
    let canvas = el('canvas', {
      className: 'ph-mi-preview-canvas',
      width: '120',
      height: '120',
    });
    canvasWrap.appendChild(canvas);
    card.appendChild(canvasWrap);

    // Info
    let info = el('div', { className: 'ph-mi-card-info' }, [
      el('div', { className: 'ph-mi-card-name', title: model.filename },
        model.filename.length > 20 ? model.filename.slice(0, 18) + '…' : model.filename
      ),
      el('div', { className: 'ph-mi-card-meta' },
        model.format.toUpperCase() + ' · ' + formatBytes(model.size_bytes)
      ),
    ]);
    card.appendChild(info);

    // Character assignment dropdown
    let assignWrap = el('div', { className: 'ph-mi-assign-wrap' });
    let select = el('select', { className: 'ph-mi-assign-select select-input-sm' });
    select.appendChild(el('option', { value: '' }, '— assign to —'));

    // Populate with known characters
    let chars = getCharacterList();
    chars.forEach(function (c) {
      let opt = el('option', { value: c.id }, c.name || c.id);
      if (assignments[c.id] === model.id) opt.selected = true;
      select.appendChild(opt);
    });

    select.addEventListener('change', function () {
      let cid = select.value;
      if (!cid) return;
      apiPost('/api/models/assign', {
        character_id: cid,
        model_id: model.id,
      }, function (res) {
        if (res.success) {
          setStatus('Assigned to ' + cid);
          assignments[cid] = model.id;
          applyModelToCharacter(cid, model);
        } else {
          setStatus(res.error || 'Assignment failed', true);
        }
      });
    });

    assignWrap.appendChild(select);
    card.appendChild(assignWrap);

    // Actions row
    let actions = el('div', { className: 'ph-mi-card-actions' });

    // Delete button
    let delBtn = el('button', {
      className: 'ph-mi-delete-btn',
      title: 'Delete model',
      onClick: function () {
        if (!confirm('Delete "' + model.filename + '"?')) return;
        apiDelete('/api/models/' + model.id, function (res) {
          if (res.success) {
            destroyPreview(model.id);
            setStatus('Deleted: ' + model.filename);
            refreshLibrary();
          } else {
            setStatus(res.error || 'Delete failed', true);
          }
        });
      },
    }, '🗑️');
    actions.appendChild(delBtn);

    card.appendChild(actions);

    // Load 3D preview after card is in DOM
    setTimeout(function () { ensureGLTFLoader(function () { createPreview(canvas, model); }); }, 50);

    return card;
  }

  /* ── Character list from bridge ────────────────────────────────── */
  function getCharacterList() {
    // Try CharacterBridge first
    if (window.CharacterBridge && typeof CharacterBridge.getCharacterIds === 'function') {
      let ids = CharacterBridge.getCharacterIds();
      return ids.map(function (id) {
        let entry = CharacterBridge.getCharacter(id);
        return {
          id: id,
          name: entry && entry.model ? (entry.model.name || id) : id,
        };
      });
    }
    // Fallback: known character IDs
    return [
      { id: 'lola', name: 'Lola' },
      { id: 'viktor', name: 'Viktor' },
      { id: 'aria', name: 'Aria' },
      { id: 'frankie', name: 'Frankie' },
      { id: 'mira', name: 'Mira' },
    ];
  }

  /* ── Apply model to character via CharacterBridge ───────────────── */
  function applyModelToCharacter(charId, modelMeta) {
    if (!window.CharacterBridge) return;
    if (!window.THREE || !window.THREE.GLTFLoader) {  // v1.58.0 — addon on window.THREE
      ensureGLTFLoader(function () { applyModelToCharacter(charId, modelMeta); });
      return;
    }

    let entry = CharacterBridge.getCharacter(charId);
    if (!entry || !entry.model) {
      console.warn('[ModelImport] Character not in scene:', charId);
      return;
    }

    let loader = new THREE.GLTFLoader();
    let fileUrl = '/api/models/file/' + modelMeta.stored_as;

    loader.load(fileUrl, function (gltf) {
      let importedScene = gltf.scene;
      let group = entry.model.group;

      // Remove existing procedural children (keep name label and bubble)
      let toRemove = [];
      group.children.forEach(function (child) {
        if (child.isSprite) return; // keep labels / bubbles
        toRemove.push(child);
      });
      toRemove.forEach(function (child) { group.remove(child); });

      // Auto-scale imported model to character height
      let box = new THREE.Box3().setFromObject(importedScene);
      let size = new THREE.Vector3();
      box.getSize(size);
      let targetH = modelMeta.height || 1.7;
      if (size.y > 0) {
        let s = targetH / size.y;
        importedScene.scale.setScalar(s);
      }

      // Recenter
      box.setFromObject(importedScene);
      let center = new THREE.Vector3();
      box.getCenter(center);
      importedScene.position.x -= center.x;
      importedScene.position.z -= center.z;
      importedScene.position.y -= box.min.y;

      group.add(importedScene);

      // Mark model as imported so animation system skips procedural anim
      entry.model._imported = true;
      entry.model._importedScene = importedScene;
      entry.model._importedMixer = null;

      // Play animations if present
      if (gltf.animations && gltf.animations.length > 0) {
        let mixer = new THREE.AnimationMixer(importedScene);
        gltf.animations.forEach(function (clip) { mixer.clipAction(clip).play(); });
        entry.model._importedMixer = mixer;
      }

      console.debug('[ModelImport] Applied', modelMeta.filename, 'to', charId);
    }, undefined, function (err) {
      console.error('[ModelImport] Failed to load model for character:', err);
      setStatus('Failed to apply model to ' + charId, true);
    });
  }

  /* ── Refresh library from server ───────────────────────────────── */
  function refreshLibrary() {
    apiGet('/api/models/library', function (data) {
      library = data.models || [];
      assignments = data.assignments || {};
      renderLibrary();
    });
  }

  function renderLibrary() {
    let grid = document.getElementById('ph-mi-lib-grid');
    if (!grid) return;

    // Cleanup old previews
    Object.keys(previewRenderers).forEach(destroyPreview);
    grid.innerHTML = '';

    if (library.length === 0) {
      grid.appendChild(el('div', { className: 'ph-mi-empty' }, 'No models uploaded yet'));
      return;
    }

    library.forEach(function (model) {
      grid.appendChild(buildModelCard(model));
    });
  }

  /* ── Panel visibility ──────────────────────────────────────────── */
  function show() {
    buildPanel();
    panel.classList.add('open');
    visible = true;
    refreshLibrary();
    let btn = document.getElementById('ph-model-import-toggle');
    if (btn) btn.classList.add('active');
  }

  function hide() {
    if (panel) panel.classList.remove('open');
    visible = false;
    let btn = document.getElementById('ph-model-import-toggle');
    if (btn) btn.classList.remove('active');
  }

  function toggle() {
    if (visible) hide();
    else show();
  }

  /* ── Animation update hook ─────────────────────────────────────── */
  function animationUpdate(dt) {
    // Update imported model animation mixers
    if (!window.CharacterBridge) return;
    let ids = typeof CharacterBridge.getCharacterIds === 'function'
      ? CharacterBridge.getCharacterIds() : [];
    ids.forEach(function (cid) {
      let entry = CharacterBridge.getCharacter(cid);
      if (entry && entry.model && entry.model._importedMixer) {
        entry.model._importedMixer.update(dt);
      }
    });
  }

  /* ── Socket.IO listener for model assignment broadcasts ────────── */
  function wireSocketIO() {
    if (typeof io === 'undefined') return;
    try {
      let socket = io();
      socket.on('model_assigned', function (data) {
        if (data && data.character_id) {
          if (data.model_id) {
            assignments[data.character_id] = data.model_id;
          } else {
            delete assignments[data.character_id];
          }
          renderLibrary();
        }
      });
    } catch (e) {
      // Socket not available — no-op
    }
  }

  /* ── Init ──────────────────────────────────────────────────────── */
  function init() {
    // Pre-load GLTFLoader
    ensureGLTFLoader();

    // Wire into animation loop if available
    if (window.penthouse3D && typeof penthouse3D.addToAnimationLoop === 'function') {
      penthouse3D.addToAnimationLoop(animationUpdate);
    }

    // Auto-apply assigned models on scene state updates
    if (typeof io !== 'undefined') {
      wireSocketIO();
    }
  }

  // Auto-init when DOM ready
  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', init);
  } else {
    init();
  }

  /* ── Public API ────────────────────────────────────────────────── */
  window.PenthouseModelImport = {
    toggle: toggle,
    show: show,
    hide: hide,
    refresh: refreshLibrary,
    applyModelToCharacter: applyModelToCharacter,
    getAssignments: function () { return Object.assign({}, assignments); },
  };
})();
