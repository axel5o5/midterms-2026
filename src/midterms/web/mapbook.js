/* Map drawing for the 2026 midterm pages. Plain JS, no libraries.
   Used by the published map page (MapBook.app) and the live dashboard's map panel
   (MapBook.drawStates / drawTiles / classP). Colors are CSS variables:
   --c0..--c8 (P(D) from Safe R to Safe D), --g0..--g6 (ours minus markets),
   --s0..--s6 (2025 swing), --none (no race). */
(function () {
  const MB = {};
  const NS = 'http://www.w3.org/2000/svg';
  MB.CLASS_NAMES = ['Safe R', 'Likely R', 'Lean R', 'Tilt R', 'Toss-up', 'Tilt D', 'Lean D', 'Likely D', 'Safe D'];
  MB.classP = (p) => p == null ? null : p < 0.05 ? 0 : p < 0.15 ? 1 : p < 0.35 ? 2 : p < 0.45 ? 3 : p <= 0.55 ? 4 : p <= 0.65 ? 5 : p <= 0.85 ? 6 : p <= 0.95 ? 7 : 8;
  MB.classMargin = (m) => { if (m == null) return null; const a = Math.abs(m), k = a < 1 ? 0 : a < 3 ? 1 : a < 6 ? 2 : a < 10 ? 3 : 4; return m >= 0 ? 4 + k : 4 - k; };
  MB.classScore = (s) => { if (s == null) return null; const a = Math.abs(s), k = a < 0.25 ? 0 : a < 0.75 ? 1 : a < 1.5 ? 2 : a < 2.5 ? 3 : 4; return s >= 0 ? 4 + k : 4 - k; };
  MB.GAP_NAMES = ['20+ pts lower', '10-20 lower', '5-10 lower', 'within 5', '5-10 higher', '10-20 higher', '20+ pts higher'];
  MB.classGap = (g) => g == null ? null : g < -0.2 ? 0 : g < -0.1 ? 1 : g < -0.05 ? 2 : g <= 0.05 ? 3 : g <= 0.1 ? 4 : g <= 0.2 ? 5 : 6;
  MB.SWING_NAMES = ['R 10+', 'R 5-10', 'R 2-5', 'under 2', 'D 2-5', 'D 5-10', 'D 10+'];
  MB.classSwing = (s) => s == null ? null : s < -10 ? 0 : s < -5 ? 1 : s < -2 ? 2 : s <= 2 ? 3 : s <= 5 ? 4 : s <= 10 ? 5 : 6;
  MB.fill = (scale, k) => k == null ? 'var(--none)' : `var(--${scale}${k})`;
  MB.pct = (p) => p == null ? 'n/a' : p > 0.99 ? '>99%' : p < 0.01 ? '<1%' : Math.round(100 * p) + '%';
  MB.margin = (m) => m == null ? 'n/a' : (m >= 0 ? 'D+' : 'R+') + Math.abs(m).toFixed(1);
  MB.market = (r) => { const v = [r.kalshi, r.polymarket].filter(x => x != null); return v.length ? v.reduce((a, b) => a + b) / v.length : null; };
  MB.esc = (s) => String(s ?? '').replace(/[&<>"]/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c]));

  function el(tag, attrs, parent) {
    const e = document.createElementNS(NS, tag);
    for (const [k, v] of Object.entries(attrs || {})) e.setAttribute(k, v);
    if (parent) parent.appendChild(e);
    return e;
  }
  MB.el = el;

  /* paths: {key: d}; fill(key) -> css color; handlers get the key */
  MB.drawPaths = function (svg, paths, viewBox, fill, on = {}) {
    svg.innerHTML = '';
    svg.setAttribute('viewBox', viewBox.join(' '));
    const g = el('g', {}, svg);
    for (const [k, d] of Object.entries(paths)) {
      const p = el('path', { d, fill: fill(k), class: 'shape', 'data-key': k, tabindex: on.click ? 0 : -1 }, g);
      if (on.hover) { p.addEventListener('mousemove', (e) => on.hover(k, e)); p.addEventListener('mouseleave', () => on.hover(null)); }
      if (on.click) { p.addEventListener('click', () => on.click(k)); p.addEventListener('keydown', (e) => { if (e.key === 'Enter') on.click(k); }); }
    }
    return svg;
  };
  MB.drawStates = (svg, states, fill, on) => MB.drawPaths(svg, states, [0, 0, 975, 610], fill, on);

  MB.drawTiles = function (svg, layout, fill, on = {}) {
    svg.innerHTML = '';
    const s = 10;
    svg.setAttribute('viewBox', `-2 -2 ${layout.w * s + 4} ${layout.h * s + 4}`);
    for (const [st, [x, y]] of Object.entries(layout.labels)) {
      const t = el('text', { x: x * s, y: y * s + 3, class: 'tile-label', 'text-anchor': 'middle' }, svg);
      t.textContent = st;
    }
    for (const [k, [x, y]] of Object.entries(layout.tiles)) {
      const r = el('rect', { x: x * s + 0.6, y: y * s + 0.6, width: s - 1.2, height: s - 1.2, rx: 1.4, fill: fill(k), class: 'shape', 'data-key': k, tabindex: on.click ? 0 : -1 }, svg);
      if (on.hover) { r.addEventListener('mousemove', (e) => on.hover(k, e)); r.addEventListener('mouseleave', () => on.hover(null)); }
      if (on.click) { r.addEventListener('click', () => on.click(k)); r.addEventListener('keydown', (e) => { if (e.key === 'Enter') on.click(k); }); }
    }
    return svg;
  };

  MB.select = function (svg, key) {
    svg.querySelectorAll('.shape.sel').forEach(n => n.classList.remove('sel'));
    const n = key && svg.querySelector(`[data-key="${key}"]`);
    if (n) { n.classList.add('sel'); n.parentNode.appendChild(n); }
  };

  MB.tip = function (tipEl, html, e) {
    if (!html) { tipEl.hidden = true; return; }
    tipEl.innerHTML = html; tipEl.hidden = false;
    const pad = 14, w = tipEl.offsetWidth, h = tipEl.offsetHeight;
    let x = e.clientX + pad, y = e.clientY + pad;
    if (x + w > innerWidth - 8) x = e.clientX - w - pad;
    if (y + h > innerHeight - 8) y = e.clientY - h - pad;
    tipEl.style.left = x + 'px'; tipEl.style.top = y + 'px';
  };

  /* Agreement rows: each source's P(D) as a dot on its own row of one 0-100 scale. items: [{label, p, kind}] */
  MB.strip = function (items, width = 520) {
    const its = items.filter(i => i.p != null);
    const lab = 92, val = 44, pad = 6, x0 = lab, x1 = width - val, rowH = 20, top = 16;
    const x = (p) => x0 + p * (x1 - x0);
    const H = top + its.length * rowH + 4;
    let s = `<svg class="strip" viewBox="0 0 ${width} ${H}" role="img" aria-label="Each source's chance for the Democrat">`;
    for (const t of [0, 0.25, 0.5, 0.75, 1]) {
      s += `<line x1="${x(t)}" x2="${x(t)}" y1="${top - 3}" y2="${H - 2}" class="strip-grid${t === 0.5 ? ' mid' : ''}"/>`;
      s += `<text x="${x(t)}" y="${top - 6}" class="strip-tick" text-anchor="middle">${Math.round(t * 100)}%</text>`;
    }
    its.forEach((q, i) => {
      const y = top + i * rowH + rowH / 2;
      const k = MB.classP(q.p);
      s += `<text x="${lab - pad - 4}" y="${y + 4}" text-anchor="end" class="strip-label ${q.kind}">${MB.esc(q.label)}</text>`;
      s += `<line x1="${x(0.5)}" x2="${x(q.p)}" y1="${y}" y2="${y}" class="strip-bar" stroke="var(--c${k})"/>`;
      s += `<circle cx="${x(q.p)}" cy="${y}" r="${q.kind === 'ours' ? 6 : 5}" class="strip-dot ${q.kind}" fill="var(--c${k})"/>`;
      s += `<text x="${x1 + pad + 4}" y="${y + 4}" class="strip-val ${q.kind}">${MB.pct(q.p)}</text>`;
    });
    return s + '</svg>';
  };

  /* ---------------------------------------------------------------------------- */
  /* The published page                                                           */
  /* ---------------------------------------------------------------------------- */
  MB.app = function (BOOK) {
    const $ = (id) => document.getElementById(id);
    const by = Object.fromEntries(BOOK.races.map(r => [r.race, r]));
    const state = { office: 'S', color: 'ours', sel: 'SEN-IA' };
    const tip = $('tip');

    const COLORS = {
      S: [['ours', 'Holdout'], ['split_ticket', 'Split Ticket'], ['polls', 'Polls'], ['raters', 'Raters'], ['kalshi', 'Kalshi'], ['polymarket', 'Polymarket'], ['gap', 'Holdout vs markets']],
      H: [['ours', 'Holdout'], ['split_ticket', 'Split Ticket'], ['kalshi', 'Kalshi'], ['polymarket', 'Polymarket'], ['gap', 'Holdout vs markets']],
      G: [['polls', 'Polls'], ['raters', 'Raters'], ['kalshi', 'Kalshi'], ['polymarket', 'Polymarket']],
    };
    const key = (office, st) => office === 'S' ? `SEN-${st}` : `GOV-${st}`;
    // venues with no data in this build (the public site has Polymarket only) drop out of the menus
    const HAS = { kalshi: BOOK.races.some(r => r.kalshi != null), polymarket: BOOK.races.some(r => r.polymarket != null) };
    for (const v of ['kalshi', 'polymarket']) {
      if (!HAS[v]) for (const o of Object.keys(COLORS)) COLORS[o] = COLORS[o].filter(c => c[0] !== v);
    }

    function value(r, src) {
      if (!r) return { k: null, text: 'No race' };
      if (src === 'polls') return { k: MB.classMargin(r.n_polls ? r.polls_margin : null), text: r.n_polls ? `${MB.margin(r.polls_margin)} (${r.n_polls} polls)` : 'No recent polls', scale: 'c' };
      if (src === 'raters') return { k: MB.classScore(r.rating_score), text: r.rating_text || 'n/a', scale: 'c' };
      if (src === 'gap') { const m = MB.market(r); const g = r.ours != null && m != null ? r.ours - m : null; return { k: MB.classGap(g), text: g == null ? 'n/a' : `${g > 0 ? '+' : ''}${Math.round(100 * g)} pts vs markets`, scale: 'g' }; }
      return { k: MB.classP(r[src]), text: MB.pct(r[src]), scale: 'c' };
    }

    function legend() {
      const isGap = state.color === 'gap';
      const names = isGap ? MB.GAP_NAMES : state.color === 'polls' ? ['R 10+', 'R 6-10', 'R 3-6', 'R 1-3', 'within 1', 'D 1-3', 'D 3-6', 'D 6-10', 'D 10+'] : MB.CLASS_NAMES;
      const scale = isGap ? 'g' : 'c';
      $('legend').innerHTML = (isGap ? '<span class="lg-cap">Holdout’s chance for the Democrat minus the market average</span>' : '') +
        names.map((n, i) => `<span class="lg"><i style="background:var(--${scale}${i})"></i>${n}</span>`).join('') +
        `<span class="lg"><i style="background:var(--none)"></i>${state.office === 'H' ? 'no contest' : 'not up'}</span>`;
    }

    function fillFor(k) { const v = value(by[k], state.color); return MB.fill(v.scale || 'c', v.k); }

    function hover(k, e) {
      if (!k) return MB.tip(tip, null);
      const rk = state.office === 'H' ? k : key(state.office, k), r = by[rk];
      if (!r) return MB.tip(tip, `<b>${k}</b><br>No race this year`, e);
      const m = MB.market(r);
      MB.tip(tip, `<b>${MB.esc(r.name)}</b>${r.dem || r.rep ? `<br><span class="muted">${MB.esc(r.dem || '?')} v ${MB.esc(r.rep || '?')}</span>` : ''}
        <div class="tip-grid">${r.ours != null ? `<span>Holdout</span><b>${MB.pct(r.ours)}</b>` : ''}<span>Markets</span><b>${MB.pct(m)}</b>
        ${state.color !== 'ours' && state.color !== 'kalshi' && state.color !== 'polymarket' ? `<span>${COLORS[state.office].find(c => c[0] === state.color)[1]}</span><b>${MB.esc(value(r, state.color).text)}</b>` : ''}</div>`, e);
    }

    function click(k) { const rk = state.office === 'H' ? k : key(state.office, k); if (by[rk]) { state.sel = rk; detail(); MB.select($('map'), k); } }

    function draw() {
      const svg = $('map');
      if (state.office === 'H') MB.drawTiles(svg, BOOK.tiles, fillFor, { hover, click });
      else MB.drawStates(svg, BOOK.geo.states, (st) => fillFor(key(state.office, st)), { hover, click });
      const selShape = state.office === 'H' ? state.sel : state.sel.split('-')[1];
      if (by[state.sel] && by[state.sel].office === state.office) MB.select(svg, selShape);
      legend();
      $('color').innerHTML = COLORS[state.office].map(([v, n]) => `<button data-c="${v}" class="${v === state.color ? 'on' : ''}">${n}</button>`).join('');
      $('maptitle').textContent = { S: 'Senate', H: 'House', G: 'Governors' }[state.office];
    }

    function detail() {
      const r = by[state.sel]; if (!r) return;
      const m = MB.market(r);
      const items = [
        { label: 'Holdout', p: r.ours, kind: 'ours' }, { label: 'Split Ticket', p: r.split_ticket, kind: 'src' },
        { label: 'Kalshi', p: r.kalshi, kind: 'mkt' }, { label: 'Polymarket', p: r.polymarket, kind: 'mkt' }];
      const rows = [
        ['Holdout', r.ours != null ? `${MB.pct(r.ours)} <span class="muted">${MB.margin(r.ours_margin)} ±${r.ours_sd?.toFixed(1)}</span>` : '<span class="muted">not modelled</span>'],
        ['Split Ticket', r.split_ticket != null ? `${MB.pct(r.split_ticket)} <span class="muted">${MB.margin(r.split_ticket_margin)}</span>` : 'n/a'],
        ['Polls', r.office === 'H' ? (r.n_polls ? `${r.n_polls} district poll${r.n_polls > 1 ? 's' : ''}${r.poll_avg_adj != null ? `, adjusted ${MB.margin(r.poll_avg_adj)}` : ''}` : 'none') : (r.n_polls ? `${MB.margin(r.polls_margin)} <span class="muted">${r.n_polls} in 30 days</span>` : 'none in 30 days')],
        ...(HAS.kalshi ? [['Kalshi', MB.pct(r.kalshi)]] : []), ...(HAS.polymarket ? [['Polymarket', MB.pct(r.polymarket)]] : []),
        ['Raters', MB.esc(r.rating_text || 'n/a')]];
      $('detail').innerHTML = `
        <div class="d-kicker">${{ S: 'Senate', H: 'House', G: 'Governor' }[r.office]}${r.held_by ? ` · held by ${r.held_by}` : ''}</div>
        <h2>${MB.esc(r.name)}</h2>
        ${r.dem || r.rep ? `<div class="d-cands"><span class="dem">${MB.esc(r.dem || 'Democrat')}</span> v <span class="rep">${MB.esc(r.rep || 'Republican')}</span></div>` : ''}
        <p class="d-head">${MB.esc(r.reasoning.headline)}</p>
        ${MB.strip(items)}
        <table class="d-src">${rows.map(([a, b]) => `<tr><th>${a}</th><td>${b}</td></tr>`).join('')}</table>
        ${r.variants ? `<h3>Other versions of Holdout</h3><table class="d-src">${Object.entries(r.variants).map(([k, v]) => `<tr><th>${k === 'robust' ? 'Main (tested)' : k[0].toUpperCase() + k.slice(1)}</th><td>${MB.pct(v)}</td></tr>`).join('')}</table>` : ''}
        <h3>How Holdout got there</h3>
        <ol class="d-steps">${r.reasoning.lines.map(l => `<li>${MB.esc(l)}</li>`).join('')}</ol>
        ${r.ratings && Object.keys(r.ratings).length ? `<div class="chips">${Object.entries(r.ratings).map(([k, v]) => `<span class="chip" style="--chip:var(--c${MB.classScore(v === 'Tossup' ? 0 : (v.endsWith('D') ? 1 : -1) * ({ Safe: 3, Solid: 3, Likely: 2, Lean: 1, Tilt: 0.5 }[v.split(' ')[0]] || 0))})">${MB.esc(k)} <b>${MB.esc(v)}</b></span>`).join('')}</div>` : ''}`;
    }

    function disagreements() {
      const gaps = BOOK.races.filter(r => r.ours != null && MB.market(r) != null).map(r => ({ r, g: r.ours - MB.market(r) }));
      const big = gaps.filter(x => Math.abs(x.g) >= 0.05).sort((a, b) => Math.abs(b.g) - Math.abs(a.g));
      const row = ({ r, g }) => `<tr data-race="${r.race}" tabindex="0"><td><b>${MB.esc(r.office === 'H' ? r.race : r.name)}</b></td><td class="n">${MB.pct(r.ours)}</td><td class="n">${MB.pct(MB.market(r))}</td>
          <td class="n"><span class="gap" style="--gap:var(--g${MB.classGap(g)})">${g > 0 ? '+' : ''}${Math.round(100 * g)}</span></td><td class="why">${MB.esc(r.reasoning.headline.replace(/^We're [^.]*\)\.\s*/, ''))}</td></tr>`;
      const head = `<thead><tr><th>Race</th><th class="n">Holdout</th><th class="n">Markets</th><th class="n">Gap</th><th>Why</th></tr></thead>`;
      const sen = big.filter(x => x.r.office === 'S'), hou = big.filter(x => x.r.office === 'H');
      $('disagree').innerHTML = `<div class="tbl-sub">Senate (${sen.length})</div><table class="tbl">${head}<tbody>${sen.map(row).join('')}</tbody></table>
        <div class="tbl-sub">House (top 12 of ${hou.length})</div><table class="tbl">${head}<tbody>${hou.slice(0, 12).map(row).join('')}</tbody></table>`;
      const hl = hou.filter(x => x.g < 0).length;
      $('house-note').textContent = `In the House, ${hou.length} races are 5+ points apart, and in ${hl} of them Holdout is lower on the Democrat than the markets are.`;
      $('disagree').querySelectorAll('tr[data-race]').forEach(tr => {
        const go = () => { const r = by[tr.dataset.race]; state.office = r.office; state.sel = r.race; if (!COLORS[r.office].some(c => c[0] === state.color)) state.color = 'ours'; setTab(); draw(); detail(); $('mapcard').scrollIntoView({ behavior: 'smooth', block: 'start' }); };
        tr.addEventListener('click', go); tr.addEventListener('keydown', (e) => { if (e.key === 'Enter') go(); });
      });
    }

    function control() {
      const c = BOOK.control;
      const card = (k, label, seats) => {
        const x = c[k];
        return `<div class="ctrl"><div class="ctrl-top"><span class="ctrl-label">${label}</span><span class="ctrl-big">${MB.pct(x.ours)}</span></div>
          <div class="ctrl-sub">${seats}</div>
          ${MB.strip([{ label: 'Holdout', p: x.ours, kind: 'ours' }, { label: 'Split Ticket', p: x.split_ticket, kind: 'src' }, { label: 'Kalshi', p: x.kalshi, kind: 'mkt' }, { label: 'Polymarket', p: x.polymarket, kind: 'mkt' }], 420)}</div>`;
      };
      $('control').innerHTML =
        card('S', 'Democrats win the Senate', `Holdout's seat range ${Math.round(c.S.seats.p10)}–${Math.round(c.S.seats.p90)} Democratic seats (80%), 51 needed${c.S.variants ? `. Other versions: one weight (Oct 30) ${MB.pct(c.S.variants['one weight (Oct 30)'])}, first ${MB.pct(c.S.variants['first version'])}, longer state record ${MB.pct(c.S.variants['longer state record'])}, no adjustments ${MB.pct(c.S.variants['no adjustments'])}` : ''}`) +
        card('H', 'Democrats win the House', `Holdout's median ${Math.round(c.H.seats.median)} seats, ${Math.round(c.H.seats.p10)}–${Math.round(c.H.seats.p90)} (80%), 218 needed`);
    }

    function swing() {
      const S = BOOK.swing2025;
      if (!S) { $('swing').innerHTML = '<p class="muted">2025 results not loaded.</p>'; return; }
      $('swing').innerHTML = S.states.map(s => `
        <figure class="swing-fig"><figcaption><b>${s.name} governor, 2025</b><span>${MB.margin(s.margin25)} vs Harris ${MB.margin(s.margin24)} in 2024: ${s.swing >= 0 ? 'D' : 'R'}+${Math.abs(s.swing).toFixed(1)} swing</span></figcaption>
        <svg id="sw-${s.st}" class="swing-map"></svg></figure>`).join('') +
        `<div class="legend">${MB.SWING_NAMES.map((n, i) => `<span class="lg"><i style="background:var(--s${i})"></i>${n}</span>`).join('')}<span class="lg-cap">swing in margin from the 2024 presidential result, points</span></div>`;
      for (const s of S.states) {
        const paths = Object.fromEntries(Object.entries(BOOK.geo.counties).filter(([f]) => f.startsWith(s.fips)));
        MB.drawPaths($(`sw-${s.st}`), paths, s.bbox, (f) => MB.fill('s', MB.classSwing(S.counties[f]?.swing)), {
          hover: (f, e) => { if (!f) return MB.tip(tip, null); const c = S.counties[f]; MB.tip(tip, c ? `<b>${MB.esc(c.county)}</b><div class="tip-grid"><span>2025</span><b>${MB.margin(c.margin25)}</b><span>2024</span><b>${MB.margin(c.margin24)}</b><span>Swing</span><b>${c.swing >= 0 ? 'D' : 'R'}+${Math.abs(c.swing).toFixed(1)}</b><span>Votes</span><b>${Math.round(c.total).toLocaleString()}</b></div>` : 'No data', e); } });
      }
    }

    function method() {
      const M = BOOK.method; if (!M) return;
      const none = M.scores.find(x => x.spec === 'none').rmse;
      const label = (k) => ({ 'pres (2024-style carry-over)': 'Previous presidential miss, one weight', 'pres split by direction': 'Previous presidential miss, by direction (kept)', 'hist (longer state record)': 'Longer state record', 'none': 'No adjustment', 'fade': 'Red-state fade' }[k] || (k.replace('pres', 'presidential miss').replace('hist', 'longer record').replace(/^./, c => c.toUpperCase())));
      const sc = M.scores.slice().sort((a, b) => a.rmse - b.rmse);
      const W = 640, lab = 310, rowH = 24, x0 = lab + 10, span = Math.max(...sc.map(x => Math.abs(x.rmse - none))) || 1;
      const half = (W - x0 - 110) / 2, zero = x0 + 50 + half;
      const px = (d) => zero + d / span * half;
      let svg = `<svg class="mchart" viewBox="0 0 ${W} ${sc.length * rowH + 30}" role="img" aria-label="Held-out polling miss by adjustment">`;
      svg += `<line x1="${zero}" x2="${zero}" y1="4" y2="${sc.length * rowH + 6}" class="mzero"/>`;
      sc.forEach((x, i) => {
        const d = x.rmse - none, y = 8 + i * rowH, keep = x.spec === 'pres split by direction';
        svg += `<text x="${lab}" y="${y + 13}" text-anchor="end" class="mlab${keep ? ' keep' : ''}">${MB.esc(label(x.spec))}</text>`;
        svg += `<rect x="${Math.min(zero, px(d))}" y="${y + 3}" width="${Math.max(1, Math.abs(px(d) - zero))}" height="14" rx="2" class="mbar${keep ? ' keep' : d > 0 ? ' worse' : ''}"/>`;
        svg += `<text x="${px(d) + (d < 0 ? -4 : 4)}" y="${y + 14}" text-anchor="${d < 0 ? 'end' : 'start'}" class="mval">${d > 0 ? '+' : ''}${d.toFixed(2)}</text>`;
      });
      svg += `<text x="${zero}" y="${sc.length * rowH + 24}" text-anchor="middle" class="mtick">change in average held-out miss, points (left is better)</text></svg>`;
      const Y = M.years, H = 150, bw = 26, gx = 70;
      const mx = Math.max(...Y.map(y => Math.max(Math.abs(y.carry - y.none), Math.abs(y.fade - y.none)))) || 1;
      const yy = (v) => 70 - v / mx * 50;
      let yr = `<svg class="mchart" viewBox="0 0 ${Y.length * gx + 74} ${H}" role="img" aria-label="Held-out change by year">`;
      yr += `<line x1="20" x2="${Y.length * gx + 64}" y1="70" y2="70" class="mzero"/>`;
      yr += `<text x="22" y="${yy(mx) + 4}" class="mtick">+${mx.toFixed(1)} hurt</text><text x="22" y="${yy(-mx) + 4}" class="mtick">−${mx.toFixed(1)} helped</text>`;
      Y.forEach((y, i) => {
        const cx = 64 + i * gx, dc = y.carry - y.none, df = y.fade - y.none;
        yr += `<rect x="${cx}" y="${Math.min(70, yy(dc))}" width="${bw}" height="${Math.abs(yy(dc) - 70)}" class="mbar keep"><title>${y.year} carry-over ${dc.toFixed(2)}</title></rect>`;
        yr += `<rect x="${cx + bw + 2}" y="${Math.min(70, yy(df))}" width="${bw}" height="${Math.abs(yy(df) - 70)}" class="mbar"><title>${y.year} fade ${df.toFixed(2)}</title></rect>`;
        yr += `<text x="${cx + bw}" y="${H - 8}" text-anchor="middle" class="mtick">${y.year}</text>`;
      });
      yr += `</svg>`;
      $('method').innerHTML = `
        <div class="mgrid"><div><h3>Each adjustment, scored on midterms it wasn't fit to</h3>${svg}</div>
        <div><h3>By year: kept carry-over vs the dropped fade</h3>${yr}
          <div class="legend"><span class="lg"><i style="background:var(--dem)"></i>presidential miss by direction (kept)</span><span class="lg"><i style="background:var(--ink-3)"></i>red-state fade (dropped)</span><span class="lg-cap">below the line = fewer points of miss</span></div></div></div>
        <p class="sec-note">${M.races} Senate and governor races in ${M.cycles} midterm years (2002–2022). Each adjustment was fitted on every year but one and scored on the year left out. The kept carry-over uses ${(100 * M.weight_d).toFixed(0)}% when polls underrated Democrats (90% range ${(100 * M.lo_d).toFixed(0)}% to ${(100 * M.hi_d).toFixed(0)}%) and ${(100 * M.weight_r).toFixed(0)}% when they underrated Republicans (${(100 * M.lo_r).toFixed(0)}% to ${(100 * M.hi_r).toFixed(0)}%), beyond the national miss. Ranges resample whole years. Split this way it scores slightly better on the years left out, but those predictions came out about half a point too Democratic on average in both directions; the single 42% weight was within a tenth of a point. The carry-over helped in 2010, 2014, 2018 and 2022 and hurt in 2002 and 2006. The other versions stay on the race panels as variations, to be scored against the results.</p>`;
    }

    function setTab() { document.querySelectorAll('#office button').forEach(b => b.classList.toggle('on', b.dataset.o === state.office)); }

    $('office').addEventListener('click', (e) => {
      const o = e.target.closest('button')?.dataset.o; if (!o) return;
      state.office = o;
      if (!COLORS[o].some(c => c[0] === state.color)) state.color = COLORS[o][0][0];
      const first = { S: 'SEN-IA', H: 'IA-01', G: 'GOV-GA' }[o];
      if (!by[state.sel] || by[state.sel].office !== o) state.sel = first;
      setTab(); draw(); detail();
    });
    $('color').addEventListener('click', (e) => { const c = e.target.closest('button')?.dataset.c; if (!c) return; state.color = c; draw(); });
    document.addEventListener('scroll', () => MB.tip(tip, null), { passive: true });

    $('asof').textContent = new Date(BOOK.asof).toLocaleString([], { month: 'short', day: 'numeric', hour: 'numeric', minute: '2-digit' });
    control(); setTab(); draw(); detail(); disagreements(); swing(); method();
  };

  window.MapBook = MB;
})();
