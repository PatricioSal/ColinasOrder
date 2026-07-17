/* ─── MSSQL Connection Pool ─────────────────────────────────────────────── 
 * Uses same config pattern as the Colinas Jerky Batch Tracker (proven to work).
 * ──────────────────────────────────────────────────────────────────────── */
import sql from 'mssql';

const config: sql.config = {
  server: process.env.DB_SERVER || '207.200.18.74',
  port: parseInt(process.env.DB_PORT || '9997', 10),
  user: process.env.DB_USER || 'UsrCFoods',
  password: process.env.DB_PASSWORD || '',
  database: process.env.DB_NAME || 'ColinasProducts',
  options: {
    encrypt: process.env.DB_ENCRYPT === 'true',
    trustServerCertificate: process.env.DB_TRUST_SERVER_CERT === 'true',
  },
  pool: {
    max: 10,
    min: 0,
    idleTimeoutMillis: 30000,
  },
  requestTimeout: 30000,
  connectionTimeout: 15000,
};

let pool: sql.ConnectionPool | null = null;

export async function getPool(): Promise<sql.ConnectionPool> {
  if (pool && pool.connected) return pool;

  let attempts = 3;
  let delay = 1000;

  while (attempts > 0) {
    try {
      pool = await sql.connect(config);
      console.log('[DB] Connected to ColinasProducts');

      pool.on('error', (err) => {
        console.error('[DB] Pool error — will reconnect on next query:', err.message);
        pool = null;
      });

      return pool;
    } catch (err) {
      attempts--;
      console.error(`[DB] Connection attempt failed. Attempts remaining: ${attempts}`, err instanceof Error ? err.message : err);
      if (attempts === 0) throw err;
      await new Promise(resolve => setTimeout(resolve, delay));
      delay *= 2;
    }
  }

  throw new Error('Failed to connect to database');
}

export async function testConnection(): Promise<boolean> {
  try {
    const p = await getPool();
    await p.request().query('SELECT 1 AS test');
    return true;
  } catch {
    return false;
  }
}

export { sql };
