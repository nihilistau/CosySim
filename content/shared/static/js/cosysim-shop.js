/**
 * cosysim-shop.js — Universal Shop Modal
 *
 * Usage:
 *   window.CosyShop.open({ title: 'BLACK MARKET', apiBase: '/api/shop' });
 *   window.CosyShop.close();
 *
 * Requires: shop_modal.html injected into DOM, cosysim-shop.css loaded.
 */
(function () {
  'use strict';

  const CosyShop = {
    _apiBase: '/api/shop',
    _mode: 'buy',          // 'buy' | 'sell'
    _cat: '',              // '' = all
    _catalog: [],          // buy catalog
    _inventory: [],        // sell inventory
    _selected: null,       // selected item metadata
    _qty: 1,
    _credits: 0,

    // ── Lifecycle ────────────────────────────────────────────────────────────

    open(opts) {
      this._apiBase = (opts && opts.apiBase) || '/api/shop';
      const title = (opts && opts.title) || 'BLACK MARKET';
      document.getElementById('cs-shop-title').textContent = title;

      const modal = document.getElementById('cs-shop-modal');
      if (!modal) { console.warn('[CosyShop] modal element not found'); return; }

      modal.hidden = false;
      requestAnimationFrame(() => modal.classList.add('is-open'));

      this._mode = 'buy';
      this._cat = '';
      this._selected = null;
      this._qty = 1;
      this._setModeUI();
      this._setTab('');
      this._loadAll();
    },

    close() {
      const modal = document.getElementById('cs-shop-modal');
      if (!modal) return;
      modal.classList.remove('is-open');
      setTimeout(() => { modal.hidden = true; }, 240);
    },

    // ── Init / Bind ───────────────────────────────────────────────────────────

    init() {
      const modal = document.getElementById('cs-shop-modal');
      if (!modal) return;

      document.getElementById('cs-shop-close')?.addEventListener('click', () => this.close());
      document.getElementById('cs-shop-backdrop')?.addEventListener('click', () => this.close());

      // Tabs
      document.getElementById('cs-shop-tabs')?.addEventListener('click', e => {
        const btn = e.target.closest('.cs-shop__tab');
        if (!btn) return;
        this._setTab(btn.dataset.cat || '');
        this._renderGrid();
      });

      // Mode (buy/sell)
      document.querySelector('.cs-shop__mode-bar')?.addEventListener('click', e => {
        const btn = e.target.closest('.cs-shop__mode');
        if (!btn) return;
        this._mode = btn.dataset.mode;
        this._setModeUI();
        this._renderGrid();
      });

      // Item grid click
      document.getElementById('cs-shop-grid')?.addEventListener('click', e => {
        const card = e.target.closest('.cs-shop__item');
        if (!card || card.classList.contains('cs-shop__item--unaffordable')) return;
        this._selectItem(card.dataset.itemId);
      });

      // Quantity buttons
      document.getElementById('cs-shop-qty-down')?.addEventListener('click', () => {
        this._qty = Math.max(1, this._qty - 1);
        this._updateDetail();
      });
      document.getElementById('cs-shop-qty-up')?.addEventListener('click', () => {
        this._qty = Math.min(99, this._qty + 1);
        this._updateDetail();
      });

      // Confirm
      document.getElementById('cs-shop-confirm')?.addEventListener('click', () => {
        if (this._mode === 'buy') this._confirmBuy();
        else this._confirmSell();
      });

      // ESC to close
      document.addEventListener('keydown', e => {
        if (e.key === 'Escape') {
          const modal = document.getElementById('cs-shop-modal');
          if (modal && !modal.hidden) this.close();
        }
      });
    },

    // ── Data Loading ──────────────────────────────────────────────────────────

    async _loadAll() {
      this._showLoading(true);
      try {
        const [catRes, invRes, credRes] = await Promise.all([
          fetch(`${this._apiBase}/catalog`).then(r => r.json()),
          fetch(`${this._apiBase}/inventory`).then(r => r.json()),
          fetch('/api/hud/state').then(r => r.json()).catch(() => ({})),
        ]);
        this._catalog = catRes.items || [];
        const invItems = (invRes.inventory && invRes.inventory.items) || [];
        // Flatten inventory items into the same shape as catalog for sell mode
        this._inventory = invItems.map(it => ({
          item_id: it.item_id,
          name: it.name,
          desc: it.desc || '',
          rarity: it.rarity || 'common',
          category: it.category || 'misc',
          icon: it.icon || '📦',
          price: it.sell_price || 0,
          sell_price: it.sell_price || 0,
          owned_qty: it.quantity || 0,
        }));
        this._credits = (credRes.player && credRes.player.credits) || 0;
        this._updateCreditsUI();
      } catch (err) {
        console.error('[CosyShop] load error', err);
      }
      this._showLoading(false);
      this._renderGrid();
    },

    // ── Rendering ─────────────────────────────────────────────────────────────

    _renderGrid() {
      const grid = document.getElementById('cs-shop-grid');
      if (!grid) return;

      const items = this._mode === 'buy' ? this._catalog : this._inventory;
      const filtered = this._cat ? items.filter(i => i.category === this._cat) : items;

      if (!filtered.length) {
        grid.innerHTML = `<div class="cs-shop__loading">No items available.</div>`;
        this._hideDetail();
        return;
      }

      grid.innerHTML = filtered.map(item => this._renderCard(item)).join('');
      if (this._selected) {
        const el = grid.querySelector(`[data-item-id="${this._selected.item_id}"]`);
        if (el) el.classList.add('cs-shop__item--selected');
      }
    },

    _renderCard(item) {
      const price = this._mode === 'sell' ? (item.sell_price || 0) : (item.price || 0);
      const affordable = this._mode === 'sell' || this._credits >= price;
      const classes = [
        'cs-shop__item',
        !affordable ? 'cs-shop__item--unaffordable' : '',
      ].filter(Boolean).join(' ');

      return `<div class="${classes}" data-item-id="${item.item_id}" data-rarity="${item.rarity}" role="listitem">
        <div class="cs-shop__item-icon">${item.icon || '📦'}</div>
        <div class="cs-shop__item-name">${this._esc(item.name)}</div>
        <div class="cs-shop__item-desc">${this._esc(item.desc || '')}</div>
        <div class="cs-shop__item-footer">
          <span class="cs-shop__item-price">${this._mode === 'sell' ? 'SELL ' : ''}₵${price.toLocaleString()}</span>
          ${item.owned_qty > 0 ? `<span class="cs-shop__item-qty">x${item.owned_qty}</span>` : ''}
        </div>
        <div class="cs-shop__item-rarity">${(item.rarity || 'common').toUpperCase()}</div>
      </div>`;
    },

    _selectItem(itemId) {
      const items = this._mode === 'buy' ? this._catalog : this._inventory;
      const item = items.find(i => i.item_id === itemId);
      if (!item) return;

      this._selected = item;
      this._qty = 1;

      // Update selection highlight
      document.querySelectorAll('.cs-shop__item--selected').forEach(el => el.classList.remove('cs-shop__item--selected'));
      const card = document.querySelector(`[data-item-id="${itemId}"]`);
      if (card) card.classList.add('cs-shop__item--selected');

      this._showDetail(item);
      this._updateDetail();
    },

    _showDetail(item) {
      const panel = document.getElementById('cs-shop-detail');
      if (!panel) return;
      panel.hidden = false;

      document.getElementById('cs-shop-detail-icon').textContent = item.icon || '📦';
      document.getElementById('cs-shop-detail-name').textContent = item.name;
      document.getElementById('cs-shop-detail-desc').textContent = item.desc || '';
      document.getElementById('cs-shop-detail-rarity').textContent = (item.rarity || 'common').toUpperCase();

      const btn = document.getElementById('cs-shop-confirm');
      if (btn) {
        btn.textContent = this._mode === 'sell' ? 'SELL' : 'BUY';
        btn.className = 'cs-shop__confirm-btn' + (this._mode === 'sell' ? ' cs-shop__confirm-btn--sell' : '');
      }
    },

    _hideDetail() {
      const panel = document.getElementById('cs-shop-detail');
      if (panel) panel.hidden = true;
      this._selected = null;
    },

    _updateDetail() {
      if (!this._selected) return;
      document.getElementById('cs-shop-qty').textContent = this._qty;
      const price = this._mode === 'sell'
        ? (this._selected.sell_price || 0)
        : (this._selected.price || 0);
      document.getElementById('cs-shop-total').textContent = `₵${(price * this._qty).toLocaleString()}`;
    },

    // ── Actions ───────────────────────────────────────────────────────────────

    async _confirmBuy() {
      if (!this._selected) return;
      try {
        const res = await fetch(`${this._apiBase}/buy`, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ item_id: this._selected.item_id, quantity: this._qty }),
        });
        const data = await res.json();
        if (data.success) {
          this._credits = data.credits_left;
          this._updateCreditsUI();
          this._toast(`Bought ${this._selected.name} x${this._qty} for ₵${(this._selected.price * this._qty).toLocaleString()}`);
          await this._loadAll();
        } else {
          this._toast(data.error || 'Purchase failed', true);
        }
      } catch (err) {
        this._toast('Network error', true);
      }
    },

    async _confirmSell() {
      if (!this._selected) return;
      try {
        const res = await fetch(`${this._apiBase}/sell`, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ item_id: this._selected.item_id, quantity: this._qty }),
        });
        const data = await res.json();
        if (data.success) {
          this._credits = data.credits_left;
          this._updateCreditsUI();
          this._toast(`Sold ${this._selected.name} x${this._qty} — earned ₵${(this._selected.sell_price * this._qty).toLocaleString()}`);
          await this._loadAll();
        } else {
          this._toast(data.error || 'Sale failed', true);
        }
      } catch (err) {
        this._toast('Network error', true);
      }
    },

    // ── UI Helpers ────────────────────────────────────────────────────────────

    _setTab(cat) {
      this._cat = cat;
      document.querySelectorAll('.cs-shop__tab').forEach(btn => {
        btn.classList.toggle('cs-shop__tab--active', (btn.dataset.cat || '') === cat);
      });
    },

    _setModeUI() {
      document.querySelectorAll('.cs-shop__mode').forEach(btn => {
        btn.classList.toggle('cs-shop__mode--active', btn.dataset.mode === this._mode);
      });
    },

    _updateCreditsUI() {
      const el = document.getElementById('cs-shop-credits');
      if (!el) return;
      el.textContent = `₵ ${this._credits.toLocaleString()}`;
      el.classList.add('cs-shop__credits-value--tick');
      setTimeout(() => el.classList.remove('cs-shop__credits-value--tick'), 300);
    },

    _showLoading(show) {
      const el = document.getElementById('cs-shop-loading');
      if (el) el.style.display = show ? '' : 'none';
    },

    _toast(msg, isError = false) {
      const toast = document.getElementById('cs-shop-toast');
      if (!toast) return;
      toast.textContent = msg;
      toast.hidden = false;
      toast.className = 'cs-shop__toast' + (isError ? ' cs-shop__toast--error' : '');
      requestAnimationFrame(() => toast.classList.add('is-visible'));
      clearTimeout(this._toastTimer);
      this._toastTimer = setTimeout(() => {
        toast.classList.remove('is-visible');
        setTimeout(() => { toast.hidden = true; }, 220);
      }, 3000);
    },

    _esc(str) {
      return String(str).replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;');
    },
  };

  // Init on DOM ready
  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', () => CosyShop.init());
  } else {
    CosyShop.init();
  }

  window.CosyShop = CosyShop;
})();
