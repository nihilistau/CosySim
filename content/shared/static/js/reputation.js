/**
 * reputation.js — Reputation HUD manager
 *
 * Listens for Socket.IO events:
 *   reputation_update  { character_id, score, label }
 *   character_speaking { character_id }
 *   reputation_data    { character_id, score, label }
 */
class ReputationHUD {
  constructor() {
    this.hud      = document.getElementById('cs-rep-hud');
    this.nameEl   = document.getElementById('cs-rep-name');
    this.barEl    = document.getElementById('cs-rep-bar');
    this.scoreEl  = document.getElementById('cs-rep-score');
    this.labelEl  = document.getElementById('cs-rep-label');
    this._bindEvents();
  }

  /**
   * Render a reputation update.
   * @param {string} charId
   * @param {number} score   -100 .. 100
   * @param {string} label   e.g. "friendly"
   */
  update(charId, score, label) {
    if (!this.hud) return;

    const prevScore = parseInt(this.scoreEl.textContent, 10) || 0;

    this.hud.style.display = 'flex';
    this.hud.dataset.label = label;
    this.nameEl.textContent  = charId;
    this.scoreEl.textContent = (score >= 0 ? '+' : '') + score;
    this.labelEl.textContent = label;

    // Bar: map -100..100 → 0..100 %
    const pct = ((score + 100) / 200 * 100).toFixed(1);
    this.barEl.style.width  = pct + '%';
    this.barEl.className    = 'cs-rep-bar cs-rep-bar--' + label;

    // Animate score on change
    if (score !== prevScore) {
      this.scoreEl.classList.remove('cs-rep-pop');
      // force reflow so the animation restarts
      void this.scoreEl.offsetWidth;
      this.scoreEl.classList.add('cs-rep-pop');
    }
  }

  _bindEvents() {
    if (typeof io === 'undefined') return;
    const socket = io();

    socket.on('reputation_update', (data) => {
      this.update(data.character_id, data.score, data.label);
    });

    socket.on('character_speaking', (data) => {
      if (data.character_id) {
        socket.emit('get_reputation', { character_id: data.character_id });
      }
    });

    socket.on('reputation_data', (data) => {
      this.update(data.character_id, data.score, data.label);
    });
  }
}

window.addEventListener('DOMContentLoaded', () => {
  window.reputationHUD = new ReputationHUD();
});
