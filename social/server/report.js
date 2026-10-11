import { readFileSync } from 'node:fs';
import { openDb } from '../../seo/server/db.js';

const seed = JSON.parse(readFileSync(new URL('./seed.json', import.meta.url), 'utf8'));
const IDS = ['instagram','facebook','youtube','tiktok','pinterest','x'];
const HOSTS = ['instagram.com','facebook.com','youtube.com','youtu.be','tiktok.com','pinterest.com','x.com','twitter.com','github.com'];
const KEYS = ['views','impressions','reach','likes','comments','saves','shares','interactions','avg_watch_seconds','outbound_clicks','pin_clicks'];
const DAY = 86400000;
const text = (v, n=1000) => typeof v === 'string' ? v.slice(0,n) : '';
const num = v => typeof v === 'number' && Number.isFinite(v) && v >= 0 ? v : null;
const stamp = v => typeof v === 'string' && Number.isFinite(Date.parse(v)) ? v : null;
export function safeUrl(value) {
  try { const u = new URL(value); return u.protocol==='https:' && !u.username && !u.password && HOSTS.some(h=>u.hostname===h||u.hostname.endsWith('.'+h)) ? u.href : ''; } catch { return ''; }
}
export function validateReport(input) {
  if (input?.schemaVersion !== 1 || (input.collectedAt!==null && !stamp(input.collectedAt)) || !Array.isArray(input.accounts) || input.accounts.length!==6 || new Set(input.accounts.map(a=>a.id)).size!==6 || input.accounts.some(a=>!IDS.includes(a.id)) || !Array.isArray(input.posts) || input.posts.length>3000) throw new Error('Invalid report');
  if (input.collectedAt===null && (input.posts.length || input.accounts.some(a=>a.followers!=null) || input.commerce?.orders!=null)) throw new Error('A populated report needs a collection date');
  if (Date.parse(input.collectedAt)>Date.now()+DAY) throw new Error('Invalid report date');
  const posts=input.posts.map(p=>{
    if(!IDS.includes(p.platform)||!safeUrl(p.url)||!stamp(p.publishedAt))throw new Error('Invalid post');
    return {id:text(p.id,150),platform:p.platform,contentId:text(p.contentId,100),title:text(p.title,500),url:safeUrl(p.url),publishedAt:stamp(p.publishedAt),dateBasis:p.dateBasis==='confirmed'?'confirmed':'published',observedAt:stamp(p.observedAt),source:text(p.source,200),status:text(p.status,60),note:text(p.note),metrics:Object.fromEntries(KEYS.map(k=>[k,num(p.metrics?.[k])]))};
  });
  if(new Set(posts.map(p=>p.platform+'|'+p.url.replace(/\/$/,''))).size!==posts.length)throw new Error('Duplicate posts');
  const c=input.commerce||{};
  return {schemaVersion:1,collectedAt:stamp(input.collectedAt),campaignStart:text(input.campaignStart,10),
    accounts:input.accounts.map(a=>({id:a.id,name:text(a.name,50),handle:text(a.handle,100),url:safeUrl(a.url),followers:num(a.followers),observedAt:stamp(a.observedAt),baseline:num(a.baseline),baselineAt:stamp(a.baselineAt),mode:a.mode==='manual'?'manual':'api_report',note:text(a.note)})),posts,
    commerce:{observedAt:stamp(c.observedAt),start:text(c.start,10),end:text(c.end,10),currency:text(c.currency,3),status:text(c.status,50),orders:num(c.orders),note:text(c.note),sessions:(Array.isArray(c.sessions)?c.sessions:[]).slice(0,2000).map(r=>({utm_source:text(r.utm_source,100),utm_medium:text(r.utm_medium,100),utm_campaign:text(r.utm_campaign,120),scope:text(r.scope,30),...Object.fromEntries(['sessions','sessions_with_cart_additions','sessions_that_reached_checkout','sessions_that_completed_checkout'].map(k=>[k,num(r[k])]))}))},
    delivery:{observedAt:stamp(input.delivery?.observedAt),queued:num(input.delivery?.queued),stories:num(input.delivery?.stories),held:num(input.delivery?.held)},evidenceUrl:safeUrl(input.evidenceUrl)};
}
export function socialPlatform(source) {
 const s=String(source||'').toLowerCase().trim().replace(/^https?:\/\//,'').split('/')[0];
 for(const [id,names] of Object.entries({instagram:['instagram','ig','instagram.com'],facebook:['facebook','fb','facebook.com','fb.com','fb.me'],youtube:['youtube','youtube.com','youtu.be'],tiktok:['tiktok','tiktok.com'],pinterest:['pinterest','pinterest.com','pin.it'],x:['x','twitter','x.com','twitter.com','t.co']})) {
  if(names.some(n=>s===n||(n.includes('.')&&s.endsWith('.'+n))))return id;
 }
 return null;
}
export function dateRange(query={},now=new Date()) {
 const end=query.end || new Date(now.getTime()-2*DAY).toISOString().slice(0,10);
 const days=[7,28,60].includes(Number(query.days))?Number(query.days):28;
 const start=query.start || new Date(Date.parse(end)-DAY*(days-1)).toISOString().slice(0,10);
 if (![start,end].every(d=>typeof d==='string'&&/^\d{4}-\d{2}-\d{2}$/.test(d)&&Number.isFinite(Date.parse(d))&&new Date(d).toISOString().slice(0,10)===d) || start>end || Date.parse(end)-Date.parse(start)>365*DAY || end>now.toISOString().slice(0,10))throw new Error('Choose a valid date range of up to 366 days.');
 return {start,end,days:Math.round((Date.parse(end)-Date.parse(start))/DAY)+1};
}
function readSaved(database) {
 if (!database.prepare("SELECT name FROM sqlite_master WHERE name='mirai_social_state'").get()) return {revision:0,report:seed,connections:{}};
 const row=database.prepare('SELECT value FROM mirai_social_state WHERE id=1').get();
 if(!row)return {revision:0,report:seed,connections:{}};
 const saved=JSON.parse(row.value);
 return {...saved,report:(Date.parse(saved.report.collectedAt)||0)>=(Date.parse(seed.collectedAt)||0)?saved.report:seed};
}
export function websiteReport(database, range) {
 const site='mirai-skin',pid='475812683';
 const daily=database.prepare('SELECT DISTINCT date FROM ga4_source WHERE site=? AND property_id=? AND date BETWEEN ? AND ? ORDER BY date').all(site,pid,range.start,range.end).map(r=>r.date);
 const rows=database.prepare('SELECT date,source,medium,sessions,engaged_sessions FROM ga4_source WHERE site=? AND property_id=? AND date BETWEEN ? AND ? ORDER BY date').all(site,pid,range.start,range.end).map(r=>({...r,platform:socialPlatform(r.source)})).filter(r=>r.platform);
 const commerce=database.prepare('SELECT date,source,medium,purchases,revenue FROM mirai_commerce WHERE site=? AND property_id=? AND date BETWEEN ? AND ? ORDER BY date').all(site,pid,range.start,range.end).map(r=>({...r,platform:socialPlatform(r.source)})).filter(r=>r.platform);
 const logs=database.prepare("SELECT source,status,run_at,start_date,end_date,data_through FROM fetch_log WHERE site=? AND source IN ('ga4','ga4_commerce') ORDER BY id DESC").all(site);
 const commerceWindows=logs.filter(r=>r.source==='ga4_commerce'&&r.status==='ok'&&r.start_date&&r.end_date);
 const commerceDays=Array.from({length:range.days},(_,i)=>new Date(Date.parse(range.start)+i*DAY).toISOString().slice(0,10)).filter(d=>commerceWindows.some(w=>d>=w.start_date&&d<=w.end_date));
 return {range,rows,commerce,daily,commerceDays,currency:'USD',freshness:{traffic:logs.find(r=>r.source==='ga4')||null,commerce:logs.find(r=>r.source==='ga4_commerce')||null},partial:daily.length<range.days,commercePartial:commerceDays.length<range.days};
}
export function registerSocialRoutes(router,runtime) {
 router.get('/api/social', (req,res)=>{
  let range;try{range=dateRange(req.query);}catch(e){return res.status(400).json({message:e.message});}
  const db=openDb(runtime.cfg.settings.database,{readonly:true});
  try {const state=readSaved(db);res.json({...state,report:validateReport(state.report),website:websiteReport(db,range),canManage:!!req.seoUser?.is_admin,loadedAt:new Date().toISOString()});}finally{db.close();}
 });
 async function save(req,res,operation) {
  if(req.get('X-SEO-Request')!=='1'||!req.is('application/json'))return res.status(403).json({message:'Invalid request.'});
  try {await runtime.mutate(async()=>{
   const db=openDb(runtime.cfg.settings.database);
   try {const current=readSaved(db);if(req.body.revision!==current.revision){const e=new Error('This report changed. Reload before saving.');e.status=409;throw e;}
    const next=operation(current);next.revision=current.revision+1;
    db.exec('CREATE TABLE IF NOT EXISTS mirai_social_state(id INTEGER PRIMARY KEY CHECK(id=1),value TEXT NOT NULL)');
    db.prepare('INSERT INTO mirai_social_state VALUES(1,?) ON CONFLICT(id) DO UPDATE SET value=excluded.value').run(JSON.stringify(next));
   }finally{db.close();}return {failed:[]};
  });res.json({ok:true});}catch{res.status(409).json({message:'Could not save. Reload the report and try again; another update may be running.'});}
 }
 router.post('/api/social/import',(req,res)=>{
  let report;try{report=validateReport(req.body.report);}catch{return res.status(400).json({message:'Use a valid Mirai social report package.'});}
  return save(req,res,current=>{if((Date.parse(report.collectedAt)||0)<(Date.parse(current.report.collectedAt)||0))throw new Error('Older report');return {...current,report};});
 });
 router.post('/api/social/connections/:id',(req,res)=>{
  if(!IDS.includes(req.params.id)||!['verified','needs_attention','unknown'].includes(req.body.status))return res.status(400).json({message:'Invalid channel record.'});
  const record={status:req.body.status,note:text(req.body.note),updatedAt:new Date().toISOString()};
  return save(req,res,current=>({...current,connections:{...current.connections,[req.params.id]:record}}));
 });
}
