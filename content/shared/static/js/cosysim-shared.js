/**
 * CosySim Shared Utilities — cosysim-shared.js
 * =============================================
 * Shared JS components loaded across CosySim scenes.
 *
 * Components:
 *   CosySimNPCBadges — Socket.IO-driven NPC activity badge panel (v72-b2)
 *
 * Usage:
 *   <script src="/shared/js/cosysim-shared.js" defer></script>
 *   <div class="cs-npc-activity-panel"></div>
 */
(function () {
  'use strict';

  /* ── CosySimNPCBadges ────────────────────────────────────────── */

  /**
   * Listens for `npc_activity_update` Socket.IO events and renders
   * `.cs-npc-badge` elements inside any `.cs-npc-activity-panel` on the page.
   *
   * Auto-removes stale badges when NPCs become idle.
   */
  class CosySimNPCBadges {
    constructor() {
      this._badges = {};     // npc_id → {el, timer}
      this._staleMs = 120000; // Remove badge after 2 min of no update
      this._panels  = [];

      this._init();
    }

    _init() {
      if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', () => this._setup());
      } else {
        this._setup();
      }
    }

    _setup() {
      this._panels = Array.from(document.querySelectorAll('.cs-npc-activity-panel'));

      // Connect to Socket.IO if available
      if (typeof window.io === 'function') {
        try {
          const socket = window.io();
          socket.on('npc_activity_update', (data) => this._onUpdate(data));
          socket.on('connect_error', () => {/* fail silently */});
        } catch (e) {
          // Socket.IO unavailable — badges will remain empty until populated
        }
      }
    }

    /**
     * Handle an `npc_activity_update` event.
     * @param {{ npcs: Array<{id: string, activity: string, scene: string}> }} data
     */
    _onUpdate(data) {
      if (!data || !Array.isArray(data.npcs)) return;

      const seen = new Set();

      data.npcs.forEach(npc => {
        const id = npc.id || npc.character_id;
        if (!id) return;
        seen.add(id);

        const activity = npc.activity || 'idle';
        const scene    = npc.scene || npc.location || '';

        if (this._badges[id]) {
          this._updateBadge(id, activity, scene);
        } else {
          this._createBadge(id, activity, scene);
        }
      });

      // Remove badges for NPCs not in this update (went idle)
      Object.keys(this._badges).forEach(id => {
        if (!seen.has(id)) this._removeBadge(id);
      });
    }

    _createBadge(id, activity, scene) {
      const el = document.createElement('div');
      el.className = 'cs-npc-badge';
      el.dataset.npcId   = id;
      el.dataset.activity = this._activityClass(activity);
      el.innerHTML = `
        <span class="badge-name">${_esc(id)}</span>
        <span class="badge-activity">${_esc(activity)}</span>`;

      this._panels.forEach(panel => panel.appendChild(el.cloneNode(true)));

      const timer = setTimeout(() => this._removeBadge(id), this._staleMs);
      this._badges[id] = { el, timer };
    }

    _updateBadge(id, activity, scene) {
      clearTimeout(this._badges[id].timer);

      this._panels.forEach(panel => {
        const el = panel.querySelector(`[data-npc-id="${CSS.escape(id)}"]`);
        if (!el) return;
        el.dataset.activity = this._activityClass(activity);
        const actEl = el.querySelector('.badge-activity');
        if (actEl) actEl.textContent = activity;
      });

      this._badges[id].timer = setTimeout(() => this._removeBadge(id), this._staleMs);
    }

    _removeBadge(id) {
      if (!this._badges[id]) return;
      clearTimeout(this._badges[id].timer);
      this._panels.forEach(panel => {
        const el = panel.querySelector(`[data-npc-id="${CSS.escape(id)}"]`);
        if (el) el.remove();
      });
      delete this._badges[id];
    }

    /** Map activity text to a CSS variant keyword. */
    _activityClass(activity) {
      const a = (activity || '').toLowerCase();
      if (/talk|chat|speak|convers/.test(a))  return 'talking';
      if (/work|tend|mend|craft|repair/.test(a)) return 'working';
      if (/rest|sleep|sit|relax/.test(a))     return 'resting';
      if (/fight|attack|combat|battle/.test(a)) return 'fighting';
      return 'idle';
    }
  }

  /* ── Utilities ───────────────────────────────────────────────── */

  function _esc(str) {
    return String(str || '')
      .replace(/&/g, '&amp;')
      .replace(/</g, '&lt;')
      .replace(/>/g, '&gt;')
      .replace(/"/g, '&quot;');
  }

  /* ── Auto-init ───────────────────────────────────────────────── */

  window.CosySimNPCBadges = CosySimNPCBadges;
  window.cosySimNPCBadges = new CosySimNPCBadges();

})();
