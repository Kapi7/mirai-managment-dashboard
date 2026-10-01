import { existsSync, mkdirSync, readFileSync, renameSync, rmSync, createReadStream, createWriteStream } from 'node:fs';
import { open } from 'node:fs/promises';
import { dirname } from 'node:path';
import { createGzip, createGunzip } from 'node:zlib';
import { Readable, Transform } from 'node:stream';
import { pipeline } from 'node:stream/promises';
import pg from 'pg';
import { openDb } from './db.js';

// Render's filesystem is ephemeral. Keep an atomic compressed aggregate-only
// cache in the existing Mirai Postgres database; no customer or credential data.
export function createStorage(filename, connectionString = process.env.DATABASE_URL, suppliedPool) {
  const pool = suppliedPool || (connectionString ? new pg.Pool({ connectionString, max: 2, connectionTimeoutMillis: 10000,
    keepAlive: true, keepAliveInitialDelayMillis: 10000, query_timeout: 30000 }) : null);
  // A dropped idle cache connection must never take down the management app.
  pool?.on?.('error', () => {});
  const key = 'mirai-seo-v1';
  let initialized = false;
  async function initialize() {
    if (!pool || initialized) return;
    await pool.query(`CREATE TABLE IF NOT EXISTS mirai_seo_cache (
      name TEXT PRIMARY KEY, snapshot BYTEA NOT NULL, updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW())`);
    initialized = true;
  }
  let writing = false;
  const storage = {
    durable: Boolean(pool),
    async restore({ force = false } = {}) {
      if (!pool || (!force && existsSync(filename))) return;
      await initialize();
      const { rows } = await pool.query('SELECT snapshot FROM mirai_seo_cache WHERE name=$1', [key]);
      if (!rows.length) return;
      mkdirSync(dirname(filename), { recursive: true });
      let size = 0;
      const limit = new Transform({ transform(chunk, _encoding, callback) {
        size += chunk.length;
        callback(size > 2 * 1024 ** 3 ? new Error('SEO cache exceeds the restore limit') : null, chunk);
      } });
      try {
        await pipeline(Readable.from([rows[0].snapshot]), createGunzip(), limit, createWriteStream(filename + '.restore', { mode: 0o600 }));
        const file = await open(filename + '.restore', 'r');
        const header = Buffer.alloc(16);
        try { await file.read(header, 0, 16, 0); } finally { await file.close(); }
        if (header.toString() !== 'SQLite format 3\0') throw new Error('Invalid SEO cache');
        // All application SQLite handles are short-lived and closed before a
        // mutation begins. Remove sidecars from the previous local snapshot.
        rmSync(filename + '-wal', { force: true });
        rmSync(filename + '-shm', { force: true });
        renameSync(filename + '.restore', filename);
      } finally { rmSync(filename + '.restore', { force: true }); }
    },
    async save(queryClient = pool) {
      if (!pool || !existsSync(filename)) return;
      await initialize();
      const temporary = filename + '.snapshot';
      const database = openDb(filename);
      try {
        await database.backup(temporary);
        await pipeline(createReadStream(temporary), createGzip(), createWriteStream(temporary + '.gz', { mode: 0o600 }));
        const bytes = readFileSync(temporary + '.gz');
        await queryClient.query(`INSERT INTO mirai_seo_cache(name,snapshot) VALUES($1,$2)
          ON CONFLICT(name) DO UPDATE SET snapshot=EXCLUDED.snapshot,updated_at=NOW()`, [key, bytes]);
      } finally { database.close(); rmSync(temporary, { force: true }); rmSync(temporary + '.gz', { force: true }); }
    },
    async exclusive(operation) {
      if (writing) throw new Error('An SEO update is already running.');
      writing = true;
      let client, heartbeat, locked = false, connectionLost = false;
      const lostConnection = () => { connectionLost = true; };
      try {
        if (pool) {
          await initialize();
          client = await pool.connect();
          client.on?.('error', lostConnection);
          const result = await client.query('SELECT pg_try_advisory_lock(173528711, 1) AS locked');
          locked = result.rows[0]?.locked === true;
          if (!locked) throw new Error('Another Mirai instance is updating SEO.');
          // Remote Postgres proxies may close idle connections while Google is
          // importing. Keep this session (and its advisory lock) alive.
          heartbeat = setInterval(() => {
            if (!connectionLost) client.query('SELECT 1').catch(lostConnection);
          }, 15000);
          heartbeat.unref();
          // Rolling deployments must build on the latest durable history.
          await storage.restore({ force: true });
        }
        const result = await operation();
        if (connectionLost) throw new Error('The SEO cache connection was interrupted. Please retry the refresh.');
        // Write through the session that owns the lock, never after losing it.
        await storage.save(client || pool);
        return result;
      } finally {
        clearInterval(heartbeat);
        try {
          if (client) {
            try { if (locked && !connectionLost) await client.query('SELECT pg_advisory_unlock(173528711, 1)'); }
            finally {
              client.release(connectionLost);
              if (!connectionLost) client.removeListener?.('error', lostConnection);
            }
          }
        } finally { writing = false; }
      }
    },
    async close() { await pool?.end(); },
  };
  return storage;
}
