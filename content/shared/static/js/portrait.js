/**
 * Portrait Overlay Manager
 * Controls the cs-portrait overlay: show/hide, mood updates, Socket.IO wiring.
 */

'use strict';

/** Mood tag → badge label + CSS variable mapping */
const MOOD_MAP = {
  happy:   { label: 'Happy',   var: '--mood-happy' },
  sad:     { label: 'Sad',     var: '--mood-sad' },
  angry:   { label: 'Angry',   var: '--mood-angry' },
  aroused: { label: 'Aroused', var: '--mood-aroused' },
  neutral: { label: 'Neutral', var: '--mood-neutral' },
  anxious: { label: 'Anxious', var: '--mood-anxious' },
  excited: { label: 'Excited', var: '--mood-excited' },
};

window.portraitManager = {
  _overlay: null,
  _imgEl: null,
  _imgArea: null,
  _nameEl: null,
  _moodEl: null,
  _placeholder: null,
  _backstoryPanel: null,
  _backstoryText: null,
  _backstoryClose: null,

  /**
   * Initialize the portrait manager.
   * Locates DOM nodes and wires Socket.IO listeners if available.
   */
  init() {
    this._overlay       = document.getElementById('cs-portrait-overlay');
    this._imgArea       = document.getElementById('cs-portrait-img-area');
    this._imgEl         = document.getElementById('cs-portrait-img');
    this._nameEl        = document.getElementById('cs-portrait-name');
    this._moodEl        = document.getElementById('cs-portrait-mood');
    this._backstoryPanel = document.getElementById('cs-backstory-panel');
    this._backstoryText  = document.getElementById('cs-backstory-text');
    this._backstoryClose = document.getElementById('cs-backstory-close');
    this._placeholder   = this._overlay
      ? this._overlay.querySelector('.cs-portrait__placeholder')
      : null;

    if (!this._overlay) return;

    this._bindSocketEvents();
    this._bindBackstoryEvents();
  },

  /**
   * Show the portrait panel.
   * @param {string} charName  - Character display name
   * @param {string} moodTag   - Mood key (must match MOOD_MAP)
   * @param {string|null} imgUrl - Portrait image URL or null for placeholder
   */
  show(charName, moodTag, imgUrl) {
    if (!this._overlay) return;

    const mood = MOOD_MAP[moodTag] ? moodTag : 'neutral';

    // Update name
    if (this._nameEl) this._nameEl.textContent = charName || '';

    // Update mood badge
    this.updateMood(mood);

    // Update image vs placeholder
    if (this._imgEl && this._placeholder) {
      if (imgUrl) {
        this._imgEl.src = imgUrl;
        this._imgEl.alt = charName || '';
        this._imgEl.style.display = 'block';
        this._placeholder.style.display = 'none';
      } else {
        this._imgEl.src = '';
        this._imgEl.style.display = 'none';
        this._placeholder.style.display = 'flex';
      }
    }

    // Reveal
    this._overlay.dataset.state = 'visible';
    this._overlay.dataset.mood  = mood;
  },

  /**
   * Hide the portrait (slide out).
   */
  hide() {
    if (!this._overlay) return;
    this._overlay.dataset.state = 'hidden';
  },

  /**
   * Update mood badge only — no hide/show transition.
   * @param {string} mood - Mood key from MOOD_MAP
   */
  updateMood(mood) {
    if (!this._overlay) return;

    const entry = MOOD_MAP[mood] || MOOD_MAP['neutral'];
    const resolvedMood = MOOD_MAP[mood] ? mood : 'neutral';

    // Update data-mood for CSS variable switching
    this._overlay.dataset.mood = resolvedMood;

    // Update badge text
    if (this._moodEl) {
      this._moodEl.textContent = entry.label;
    }
  },

  /**
   * Parse a [MOOD:X] tag from a message string.
   * @param {string} messageText
   * @returns {string|null} mood key in lowercase, or null
   */
  parseMood(messageText) {
    if (!messageText || typeof messageText !== 'string') return null;
    const match = messageText.match(/\[MOOD:(\w+)\]/i);
    return match ? match[1].toLowerCase() : null;
  },

  /**
   * Fetch backstory for the named character from the server.
   * @param {string} charName
   */
  _fetchBackstory(charName) {
    if (!charName || !this._backstoryPanel || !this._backstoryText) return;
    fetch(`/api/character/backstory/${encodeURIComponent(charName)}`)
      .then(r => r.ok ? r.json() : null)
      .then(data => {
        if (!data) return;
        const text = data.backstory || data.content || data.text || '';
        if (!text) return;
        this._backstoryText.textContent = text;
        this._backstoryPanel.classList.add('is-visible');
      })
      .catch(() => {});
  },

  /**
   * Bind backstory close button and show-backstory events.
   */
  _bindBackstoryEvents() {
    if (this._backstoryClose) {
      this._backstoryClose.addEventListener('click', () => {
        if (this._backstoryPanel) {
          this._backstoryPanel.classList.remove('is-visible');
        }
      });
    }

    // Double-click portrait image area to show backstory
    if (this._imgArea) {
      this._imgArea.addEventListener('dblclick', () => {
        const name = this._nameEl ? this._nameEl.textContent : '';
        if (name) this._fetchBackstory(name);
      });
    }
  },

  /**
   * Attach Socket.IO listeners for portrait events.
   * Called internally by init().
   */
  _bindSocketEvents() {
    const socket = window.socket || (window.io ? window.io() : null);
    if (!socket) return;

    // Parse [MOOD:X] from incoming messages and update badge
    socket.on('message', (data) => {
      const text = typeof data === 'string'
        ? data
        : (data && (data.content || data.text || data.message || ''));
      if (!text) return;

      const mood = this.parseMood(text);
      if (mood) this.updateMood(mood);
    });

    // Character entering the scene → show portrait
    socket.on('character_entered', (data) => {
      const name   = (data && (data.name || data.char_name || data.character)) || '';
      const mood   = (data && data.mood) || 'neutral';
      const imgUrl = (data && (data.portrait_url || data.image_url || data.img_url)) || null;
      this.show(name, mood, imgUrl);
    });

    // Character leaving the scene → hide portrait
    socket.on('character_exited', () => {
      this.hide();
    });
  },
};

// Auto-initialise once the DOM is ready, if Socket.IO is present or absent
document.addEventListener('DOMContentLoaded', () => {
  window.portraitManager.init();
});