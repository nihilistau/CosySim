/**
 * apps/markets.js — Markets app ("The Exchange") for the NeonOS desktop.
 * =====================================================================
 * v1.63.0 [2026-06-16] — D-T2: surfaces the ONE engine economy
 *   (engine.world.market.get_market) — the SAME live Market The Grid trades
 *   in D-T1 — as a neon broker terminal. Reads + trades via:
 *     GET  /api/markets/state        -> {district, goods[], inventory[], credits, stats}
 *     POST /api/markets/buy          -> {good_id, quantity} → engine buy + fresh state
 *     POST /api/markets/sell         -> {good_id, quantity} → engine sell + fresh state
 *   UI: a live ticker/table of goods (name, price, ▲/▼/▬ change, category,
 *   illegal flag), the player's positions/inventory + credits, and broker
 *   buy/sell controls (qty + buy/sell) that toast the result and refresh.
 *   Prices MATCH The Grid because both call the same get_market() district.
 *   Polls /api/markets/state (~12s) for live prices. 0 uncaught console errors.
 *
 * CONNECTS: window.ES registry API, executive_suite_scene /api/markets/*
 */
(function () {
  'use strict';
  if (!window.ES) return;
  var ES = window.ES;

  /** Inject scoped styles once (self-contained; uses the OS CSS variables). */
  function injectStyles() {
    if (document.getElementById('es-mk-styles')) return;
    var css = [
      '.es-mk{display:flex;flex-direction:column;height:100%;font-size:13px;color:var(--es-neutral-300);}',
      '.es-mk__bar{display:flex;align-items:center;gap:14px;padding:8px 12px;border-bottom:1px solid rgba(var(--es-rgb),0.18);background:rgba(var(--es-rgb),0.04);flex:0 0 auto;}',
      '.es-mk__title{font-family:Orbitron,sans-serif;letter-spacing:.08em;color:var(--es);text-shadow:0 0 8px var(--es-glow);font-size:13px;}',
      '.es-mk__district{color:var(--es-neutral-500);font-size:11px;letter-spacing:.05em;}',
      '.es-mk__credits{margin-left:auto;font-family:Orbitron,sans-serif;color:var(--es-amber);text-shadow:0 0 8px rgba(var(--es-amber-rgb),.4);}',
      '.es-mk__body{display:flex;flex:1 1 auto;min-height:0;}',
      '.es-mk__main{flex:1 1 auto;min-width:0;display:flex;flex-direction:column;}',
      '.es-mk__side{flex:0 0 210px;border-left:1px solid rgba(var(--es-rgb),0.14);display:flex;flex-direction:column;background:rgba(0,0,0,.18);}',
      '.es-mk__scroll{overflow:auto;flex:1 1 auto;min-height:0;}',
      '.es-mk__tbl{width:100%;border-collapse:collapse;}',
      '.es-mk__tbl th{position:sticky;top:0;background:var(--es-neutral-900);color:var(--es-neutral-500);font-weight:600;text-align:left;font-size:10px;letter-spacing:.08em;text-transform:uppercase;padding:7px 10px;border-bottom:1px solid rgba(var(--es-rgb),0.18);z-index:1;}',
      '.es-mk__tbl td{padding:7px 10px;border-bottom:1px solid rgba(255,255,255,.04);white-space:nowrap;}',
      '.es-mk__row{cursor:pointer;}',
      '.es-mk__row:hover{background:rgba(var(--es-rgb),0.08);}',
      '.es-mk__row.sel{background:rgba(var(--es-rgb),0.13);}',
      '.es-mk__name{color:var(--es-neutral-300);}',
      '.es-mk__cat{color:var(--es-neutral-500);font-size:11px;text-transform:capitalize;}',
      '.es-mk__price{font-family:Orbitron,sans-serif;text-align:right;color:var(--es-neutral-300);}',
      '.es-mk__t{text-align:center;font-weight:700;}',
      '.es-mk__t.up{color:var(--es-green);}.es-mk__t.dn{color:var(--es-red);}.es-mk__t.fl{color:var(--es-neutral-600);}',
      '.es-mk__ill{color:var(--es-red);border:1px solid var(--es-red);border-radius:4px;font-size:9px;padding:1px 4px;letter-spacing:.05em;}',
      '.es-mk__side-hd{padding:8px 12px;font-size:10px;letter-spacing:.08em;text-transform:uppercase;color:var(--es-neutral-500);border-bottom:1px solid rgba(var(--es-rgb),0.14);}',
      '.es-mk__pos{padding:7px 12px;border-bottom:1px solid rgba(255,255,255,.04);display:flex;justify-content:space-between;gap:8px;}',
      '.es-mk__pos b{color:var(--es-neutral-300);font-weight:500;}',
      '.es-mk__pos span{color:var(--es-neutral-500);font-size:11px;}',
      '.es-mk__empty{padding:18px 12px;color:var(--es-neutral-600);text-align:center;font-size:12px;}',
      '.es-mk__broker{flex:0 0 auto;padding:10px 12px;border-top:1px solid rgba(var(--es-rgb),0.18);background:rgba(var(--es-rgb),0.04);display:flex;align-items:center;gap:10px;flex-wrap:wrap;}',
      '.es-mk__sel-name{font-family:Orbitron,sans-serif;color:var(--es);min-width:120px;}',
      '.es-mk__qty{width:62px;background:var(--es-neutral-800);border:1px solid rgba(var(--es-rgb),0.25);color:var(--es-neutral-300);border-radius:6px;padding:5px 7px;font-family:inherit;}',
      '.es-mk__btn{border:1px solid;border-radius:6px;padding:5px 14px;cursor:pointer;background:transparent;font-family:Orbitron,sans-serif;font-size:11px;letter-spacing:.06em;}',
      '.es-mk__btn--buy{color:var(--es-green);border-color:var(--es-green);}',
      '.es-mk__btn--buy:hover{background:rgba(34,197,94,.15);}',
      '.es-mk__btn--sell{color:var(--es-amber);border-color:var(--es-amber);}',
      '.es-mk__btn--sell:hover{background:rgba(245,158,11,.15);}',
      '.es-mk__btn:disabled{opacity:.4;cursor:default;}',
      '.es-mk__hint{color:var(--es-neutral-600);font-size:11px;margin-left:auto;}',
    ].join('');
    var s = document.createElement('style');
    s.id = 'es-mk-styles';
    s.textContent = css;
    document.head.appendChild(s);
  }

  /** Format an integer credit amount with thin separators. */
  function fmt(n) {
    n = Math.round(Number(n) || 0);
    return n.toString().replace(/\B(?=(\d{3})+(?!\d))/g, ',');
  }

  function trendClass(t) {
    if (t === '▲') return 'up';
    if (t === '▼') return 'dn';
    return 'fl';
  }

  function ready(fn) {
    if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', fn);
    else fn();
  }

  ready(function () {
  injectStyles();
  ES.registerApp('markets', {
    title: 'Markets', icon: '📈', color: 'gr', pinned: true,
    width: 760, height: 480,
    render: function (body, win) {
      body.innerHTML = '';

      var districtEl = ES.el('span', { class: 'es-mk__district', text: '' });
      var creditsEl = ES.el('span', { class: 'es-mk__credits', text: '₵ —' });
      var bar = ES.el('div', { class: 'es-mk__bar' }, [
        ES.el('span', { class: 'es-mk__title', text: 'THE EXCHANGE' }),
        districtEl,
        creditsEl,
      ]);

      var tbody = ES.el('tbody');
      var table = ES.el('table', { class: 'es-mk__tbl' }, [
        ES.el('thead', {}, [ES.el('tr', {}, [
          ES.el('th', { text: 'Good' }),
          ES.el('th', { text: 'Category' }),
          ES.el('th', { text: 'Price', style: { textAlign: 'right' } }),
          ES.el('th', { text: 'Chg', style: { textAlign: 'center' } }),
          ES.el('th', { text: 'Flag' }),
        ])]),
        tbody,
      ]);
      var scroll = ES.el('div', { class: 'es-mk__scroll' }, [table]);

      // Broker controls
      var selName = ES.el('span', { class: 'es-mk__sel-name', text: 'select a good' });
      var qty = ES.el('input', { class: 'es-mk__qty', type: 'number', value: '1', min: '1' });
      var buyBtn = ES.el('button', { class: 'es-mk__btn es-mk__btn--buy', text: 'BUY', disabled: 'disabled' });
      var sellBtn = ES.el('button', { class: 'es-mk__btn es-mk__btn--sell', text: 'SELL', disabled: 'disabled' });
      var hint = ES.el('span', { class: 'es-mk__hint', text: 'live · same economy as The Grid' });
      var broker = ES.el('div', { class: 'es-mk__broker' }, [selName, qty, buyBtn, sellBtn, hint]);

      var main = ES.el('div', { class: 'es-mk__main' }, [scroll, broker]);

      // Positions sidebar
      var posList = ES.el('div', { class: 'es-mk__scroll' });
      var side = ES.el('div', { class: 'es-mk__side' }, [
        ES.el('div', { class: 'es-mk__side-hd', text: 'Positions' }),
        posList,
      ]);

      body.appendChild(ES.el('div', { class: 'es-mk', style: { '--es': 'var(--es-green)' } }, [
        bar,
        ES.el('div', { class: 'es-mk__body' }, [main, side]),
      ]));

      var selectedId = null;
      var selectedName = null;
      var goods = [];
      var pollTimer = null;

      function selectGood(g) {
        selectedId = g.good_id;
        selectedName = g.name;
        selName.textContent = g.name;
        buyBtn.disabled = false;
        sellBtn.disabled = false;
        Array.prototype.forEach.call(tbody.children, function (tr) {
          tr.classList.toggle('sel', tr.getAttribute('data-id') === selectedId);
        });
      }

      function renderGoods() {
        tbody.innerHTML = '';
        if (!goods.length) {
          tbody.appendChild(ES.el('tr', {}, [
            ES.el('td', { colspan: '5' }, [
              ES.el('div', { class: 'es-mk__empty', text: 'The exchange is dark. No goods listed.' }),
            ]),
          ]));
          return;
        }
        goods.forEach(function (g) {
          var tr = ES.el('tr', {
            class: 'es-mk__row' + (g.good_id === selectedId ? ' sel' : ''),
            'data-id': g.good_id,
          }, [
            ES.el('td', {}, [ES.el('span', { class: 'es-mk__name', text: g.name })]),
            ES.el('td', {}, [ES.el('span', { class: 'es-mk__cat', text: g.category || '—' })]),
            ES.el('td', { class: 'es-mk__price', text: '₵' + fmt(g.price) }),
            ES.el('td', {}, [ES.el('div', { class: 'es-mk__t ' + trendClass(g.trend), text: g.trend || '▬' })]),
            ES.el('td', {}, g.illegal ? [ES.el('span', { class: 'es-mk__ill', text: 'ILLEGAL' })] : []),
          ]);
          tr.addEventListener('click', function () { selectGood(g); });
          tbody.appendChild(tr);
        });
      }

      function renderPositions(inv) {
        posList.innerHTML = '';
        if (!inv || !inv.length) {
          posList.appendChild(ES.el('div', { class: 'es-mk__empty', text: 'No tradable positions.' }));
          return;
        }
        inv.forEach(function (p) {
          posList.appendChild(ES.el('div', { class: 'es-mk__pos' }, [
            ES.el('div', {}, [
              ES.el('b', { text: p.name }),
              ES.el('div', { class: 'es-mk__cat', text: 'x' + p.quantity + ' · ₵' + fmt(p.value) }),
            ]),
            ES.el('span', { text: '₵' + fmt(p.price) }),
          ]));
        });
      }

      function applyState(d) {
        if (!d) return;
        districtEl.textContent = '· ' + (d.district || '');
        creditsEl.textContent = '₵ ' + fmt(d.credits);
        goods = (d.goods || []).slice();
        renderGoods();
        renderPositions(d.inventory || []);
      }

      function refresh() {
        return fetch('/api/markets/state')
          .then(function (r) { return r.json(); })
          .then(function (d) { applyState(d); })
          .catch(function () {
            tbody.innerHTML = '';
            tbody.appendChild(ES.el('tr', {}, [ES.el('td', { colspan: '5' }, [
              ES.el('div', { class: 'es-mk__empty', text: 'Exchange offline.' }),
            ])]));
          });
      }

      function trade(action) {
        if (!selectedId) return;
        var q = Math.max(1, parseInt(qty.value, 10) || 1);
        buyBtn.disabled = true; sellBtn.disabled = true;
        fetch('/api/markets/' + action, {
          method: 'POST', headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ good_id: selectedId, quantity: q }),
        }).then(function (r) { return r.json(); })
          .then(function (res) {
            buyBtn.disabled = false; sellBtn.disabled = false;
            if (res.state) applyState(res.state);
            if (!res.success) {
              ES.toast((action === 'buy' ? 'Buy' : 'Sell') + ' failed: ' + (res.error || 'rejected'), 'error');
              return;
            }
            var verb = action === 'buy' ? 'Bought' : 'Sold';
            var amt = action === 'buy' ? ('−₵' + fmt(res.total)) : ('+₵' + fmt(res.total));
            ES.toast(verb + ' ' + res.quantity + '× ' + (res.good_name || selectedName) + ' (' + amt + ')', 'success');
          })
          .catch(function () {
            buyBtn.disabled = false; sellBtn.disabled = false;
            ES.toast('Trade failed', 'error');
          });
      }

      buyBtn.addEventListener('click', function () { trade('buy'); });
      sellBtn.addEventListener('click', function () { trade('sell'); });
      qty.addEventListener('keydown', function (e) { if (e.key === 'Enter') trade('buy'); });

      // Live polling (~12s) — prices visibly move as the economy ticks.
      refresh();
      pollTimer = setInterval(refresh, 12000);
      win._mkPoll = pollTimer;
    },
    onClose: function (win) {
      if (win && win._mkPoll) { clearInterval(win._mkPoll); win._mkPoll = null; }
    },
  });
  });
})();
