/**
 * Penthouse Model Import — GLB / VRM / GLTF model upload & assignment UI.
 *
 * Exposes window.PenthouseModelImport with:
 *   .toggle()          – show/hide the panel
 *   .show() / .hide()  – explicit open/close
 *   .refresh()         – reload library from server
 *
 * Depends on: Three.js r128 (window.THREE), CharacterBridge (optional).
 * GLTFLoader loaded on-demand from CDN.
 */
(function () {
  'use strict';

  /* ── Constants ────────────────────────────────────────────────── */
  var ALLOWED_EXT = ['glb', 'vrm', 'gltf'];
  var MAX_MB = 50;
  var GLTF_LOADER_URL = 'https://cdn.jsdelivr.net/npm/three@0.128.0/examples/js/loaders/GLTFLoader.js';

  /* ── State ────────────────────────────────────────────────────── */
  var panel = null;
  var visible = false;
  var library = [];       // [{id, filename, format, size_mb, uploaded_at, ...}]
  var assignments = {};   // character_id → model_id
  var previewRenderers = {};  // model_id → {renderer, scene, camera, animId}
  var gltfLoaderReady = false;
  var gltfLoaderLoading = false;

  /* ── GLTFLoader Bootstrap ─────────────────────────────────────── */
  function ensureGLTFLoader(cb) {
    if (gltfLoaderReady || (window.THREE && window.THREE.GLTFLoader)) {
      gltfLoaderReady = true;
      if (cb) cb();
      return;
    }
    if (gltfLoaderLoading) {
      var iv = setInterval(function () {
        if (gltfLoaderReady) { clearInterval(iv); if (cb) cb(); }
      }, 100);
      return;
    }
    gltfLoaderLoading = true;
    var s = document.createElement('script');
    s.src = GLTF_LOADER_URL;
    s.onload = function () {
      gltfLoaderReady = true;
      gltfLoaderLoading = false;
      if (cb) cb();
    };
    s.onerror = function () {
      console.error('[ModelImport] Failed to load GLTFLoader from CDN');
      gltfLoaderLoading = false;
    };
    document.head.appendChild(s);
  }

  /* ── Utility ──────────────────────────────────────────────────── */
  function el(tag, attrs, children) {
    var e = document.createElement(tag);
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
    var parts = name.split('.');
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
    var ext = fileExtension(file.name);
    if (ALLOWED_EXT.indexOf(ext) === -1) {
      setStatus('Unsupported format: .' + ext, true);
      return;
    }
    if (file.size > MAX_MB * 1048576) {
      setStatus('File too large (' + formatBytes(file.size) + '). Max ' + MAX_MB + ' MB.', true);
      return;
    }

    var form = new FormData();
    form.append('file', file);

    setStatus('Uploading ' + file.name + '…');
    showProgress(0);

    var xhr = new XMLHttpRequest();
    xhr.open('POST', '/api/models/upload');
    xhr.upload.onprogress = function (e) {
      if (e.lengthComputable) showProgress(Math.round(e.loaded / e.total * 100));
    };
    xhr.onload = function () {
      hideProgress();
      try {
        var res = JSON.parse(xhr.responseText);
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
    var header = el('div', { className: 'ph-mi-header' }, [
      el('span', { className: 'ph-mi-title' }, '📦 Model Library'),
      el('button', {
        className: 'ph-mi-close',
        onClick: function () { hide(); },
        title: 'Close',
      }, '×'),
    ]);
    panel.appendChild(header);

    // Status bar
    var statusBar = el('div', { id: 'ph-mi-status', className: 'ph-mi-status' });
    panel.appendChild(statusBar);

    // Progress bar
    var progressWrap = el('div', {
      id: 'ph-mi-progress-wrap',
      className: 'ph-mi-progress-wrap',
      style: { display: 'none' },
    }, [
      el('div', { id: 'ph-mi-progress-bar', className: 'ph-mi-progress-bar' }),
    ]);
    panel.appendChild(progressWrap);

    // Drop zone
    var dropZone = el('div', {
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
    var fileInput = el('input', {
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
    var libSection = el('div', { className: 'ph-mi-lib-section' }, [
      el('div', { className: 'ph-mi-lib-header' }, 'Uploaded Models'),
      el('div', { id: 'ph-mi-lib-grid', className: 'ph-mi-lib-grid' }),
    ]);
    panel.appendChild(libSection);

    document.body.appendChild(panel);
    return panel;
  }

  /* ── Status / progress helpers ─────────────────────────────────── */
  function setStatus(msg, isError) {
    var bar = document.getElementById('ph-mi-status');
    if (!bar) return;
    bar.textContent = msg;
    bar.style.color = isError ? '#ef4444' : '#a78bfa';
    if (msg) {
      clearTimeout(bar._tid);
      bar._tid = setTimeout(function () { bar.textContent = ''; }, 5000);
    }
  }

  function showProgress(pct) {
    var wrap = document.getElementById('ph-mi-progress-wrap');
    var bar = document.getElementById('ph-mi-progress-bar');
    if (wrap) wrap.style.display = 'block';
    if (bar) bar.style.width = pct + '%';
  }

  function hideProgress() {
    var wrap = document.getElementById('ph-mi-progress-wrap');
    var bar = document.getElementById('ph-mi-progress-bar');
    if (wrap) wrap.style.display = 'none';
    if (bar) bar.style.width = '0%';
  }

  /* ── 3D Preview ────────────────────────────────────────────────── */
  function createPreview(canvas, modelMeta) {
    if (!window.THREE || !gltfLoaderReady) return;

    var w = canvas.clientWidth || 120;
    var h = canvas.clientHeight || 120;

    var renderer = new THREE.WebGLRenderer({ canvas: canvas, alpha: true, antialias: true });
    renderer.setSize(w, h);
    renderer.setPixelRatio(Math.min(window.devicePixelRatio, 2));
    renderer.outputEncoding = THREE.sRGBEncoding;

    var scene = new THREE.Scene();

    var camera = new THREE.PerspectiveCamera(40, w / h, 0.01, 50);
    camera.position.set(0, 1.2, 3);
    camera.lookAt(0, 0.8, 0);

    // Lighting
    var amb = new THREE.AmbientLight(0xffffff, 0.6);
    scene.add(amb);
    var dir = new THREE.DirectionalLight(0xffffff, 0.8);
    dir.position.set(2, 3, 2);
    scene.add(dir);
    var rim = new THREE.DirectionalLight(0x8888ff, 0.3);
    rim.position.set(-2, 1, -2);
    scene.add(rim);

    // Load model
    var loader = new THREE.GLTFLoader();
    var fileUrl = '/api/models/file/' + modelMeta.stored_as;

    loader.load(fileUrl, function (gltf) {
      var model = gltf.scene;

      // Auto-fit: compute bounding box and normalize
      var box = new THREE.Box3().setFromObject(model);
      var size = new THREE.Vector3();
      var center = new THREE.Vector3();
      box.getSize(size);
      box.getCenter(center);

      var maxDim = Math.max(size.x, size.y, size.z);
      if (maxDim > 0) {
        var targetHeight = 2.0;
        var s = targetHeight / maxDim;
        model.scale.setScalar(s);
      }

      // Center model
      model.position.sub(center.multiplyScalar(model.scale.x));
      model.position.y -= box.min.y * model.scale.y;

      scene.add(model);

      // Spin animation
      var animId;
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
    var pr = previewRenderers[modelId];
    if (pr) {
      if (pr.animId) cancelAnimationFrame(pr.animId);
      if (pr.renderer) pr.renderer.dispose();
      delete previewRenderers[modelId];
    }
  }

  /* ── Build model card ──────────────────────────────────────────── */
  function buildModelCard(model) {
    var card = el('div', { className: 'ph-mi-card' });

    // Preview canvas
    var canvasWrap = el('div', { className: 'ph-mi-preview-wrap' });
    var canvas = el('canvas', {
      className: 'ph-mi-preview-canvas',
      width: '120',
      height: '120',
    });
    canvasWrap.appendChild(canvas);
    card.appendChild(canvasWrap);

    // Info
    var info = el('div', { className: 'ph-mi-card-info' }, [
      el('div', { className: 'ph-mi-card-name', title: model.filename },
        model.filename.length > 20 ? model.filename.slice(0, 18) + '…' : model.filename
      ),
      el('div', { className: 'ph-mi-card-meta' },
        model.format.toUpperCase() + ' · ' + formatBytes(model.size_bytes)
      ),
    ]);
    card.appendChild(info);

    // Character assignment dropdown
    var assignWrap = el('div', { className: 'ph-mi-assign-wrap' });
    var select = el('select', { className: 'ph-mi-assign-select select-input-sm' });
    select.appendChild(el('option', { value: '' }, '— assign to —'));

    // Populate with known characters
    var chars = getCharacterList();
    chars.forEach(function (c) {
      var opt = el('option', { value: c.id }, c.name || c.id);
      if (assignments[c.id] === model.id) opt.selected = true;
      select.appendChild(opt);
    });

    select.addEventListener('change', function () {
      var cid = select.value;
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
    var actions = el('div', { className: 'ph-mi-card-actions' });

    // Delete button
    var delBtn = el('button', {
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
      var ids = CharacterBridge.getCharacterIds();
      return ids.map(function (id) {
        var entry = CharacterBridge.getCharacter(id);
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
    if (!window.THREE || !gltfLoaderReady) {
      ensureGLTFLoader(function () { applyModelToCharacter(charId, modelMeta); });
      return;
    }

    var entry = CharacterBridge.getCharacter(charId);
    if (!entry || !entry.model) {
      console.warn('[ModelImport] Character not in scene:', charId);
      return;
    }

    var loader = new THREE.GLTFLoader();
    var fileUrl = '/api/models/file/' + modelMeta.stored_as;

    loader.load(fileUrl, function (gltf) {
      var importedScene = gltf.scene;
      var group = entry.model.group;

      // Remove existing procedural children (keep name label and bubble)
      var toRemove = [];
      group.children.forEach(function (child) {
        if (child.isSprite) return; // keep labels / bubbles
        toRemove.push(child);
      });
      toRemove.forEach(function (child) { group.remove(child); });

      // Auto-scale imported model to character height
      var box = new THREE.Box3().setFromObject(importedScene);
      var size = new THREE.Vector3();
      box.getSize(size);
      var targetH = modelMeta.height || 1.7;
      if (size.y > 0) {
        var s = targetH / size.y;
        importedScene.scale.setScalar(s);
      }

      // Recenter
      box.setFromObject(importedScene);
      var center = new THREE.Vector3();
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
        var mixer = new THREE.AnimationMixer(importedScene);
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
    var grid = document.getElementById('ph-mi-lib-grid');
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
    var btn = document.getElementById('ph-model-import-toggle');
    if (btn) btn.classList.add('active');
  }

  function hide() {
    if (panel) panel.classList.remove('open');
    visible = false;
    var btn = document.getElementById('ph-model-import-toggle');
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
    var ids = typeof CharacterBridge.getCharacterIds === 'function'
      ? CharacterBridge.getCharacterIds() : [];
    ids.forEach(function (cid) {
      var entry = CharacterBridge.getCharacter(cid);
      if (entry && entry.model && entry.model._importedMixer) {
        entry.model._importedMixer.update(dt);
      }
    });
  }

  /* ── Socket.IO listener for model assignment broadcasts ────────── */
  function wireSocketIO() {
    if (typeof io === 'undefined') return;
    try {
      var socket = io();
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
