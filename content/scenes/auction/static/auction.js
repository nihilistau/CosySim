/**
 * auction.js — THE AUCTION HOUSE Scene Controller
 * ================================================
 *
 * Real-time bidding UI for underground black market auctions.
 * Handles Socket.IO events, NPC bid rendering, timer animations,
 * phase transitions, and session management.
 *
 * Version: v1.50.0 [2026-03-22]
 * Author:  CosySim Team
 *
 * Change Log:
 *   v1.50.0 [2026-03-22] — Full auction UI controller: real-time bidding,
 *                            NPC card updates, timer bar, phase indicators,
 *                            bid feed, session summary, preset bid buttons
 *   v1.0.0  [2026-03-22] — Initial scaffold via Creation Kit
 */

'use strict';

// ──── Scene App Class ─────────────────────────────────────────────────
// v1.50.0 [2026-03-22] — Complete auction controller

class AuctionController {
  constructor() {
    this.socket = null;
    this.state = null;
    this.currentLot = null;
    this.timerInterval = null;
    this.lotStartTime = 0;
    this.lotDuration = 30;
  }

  // ── Lifecycle ─────────────────────────────────────────────────────

  init() {
    this._cacheDOM();
    this._bindEvents();
    this._setupSocket();
    console.log('[THE AUCTION HOUSE] Scene initialized');
  }

  // ── DOM Cache ─────────────────────────────────────────────────────
  // v1.50.0 [2026-03-22] — Cache all DOM references for performance

  _cacheDOM() {
    // Header
    this.$credits = document.getElementById('player-credits');
    this.$itemsWon = document.getElementById('items-won-count');
    this.$totalSpent = document.getElementById('total-spent');

    // Gavel
    this.$gavelBar = document.getElementById('gavel-bar');
    this.$gavelText = document.getElementById('gavel-text');

    // Lot panels
    this.$lotIdle = document.getElementById('lot-idle');
    this.$lotActive = document.getElementById('lot-active');
    this.$lotComplete = document.getElementById('lot-complete');

    // Lot details
    this.$lotNumber = document.getElementById('lot-number');
    this.$lotRarity = document.getElementById('lot-rarity');
    this.$lotItemName = document.getElementById('lot-item-name');
    this.$lotItemDesc = document.getElementById('lot-item-desc');
    this.$lotItemCat = document.getElementById('lot-item-category');

    // Timer
    this.$timerFill = document.getElementById('timer-fill');
    this.$timerText = document.getElementById('timer-text');

    // Price
    this.$currentPrice = document.getElementById('current-price');
    this.$currentWinner = document.getElementById('current-winner');

    // Bid controls
    this.$bidInput = document.getElementById('bid-input');
    this.$bidBtn = document.getElementById('btn-place-bid');
    this.$bidMinimum = document.getElementById('bid-minimum');

    // Phase
    this.$phaseIndicator = document.getElementById('phase-indicator');
    this.$phaseText = document.getElementById('phase-text');

    // Start buttons
    this.$btnStart = document.getElementById('btn-start-auction');
    this.$btnNew = document.getElementById('btn-new-auction');

    // Right column
    this.$npcList = document.getElementById('npc-list');
    this.$bidFeed = document.getElementById('bid-feed');
    this.$lotsProgress = document.getElementById('lots-progress');
    this.$sessionSummary = document.getElementById('session-summary');
  }

  // ── Event Binding ─────────────────────────────────────────────────
  // v1.50.0 [2026-03-22] — Button clicks, preset bids, keyboard shortcuts

  _bindEvents() {
    // Start auction buttons
    if (this.$btnStart) {
      this.$btnStart.addEventListener('click', () => this._startAuction());
    }
    if (this.$btnNew) {
      this.$btnNew.addEventListener('click', () => this._startAuction());
    }

    // Place bid button
    if (this.$bidBtn) {
      this.$bidBtn.addEventListener('click', () => this._placeBid());
    }

    // Enter key on bid input
    if (this.$bidInput) {
      this.$bidInput.addEventListener('keydown', (e) => {
        if (e.key === 'Enter') this._placeBid();
      });
    }

    // Preset bid buttons (+10%, +25%, +50%)
    document.querySelectorAll('.btn-bid-preset').forEach(btn => {
      btn.addEventListener('click', () => {
        const pct = parseInt(btn.dataset.increment, 10) / 100;
        if (this.currentLot) {
          const increment = Math.max(1, Math.ceil(this.currentLot.current_price * pct));
          const amount = this.currentLot.current_price + increment;
          this.$bidInput.value = amount;
          this._placeBid();
        }
      });
    });
  }

  // ── Socket.IO ─────────────────────────────────────────────────────
  // v1.50.0 [2026-03-22] — All auction Socket.IO event handlers

  _setupSocket() {
    this.socket = io('', { transports: ['websocket', 'polling'] });

    this.socket.on('connect', () => {
      console.log('[THE AUCTION HOUSE] Socket connected');
    });

    // Scene state (general)
    this.socket.on('scene_state', (data) => {
      this.state = data;
      this._renderSceneState(data);
    });

    // Auction state (detailed)
    this.socket.on('auction_state', (data) => {
      this._renderAuctionState(data);
    });

    // New item up for auction
    this.socket.on('auction_item', (data) => {
      this.currentLot = data;
      this._showActiveLot(data);
    });

    // Bid placed (any bidder)
    this.socket.on('bid_placed', (data) => {
      this._onBidPlaced(data);
    });

    // Bid rejected
    this.socket.on('bid_rejected', (data) => {
      this._onBidRejected(data);
    });

    // Phase events
    this.socket.on('going_once', (data) => {
      this._onPhase('going_once', data);
    });

    this.socket.on('going_twice', (data) => {
      this._onPhase('going_twice', data);
    });

    // Sold
    this.socket.on('sold', (data) => {
      this._onSold(data);
    });

    // Unsold
    this.socket.on('unsold', (data) => {
      this._onUnsold(data);
    });

    // Gavel narration
    this.socket.on('gavel_narration', (data) => {
      this._showGavel(data.text, data.type);
    });

    // Auction session complete
    this.socket.on('auction_complete', (data) => {
      this._onAuctionComplete(data);
    });

    // HUD update (credits changed)
    this.socket.on('hud_update', (data) => {
      if (this.state) Object.assign(this.state, data);
      if (data.credits !== undefined) this._setCredits(data.credits);
    });

    // Error
    this.socket.on('error', (data) => {
      console.warn('[THE AUCTION HOUSE] Error:', data.message || data);
    });
  }

  // ── Actions ───────────────────────────────────────────────────────

  /** Start a new auction session. */
  _startAuction() {
    if (this.socket) {
      this.socket.emit('auction_start');
      // Optimistically show loading state
      if (this.$btnStart) this.$btnStart.textContent = 'STARTING...';
      if (this.$btnNew) this.$btnNew.textContent = 'STARTING...';
    }
  }

  /**
   * Place a bid using the input field value.
   * v1.50.0 [2026-03-22] — Validates locally before sending.
   */
  _placeBid() {
    const val = parseInt(this.$bidInput.value, 10);
    if (!val || val <= 0) return;
    if (this.socket) {
      this.socket.emit('auction_bid', { amount: val });
      this.$bidInput.value = '';
    }
  }

  // ── Rendering — Scene State ───────────────────────────────────────

  /**
   * Render general scene state (credits, stats).
   * @param {Object} data — Scene state from server.
   */
  _renderSceneState(data) {
    if (data.player) {
      this._setCredits(data.player.credits);
    }
    if (data.auction && data.auction.bidder_state) {
      const bs = data.auction.bidder_state;
      this._setCredits(bs.credits);
      if (this.$itemsWon) this.$itemsWon.textContent = `Won: ${bs.items_won.length}`;
      if (this.$totalSpent) this.$totalSpent.textContent = `Spent: ${bs.total_spent.toLocaleString()}`;
    }
  }

  /**
   * Render detailed auction state (on reconnect).
   * @param {Object} data — Auction state from server.
   */
  _renderAuctionState(data) {
    if (data.bidder_state) {
      this._setCredits(data.bidder_state.credits);
    }
    if (data.session && data.session.current_lot) {
      this.currentLot = data.session.current_lot;
      this._showActiveLot(data.session.current_lot);
    }
    if (data.npcs) {
      this._updateNPCs(data.npcs);
    }
    // Render lots progress
    if (data.session && data.session.lots_summary) {
      this._renderLotsProgress(data.session.lots_summary, data.session.current_lot_index);
    }
  }

  // ── Rendering — Lot Display ───────────────────────────────────────
  // v1.50.0 [2026-03-22] — Active lot rendering with timer

  /**
   * Show the active lot panel with item details.
   * @param {Object} lot — Lot data from server.
   */
  _showActiveLot(lot) {
    // Switch to active view
    if (this.$lotIdle) this.$lotIdle.style.display = 'none';
    if (this.$lotComplete) this.$lotComplete.style.display = 'none';
    if (this.$lotActive) this.$lotActive.style.display = 'flex';

    // Populate item details
    if (this.$lotNumber) this.$lotNumber.textContent = `LOT ${lot.lot_number}`;
    if (this.$lotRarity) {
      this.$lotRarity.textContent = (lot.item.rarity || 'common').toUpperCase();
      this.$lotRarity.dataset.rarity = lot.item.rarity || 'common';
    }
    if (this.$lotItemName) this.$lotItemName.textContent = lot.item.name;
    if (this.$lotItemDesc) this.$lotItemDesc.textContent = lot.item.description;
    if (this.$lotItemCat) this.$lotItemCat.textContent = lot.item.category;

    // Price
    this._updatePrice(lot.current_price, lot.current_winner_name);

    // Minimum bid hint
    const minBid = lot.current_price + Math.max(1, Math.ceil(lot.current_price * 0.10));
    if (this.$bidMinimum) this.$bidMinimum.textContent = `Minimum: ${minBid.toLocaleString()}`;

    // Hide phase indicator
    if (this.$phaseIndicator) this.$phaseIndicator.style.display = 'none';

    // Start timer
    this.lotStartTime = Date.now() / 1000;
    this.lotDuration = lot.time_remaining || 30;
    this._startTimer();

    // Clear feed for new lot
    this._addFeedEntry(`--- LOT ${lot.lot_number}: ${lot.item.name} ---`, 'feed-gavel');
  }

  /**
   * Update price display.
   * @param {number} price — Current price.
   * @param {string} winner — Current winner name.
   */
  _updatePrice(price, winner) {
    if (this.$currentPrice) this.$currentPrice.textContent = price.toLocaleString();
    if (this.$currentWinner) {
      if (winner) {
        this.$currentWinner.textContent = `Leading: ${winner}`;
        this.$currentWinner.className = winner === 'You' ? 'price-winner is-player' : 'price-winner';
      } else {
        this.$currentWinner.textContent = 'No bids yet';
        this.$currentWinner.className = 'price-winner';
      }
    }
    // Update minimum bid hint
    const minBid = price + Math.max(1, Math.ceil(price * 0.10));
    if (this.$bidMinimum) this.$bidMinimum.textContent = `Minimum: ${minBid.toLocaleString()}`;
  }

  // ── Timer ─────────────────────────────────────────────────────────
  // v1.50.0 [2026-03-22] — Animated countdown bar with color phases

  _startTimer() {
    if (this.timerInterval) clearInterval(this.timerInterval);

    this.timerInterval = setInterval(() => {
      const elapsed = (Date.now() / 1000) - this.lotStartTime;
      const remaining = Math.max(0, this.lotDuration - elapsed);
      const pct = (remaining / this.lotDuration) * 100;

      if (this.$timerFill) {
        this.$timerFill.style.width = `${pct}%`;
        this.$timerFill.classList.remove('timer-warning', 'timer-danger');
        if (remaining <= 5) {
          this.$timerFill.classList.add('timer-danger');
        } else if (remaining <= 10) {
          this.$timerFill.classList.add('timer-warning');
        }
      }
      if (this.$timerText) {
        this.$timerText.textContent = `${Math.ceil(remaining)}s`;
      }

      if (remaining <= 0) {
        clearInterval(this.timerInterval);
        this.timerInterval = null;
      }
    }, 250);
  }

  _stopTimer() {
    if (this.timerInterval) {
      clearInterval(this.timerInterval);
      this.timerInterval = null;
    }
  }

  // ── Event Handlers ────────────────────────────────────────────────
  // v1.50.0 [2026-03-22] — Bid, phase, sold, unsold, complete handlers

  /**
   * Handle a bid_placed event.
   * @param {Object} data — Bid data.
   */
  _onBidPlaced(data) {
    // Update current lot state
    if (this.currentLot) {
      this.currentLot.current_price = data.amount;
      this.currentLot.current_winner = data.bidder;
      this.currentLot.current_winner_name = data.display_name;
    }

    // Update price display
    this._updatePrice(data.amount, data.display_name);

    // Add to feed
    const cls = data.is_player ? 'feed-player-bid' : 'feed-bid';
    const text = data.flavor_text || `${data.display_name} bids ${data.amount.toLocaleString()}`;
    this._addFeedEntry(text, cls);

    // Highlight NPC card if NPC bid
    if (!data.is_player) {
      this._flashNPC(data.bidder, 'npc-bidding');
    }

    // Reset timer if bid came during going_once/going_twice
    // (server will have rescheduled phases — we reset our local timer)
    if (this.$phaseIndicator && this.$phaseIndicator.style.display !== 'none') {
      this.$phaseIndicator.style.display = 'none';
      // Reset timer to ~15s (the server extension window)
      this.lotStartTime = Date.now() / 1000;
      this.lotDuration = 15;
      this._startTimer();
    }

    // Update bidder state credits display (refresh from server)
    this.socket.emit('get_state');
  }

  /**
   * Handle a bid_rejected event.
   * @param {Object} data — Rejection data.
   */
  _onBidRejected(data) {
    const reason = data.reason || 'Bid rejected';
    this._addFeedEntry(`REJECTED: ${reason}`, 'feed-unsold');
    // Flash the bid input red briefly
    if (this.$bidInput) {
      this.$bidInput.style.borderColor = '#ef4444';
      setTimeout(() => {
        this.$bidInput.style.borderColor = '';
      }, 1500);
    }
  }

  /**
   * Handle going_once / going_twice phase events.
   * @param {string} phase — Phase name.
   * @param {Object} data — Phase data.
   */
  _onPhase(phase, data) {
    if (this.$phaseIndicator) {
      this.$phaseIndicator.style.display = 'block';
      this.$phaseIndicator.className = `phase-indicator ${phase.replace('_', '-')}`;
    }
    if (this.$phaseText) {
      this.$phaseText.textContent = phase === 'going_once' ? 'GOING ONCE...' : 'GOING TWICE...';
    }
    if (data.narration) {
      this._addFeedEntry(data.narration, 'feed-gavel');
    }
  }

  /**
   * Handle item sold event.
   * @param {Object} data — Sold data.
   */
  _onSold(data) {
    this._stopTimer();

    // Show sold phase
    if (this.$phaseIndicator) {
      this.$phaseIndicator.style.display = 'block';
      this.$phaseIndicator.className = 'phase-indicator sold';
    }
    if (this.$phaseText) {
      this.$phaseText.textContent = data.is_player ? 'YOU WON!' : `SOLD TO ${data.winner_name.toUpperCase()}`;
    }

    // Add to feed
    const text = data.narration || `SOLD: ${data.item.name} to ${data.winner_name} for ${data.amount.toLocaleString()}`;
    this._addFeedEntry(text, 'feed-sold');

    // Update NPC winning state
    if (!data.is_player && data.winner) {
      this._flashNPC(data.winner, 'npc-winning');
    }

    // Update lots progress
    this._updateLotProgress(data.lot_number, 'sold', `${data.amount.toLocaleString()}`);
  }

  /**
   * Handle unsold event.
   * @param {Object} data — Unsold data.
   */
  _onUnsold(data) {
    this._stopTimer();

    if (this.$phaseIndicator) {
      this.$phaseIndicator.style.display = 'block';
      this.$phaseIndicator.className = 'phase-indicator going-twice';
    }
    if (this.$phaseText) {
      this.$phaseText.textContent = 'NO SALE';
    }

    const text = data.narration || `UNSOLD: ${data.item.name}`;
    this._addFeedEntry(text, 'feed-unsold');

    this._updateLotProgress(data.lot_number, 'unsold', 'No Sale');
  }

  /**
   * Handle auction session complete.
   * @param {Object} data — Session summary.
   */
  _onAuctionComplete(data) {
    this._stopTimer();
    this.currentLot = null;

    // Switch to complete view
    if (this.$lotIdle) this.$lotIdle.style.display = 'none';
    if (this.$lotActive) this.$lotActive.style.display = 'none';
    if (this.$lotComplete) this.$lotComplete.style.display = 'flex';

    // Render summary
    if (this.$sessionSummary) {
      let html = '';
      html += this._summaryLine('Items Sold', `${data.items_sold} / ${data.total_lots}`);
      html += this._summaryLine('Total Revenue', data.total_revenue.toLocaleString());
      html += this._summaryLine('Your Wins', data.player_wins.toString());
      html += this._summaryLine('Your Spending', data.player_spent.toLocaleString());
      html += this._summaryLine('Credits Left', data.player_credits_remaining.toLocaleString());

      if (data.player_items && data.player_items.length > 0) {
        html += '<div style="margin-top: 8px; font-size: 0.7rem; color: var(--auction-text-dim);">YOUR ITEMS:</div>';
        data.player_items.forEach(item => {
          html += this._summaryLine(item.name, `${item.paid.toLocaleString()} (${item.rarity})`);
        });
      }

      this.$sessionSummary.innerHTML = html;
    }

    // Reset button text
    if (this.$btnNew) this.$btnNew.textContent = 'NEW AUCTION SESSION';

    // Update stats
    this.socket.emit('get_state');
  }

  // ── UI Helpers ────────────────────────────────────────────────────
  // v1.50.0 [2026-03-22] — Feed entries, NPC flashing, gavel bar

  /**
   * Set the credits display.
   * @param {number} credits — Credit amount.
   */
  _setCredits(credits) {
    if (this.$credits) this.$credits.textContent = credits.toLocaleString();
  }

  /**
   * Add an entry to the activity feed.
   * @param {string} text — Feed text.
   * @param {string} cls — CSS class for the entry.
   */
  _addFeedEntry(text, cls = 'feed-bid') {
    if (!this.$bidFeed) return;

    // Remove empty placeholder
    const empty = this.$bidFeed.querySelector('.feed-empty');
    if (empty) empty.remove();

    const entry = document.createElement('div');
    entry.className = `feed-entry ${cls}`;
    entry.textContent = text;

    // Prepend (newest first)
    this.$bidFeed.prepend(entry);

    // Cap at 50 entries
    while (this.$bidFeed.children.length > 50) {
      this.$bidFeed.lastChild.remove();
    }
  }

  /**
   * Show gavel narration text with highlight animation.
   * @param {string} text — Gavel narration.
   * @param {string} type — Narration type.
   */
  _showGavel(text, type) {
    if (this.$gavelText) this.$gavelText.textContent = text;
    if (this.$gavelBar) {
      this.$gavelBar.classList.add('gavel-highlight');
      setTimeout(() => this.$gavelBar.classList.remove('gavel-highlight'), 2000);
    }
  }

  /**
   * Flash an NPC card with a temporary class.
   * @param {string} npcId — NPC identifier.
   * @param {string} cls — CSS class to apply.
   */
  _flashNPC(npcId, cls) {
    const card = this.$npcList ? this.$npcList.querySelector(`[data-npc="${npcId}"]`) : null;
    if (!card) return;

    // Remove all state classes first
    card.classList.remove('npc-bidding', 'npc-winning');
    card.classList.add(cls);

    // Remove after 3 seconds (unless it's winning — that persists)
    if (cls !== 'npc-winning') {
      setTimeout(() => card.classList.remove(cls), 3000);
    }
  }

  /**
   * Update NPC panel from auction state data.
   * @param {Object} npcs — NPC data map.
   */
  _updateNPCs(npcs) {
    if (!this.$npcList) return;
    Object.entries(npcs).forEach(([id, npc]) => {
      const card = this.$npcList.querySelector(`[data-npc="${id}"]`);
      if (!card) return;

      const status = card.querySelector('.npc-status');
      if (status) {
        if (!npc.active) {
          status.textContent = 'Out';
          status.className = 'npc-status npc-out';
          card.classList.add('npc-broke');
        } else {
          status.textContent = npc.budget_hint;
          status.className = 'npc-status npc-active';
          card.classList.remove('npc-broke');
        }
      }
    });
  }

  /**
   * Render lots progress sidebar from session data.
   * @param {Array} lots — Lots summary array.
   * @param {number} currentIdx — Current lot index.
   */
  _renderLotsProgress(lots, currentIdx) {
    if (!this.$lotsProgress) return;
    this.$lotsProgress.innerHTML = '';
    lots.forEach((lot, i) => {
      const div = document.createElement('div');
      let cls = 'lot-progress-item';
      if (i === currentIdx) cls += ' lot-current';
      if (lot.status === 'sold') cls += ' lot-sold';
      if (lot.status === 'unsold') cls += ' lot-unsold';
      div.className = cls;

      const statusCls = `status-${lot.status}`;
      let statusText = lot.status;
      if (lot.status === 'sold') statusText = lot.sold_for ? lot.sold_for.toLocaleString() : 'Sold';

      div.innerHTML = `
        <span class="lot-progress-num">Lot ${lot.lot_number}</span>
        <span class="lot-progress-name">${lot.item_name}</span>
        <span class="lot-progress-status ${statusCls}">${statusText}</span>
      `;
      this.$lotsProgress.appendChild(div);
    });
  }

  /**
   * Update a single lot in the progress sidebar.
   * @param {number} lotNum — Lot number.
   * @param {string} status — New status.
   * @param {string} text — Status text.
   */
  _updateLotProgress(lotNum, status, text) {
    if (!this.$lotsProgress) return;
    const items = this.$lotsProgress.querySelectorAll('.lot-progress-item');
    items.forEach(item => {
      const numEl = item.querySelector('.lot-progress-num');
      if (numEl && numEl.textContent.includes(lotNum.toString())) {
        item.classList.remove('lot-current');
        item.classList.add(`lot-${status}`);
        const statusEl = item.querySelector('.lot-progress-status');
        if (statusEl) {
          statusEl.className = `lot-progress-status status-${status}`;
          statusEl.textContent = text;
        }
      }
    });
  }

  /**
   * Generate a summary line HTML snippet.
   * @param {string} label — Line label.
   * @param {string} value — Line value.
   * @returns {string} HTML string.
   */
  _summaryLine(label, value) {
    return `<div class="summary-line"><span class="summary-label">${label}</span><span class="summary-value">${value}</span></div>`;
  }

  /** Request a full state refresh from the server. */
  refresh() {
    if (this.socket) this.socket.emit('get_state');
  }
}

// ──── Bootstrap ─────────────────────────────────────────────────────────
// v1.50.0 [2026-03-22] — Renamed to avoid const redeclaration

const auctionApp = new AuctionController();

document.addEventListener('DOMContentLoaded', () => {
  auctionApp.init();
});
