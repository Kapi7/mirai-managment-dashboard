import http from 'node:http';

// Register before express.json(): preserve all legacy request bodies verbatim.
// Dashboard /reports-api routes retain their existing implementation.
export function reportsProxy(req, res, next) {
  if (process.env.REPORTS_ENABLED !== '1') return next();
  const prefix = '/automation-reports';
  if (req.url !== prefix && !req.url.startsWith(prefix + '/') && !req.url.startsWith(prefix + '?')) return next();
  const path = req.url.slice(prefix.length) || '/';
  const headers = { ...req.headers, host: '127.0.0.1:8081' };
  const upstream = http.request({ hostname: '127.0.0.1', port: 8081, method: req.method,
    path: path.startsWith('?') ? '/' + path : path, headers }, incoming => {
      res.writeHead(incoming.statusCode, incoming.headers);
      incoming.pipe(res);
      incoming.on('error', () => res.destroy());
  });
  upstream.setTimeout(180000, () => upstream.destroy(new Error('Reports timed out')));
  upstream.on('error', () => {
    if (!res.headersSent) res.writeHead(502, { 'Content-Type': 'application/json' });
    res.end(JSON.stringify({ error: 'Reports API unavailable' }));
  });
  req.on('aborted', () => upstream.destroy());
  res.on('close', () => { if (!res.writableEnded) upstream.destroy(); });
  req.pipe(upstream);
}
