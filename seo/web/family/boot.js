/* AIO dashboard page — loader.
   The server assembles this file with the sources in web/family/src (see
   server/family-page.js) and serves it as /family/app.js. The page asks the API
   for one dataset and renders everything from it in the browser. */
(() => {
  'use strict';
  const BASE = document.querySelector('meta[name="aio-base"]')?.content || '';
  // Every request uses the existing Mirai session. Tokens never enter URLs,
  // HTML, postMessage payloads, exports, or third-party requests.
  const fetch = (url, options = {}) => {
    const headers = new Headers(options.headers);
    const token = localStorage.getItem('mirai_auth_token');
    if (token && new URL(url, location.href).origin === location.origin) headers.set('Authorization', `Bearer ${token}`);
    return window.fetch(url, { ...options, headers });
  };
  async function refreshData() {
    const button = document.getElementById('refreshSeo');
    button.disabled = true; button.textContent = 'Refreshing…';
    try {
      const response = await fetch(`${BASE}/api/fetch`, { method: 'POST', headers: { 'Content-Type': 'application/json', 'X-SEO-Request': '1' }, body: '{}' });
      const body = await response.json();
      if (!response.ok) throw new Error(body.message || 'The refresh could not start.');
      for (;;) {
        await new Promise(resolve => setTimeout(resolve, 2500));
        const statusResponse = await fetch(`${BASE}/api/fetch/status`);
        const status = await statusResponse.json();
        if (!statusResponse.ok) throw new Error(status.message || 'Refresh status is unavailable.');
        if (!status.running) {
          if (status.error) throw new Error(status.error);
          location.reload(); return;
        }
      }
    } catch (error) { document.getElementById('refreshMessage').textContent = error.message; }
    finally { button.disabled = false; button.textContent = 'Refresh Google data'; }
  }
  document.getElementById('refreshSeo').addEventListener('click', refreshData);
  const box = () => document.getElementById('boot');
  function fail(title, detail) {
    const el = box(); if (!el) return;
    el.className = 'panel boot fail';
    el.textContent = '';
    const b = document.createElement('b'); b.textContent = title;
    const p = document.createElement('p'); p.textContent = detail;
    el.append(b, p);
  }
  fetch(`${BASE}/api/dashboard`, { credentials: 'same-origin', headers: { Accept: 'application/json' } })
    .then(async (res) => {
      const body = await res.json().catch(() => ({}));
      if (!res.ok) throw Object.assign(new Error(body.message || `The server answered ${res.status}.`), { code: body.error });
      return body;
    })
    .then((D) => {
      if (D.empty) {
        fail('Your Mirai SEO workspace is ready', 'No history has been collected yet. An administrator can use Refresh Google data to import Mirai Skin, Glow Coded and Rooted Glow. Missing credentials or access errors will be shown here.');
        fetch(`${BASE}/api/status`).then(r => r.json()).then(status => {
          const text = !status.googleConfigured ? 'Mirai Google credentials are not configured on this server.' : status.running ? 'The first import is running. Reload after it completes.' : status.failed.length ? 'Some sources need attention. Check Google permissions and refresh again.' : 'Google credentials are configured. Ready for the first import.';
          document.getElementById('refreshMessage').textContent = text;
        }).catch(() => {});
        return;
      }
      start(D);
    })
    .catch((err) => {
      console.error(err);
      if (err.code === 'no_database') fail('No data yet', 'Use Refresh Google data to collect the first history.');
      else fail('The dashboard could not load', err.message || 'Unknown error.');
    });

  function start(D) {
/*__APP__*/
  }
})();
