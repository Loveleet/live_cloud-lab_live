const fs = require("fs");
const path = require("path");

// ✅ Load secrets from one file (never in Git). Tries: SECRETS_FILE env, then ./secrets.env, ../secrets.env, /etc/lab-trading-dashboard.secrets.env
(function loadSecretsEnv() {
  const tryPaths = [
    process.env.SECRETS_FILE,
    path.join(__dirname, "secrets.env"),
    path.join(__dirname, "..", "secrets.env"),
    "/etc/lab-trading-dashboard.secrets.env",
  ].filter(Boolean);
  for (const p of tryPaths) {
    try {
      if (fs.existsSync(p)) {
        const content = fs.readFileSync(p, "utf8");
        content.split("\n").forEach((line) => {
          const trimmed = line.replace(/#.*$/, "").trim();
          if (!trimmed) return;
          const match = trimmed.match(/^(?:export\s+)?([A-Za-z_][A-Za-z0-9_]*)=(.*)$/);
          if (match && process.env[match[1]] === undefined) {
            process.env[match[1]] = match[2].replace(/^["']|["']$/g, "").trim();
          }
        });
        console.log("[secrets] Loaded from", p);
        return;
      }
    } catch (e) {
      // skip invalid path
    }
  }
})();

const express = require("express");
const cors = require("cors");
const cookieParser = require("cookie-parser");
const { Pool } = require("pg");
const axios = require('axios');
const { spawn } = require("child_process");

const app = express();

const SEP = "────────────────────────────────────────────────────────────";
function log(msg, level = "INFO") {
  const ts = new Date().toISOString();
  console.log(`\n[${ts}] [${level}] ${msg}\n${SEP}`);
}
function sendTelegramSync(message) {
  const py = path.join(__dirname, "..", "python", "send_telegram_cli.py");
  try {
    const proc = spawn(process.platform === "win32" ? "python" : "python3", [py, message], {
      cwd: path.join(__dirname, "..", "python"),
      stdio: "ignore",
    });
    proc.on("error", (e) => log(`Telegram send failed: ${e.message}`, "ERROR"));
  } catch (e) {
    log(`Telegram send failed: ${e.message}`, "ERROR");
  }
}
let currentLogPath = "D:/Projects/blockchainProject/pythonProject/Binance/Loveleet_Anish_Bot/LAB-New-Logic/hedge_logs";
const PORT = process.env.PORT || 10000;
const ENABLE_SELF_PING = String(process.env.ENABLE_SELF_PING || '').toLowerCase() === 'true';
const VERBOSE_LOG = String(process.env.VERBOSE_LOG || '').toLowerCase() === 'true';

// ✅ Allowed Frontend Origins (local dev, cloud server, GitHub Pages). Add more via ALLOWED_ORIGINS env.
const extraOrigins = (process.env.ALLOWED_ORIGINS || "")
  .split(",")
  .map((o) => o.trim())
  .filter(Boolean);
const allowedOrigins = [
  "http://localhost:5173",
  "http://localhost:5174",
  "http://localhost:10000",
  "http://150.241.244.130:10000",
  "https://loveleet.github.io",
  ...extraOrigins,
];

// ✅ Proper CORS Handling
app.use(cors({
  origin: function (origin, callback) {
    try {
      if (!origin) {
        console.log("[CORS] Request with no origin (same-origin or server-to-server) — allowing");
        return callback(null, true);
      }
      if (allowedOrigins.includes(origin)) {
        console.log("[CORS] ✅ Allowed origin:", origin);
        return callback(null, true);
      }
      console.error("❌ CORS blocked origin:", origin);
      console.error("❌ Allowed origins:", allowedOrigins.join(", "));
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
app.use(cookieParser());

// ─── Public routes (no auth) ────────────────────────────────────────────────
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

// ✅ Database Configuration — use Render DATABASE_URL so cloud shows same data as Render, or DB_* vars
function buildDbConfig() {
  const databaseUrl = process.env.DATABASE_URL;
  if (databaseUrl) {
    try {
      const url = new URL(databaseUrl);
      const db = (url.pathname || '/labdb2').replace(/^\//, '') || 'labdb2';
      const host = (url.hostname === '150.241.244.130' && process.env.RUNNING_ON_CLOUD_VM === '1') ? '127.0.0.1' : url.hostname;
      return {
        host,
        port: parseInt(url.port || '5432', 10),
        user: url.username || 'postgres',
        password: String(url.password ?? ''),
        database: db,
        connectionTimeoutMillis: 10000,
        idleTimeoutMillis: 30000,
        max: 10,
      };
    } catch (e) {
      console.error("Invalid DATABASE_URL:", e.message);
    }
  }
  // Default to cloud database (150.241.244.130) for local development
  // Set DB_HOST=localhost to use local PostgreSQL instead
  const dbHost = process.env.DB_HOST || '150.241.244.130';
  const isLocalHost = dbHost === 'localhost' || dbHost === '127.0.0.1';
  const isCloudHost = dbHost === '150.241.244.130';
  
  // On macOS localhost, PostgreSQL often has no "postgres" role — use current user if DB_USER not set
  // For cloud DB, default to "lab" user
  let defaultUser = 'postgres';
  if (isLocalHost && process.env.USER) {
    defaultUser = process.env.USER;
  } else if (isCloudHost) {
    defaultUser = 'lab';
  }
  
  // Real trading data is in "olab" (same as Final_olab_database.py). Use DB_NAME=labdb2 for demo/seed data.
  const defaultDb = isCloudHost ? 'olab' : 'labdb2';
  // When running ON the cloud VM (Ubuntu at 150.241.244.130), connect to localhost
  const host = (dbHost === '150.241.244.130' && process.env.RUNNING_ON_CLOUD_VM === '1') ? '127.0.0.1' : dbHost;
  return {
    host,
    port: parseInt(process.env.DB_PORT || '5432', 10),
    user: process.env.DB_USER || defaultUser,
    password: String(process.env.DB_PASSWORD ?? (isCloudHost ? 'IndiaNepal1-' : '')),
    database: process.env.DB_NAME || defaultDb,
    connectionTimeoutMillis: 10000,
    idleTimeoutMillis: 30000,
    max: 10,
  };
}
const dbConfig = buildDbConfig();
log(`CORS allowed origins: ${allowedOrigins.join(", ")}`);
if (process.env.DATABASE_URL) {
  log("DB | Using DATABASE_URL (Render/cloud)");
} else {
  const hostType = dbConfig.host === '150.241.244.130' ? 'CLOUD' : (dbConfig.host === 'localhost' ? 'LOCAL' : 'REMOTE');
  log(`DB | ${hostType} | host=${dbConfig.host} database=${dbConfig.database} user=${dbConfig.user}`);
}
if (dbConfig.database !== 'olab' && dbConfig.host === '150.241.244.130') {
  console.warn("[DB] ⚠️ Cloud server should use database=olab for real data. Current:", dbConfig.database);
}

// ✅ Retry PostgreSQL Connection Until Successful (try non-SSL first when using localhost, like Render)
// Ensure password is always a string (node-pg SCRAM requires string)
function normalizePoolConfig(cfg) {
  return { ...cfg, password: String(cfg.password ?? '') };
}
function getConnectionConfigs() {
  const isLocal = !dbConfig.host || dbConfig.host === 'localhost' || dbConfig.host === '127.0.0.1';
  const isCloud = dbConfig.host === '150.241.244.130';
  
  if (isLocal) {
    return [
      normalizePoolConfig({ ...dbConfig, ssl: false }),
      normalizePoolConfig({ ...dbConfig, ssl: { rejectUnauthorized: false } }),
      normalizePoolConfig({ ...dbConfig, ssl: { rejectUnauthorized: false, sslmode: 'require' } }),
    ];
  }
  
  // Cloud DB (150.241.244.130) - try non-SSL first (same as Python code)
  if (isCloud) {
    return [
      normalizePoolConfig({ ...dbConfig, ssl: false }),
      normalizePoolConfig({ ...dbConfig, ssl: { rejectUnauthorized: false } }),
    ];
  }
  
  // Other remote hosts - try SSL first
  return [
    normalizePoolConfig({ ...dbConfig, ssl: { rejectUnauthorized: false } }),
    normalizePoolConfig({ ...dbConfig, ssl: { rejectUnauthorized: false, sslmode: 'require' } }),
    normalizePoolConfig({ ...dbConfig, ssl: false }),
  ];
}

const MAX_DB_RETRY_ROUNDS = 2; // then resolve with null so API doesn't hang

async function connectWithRetry(round = 0) {
  const configs = getConnectionConfigs();

  for (let i = 0; i < configs.length; i++) {
    const config = configs[i];
    try {
      // node-pg SCRAM requires password to be a string; force it at use site
      config.password = typeof config.password === 'string' ? config.password : String(config.password ?? '');
      console.log(`🔧 Attempt ${i + 1}: PostgreSQL connection to:`, `${config.host}:${config.port}/${config.database} (user: ${config.user})`);
      
      const pool = new Pool(config);
      await pool.query('SELECT NOW()');
      console.log(`✅ Connected to PostgreSQL successfully with config ${i + 1}`);
      const countResult = await pool.query('SELECT count(*) as c FROM alltraderecords').catch(() => ({ rows: [{ c: 0 }] }));
      const tradeCount = parseInt(countResult.rows[0]?.c || 0, 10);
      console.log(`[DB] alltraderecords has ${tradeCount} rows — dashboard will show ${tradeCount} trades`);
      return pool;
    } catch (err) {
      console.error(`❌ PostgreSQL Connection Failed (attempt ${i + 1}):`, err.message);
      
      if (i === configs.length - 1) {
        if (round < MAX_DB_RETRY_ROUNDS - 1) {
          console.error("   All configs failed. Retrying in 5 seconds...");
          await new Promise((resolve) => setTimeout(resolve, 5000));
          return connectWithRetry(round + 1);
        }
        console.error("   Giving up after " + MAX_DB_RETRY_ROUNDS + " rounds. API will run without DB (trades/debug will return empty). Set DATABASE_URL or DB_* to fix.");
        return null;
      }
      console.log(`   Trying next configuration...`);
    }
  }
  return null;
}

let poolPromise = connectWithRetry();

// ✅ Health Check (for monitoring)
app.get("/api/health", (req, res) => {
  res.send("✅ Backend is working!");
});

// ✅ Server config check (no secrets) — verify cloud has CORS + olab; call from browser or: curl https://tunnel-url/api/server-info
app.get("/api/server-info", (req, res) => {
  const requestOrigin = req.headers.origin || "(no origin header)";
  const isAllowed = !requestOrigin || requestOrigin === "(no origin header)" || allowedOrigins.includes(requestOrigin);
  res.json({
    ok: true,
    allowedOrigins,
    database: dbConfig.database,
    dbHost: dbConfig.host,
    hasGitHubPagesOrigin: allowedOrigins.includes("https://loveleet.github.io"),
    requestOrigin,
    requestOriginAllowed: isAllowed,
    message: allowedOrigins.includes("https://loveleet.github.io") && dbConfig.database === "olab"
      ? "Cloud server config OK for GitHub Pages (CORS + olab)"
      : "Update server.js on cloud: need CORS for loveleet.github.io and DB=olab",
  });
});

// ─── Auth: cookie-based sessions (users + sessions tables) ───────────────────
const SESSION_COOKIE = "session_id";
const COOKIE_SECURE = process.env.NODE_ENV === "production";
const SESSION_DAYS = 7;
const LOCKOUT_AFTER = 8;
const LOCKOUT_MINUTES = 15;

async function requireAuth(req, res, next) {
  const sid = req.cookies?.[SESSION_COOKIE];
  if (!sid) return res.status(401).json({ error: "Not logged in" });
  try {
    const pool = await poolPromise;
    if (!pool) return res.status(503).json({ error: "Database not connected" });
    const sRes = await pool.query(
      `SELECT s.id, s.user_id, u.email FROM sessions s
       JOIN users u ON u.id = s.user_id
       WHERE s.id = $1 AND s.expires_at > NOW() AND u.is_active = TRUE`,
      [sid]
    );
    if (sRes.rowCount === 0) return res.status(401).json({ error: "Session expired" });
    req.user = { id: sRes.rows[0].user_id, email: sRes.rows[0].email };
    next();
  } catch (e) {
    log(`requireAuth error: ${e.message}`, "ERROR");
    res.status(500).json({ error: "Auth check failed" });
  }
}

// Auth gate: protect /api/* except health and server-info; /api/tunnel-url stays public for scripts
const PUBLIC_API_PATHS = ["/api/health", "/api/server-info", "/api/tunnel-url"];
const ALLOW_PUBLIC_READ_SIGNALS = String(process.env.ALLOW_PUBLIC_READ_SIGNALS || "").toLowerCase() === "true";
const PUBLIC_READ_SIGNAL_PATHS = ["/api/pairstatus", "/api/active-loss", "/api/open-position", "/api/calculate-signals"];
app.use((req, res, next) => {
  if (req.path.startsWith("/api/") && PUBLIC_API_PATHS.includes(req.path)) return next();
  if (ALLOW_PUBLIC_READ_SIGNALS && req.path.startsWith("/api/") && PUBLIC_READ_SIGNAL_PATHS.includes(req.path)) return next();
  if (req.path.startsWith("/api/") || req.path === "/auth/me") return requireAuth(req, res, next);
  next();
});
if (ALLOW_PUBLIC_READ_SIGNALS) {
  log("ALLOW_PUBLIC_READ_SIGNALS=true — pairstatus, active-loss, open-position, calculate-signals are public", "INFO");
}

// POST /auth/login — verify password with crypt(), create session, set cookie
app.post("/auth/login", async (req, res) => {
  const { email, password } = req.body || {};
  const em = (email || "").trim();
  const pw = (password || "").trim();
  if (!em || !pw) return res.status(400).json({ error: "email and password required" });
  try {
    const pool = await poolPromise;
    if (!pool) return res.status(503).json({ error: "Database not connected" });
    const userRes = await pool.query(
      `SELECT id, email FROM users
       WHERE email = $1 AND is_active = TRUE
         AND (locked_until IS NULL OR locked_until <= NOW())
         AND password_hash = crypt($2, password_hash)`,
      [em, pw]
    );
    if (userRes.rowCount === 0) {
      await pool.query(
        `UPDATE users SET failed_attempts = failed_attempts + 1,
          locked_until = CASE WHEN failed_attempts + 1 >= $2 THEN NOW() + ($3 || ' minutes')::INTERVAL ELSE locked_until END
         WHERE email = $1`,
        [em, LOCKOUT_AFTER, LOCKOUT_MINUTES]
      ).catch(() => {});
      return res.status(401).json({ error: "Invalid credentials" });
    }
    const user = userRes.rows[0];
    await pool.query(`UPDATE users SET failed_attempts = 0, locked_until = NULL WHERE email = $1`, [em]);
    const sessionRes = await pool.query(
      `INSERT INTO sessions (user_id, expires_at) VALUES ($1, NOW() + ($2 || ' days')::INTERVAL)
       RETURNING id, expires_at`,
      [user.id, SESSION_DAYS]
    );
    const session = sessionRes.rows[0];
    res.cookie(SESSION_COOKIE, session.id, {
      httpOnly: true,
      secure: COOKIE_SECURE,
      sameSite: process.env.NODE_ENV === "production" ? "none" : "lax",
      path: "/",
      maxAge: SESSION_DAYS * 24 * 60 * 60 * 1000,
    });
    res.json({ ok: true, user: { id: user.id, email: user.email } });
  } catch (e) {
    log(`auth/login error: ${e.message}`, "ERROR");
    res.status(500).json({ error: "Login failed" });
  }
});

// POST /auth/logout — delete session, clear cookie
app.post("/auth/logout", (req, res) => {
  const sid = req.cookies?.[SESSION_COOKIE];
  if (sid) {
    poolPromise.then((pool) => {
      if (pool) pool.query(`DELETE FROM sessions WHERE id = $1`, [sid]).catch(() => {});
    }).catch(() => {});
  }
  res.clearCookie(SESSION_COOKIE, { path: "/" });
  res.json({ ok: true });
});

// GET /auth/me — return current user (auth gate sets req.user)
app.get("/auth/me", (req, res) => res.json({ ok: true, user: req.user }));

// Extend session (e.g. when user clicks "Stay logged in")
app.post("/auth/extend-session", async (req, res) => {
  const sid = req.cookies?.[SESSION_COOKIE];
  if (!sid) return res.status(401).json({ error: "Not logged in" });
  try {
    const pool = await poolPromise;
    if (!pool) return res.status(503).json({ error: "Database not connected" });
    const r = await pool.query(
      "SELECT id FROM sessions WHERE id = $1 AND expires_at > NOW()",
      [sid]
    );
    if (!r.rows?.length) return res.status(401).json({ error: "Session expired" });
    await pool.query(
      "UPDATE sessions SET expires_at = NOW() + ($1 || ' days')::INTERVAL WHERE id = $2",
      [SESSION_DAYS, sid]
    );
    res.json({ ok: true });
  } catch (e) {
    log(`auth/extend-session error: ${e.message}`, "ERROR");
    res.status(500).json({ error: "Failed to extend session" });
  }
});

// Return current Cloudflare tunnel URL (for GitHub Pages). Used by scripts/docs and so GitHub Pages can discover API.
// 1) Read /var/run/lab-tunnel-url (written by update-github-secret-from-tunnel.sh). 2) Fallback: parse cloudflared log.
const TUNNEL_URL_FILE = path.join("/var/run", "lab-tunnel-url");
const TUNNEL_LOG_PATHS = ["/var/log/cloudflared-tunnel.log", "/tmp/tunnel.log"];
const TUNNEL_URL_REGEX = /https:\/\/[a-zA-Z0-9.-]+\.trycloudflare\.com/g;

function getTunnelUrlFromLog(logPath) {
  try {
    if (!fs.existsSync(logPath)) return null;
    const content = fs.readFileSync(logPath, "utf8");
    const matches = content.match(TUNNEL_URL_REGEX);
    return matches && matches.length ? matches[matches.length - 1].trim() : null;
  } catch (e) { return null; }
}

app.get("/api/tunnel-url", (req, res) => {
  try {
    if (fs.existsSync(TUNNEL_URL_FILE)) {
      const url = fs.readFileSync(TUNNEL_URL_FILE, "utf8").trim();
      if (url) return res.json({ tunnelUrl: url });
    }
    for (const logPath of TUNNEL_LOG_PATHS) {
      const url = getTunnelUrlFromLog(logPath);
      if (url) return res.json({ tunnelUrl: url });
    }
  } catch (e) { /* ignore */ }
  res.json({ tunnelUrl: null });
});

// ✅ Auto-Pilot: in-memory cache + DB update (alltraderecords.auto = true)
const autopilotStore = new Map();
app.get("/api/autopilot", (req, res) => {
  const unique_id = (req.query.unique_id || "").trim();
  if (!unique_id) return res.status(400).json({ error: "unique_id required" });
  const entry = autopilotStore.get(unique_id);
  res.json({ enabled: !!(entry && entry.enabled) });
});
app.post("/api/autopilot", async (req, res) => {
  const { unique_id, machineid, password, enabled } = req.body || {};
  if (!(unique_id && typeof unique_id === "string")) return res.status(400).json({ ok: false, message: "unique_id required" });
  if ((!machineid || typeof machineid !== "string")) {
    return res.status(400).json({ ok: false, message: "machineid is required for autopilot" });
  }

  // Verify password against logged-in user (users table)
  const pw = (password || "").trim();
  if (!pw) return res.status(400).json({ ok: false, message: "Password required" });
  const user = req.user;
  if (!user?.id) return res.status(401).json({ ok: false, message: "Not logged in" });
  try {
    const pool = await poolPromise;
    if (!pool) return res.status(503).json({ ok: false, message: "Database not connected. Please try again later." });
    const verifyRes = await pool.query(
      "SELECT 1 FROM users WHERE id = $1 AND password_hash = crypt($2, password_hash)",
      [user.id, pw]
    );
    if (verifyRes.rowCount === 0) return res.status(401).json({ ok: false, message: "Invalid password" });
  } catch (e) {
    log(`autopilot password verify error: ${e.message}`, "ERROR");
    return res.status(500).json({ ok: false, message: "Password verification failed" });
  }

  if (machineid && typeof machineid === "string") {
    try {
      const pool = await poolPromise;
      if (!pool) {
        return res.status(503).json({ ok: false, message: "Database not connected. Please try again later." });
      }
      const m = (machineid || "").trim();
      const autoVal = !!enabled;
      // Match both 'running' and 'hedge_hold' so Auto-Pilot works for hedged trades too
      const r1 = await pool.query(
        "UPDATE alltraderecords SET auto = $3 WHERE unique_id = $1 AND machineid = $2 AND type IN ('running', 'hedge_hold')",
        [unique_id.trim(), m, autoVal]
      );
      if (r1.rowCount === 0) {
        return res.status(404).json({
          ok: false,
          message: "No matching trade found. The trade may not exist, or may not be in 'running'/'hedge_hold' state, or machineid does not match.",
        });
      }
      const machineTable = m.toLowerCase().replace(/[^a-z0-9_]/g, "");
      if (/^m\d+$/.test(machineTable)) {
        try {
          await pool.query(
            `UPDATE ${machineTable} SET auto = $2 WHERE unique_id = $1 AND type IN ('running', 'hedge_hold')`,
            [unique_id.trim(), autoVal]
          );
        } catch (e2) {
          console.warn("[autopilot] Per-machine table update failed (alltraderecords updated):", e2.message);
        }
      }
    } catch (e) {
      console.error("[autopilot] DB update error:", e.message);
      return res.status(500).json({ ok: false, message: `Database error: ${e.message}` });
    }
  }

  autopilotStore.set(unique_id.trim(), { enabled: !!enabled, updatedAt: new Date().toISOString() });
  res.json({ ok: true, enabled: !!enabled });
});

// ✅ Debug: table row counts (no secrets)
app.get("/api/debug", async (req, res) => {
  try {
    const pool = await poolPromise;
    if (!pool) return res.json({ ok: false, error: "Database not connected" });
    const tables = ["alltraderecords", "machines", "pairstatus", "signalprocessinglogs", "bot_event_log"];
    const counts = {};
    const sampleData = {};
    for (const table of tables) {
      try {
        const r = await pool.query(`SELECT count(*) as c FROM ${table}`);
        counts[table] = parseInt(r.rows[0]?.c ?? 0, 10);
        // Get sample row if table has data
        if (counts[table] > 0) {
          try {
            const sample = await pool.query(`SELECT * FROM ${table} LIMIT 1`);
            if (sample.rows.length > 0) {
              sampleData[table] = {
                columns: Object.keys(sample.rows[0]),
                hasData: true
              };
            }
          } catch (e) {
            sampleData[table] = { error: e.message };
          }
        } else {
          sampleData[table] = { hasData: false };
        }
      } catch (e) {
        counts[table] = e.code === "42P01" ? "missing" : e.message;
        sampleData[table] = { error: e.code === "42P01" ? "table missing" : e.message };
      }
    }
    const tradesEmpty = counts.alltraderecords === 0 || counts.alltraderecords === "missing";
    res.json({ 
      ok: true, 
      counts, 
      sampleData,
      dbConfig: {
        host: dbConfig.host,
        port: dbConfig.port,
        database: dbConfig.database,
        user: dbConfig.user,
        usingDATABASE_URL: !!process.env.DATABASE_URL
      },
      hint: tradesEmpty ? "alltraderecords is empty or missing — copy DB or add data to see trades" : null 
    });
  } catch (e) {
    res.json({ ok: false, error: e.message, stack: e.stack });
  }
});

// ✅ Test DB: Get sample rows from key tables
app.get("/api/test-db", async (req, res) => {
  try {
    const pool = await poolPromise;
    if (!pool) {
      return res.json({ ok: false, error: "Database pool not available" });
    }
    
    // Test connection
    const connectionTest = await pool.query('SELECT NOW() as current_time, version() as pg_version');
    
    // Get sample from alltraderecords
    let tradesSample = [];
    try {
      const tradesResult = await pool.query('SELECT * FROM alltraderecords LIMIT 3');
      tradesSample = tradesResult.rows;
    } catch (e) {
      tradesSample = [{ error: e.message, code: e.code }];
    }
    
    // Get sample from signalprocessinglogs
    let signalsSample = [];
    try {
      const signalsResult = await pool.query('SELECT * FROM signalprocessinglogs ORDER BY created_at DESC LIMIT 3');
      signalsSample = signalsResult.rows;
    } catch (e) {
      signalsSample = [{ error: e.message, code: e.code }];
    }
    
    res.json({
      ok: true,
      connection: {
        connected: true,
        currentTime: connectionTest.rows[0].current_time,
        pgVersion: connectionTest.rows[0].pg_version.split(' ')[0] + ' ' + connectionTest.rows[0].pg_version.split(' ')[1]
      },
      samples: {
        alltraderecords: tradesSample,
        signalprocessinglogs: signalsSample
      },
      message: tradesSample.length > 0 && !tradesSample[0].error 
        ? `✅ Database is returning data — found ${tradesSample.length} sample trade(s)`
        : "⚠️ Database connection works but alltraderecords table is empty or missing"
    });
  } catch (e) {
    res.json({ ok: false, error: e.message, code: e.code, stack: e.stack });
  }
});

// ✅ API: Fetch All Trades
// ✅ API: Fetch SuperTrend Signals (returns empty if table missing so dashboard doesn't 500)
app.get("/api/supertrend", async (req, res) => {
  try {
    const pool = await poolPromise;
    if (!pool) return res.json({ supertrend: [] });
    const result = await pool.query(
      'SELECT source, trend, timestamp FROM supertrend ORDER BY timestamp DESC LIMIT 10;'
    );
    res.json({ supertrend: result.rows || [] });
  } catch (error) {
    if (isMissingTable(error)) {
      console.log("[SuperTrend] Table supertrend missing — returning empty");
      return res.json({ supertrend: [] });
    }
    console.error("❌ [SuperTrend] Error:", error.message);
    res.status(500).json({ error: error.message || "Failed to fetch SuperTrend data" });
  }
});
// Helper: true if error is "table does not exist"
function isMissingTable(err) {
  return err && (err.code === "42P01" || (err.message && err.message.includes("does not exist")));
}

app.get("/api/trades", async (req, res) => {
  try {
    const pool = await poolPromise;
    if (!pool) {
      console.log("[Trades] ❌ No pool — returning empty");
      return res.json({ trades: [], _meta: { count: 0, table: "alltraderecords", error: "pool not available" } });
    }
    
    // Test connection first
    try {
      await pool.query('SELECT 1');
    } catch (connErr) {
      console.error("[Trades] ❌ Connection test failed:", connErr.message);
      return res.json({ trades: [], _meta: { count: 0, table: "alltraderecords", error: "connection failed", details: connErr.message } });
    }
    
    const result = await pool.query("SELECT * FROM alltraderecords ORDER BY created_at DESC NULLS LAST, unique_id DESC;");
    const count = result.rows.length;
    
    console.log(`[Trades] ✅ Fetched ${count} rows from alltraderecords`);
    if (count > 0) {
      console.log(`[Trades] Sample columns: ${Object.keys(result.rows[0]).join(', ')}`);
      console.log(`[Trades] First trade pair: ${result.rows[0].pair || 'N/A'}, created_at: ${result.rows[0].created_at || 'N/A'}`);
    } else {
      console.log("[Trades] ⚠️ Table is empty — dashboard will show no trade rows until data is added or DB is copied.");
    }
    
    res.json({ trades: result.rows, _meta: { count, table: "alltraderecords", timestamp: new Date().toISOString() } });
  } catch (error) {
    if (isMissingTable(error)) {
      console.log("[Trades] ⚠️ Table alltraderecords missing — returning empty");
      return res.json({ trades: [], _meta: { count: 0, table: "alltraderecords", error: "table missing", code: error.code } });
    }
    console.error("❌ [Trades] Error:", error.message);
    console.error("❌ [Trades] Error code:", error.code);
    console.error("❌ [Trades] Error stack:", error.stack);
    res.status(500).json({ error: error.message || "Failed to fetch trades", code: error.code });
  }
});

// ✅ API: Fetch single trade by unique_id (efficient — no full table scan)
app.get("/api/trade", async (req, res) => {
  const unique_id = (req.query.unique_id || "").trim();
  if (!unique_id) return res.status(400).json({ error: "unique_id query param required" });
  try {
    const pool = await poolPromise;
    if (!pool) return res.status(503).json({ error: "Database not connected" });
    const result = await pool.query("SELECT * FROM alltraderecords WHERE unique_id = $1 LIMIT 1", [unique_id]);
    const trade = result.rows[0] || null;
    res.json({ trade });
  } catch (error) {
    if (isMissingTable(error)) return res.json({ trade: null });
    console.error("❌ [Trade] Error:", error.message);
    res.status(500).json({ error: error.message || "Failed to fetch trade" });
  }
});

// ✅ Proxy to Python api_signals.py (calculate-signals, open-position, sync-open-positions)
const PYTHON_SIGNALS_URL = process.env.PYTHON_SIGNALS_URL || "http://localhost:5001";

app.get("/api/open-position", async (req, res) => {
  try {
    const symbol = (req.query.symbol || "").trim().toUpperCase();
    if (!symbol) return res.status(400).json({ ok: false, message: "symbol query param required" });
    const resp = await fetch(`${PYTHON_SIGNALS_URL}/api/open-position?symbol=${encodeURIComponent(symbol)}`, {
      method: "GET",
      signal: AbortSignal.timeout(15000),
    });
    const data = await resp.json().catch(() => ({}));
    res.status(resp.status || 200).json(data);
  } catch (err) {
    console.error("[open-position] Proxy error:", err.message);
    res.status(502).json({ ok: false, message: err.message || "Python signals service unavailable" });
  }
});

app.get("/api/sync-open-positions", async (req, res) => {
  try {
    const SYNC_POSITIONS_TIMEOUT_MS = Number(process.env.SYNC_POSITIONS_TIMEOUT_MS) || 180000;
    const resp = await fetch(`${PYTHON_SIGNALS_URL}/api/sync-open-positions`, {
      method: "GET",
      signal: AbortSignal.timeout(SYNC_POSITIONS_TIMEOUT_MS),
    });
    const data = await resp.json().catch(() => ({}));
    res.status(resp.status || 200).json(data);
  } catch (err) {
    console.error("[sync-open-positions] Proxy error:", err.message);
    res.status(502).json({ ok: false, message: err.message || "Python signals service unavailable" });
  }
});

app.get("/api/futures-balance", async (req, res) => {
  try {
    const resp = await fetch(`${PYTHON_SIGNALS_URL}/api/futures-balance`, {
      method: "GET",
      signal: AbortSignal.timeout(15000),
    });
    const data = await resp.json().catch(() => ({}));
    res.status(resp.status || 200).json(data);
  } catch (err) {
    console.error("[futures-balance] Proxy error:", err.message);
    res.status(502).json({ ok: false, message: err.message || "Python signals service unavailable" });
  }
});

app.get("/api/income-history", async (req, res) => {
  try {
    const qs = new URLSearchParams(req.query || {}).toString();
    const url = `${PYTHON_SIGNALS_URL}/api/income-history${qs ? `?${qs}` : ""}`;
    const resp = await fetch(url, {
      method: "GET",
      signal: AbortSignal.timeout(30000),
    });
    const data = await resp.json().catch(() => ({}));
    res.status(resp.status || 200).json(data);
  } catch (err) {
    console.error("[income-history] Proxy error:", err.message);
    res.status(502).json({ ok: false, message: err.message || "Python income-history service unavailable" });
  }
});

app.post("/api/calculate-signals", async (req, res) => {
  try {
    const resp = await fetch(`${PYTHON_SIGNALS_URL}/api/calculate-signals`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(req.body || {}),
      signal: AbortSignal.timeout(Number(process.env.CALCULATE_SIGNALS_TIMEOUT_MS) || 300000),
    });
    const data = await resp.json().catch(() => ({}));
    res.status(resp.status || 200).json(data);
  } catch (err) {
    console.error("[calculate-signals] Proxy error:", err.message);
    res.status(502).json({ ok: false, message: err.message || "Python signals service unavailable" });
  }
});

// ✅ POST /api/close-order — verify password, then proxy to Python closeOrder(symbol)
app.post("/api/close-order", async (req, res) => {
  const { symbol, password } = req.body || {};
  const sym = (symbol || "").trim().toUpperCase();
  const pw = (password || "").trim();
  if (!sym) return res.status(400).json({ ok: false, message: "symbol required" });
  if (!pw) return res.status(400).json({ ok: false, message: "Password required" });
  const user = req.user;
  if (!user?.id) return res.status(401).json({ ok: false, message: "Not logged in" });
  try {
    const pool = await poolPromise;
    if (!pool) return res.status(503).json({ ok: false, message: "Database not connected. Please try again later." });
    const verifyRes = await pool.query(
      "SELECT 1 FROM users WHERE id = $1 AND password_hash = crypt($2, password_hash)",
      [user.id, pw]
    );
    if (verifyRes.rowCount === 0) return res.status(401).json({ ok: false, message: "Invalid password" });
  } catch (e) {
    log(`close-order password verify error: ${e.message}`, "ERROR");
    return res.status(500).json({ ok: false, message: "Password verification failed" });
  }
  try {
    const resp = await fetch(`${PYTHON_SIGNALS_URL}/api/close-order?symbol=${encodeURIComponent(sym)}`, {
      method: "GET",
      signal: AbortSignal.timeout(15000),
    });
    const data = await resp.json().catch(() => ({}));
    res.status(resp.status || 200).json(data);
  } catch (err) {
    log(`close-order proxy error: ${err.message}`, "ERROR");
    res.status(502).json({ ok: false, message: err.message || "Python signals service unavailable" });
  }
});

// ✅ POST /api/end-trade — Flow: Frontend → server.js (here) → Python.
// Frontend sends symbol, position_side, quantity, password to Node. Node verifies password, then proxies to Python.
app.post("/api/end-trade", async (req, res) => {
  const { symbol, position_side, quantity, unique_id, password } = req.body || {};
  const sym = (symbol || "").trim().toUpperCase();
  const posSide = (position_side || "BOTH").toString().trim().toUpperCase();
  const pw = (password || "").trim();
  if (!sym) return res.status(400).json({ ok: false, message: "symbol required" });
  if (!pw) return res.status(400).json({ ok: false, message: "Password required" });
  if (!["LONG", "SHORT", "BOTH"].includes(posSide)) return res.status(400).json({ ok: false, message: "position_side must be LONG, SHORT, or BOTH" });
  const user = req.user;
  if (!user?.id) return res.status(401).json({ ok: false, message: "Not logged in" });
  try {
    const pool = await poolPromise;
    if (!pool) return res.status(503).json({ ok: false, message: "Database not connected. Please try again later." });
    const verifyRes = await pool.query(
      "SELECT 1 FROM users WHERE id = $1 AND password_hash = crypt($2, password_hash)",
      [user.id, pw]
    );
    if (verifyRes.rowCount === 0) return res.status(401).json({ ok: false, message: "Invalid password" });
  } catch (e) {
    log(`end-trade password verify error: ${e.message}`, "ERROR");
    return res.status(500).json({ ok: false, message: "Password verification failed" });
  }
  try {
    const body = JSON.stringify({
      symbol: sym,
      position_side: posSide,
      quantity: quantity === undefined || quantity === null || quantity === "" ? null : Number(quantity),
      unique_id: unique_id || null,
    });
    const resp = await fetch(`${PYTHON_SIGNALS_URL}/api/end-trade`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body,
      signal: AbortSignal.timeout(20000),
    });
    const data = await resp.json().catch(() => ({}));
    const uid = unique_id != null && String(unique_id).trim() !== "" ? String(unique_id).trim() : null;
    if (data?.ok && uid) {
      try {
        const pool = await poolPromise;
        if (pool) {
          let m1Rows = 0;
          let atrRows = 0;
          try {
            const m1Res = await pool.query("UPDATE m1 SET exchange_position = $1 WHERE unique_id = $2", ["close", uid]);
            m1Rows = m1Res?.rowCount ?? 0;
            log(`end-trade: m1 exchange_position=close for unique_id=${uid}, rows updated: ${m1Rows}`);
          } catch (e1) {
            log(`end-trade m1 update error (unique_id=${uid}): ${e1.message}`, "ERROR");
          }
          try {
            const atrRes = await pool.query("UPDATE alltraderecords SET exchange_position = $1 WHERE unique_id = $2", ["close", uid]);
            atrRows = atrRes?.rowCount ?? 0;
            log(`end-trade: alltraderecords exchange_position=close for unique_id=${uid}, rows updated: ${atrRows}`);
          } catch (e2) {
            log(`end-trade alltraderecords update error (unique_id=${uid}): ${e2.message}`, "ERROR");
          }
          if (m1Rows === 0 && atrRows === 0) {
            log(`end-trade: no rows updated for unique_id=${uid} (check that unique_id exists in m1/alltraderecords)`, "WARN");
          }
        } else {
          log(`end-trade: pool not available, skipping DB update for unique_id=${uid}`, "WARN");
        }
      } catch (e) {
        log(`end-trade DB update error (unique_id=${uid}): ${e.message}`, "ERROR");
      }
    } else if (data?.ok && !uid) {
      log(`end-trade: close succeeded but unique_id missing in request body — cannot update m1/alltraderecords`, "WARN");
    }
    res.status(resp.status || 200).json(data);
  } catch (err) {
    log(`end-trade proxy error: ${err.message}`, "ERROR");
    res.status(502).json({ ok: false, message: err.message || "Python signals service unavailable" });
  }
});

// Helper: verify password for logged-in user, return 401/500 on failure
async function verifyPasswordAndProxyToPython(req, res, pythonPath, bodyForPython) {
  const pw = (req.body?.password || "").trim();
  if (!pw) return res.status(400).json({ ok: false, message: "Password required" });
  const user = req.user;
  if (!user?.id) return res.status(401).json({ ok: false, message: "Not logged in" });
  try {
    const pool = await poolPromise;
    if (!pool) return res.status(503).json({ ok: false, message: "Database not connected. Please try again later." });
    const verifyRes = await pool.query(
      "SELECT 1 FROM users WHERE id = $1 AND password_hash = crypt($2, password_hash)",
      [user.id, pw]
    );
    if (verifyRes.rowCount === 0) return res.status(401).json({ ok: false, message: "Invalid password" });
  } catch (e) {
    log(`password verify error (${pythonPath}): ${e.message}`, "ERROR");
    return res.status(500).json({ ok: false, message: "Password verification failed" });
  }
  try {
    const resp = await fetch(`${PYTHON_SIGNALS_URL}${pythonPath}`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(bodyForPython || req.body || {}),
      signal: AbortSignal.timeout(20000),
    });
    const data = await resp.json().catch(() => ({}));
    res.status(resp.status || 200).json(data);
  } catch (err) {
    log(`proxy error (${pythonPath}): ${err.message}`, "ERROR");
    res.status(502).json({ ok: false, message: err.message || "Python signals service unavailable" });
  }
}

// ✅ POST /api/execute — Frontend → server.js → Python (NewOrderPlace: getQuantity + HedgeModePlaceOrder + setHedgeStopLoss)
app.post("/api/execute", async (req, res) => {
  const { symbol, amount, stop_price, position_side } = req.body || {};
  const sym = (symbol || "").toString().trim().toUpperCase();
  const amt = amount != null && amount !== "" ? String(amount).trim() : "";
  const stop = stop_price != null && stop_price !== "" ? String(stop_price).trim() : "";
  const posSide = (position_side || "LONG").toString().toUpperCase();
  if (!sym) return res.status(400).json({ ok: false, message: "symbol required" });
  if (!amt) return res.status(400).json({ ok: false, message: "amount required" });
  if (!stop) return res.status(400).json({ ok: false, message: "stop_price required" });
  await verifyPasswordAndProxyToPython(req, res, "/api/execute", { symbol: sym, amount: amt, stop_price: stop, position_side: posSide });
});

// ✅ POST /api/hedge — Frontend → server.js → Python (place_hedge_opposite: check then open_hedge_position)
app.post("/api/hedge", async (req, res) => {
  const { symbol, position_side, quantity } = req.body || {};
  const sym = (symbol || "").toString().trim().toUpperCase();
  const posSide = (position_side || "LONG").toString().toUpperCase();
  const qty = quantity != null && quantity !== "" ? String(quantity).trim() : "";
  if (!sym) return res.status(400).json({ ok: false, message: "symbol required" });
  if (!qty) return res.status(400).json({ ok: false, message: "quantity required" });
  await verifyPasswordAndProxyToPython(req, res, "/api/hedge", { symbol: sym, position_side: posSide, quantity: qty });
});

// ✅ POST /api/partial-close — Partially close position by quantity (Frontend → server.js → Python partial_close_position)
app.post("/api/partial-close", async (req, res) => {
  const { symbol, quantity, position_side } = req.body || {};
  const sym = (symbol || "").toString().trim().toUpperCase();
  const qty = quantity != null && quantity !== "" ? String(quantity).trim() : "";
  const posSide = (position_side || "LONG").toString().toUpperCase();
  if (!sym) return res.status(400).json({ ok: false, message: "symbol required" });
  if (!qty) return res.status(400).json({ ok: false, message: "quantity required" });
  if (!["LONG", "SHORT"].includes(posSide)) return res.status(400).json({ ok: false, message: "position_side must be LONG or SHORT" });
  await verifyPasswordAndProxyToPython(req, res, "/api/partial-close", { symbol: sym, quantity: qty, position_side: posSide });
});

// ✅ POST /api/stop-price — Frontend → server.js → Python (main_binance.setHedgeStopLoss)
app.post("/api/stop-price", async (req, res) => {
  const { symbol, position_side, stop_price } = req.body || {};
  const sym = (symbol || "").toString().trim().toUpperCase();
  const posSide = (position_side || "BOTH").toString().toUpperCase();
  const stop = (stop_price != null && stop_price !== "") ? String(stop_price).trim() : "";
  if (!sym) return res.status(400).json({ ok: false, message: "symbol required" });
  if (!stop) return res.status(400).json({ ok: false, message: "stop_price required" });
  await verifyPasswordAndProxyToPython(req, res, "/api/stop-price", { symbol: sym, position_side: posSide, stop_price: stop });
});

// ✅ GET /api/quantity-preview — no auth, proxy to Python getQuantity (for add-investment preview)
app.get("/api/quantity-preview", async (req, res) => {
  const symbol = (req.query.symbol || "").toString().trim().toUpperCase();
  const invest = req.query.invest;
  if (!symbol) return res.status(400).json({ ok: false, message: "symbol required" });
  if (invest == null || invest === "") return res.status(400).json({ ok: false, message: "invest required" });
  try {
    const resp = await fetch(`${PYTHON_SIGNALS_URL}/api/quantity-preview?symbol=${encodeURIComponent(symbol)}&invest=${encodeURIComponent(invest)}`, {
      method: "GET",
      signal: AbortSignal.timeout(10000),
    });
    const data = await resp.json().catch(() => ({}));
    res.status(resp.status || 200).json(data);
  } catch (err) {
    log(`quantity-preview proxy error: ${err.message}`, "ERROR");
    res.status(502).json({ ok: false, message: err.message || "Python signals service unavailable" });
  }
});

// ✅ POST /api/add-investment — Frontend → server.js → Python (getQuantity + HedgeModePlaceOrder)
app.post("/api/add-investment", async (req, res) => {
  const { symbol, position_side, amount } = req.body || {};
  const sym = (symbol || "").toString().trim().toUpperCase();
  const posSide = (position_side || "LONG").toString().toUpperCase();
  const amt = amount != null && amount !== "" ? String(amount).trim() : "";
  if (!sym) return res.status(400).json({ ok: false, message: "symbol required" });
  if (!amt) return res.status(400).json({ ok: false, message: "amount required" });
  await verifyPasswordAndProxyToPython(req, res, "/api/add-investment", { symbol: sym, position_side: posSide, amount: amt });
});

// ✅ API: Fetch Machines
app.get("/api/machines", async (req, res) => {
  try {
    const pool = await poolPromise;
    if (!pool) return res.json({ machines: [] });
    const result = await pool.query("SELECT machineid, active FROM machines;");
    res.json({ machines: result.rows });
  } catch (error) {
    if (isMissingTable(error)) return res.json({ machines: [] });
    console.error("❌ Query Error (/api/machines):", error.message);
    res.status(500).json({ error: error.message || "Failed to fetch machines" });
  }
});

// ✅ API: Fetch EMA Trend Data from pairstatus
// last_updated: format in UTC (to_char ... AT TIME ZONE 'UTC') so client always gets e.g. "2026-02-23T07:49:31.511850Z"
app.get("/api/pairstatus", async (req, res) => {
  try {
    const pool = await poolPromise;
    if (!pool) return res.json({});
    const result = await pool.query(`
      SELECT to_char(last_updated AT TIME ZONE 'UTC', 'YYYY-MM-DD"T"HH24:MI:SS.US"Z"') AS last_updated,
             overall_ema_trend_1m, overall_ema_trend_percentage_1m,
             overall_ema_trend_5m, overall_ema_trend_percentage_5m,
             overall_ema_trend_15m, overall_ema_trend_percentage_15m
      FROM pairstatus
      LIMIT 1;
    `);
    const row = result.rows[0] || {};
    console.log("PairStatus Deatils", row);
    res.set("Cache-Control", "no-store, no-cache, must-revalidate");
    res.json(row);
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

// ✅ Binance Proxy Endpoint (always use local/cloud server, no Render)
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
  log(`server.js STARTED | http://localhost:${PORT}`);
  log(`server.js | config: GET /api/server-info`, "INFO");
});

// ✅ 24/7 resilience: send Telegram on exit (use PM2 or run-server-24-7 for auto-restart)
process.on("uncaughtException", (err) => {
  const msg = `[server.js] CRASH uncaughtException: ${err.message}`;
  log(msg, "ERROR");
  sendTelegramSync(msg);
  process.exit(1);
});
process.on("unhandledRejection", (reason, promise) => {
  const msg = `[server.js] CRASH unhandledRejection: ${String(reason)}`;
  log(msg, "ERROR");
  sendTelegramSync(msg);
  process.exit(1);
});
process.on("SIGTERM", () => {
  const msg = `[server.js] Exiting (SIGTERM)`;
  log(msg);
  sendTelegramSync(msg);
  process.exit(0);
});
process.on("SIGINT", () => {
  const msg = `[server.js] Exiting (SIGINT)`;
  log(msg);
  sendTelegramSync(msg);
  process.exit(0);
});

const http = require("http");

// Self-ping this server (cloud local) to keep warm — gated by env
if (ENABLE_SELF_PING) {
  const pingUrl = `http://127.0.0.1:${PORT}/api/health`;
  setInterval(() => {
    http.get(pingUrl, (res) => {
      if (VERBOSE_LOG) log(`Self-ping status: ${res.statusCode}`);
    }).on("error", (err) => {
      log(`Self-ping failed: ${err.message}`, "ERROR");
    });
  }, 14 * 60 * 1000); // 14 minutes
}