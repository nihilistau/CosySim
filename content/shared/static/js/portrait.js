/**
 * PortraitManager — NPC portrait overlay controller
 * Listens to Socket.IO 'message' events for [MOOD:x] tags.
 * Also listens for 'character_speaking' events directly.
 */

const MOOD_COLORS = {
  happy:     '#22c55e',
  angry:     '#ef4444',
  sad:       '#3b82f6',
  aroused:   '#ec4899',
  fearful:   '#f97316',
  disgusted: '#84cc16',
  surprised: '#f59e0b',
  neutral:   '#6b7280',
  seductive: '#d946ef',
  drunk:     '#a16207',
  tired:     '#64748b',
};

const PORTRAIT_AUTO_HIDE_MS = 8000;

class PortraitManager {
  constructor() {
    this._overlay = null;
    this._hideTimer = null;
    this._current = null;
    this._backstoryPanel = null;
    this._backstoryText = null;
  }

  init() {
    this._overlay = document.getElementById('cs-portrait-overlay');
    if (!this._overlay) return;
    this._backstoryPanel = document.getElementById('cs-backstory-panel');
    this._backstoryText = document.getElementById('cs-backstory-text');
    this._bindEvents();
    this._bindBackstoryEvents();
  }

  /**
   * Show the portrait panel for a character.
   * @param {string|null} charName - Character name (null keeps current)
   * @param {string} mood - Mood key from MOOD_COLORS
   * @param {string|null} imageUrl - Optional portrait image URL
   */
  show(charName, mood = 'neutral', imageUrl = null) {
    if (!this._overlay) return;

    const name = charName || this._current || '';
    this._current = name || this._current;

    // Update data attributes
    this._overlay.dataset.char = name;
    this._overlay.dataset.mood = mood;

    // Update name display
    const nameEl = document.getElementById('cs-portrait-name');
    if (nameEl) nameEl.textContent = name;

    // Update initial letter
    const initialEl = document.getElementById('cs-portrait-initial');
    if (initialEl) initialEl.textContent = name ? name.charAt(0).toUpperCase() : '?';

    // Update mood badge
    const badgeEl = document.getElementById('cs-portrait-mood-badge');
    if (badgeEl) badgeEl.textContent = mood;

    // Apply mood colour via CSS custom property
    const color = MOOD_COLORS[mood] || MOOD_COLORS['neutral'];
    this._overlay.style.setProperty('--portrait-mood-color', color);

    // Handle image — show real image or placeholder
    const placeholder = document.getElementById('cs-portrait-placeholder');
    const imgEl = document.getElementById('cs-portrait-img');
    if (imageUrl) {
      if (placeholder) placeholder.style.display = 'none';
      if (imgEl) {
        imgEl.style.backgroundImage = `url('${imageUrl}')`;
        imgEl.style.backgroundSize = 'cover';
        imgEl.style.backgroundPosition = 'center';
      }
    } else {
      if (placeholder) placeholder.style.display = '';
      if (imgEl) {
        imgEl.style.backgroundImage = '';
      }
    }

    // Slide in
    this._overlay.setAttribute('aria-hidden', 'false');
    this._overlay.classList.add('is-visible');

    // Auto-hide after PORTRAIT_AUTO_HIDE_MS of no new show() call
    if (this._hideTimer) clearTimeout(this._hideTimer);
    this._hideTimer = setTimeout(() => this.hide(), PORTRAIT_AUTO_HIDE_MS);
  }

  /** Slide the overlay out. */
  hide() {
    if (!this._overlay) return;
    this._overlay.classList.remove('is-visible');
    this._overlay.setAttribute('aria-hidden', 'true');
    if (this._hideTimer) {
      clearTimeout(this._hideTimer);
      this._hideTimer = null;
    }
  }

  /**
   * Update just the mood ring and badge without hiding/re-showing.
   * @param {string} mood - Mood key
   */
  updateMood(mood) {
    if (!this._overlay) return;
    this._overlay.dataset.mood = mood;

    const color = MOOD_COLORS[mood] || MOOD_COLORS['neutral'];
    this._overlay.style.setProperty('--portrait-mood-color', color);

    const badgeEl = document.getElementById('cs-portrait-mood-badge');
    if (badgeEl) badgeEl.textContent = mood;
  }

  /**
   * Extract [MOOD:x] tag from streamed text.
   * @param {string} text
   * @returns {string|null} mood string or null
   */
  _parseMoodTag(text) {
    const match = text.match(/\[MOOD:(\w+)\]/i);
    return match ? match[1].toLowerCase() : null;
  }

  /**
   * Extract character name from [CHAR:name] tag or "Name: text" prefix.
   * @param {string} text
   * @returns {string|null}
   */
  _parseCharTag(text) {
    // Try [CHAR:name] tag first
    const tagMatch = text.match(/\[CHAR:([^\]]+)\]/i);
    if (tagMatch) return tagMatch[1].trim();

    // Fall back to "Name: " prefix at start of message
    const prefixMatch = text.match(/^([A-Z][a-zA-Z' -]{1,30}):\s/);
    if (prefixMatch) return prefixMatch[1].trim();

    return null;
  }

  /**
   * Fetch and display backstory for the current character.
   * @param {string} charId - lowercase character identifier
   */
  _fetchBackstory(charId) {
    if (!this._backstoryPanel || !this._backstoryText || !charId) return;
    fetch(`/api/character/backstory/${encodeURIComponent(charId)}`)
      .then((r) => r.ok ? r.json() : null)
      .then((data) => {
        if (!data || !data.backstory) return;
        this._backstoryText.textContent = data.backstory;
        this._backstoryPanel.classList.add('is-visible');
      })
      .catch(() => {});
  }

  /** Bind click-to-reveal backstory on the portrait frame and close button. */
  _bindBackstoryEvents() {
    const frame = this._overlay && this._overlay.querySelector('.cs-portrait__frame');
    if (frame) {
      frame.style.cursor = 'pointer';
      frame.addEventListener('click', () => {
        if (this._current) this._fetchBackstory(this._current.toLowerCase());
      });
    }
    const closeBtn = document.getElementById('cs-backstory-close');
    if (closeBtn) {
      closeBtn.addEventListener('click', (e) => {
        e.stopPropagation();
        if (this._backstoryPanel) this._backstoryPanel.classList.remove('is-visible');
      });
    }
  }

  /** Attach Socket.IO event listeners if a socket is available. */
  _bindEvents() {
    if (window.socket || window.io) {
      const socket = window.socket || (window.io && window.io());
      if (socket) {
        socket.on('message', (data) => {
          const text = typeof data === 'string' ? data : (data.content || data.text || '');
          const mood = this._parseMoodTag(text);
          const char = this._parseCharTag(text);
          if (char || mood) this.show(char || this._current, mood || 'neutral');
        });

        socket.on('character_speaking', (data) => {
          this.show(data.name, data.mood || 'neutral', data.portrait_url || null);
        });
      }
    }
  }
}

// Auto-init
document.addEventListener('DOMContentLoaded', () => {
  window.portraitManager = new PortraitManager();
  window.portraitManager.init();
});
