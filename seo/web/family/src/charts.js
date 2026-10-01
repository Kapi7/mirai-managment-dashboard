/* ---------- chart kit: drawn at real pixel width, redrawn on resize ---------- */
const CHARTS = new Map(); let chartSeq = 0;
const RO = typeof ResizeObserver !== 'undefined' ? new ResizeObserver(es => {
  for (const en of es) { const el = en.target, f = CHARTS.get(el.dataset.chart); if (f && el.isConnected && Math.abs((el._w || 0) - el.clientWidth) > 2) f(el); }
}) : null;
function slot(draw, aria, cls = '', interactive = false) { const id = 'c' + (++chartSeq); CHARTS.set(id, draw); return `<div class="chart ${cls}" data-chart="${id}" role="${interactive ? 'group' : 'img'}" aria-label="${esc(aria)}"></div>`; }
function mountCharts(root) {
  root.querySelectorAll('[data-chart]').forEach(el => { if (el._mounted) return; const f = CHARTS.get(el.dataset.chart); if (!f) return; el._mounted = true; f(el); if (RO) RO.observe(el); });
  for (const id of [...CHARTS.keys()]) if (!document.querySelector(`[data-chart="${id}"]`)) CHARTS.delete(id);
}
function niceMax(v) { if (!(v > 0)) return 1; const p = Math.pow(10, Math.floor(Math.log10(v))), m = v / p; return (m <= 1 ? 1 : m <= 2 ? 2 : m <= 2.5 ? 2.5 : m <= 5 ? 5 : 10) * p; }
const tickFmt = t => Number.isInteger(t) ? fmt(t) : t.toFixed(1);
const svgText = (x, y, t, a = 'middle', fill = 'var(--dim)', size = 10.5) => `<text x="${x.toFixed(1)}" y="${y.toFixed(1)}" text-anchor="${a}" font-size="${size}" fill="${fill}" font-family="Inter,system-ui,sans-serif">${esc(t)}</text>`;
function tipBox(el) { let t = el.querySelector('.ctip'); if (!t) { t = document.createElement('div'); t.className = 'ctip'; t.hidden = true; el.appendChild(t); } return t; }
function guideLine(el) { let g = el.querySelector('.guide'); if (!g) { g = document.createElement('div'); g.className = 'guide'; g.hidden = true; el.appendChild(g); } return g; }

/* time series: bars / area / line, optional previous-period dashed overlay, hover read-out, day markers */
function timeChart(cfg) {
  return slot(el => {
    const W = Math.max(220, el.clientWidth); el._w = W;
    const H = cfg.h || 150, L = cfg.left ?? 42, R = 12, T = 12, B = 24;
    const n = cfg.e - cfg.s + 1, step = (W - L - R) / n, x = i => L + (i + 0.5) * step;
    const cmp = state.compare && cfg.series.some(s => s.prev);
    const vals = []; cfg.series.forEach(s => { s.vals.forEach(v => v != null && vals.push(v)); if (cmp && s.prev) s.prev.forEach(v => v != null && vals.push(v)); });
    let lo = 0, hi = niceMax(Math.max(0, ...vals));
    if (cfg.invert) { lo = 1; hi = Math.max(10, Math.ceil(Math.max(10, ...vals) / 10) * 10); }
    const y = v => cfg.invert ? T + ((v - lo) / (hi - lo)) * (H - T - B) : H - B - ((v - lo) / (hi - lo)) * (H - T - B);
    let g = '';
    const ticks = cfg.invert ? [1, Math.round((1 + hi) / 2), hi] : Number.isInteger(hi / 2) || hi >= 10 ? [0, hi / 2, hi] : [0, hi];
    ticks.forEach((t, k) => {
      g += `<line x1="${L}" x2="${W - R}" y1="${y(t).toFixed(1)}" y2="${y(t).toFixed(1)}" stroke="rgba(148,163,184,${k === 0 ? .28 : .13})" ${k === 0 ? '' : 'stroke-dasharray="3 4"'}/>`;
      g += svgText(L - 7, y(t) + 3.5, cfg.invert ? '#' + tickFmt(t) : tickFmt(t), 'end');
    });
    const k = Math.min(n, Math.max(2, Math.floor((W - L - R) / 105)));
    for (let j = 0; j < k; j++) { const i = k === 1 ? 0 : Math.round(j * (n - 1) / (k - 1)); g += svgText(x(i), H - 6, dm(cfg.s + i), j === 0 && k > 1 ? 'start' : j === k - 1 && k > 1 ? 'end' : 'middle'); }
    const line = arr => { let d = '', pen = false; arr.forEach((v, i) => { if (v == null) { pen = false; return; } d += (pen ? 'L' : 'M') + x(i).toFixed(1) + ' ' + y(v).toFixed(1); pen = true; }); return d; };
    for (const [si, s] of cfg.series.entries()) {
      const gradient = `${el.dataset.chart}-fill-${si}`;
      g += `<defs><linearGradient id="${gradient}" x1="0" y1="0" x2="0" y2="1"><stop offset="0%" stop-color="${s.color}" stop-opacity=".42"/><stop offset="100%" stop-color="${s.color}" stop-opacity=".015"/></linearGradient></defs>`;
      if (cmp && s.prev) g += `<path d="${line(s.prev)}" fill="none" stroke="${s.color}" stroke-width="1.4" stroke-dasharray="4 4" opacity=".5"/>`;
      if (s.kind === 'bars') {
        const bw = Math.max(1, step * (n > 120 ? 0.9 : 0.68));
        s.vals.forEach((v, i) => { if (v > 0) g += `<rect x="${(x(i) - bw / 2).toFixed(1)}" y="${y(v).toFixed(1)}" width="${bw.toFixed(1)}" height="${(H - B - y(v)).toFixed(1)}" rx="${Math.min(2, bw / 3).toFixed(1)}" fill="${s.color}"/>`; });
      } else {
        const d = line(s.vals);
        if (s.kind === 'area' && !cfg.invert) {
          let area = ''; let seg = [];
          const flush = () => { if (seg.length) { area += `M${x(seg[0]).toFixed(1)} ${H - B}` + seg.map(i => `L${x(i).toFixed(1)} ${y(s.vals[i]).toFixed(1)}`).join('') + `L${x(seg[seg.length - 1]).toFixed(1)} ${H - B}Z`; seg = []; } };
          s.vals.forEach((v, i) => v == null ? flush() : seg.push(i)); flush();
          g += `<path d="${area}" fill="url(#${gradient})"/>`;
        }
        g += `<path class="trend-line" style="--trend:${s.color}" d="${d}" fill="none" stroke="${s.color}" stroke-width="2.5" stroke-linejoin="round" stroke-linecap="round"/>`;
        let li = s.vals.length - 1; while (li >= 0 && s.vals[li] == null) li--;
        if (li >= 0) g += `<circle cx="${x(li).toFixed(1)}" cy="${y(s.vals[li]).toFixed(1)}" r="3.6" fill="${s.color}" stroke="var(--bg)" stroke-width="2"/>`;
      }
    }
    (cfg.marks || []).forEach(m => { if (m.d < cfg.s || m.d > cfg.e) return; const mx = x(m.d - cfg.s); g += `<path d="M${mx} ${H - B - 7}l4.5 4.5-4.5 4.5-4.5-4.5z" fill="var(--gold)" stroke="var(--bg)" stroke-width="1.2"/>`; });
    const hits = Array.from({ length: n }, (_, i) => {
      const label = cfg.series.map(s => `${s.label}: ${s.vals[i] == null ? 'no data' : (s.fmt || fmt)(s.vals[i])}`).join(', ');
      return `<rect class="day-hit" x="${L + i * step}" y="${T}" width="${step}" height="${H - T - B}" fill="transparent" ${chartTarget(cfg.s + i, cfg.s + i, i, label, cfg.site)}/>`;
    }).join('');
    el.innerHTML = `<svg width="${W}" height="${H}" viewBox="0 0 ${W} ${H}"><g aria-hidden="true">${g}</g>${hits}</svg>`;
    const tip = tipBox(el), guide = guideLine(el);
    guide.style.top = T + 'px'; guide.style.height = (H - T - B) + 'px';
    el.onpointermove = ev => {
      const r = el.getBoundingClientRect(); const i = Math.max(0, Math.min(n - 1, Math.floor((ev.clientX - r.left - L) / step)));
      const d = cfg.s + i, mk = (cfg.marks || []).filter(m => m.d === d);
      let h = `<b>${dm(d)} ${yr(d)}</b><div class="dim">Click to open this day</div>`;
      for (const s of cfg.series) {
        const v = s.vals[i];
        h += `<div class="r"><span><i style="background:${s.color}"></i>${esc(s.label)}</span><b>${v == null ? '—' : (s.fmt || fmt)(v)}</b></div>`;
        if (cmp && s.prev) { const pv = s.prev[i]; h += `<div class="r dim"><span>${dm(d - n)}</span><span>${pv == null ? '—' : (s.fmt || fmt)(pv)}</span></div>`; }
      }
      mk.forEach(m => { h += `<div class="r" style="color:var(--gold)">◆ ${esc(m.label)}</div>`; });
      tip.innerHTML = h; tip.hidden = false; guide.hidden = false;
      const gx = x(i); guide.style.left = gx + 'px';
      tip.style.left = Math.max(90, Math.min(W - 90, gx)) + 'px'; tip.style.top = (T - 4) + 'px';
    };
    el.onpointerleave = () => { tip.hidden = true; guide.hidden = true; };
  }, cfg.aria + '. Select a day to open its details.', '', true);
}

/* compact bar strip for KPI cards (buckets long periods to ≤ 30 bars) */
function sparkBars(vals, color, start, label) {
  const n = vals.length; if (!n) return '';
  const k = Math.min(30, n), per = n / k, w = 100 / k;
  const buckets = Array.from({ length: k }, (_, j) => {
    const first = Math.floor(j * per), last = Math.floor((j + 1) * per) - 1;
    const observed = vals.slice(first, last + 1).filter(v => v != null);
    return { first, last, value: observed.length ? observed.reduce((sum, v) => sum + v, 0) : null };
  });
  const max = Math.max(1, ...buckets.map(b => b.value || 0));
  return `<svg class="sbars" viewBox="0 0 100 38" preserveAspectRatio="none" role="group" aria-label="${esc(label)} by date. Select a bar to open its dates.">${buckets.map((b, j) => {
    const h = b.value ? Math.max(3, b.value / max * 36) : 1.2;
    const title = `${label}: ${b.value == null ? 'no data' : fmt(b.value)}`;
    return `<g><rect aria-hidden="true" x="${(j * w + w * .14).toFixed(2)}" width="${(w * .72).toFixed(2)}" y="${(38 - h).toFixed(2)}" height="${h.toFixed(2)}" fill="${color}" opacity="${b.value ? 1 : .22}"/><rect class="day-hit" x="${j * w}" y="0" width="${w}" height="38" fill="transparent" ${chartTarget(start + b.first, start + b.last, j, title)}><title>${esc(rangeTxt(start + b.first, start + b.last) + ' · ' + title + ' · Click to open')}</title></rect></g>`;
  }).join('')}</svg>`;
}
function ring(frac, color) {
  const r = 16, c = 2 * Math.PI * r, f = Math.max(0, Math.min(1, frac || 0));
  return `<svg class="ring" width="40" height="40" viewBox="0 0 40 40" aria-hidden="true"><circle cx="20" cy="20" r="${r}" fill="none" stroke="rgba(245,158,11,.18)" stroke-width="4"/><circle cx="20" cy="20" r="${r}" fill="none" stroke="${color}" stroke-width="4" stroke-linecap="round" stroke-dasharray="${(c * f).toFixed(1)} ${c.toFixed(1)}" transform="rotate(-90 20 20)"/><text x="20" y="23.5" text-anchor="middle" font-size="9.5" font-weight="800" fill="${color}" font-family="Inter,sans-serif">${f < 0.01 && f > 0 ? '<1' : Math.round(f * 100)}%</text></svg>`;
}

/* search opportunity map: every search term by Google position (x, log) and views (y, log) */
function scatterChart(pts, aria) {
  return slot(el => {
    const W = Math.max(260, el.clientWidth); el._w = W;
    const H = W < 480 ? 260 : 310, L = 46, R = 14, T = 28, B = 36;
    const xs = p => L + (Math.log10(Math.min(100, Math.max(1, p))) / 2) * (W - L - R);
    const maxY = Math.max(10, ...pts.map(p => p.y)), ly = Math.log10(maxY + 1);
    const ys = v => H - B - (Math.log10(v + 1) / ly) * (H - T - B);
    let g = `<rect x="${xs(7.5).toFixed(1)}" y="${T}" width="${(xs(20.5) - xs(7.5)).toFixed(1)}" height="${H - T - B}" fill="rgba(163,230,53,.08)" stroke="rgba(163,230,53,.35)" stroke-dasharray="4 4"/>`;
    g += svgText((xs(7.5) + xs(20.5)) / 2, T - 9, 'Close to page 1', 'middle', 'var(--lime)', 11);
    [10.5, 20.5, 30.5, 50.5].forEach(b => { g += `<line x1="${xs(b).toFixed(1)}" x2="${xs(b).toFixed(1)}" y1="${T}" y2="${H - B}" stroke="rgba(148,163,184,.16)"/>`; });
    const pages = W < 480 ? [[1, 10.5, 'P1'], [10.5, 20.5, 'P2'], [20.5, 30.5, 'P3'], [30.5, 50.5, '4–5'], [50.5, 100, '6+']] : [[1, 10.5, 'Page 1'], [10.5, 20.5, 'Page 2'], [20.5, 30.5, 'Page 3'], [30.5, 50.5, 'Pages 4–5'], [50.5, 100, 'Page 6+']];
    pages.forEach(([a, b, t]) => { g += svgText((xs(a) + xs(b)) / 2, H - 8, t); });
    for (let v = 1; v <= maxY * 1.01; v *= 10) { g += `<line x1="${L}" x2="${W - R}" y1="${ys(v).toFixed(1)}" y2="${ys(v).toFixed(1)}" stroke="rgba(148,163,184,.1)" stroke-dasharray="3 4"/>` + svgText(L - 8, ys(v) + 3.5, fmt(v), 'end'); }
    g += svgText(L - 8, T - 9, 'Views', 'end', 'var(--dim)', 10);
    const sorted = [...pts].sort((a, b) => (a.c > 0) - (b.c > 0) || a.y - b.y);
    const P2 = sorted.map(p => ({ ...p, px: xs(p.x), py: ys(p.y) }));
    P2.forEach(p => { g += `<circle cx="${p.px.toFixed(1)}" cy="${p.py.toFixed(1)}" r="${p.c > 0 ? 6 : 3.8}" fill="${p.color}" fill-opacity="${p.c > 0 ? .95 : .62}" ${p.c > 0 ? 'stroke="var(--point-stroke)" stroke-width="1.5"' : ''}/>`; });
    el.innerHTML = `<svg width="${W}" height="${H}" viewBox="0 0 ${W} ${H}">${g}</svg>`;
    const tip = tipBox(el);
    const near = ev => { const r = el.getBoundingClientRect(), mx = ev.clientX - r.left, my = ev.clientY - r.top; let best = null, bd = 196; for (const p of P2) { const d = (p.px - mx) ** 2 + (p.py - my) ** 2; if (d < bd) { bd = d; best = p; } } return best; };
    el.onpointermove = ev => {
      const p = near(ev); if (!p) { tip.hidden = true; el.style.cursor = ''; return; }
      el.style.cursor = 'pointer';
      tip.innerHTML = `<b>${esc(p.label)}</b><div class="r"><span>${esc(p.site.name)}</span></div><div class="r"><span>Views</span><b>${fmt(p.y)}</b></div><div class="r"><span>Clicks</span><b>${fmt(p.c)}</b></div><div class="r"><span>Position</span><b>${rankText(p.x)} · lower is better</b></div>`;
      tip.hidden = false; tip.style.left = Math.max(100, Math.min(W - 100, p.px)) + 'px'; tip.style.top = (p.py - 10) + 'px';
    };
    el.onpointerleave = () => { tip.hidden = true; };
    el.onclick = ev => { const p = near(ev); if (p) openSite(p.site.slug); };
  }, aria);
}

/* data-arrival heatmap: one strip per site and source, one cell per day (per week beyond 91 days) */
function heatmap(rows, s, e, aria) {
  return slot(el => {
    const W = Math.max(280, el.clientWidth); el._w = W;
    const n = e - s + 1, wk = n > 91 ? 7 : 1, cols = Math.ceil(n / wk);
    const LW = W < 520 ? 104 : 170, RW = 8, rh = 12, gap = 3, pairGap = 7;
    const cw = (W - LW - RW) / cols;
    let y = 4, g = '';
    const cells = [];
    rows.forEach((r, ri) => {
      if (ri > 0 && r.first) y += pairGap;
      g += `<rect x="${LW}" y="${y}" width="${(W - LW - RW).toFixed(1)}" height="${rh}" rx="3" fill="var(--inset)"/>`;
      if (r.first) g += svgText(LW - 34, y + 10, r.label.length > (W < 520 ? 13 : 24) ? r.label.slice(0, W < 520 ? 12 : 23) + '…' : r.label, 'end', 'var(--fg)', 11);
      g += svgText(LW - 6, y + 10, r.src, 'end', r.color, 9.5);
      const max = Math.max(1, ...r.vals.filter(v => v != null));
      for (let c = 0; c < cols; c++) {
        let v = null; for (let i = c * wk; i < Math.min(n, (c + 1) * wk); i++) if (r.vals[i] != null) v = (v || 0) + r.vals[i];
        if (v == null) continue;
        const op = v > 0 ? (0.28 + 0.72 * Math.log(v + 1) / Math.log(max + 1)).toFixed(2) : 1;
        g += `<rect x="${(LW + c * cw + .6).toFixed(1)}" y="${y}" width="${Math.max(1, cw - 1.2).toFixed(1)}" height="${rh}" rx="2" fill="${v > 0 ? r.color : 'rgba(148,163,184,.22)'}" fill-opacity="${op}"/>`;
      }
      cells.push({ r, y }); y += rh + gap;
    });
    el.innerHTML = `<svg width="${W}" height="${y + 18}" viewBox="0 0 ${W} ${y + 18}">${g}${svgText(LW, y + 14, dm(s), 'start')}${svgText(W - RW, y + 14, dm(e), 'end')}</svg>`;
    const tip = tipBox(el);
    el.onpointermove = ev => {
      const b = el.getBoundingClientRect(), mx = ev.clientX - b.left, my = ev.clientY - b.top;
      const row = cells.find(c => my >= c.y - 1 && my <= c.y + rh + 1); const c = Math.floor((mx - LW) / cw);
      if (!row || c < 0 || c >= cols) { tip.hidden = true; return; }
      let v = null; for (let i = c * wk; i < Math.min(n, (c + 1) * wk); i++) if (row.r.vals[i] != null) v = (v || 0) + row.r.vals[i];
      const d0 = s + c * wk, d1 = Math.min(e, d0 + wk - 1);
      tip.innerHTML = `<b>${esc(row.r.site)}</b> · ${esc(row.r.src)}<div class="r"><span>${wk > 1 ? `${dm(d0)}–${dm(d1)}` : dm(d0)}</span><b>${v == null ? 'nothing recorded' : fmt(v) + ' ' + row.r.unit}</b></div>`;
      tip.hidden = false; tip.style.left = Math.max(100, Math.min(W - 100, LW + (c + .5) * cw)) + 'px'; tip.style.top = (row.y - 4) + 'px';
    };
    el.onpointerleave = () => { tip.hidden = true; };
  }, aria);
}
