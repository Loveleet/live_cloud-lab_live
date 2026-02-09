const express = require("express");
const cors = require("cors");
const { Pool } = require("pg");

const app = express();
const PORT = 3001; // Different port to avoid conflicts

// ✅ Local Development CORS (Allow all origins for testing)
app.use(cors({
  origin: true, // Allow all origins for local development
  credentials: true,
  methods: ["GET", "POST", "PUT", "DELETE", "OPTIONS"],
}));

app.use(express.json());
// 150.241.244.130:5432/olab

// ✅ Database Configuration — try localhost first, fallback to 150.241.244.130
// Fallback uses same credentials as python/utils/Final_olab_database.py: user lab, ssl off
const FALLBACK_HOST = "150.241.244.130";
function getDbConfig(host, options = {}) {
  const useSsl = options.ssl === true;
  const isRemote = host === FALLBACK_HOST || (host && host !== "localhost");
  const ssl = useSsl || (process.env.DB_SSL === "true" && !options.noSsl)
    ? { rejectUnauthorized: false }
    : false;
  return {
    user: options.user ?? process.env.DB_USER ?? "postgres",
    password: options.password ?? process.env.DB_PASSWORD ?? "",
    host: host || process.env.DB_HOST || "localhost",
    port: parseInt(process.env.DB_PORT || "5432", 10),
    database: process.env.DB_NAME || "olab",
    ssl,
    connectionTimeoutMillis: options.connectTimeout ?? 10000,
    idleTimeoutMillis: 30000,
    max: 10,
  };
}
/** Same as Final_olab_database.py: 150.241.244.130, user lab, ssl disable */
function getFallbackDbConfig() {
  return getDbConfig(FALLBACK_HOST, {
    user: process.env.DB_USER || process.env.FALLBACK_DB_USER || "lab",
    password: process.env.DB_PASSWORD || process.env.FALLBACK_DB_PASSWORD || "IndiaNepal1-",
    noSsl: true,
    connectTimeout: 30000,
  });
}
let dbConfig = getDbConfig(process.env.DB_HOST || "localhost");

console.log("🔧 Connecting to PostgreSQL at:", dbConfig.host + ":" + dbConfig.port + "/" + dbConfig.database);

// ✅ Create PostgreSQL Connection Pool
let pool;
async function initDatabase() {
  const tryConnect = async (config) => {
    const p = new Pool(config);
    const result = await p.query('SELECT NOW() as current_time, version() as pg_version');
    return { pool: p, result };
  };

  try {
    let connected = false;
    try {
      const { pool: p, result } = await tryConnect(dbConfig);
      pool = p;
      connected = true;
      console.log("✅ Connected to PostgreSQL successfully! (", dbConfig.host + ")");
      console.log("📅 Server time:", result.rows[0].current_time);
      console.log("🗄️ PostgreSQL version:", result.rows[0].pg_version.split(' ')[0] + ' ' + result.rows[0].pg_version.split(' ')[1]);
    } catch (localhostError) {
      if (dbConfig.host === "localhost" && !process.env.DB_HOST) {
        console.warn("⚠️ localhost connection failed:", localhostError.message);
        console.log("🔄 Trying fallback:", FALLBACK_HOST, "user=lab, no SSL (same as Final_olab_database.py)");
        dbConfig = getFallbackDbConfig();
        const { pool: p, result } = await tryConnect(dbConfig);
        pool = p;
        connected = true;
        console.log("✅ Connected to PostgreSQL via fallback", FALLBACK_HOST);
        console.log("📅 Server time:", result.rows[0].current_time);
        console.log("🗄️ PostgreSQL version:", result.rows[0].pg_version.split(' ')[0] + ' ' + result.rows[0].pg_version.split(' ')[1]);
      } else {
        throw localhostError;
      }
    }

    // Test if our trading tables exist
    const tablesResult = await pool.query(`
      SELECT table_name 
      FROM information_schema.tables 
      WHERE table_schema = 'public' 
      ORDER BY table_name;
    `);
    console.log("📋 Available tables:", tablesResult.rows.map(r => r.table_name).join(', '));

  } catch (error) {
    console.error("❌ Database connection failed:", error.message);
    console.error("🔧 Tried:", dbConfig.host + ":" + dbConfig.port, dbConfig.host === "localhost" ? "(and fallback " + FALLBACK_HOST + ")" : "");
    process.exit(1);
  }
}

// ✅ Health Check Route
app.get("/", async (req, res) => {
  try {
    const result = await pool.query('SELECT NOW() as server_time');
    res.json({
      status: "✅ Local server is working!",
      database: "✅ PostgreSQL connected",
      server_time: result.rows[0].server_time,
      host: dbConfig.host,
      database_name: dbConfig.database
    });
  } catch (error) {
    res.status(500).json({
      status: "❌ Server error",
      error: error.message
    });
  }
});

// ✅ API: Fetch All Trades
app.get("/api/trades", async (req, res) => {
  try {
    console.log("🔍 [Trades] Request received");
    
    const result = await pool.query("SELECT * FROM alltraderecords ORDER BY candel_time DESC NULLS LAST LIMIT 100;");
    
    console.log("✅ [Trades] Fetched", result.rows.length, "trades");
    if (result.rows.length > 0) {
      const r = result.rows[0];
      console.log("📊 [Trades] Latest trade:", {
        candel_time: r.candel_time,
        pair: r.pair || r.symbol,
        action: r.action || r.side
      });
    }
    
    res.json({ 
      trades: result.rows,
      count: result.rows.length,
      source: "Ubuntu Server Database"
    });
  } catch (error) {
    console.error("❌ [Trades] Error:", error.message);
    res.status(500).json({ 
      error: error.message,
      hint: "Check if 'alltraderecords' table exists in the database"
    });
  }
});

// ✅ API: Fetch Machines
app.get("/api/machines", async (req, res) => {
  try {
    console.log("🔍 [Machines] Request received");
    
    const result = await pool.query("SELECT machineid, active FROM machines ORDER BY machineid;");
    
    console.log("✅ [Machines] Fetched", result.rows.length, "machines");
    
    res.json({ 
      machines: result.rows,
      count: result.rows.length,
      source: "Ubuntu Server Database"
    });
  } catch (error) {
    console.error("❌ [Machines] Error:", error.message);
    res.status(500).json({ 
      error: error.message,
      hint: "Check if 'machines' table exists in the database"
    });
  }
});

// ✅ API: Test Database Tables
app.get("/api/tables", async (req, res) => {
  try {
    const result = await pool.query(`
      SELECT table_name, 
             (SELECT COUNT(*) FROM information_schema.columns WHERE table_name = t.table_name) as column_count
      FROM information_schema.tables t
      WHERE table_schema = 'public' 
      ORDER BY table_name;
    `);
    
    res.json({
      tables: result.rows,
      count: result.rows.length,
      database: dbConfig.database
    });
  } catch (error) {
    console.error("❌ [Tables] Error:", error.message);
    res.status(500).json({ error: error.message });
  }
});

// ✅ API: Fetch SignalProcessingLogs  
app.get("/api/signalprocessinglogs", async (req, res) => {
  try {
    console.log("🔍 [SignalLogs] Request received");
    
    const result = await pool.query("SELECT * FROM signalprocessinglogs ORDER BY timestamp DESC LIMIT 100;");
    
    console.log("✅ [SignalLogs] Fetched", result.rows.length, "signal logs");
    
    res.json({ 
      logs: result.rows,
      count: result.rows.length,
      source: "Ubuntu Server Database"
    });
  } catch (error) {
    console.error("❌ [SignalLogs] Error:", error.message);
    res.status(500).json({ 
      error: error.message,
      hint: "Check if 'signalprocessinglogs' table exists in the database"
    });
  }
});

// ✅ API: Bot Event Logs (same shape as server.example.js for LiveTradeViewPage)
app.get("/api/bot-event-logs", async (req, res) => {
  try {
    const page = parseInt(req.query.page) || 1;
    const limit = req.query.limit === "all" ? "all" : (parseInt(req.query.limit) || 50);
    const offset = (limit === "all" ? 0 : (page - 1) * limit);

    let whereConditions = [];
    let params = [];
    let paramIndex = 1;
    if (req.query.uid) {
      whereConditions.push(`uid = $${paramIndex}`);
      params.push(req.query.uid);
      paramIndex++;
    }
    const whereClause = whereConditions.length > 0 ? `WHERE ${whereConditions.join(" AND ")}` : "";
    const orderByClause = "ORDER BY timestamp DESC";

    const countQuery = `SELECT COUNT(*) as total FROM bot_event_log ${whereClause}`;
    const countResult = await pool.query(countQuery, params);
    const total = parseInt(countResult.rows[0].total, 10);

    const dataQuery = `
      SELECT id, uid, source, pl_after_comm, plain_message, json_message, timestamp, machine_id
      FROM bot_event_log
      ${whereClause}
      ${orderByClause}
      ${limit === "all" ? "" : `LIMIT ${limit} OFFSET ${offset}`}
    `;
    const dataResult = await pool.query(dataQuery, params);
    const logs = dataResult.rows.map((log) => {
      let parsedJson = null;
      if (log.json_message) {
        try {
          parsedJson = JSON.parse(log.json_message);
        } catch (e) {}
      }
      return { ...log, parsed_json_message: parsedJson };
    });

    console.log("🔍 [BotEventLogs] Request received", req.query.uid ? `uid=${req.query.uid}` : "", "→", logs.length, "logs");

    res.json({
      logs,
      pagination: {
        page,
        limit,
        total,
        totalPages: limit === "all" ? 1 : Math.ceil(total / limit),
        hasNext: limit === "all" ? false : page < Math.ceil(total / limit),
        hasPrev: limit === "all" ? false : page > 1,
      },
    });
  } catch (error) {
    console.error("❌ [BotEventLogs] Error:", error.message);
    res.status(500).json({ error: error.message || "Failed to fetch bot event logs" });
  }
});

// ✅ Auto-Pilot state (in-memory by unique_id; replace with DB if needed)
const autopilotStore = new Map();
app.get("/api/autopilot", (req, res) => {
  const unique_id = (req.query.unique_id || "").trim();
  if (!unique_id) return res.status(400).json({ error: "unique_id required" });
  const entry = autopilotStore.get(unique_id);
  res.json({ enabled: !!(entry && entry.enabled) });
});
app.post("/api/autopilot", (req, res) => {
  const { unique_id, password, enabled } = req.body || {};
  if (!(unique_id && typeof unique_id === "string")) return res.status(400).json({ error: "unique_id required" });
  autopilotStore.set(unique_id.trim(), { enabled: !!enabled, updatedAt: new Date().toISOString() });
  res.json({ ok: true, enabled: !!enabled });
});

// ✅ Proxy to Python CalculateSignals API (run python api_signals.py on port 5001)
const PYTHON_SIGNALS_URL = process.env.PYTHON_SIGNALS_URL || "http://localhost:5001";
app.post("/api/calculate-signals", async (req, res) => {
  try {
    console.log("[calculate-signals] Request body:", JSON.stringify(req.body));
    const resp = await fetch(`${PYTHON_SIGNALS_URL}/api/calculate-signals`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(req.body),
      signal: AbortSignal.timeout(Number(process.env.CALCULATE_SIGNALS_TIMEOUT_MS) || 300000), // 5 min default (4 intervals can be slow)
    });
    const data = await resp.json().catch(() => ({}));
    console.log("[calculate-signals] Python API response:", JSON.stringify(data, null, 2));
    res.status(resp.status || 200).json(data);
  } catch (err) {
    console.error("[calculate-signals] Proxy error:", err.message);
    res.status(502).json({ ok: false, message: err.message || "Python signals service unavailable" });
  }
});

// ✅ Initialize and Start Server
async function startServer() {
  await initDatabase();
  
  app.listen(PORT, () => {
    console.log("\n🚀 Local Server Started Successfully!");
    console.log("📍 Server URL: http://localhost:" + PORT);
    console.log("🗄️ Database: " + dbConfig.host + ":" + dbConfig.port + "/" + dbConfig.database);
    console.log("\n📋 Available endpoints:");
    console.log("   GET  /                     - Health check");
    console.log("   GET  /api/trades           - Fetch trading records");
    console.log("   GET  /api/machines         - Fetch machine status");
    console.log("   GET  /api/tables           - List all database tables");
    console.log("   GET  /api/signalprocessinglogs - Fetch signal logs");
    console.log("   GET  /api/bot-event-logs       - Fetch bot event logs (uid, page, limit)");
    console.log("   POST /api/calculate-signals    - Proxy to Python (PYTHON_SIGNALS_URL)");
    console.log("\n✨ Ready to serve data from your Ubuntu trading server!");
  });
}

// ✅ Handle graceful shutdown
process.on('SIGINT', async () => {
  console.log('\n🔄 Shutting down server...');
  if (pool) {
    await pool.end();
    console.log('✅ Database connections closed');
  }
  process.exit(0);
});

// ✅ Start the server
startServer().catch(error => {
  console.error("❌ Failed to start server:", error);
  process.exit(1);
});
