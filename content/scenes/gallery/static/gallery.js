/**
 * THE OBSCURA — Gallery Scene v0.68 Dark Renaissance
 * ObscuraScene: Socket.IO wiring, gallery rendering, detail panel, private viewing, commissions.
 */
'use strict';

class ObscuraScene {
  constructor () {
    /** @type {ReturnType<import('socket.io-client')['io']>} */
    this.socket = null;
    /** @type {Array<Object>} */
    this.pieces = [];
    /** @type {string|null} */
    this.currentPieceId = null;
    /** @type {Set<string>} */
    this.unlockedPieces = new Set();
    this._commissionOpen = false;
  }

  // ── Lifecycle ─────────────────────────────────────────────

  init () {
    this._setupUI();
    this._setupSocket();
    this.loadGallery();
    this._initParticles();
  }

  // ── Socket.IO ─────────────────────────────────────────────

  _setupSocket () {
    this.socket = io();

    this.socket.on('connect', () => {
      this.socket.emit('get_gallery_state');
    });

    this.socket.on('gallery_state', (data) => this._onGalleryState(data));

    this.socket.on('piece_detail', (data) => this._openDetailPanel(data));
    this.socket.on('piece_not_found', (data) => {
      this._showNotification('Piece not found in the collection.', 'denied');
    });

    this.socket.on('private_viewing_granted', (data) => this._onPrivateViewingGranted(data));
    this.socket.on('private_viewing_denied',  (data) => this._onPrivateViewingDenied(data));

    this.socket.on('commission_complete', (data) => this._onCommissionComplete(data));
    this.socket.on('commission_error',    (data) => {
      this._showNotification(data.reason || 'Commission failed.', 'denied');
    });
  }

  // ── Public API ────────────────────────────────────────────

  /** Fetch full piece list from the REST endpoint and render. */
  loadGallery () {
    fetch('/api/gallery/pieces')
      .then((r) => r.json())
      .then((data) => {
        if (data.pieces)       this._renderPieces(data.pieces);
        if (data.curator_mood) this._updateCuratorMood(data.curator_mood);
        const loading = document.getElementById('gallery-loading');
        if (loading) loading.remove();
      })
      .catch((err) => {
        console.warn('[ObscuraScene] Gallery load error:', err);
        const loading = document.getElementById('gallery-loading');
        if (loading) loading.textContent = 'The gallery is dark tonight.';
      });
  }

  /** Emit view_piece and open the detail panel when the server responds. */
  viewPiece (pieceId) {
    this.currentPieceId = pieceId;
    this.socket.emit('view_piece', { piece_id: pieceId });
  }

  /** Emit get_private_viewing for an adult-gated piece. */
  requestPrivateViewing (pieceId) {
    if (!pieceId) return;
    this.currentPieceId = pieceId;
    this.socket.emit('get_private_viewing', { piece_id: pieceId });
  }

  /** Commission a new work via the socket. Falls back to form values. */
  commissionWork (description, intensity) {
    description = description
      || document.getElementById('commission-description')?.value?.trim()
      || '';
    intensity = intensity
      || parseInt(document.getElementById('commission-intensity')?.value || '1', 10);

    if (!description) {
      this._showNotification('A description is required to commission work.', 'denied');
      return;
    }

    this.socket.emit('commission_work', { description, intensity });

    const status = document.getElementById('commission-status');
    if (status) status.textContent = 'Commission submitted to the curator\u2026';
  }

  /** Send a free-form chat message (for future chat integration). */
  sendMessage (text) {
    if (!text || !text.trim()) return;
    this.socket.emit('chat_message', { text: text.trim() });
  }

  /** Close the slide-in detail panel. */
  closeDetailPanel () {
    document.getElementById('detail-panel')?.classList.remove('open');
    document.getElementById('overlay-backdrop')?.classList.remove('active');
  }

  /** Toggle the commission form. */
  toggleCommission () {
    this._commissionOpen = !this._commissionOpen;
    document.getElementById('commission-form')?.classList.toggle('open', this._commissionOpen);
  }

  // ── Rendering ─────────────────────────────────────────────

  _renderPieces (pieces) {
    this.pieces = pieces;
    const floor = document.getElementById('gallery-floor');
    if (!floor) return;
    // Remove loading state
    const loading = document.getElementById('gallery-loading');
    if (loading) loading.remove();
    // Insert frames
    floor.innerHTML = pieces.map((p, i) => this._frameHtml(p, i)).join('');
  }

  _frameHtml (piece, index) {
    const locked     = piece.adult && !this.unlockedPieces.has(piece.id);
    const blurClass  = locked ? 'private-viewing-blur' : '';
    const bgStyle    = piece.placeholder_gradient
      ? `background: ${piece.placeholder_gradient};`
      : 'background: #0d0814;';
    const imgContent = piece.image_url
      ? `<img src="${this._esc(piece.image_url)}" alt="${this._esc(piece.title)}" loading="lazy">`
      : `<div class="artwork-placeholder" style="${bgStyle}"></div>`;
    const badge      = this._intensityBadge(piece.tags || []);

    return `
<div class="artwork-frame ${blurClass}"
     data-piece-id="${this._esc(piece.id)}"
     onclick="app.viewPiece('${this._esc(piece.id)}')"
     style="animation-delay:${index * 0.07}s"
     role="button"
     tabindex="0"
     aria-label="View ${this._esc(piece.title)}">
  <div class="frame-inner" style="${bgStyle}">
    ${imgContent}
    <div class="spotlight"></div>
    ${badge}
  </div>
  <div class="artwork-title">
    <span class="title-text">${this._esc(piece.title)}</span>
    <span class="title-artist">${this._esc(piece.artist || '')}</span>
  </div>
</div>`.trim();
  }

  _intensityBadge (tags) {
    if (tags.some((t) => t === 'explicit' || t === 'adult:sexual')) {
      return '<span class="intensity-badge explicit">EXPLICIT</span>';
    }
    if (tags.some((t) => t === 'violent' || t === 'adult:violent')) {
      return '<span class="intensity-badge violent">VIOLENT</span>';
    }
    if (tags.includes('disturbing')) {
      return '<span class="intensity-badge disturbing">DISTURBING</span>';
    }
    return '';
  }

  /** Populate and open the detail panel with piece data. */
  _openDetailPanel (piece) {
    const set = (id, text) => {
      const el = document.getElementById(id);
      if (el) el.textContent = text || '';
    };

    set('detail-title',       piece.title);
    set('detail-artist',      piece.artist);
    set('detail-medium',      piece.medium);
    set('detail-description', piece.description);
    set('detail-commentary',  piece.commentary);

    // Background
    const bg = document.getElementById('detail-art-bg');
    if (bg) {
      if (piece.image_url) {
        bg.style.backgroundImage = `url('${this._esc(piece.image_url)}')`;
        bg.style.background = '';
      } else {
        bg.style.backgroundImage = '';
        bg.style.background = piece.placeholder_gradient || '#0d0814';
      }
    }

    // Inline tag badges
    const tagsEl = document.getElementById('detail-tags');
    if (tagsEl) {
      tagsEl.innerHTML = (piece.tags || []).map((t) => {
        const cls = this._tagBadgeClass(t);
        const label = t.replace('adult:', '').toUpperCase();
        return `<span class="intensity-badge ${cls}">${label}</span>`;
      }).join('');
    }

    // Private viewing button
    const pvBtn = document.getElementById('private-viewing-btn');
    if (pvBtn) {
      const showBtn = piece.adult && !this.unlockedPieces.has(piece.id);
      pvBtn.style.display = showBtn ? 'block' : 'none';
      pvBtn.onclick = () => this.requestPrivateViewing(piece.id);
    }

    // Open panel
    document.getElementById('detail-panel')?.classList.add('open');
    document.getElementById('overlay-backdrop')?.classList.add('active');
  }

  _tagBadgeClass (tag) {
    if (tag.includes('sexual') || tag === 'explicit') return 'explicit';
    if (tag.includes('violent'))                       return 'violent';
    return 'disturbing';
  }

  // ── Socket Event Handlers ──────────────────────────────────

  _onGalleryState (data) {
    if (data.pieces)       this._renderPieces(data.pieces);
    if (data.curator_mood) this._updateCuratorMood(data.curator_mood);
  }

  _onPrivateViewingGranted (data) {
    const piece = data.piece || {};
    const id    = piece.id || this.currentPieceId;
    if (id) {
      this.unlockedPieces.add(id);
      const frame = document.querySelector(`[data-piece-id="${this._esc(id)}"]`);
      frame?.classList.remove('private-viewing-blur');
    }
    this._openDetailPanel(piece);
    this._showNotification('Private viewing granted.', 'granted');
  }

  _onPrivateViewingDenied (data) {
    this._showNotification(data.reason || 'Access denied.', 'denied');
  }

  _onCommissionComplete (data) {
    const status = document.getElementById('commission-status');
    if (status) {
      status.textContent = data.url
        ? '\u2713 Commission received \u2014 work will be delivered.'
        : '\u2713 Commission noted by the curator.';
    }
    // If an image URL was returned, append the piece to the gallery floor
    if (data.url) {
      this.pieces.push({
        id:                   `commission_${Date.now()}`,
        title:                (data.description || '').slice(0, 40),
        artist:               'Commissioned',
        medium:               `Intensity ${data.intensity}`,
        description:          data.description || '',
        tags:                 [],
        adult:                data.intensity >= 3,
        image_url:            data.url,
        placeholder_gradient: 'linear-gradient(135deg, #1a0a2e 0%, #2a1a4e 100%)',
      });
      this._renderPieces(this.pieces);
    }
  }

  // ── UI Helpers ────────────────────────────────────────────

  _setupUI () {
    // Backdrop closes detail panel
    document.getElementById('overlay-backdrop')?.addEventListener('click', () =>
      this.closeDetailPanel()
    );
    // Detail close button
    document.getElementById('detail-close')?.addEventListener('click', () =>
      this.closeDetailPanel()
    );
    // Commission toggle
    document.getElementById('commission-toggle')?.addEventListener('click', () =>
      this.toggleCommission()
    );
    // Commission submit
    document.getElementById('commission-submit')?.addEventListener('click', () =>
      this.commissionWork()
    );
    // Escape key
    document.addEventListener('keydown', (e) => {
      if (e.key === 'Escape') this.closeDetailPanel();
    });
    // Keyboard-accessible frames (Enter/Space)
    document.getElementById('gallery-floor')?.addEventListener('keydown', (e) => {
      if (e.key === 'Enter' || e.key === ' ') {
        const frame = e.target.closest('.artwork-frame');
        if (frame) {
          e.preventDefault();
          const id = frame.dataset.pieceId;
          if (id) this.viewPiece(id);
        }
      }
    });
  }

  _updateCuratorMood (mood) {
    const el = document.getElementById('curator-mood');
    if (el) el.textContent = mood;
  }

  _showNotification (message, type) {
    const el = document.createElement('div');
    el.className = `gallery-notification ${type}`;
    el.textContent = message;
    document.body.appendChild(el);
    setTimeout(() => el.remove(), 4500);
  }

  /**
   * Initialise hologram_static particles on the featured strip.
   * Degrades gracefully if cosysim-particles3d.js is not loaded.
   */
  _initParticles () {
    const container = document.getElementById('featured-particles');
    if (!container) return;
    try {
      if (window.CosyParticles3D && typeof window.CosyParticles3D.init === 'function') {
        window.CosyParticles3D.init(container, { color: '#7c3aed', density: 28, speed: 0.35 });
      } else if (window.hologramStatic && typeof window.hologramStatic === 'function') {
        window.hologramStatic(container, { color: '#7c3aed' });
      }
    } catch (_) {
      /* Particles unavailable — degrade gracefully */
    }
  }

  /**
   * Escape HTML entities to prevent XSS injection into innerHTML.
   * @param {string} str
   * @returns {string}
   */
  _esc (str) {
    return String(str || '').replace(/[&<>"']/g, (c) => ({
      '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;',
    }[c]));
  }
}

// ── Bootstrap ──────────────────────────────────────────────────────────────────
const app = new ObscuraScene();
document.addEventListener('DOMContentLoaded', () => app.init());
