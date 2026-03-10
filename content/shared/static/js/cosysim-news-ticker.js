/**
 * cosysim-news-ticker.js — Bottom-Screen Crawling World News Ticker
 * ==================================================================
 * Persistent horizontal crawl at the bottom of every scene.
 * Pulls articles from /api/news/ticker (NewsTicker Flask blueprint)
 * and /api/news/breaking for interrupt banners.
 *
 * Depends on: neon_base.js (for NeonBase.socket), cosysim-news-ticker.css
 * Exposed as: window.CosyNewsTicker
 */

(function () {
  'use strict';

  // ── Config ──────────────────────────────────────────────────────────────
  const POLL_INTERVAL_MS     = 30_000;  // fetch new items every 30s
  const BREAKING_POLL_MS     = 15_000;  // check breaking news every 15s
  const BREAKING_BANNER_MS   = 12_000;  // show breaking banner for 12s
  const MIN_SCROLL_DURATION  = 30;      // seconds for short content
  const MAX_SCROLL_DURATION  = 90;      // seconds for lots of content
  const SECONDS_PER_ITEM     = 5;       // scroll pacing per item

  // Category colour classes (match CSS)
  const CATEGORY_CSS = {
    crime:      'cs-ticker__tag--crime',
    economy:    'cs-ticker__tag--economy',
    faction:    'cs-ticker__tag--faction',
    tech:       'cs-ticker__tag--tech',
    social:     'cs-ticker__tag--social',
    breaking:   'cs-ticker__tag--breaking',
    sports:     'cs-ticker__tag--sports',
    underworld: 'cs-ticker__tag--underworld',
  };

  // Fallback items when API is unavailable
  const FALLBACK_ITEMS = [
    { category: 'faction', headline: 'OmniCorp security sweeps intensify in the Commercial District' },
    { category: 'crime',   headline: 'Three data couriers vanish near Grid nexus — StreetWatch investigating' },
    { category: 'economy', headline: 'eCred exchange rate volatile after Yakuza market intervention' },
    { category: 'tech',    headline: 'New ICE-breaker firmware surfaces on darknet forums' },
    { category: 'social',  headline: 'Neon District block party draws 2,000 despite acid rain advisory' },
    { category: 'faction', headline: 'Ghost Net operatives spotted running encrypted relay near docks' },
    { category: 'sports',  headline: 'Arena tournament bracket opens — record prize pool confirmed' },
    { category: 'crime',   headline: 'Cyber-jacking incidents spike 40% in lower sectors' },
    { category: 'economy', headline: 'Rare cyberware shipment intercepted — black market prices surge' },
    { category: 'tech',    headline: 'NeoTech announces neural interface v4.2 — street mods incoming' },
  ];

  // ── State ───────────────────────────────────────────────────────────────
  let _items         = [];
  let _breakingQueue = [];
  let _pollTimer     = null;
  let _breakingTimer = null;
  let _bannerTimeout = null;
  let _visible       = false;
  let _muted         = false;
  let _els           = {};

  // ── DOM Construction ────────────────────────────────────────────────────
  function buildDOM() {
    // Main ticker bar
    const ticker = document.createElement('div');
    ticker.id = 'cs-news-ticker';
    ticker.className = 'cs-ticker';
    ticker.innerHTML = `
      <div class="cs-ticker__label" id="ticker-label" title="Toggle news ticker">
        <span class="cs-ticker__led"></span>
        <span>NEON NEWS</span>
      </div>
      <div class="cs-ticker__track">
        <div class="cs-ticker__content" id="ticker-content"></div>
      </div>
      <div class="cs-ticker__controls">
        <button class="cs-ticker__btn" id="ticker-mute" title="Mute ticker">🔊</button>
        <button class="cs-ticker__btn" id="ticker-close" title="Hide ticker">✕</button>
      </div>
    `;
    document.body.appendChild(ticker);

    // Breaking news banner (sits above ticker)
    const banner = document.createElement('div');
    banner.id = 'cs-breaking-banner';
    banner.className = 'cs-ticker__breaking-banner';
    banner.innerHTML = `
      <span class="cs-ticker__tag cs-ticker__tag--breaking">⚡ BREAKING</span>
      <span class="cs-ticker__breaking-text" id="breaking-text"></span>
      <button class="cs-ticker__breaking-dismiss" id="breaking-dismiss">DISMISS</button>
    `;
    document.body.appendChild(banner);

    _els = {
      ticker:        ticker,
      label:         document.getElementById('ticker-label'),
      content:       document.getElementById('ticker-content'),
      muteBtn:       document.getElementById('ticker-mute'),
      closeBtn:      document.getElementById('ticker-close'),
      banner:        banner,
      breakingText:  document.getElementById('breaking-text'),
      breakingDismiss: document.getElementById('breaking-dismiss'),
    };
  }

  // ── Event Binding ───────────────────────────────────────────────────────
  function bindEvents() {
    // Close ticker
    if (_els.closeBtn) {
      _els.closeBtn.onclick = () => hide();
    }

    // Mute (pause scrolling)
    if (_els.muteBtn) {
      _els.muteBtn.onclick = () => toggleMute();
    }

    // Click label to toggle visibility
    if (_els.label) {
      _els.label.onclick = () => {
        if (_muted) toggleMute();
      };
    }

    // Dismiss breaking banner
    if (_els.breakingDismiss) {
      _els.breakingDismiss.onclick = () => dismissBanner();
    }

    // Keyboard: N = toggle ticker
    document.addEventListener('keydown', function (e) {
      if (['INPUT', 'TEXTAREA'].includes(e.target.tagName) || e.target.isContentEditable) return;
      if ((e.key === 'n' || e.key === 'N') && !e.ctrlKey && !e.altKey && !e.metaKey) {
        if (_visible) hide();
        else show();
      }
    });

    // Socket events for real-time news
    _attachSocket();
  }

  function _attachSocket() {
    function tryAttach() {
      const socket = window.NeonBase?.socket;
      if (!socket) return false;
      socket.on('news_article', function (data) {
        if (data && data.headline) {
          _pushItem({
            category: (data.category || 'social').toLowerCase(),
            headline: data.headline,
            severity: data.severity || 3,
          });
          if (data.severity >= 5 || (data.category || '').toLowerCase() === 'breaking') {
            _showBreaking(data.headline);
          }
        }
      });
      socket.on('breaking_news', function (data) {
        if (data && (data.headline || data.text)) {
          _showBreaking(data.headline || data.text);
        }
      });
      return true;
    }

    if (!tryAttach()) {
      const check = setInterval(function () {
        if (tryAttach()) clearInterval(check);
      }, 1000);
      // Give up after 30s
      setTimeout(function () { clearInterval(check); }, 30_000);
    }
  }

  // ── Data Fetching ───────────────────────────────────────────────────────
  async function fetchItems() {
    try {
      const r = await fetch('/api/news/ticker', { signal: AbortSignal.timeout(5000) });
      if (!r.ok) throw new Error('HTTP ' + r.status);
      const data = await r.json();
      const items = (data.items || []).map(function (i) {
        return {
          category: (i.category || 'social').toLowerCase(),
          headline: i.headline || i.text || '',
          severity: i.severity || 3,
        };
      }).filter(function (i) { return i.headline; });

      if (items.length > 0) {
        _items = items;
        renderTicker();
        if (!_visible) show();
      }
    } catch (_e) {
      // Use fallback items if we have nothing
      if (_items.length === 0) {
        _items = FALLBACK_ITEMS.slice();
        renderTicker();
        if (!_visible) show();
      }
    }
  }

  async function fetchBreaking() {
    try {
      const r = await fetch('/api/news/breaking', { signal: AbortSignal.timeout(3000) });
      if (!r.ok) return;
      const data = await r.json();
      const articles = data.articles || [];
      if (articles.length > 0) {
        const latest = articles[0];
        const headline = latest.headline || latest.title || '';
        if (headline && !_breakingQueue.includes(headline)) {
          _breakingQueue.push(headline);
          if (_breakingQueue.length > 10) _breakingQueue.shift();
          _showBreaking(headline);
        }
      }
    } catch (_e) {
      // Silent — breaking news is optional
    }
  }

  // ── Rendering ───────────────────────────────────────────────────────────
  function renderTicker() {
    const content = _els.content;
    if (!content) return;

    // Build item HTML (duplicated for seamless loop)
    let html = '';
    const items = _items.length > 0 ? _items : FALLBACK_ITEMS;

    for (let i = 0; i < items.length; i++) {
      html += _buildItemHTML(items[i]);
      if (i < items.length - 1) {
        html += '<span class="cs-ticker__sep"></span>';
      }
    }

    // Duplicate for infinite scroll illusion
    const fullHTML = html + '<span class="cs-ticker__sep"></span>' + html;
    content.innerHTML = fullHTML;

    // Adjust scroll duration based on content length
    const duration = Math.min(
      MAX_SCROLL_DURATION,
      Math.max(MIN_SCROLL_DURATION, items.length * SECONDS_PER_ITEM)
    );
    content.style.setProperty('--ticker-duration', duration + 's');
  }

  function _buildItemHTML(item) {
    const catClass = CATEGORY_CSS[item.category] || CATEGORY_CSS.social;
    const catLabel = (item.category || 'social').toUpperCase();
    const headline = _esc(item.headline);

    return '<span class="cs-ticker__item">' +
      '<span class="cs-ticker__tag ' + catClass + '">' + catLabel + '</span>' +
      '<span class="cs-ticker__headline">' + headline + '</span>' +
      '</span>';
  }

  // ── Breaking News Banner ────────────────────────────────────────────────
  function _showBreaking(headline) {
    if (!_els.banner || !headline) return;

    // Set ticker to breaking mode
    _els.ticker?.classList.add('cs-ticker--breaking');
    _els.ticker?.classList.add('cs-ticker--glitch');
    setTimeout(function () {
      _els.ticker?.classList.remove('cs-ticker--glitch');
    }, 300);

    // Show banner
    _els.breakingText.textContent = headline;
    _els.banner.classList.add('cs-ticker__breaking-banner--visible');

    // Auto-dismiss after timeout
    if (_bannerTimeout) clearTimeout(_bannerTimeout);
    _bannerTimeout = setTimeout(function () {
      dismissBanner();
    }, BREAKING_BANNER_MS);
  }

  function dismissBanner() {
    _els.banner?.classList.remove('cs-ticker__breaking-banner--visible');
    _els.ticker?.classList.remove('cs-ticker--breaking');
    if (_bannerTimeout) {
      clearTimeout(_bannerTimeout);
      _bannerTimeout = null;
    }
  }

  // ── Push Live Items ─────────────────────────────────────────────────────
  function _pushItem(item) {
    if (!item.headline) return;

    // Dedup by headline
    const exists = _items.some(function (i) { return i.headline === item.headline; });
    if (exists) return;

    _items.unshift(item);
    if (_items.length > 30) _items.length = 30;

    renderTicker();
    if (!_visible) show();
  }

  // ── Visibility ──────────────────────────────────────────────────────────
  function show() {
    if (!_els.ticker) return;
    _visible = true;
    _els.ticker.classList.add('cs-ticker--visible');
    _els.ticker.classList.remove('cs-ticker--hidden');
    document.body.classList.add('has-ticker');
  }

  function hide() {
    if (!_els.ticker) return;
    _visible = false;
    _els.ticker.classList.remove('cs-ticker--visible');
    _els.ticker.classList.add('cs-ticker--hidden');
    document.body.classList.remove('has-ticker');
    dismissBanner();
  }

  function toggleMute() {
    _muted = !_muted;
    if (_els.content) {
      _els.content.style.animationPlayState = _muted ? 'paused' : 'running';
    }
    if (_els.muteBtn) {
      _els.muteBtn.textContent = _muted ? '🔇' : '🔊';
      _els.muteBtn.classList.toggle('cs-ticker__btn--active', _muted);
    }
  }

  // ── Helpers ─────────────────────────────────────────────────────────────
  function _esc(str) {
    return String(str)
      .replace(/&/g, '&amp;')
      .replace(/</g, '&lt;')
      .replace(/>/g, '&gt;')
      .replace(/"/g, '&quot;');
  }

  // ── Public API ──────────────────────────────────────────────────────────
  const CosyNewsTicker = {
    show:       show,
    hide:       hide,
    toggleMute: toggleMute,
    refresh:    fetchItems,
    pushItem:   _pushItem,
    isVisible:  function () { return _visible; },
    isMuted:    function () { return _muted; },
    getItems:   function () { return _items.slice(); },
  };

  // ── Boot ────────────────────────────────────────────────────────────────
  function boot() {
    buildDOM();
    bindEvents();

    // Initial fetch
    fetchItems();

    // Periodic polling
    _pollTimer = setInterval(fetchItems, POLL_INTERVAL_MS);
    _breakingTimer = setInterval(fetchBreaking, BREAKING_POLL_MS);

    window.CosyNewsTicker = CosyNewsTicker;
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', boot);
  } else {
    boot();
  }

})();
