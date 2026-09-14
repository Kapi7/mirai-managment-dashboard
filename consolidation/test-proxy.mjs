import http from 'node:http';
import assert from 'node:assert/strict';
import { reportsProxy } from './reports-proxy.js';
const upstream = http.createServer(async (req,res) => {
 let body='';for await (const chunk of req) body+=chunk;
 res.writeHead(201,{'Content-Type':'application/json','X-Reports-Test':'preserved'});
 res.end(JSON.stringify({url:req.url,method:req.method,body}));
});
const gateway=http.createServer((req,res)=>reportsProxy(req,res,()=>{res.writeHead(404);res.end('existing dashboard');}));
await new Promise(r=>upstream.listen(8081,'127.0.0.1',r));
await new Promise(r=>gateway.listen(0,'127.0.0.1',r));
const base=`http://127.0.0.1:${gateway.address().port}`;
try {
 process.env.REPORTS_ENABLED='0';assert.equal((await fetch(base+'/automation-reports/health')).status,404);
 process.env.REPORTS_ENABLED='1';
 const body=JSON.stringify({start_date:'2026-09-01',end_date:'2026-09-02'});
 const r=await fetch(base+'/automation-reports/daily-report?x=1',{method:'POST',headers:{'Content-Type':'application/json'},body});
 assert.equal(r.status,201);assert.equal(r.headers.get('x-reports-test'),'preserved');
 assert.deepEqual(await r.json(),{url:'/daily-report?x=1',method:'POST',body});
 assert.equal((await fetch(base+'/reports-api/daily-report')).status,404);
 assert.equal((await fetch(base+'/automation-reports-wrong')).status,404);
 await new Promise(r=>upstream.close(r));
 assert.equal((await fetch(base+'/automation-reports/health')).status,502);
 console.log('PASS: proxy gates, path/query/body/header preservation, dashboard isolation, upstream failure');
} finally {gateway.closeAllConnections();gateway.close();upstream.closeAllConnections();upstream.close();}
