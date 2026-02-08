import 'dotenv/config';
import { McpServer } from '@modelcontextprotocol/sdk/server/mcp.js';
import { StdioServerTransport } from '@modelcontextprotocol/sdk/server/stdio.js';
import { z } from 'zod';
import pkg from 'pg';

const { Pool } = pkg;

// DB config: prefer env, fallback to existing server defaults
const dbConfig = {
  user: process.env.PGUSER || 'lab',
  password: process.env.PGPASSWORD || 'IndiaNepal1-',
  host: process.env.PGHOST || '150.241.244.130',
  port: parseInt(process.env.PGPORT || '5432', 10),
  database: process.env.PGDATABASE || 'olab',
  ssl: (process.env.PGSSLMODE || 'require') !== 'disable' ? { rejectUnauthorized: false } : false,
  connectionTimeoutMillis: 30000,
  idleTimeoutMillis: 30000,
};

const pool = new Pool(dbConfig);

const isProbe = process.argv.includes('--probe');

async function query(sql, params = []) {
  const client = await pool.connect();
  try {
    const res = await client.query(sql, params);
    return res.rows;
  } finally {
    client.release();
  }
}

const mcpServer = new McpServer({ name: 'lab-mcp-server', version: '0.1.0' });

mcpServer.registerTool('get_trades', {
  description: 'Fetch recent trades from alltraderecords table',
  inputSchema: { limit: z.number().int().min(1).max(5000).optional() },
}, async ({ limit = 200 }) => {
  const rows = await query(`SELECT * FROM alltraderecords ORDER BY candel_time DESC NULLS LAST LIMIT $1`, [limit]);
  return { content: [{ type: 'json', json: rows }] };
});

mcpServer.registerTool('get_machines', {
  description: 'Fetch machines with active flag',
}, async () => {
  const rows = await query(`SELECT machineid, active FROM machines`);
  return { content: [{ type: 'json', json: rows }] };
});

mcpServer.registerTool('get_signal_logs', {
  description: 'Fetch paginated signalprocessinglogs with optional symbols filter',
  inputSchema: {
    symbols: z.array(z.string()).optional(),
    page: z.number().int().min(1).optional(),
    limit: z.number().int().min(1).max(2000).optional(),
    sortKey: z.string().optional(),
    sortDirection: z.enum(['ASC','DESC']).optional(),
  },
}, async ({ symbols = [], page = 1, limit = 100, sortKey = 'created_at', sortDirection = 'DESC' }) => {
  const allowed = new Set(['candle_time','symbol','interval','signal_type','signal_source','candle_pattern','price','squeeze_status','active_squeeze','machine_id','timestamp','processing_time_ms','created_at','unique_id']);
  const key = allowed.has(sortKey) ? sortKey : 'created_at';
  const dir = sortDirection === 'ASC' ? 'ASC' : 'DESC';
  const offset = (page - 1) * limit;

  const params = [];
  let where = 'TRUE';
  if (symbols?.length) {
    const placeholders = symbols.map((_, i) => `$${i + 1}`).join(',');
    where = `symbol IN (${placeholders})`;
    params.push(...symbols);
  }

  const countSql = `SELECT COUNT(*) AS total FROM signalprocessinglogs WHERE ${where}`;
  const dataSql = `SELECT * FROM signalprocessinglogs WHERE ${where} ORDER BY ${key} ${dir} LIMIT $${params.length + 1} OFFSET $${params.length + 2}`;
  const totalRows = await query(countSql, params);
  const total = parseInt(totalRows?.[0]?.total || '0', 10);
  const rows = await query(dataSql, [...params, limit, offset]);
  return { content: [{ type: 'json', json: { logs: rows, pagination: { page, limit, total, totalPages: Math.max(1, Math.ceil(total / limit)) } } }] };
});

mcpServer.registerTool('get_bot_event_logs', {
  description: 'Fetch paginated bot_event_log rows',
  inputSchema: {
    page: z.number().int().min(1).optional(),
    limit: z.number().int().min(1).max(2000).optional(),
    sortKey: z.string().optional(),
    sortDirection: z.enum(['ASC','DESC']).optional(),
  },
}, async ({ page = 1, limit = 100, sortKey = 'timestamp', sortDirection = 'DESC' }) => {
  const allowed = new Set(['id','uid','source','pl_after_comm','plain_message','timestamp','machine_id']);
  const key = allowed.has(sortKey) ? sortKey : 'timestamp';
  const dir = sortDirection === 'ASC' ? 'ASC' : 'DESC';
  const offset = (page - 1) * limit;
  const countSql = `SELECT COUNT(*) AS total FROM bot_event_log`;
  const dataSql = `SELECT id, uid, source, pl_after_comm, plain_message, json_message, timestamp, machine_id FROM bot_event_log ORDER BY ${key} ${dir} LIMIT $1 OFFSET $2`;
  const totalRows = await query(countSql);
  const total = parseInt(totalRows?.[0]?.total || '0', 10);
  const rows = await query(dataSql, [limit, offset]);
  return { content: [{ type: 'json', json: { logs: rows, pagination: { page, limit, total, totalPages: Math.max(1, Math.ceil(total / limit)) } } }] };
});

// Start stdio transport
if (isProbe) {
  try {
    const rows = await query('SELECT NOW() AS now');
    console.log(JSON.stringify({ ok: true, now: rows?.[0]?.now || null }));
    process.exit(0);
  } catch (e) {
    console.error(JSON.stringify({ ok: false, error: e?.message || String(e) }));
    process.exit(1);
  }
} else {
  const transport = new StdioServerTransport();
  await mcpServer.connect(transport);
}
