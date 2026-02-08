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


if __name__ == "__main__":
    port = int(os.environ.get("PYTHON_SIGNALS_PORT", "5001"))
    kill_process_on_port(port)
    print(f"Starting signals API on port {port}. POST /api/calculate-signals with {{ symbol, candle? }}")
    print(f"Returns intervals: {list(SIGNALS_INTERVALS)} (5m, 15m, 1h, 4h)")
    app.run(host="0.0.0.0", port=port, threaded=True)
