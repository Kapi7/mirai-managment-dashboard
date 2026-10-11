export const COLORS={instagram:'#c0659b',facebook:'#628acf',youtube:'#d57679',tiktok:'#514b67',pinterest:'#bb7378',x:'#829298'};
export const number=value=>value==null?'—':new Intl.NumberFormat('en',{maximumFractionDigits:1}).format(value);
export const date=value=>value&&Number.isFinite(Date.parse(value))?new Intl.DateTimeFormat('en-GB',{day:'numeric',month:'short',year:'numeric',timeZone:'UTC'}).format(new Date(value)):'Not recorded';
export function totalMetric(posts,key){let count=0,value=0,partial=false;for(const p of posts){let v=p.metrics?.[key];if(key==='interactions'&&v==null){const keys=['likes','comments','shares','saves'],known=keys.filter(k=>p.metrics?.[k]!=null);v=known.length?known.reduce((a,k)=>a+p.metrics[k],0):null;partial ||= known.length<keys.length;}if(v!=null){count++;value+=v;}}return {value:count?value:null,partial:partial||count<posts.length,count,total:posts.length};}
export const precise=m=>(m.value!=null&&m.partial?'≥ ':'')+number(m.value);
export function selectPosts(report,{channel='all',start,end,search='',sort='views'}={}){
 return (report?.posts||[]).filter(p=>(channel==='all'||p.platform===channel)&&(!start||p.publishedAt?.slice(0,10)>=start)&&(!end||p.publishedAt?.slice(0,10)<=end)&&(!search||`${p.title} ${p.contentId} ${p.platform}`.toLowerCase().includes(search.toLowerCase()))).sort((a,b)=>sort==='date'?(b.publishedAt||'').localeCompare(a.publishedAt||''):(sort==='interactions'?(totalMetric([b],sort).value??-1)-(totalMetric([a],sort).value??-1):(b.metrics?.[sort]??-1)-(a.metrics?.[sort]??-1)));
}
export function websiteTotals(website,channel='all',traffic='all'){
 const matches=r=>(channel==='all'||r.platform===channel)&&(traffic==='all'||(/paid|cpc|ppc|cpm|display|retarget/i.test(r.medium)=== (traffic==='paid')));
 const rows=website?.rows.filter(matches)||[],sales=website?.commerce.filter(matches)||[];
 const sum=(data,key,known)=>known?data.reduce((a,r)=>a+r[key],0):null;
 return {rows,sales,sessions:sum(rows,'sessions',website?.daily.length),engaged:sum(rows,'engaged_sessions',website?.daily.length),purchases:sum(sales,'purchases',website?.commerceDays.length),revenue:sum(sales,'revenue',website?.commerceDays.length)};
}

export function rangeFromParams(params,now=new Date()){
 const today=now.toISOString().slice(0,10),valid=d=>/^\d{4}-\d{2}-\d{2}$/.test(d||'')&&Number.isFinite(Date.parse(d))&&new Date(d).toISOString().slice(0,10)===d;
 const days=[7,28,60].includes(Number(params.get('days')))?Number(params.get('days')):28;
 const end=valid(params.get('end'))&&params.get('end')<=today?params.get('end'):today;
 const fallback=new Date(Date.parse(end)-86400000*(days-1)).toISOString().slice(0,10);
 const a=params.get('start'),start=valid(a)&&a<=end&&Date.parse(end)-Date.parse(a)<=365*86400000?a:fallback;
 return {start,end,days};
}
