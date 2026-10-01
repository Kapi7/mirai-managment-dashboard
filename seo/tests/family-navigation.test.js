import test from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import vm from 'node:vm';
const source = ['core.js', 'navigation.js', 'charts.js'].map(f => readFileSync(new URL(`../web/family/src/${f}`, import.meta.url), 'utf8')).join('\n');
function setup(query = '', saved = {}) {
  const events = {}, entries = [];
  const location = new URL('http://localhost/seo/' + query);
  const site = (slug, vertical = 'Main', excluded = false) => ({slug, name: slug + '.com', vertical, excluded, g: [], a: [], ev: []});
  const context = vm.createContext({
    D: { epoch:'2026-01-01', end:270, minDay:0, channels:[], sources:[], sites:[site('mirai-skin'), site('glow-coded','Satellites'), site('rooted-glow','Satellites'),site('retired-site','Satellites',true)] },
    URL, URLSearchParams, location, localStorage: {getItem: () => JSON.stringify(saved), setItem(){}},
    history: Object.fromEntries(['pushState','replaceState'].map(method => [method, (_,__,url) => {entries.push({method,url:String(url)}); location.href = url;} ])),
    window: {addEventListener:(name, fn) => events[name] = fn},
    document: {querySelector:() => ({focus(){}})},
    openSlug: null, closeSite(){context.openSlug = null;}, closePops(){}, renderAll(){}, openSite(slug){context.openSlug=slug;}
  });
  vm.runInContext(source, context);
  return {context, events, entries, run: code => vm.runInContext(code,context), json: code => JSON.parse(vm.runInContext(`JSON.stringify(${code})`,context))};
}
test('fresh visits select Mirai Skin even with an old saved portfolio scope', () => {
  const c=setup('',{lens:'Satellites',sites:['glow-coded']});
  assert.deepEqual(c.json('scope().map(s=>s.slug)'),['mirai-skin']);
});
test('active site links and multi-site/all/empty selections survive reload', () => {
  for (const [query,slugs] of [['?site=glow-coded',['glow-coded']],['?sites=glow-coded,rooted-glow',['glow-coded','rooted-glow']],['?sites=all',['mirai-skin','glow-coded','rooted-glow']],['?sites=none',[]]]) {
    const c=setup(query); assert.deepEqual(c.json('scope().map(s=>s.slug)'),slugs);
    c.run('syncUrl()'); const again=setup(c.context.location.search);
    assert.deepEqual(again.json('scope().map(s=>s.slug)'),slugs);
  }
});
test('excluded and unknown links fall back to Mirai Skin and honor the legacy 30 days', () => {
  const c=setup('?view=overview&days=30&site=retired-site');
  assert.deepEqual(c.json('scope().map(s=>s.slug)'),['mirai-skin']); assert.equal(c.run('win().n'),30);
  assert.deepEqual(setup('?site=unknown').json('scope().map(s=>s.slug)'),['mirai-skin']);
});
test('chart day filters recompute exactly that date and preserve site, tab, traffic and comparison', () => {
  const c=setup('?site=glow-coded&traffic=nodirect&compare=0#visits');
  c.run("SITES[1].g = [[260,2,10,20],[261,3,20,40]]; openChartRange(260,260)");
  assert.deepEqual(c.json('[win().s,win().e,state.tab,state.traffic,state.compare]'),[260,260,'visits','nodirect',false]);
  assert.equal(c.run('totals(scope(),win().s,win().e).clicks'),2);
  assert.equal(c.entries.filter(x=>x.method==='pushState').length,1);
  const reload=setup(c.context.location.search+c.context.location.hash);
  assert.deepEqual(reload.json('[win().s,win().e,...scope().map(s=>s.slug)]'),[260,260,'glow-coded']);
  c.run('backToPeriod()'); assert.equal(c.run('win().n'),28);
});
test('drawer charts select their own site and return restores the portfolio and drawer', () => {
  const c=setup('?sites=all'); c.context.openSlug='glow-coded';
  c.run("openChartRange(260,260,'glow-coded')"); assert.deepEqual(c.json('scope().map(s=>s.slug)'),['glow-coded']);
  c.run('backToPeriod()'); assert.equal(c.run('scope().length'),3); assert.equal(c.context.openSlug,'glow-coded');
});
test('day stepping moves both ways and stops at available boundaries', () => {
  const c=setup(); c.run('openChartRange(260,260); stepPeriod(1)'); assert.equal(c.run('win().s'),261);
  c.run('stepPeriod(-1)');assert.equal(c.run('win().s'),260);
  c.run('openChartRange(270,270)');assert.equal(c.run('stepPeriod(1)'),false);
  c.run('openChartRange(0,0)');assert.equal(c.run('stepPeriod(-1)'),false);
});
test('browser Back restores the range and site encoded by the previous entry', () => {
  const c=setup('?sites=all&period=7d');c.run('syncUrl()');const original=c.context.location.href;
  c.run('openChartRange(265,265)');c.context.location.href=original;c.events.popstate();
  assert.equal(c.run('win().n'),7);assert.equal(c.run('scope().length'),3);
});
test('bad dates cannot break the reporting window', () => {
  for(const q of ['?from=2026-02-30&to=2026-03-04','?from=2026-09-02&to=2026-08-01','?from=2099-01-01&to=2099-01-01']) {
    assert.equal(setup(q).run('win().n'),28);
  }
});
test('compact bars expose exact bucket boundaries, zero values and date labels', () => {
  const c=setup();const html=c.run("sparkBars(Array.from({length:91},(_,i)=>i), '#fff', 100, 'Clicks')");
  const ranges=[...html.matchAll(/data-chart-from="(\d+)" data-chart-to="(\d+)"/g)].map(m=>[+m[1],+m[2]]);
  assert.equal(ranges.length,30);assert.equal(ranges[0][0],100);assert.equal(ranges.at(-1)[1],190);
  for(let i=1;i<ranges.length;i++) assert.equal(ranges[i][0],ranges[i-1][1]+1);
  assert.equal((html.match(/tabindex="0"/g)||[]).length,1);
  assert.match(c.run("sparkBars([0,null], '#fff', 100, 'Clicks')"),/Clicks: 0/);
  assert.match(c.run("sparkBars([0,null], '#fff', 100, 'Clicks')"),/Clicks: no data/);
});
test('keyboard activation opens a day and prevents page scrolling', () => {
  const c=setup();let prevented=false;
  c.context.keyEvent={key:' ',preventDefault(){prevented=true;},target:{closest:()=>({dataset:{chartFrom:'260',chartTo:'260'}})}};
  assert.equal(c.run('handleChartKey(keyEvent)'),true);assert.equal(prevented,true);assert.equal(c.run('win().n'),1);
});

test('Mirai Skin links synchronize the top category and every scope label, including old All links', () => {
  for (const query of ['', '?lens=All&site=mirai-skin', '?lens=Main&site=mirai-skin', '?site=unknown']) {
    const c = setup(query);
    assert.equal(c.run('checkedLens()'), 'Main');
    assert.equal(c.run('scopeLabel()'), 'mirai-skin.com');
    assert.equal(c.run('scopeWords(scope())'), 'mirai-skin.com');
    c.run('syncUrl()');
    assert.equal(new URLSearchParams(c.context.location.search).get('lens'), 'Main');
    assert.equal(setup(c.context.location.search).run('checkedLens()'), 'Main');
  }
});
test('mixed explicit links keep all selected sites even if an old category disagrees', () => {
  const c = setup('?lens=AI&sites=mirai-skin,glow-coded');
  assert.deepEqual(c.json('scope().map(s=>s.slug)'), ['mirai-skin', 'glow-coded']);
  assert.equal(c.run('checkedLens()'), null, 'a partial mixed scope must not highlight All');
  assert.equal(c.run('scopeLabel()'), '2 selected sites');
  c.run('syncUrl()');
  const reload = setup(c.context.location.search);
  assert.deepEqual(reload.json('scope().map(s=>s.slug)'), ['mirai-skin', 'glow-coded']);
  assert.equal(reload.run('checkedLens()'), null);
});
test('site choices, category buttons, Select all and empty selection use consistent scopes', () => {
  const c = setup('?sites=all&traffic=nodirect&compare=0#visits');
  c.run("selectSites(new Set(['rooted-glow']))");
  assert.deepEqual(c.json('[checkedLens(),scopeLabel()]'), ['Satellites', 'rooted-glow.com']);
  c.run("selectSites(new Set(['rooted-glow','mirai-skin']))");
  assert.deepEqual(c.json('[checkedLens(),scopeLabel()]'), [null, '2 selected sites']);
  c.run("selectSites(new Set(['mirai-skin']))");
  assert.equal(c.run('checkedLens()'), 'Main');
  c.run("selectLens('Satellites')");
  assert.deepEqual(c.json('scope().map(s=>s.slug)'), ['glow-coded','rooted-glow']);
  c.run("selectLens('All')");
  assert.deepEqual(c.json('[checkedLens(),scopeLabel(),scope().length]'), ['All', 'All 3 sites', 3]);
  c.run("selectSites(new Set(['mirai-skin','rooted-glow','glow-coded','retired-site']))");
  assert.equal(c.run('state.sites'), null, 'full active selection canonicalizes to All, excluding retired sites');
  c.run('selectSites(new Set())');
  assert.deepEqual(c.json('[checkedLens(),scopeLabel(),scope().length]'), [null, 'No sites selected', 0]);
  assert.deepEqual(c.json('[state.tab,state.traffic,state.compare]'), ['visits','nodirect',false]);
});
test('single-site chart navigation and browser Back restore matching category and site scope', () => {
  const c = setup('?site=mirai-skin'); c.run('syncUrl()'); const initial = c.context.location.href;
  c.run("openChartRange(260,260,'glow-coded')");
  assert.deepEqual(c.json('[checkedLens(),scopeLabel()]'), ['Satellites','glow-coded.com']);
  c.run('backToPeriod()');
  assert.deepEqual(c.json('[checkedLens(),scopeLabel()]'), ['Main','mirai-skin.com']);
  c.run("selectLens('Main'); syncUrl(true)");
  c.context.location.href = initial; c.events.popstate();
  assert.deepEqual(c.json('[checkedLens(),scopeLabel()]'), ['Main','mirai-skin.com']);
});

test('embedded navigation shares only route state with the same-origin Mirai shell',()=>{
  const c=setup('?site=glow-coded#visits');let message,origin;
  c.context.window.parent={postMessage:(body,target)=>{message=body;origin=target;}};
  c.run('syncUrl()');
  assert.equal(origin,'http://localhost');assert.equal(message.type,'mirai-seo-route');assert.equal(message.hash,'#visits');
  assert.equal(new URLSearchParams(message.search).get('site'),'glow-coded');
  assert.deepEqual(Object.keys(message).sort(),['hash','search','type']);
});
