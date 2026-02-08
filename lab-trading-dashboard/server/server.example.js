/**
 * Backend template — no credentials. On the cloud this file is deployed as server.js.
 * The Node.js server runs on your cloud only (no Render, no Vercel). DB and other secrets
 * live only in /etc/lab-trading-dashboard.env on the server (never in Git).
 */

// Load env from file so cloud can use DATABASE_URL (systemd may also set EnvironmentFile)
(function loadEnvFile() {
  const fs = require("fs");
  const path = require("path");
  const tryLoad = (filePath) => {
    if (!fs.existsSync(filePath)) return;
    try {
      const content = fs.readFileSync(filePath, "utf8");
      content.split("\n").forEach((line) => {
        const raw = line.trim();
        if (!raw || raw.startsWith("#")) return;
        const eq = raw.indexOf("=");
        if (eq <= 0) return;
        const key = raw.slice(0, eq).trim();
        let val = raw.slice(eq + 1).trim();
        if ((val.startsWith('"') && val.endsWith('"')) || (val.startsWith("'") && val.endsWith("'"))) {
          val = val.slice(1, -1);
        } else {
          const comment = val.indexOf("#");
          if (comment >= 0) val = val.slice(0, comment).trim();
        }
        if (key) process.env[key] = val;
      });
      console.log("[env] Loaded", filePath);
    } catch (e) {
      console.warn("[env] Could not load", filePath, e.message);
    }
  };
  tryLoad(path.join(process.cwd(), ".env"));
  tryLoad(path.join(process.cwd(), "..", ".env"));
  tryLoad("/etc/lab-trading-dashboard.env");
  if (process.env.DATABASE_URL) {
    console.log("[env] DATABASE_URL is set — app will use remote DB when connection succeeds");
  } else {
    console.log("[env] DATABASE_URL not set — app will use local DB (DB_HOST/DB_*)");
  }
})();

const express = require("express");
const cors = require("cors");
const { Pool } = require("pg");
const axios = require('axios');

const app = express();
const fs = require("fs");
const path = require("path");
let currentLogPath = "D:/Projects/blockchainProject/pythonProject/Binance/Loveleet_Anish_Bot/LAB-New-Logic/hedge_logs";
const PORT = process.env.PORT || 10000;
const ENABLE_SELF_PING = String(process.env.ENABLE_SELF_PING || '').toLowerCase() === 'true';
const VERBOSE_LOG = String(process.env.VERBOSE_LOG || '').toLowerCase() === 'true';

// ✅ Allowed Frontend Origins (local + cloud + GitHub Pages / Vercel when frontend is hosted there)
const extraOrigins = (process.env.ALLOWED_ORIGINS || "").split(",").map((o) => o.trim()).filter(Boolean);
const allowedOrigins = [
  "http://localhost:5173",
  "http://localhost:5174",
  "http://localhost:10000",
  "http://150.241.244.130:10000", // Cloud (when frontend is served from same server)
  "https://loveleet.github.io",   // GitHub Pages (frontend hosted by GitHub)
  "https://lab-anish.vercel.app",
  ...extraOrigins,
];

// ✅ Proper CORS Handling
app.use(cors({
  origin: function (origin, callback) {
    try {
      if (!origin) return callback(null, true);
      if (allowedOrigins.includes(origin)) return callback(null, true);
      console.error("❌ CORS blocked origin:", origin);
      return callback(new Error("CORS not allowed for this origin"));
    } catch (e) {
      console.error("❌ CORS origin parse error:", e.message);
      return callback(new Error("CORS origin parse error"));
    }
  },
  credentials: true,
  methods: ["GET", "POST", "PUT", "DELETE", "OPTIONS"],
}));

app.use(express.json());

app.post("/api/set-log-path", (req, res) => {
  const { path } = req.body;
  if (fs.existsSync(path)) {
    currentLogPath = path;
    console.log("✅ Log path updated to:", currentLogPath);
    res.json({ success: true, message: "Log path updated." });
  } else {
    res.status(400).json({ success: false, message: "Invalid path" });
  }
});

app.use("/logs", (req, res, next) => {
  express.static(currentLogPath)(req, res, next);
});

// ✅ Database Configuration — same as server copy.js / Render: 150.241.245.36, postgres, IndiaNepal1-, olab, ssl: false
function buildDbConfig() {
  const dbHost = process.env.DB_HOST || 'localhost';
  const host = (dbHost === '150.241.244.130' ? 'localhost' : dbHost);
  const isRemoteDb = host === '150.241.245.36';
  return {
    host,
    port: parseInt(process.env.DB_PORT || '5432', 10),
    user: process.env.DB_USER || 'postgres',
    password: process.env.DB_PASSWORD || (isRemoteDb ? 'IndiaNepal1-' : ''),
    database: process.env.DB_NAME || 'olab',
    connectionTimeoutMillis: isRemoteDb ? 30000 : 10000,
    idleTimeoutMillis: 30000,
    max: isRemoteDb ? 20 : 10,
  };
}
const dbConfig = buildDbConfig();

// ✅ Connection configs: for 150.241.245.36 use exact same single config as server copy.js (Render)
function getConnectionConfigs() {
  const databaseUrl = process.env.DATABASE_URL;
  if (databaseUrl) {
    return [
      { connectionString: databaseUrl, ssl: { rejectUnauthorized: false }, connectionTimeoutMillis: 15000 },
      { connectionString: databaseUrl, ssl: true, connectionTimeoutMillis: 15000 },
      { connectionString: databaseUrl, ssl: false, connectionTimeoutMillis: 15000 },
    ];
  }
  const isLocal = !dbConfig.host || dbConfig.host === 'localhost' || dbConfig.host === '127.0.0.1';
  if (isLocal) {
    return [
      { ...dbConfig, ssl: false },
      { ...dbConfig, ssl: { rejectUnauthorized: false } },
      { ...dbConfig, ssl: { rejectUnauthorized: false, sslmode: 'require' } },
    ];
  }
  // 150.241.245.36 — exact same as server copy.js: single config, ssl: false, 30s timeout (Render uses this and gets data)
  if (dbConfig.host === '150.241.245.36') {
    return [{ ...dbConfig, ssl: false }];
  }
  return [
    { ...dbConfig, ssl: { rejectUnauthorized: false } },
    { ...dbConfig, ssl: { rejectUnauthorized: false, sslmode: 'require' } },
    { ...dbConfig, ssl: false },
  ];
}

// Stop retrying after 60s so app stays responsive (APIs return "DB not connected" instead of hanging)
const CONNECT_TIMEOUT_MS = 60000;

async function connectWithRetry(startTime = Date.now()) {
  const configs = getConnectionConfigs();
  const isConnectionString = !!process.env.DATABASE_URL;

  for (let i = 0; i < configs.length; i++) {
    const config = configs[i];
    if (Date.now() - startTime > CONNECT_TIMEOUT_MS) {
      console.error("[DB] Connection timeout. Ensure this server can reach the DB (firewall, pg_hba). Check: journalctl -u lab-trading-dashboard -n 80");
      return null;
    }
    try {
      if (isConnectionString) {
        console.log(`🔧 Attempt ${i + 1}: PostgreSQL via DATABASE_URL (ssl: ${!!config.ssl})`);
      } else {
        console.log(`🔧 Attempt ${i + 1}: PostgreSQL to ${config.host}:${config.port}/${config.database} (same config as Render)`);
      }
      const pool = new Pool(config);
      await pool.query('SELECT NOW()');
      console.log(`✅ Connected to PostgreSQL successfully`);
      const countResult = await pool.query('SELECT count(*) as c FROM alltraderecords').catch(() => ({ rows: [{ c: 0 }] }));
      const tradeCount = parseInt(countResult.rows[0]?.c || 0, 10);
      console.log(`[DB] alltraderecords has ${tradeCount} rows — dashboard will show ${tradeCount} trades`);
      return pool;
    } catch (err) {
      console.error(`❌ PostgreSQL connection failed (attempt ${i + 1}):`, err.code || "", err.message);
      if (i === configs.length - 1) {
        console.error("   Retrying in 5 seconds...");
        await new Promise((resolve) => setTimeout(resolve, 5000));
        return connectWithRetry(startTime);
      }
    }
  }
  return null;
}

let poolPromise = connectWithRetry();

// ✅ When DB is unreachable, proxy data from Render (same DB Render uses). Set FALLBACK_API_URL in /etc/lab-trading-dashboard.env
const FALLBACK_API_URL = (process.env.FALLBACK_API_URL || "").trim();
async function fetchFromFallback(path, queryString = "") {
  if (!FALLBACK_API_URL) return null;
  const url = FALLBACK_API_URL.replace(/\/$/, "") + path + (queryString ? "?" + queryString : "");
  try {
    const r = await axios.get(url, { timeout: 20000, validateStatus: () => true });
    if (r.status !== 200) return null;
    return r.data;
  } catch (e) {
    console.warn("[Fallback]", path, e.code || e.message);
    return null;
  }
}

// ✅ Health Check (for monitoring)
app.get("/api/health", (req, res) => {
  res.send("✅ Backend is working!");
});

// Return current Cloudflare tunnel URL (for GitHub Pages). Written by update-github-secret-from-tunnel.sh on cloud.
app.get("/api/tunnel-url", (req, res) => {
  try {
    const f = path.join("/var/run", "lab-tunnel-url");
    if (fs.existsSync(f)) {
      const url = fs.readFileSync(f, "utf8").trim();
      return res.json({ tunnelUrl: url });
    }
  } catch (e) { /* ignore */ }
  res.json({ tunnelUrl: null });
});

// ✅ Debug: table row counts + DB source (no secrets) — explains why cloud shows fewer trades
app.get("/api/debug", async (req, res) => {
  try {
    const pool = await poolPromise;
    if (!pool) {
      if (FALLBACK_API_URL) {
        const debug = await fetchFromFallback("/api/debug");
        if (debug && debug.ok) return res.json({ ...debug, dbSource: (debug.dbSource || "remote") + " (via fallback)" });
        const trades = await fetchFromFallback("/api/trades");
        const machines = await fetchFromFallback("/api/machines");
        const tn = (trades && trades.trades && trades.trades.length) || (trades && trades._meta && trades._meta.count) || 0;
        const mn = (machines && machines.machines && machines.machines.length) || 0;
        if (tn > 0 || mn > 0) {
          return res.json({ ok: true, counts: { alltraderecords: tn, machines: mn, pairstatus: "n/a" }, dbSource: "fallback:" + FALLBACK_API_URL });
        }
      }
      return res.json({
        ok: false,
        error: "Database not connected",
        dbSource: process.env.DATABASE_URL ? "DATABASE_URL (connection failed or timeout)" : "DB_* / local",
        hint: "Set FALLBACK_API_URL=https://lab-anish.onrender.com in /etc/lab-trading-dashboard.env and restart to use Render data when DB is unreachable."
      });
    }
    const tables = ["alltraderecords", "machines", "pairstatus"];
    const counts = {};
    for (const table of tables) {
      try {
        const r = await pool.query(`SELECT count(*) as c FROM ${table}`);
        counts[table] = parseInt(r.rows[0]?.c ?? 0, 10);
      } catch (e) {
        counts[table] = e.code === "42P01" ? "missing" : e.message;
      }
    }
    const tradeCount = typeof counts.alltraderecords === "number" ? counts.alltraderecords : 0;
    const tradesEmpty = tradeCount === 0 || counts.alltraderecords === "missing";
    const dbSource = process.env.DATABASE_URL ? "DATABASE_URL (remote)" : "DB_* / local";
    let hint = null;
    if (tradesEmpty) {
      hint = "alltraderecords is empty or missing — set DATABASE_URL (or DB_HOST/DB_USER/DB_PASSWORD/DB_NAME) in /etc/lab-trading-dashboard.env, then restart.";
    } else if (tradeCount < 50) {
      hint = "This app is using the local DB with very few rows. To see real data: set DATABASE_URL (or DB_*) in /etc/lab-trading-dashboard.env to your Postgres URL and restart.";
    }
    res.json({ ok: true, counts, dbSource, hint });
  } catch (e) {
    res.json({ ok: false, error: e.message });
  }
});

// ✅ API: Fetch All Trades
// Helper: true if error is "table does not exist"
function isMissingTable(err) {
  return err && (err.code === "42P01" || (err.message && err.message.includes("does not exist")));
}

// ✅ API: Fetch SuperTrend Signals (return empty if table missing or DB not connected — avoid 500)
app.get("/api/supertrend", async (req, res) => {
  try {
    const pool = await poolPromise;
    if (!pool) {
      const fallback = await fetchFromFallback("/api/supertrend");
      if (fallback && (fallback.supertrend || Array.isArray(fallback.supertrend))) return res.json(fallback);
      return res.json({ supertrend: [] });
    }
    const result = await pool.query(
      'SELECT source, trend, timestamp FROM supertrend ORDER BY timestamp DESC LIMIT 10;'
    );
    res.json({ supertrend: result.rows || [] });
  } catch (error) {
    if (isMissingTable(error)) {
      return res.json({ supertrend: [] });
    }
    console.error("❌ [SuperTrend] Error:", error.message);
    res.status(500).json({ error: error.message || "Failed to fetch SuperTrend data" });
  }
});

// No LIMIT — return all rows from the configured DB.
app.get("/api/trades", async (req, res) => {
  try {
    const pool = await poolPromise;
    if (!pool) {
      const fallback = await fetchFromFallback("/api/trades");
      if (fallback && (fallback.trades || Array.isArray(fallback.trades))) {
        console.log("[Trades] Fallback:", (fallback.trades || []).length, "rows");
        return res.json(fallback);
      }
      console.log("[Trades] No pool — returning empty");
      return res.json({ trades: [], _meta: { count: 0, table: "alltraderecords" } });
    }
    const result = await pool.query("SELECT * FROM alltraderecords;");
    const count = result.rows.length;
    if (count === 0) console.log("[Trades] Table is empty — add data or set DATABASE_URL in /etc/lab-trading-dashboard.env to point to your DB.");
    else console.log("[Trades] Fetched", count, "rows from alltraderecords");
    res.json({
      trades: result.rows,
      _meta: {
        count,
        table: "alltraderecords",
        ...(count === 0 && { demoData: true, hint: "No rows in alltraderecords. Set DATABASE_URL (or DB_HOST/DB_USER/DB_PASSWORD/DB_NAME) in /etc/lab-trading-dashboard.env on this server to point to your Postgres and restart." })
      }
    });
  } catch (error) {
    if (isMissingTable(error)) {
      console.log("[Trades] Table alltraderecords missing — returning empty");
      return res.json({ trades: [], _meta: { count: 0, table: "alltraderecords", error: "table missing" } });
    }
    console.error("❌ [Trades] Error:", error);
    res.status(500).json({ error: error.message || "Failed to fetch trades" });
  }
});

// ✅ API: Fetch Machines
app.get("/api/machines", async (req, res) => {
  try {
    const pool = await poolPromise;
    if (!pool) {
      const fallback = await fetchFromFallback("/api/machines");
      if (fallback && (fallback.machines || Array.isArray(fallback.machines))) {
        return res.json(fallback);
      }
      return res.json({ machines: [] });
    }
    const result = await pool.query("SELECT machineid, active FROM machines;");
    res.json({ machines: result.rows });
  } catch (error) {
    if (isMissingTable(error)) return res.json({ machines: [] });
    console.error("❌ Query Error (/api/machines):", error.message);
    res.status(500).json({ error: error.message || "Failed to fetch machines" });
  }
});

// ✅ API: Fetch EMA Trend Data from pairstatus
app.get("/api/pairstatus", async (req, res) => {
  try {
    const pool = await poolPromise;
    if (!pool) {
      const fallback = await fetchFromFallback("/api/pairstatus");
      if (fallback && typeof fallback === "object") return res.json(fallback);
      return res.json({});
    }
    const result = await pool.query(`
      SELECT overall_ema_trend_1m, overall_ema_trend_percentage_1m,
             overall_ema_trend_5m, overall_ema_trend_percentage_5m,
             overall_ema_trend_15m, overall_ema_trend_percentage_15m
      FROM pairstatus
      LIMIT 1;
    `);
    res.json(result.rows[0] || {});
  } catch (error) {
    if (isMissingTable(error)) return res.json({});
    console.error("❌ Query Error (/api/pairstatus):", error.message);
    res.status(500).json({ error: error.message || "Failed to fetch pairstatus" });
  }
});

// ✅ API: Fetch Active Loss/Condition flags (e.g., BUY/SELL booleans)
// Expected table: active_loss with columns like buy, sell (bool/int/text) where id=1
const defaultActiveLoss = { id: 1, buy: false, sell: false, buy_condition: false, sell_condition: false, buyflag: false, sellflag: false };
app.get("/api/active-loss", async (req, res) => {
  try {
    const pool = await poolPromise;
    if (!pool) {
      const fallback = await fetchFromFallback("/api/active-loss");
      if (fallback && typeof fallback === "object") return res.json(fallback);
      return res.json(defaultActiveLoss);
    }
    const result = await pool.query(`
      SELECT *
      FROM active_loss
      WHERE id = 1
      LIMIT 1;
    `);
    const row = result.rows?.[0] || defaultActiveLoss;
    res.json(row);
  } catch (error) {
    if (error.code === "42P01" || (error.message && error.message.includes("does not exist"))) {
      return res.json(defaultActiveLoss);
    }
    console.error("❌ Query Error (/api/active-loss):", error.message);
    res.status(500).json({ error: error.message || "Failed to fetch active loss flags" });
  }
});

// ✅ Binance Proxy Endpoint (local/cloud server)
const LOCAL_PROXY = `http://localhost:${process.env.PORT || 10000}/api/klines`;

app.get('/api/klines', async (req, res) => {
  try {
    const { symbol, interval, limit } = req.query;
    const url = `https://api.binance.com/api/v3/klines?symbol=${symbol}&interval=${interval}&limit=${limit || 200}`;
    const { data } = await axios.get(url);
    res.json(data);
  } catch (err) {
    res.status(500).json({ error: err.toString() });
  }
});

// ✅ Proxy to Python CalculateSignals API (run python/api_signals.py; set PYTHON_SIGNALS_URL=http://localhost:5001)
app.post("/api/calculate-signals", async (req, res) => {
  const pythonUrl = process.env.PYTHON_SIGNALS_URL || "http://localhost:5001";
  try {
    console.log("[calculate-signals] Request body:", JSON.stringify(req.body));
    const timeoutMs = Number(process.env.CALCULATE_SIGNALS_TIMEOUT_MS) || 300000; // 5 min default (4 intervals can be slow)
    const { data, status } = await axios.post(`${pythonUrl}/api/calculate-signals`, req.body, {
      headers: { "Content-Type": "application/json" },
      timeout: timeoutMs,
      validateStatus: () => true,
    });
    console.log("[calculate-signals] Python API response:", JSON.stringify(data, null, 2));
    res.status(status || 200).json(data);
  } catch (err) {
    console.error("[calculate-signals] Proxy error:", err.message);
    res.status(502).json({ ok: false, message: err.message || "Python signals service unavailable" });
  }
});

// ✅ API: Fetch Signal Processing Logs with Pagination and Filtering
app.get("/api/SignalProcessingLogs", async (req, res) => {
  try {
    console.log("🔍 [SignalProcessingLogs] Request received:", req.query);
    const pool = await poolPromise;
    if (!pool) throw new Error("Database not connected");
    
    // Parse query parameters
    const page = parseInt(req.query.page) || 1;
    const limit = req.query.limit === 'all' ? 'all' : (parseInt(req.query.limit) || 50);
    const offset = (page - 1) * (limit === 'all' ? 0 : limit);
    
    // Build WHERE clause for filters
    let whereConditions = [];
    let params = [];
    let paramIndex = 1;
    
    // Symbol filter
    if (req.query.symbol) {
      whereConditions.push(`symbol LIKE $${paramIndex}`);
      params.push(`%${req.query.symbol}%`);
      paramIndex++;
    }
    // Signal type filter
    if (req.query.signalType) {
      whereConditions.push(`signal_type LIKE $${paramIndex}`);
      params.push(`%${req.query.signalType}%`);
      paramIndex++;
    }
    // Machine filter
    if (req.query.machineId) {
      whereConditions.push(`machine_id = $${paramIndex}`);
      params.push(req.query.machineId);
      paramIndex++;
    }
    // Date range filter
    if (req.query.fromDate) {
      whereConditions.push(`candle_time >= $${paramIndex}`);
      params.push(req.query.fromDate);
      paramIndex++;
    }
    if (req.query.toDate) {
      whereConditions.push(`candle_time <= $${paramIndex}`);
      params.push(req.query.toDate);
      paramIndex++;
    }
    // RSI range filter (from json_data, so not filterable in SQL directly)
    const whereClause = whereConditions.length > 0 ? `WHERE ${whereConditions.join(' AND ')}` : '';

    // --- Sorting logic ---
    const allowedSortKeys = [
      'candle_time', 'symbol', 'interval', 'signal_type', 'signal_source', 'candle_pattern', 'price',
      'squeeze_status', 'active_squeeze', 'processing_time_ms', 'machine_id', 'timestamp', 'created_at', 'unique_id'
    ];
    let sortKey = req.query.sortKey;
    let sortDirection = req.query.sortDirection && req.query.sortDirection.toUpperCase() === 'ASC' ? 'ASC' : 'DESC';
    if (!allowedSortKeys.includes(sortKey)) {
      sortKey = 'candle_time';
    }
    const orderByClause = `ORDER BY ${sortKey} ${sortDirection}`;
    
    // Build the query
    const countQuery = `SELECT COUNT(*) as total FROM signalprocessinglogs ${whereClause}`;
    const dataQuery = `
      SELECT 
        id,
        candle_time,
        symbol,
        interval,
        signal_type,
        signal_source,
        candle_pattern,
        price,
        squeeze_status,
        active_squeeze,
        processing_time_ms,
        machine_id,
        timestamp,
        json_data,
        created_at,
        unique_id
      FROM signalprocessinglogs 
      ${whereClause}
      ${orderByClause}
      ${limit === 'all' ? '' : `LIMIT ${limit} OFFSET ${offset}`}
    `;
    
    // Execute queries
    console.log("🔍 [SignalProcessingLogs] Count query:", countQuery);
    console.log("🔍 [SignalProcessingLogs] Data query:", dataQuery);
    console.log("🔍 [SignalProcessingLogs] Parameters:", params);
    
    const [countResult, dataResult] = await Promise.all([
      pool.query(countQuery, params),
      pool.query(dataQuery, params)
    ]);
    
    const total = parseInt(countResult.rows[0].total);
    const logs = dataResult.rows;
    
    console.log("🔍 [SignalProcessingLogs] Total records:", total);
    console.log("🔍 [SignalProcessingLogs] Fetched logs:", logs.length);
    
    // Parse JSON data for each log and extract extra fields
    const processedLogs = logs.map(log => {
      let extra = {};
      if (log.json_data) {
        try {
          const json = JSON.parse(log.json_data);
          extra = {
            rsi: json.rsi,
            macd: json.macd,
            trend: json.trend,
            action: json.action,
            status: json.status,
            // add more as needed
          };
        } catch (e) {}
      }
      return { ...log, ...extra };
    });
    
    console.log("🔍 [SignalProcessingLogs] Sending response with", processedLogs.length, "logs");
    res.json({
      logs: processedLogs,
      pagination: {
        page,
        limit,
        total,
        totalPages: limit === 'all' ? 1 : Math.ceil(total / limit),
        hasNext: limit === 'all' ? false : page < Math.ceil(total / limit),
        hasPrev: limit === 'all' ? false : page > 1
      }
    });
    
  } catch (error) {
    console.error("❌ [SignalProcessingLogs] Error:", error);
    console.error("❌ [SignalProcessingLogs] Error stack:", error.stack);
    res.status(500).json({ error: error.message || "Failed to fetch signal processing logs" });
  }
});

// ✅ API: Fetch Bot Event Logs with Pagination and Filtering
app.get("/api/bot-event-logs", async (req, res) => {
  try {
    const pool = await poolPromise;
    if (!pool) throw new Error("Database not connected");
    
    // Parse query parameters
    const page = parseInt(req.query.page) || 1;
    const limit = req.query.limit === 'all' ? 'all' : (parseInt(req.query.limit) || 50);
    const offset = (page - 1) * (limit === 'all' ? 0 : limit);
    
    // Build WHERE clause for filters
    let whereConditions = [];
    let params = [];
    let paramIndex = 1;
    
    // UID filter (exact match)
    if (req.query.uid) {
      whereConditions.push(`uid = $${paramIndex}`);
      params.push(req.query.uid);
      paramIndex++;
    }
    
    // Source filter
    if (req.query.source) {
      whereConditions.push(`source LIKE $${paramIndex}`);
      params.push(`%${req.query.source}%`);
      paramIndex++;
    }
    
    // Machine filter
    if (req.query.machineId) {
      whereConditions.push(`machine_id = $${paramIndex}`);
      params.push(req.query.machineId);
      paramIndex++;
    }
    
    // Date range filter
    if (req.query.fromDate) {
      whereConditions.push(`timestamp >= $${paramIndex}`);
      params.push(req.query.fromDate);
      paramIndex++;
    }
    if (req.query.toDate) {
      whereConditions.push(`timestamp <= $${paramIndex}`);
      params.push(req.query.toDate);
      paramIndex++;
    }
    
    const whereClause = whereConditions.length > 0 ? `WHERE ${whereConditions.join(' AND ')}` : '';
    
    // --- Sorting logic ---
    const allowedSortKeys = [
      'id', 'uid', 'source', 'pl_after_comm', 'plain_message', 'timestamp', 'machine_id'
    ];
    let sortKey = req.query.sortKey;
    let sortDirection = req.query.sortDirection && req.query.sortDirection.toUpperCase() === 'ASC' ? 'ASC' : 'DESC';
    if (!allowedSortKeys.includes(sortKey)) {
      sortKey = 'timestamp';
    }
    const orderByClause = `ORDER BY ${sortKey} ${sortDirection}`;
    
    // Build the query
    const countQuery = `SELECT COUNT(*) as total FROM bot_event_log ${whereClause}`;
    const dataQuery = `
      SELECT 
        id,
        uid,
        source,
        pl_after_comm,
        plain_message,
        json_message,
        timestamp,
        machine_id
      FROM bot_event_log 
      ${whereClause}
      ${orderByClause}
      ${limit === 'all' ? '' : `LIMIT ${limit} OFFSET ${offset}`}
    `;
    
    // Execute queries
    const [countResult, dataResult] = await Promise.all([
      pool.query(countQuery, params),
      pool.query(dataQuery, params)
    ]);
    
    const total = parseInt(countResult.rows[0].total);
    const logs = dataResult.rows;
    
    // Parse JSON message for each log if needed
    const processedLogs = logs.map(log => {
      let parsedJson = null;
      if (log.json_message) {
        try {
          parsedJson = JSON.parse(log.json_message);
        } catch (e) {
          // Keep as string if parsing fails
        }
      }
      return { 
        ...log, 
        parsed_json_message: parsedJson 
      };
    });
    
    res.json({
      logs: processedLogs,
      pagination: {
        page,
        limit,
        total,
        totalPages: limit === 'all' ? 1 : Math.ceil(total / (limit === 'all' ? total : limit)),
        hasNext: limit === 'all' ? false : page < Math.ceil(total / (limit === 'all' ? total : limit)),
        hasPrev: limit === 'all' ? false : page > 1
      }
    });
    
  } catch (error) {
    console.error("\u274c Query Error (/api/bot-event-logs):", error.message);
    res.status(500).json({ error: error.message || "Failed to fetch bot event logs" });
  }
});

// ✅ API: Get Log Summary Statistics
app.get("/api/SignalProcessingLogs/summary", async (req, res) => {
  try {
    const pool = await poolPromise;
    if (!pool) throw new Error("Database not connected");
    
    // Build WHERE clause for filters (same as above)
    let whereConditions = [];
    let params = [];
    let paramIndex = 1;
    if (req.query.symbol) {
      whereConditions.push(`symbol LIKE $${paramIndex}`);
      params.push(`%${req.query.symbol}%`);
      paramIndex++;
    }
    if (req.query.signalType) {
      whereConditions.push(`signal_type LIKE $${paramIndex}`);
      params.push(`%${req.query.signalType}%`);
      paramIndex++;
    }
    if (req.query.machineId) {
      whereConditions.push(`machine_id = $${paramIndex}`);
      params.push(req.query.machineId);
      paramIndex++;
    }
    if (req.query.fromDate) {
      whereConditions.push(`candle_time >= $${paramIndex}`);
      params.push(req.query.fromDate);
      paramIndex++;
    }
    if (req.query.toDate) {
      whereConditions.push(`candle_time <= $${paramIndex}`);
      params.push(req.query.toDate);
      paramIndex++;
    }
    const whereClause = whereConditions.length > 0 ? `WHERE ${whereConditions.join(' AND ')}` : '';
    
    // Get all logs for summary (for small/medium datasets; for large, optimize with SQL aggregation)
    const summaryQuery = `
      SELECT 
        signal_type,
        json_data
      FROM signalprocessinglogs 
      ${whereClause}
    `;
    const result = await pool.query(summaryQuery, params);
    const logs = result.rows;
    let totalLogs = logs.length;
    let buyCount = 0;
    let sellCount = 0;
    let rsiSum = 0;
    let rsiCount = 0;
    let earliestLog = null;
    let latestLog = null;
    let uniqueSymbols = new Set();
    let uniqueMachines = new Set();
    logs.forEach(log => {
      if (log.signal_type === 'BUY') buyCount++;
      if (log.signal_type === 'SELL') sellCount++;
      if (log.json_data) {
        try {
          const json = JSON.parse(log.json_data);
          if (json.rsi !== undefined && json.rsi !== null) {
            rsiSum += Number(json.rsi);
            rsiCount++;
          }
        } catch (e) {}
      }
    });
    const avgRSI = rsiCount > 0 ? (rsiSum / rsiCount).toFixed(2) : null;
    res.json({
      summary: {
        totalLogs,
        buyCount,
        sellCount,
        avgRSI,
        uniqueSymbols: uniqueSymbols.size,
        uniqueMachines: uniqueMachines.size,
        earliestLog,
        latestLog
      }
    });
  } catch (error) {
    console.error("❌ Query Error (/api/SignalProcessingLogs/summary):", error.message);
    res.status(500).json({ error: error.message || "Failed to fetch summary" });
  }
});

// ✅ API: Get Bot Event Log Summary Statistics
app.get("/api/bot-event-logs/summary", async (req, res) => {
  try {
    const pool = await poolPromise;
    if (!pool) throw new Error("Database not connected");
    
    // Build WHERE clause for filters (same as above)
    let whereConditions = [];
    let params = [];
    let paramIndex = 1;
    
    if (req.query.uid) {
      whereConditions.push(`uid = $${paramIndex}`);
      params.push(req.query.uid);
      paramIndex++;
    }
    if (req.query.source) {
      whereConditions.push(`source LIKE $${paramIndex}`);
      params.push(`%${req.query.source}%`);
      paramIndex++;
    }
    if (req.query.machineId) {
      whereConditions.push(`machine_id = $${paramIndex}`);
      params.push(req.query.machineId);
      paramIndex++;
    }
    if (req.query.fromDate) {
      whereConditions.push(`timestamp >= $${paramIndex}`);
      params.push(req.query.fromDate);
      paramIndex++;
    }
    if (req.query.toDate) {
      whereConditions.push(`timestamp <= $${paramIndex}`);
      params.push(req.query.toDate);
      paramIndex++;
    }
    
    const whereClause = whereConditions.length > 0 ? `WHERE ${whereConditions.join(' AND ')}` : '';
    
    // Get summary statistics
    const summaryQuery = `
      SELECT 
        COUNT(*) as totalLogs,
        COUNT(DISTINCT machine_id) as uniqueMachines,
        COUNT(DISTINCT source) as uniqueSources,
        SUM(CASE WHEN pl_after_comm > 0 THEN 1 ELSE 0 END) as positivePLCount,
        SUM(CASE WHEN pl_after_comm < 0 THEN 1 ELSE 0 END) as negativePLCount,
        SUM(CASE WHEN pl_after_comm = 0 THEN 1 ELSE 0 END) as zeroPLCount,
        AVG(pl_after_comm) as avgPL,
        MIN(timestamp) as earliestLog,
        MAX(timestamp) as latestLog
      FROM bot_event_log 
      ${whereClause}
    `;
    
    const result = await pool.query(summaryQuery, params);
    const summary = result.rows[0];
    
    res.json({
      summary: {
        totalLogs: summary.totalLogs,
        uniqueMachines: summary.uniqueMachines,
        uniqueSources: summary.uniqueSources,
        positivePLCount: summary.positivePLCount,
        negativePLCount: summary.negativePLCount,
        zeroPLCount: summary.zeroPLCount,
        avgPL: summary.avgPL ? parseFloat(summary.avgPL).toFixed(2) : 0,
        earliestLog: summary.earliestLog,
        latestLog: summary.latestLog
      }
    });
  } catch (error) {
    console.error("❌ Query Error (/api/bot-event-logs/summary):", error.message);
    res.status(500).json({ error: error.message || "Failed to fetch bot event log summary" });
  }
});

// ✅ API: Fetch Trades with Pair Filter
app.get("/api/trades/filtered", async (req, res) => {
  try {
    const pool = await poolPromise;
    if (!pool) {
      const qs = Object.entries(req.query).map(([k, v]) => k + "=" + encodeURIComponent(v)).join("&");
      const fallback = await fetchFromFallback("/api/trades/filtered", qs);
      if (fallback && (fallback.trades || Array.isArray(fallback.trades))) return res.json(fallback);
      return res.json({ trades: [] });
    }
    const { pair, limit = 1000 } = req.query;
    let query = "SELECT * FROM alltraderecords";
    let params = [];
    let paramIndex = 1;
    
    if (pair) {
      query += ` WHERE pair = $${paramIndex}`;
      params.push(pair);
      paramIndex++;
    }
    
    query += " ORDER BY created_at DESC";
    
    if (limit && limit !== 'all') {
      query += ` LIMIT ${parseInt(limit)}`;
    }
    
    const result = await pool.query(query, params);
    console.log(`[Server] Fetched ${result.rows.length} trades for pair: ${pair || 'all'}`);
    
    res.json({ trades: result.rows });
  } catch (error) {
    console.error("❌ Query Error (/api/trades/filtered):", error.message);
    res.status(500).json({ error: error.message || "Failed to fetch filtered trades" });
  }
});

// ✅ API: Fetch SignalProcessingLogs with Unique_id only (paginated)
app.get("/api/SignalProcessingLogsWithUniqueId", async (req, res) => {
  try {
    const pool = await poolPromise;
    if (!pool) throw new Error("Database not connected");

    let { symbols, page = 1, limit = 100, sortKey, sortDirection = 'ASC' } = req.query;
    page = parseInt(page);
    limit = parseInt(limit);
    if (!symbols) return res.status(400).json({ error: "Missing symbols param" });
    const symbolList = symbols.split(",").map(s => s.trim()).filter(Boolean);
    if (!symbolList.length) return res.status(400).json({ error: "No symbols provided" });

    // Define allowed sort keys to prevent SQL injection
    const allowedSortKeys = [
      'candle_time', 'symbol', 'interval', 'signal_type', 'signal_source', 
      'candle_pattern', 'price', 'squeeze_status', 'active_squeeze', 
      'machine_id', 'timestamp', 'processing_time_ms', 'created_at', 'unique_id'
    ];

    // Build WHERE clause for symbols and Unique_id (PostgreSQL trims whitespace)
    const symbolPlaceholders = symbolList.map((_, i) => `$${i + 1}`).join(",");
    const whereClause = `symbol IN (${symbolPlaceholders}) AND unique_id IS NOT NULL AND TRIM(unique_id) <> ''`;

    // Build ORDER BY clause
    let orderByClause = 'ORDER BY created_at DESC';
    if (sortKey && allowedSortKeys.includes(sortKey)) {
      orderByClause = `ORDER BY ${sortKey} ${sortDirection === 'ASC' ? 'ASC' : 'DESC'}`;
    }

    // Get total count for pagination (primary query)
    const countQuery = `SELECT COUNT(*) as total FROM signalprocessinglogs WHERE ${whereClause}`;
    const countResult = await pool.query(countQuery, symbolList);
    let total = parseInt(countResult.rows[0]?.total) || 0;
    let totalPages = Math.ceil(total / limit);
    const offset = (page - 1) * limit;

    // Fetch paginated logs (primary query)
    const logsQuery = `SELECT * FROM signalprocessinglogs WHERE ${whereClause} ${orderByClause} LIMIT $${symbolList.length + 1} OFFSET $${symbolList.length + 2}`;
    const logsParams = [...symbolList, limit, offset];
    const logsResult = await pool.query(logsQuery, logsParams);

    let filteredLogs = logsResult.rows.filter(
      log => typeof log.unique_id === 'string' && log.unique_id.replace(/\s|\u00A0/g, '').length > 0
    );

    // If no results, run fallback query (BUY/SELL signal_type)
    let usedFallback = false;
    if (filteredLogs.length === 0) {
      usedFallback = true;
      // Fallback count
      const fallbackCountQuery = `SELECT COUNT(*) as total FROM signalprocessinglogs WHERE symbol IN (${symbolPlaceholders}) AND (signal_type = 'BUY' OR signal_type = 'SELL')`;
      const fallbackCountResult = await pool.query(fallbackCountQuery, symbolList);
      total = parseInt(fallbackCountResult.rows[0]?.total) || 0;
      totalPages = Math.ceil(total / limit);
      // Fallback logs
      const fallbackQuery = `SELECT * FROM signalprocessinglogs WHERE symbol IN (${symbolPlaceholders}) AND (signal_type = 'BUY' OR signal_type = 'SELL') ${orderByClause} LIMIT $${symbolList.length + 1} OFFSET $${symbolList.length + 2}`;
      const fallbackParams = [...symbolList, limit, offset];
      const fallbackResult = await pool.query(fallbackQuery, fallbackParams);
      filteredLogs = fallbackResult.rows;
    }

    res.json({
      logs: filteredLogs,
      pagination: {
        total,
        totalPages,
        page,
        limit,
        usedFallback
      }
    });
  } catch (error) {
    console.error("❌ Query Error (/api/SignalProcessingLogsWithUniqueId):", error);
    res.status(500).json({ error: error.message || "Failed to fetch logs with Unique_id" });
  }
});

// ✅ API: Fetch SignalProcessingLogs by a list of UIDs
app.get("/api/SignalProcessingLogsByUIDs", async (req, res) => {
  try {
    const pool = await poolPromise;
    if (!pool) throw new Error("Database not connected");
    let { uids } = req.query;
    if (!uids) return res.status(400).json({ error: "Missing uids param" });
    const uidList = uids.split(",").map(u => u.trim()).filter(Boolean);
    if (!uidList.length) return res.status(400).json({ error: "No UIDs provided" });

    const uidPlaceholders = uidList.map((_, i) => `$${i + 1}`).join(",");
    const query = `SELECT * FROM signalprocessinglogs WHERE unique_id IN (${uidPlaceholders})`;
    const result = await pool.query(query, uidList);

    res.json({ logs: result.rows });
  } catch (error) {
    console.error("❌ Query Error (/api/SignalProcessingLogsByUIDs):", error);
    res.status(500).json({ error: error.message || "Failed to fetch logs by UIDs" });
  }
});

// ✅ Serve frontend (dashboard) from dist when present
const distPath = path.join(__dirname, "..", "dist");
if (fs.existsSync(distPath)) {
  app.use(express.static(distPath));
  app.get("*", (req, res, next) => {
    if (req.path.startsWith("/api")) return next();
    res.sendFile(path.join(distPath, "index.html"), (err) => err && next());
  });
}

// ✅ Start Express Server
app.listen(PORT, () => {
  console.log(`🚀 Server running at http://localhost:${PORT}`);
});
const http = require("http");

// Self-ping this server (cloud local) to keep warm — gated by env
if (ENABLE_SELF_PING) {
  const pingUrl = `http://127.0.0.1:${PORT}/api/health`;
  setInterval(() => {
    http.get(pingUrl, (res) => {
      if (VERBOSE_LOG) console.log(`📡 Self-ping status: ${res.statusCode}`);
    }).on("error", (err) => {
      console.error("❌ Self-ping failed:", err.message);
    });
  }, 14 * 60 * 1000); // 14 minutes
}
