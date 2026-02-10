"""
Flask API to expose CalculateSignals(symbol, interval, candle) from FinalVersionTrading_AWS.
Run from lab-trading-dashboard/python: python api_signals.py
Set env PYTHON_SIGNALS_PORT (default 5001). Node server can proxy /api/calculate-signals to this URL.
"""
import os
import time
import json
import threading

try:
    from flask import Flask, request, jsonify
except ImportError:
    raise SystemExit("Install Flask: pip install flask")


def kill_process_on_port(port):
    """If the given port is in use, kill the process(es) using it so we can bind. Works on Windows and Ubuntu/Linux (uses psutil)."""
    try:
        import psutil
    except ImportError:
        print(f"[startup] psutil not installed; if port {port} is in use, start may fail.")
        return
    my_pid = os.getpid()
    killed = []
    try:
        for conn in psutil.net_connections():
            if conn.status != "LISTEN":
                continue
            try:
                if getattr(conn, "laddr", None) is None or conn.laddr.port != port:
                    continue
            except Exception:
                continue
            pid = conn.pid
            if pid is None or pid == my_pid:
                continue
            try:
                p = psutil.Process(pid)
                p.terminate()
                killed.append(pid)
            except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.Error):
                pass
        if killed:
            print(f"[startup] Killed process(es) on port {port}: {killed}")
            time.sleep(1.5)
    except Exception as e:
        print(f"[startup] Could not check/kill port {port}: {e}")

# Import after ensuring we're in the right context (run from python/ directory)
from FinalVersionTrading_AWS import CalculateSignals_Direct_Api
import sys
import os

# Add utils directory to path to import main_binance
sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'utils'))
try:
    from utils.main_binance import getAllOpenPosition, getOpenPosition
    from utils.Final_olab_database import olab_sync_exchange_trades
except ImportError as e:
    print(f"⚠️ Warning: Could not import getAllOpenPosition, getOpenPosition or olab_sync_exchange_trades: {e}")
    getAllOpenPosition = None
    getOpenPosition = None
    olab_sync_exchange_trades = None

app = Flask(__name__)

# Deduplicate: don't run the same symbol while it's already being computed
_in_flight = set()
_in_flight_lock = threading.Lock()

# CORS for local/dev (Node proxy avoids CORS in production)
@app.after_request
def cors_headers(resp):
    resp.headers["Access-Control-Allow-Origin"] = "*"
    resp.headers["Access-Control-Allow-Methods"] = "GET, POST, OPTIONS"
    resp.headers["Access-Control-Allow-Headers"] = "Content-Type"
    return resp


SIGNALS_INTERVALS = ("5m", "15m", "1h", "4h")


def _df_row_to_json(summary):
    """Convert one row dict to JSON-serializable types."""
    if not summary:
        return summary
    for k, v in list(summary.items()):
        if v is None or (hasattr(v, "__float__") and isinstance(v, float) and v != v):
            summary[k] = None
        elif hasattr(v, "item"):
            summary[k] = v.item()
        elif hasattr(v, "isoformat"):
            summary[k] = v.isoformat()
        elif hasattr(v, "tolist"):
            summary[k] = v.tolist()
    return summary


@app.route("/api/calculate-signals", methods=["POST", "OPTIONS"])
def calculate_signals():
    if request.method == "OPTIONS":
        return "", 204
    try:
        body = request.get_json(force=True, silent=True) or {}
        symbol = (body.get("symbol") or "").strip().upper()
        if not symbol:
            return jsonify({"ok": False, "message": "Missing or empty symbol"}), 400
        candle = (body.get("candle") or "regular").strip()

        with _in_flight_lock:
            if symbol in _in_flight:
                print(f"[calculate-signals] {symbol}: skipped (already in progress)")
                return jsonify({"ok": False, "message": f"{symbol} already being computed, retry later"}), 429
            _in_flight.add(symbol)
        try:
            # Run CalculateSignals for 5m, 15m, 1h, 4h and send each result to server
            print(f"[calculate-signals] {symbol}: computing 5m, 15m, 1h, 4h ...")
            intervals = {}
            for interval in SIGNALS_INTERVALS:
                df = CalculateSignals_Direct_Api(symbol, interval, candle=candle)
                if df is None or df.empty:
                    intervals[interval] = {"ok": False, "summary": None, "error": "No data"}
                    continue
                try:
                    # Last 3 rows, full dataframe columns for each
                    last_3 = df.iloc[-3:]
                    rows = last_3.to_dict(orient="records")
                    rows_serializable = [_df_row_to_json(dict(row)) for row in rows]
                    intervals[interval] = {"ok": True, "summary": rows_serializable}
                except Exception as e:
                    intervals[interval] = {"ok": False, "summary": None, "error": str(e)}

            print(f"[calculate-signals] {symbol}: returning intervals {list(intervals.keys())}")
            return jsonify({
                "ok": True,
                "symbol": symbol,
                "intervals": intervals,
            })
        finally:
            with _in_flight_lock:
                _in_flight.discard(symbol)
    except Exception as e:
        with _in_flight_lock:
            try:
                _in_flight.discard(symbol)
            except NameError:
                pass
        return jsonify({"ok": False, "message": str(e)}), 500


@app.route("/api/calculate-signals/health", methods=["GET"])
def health():
    return jsonify({"ok": True, "service": "calculate-signals"})


@app.route("/api/sync-open-positions", methods=["GET", "POST", "OPTIONS"])
def sync_open_positions():
    """Sync open positions from Binance to exchange_trade table."""
    if request.method == "OPTIONS":
        return "", 204
    
    if getAllOpenPosition is None or olab_sync_exchange_trades is None:
        return jsonify({
            "ok": False,
            "message": "getAllOpenPosition or olab_sync_exchange_trades not available"
        }), 500
    
    try:
        print("[sync-open-positions] Fetching open positions from Binance (getAllOpenPosition)...")
        positions = getAllOpenPosition()
        positions_count = len(positions) if positions else 0
        
        print(f"[sync-open-positions] DEBUG: getAllOpenPosition returned {positions_count} positions")
        
        if not positions:
            print("[sync-open-positions] DEBUG: No data from getAllOpenPosition, nothing to sync")
            return jsonify({
                "ok": True,
                "message": "No open positions found",
                "positions_count": 0,
                "inserted_count": 0,
                "updated_count": 0,
                "already_existed_count": 0,
            })
        
        print(f"[sync-open-positions] Syncing {positions_count} positions to exchange_trade...")
        result = olab_sync_exchange_trades(positions)
        
        inserted = result["inserted_count"]
        already_existed = result.get("already_existed_count", 0)
        print(f"[sync-open-positions] DEBUG: data from getAllOpenPosition = {positions_count}")
        print(f"[sync-open-positions] DEBUG: already existed in exchange_trade (skipped) = {already_existed}")
        print(f"[sync-open-positions] DEBUG: insert success count = {inserted}")
        if result.get("errors"):
            print(f"[sync-open-positions] DEBUG: errors = {result['errors']}")
        
        return jsonify({
            "ok": True,
            "message": f"Synced {inserted} positions",
            "positions_count": positions_count,
            "inserted_count": inserted,
            "updated_count": result["updated_count"],
            "already_existed_count": already_existed,
            "hedge_trades": result.get("hedge_trades", 0),
            "errors": result.get("errors", [])
        })
        
    except Exception as e:
        error_msg = str(e)
        print(f"[sync-open-positions] Error: {error_msg}")
        import traceback
        traceback.print_exc()
        return jsonify({
            "ok": False,
            "message": error_msg
        }), 500


@app.route("/api/open-position", methods=["GET", "OPTIONS"])
def open_position():
    """Return open position(s) for a symbol from Binance via getOpenPosition(symbol)."""
    if request.method == "OPTIONS":
        return "", 204

    if getOpenPosition is None:
        return jsonify({"ok": False, "message": "getOpenPosition not available"}), 500

    symbol = (request.args.get("symbol") or (request.get_json(silent=True) or {}).get("symbol") or "").strip().upper()
    if not symbol:
        return jsonify({"ok": False, "message": "symbol query param required"}), 400

    try:
        positions = getOpenPosition(symbol)
        if positions is None:
            positions = []
        return jsonify({"ok": True, "symbol": symbol, "positions": positions or []})
    except Exception as e:
        error_msg = str(e)
        print(f"[open-position] Error: {error_msg}")
        import traceback
        traceback.print_exc()
        return jsonify({"ok": False, "message": error_msg}), 500


if __name__ == "__main__":
    port = int(os.environ.get("PYTHON_SIGNALS_PORT", "5001"))
    kill_process_on_port(port)
    print(f"Starting signals API on port {port}. POST /api/calculate-signals with {{ symbol, candle? }}")
    print(f"Returns intervals: {list(SIGNALS_INTERVALS)} (5m, 15m, 1h, 4h)")
    app.run(host="0.0.0.0", port=port, threaded=True)
