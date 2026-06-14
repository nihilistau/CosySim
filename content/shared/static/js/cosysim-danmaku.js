/**
 * Danmaku Overlay — Floating bullet comments for CosySim
 * ======================================================
 *
 * Creates a fixed overlay div with pointer-events: none so it never
 * blocks interaction.  Messages float right-to-left in 5 staggered
 * lanes.  Listens for 'danmaku_msg' SocketIO events from the
 * SpectatorBus.
 *
 * Toggle visibility with F7 key.
 *
 * Version: v1.51.0 [2026-03-25]
 * Author:  CosySim Team
 *
 * Change Log:
 *     v1.51.0 [2026-03-25] — Initial implementation: overlay, lane
 *                              cycling, CSS animation, F7 toggle,
 *                              auto-init on DOMContentLoaded
 *
 * CONNECTS: SpectatorBus (via SocketIO 'danmaku_msg' event)
 * CALLED BY: neon_base.html (auto-init), any scene template
 * EMITS:     DOM mutations (overlay div + animated message spans)
 */

// ──── Constants ──────────────────────────────────────────────────────
const DANMAKU_LANE_COUNT = 5;
const DANMAKU_LANE_HEIGHT = 30;     // px between lanes
const DANMAKU_TOP_OFFSET = 60;      // px from viewport top (clear navbar)
const DANMAKU_DEFAULT_TTL = 8;      // seconds for animation duration
const DANMAKU_MAX_VISIBLE = 40;     // max simultaneous messages on screen
const DANMAKU_STORAGE_KEY = 'cosysim-danmaku-enabled';

// ──── CosyDanmaku Class ─────────────────────────────────────────────

class CosyDanmaku {
  /**
   * @param {object} socket - Socket.IO client instance
   */
  constructor(socket) {
    this._socket = socket;
    this._overlay = null;
    this._enabled = this._loadState();
    this._laneIndex = 0;
    this._activeCount = 0;

    this._createOverlay();
    this._bindSocket();
    this._bindHotkey();
  }

  // ── Overlay DOM ──────────────────────────────────────────────────

  /**
   * Create the fixed overlay container.
   * v1.51.0 [2026-03-25] — Overlay with pointer-events: none, z-index 9990
   */
  _createOverlay() {
    // Avoid duplicate overlays
    const existing = document.getElementById('cosy-danmaku-overlay');
    if (existing) {
      this._overlay = existing;
      return;
    }

    const overlay = document.createElement('div');
    overlay.id = 'cosy-danmaku-overlay';
    overlay.className = 'cosy-danmaku-overlay';
    if (!this._enabled) {
      overlay.style.display = 'none';
    }
    document.body.appendChild(overlay);
    this._overlay = overlay;
  }

  // ── Message Rendering ────────────────────────────────────────────

  /**
   * Add a floating danmaku message to the overlay.
   * v1.51.0 [2026-03-25] — CSS animation right→left, lane positioning
   *
   * @param {string} text  - Message text to display
   * @param {string} color - CSS color value (hex or named)
   * @param {number} lane  - Lane index (0-based, cycles through DANMAKU_LANE_COUNT)
   * @param {number} ttl   - Animation duration in seconds
   */
  _addMessage(text, color, lane, ttl) {
    if (!this._overlay || !this._enabled) return;
    if (this._activeCount >= DANMAKU_MAX_VISIBLE) return;

    const msg = document.createElement('span');
    msg.className = 'cosy-danmaku-msg';
    msg.textContent = text;
    msg.style.color = color || '#e2e8f0';
    msg.style.top = `${DANMAKU_TOP_OFFSET + (lane * DANMAKU_LANE_HEIGHT)}px`;
    msg.style.animationDuration = `${ttl || DANMAKU_DEFAULT_TTL}s`;

    this._overlay.appendChild(msg);
    this._activeCount++;

    // Remove after animation completes
    const cleanup = () => {
      if (msg.parentNode) {
        msg.parentNode.removeChild(msg);
      }
      this._activeCount--;
    };
    msg.addEventListener('animationend', cleanup, { once: true });

    // Safety fallback: remove after ttl + 1s even if animationend doesn't fire
    setTimeout(cleanup, ((ttl || DANMAKU_DEFAULT_TTL) + 1) * 1000);
  }

  /**
   * Cycle through lanes to distribute messages evenly.
   * @returns {number} The next lane index
   */
  _getNextLane() {
    const lane = this._laneIndex;
    this._laneIndex = (this._laneIndex + 1) % DANMAKU_LANE_COUNT;
    return lane;
  }

  // ── SocketIO Binding ─────────────────────────────────────────────

  /**
   * Listen for danmaku_msg events from the SpectatorBus relay.
   * v1.51.0 [2026-03-25] — SocketIO listener for spectator feed
   */
  _bindSocket() {
    if (!this._socket) return;

    this._socket.on('danmaku_msg', (data) => {
      const text = data.text || '';
      const color = data.color || '#e2e8f0';
      const ttl = data.ttl_secs || DANMAKU_DEFAULT_TTL;
      const lane = this._getNextLane();
      this._addMessage(text, color, lane, ttl);
    });
  }

  // ── Hotkey Toggle ────────────────────────────────────────────────

  /**
   * Bind F7 key to toggle danmaku overlay visibility.
   * v1.51.0 [2026-03-25] — Persists state to localStorage
   */
  _bindHotkey() {
    document.addEventListener('keydown', (e) => {
      if (e.key === 'F7') {
        e.preventDefault();
        this.toggle();
      }
    });
  }

  // ── Public API ───────────────────────────────────────────────────

  /**
   * Toggle the danmaku overlay on/off.
   */
  toggle() {
    this._enabled = !this._enabled;
    if (this._overlay) {
      this._overlay.style.display = this._enabled ? '' : 'none';
    }
    this._saveState();
  }

  /**
   * Check if danmaku is currently enabled.
   * @returns {boolean}
   */
  get enabled() {
    return this._enabled;
  }

  /**
   * Programmatically push a message (for local events, not just SocketIO).
   * @param {string} text
   * @param {string} color
   * @param {number} [ttl]
   */
  push(text, color, ttl) {
    const lane = this._getNextLane();
    this._addMessage(text, color || '#e2e8f0', lane, ttl || DANMAKU_DEFAULT_TTL);
  }

  /**
   * Remove overlay and unbind events.
   */
  destroy() {
    if (this._overlay && this._overlay.parentNode) {
      this._overlay.parentNode.removeChild(this._overlay);
    }
    this._overlay = null;
  }

  // ── Persistence ──────────────────────────────────────────────────

  _loadState() {
    try {
      const stored = localStorage.getItem(DANMAKU_STORAGE_KEY);
      // Default to enabled if no stored preference
      return stored === null ? true : stored === '1';
    } catch {
      return true;
    }
  }

  _saveState() {
    try {
      localStorage.setItem(DANMAKU_STORAGE_KEY, this._enabled ? '1' : '0');
    } catch {
      // localStorage may be unavailable
    }
  }
}

// ──── Auto-Init ──────────────────────────────────────────────────────
// v1.51.0 [2026-03-25] — Auto-initialize if Socket.IO is present
if (typeof io !== 'undefined') {
  document.addEventListener('DOMContentLoaded', () => {
    const socket = io();
    window.cosyDanmaku = new CosyDanmaku(socket);
  });
}
