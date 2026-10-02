import test from 'node:test';
import assert from 'node:assert/strict';
import vm from 'node:vm';
import { readFileSync } from 'node:fs';
import { googleFreshness } from '../server/freshness.js';
import { createRuntime } from '../server/runtime.js';
import { loadConfig } from '../server/config.js';
import { logFetch } from '../server/db.js';
import { tempDb } from './helpers.js';

const now = new Date('2026-10-02T05:00:00Z');
function seed(database, cfg, { runAt = '2026-10-02T04:00:00Z', oldDay = false } = {}) {
  for (const site of cfg.sites) {
    for (const [source, connection] of [['gsc',site.gscProperty],['ga4',site.ga4PropertyId],['ga4_commerce',site.ga4PropertyId]]) {
      const endDate = source === 'gsc' ? (oldDay ? '2026-09-28' : '2026-09-29') : (oldDay ? '2026-09-29' : '2026-09-30');
      logFetch(database,{runAt,source,site:site.slug,connection,endDate,dataThrough:endDate,status:'ok',rows:1});
    }
  }
}

test('new reporting day is due even when yesterday’s import is less than 24 hours old', () => {
  const t=tempDb(),cfg=loadConfig();
  try {
    seed(t.database,cfg,{runAt:'2026-10-01T15:00:00Z',oldDay:true});
    const status=googleFreshness(t.database,cfg,now);
    assert.equal(status.due,true);assert.equal(status.sources.length,9);
    assert.ok(status.sources.every(s=>s.reason==='new_reporting_day'));
    assert.equal(status.sources.find(s=>s.source==='gsc').expectedThrough,'2026-09-29');
    assert.equal(status.sources.find(s=>s.source==='ga4').expectedThrough,'2026-09-30');
  } finally {t.cleanup();}
});

test('healthy imports wait six hours before checking late corrections again', () => {
  const t=tempDb(),cfg=loadConfig();
  try {
    seed(t.database,cfg);
    assert.equal(googleFreshness(t.database,cfg,now).due,false);
    const later=googleFreshness(t.database,cfg,new Date('2026-10-02T10:00:00Z'));
    assert.equal(later.due,true);assert.ok(later.sources.every(s=>s.reason==='scheduled'));
  } finally {t.cleanup();}
});

test('a satellite or commerce failure is not hidden by newer healthy GA4 imports', () => {
  const t=tempDb(),cfg=loadConfig();
  try {
    seed(t.database,cfg);
    logFetch(t.database,{runAt:now.toISOString(),source:'gsc',site:'rooted-glow',connection:cfg.sites[2].gscProperty,status:'error'});
    logFetch(t.database,{runAt:now.toISOString(),source:'ga4_commerce',site:'mirai-skin',connection:cfg.sites[0].ga4PropertyId,status:'error'});
    const status=googleFreshness(t.database,cfg,now);
    assert.equal(status.due,true);assert.equal(status.failures,2);
    assert.deepEqual(status.sources.filter(s=>s.reason).map(s=>s.reason),['retry','retry']);
  } finally {t.cleanup();}
});

test('changing a property requires its own successful import', () => {
  const t=tempDb(),cfg=loadConfig();
  try {
    seed(t.database,cfg);cfg.sites[1].ga4PropertyId='new-property';
    const missing=googleFreshness(t.database,cfg,now).sources.filter(s=>s.reason);
    assert.equal(missing.length,2);assert.ok(missing.every(s=>s.site==='glow-coded'&&s.reason==='not_fetched'));
  } finally {t.cleanup();}
});

test('a successful empty reporting window keeps its actual date without an hourly retry loop', () => {
  const t=tempDb(),cfg=loadConfig();
  try {
    seed(t.database,cfg);
    logFetch(t.database,{runAt:now.toISOString(),source:'gsc',site:'rooted-glow',connection:cfg.sites[2].gscProperty,
      endDate:'2026-09-29',dataThrough:'2026-09-27',status:'ok',rows:0});
    const status=googleFreshness(t.database,cfg,now);
    assert.equal(status.due,false);assert.equal(status.sources.find(s=>s.site==='rooted-glow'&&s.source==='gsc').dataThrough,'2026-09-27');
  } finally {t.cleanup();}
});

test('scheduler checks all sources, runs only Google, and skips another import while busy', async () => {
  const t=tempDb(),cfg=loadConfig();cfg.settings.database=t.path;const calls=[];let unblock;
  const wait=new Promise(resolve=>{unblock=resolve;});
  const runtime=createRuntime({cfg,fetcher:async options=>{calls.push(options.source);await wait;return {failed:[]};},
    storage:{durable:true,async restore(){},async exclusive(op){return op();},async close(){}}});
  try {
    await runtime.ready;
    const first=runtime.checkRefresh(now);await new Promise(resolve=>setImmediate(resolve));
    assert.equal(runtime.state.running,true);await runtime.checkRefresh(now);
    assert.deepEqual(calls,['gsc']);unblock();await first;
    assert.deepEqual(calls,['gsc','ga4']);assert.equal(runtime.state.nextCheckAt,'2026-10-02T06:00:00.000Z');
    seed(t.database,cfg);await runtime.checkRefresh(now);assert.equal(calls.length,2);
  } finally {unblock();await runtime.close();t.cleanup();}
});

test('open dashboards reload only after import completion and preserve active editing', async () => {
  let poll, visibility, reloads=0, editing=false, status={running:true,freshness:{lastFetch:'new'}};
  const message={textContent:''};
  const initial={lastFetch:'old',refresh:{freshness:{lastFetch:'old'}}};
  const context={Headers,URL,location:{href:'https://mirai.test/seo-dashboard/?period=7d#visits',origin:'https://mirai.test',reload(){reloads++;}},
    localStorage:{getItem(){return null;}},console,CustomEvent:class{constructor(type,options){this.type=type;this.detail=options.detail;}},
    setInterval(callback){poll=callback;},
    document:{visibilityState:'visible',activeElement:{matches(){return editing;}},
      querySelector(){return {content:'/seo-dashboard'};},
      getElementById(id){return id==='refreshMessage'?message:{addEventListener(){}};},
      addEventListener(_event,callback){visibility=callback;},dispatchEvent(){}},
    window:{fetch:async url=>({ok:true,json:async()=>url.endsWith('/api/dashboard')?initial:status})}};
  vm.runInNewContext(readFileSync(new URL('../web/family/boot.js',import.meta.url),'utf8'),context);
  await new Promise(resolve=>setImmediate(resolve));
  await poll();assert.equal(reloads,0);assert.match(message.textContent,/Updating/);
  status.running=false;editing=true;await poll();assert.equal(reloads,0);assert.match(message.textContent,/Finish editing/);
  editing=false;context.document.visibilityState='hidden';await poll();assert.equal(reloads,0);
  context.document.visibilityState='visible';await visibility();assert.equal(reloads,1);
});
