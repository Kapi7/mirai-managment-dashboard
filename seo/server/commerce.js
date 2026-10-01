import { hostFilter } from './ga4.js';

export function initCommerce(database) {
  database.exec(`CREATE TABLE IF NOT EXISTS mirai_commerce (
    site TEXT NOT NULL, property_id TEXT NOT NULL, date TEXT NOT NULL,
    source TEXT NOT NULL, medium TEXT NOT NULL, sessions INTEGER NOT NULL,
    purchases REAL NOT NULL, revenue REAL NOT NULL,
    PRIMARY KEY(site,property_id,date,source,medium))`);
}

export async function fetchCommerce(database, client, site, startDate, endDate) {
  initCommerce(database);
  const rows = [];
  let offset = 0;
  for (;;) {
    const [body] = await client.runReport({
      property: `properties/${site.ga4PropertyId}`, ...hostFilter(site.ga4PropertyId),
      dimensions: ['date','sessionSource','sessionMedium'].map(name => ({ name })),
      metrics: ['sessions','ecommercePurchases','purchaseRevenue'].map(name => ({ name })),
      dateRanges: [{ startDate, endDate }], currencyCode: 'USD', limit: 100000, offset,
    });
    const batch = body.rows || [];
    for (const r of batch) {
      const d = r.dimensionValues.map(x => x.value), m = r.metricValues.map(x => Number(x.value));
      rows.push([site.slug,site.ga4PropertyId,`${d[0].slice(0,4)}-${d[0].slice(4,6)}-${d[0].slice(6,8)}`,d[1],d[2],...m]);
    }
    offset += batch.length;
    if (!batch.length || offset >= (body.rowCount || 0)) break;
  }
  // Replace the successfully collected window, including genuine zero results.
  // A failed/partial API request never erases the previous window.
  const insert = database.prepare('INSERT INTO mirai_commerce VALUES(?,?,?,?,?,?,?,?)');
  database.transaction(() => {
    database.prepare('DELETE FROM mirai_commerce WHERE site=? AND property_id=? AND date BETWEEN ? AND ?')
      .run(site.slug,site.ga4PropertyId,startDate,endDate);
    for (const row of rows) insert.run(...row);
  })();
  return rows.length;
}
