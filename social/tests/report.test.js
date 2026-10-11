import test from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync, mkdtempSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import express from 'express';
import { initDb, logFetch } from '../../seo/server/db.js';
import { createSeoRouter } from '../../seo/server/router.js';
import { loadConfig } from '../../seo/server/config.js';
import { dateRange, socialPlatform, validateReport, websiteReport } from '../server/report.js';
import { selectPosts, totalMetric, websiteTotals, rangeFromParams } from '../../src/features/social/data.js';
const empty=JSON.parse(readFileSync(new URL('../server/seed.json',import.meta.url)));
// Synthetic test data only. Production metrics are imported into private storage.
const seed={...structuredClone(empty),collectedAt:'2026-10-01T00:00:00Z',accounts:empty.accounts.map(a=>({...a,followers:10,baseline:9,observedAt:'2026-10-01T00:00:00Z'})),posts:[{id:'test-tiktok',platform:'tiktok',contentId:'test',title:'Test post',url:'https://www.tiktok.com/@test/video/123',publishedAt:'2026-10-01T00:00:00Z',observedAt:'2026-10-02T00:00:00Z',source:'Synthetic fixture',dateBasis:'confirmed',metrics:{views:100}}]};
test('public seed contains profiles only; production measurements are private',()=>{
 const r=validateReport(empty);assert.equal(r.posts.length,0);assert.equal(r.collectedAt,null);assert.ok(r.accounts.every(a=>a.followers===null));assert.equal(r.commerce.orders,null);
 const imported=validateReport(seed);assert.equal(imported.posts[0].dateBasis,'confirmed');assert.equal(imported.posts[0].metrics.views,100);
});
test('reject invalid dates, unknown platforms, duplicates, and unsafe URLs; drop extra fields',()=>{
 assert.throws(()=>dateRange({start:'2026-02-30',end:'2026-03-04'}));assert.throws(()=>dateRange({start:'2026-10-10',end:'2026-09-01'}));assert.throws(()=>dateRange({end:'junk'}));
 assert.equal(dateRange({days:'7'},new Date('2026-10-11')).start,'2026-10-03');
 const c=structuredClone(seed);c.posts.push(c.posts[0]);assert.throws(()=>validateReport(c));
 const bad=structuredClone(seed);bad.posts[0].url='javascript:alert(1)';assert.throws(()=>validateReport(bad));
 const extra=structuredClone(seed);extra.token='secret';extra.accounts[0].token='secret';assert.ok(!JSON.stringify(validateReport(extra)).includes('secret'));
});
test('source mapping uses exact platform aliases and real domains',()=>{
 assert.equal(socialPlatform('l.instagram.com'),'instagram');assert.equal(socialPlatform('m.facebook.com'),'facebook');assert.equal(socialPlatform('t.co'),'x');assert.equal(socialPlatform('instagram.com.attacker.tld'),null);assert.equal(socialPlatform('notinstagram'),null);
});
test('missing counters stay null and partial totals are marked; real zeros survive',()=>{
 assert.equal(totalMetric([{metrics:{}}],'views').value,null);assert.equal(totalMetric([{metrics:{views:0}}],'views').value,0);
 assert.deepEqual(totalMetric([{metrics:{views:100}},{metrics:{}}],'views'),{value:100,partial:true,count:1,total:2});
 assert.equal(totalMetric([{metrics:{likes:3,comments:0}}],'interactions').partial,true);
 assert.equal(totalMetric([{metrics:{interactions:0}}],'interactions').partial,false);
});
test('channel, search, date and ranking filters preserve follower snapshots',()=>{
 const selected=selectPosts(seed,{channel:'tiktok',start:'2026-10-01',end:'2026-10-09',sort:'views'});assert.equal(selected.length,1);assert.equal(selected[0].metrics.views,100);
 assert.equal(selectPosts(seed,{search:'no match'}).length,0);
 assert.equal(seed.accounts.find(a=>a.id==='tiktok').followers,10);
});
test('website queries isolate Mirai, distinguish missing days, paid traffic and successful zero commerce',()=>{
 const db=initDb(':memory:');const range={start:'2026-10-01',end:'2026-10-02',days:2};
 db.prepare('INSERT INTO ga4_daily(site,property_id,date,channel,sessions) VALUES(?,?,?,?,?)').run('mirai-skin','475812683','2026-10-01','Organic Social',8);
 const ins=db.prepare('INSERT INTO ga4_source(site,property_id,date,source,medium,sessions,engaged_sessions) VALUES(?,?,?,?,?,?,?)');
 ins.run('mirai-skin','475812683','2026-10-01','instagram','social',5,3);ins.run('mirai-skin','475812683','2026-10-01','facebook','paid_social',3,1);ins.run('glow-coded','530345570','2026-10-01','instagram','social',100,90);
 logFetch(db,{runAt:'2026-10-04T00:00:00Z',source:'ga4_commerce',site:'mirai-skin',connection:'475812683',startDate:'2026-10-01',endDate:'2026-10-02',dataThrough:'2026-10-02',rows:0,status:'ok'});
 const r=websiteReport(db,range);assert.equal(r.partial,true);assert.equal(r.commercePartial,false);assert.equal(websiteTotals(r).sessions,8);assert.equal(websiteTotals(r,'all','organic').sessions,5);assert.equal(websiteTotals(r,'all','paid').sessions,3);assert.equal(websiteTotals(r).purchases,0);db.close();
});
test('authenticated routes enforce privacy, admin writes, revisions and persistence',async()=>{
 const cfg=loadConfig();cfg.settings.database=join(mkdtempSync(join(tmpdir(),'mirai-social-test-')),'test.db');initDb(cfg.settings.database).close();
 const runtime={cfg,ready:Promise.resolve(),error:()=>null,state:{},freshness:()=>({}),mutate:fn=>fn(),refresh:async()=>({}),storage:{}};
 const app=express();app.use('/seo-dashboard',createSeoRouter({runtime,authorize:(req,res,next)=>{const token=req.get('authorization');if(!token)return res.status(401).json({error:'unauthorized'});req.seoUser={email:'qa@example.test',is_admin:token==='Bearer admin'};next();}}));
 const server=app.listen(0,'127.0.0.1');await new Promise(r=>server.once('listening',r));const url='http://127.0.0.1:'+server.address().port+'/seo-dashboard/api/social';
 try {
  assert.equal((await fetch(url)).status,401);const read=await fetch(url,{headers:{Authorization:'Bearer viewer'}});assert.equal(read.headers.get('cache-control'),'no-store');const data=await read.json();assert.equal(data.report.accounts.length,6);
  const body={status:'needs_attention',note:'QA record',revision:0};const send=(path,token,b=body)=>fetch(url+path,{method:'POST',headers:{Authorization:token,'Content-Type':'application/json','X-SEO-Request':'1'},body:JSON.stringify(b)});
  assert.equal((await send('/connections/instagram','Bearer viewer')).status,403);
  assert.equal((await send('/connections/instagram','Bearer admin')).status,200);
  assert.equal((await send('/connections/instagram','Bearer admin')).status,409);
  const saved=await (await fetch(url,{headers:{Authorization:'Bearer viewer'}})).json();assert.equal(saved.connections.instagram.note,'QA record');assert.equal(saved.revision,1);
  assert.equal((await send('/import','Bearer admin',{report:seed,revision:1})).status,200);
  assert.equal((await send('/import','Bearer admin',{report:{...seed,posts:[{url:'javascript:bad'}]},revision:2})).status,400);
 }finally{await new Promise(r=>server.close(r));}
});

test('malformed browser query dates safely resolve to a real range',()=>{const r=rangeFromParams(new URLSearchParams('start=broken&end=broken&days=99'),new Date('2026-10-11'));assert.equal(r.end,'2026-10-11');assert.equal(r.start,'2026-09-14');});
