import test from 'node:test';
import assert from 'node:assert/strict';
import express from 'express';
import vm from 'node:vm';
import { readFileSync, writeFileSync, mkdtempSync, rmSync } from 'node:fs';
import { join } from 'node:path';
import { tmpdir } from 'node:os';
import { loadConfig } from '../server/config.js';
import { readGoogleCredential } from '../server/google-credentials.js';
import { createSeoRouter } from '../server/router.js';
import { createRuntime } from '../server/runtime.js';
import { familyScript, familyHtml } from '../server/family-page.js';
import { fetchCommerce } from '../server/commerce.js';
import { buildDashboard } from '../server/dashboard.js';
import { tempDb, makeSite, seedGscDaily } from './helpers.js';

test('Mirai registry contains only the main Shopify store and its two satellites', () => {
  const cfg = loadConfig();
  assert.deepEqual(cfg.sites.map(s => [s.slug,s.vertical,s.ga4PropertyId]), [
    ['mirai-skin','Main','475812683'],['glow-coded','Satellites','530345570'],['rooted-glow','Satellites','530337594'],
  ]);
  assert.equal(cfg.wpSites.length, 0);
  assert.ok(cfg.sites.every(s => s.gscAuth === 'mirai' && s.ga4Auth === 'mirai' && s.hosts.length));
  assert.equal(cfg.credentials.mirai.envVar, 'MIRAI_SEO_GOOGLE_TOKEN_PATH');
});

test('existing Mirai OAuth export is normalized without changing its file', () => {
  const dir=mkdtempSync(join(tmpdir(),'mirai-oauth-')), file=join(dir,'token.json');
  const input={client_id:'id',client_secret:'secret',refresh_token:'refresh',token:'expired',expiry:'old',scopes:['analytics.readonly']};
  writeFileSync(file,JSON.stringify(input));
  try { assert.deepEqual(readGoogleCredential(file),{type:'authorized_user',client_id:'id',client_secret:'secret',refresh_token:'refresh'});
    assert.deepEqual(JSON.parse(readFileSync(file)),input); } finally { rmSync(dir,{recursive:true,force:true}); }
});

test('every SEO API fails closed without a Mirai bearer session', async () => {
  const t=tempDb(), cfg=loadConfig(); cfg.settings.database=t.path;
  const runtime=createRuntime({cfg,storage:{durable:false,async restore(){},async save(){},async close(){}}});
  const app=express(); app.use('/seo-dashboard',createSeoRouter({runtime}));
  const server=app.listen(0,'127.0.0.1'); await new Promise(r=>server.once('listening',r));
  const base=`http://127.0.0.1:${server.address().port}/seo-dashboard`;
  try {
    for (const endpoint of ['/api/dashboard','/api/status','/api/connections','/api/authority/research?site=mirai-skin','/api/unknown']) {
      const r=await fetch(base+endpoint); assert.equal(r.status,401,endpoint);
      assert.ok(!JSON.stringify(await r.json()).includes('client_secret'));
    }
    assert.equal((await fetch(base+'/api/fetch',{method:'POST',headers:{'Content-Type':'application/json','X-SEO-Request':'1'},body:'{}'})).status,401);
    const shell=await fetch(base+'/'); assert.equal(shell.status,200);
    assert.equal(shell.headers.get('x-frame-options'),'SAMEORIGIN');
    assert.ok(!(await shell.text()).includes('475812683'), 'shell carries no business dataset');
  } finally { server.closeAllConnections(); await new Promise(r=>server.close(r)); await runtime.close();t.cleanup(); }
});

test('Mirai viewers can read analytics but cannot refresh data or spend Ahrefs units', async () => {
  const t=tempDb(),cfg=loadConfig();cfg.settings.database=t.path;
  const runtime=createRuntime({cfg,storage:{durable:false,async restore(){},async save(){},async close(){}}});
  const app=express();app.use(createSeoRouter({runtime,authorize:(req,_res,next)=>{req.seoUser={email:'viewer@example.test',is_admin:false};next();}}));
  const server=app.listen(0,'127.0.0.1');await new Promise(r=>server.once('listening',r));const base=`http://127.0.0.1:${server.address().port}`;
  try {
    const r=await fetch(base+'/api/dashboard');assert.equal(r.status,200);assert.equal(r.headers.get('cache-control'),'no-store');assert.equal((await r.json()).empty,true);
    for(const endpoint of ['/api/fetch','/api/authority/research','/api/authority/refresh']) assert.equal((await fetch(base+endpoint,{method:'POST',headers:{'Content-Type':'application/json','X-SEO-Request':'1'},body:'{}'})).status,403);
  } finally {server.closeAllConnections();await new Promise(r=>server.close(r));await runtime.close();t.cleanup();}
});

test('commerce uses production hosts and USD; a failed fetch preserves history and a successful zero clears it',async()=>{
  const t=tempDb(),site=loadConfig().sites[0];let request;
  const client={runReport:async input=>{request=input;return [{rowCount:1,rows:[{dimensionValues:[{value:'20260928'},{value:'glow-coded.com'},{value:'referral'}],metricValues:[{value:'4'},{value:'1'},{value:'32.5'}]}]}];}};
  try {
    assert.equal(await fetchCommerce(t.database,client,site,'2026-09-28','2026-09-28'),1);
    assert.deepEqual(request.dimensionFilter.filter.inListFilter.values,site.hosts);assert.equal(request.currencyCode,'USD');
    const row=t.database.prepare('SELECT * FROM mirai_commerce').get();assert.equal(row.purchases,1);assert.equal(row.revenue,32.5);
    await assert.rejects(fetchCommerce(t.database,{runReport:async()=>{throw Error('offline');}},site,'2026-09-28','2026-09-28'));
    assert.equal(t.database.prepare('SELECT COUNT(*) n FROM mirai_commerce').get().n,1);
    await fetchCommerce(t.database,{runReport:async()=>[{rowCount:0,rows:[]}]},site,'2026-09-28','2026-09-28');
    assert.equal(t.database.prepare('SELECT COUNT(*) n FROM mirai_commerce').get().n,0);
  } finally {t.cleanup();}
});

test('large query samples are bounded without changing headline totals',()=>{
  const t=tempDb(),site=makeSite();
  try {
    seedGscDaily(t.database,'alpha','2026-09-28',1,()=>({impressions:100000,clicks:1000,position:7}));
    const q=t.database.prepare('INSERT INTO gsc_query VALUES(?,?,?,?,?,?,?)');
    t.database.transaction(()=>{for(let i=0;i<550;i++)q.run('alpha','2026-09-28','query '+i,1,550-i,.1,7);})();
    const result=buildDashboard(t.database,{sites:[site],credentials:{},settings:{affiliateEvents:[]}});
    assert.equal(result.sites[0].q.length,500);assert.equal(result.sites[0].g[0][2],100000);
  } finally {t.cleanup();}
});

test('combined browser bundle parses; shell exposes Mirai hierarchy and refresh',()=>{
  new vm.Script(familyScript()); const html=familyHtml('/seo-dashboard');
  for(const name of ['Mirai SEO','Mirai Skin','Glow Coded','Rooted Glow','Refresh Google data'])assert.ok(html.includes(name));
  assert.ok(!html.includes('Aether')); assert.ok(!html.includes('top10ai'));
});

test('durable cache survives an ephemeral filesystem restart with history intact',async()=>{
  const {createStorage}=await import('../server/storage.js');
  const {openDb}=await import('../server/db.js');
  const t=tempDb(), dir=mkdtempSync(join(tmpdir(),'mirai-restore-'));
  let snapshot;
  const pool={async query(sql,args){if(sql.startsWith('INSERT'))snapshot=args[1];return {rows:snapshot?[{snapshot}]:[]};},async end(){}};
  const writer=createStorage(t.path,null,pool), target=join(dir,'restored.db'),reader=createStorage(target,null,pool);
  try{
    seedGscDaily(t.database,'alpha','2026-09-28',2);
    await writer.save();assert.ok(snapshot.length>0);
    await reader.restore();const restored=openDb(target,{readonly:true});
    try{assert.equal(restored.prepare('SELECT SUM(clicks) n FROM gsc_daily').get().n,20);assert.equal(restored.pragma('integrity_check',{simple:true}),'ok');}finally{restored.close();}
  }finally{await writer.close();await reader.close();t.cleanup();rmSync(dir,{recursive:true,force:true});}
});

test('durable writer refuses a second instance before invoking upstream operations', async()=>{
  const {createStorage}=await import('../server/storage.js');const t=tempDb();let released=false, called=false;
  const pool={async query(){return {rows:[]};},async connect(){return {async query(){return {rows:[{locked:false}]};},release(){released=true;}};},async end(){}};
  const storage=createStorage(t.path,null,pool);
  try{await assert.rejects(storage.exclusive(async()=>{called=true;}),/Another Mirai/);assert.equal(called,false);assert.equal(released,true);}finally{await storage.close();t.cleanup();}
});

test('runtime serializes refreshes, preserves errors and never exposes provider secrets',async()=>{
  const t=tempDb(),cfg=loadConfig();cfg.settings.database=t.path;let unblock;
  const pending=new Promise(resolve=>{unblock=resolve;});let saved=0;
  const runtime=createRuntime({cfg,fetcher:async()=>{await pending;return {failed:[],sourceAsOf:{}};},storage:{durable:true,async restore(){},async exclusive(op){const result=await op();saved++;return result;},async close(){}}});
  try{await runtime.ready;const first=runtime.refresh();await Promise.resolve();await assert.rejects(runtime.refresh(),/already running/);unblock();await first;assert.equal(saved,1);assert.equal(runtime.state.running,false);
    await assert.rejects(runtime.mutate(async()=>{throw Error('client_secret=private');}),/could not complete/);assert.ok(!JSON.stringify(runtime.state).includes('private'));
  }finally{unblock();await runtime.close();t.cleanup();}
});

test('commerce graph distinguishes missing days from a source observed at zero',()=>{
  const source=readFileSync(new URL('../web/family/src/ecosystem.js',import.meta.url),'utf8');
  const context=vm.createContext({});vm.runInContext(source,context);
  context.sites=[{sales:[[10,'google','organic',8,2,90],[11,'direct','none',5,1,40]]}];
  const actual=JSON.parse(vm.runInContext("JSON.stringify(commerceSeries(sites,{s:10,e:12},'sessions',r=>r.medium==='organic'))",context));
  assert.deepEqual(actual,[8,0,null]);
  context.sites.push({sales:[[10,'google','organic',3,0,0]]});
  assert.deepEqual(JSON.parse(vm.runInContext("JSON.stringify(commerceSeries(sites,{s:10,e:12},'purchases'))",context)),[2,null,null]);
});

test('a dropped Postgres cache connection never crashes the app or saves without its lock',async()=>{
  const {EventEmitter}=await import('node:events');const {createStorage}=await import('../server/storage.js');const t=tempDb();
  const client=new EventEmitter();let destroyed=false,writes=0;
  client.query=async sql=>{if(sql.startsWith('INSERT'))writes++;return {rows:[{locked:true}]};};client.release=bad=>{destroyed=bad;};
  const pool=new EventEmitter();pool.query=async()=>({rows:[]});pool.connect=async()=>client;pool.end=async()=>{};
  const storage=createStorage(t.path,null,pool);
  try{
    assert.doesNotThrow(()=>pool.emit('error',new Error('idle connection reset')));
    await assert.rejects(storage.exclusive(async()=>{client.emit('error',new Error('active connection reset'));return {failed:[]};}),/interrupted/);
    assert.equal(writes,0);assert.equal(destroyed,true);
  }finally{await storage.close();t.cleanup();}
});

test('persistent-disk mode keeps SEO independent of the management Postgres connection',async()=>{
  const {createStorage}=await import('../server/storage.js');const t=tempDb();
  const oldMode=process.env.MIRAI_SEO_STORAGE,oldUrl=process.env.DATABASE_URL;
  process.env.MIRAI_SEO_STORAGE='disk';process.env.DATABASE_URL='postgres://unreachable.invalid/should-not-connect';
  const storage=createStorage(t.path);
  try{assert.equal(storage.durable,true);await storage.restore();assert.equal(await storage.exclusive(async()=>42),42);}
  finally{await storage.close();t.cleanup();if(oldMode===undefined)delete process.env.MIRAI_SEO_STORAGE;else process.env.MIRAI_SEO_STORAGE=oldMode;if(oldUrl===undefined)delete process.env.DATABASE_URL;else process.env.DATABASE_URL=oldUrl;}
});
