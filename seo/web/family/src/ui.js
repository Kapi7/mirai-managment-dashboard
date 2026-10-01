/* ---------- controls + rendering ---------- */
const LENSES = [{ k: 'All', l: 'Ecosystem', icon: 'globe' }, { k: 'Main', l: 'Mirai Skin', icon: 'spark' }, { k: 'Satellites', l: 'Satellites', icon: 'bars' }];
const isPhone = () => window.matchMedia('(max-width:760px)').matches;
function buildStatic() {
  $('#lens').innerHTML = LENSES.map(x => { const n = x.k === 'All' ? ACTIVE.length : ACTIVE.filter(s => s.vertical === x.k).length; return `<button type="button" role="radio" data-lens="${x.k}" aria-checked="false" data-tip="${n} ${plural(n, 'site')}">${icon(x.icon, 15)}${x.l}</button>`; }).join('');
  $('#segPeriod').innerHTML = PRESETS.map(p => `<button type="button" role="radio" data-preset="${p.k}" aria-checked="false">${p.l}</button>`).join('');
  $('#segTraffic').innerHTML = [['all', 'All visits'], ['nodirect', 'Without Direct']].map(([k, l]) => `<button type="button" role="radio" data-traffic="${k}" aria-checked="false">${l}</button>`).join('');
  const months = []; for (let d = END; d >= Math.max(MIN, END - 200) && months.length < 6;) { const m = isoOf(d).slice(0, 7); if (!months.includes(m)) months.push(m); d = dayOf(m + '-01') - 1; }
  $('#popCustom').innerHTML = `<h3>Custom dates</h3><div class="dates"><label>From<input type="date" id="cFrom" min="${isoOf(MIN)}" max="${isoOf(END)}"></label><label>To<input type="date" id="cTo" min="${isoOf(MIN)}" max="${isoOf(END)}"></label></div>
    <div class="months">${months.map(m => `<button type="button" class="chipbtn" data-month="${m}">${MON[+m.slice(5) - 1]} ${m.slice(0, 4)}</button>`).join('')}</div>
    <div class="err" id="cErr" role="alert"></div><div style="display:flex;gap:8px;justify-content:flex-end"><button type="button" class="btn ghost" data-popclose>Cancel</button><button type="button" class="btn" id="cApply">Apply dates</button></div>`;
  $('#popSites').innerHTML = `<input class="dd-search" id="sSearch" type="search" placeholder="Type to filter sites" aria-label="Filter the site list" autocomplete="off"><div class="dd-acts"><button type="button" class="chipbtn" data-sall>Select all</button><button type="button" class="chipbtn" data-snone>Clear</button></div><div class="dd-list" id="sList"></div>`;
}
function renderSiteList() {
  const q = $('#sSearch').value.trim().toLowerCase(), w = win(), groups = {}, selected = new Set(scope().map(s => s.slug));
  ACTIVE.forEach(s => { if (!q || s.name.includes(q)) (groups[s.vertical] = groups[s.vertical] || []).push(s); });
  $('#sList').innerHTML = Object.entries(groups).map(([v, list]) => `<div class="dd-g">${VNAME[v] || v}</div>` + list.map(s => `<label class="dd-o"><input type="checkbox" data-scheck="${s.slug}" ${selected.has(s.slug) ? 'checked' : ''}>${avatar(s, 'sm')}<span class="nm">${esc(s.name)}</span><span class="v">${fmt(agg(s, w.s, w.e).impr)} views</span></label>`).join('')).join('') || '<div class="empty">No site matches.</div>';
}
const fchip = (label, key) => `<span class="fchip">${esc(label)}<button type="button" data-clear="${key}" aria-label="Remove filter: ${esc(label)}">✕</button></span>`;
function activeChips(w, L) {
  const ls = lensSites(), c = [];
  if (state.lens !== 'All') c.push(fchip(`${VNAME[state.lens]} sites`, 'lens'));
  if (state.sites) c.push(fchip(L.length === 1 ? L[0].name : `${L.length} of ${ls.length} sites`, 'sites'));
  if (state.preset !== '28d' || state.offset) c.push(fchip(state.preset === 'custom' || state.offset ? rangeTxt(w.s, w.e) : PRESETS.find(p => p.k === state.preset).l, 'period'));
  if (!state.compare) c.push(fchip('No comparison', 'compare'));
  if (state.traffic === 'nodirect') c.push(fchip('Without Direct', 'traffic'));
  if (state.find.trim()) c.push(fchip(`Find “${state.find.trim()}”`, 'find'));
  if (selectedCountry()) c.push(fchip(`${countryLabel(selectedCountry())} · country visits`, 'country'));
  return c;
}
function syncChrome() {
  const w = win(), L = scope();
  const countries = geoAgg(L, w.s, w.e), selected = selectedCountry();
  if (selected && !countries.some(g => countryKey(g) === state.country)) countries.push(selected);
  $('#countryFilter').innerHTML = '<option value="">🌐 All countries</option>' + countries.map(g => `<option value="${esc(countryKey(g))}"${countryKey(g) === state.country ? ' selected' : ''}>${esc(countryLabel(g))}</option>`).join('');
  $$('#lens [data-lens]').forEach(b => b.setAttribute('aria-checked', String(b.dataset.lens === checkedLens())));
  $$('#segPeriod [data-preset]').forEach(b => b.setAttribute('aria-checked', String(state.preset === b.dataset.preset)));
  $$('#segTraffic [data-traffic]').forEach(b => b.setAttribute('aria-checked', String(state.traffic === b.dataset.traffic)));
  $('#btnCustom').classList.toggle('on', state.preset === 'custom');
  $('#customLbl').textContent = state.preset === 'custom' ? rangeTxt(w.s, w.e) : 'Custom';
  $('#swCompare').setAttribute('aria-checked', String(state.compare));
  const some = state.lens !== 'All' || !!state.sites;
  $('#sitesLbl').textContent = scopeLabel(L);
  $('#btnSites').classList.toggle('on', !!some);
  $('#dayPill').textContent = rangeTxt(w.s, w.e);
  $('#stepBack').disabled = w.s - w.n < MIN; $('#stepFwd').disabled = w.e + w.n > END;
  $('#stepBack').setAttribute('aria-label', w.n === 1 ? 'Previous day' : 'Previous period');
  $('#stepFwd').setAttribute('aria-label', w.n === 1 ? 'Next day' : 'Next period');
  const age = TODAY - END, urgentAll = fixItems(ACTIVE).filter(a => a.sev === 'bad').length;
  $('#btnStatus').className = `pill status ${age <= 4 ? 'fresh' : 'stale'}`;
  $('#statusTxt').textContent = `Data to ${dm(END)}${age > 4 ? ` · ${age}d old` : ''}`;
  $('#popStatus').innerHTML = `<h3>Data freshness</h3><div class="srows"><span>Search Console</span><b>to ${dm(D.gscEnd)} ${yr(D.gscEnd)}</b><span>Analytics 4</span><b>to ${dm(D.ga4End)} ${yr(D.ga4End)}</b><span>Last fetch</span><b>${dm(D.lastFetch)}, ${esc(String(D.lastFetch || '').slice(11, 16))} UTC</b><span>Live check</span><b>${LIVE.state === 'done' ? `${liveTime()} today` : LIVE.state === 'running' ? 'running…' : 'not run yet'}</b><span>Needs a fix</span><b class="${urgentAll ? 'w' : 'ok'}">${urgentAll} urgent</b><span>Refresh</span><b>${D.refresh?.automatic ? 'daily while running' : 'manual refresh'}</b></div><button type="button" class="more" data-go="connections">Open Connections ›</button>`;
  const chips = activeChips(w, L);
  $('#fsum').innerHTML = `<span>${state.compare ? `vs <b>${rangeTxt(w.ps, w.pe)}</b> · ` : ''}<b>${L.length}</b> ${plural(L.length, 'site')}</span>${dayTrail.length ? '<button type="button" class="chipbtn" data-chart-back>← Back to period</button>' : ''}${chips.join('')}${chips.length ? '<button type="button" class="reset" data-resetall>Reset all</button>' : ''}`;
  $('#fabN').textContent = chips.length; $('#fabN').hidden = !chips.length;
  $('#miniTxt').innerHTML = `${icon('cal', 13)} <b>${rangeTxt(w.s, w.e)}</b> <span class="sep">|</span> ${esc(scopeLabel(L))}${state.traffic === 'nodirect' ? ' · without Direct' : ''}${state.compare ? '' : ' · no comparison'}`;
  $('#ctaN').textContent = urgentAll; $('#ctaConn').setAttribute('aria-label', `Connections: ${urgentAll} urgent fixes`);
}
const tabBtn = (t, cls, cnt) => { const sel = state.tab === t.k, c = cnt[t.k]; return `<button type="button" class="${cls}" role="tab" id="${cls}-${t.k}" data-tab="${t.k}" aria-selected="${sel}" aria-controls="tabBody" tabindex="${sel ? 0 : -1}">${icon(t.icon, cls === 'bn' ? 19 : 15)}<span>${cls === 'bn' ? t.short || t.label : t.label}</span>${c ? `<span class="cnt ${t.k === 'connections' ? 'bad' : ''}">${fmt(c)}</span>` : ''}</button>`; };
function renderAll() {
  MEMO = new Map();
  syncChrome();
  const w = win(), L = scope(), main = $('#main');
  if (!L.length) { main.innerHTML = '<div class="panel"><div class="empty">No sites are selected. <button type="button" class="reset" data-clear="sites">Show all sites</button></div></div>'; $('#bnav').innerHTML = ''; $('#vtabs').innerHTML = ''; return; }
  CTX = { L, w, T: totals(L, w.s, w.e), TP: totals(L, w.ps, w.pe), S: series(L, w.s, w.e), SP: state.compare ? series(L, w.ps, w.pe) : {}, qs: queryAgg(L, w.s, w.e), qsPrev: state.compare ? queryAgg(L, w.ps, w.pe) : [], eng: engineAgg(L, w.s, w.e) };
  const cnt = { sites: L.length, searches: CTX.qs.filter(q => q.i > 0).length, connections: fixItems(L).filter(a => a.sev === 'bad').length };
  const partial = w.s < MIN || (state.compare && w.ps < MIN);
  main.innerHTML = (partial ? `<div class="banner warn">History begins ${dm(MIN)} ${yr(MIN)}. This range or its comparison includes days before collection; those days are unavailable, not measured zero.</div>` : '') + kpiHTML(CTX) + signalsHTML(CTX) + arenaHTML(CTX)
    + `<div id="tabBody" class="wrap" role="tabpanel" tabindex="-1"></div>`;
  $('#vtabs').innerHTML = TABS.map(t => tabBtn(t, 'vtab', cnt)).join('');
  $('#bnav').innerHTML = TABS.map(t => tabBtn(t, 'bn', cnt)).join('');
  mountCharts(main);
  renderTab();
}
let CTX = null;
function renderSignals(focusKey) {
  const el = $('#signals'); if (!el || !CTX) return;
  el.outerHTML = signalsHTML(CTX);
  if (focusKey) document.querySelector(`.sig[data-sig="${focusKey}"]`)?.focus();
}
function renderTab() {
  const body = $('#tabBody'); if (!body) return;
  const V = { sites: vSites, ecosystem: vEcosystem, searches: vSearches, visits: vVisits, authority: vAuthority, connections: vConnections }[state.tab] || vSites;
  body.innerHTML = V(scope(), win());
  body.setAttribute('aria-labelledby', 'vtab-' + state.tab);
  mountCharts(body);
  if (state.tab === 'authority') ensureAuthorityData();
}
function setTab(k, scroll) {
  state.tab = k; syncUrl();
  $$('[data-tab]').forEach(b => { const on = b.dataset.tab === k; b.setAttribute('aria-selected', String(on)); b.tabIndex = on ? 0 : -1; });
  renderTab();
  if (scroll) $('#tabBody')?.scrollIntoView({ behavior: window.matchMedia('(prefers-reduced-motion: reduce)').matches ? 'auto' : 'smooth', block: 'start' });
}
function showCountries() {
  setSheet(false); setTab('visits', false);
  const panel = $('#countriesPanel');
  if (panel) { panel.tabIndex = -1; panel.scrollIntoView({ block: 'start' }); panel.focus({ preventScroll: true }); }
}
function closePops(except) { $$('.pop').forEach(p => { if (p !== except) { p.hidden = true; const b = document.querySelector(`[aria-controls="${p.id}"]`); if (b) b.setAttribute('aria-expanded', 'false'); } }); }
function togglePop(btn, pop, onOpen) {
  const open = pop.hidden; closePops(pop); pop.hidden = !open; btn.setAttribute('aria-expanded', String(open));
  if (open && onOpen) onOpen();
}
function openCustom() {
  const w = win(); $('#cFrom').value = isoOf(w.s); $('#cTo').value = isoOf(w.e); $('#cErr').textContent = '';
  $$('#popCustom [data-month]').forEach(b => b.setAttribute('aria-pressed', 'false'));
  $('#cFrom').focus();
}
function applyCustom() {
  const f = $('#cFrom').value, t = $('#cTo').value;
  if (!f || !t) { $('#cErr').textContent = 'Pick both dates.'; return; }
  let s = dayOf(f), e = dayOf(t);
  if (s > e) { $('#cErr').textContent = 'The start date is after the end date.'; return; }
  if (e < MIN || s > END) { $('#cErr').textContent = `Data exists from ${dm(MIN)} ${yr(MIN)} to ${dm(END)} ${yr(END)}.`; return; }
  s = Math.max(MIN, s); e = Math.min(END, e);
  dayTrail = []; Object.assign(state, { preset: 'custom', from: s, to: e, offset: 0 }); closePops(); persist(); renderAll();
}
function setSheet(open) { document.documentElement.classList.toggle('fopen', open); $('#fab').setAttribute('aria-expanded', String(open)); if (!open) closePops(); }
function clearFilter(k) {
  if (k === 'lens' || k === 'sites') selectLens('All');
  if (k === 'period') { dayTrail = []; state.preset = '28d'; state.offset = 0; }
  if (k === 'compare') state.compare = true;
  if (k === 'traffic') state.traffic = 'all';
  if (k === 'country') state.country = '';
  if (k === 'find') { state.find = ''; $('#find').value = ''; $('#findClr').hidden = true; }
}
function attrSel(el) { for (const a of ['data-tab', 'data-lens', 'data-preset', 'data-traffic', 'data-view', 'data-sort']) if (el.hasAttribute(a)) return `.${el.classList[0] || 'x'}[${a}="${el.getAttribute(a)}"]`.replace('.x[', '['); return null; }

document.addEventListener('click', e => {
  const day = e.target.closest('[data-chart-from]');
  if (day) return openChartRange(Number(day.dataset.chartFrom), Number(day.dataset.chartTo), day.dataset.chartSite);
  const t = e.target.closest('button,[data-close],[data-fclose],label.dd-o'); if (!t) { if (!e.target.closest('.pop')) closePops(); return; }
  if (!t.closest('.dd')) closePops();
  const d = t.dataset;
  if ('chartBack' in d) return backToPeriod();
  if (t.id === 'btnCustom') return togglePop(t, $('#popCustom'), openCustom);
  if (t.id === 'btnStatus') return togglePop(t, $('#popStatus'));
  if ('livecheck' in d) return runLiveCheck();
  if (d.sig) { state.sig = state.sig === d.sig ? null : d.sig; return renderSignals(d.sig); }
  if (t.id === 'btnSites') return togglePop(t, $('#popSites'), () => { $('#sSearch').value = ''; renderSiteList(); $('#sSearch').focus(); });
  if (t.id === 'cApply') return applyCustom();
  if (t.id === 'swCompare') { state.compare = !state.compare; persist(); return renderAll(); }
  if (t.id === 'stepBack' || t.id === 'stepFwd') { stepPeriod(t.id === 'stepBack' ? -1 : 1); persist(); return renderAll(); }
  if (t.id === 'dayPill') { if (isPhone()) return setSheet(true); $('#fpanel').scrollIntoView({ block: 'nearest' }); return togglePop($('#btnCustom'), $('#popCustom'), openCustom); }
  if (t.id === 'ctaConn') return setTab('connections', true);
  if (t.id === 'fab') return setSheet(true);
  if (t.id === 'findClr') { clearFilter('find'); syncChrome(); renderTab(); return $('#find').focus(); }
  if (t.id === 'editFilters' || 'editfilters' in d) { if (isPhone()) return setSheet(true); $('#fpanel').scrollIntoView({ block: 'start' }); return $('#segPeriod [aria-checked="true"]')?.focus({ preventScroll: true }); }
  if ('goCountry' in d) return showCountries();
  if ('fclose' in d) return setSheet(false);
  if ('popclose' in d) return closePops();
  if (d.month) { const s = Math.max(MIN, dayOf(d.month + '-01')), mEnd = new Date(Date.UTC(+d.month.slice(0, 4), +d.month.slice(5), 0)).toISOString().slice(0, 10); $('#cFrom').value = isoOf(s); $('#cTo').value = isoOf(Math.min(END, dayOf(mEnd))); $$('#popCustom [data-month]').forEach(b => b.setAttribute('aria-pressed', String(b === t))); return; }
  if (d.lens) { selectLens(d.lens); persist(); return renderAll(); }
  if (d.preset) { dayTrail = []; state.preset = d.preset; state.offset = 0; persist(); return renderAll(); }
  if (d.traffic) { state.traffic = d.traffic; persist(); return renderAll(); }
  if ('sall' in d) { selectLens('All'); persist(); renderAll(); return renderSiteList(); }
  if ('snone' in d) { selectSites(new Set()); persist(); renderAll(); return renderSiteList(); }
  if (d.clear) { clearFilter(d.clear); persist(); return renderAll(); }
  if ('resetall' in d) { ['lens', 'sites', 'period', 'compare', 'traffic', 'find', 'country'].forEach(clearFilter); persist(); return renderAll(); }
  if ('clearfind' in d) { clearFilter('find'); syncChrome(); return renderTab(); }
  if (d.tab) return setTab(d.tab, true);
  if (d.go) { closePops(); return setTab(d.go, true); }
  if (d.site) return openSite(d.site);
  if ('close' in d) return closeSite();
  if (d.view) { state.view = d.view; persist(); return renderTab(); }
  if (d.sort) { state.sort = d.sort; state.sortDir = d.sort === 'pos' ? 1 : -1; persist(); return renderTab(); }
  if (d.tsort) { if (state.sort === d.tsort) state.sortDir *= -1; else { state.sort = d.tsort; state.sortDir = ['name', 'pos'].includes(d.tsort) ? 1 : -1; } persist(); return renderTab(); }
  if (d.more) { MORE[d.more] = true; return renderTab(); }
});
document.addEventListener('change', e => {
  if (e.target.id === 'countryFilter') { state.country = e.target.value; if (!selectedCountry()) state.country = ''; persist(); renderAll(); return showCountries(); }
  const c = e.target.closest('[data-scheck]'); if (!c) return;
  const set = new Set(scope().map(s => s.slug));
  c.checked ? set.add(c.dataset.scheck) : set.delete(c.dataset.scheck);
  selectSites(set); persist(); renderAll(); renderSiteList();
  $$('[data-scheck]').find(x => x.dataset.scheck === c.dataset.scheck)?.focus({ preventScroll: true });
});
let findTimer = 0;
document.addEventListener('input', e => {
  if (e.target.id === 'sSearch') return renderSiteList();
  if (e.target.id === 'find') { $('#findClr').hidden = !e.target.value; clearTimeout(findTimer); findTimer = setTimeout(() => { state.find = e.target.value; MORE.q = MORE.p = false; syncChrome(); renderTab(); }, 140); }
});
document.addEventListener('keydown', e => {
  if (handleChartKey(e)) return;
  if (e.key === 'Escape') { if ($('.drawer')) return closeSite(); if (state.sig) { const k = state.sig; state.sig = null; return renderSignals(k); } if ($$('.pop').some(p => !p.hidden)) { const open = $$('.pop').find(p => !p.hidden); closePops(); document.querySelector(`[aria-controls="${open.id}"]`)?.focus(); return; } if (document.documentElement.classList.contains('fopen')) return setSheet(false); }
  if (e.key === 'Tab' && $('.drawer')) { const f = $$('.drawer a, .drawer button, .drawer [data-chart-from][tabindex="0"]'); if (f.length) { if (e.shiftKey && document.activeElement === f[0]) { e.preventDefault(); f.at(-1).focus(); } else if (!e.shiftKey && document.activeElement === f.at(-1)) { e.preventDefault(); f[0].focus(); } } }
  const r = e.target.closest && e.target.closest('[role="radio"],[role="tab"]');
  if (r && (e.key === 'ArrowRight' || e.key === 'ArrowLeft')) {
    const items = [...r.parentElement.children].filter(x => x.matches('[role="radio"],[role="tab"]'));
    const j = (items.indexOf(r) + (e.key === 'ArrowRight' ? 1 : -1) + items.length) % items.length, sel = attrSel(items[j]);
    e.preventDefault(); items[j].click(); if (sel) document.querySelector(sel)?.focus();
  }
});
/* info tooltips */
const tipEl = () => $('#tip');
function showTip(el) { const t = tipEl(); t.textContent = el.dataset.tip; t.hidden = false; const r = el.getBoundingClientRect(), tw = t.offsetWidth, th = t.offsetHeight; t.style.left = Math.max(8, Math.min(innerWidth - tw - 8, r.left + r.width / 2 - tw / 2)) + 'px'; let y = r.top - th - 8; if (y < 8) y = r.bottom + 8; t.style.top = y + 'px'; }
document.addEventListener('pointerover', e => { const el = e.target.closest('[data-tip]'); if (el) showTip(el); });
document.addEventListener('pointerout', e => { if (e.target.closest('[data-tip]')) tipEl().hidden = true; });
document.addEventListener('focusin', e => { const el = e.target.closest('[data-tip]'); if (el) showTip(el); else tipEl().hidden = true; });
window.addEventListener('scroll', () => { tipEl().hidden = true; }, { passive: true });
window.addEventListener('hashchange', () => { const h = location.hash.slice(1); if (TABS.some(t => t.k === h) && h !== state.tab) setTab(h, true); });

/* boot */
(function boot() {
  const h = location.hash.slice(1); if (TABS.some(t => t.k === h)) state.tab = h;
  buildStatic(); renderAll(); syncUrl();
  const sizeNavigation = () => document.documentElement.style.setProperty('--top-nav-height', $('#topNav').getBoundingClientRect().height + 'px');
  sizeNavigation();
  if (typeof ResizeObserver !== 'undefined') new ResizeObserver(sizeNavigation).observe($('#topNav'));
  if ('IntersectionObserver' in window) new IntersectionObserver(([en]) => { $('#mini').hidden = en.isIntersecting || isPhone(); }, { rootMargin: '-60px 0px 0px 0px' }).observe($('#fpanel'));
  $('#foot').innerHTML = `<span>Numbers come from the SEO history database (last fetch ${dm(D.lastFetch)}: Search Console to ${dm(D.gscEnd)}, GA4 to ${dm(D.ga4End)}). Periods end on ${dm(END)}, the last day every source delivered.</span><span>Details cover up to 500 named queries and 250 pages per site, selected by views across retained history; headline totals include all reported daily traffic. Google omits anonymized queries. Mirai Skin · Glow Coded · Rooted Glow. Analytics purchases are not reconciled Shopify orders.</span>`;
})();
