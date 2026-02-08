const express = require("express");
const cors = require("cors");
const { Pool } = require("pg");
const axios = require('axios');

const app = express();
const fs = require("fs");
let currentLogPath = "D:/Projects/blockchainProject/pythonProject/Binance/Loveleet_Anish_Bot/LAB-New-Logic/hedge_logs";
const PORT = process.env.PORT || 10000;

// ✅ Allowed Frontend Origins (Local + Vercel + Render)
const allowedOrigins = [
  "http://localhost:5173", // Local Vite
  "http://localhost:5174", // Alternate local Vite
  "https://lab-anish.onrender.com", // Your backend (if you ever serve frontend from here)
  "https://lab-anish.vercel.app", // Vercel frontend
  "https://lab-anish.onrender.com", // Alternate Render frontend
  "https://lab-code-4kbs-git-lab-loveleets-projects-ef26b22c.vercel.app/", // Vercel preview
  "https://lab-code-4kbs-q77fv3aml-loveleets-projects-ef26b22c.vercel.app/", // Vercel preview
  // Add any other frontend URLs you use here
];

// ✅ Proper CORS Handling
app.use(cors({
  origin: function (origin, callback) {
    if (!origin || allowedOrigins.includes(origin)) {
      callback(null, true);
    } else {
      console.error("❌ CORS blocked origin:", origin);
      callback(new Error("CORS not allowed for this origin"));
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

// ✅ Database Configuration
const dbConfig = {
  user: process.env.DB_USER || "postgres",
  password: process.env.DB_PASSWORD || "IndiaNepal1-",
  host: process.env.DB_HOST || "150.241.245.36",
  port: parseInt(process.env.DB_PORT) || 5432,
  database: process.env.DB_NAME || "olab",
  ssl: false, // Disable SSL for direct connection
  connectionTimeoutMillis: 30000, // 30 second timeout
  idleTimeoutMillis: 30000,
  max: 20, // Maximum number of connections
};

// ✅ Retry PostgreSQL Connection Until Successful
async function connectWithRetry() {
  try {
    const pool = new Pool(dbConfig);
    // Test the connection
    await pool.query('SELECT NOW()');
    console.log("✅ Connected to PostgreSQL");
    return pool;
  } catch (err) {
    console.error("❌ PostgreSQL Connection Failed. Retrying in 5 seconds...", err.code || err.message);
    await new Promise((resolve) => setTimeout(resolve, 5000));
    return connectWithRetry();
  }
}

let poolPromise = connectWithRetry();

// ✅ Health Check Route
app.get("/", (req, res) => {
  res.send("✅ Backend is working!");
});

// ✅ API: Fetch All Trades
app.get("/api/trades", async (req, res) => {
  try {
    console.log("🔍 [Trades] Request received");
    const pool = await poolPromise;
    if (!pool) throw new Error("Database not connected");
    const result = await pool.query("SELECT * FROM alltraderecords;");
    console.log("🔍 [Trades] Fetched", result.rows.length, "trades");
    console.log("🔍 [Trades] Sample trade:", result.rows[0]);
    res.json({ trades: result.rows });
  } catch (error) {
    console.error("❌ [Trades] Error:", error);
    res.status(500).json({ error: error.message || "Failed to fetch trades" });
  }
});

// ✅ API: Fetch Machines
app.get("/api/machines", async (req, res) => {
  try {
    const pool = await poolPromise;
    if (!pool) throw new Error("Database not connected");
    const result = await pool.query("SELECT machineid, active FROM machines;");
    res.json({ machines: result.rows });
  } catch (error) {
    console.error("❌ Query Error (/api/machines):", error.message);
    res.status(500).json({ error: error.message || "Failed to fetch machines" });
  }
});

// ✅ Binance Proxy Endpoint
const LOCAL_PROXY =
  process.env.NODE_ENV === 'production'
    ? 'https://lab-anish.onrender.com/api/klines'
    : 'http://localhost:10000/api/klines';

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
    if (!pool) throw new Error("Database not connected");
    
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

// ✅ Start Express Server
app.listen(PORT, () => {
  console.log(`🚀 Server running at http://localhost:${PORT}`);
});
const http = require("https");

// ✅ Self-Ping to Prevent Render Sleep (every 14 minutes)
setInterval(() => {
  
  http.get("https://lab-anish.onrender.com/api/machines", (res) => {
    console.log(`📡 Self-ping status: ${res.statusCode}`);
  }).on("error", (err) => {
    console.error("❌ Self-ping failed:", err.message);
  });
}, 14 * 60 * 1000); // 14 minutes