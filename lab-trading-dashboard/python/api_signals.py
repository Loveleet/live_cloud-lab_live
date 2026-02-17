"""
Flask API to expose CalculateSignals(symbol, interval, candle) from FinalVersionTrading_AWS.
Run from lab-trading-dashboard/python: python api_signals.py
Set env PYTHON_SIGNALS_PORT (default 5001). Node server can proxy /api/calculate-signals to this URL.
Runs 24/7 with auto-restart on error. Sends Telegram alert if process exits.
"""
import os
import sys
import time
import json
import threading
import atexit
import asyncio

try:
    from flask import Flask, request, jsonify
except ImportError:
    raise SystemExit("Install Flask: pip install flask")


SEP = "─" * 60

def _log(msg, level="INFO"):
    ts = __import__("datetime").datetime.now(__import__("datetime").timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
    print(f"\n[{ts}] [{level}] {msg}\n{SEP}")

def _send_telegram_sync(message):
    """Send a Telegram message (sync wrapper)."""
    try:
        from telegram_message_sender import send_message_to_users
        asyncio.run(send_message_to_users(message))
    except Exception as e:
        _log(f"Could not send Telegram: {e}", "ERROR")


def kill_process_on_port(port, max_retries=3):
    """If the given port is in use, kill the process(es) using it so we can bind. Works on Windows and Ubuntu/Linux (uses psutil)."""
    try:
        import psutil
    except ImportError:
        _log("psutil not installed; if port is in use, start may fail", "WARN")
        return
    my_pid = os.getpid()
    for attempt in range(max_retries):
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
                    p.kill()
                    killed.append(pid)
                except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.Error):
                    pass
            if killed:
                _log(f"Killed process(es) on port {port}: {killed}")
                time.sleep(2)
            else:
                break
        except Exception as e:
            _log(f"Could not check/kill port {port}: {e}", "ERROR")
            break

# Import after ensuring we're in the right context (run from python/ directory)
from FinalVersionTrading_AWS import CalculateSignals_Direct_Api
import sys
import os

# Add utils directory to path to import main_binance
sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'utils'))
try:
    from utils.main_binance import getAllOpenPosition, getOpenPosition, closeOrder, close_hedge_position, setHedgeStopLoss, HedgeModePlaceOrder, getQuantity, NewOrderPlace, place_hedge_opposite, client
    from utils.Final_olab_database import olab_sync_exchange_trades
except ImportError as e:
    _log(f"Could not import main_binance or Final_olab_database: {e}", "WARN")
    getAllOpenPosition = None
    getOpenPosition = None
    closeOrder = None
    close_hedge_position = None
    setHedgeStopLoss = None
    HedgeModePlaceOrder = None
    getQuantity = None
    NewOrderPlace = None
    place_hedge_opposite = None
    client = None
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
                _log(f"calculate-signals | {symbol}: SKIPPED (already in progress)", "WARN")
                return jsonify({"ok": False, "message": f"{symbol} already being computed, retry later"}), 429
            _in_flight.add(symbol)
        try:
            _log(f"calculate-signals | {symbol}: computing 5m, 15m, 1h, 4h ...")
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

            _log(f"calculate-signals | {symbol}: OK | intervals {list(intervals.keys())}")
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
        _log("sync-open-positions | Fetching from Binance (getAllOpenPosition)...")
        positions = getAllOpenPosition()
        positions_count = len(positions) if positions else 0
        
        if not positions:
            _log("sync-open-positions | No positions from Binance, nothing to sync", "WARN")
            return jsonify({
                "ok": True,
                "message": "No open positions found",
                "positions_count": 0,
                "inserted_count": 0,
                "updated_count": 0,
                "already_existed_count": 0,
            })
        
        result = olab_sync_exchange_trades(positions)
        inserted = result["inserted_count"]
        already_existed = result.get("already_existed_count", 0)
        errs = result.get("errors", [])
        _log(
            f"sync-open-positions | OK | positions={positions_count} inserted={inserted} "
            f"already_existed={already_existed}" + (f" errors={len(errs)}" if errs else "")
        )
        if errs:
            _log(f"sync-open-positions | errors: {errs}", "ERROR")
        
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
        _log(f"sync-open-positions | Error: {error_msg}", "ERROR")
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
        _log(f"open-position | Error: {error_msg}", "ERROR")
        import traceback
        traceback.print_exc()
        return jsonify({"ok": False, "message": error_msg}), 500


@app.route("/api/execute", methods=["POST", "OPTIONS"])
def execute():
    """
    Place a new order via main_binance.NewOrderPlace(symbol, invest, stop_price, position_side).
    Body: { symbol, amount (invest in USDT), stop_price, position_side (optional, default LONG), password }.
    Flow: getQuantity -> HedgeModePlaceOrder -> setHedgeStopLoss.
    """
    if request.method == "OPTIONS":
        return "", 204
    if NewOrderPlace is None:
        return jsonify({"ok": False, "message": "NewOrderPlace not available"}), 500
    data = request.get_json(silent=True) or {}
    symbol = (data.get("symbol") or "").strip().upper()
    amount_val = data.get("amount")
    stop_price_val = data.get("stop_price")
    position_side = (data.get("position_side") or "LONG").strip().upper()
    if not symbol:
        return jsonify({"ok": False, "message": "symbol required"}), 400
    if amount_val is None or amount_val == "":
        return jsonify({"ok": False, "message": "amount required"}), 400
    if stop_price_val is None or stop_price_val == "":
        return jsonify({"ok": False, "message": "stop_price required"}), 400
    try:
        amount_float = float(amount_val)
        stop_price_float = float(stop_price_val)
    except (TypeError, ValueError):
        return jsonify({"ok": False, "message": "amount and stop_price must be numbers"}), 400
    if amount_float <= 0:
        return jsonify({"ok": False, "message": "amount must be positive"}), 400
    if position_side not in ("LONG", "SHORT"):
        return jsonify({"ok": False, "message": "position_side must be LONG or SHORT"}), 400
    result = NewOrderPlace(symbol, amount_float, stop_price_float, position_side)
    if isinstance(result, dict) and result.get("ok") is False:
        error_msg = result.get("message", "Unknown error")
        _log(f"execute | {symbol}: Error: {error_msg}", "ERROR")
        return jsonify({"ok": False, "message": error_msg}), 500
    _log(f"execute | {symbol} {position_side} invest={amount_float} stop={stop_price_float}: OK")
    return jsonify({
        "ok": True,
        "symbol": symbol,
        "position_side": position_side,
        "amount": amount_float,
        "stop_price": stop_price_float,
        "message": "Order placed",
        "order": result,
    })


@app.route("/api/hedge", methods=["POST", "OPTIONS"])
def hedge():
    """
    Place opposite hedge via main_binance.place_hedge_opposite(symbol, current_position_side, quantity).
    If opposite position already exists, returns {"ok": False, "message": "Pair already in hedge position"}.
    Body: { symbol, position_side (current: LONG or SHORT), quantity, password }.
    """
    if request.method == "OPTIONS":
        return "", 204
    if place_hedge_opposite is None:
        return jsonify({"ok": False, "message": "place_hedge_opposite not available"}), 500
    data = request.get_json(silent=True) or {}
    symbol = (data.get("symbol") or "").strip().upper()
    position_side = (data.get("position_side") or "LONG").strip().upper()
    quantity_val = data.get("quantity")
    if not symbol:
        return jsonify({"ok": False, "message": "symbol required"}), 400
    if quantity_val is None or quantity_val == "":
        return jsonify({"ok": False, "message": "quantity required"}), 400
    try:
        quantity_float = float(quantity_val)
    except (TypeError, ValueError):
        return jsonify({"ok": False, "message": "quantity must be a number"}), 400
    if quantity_float <= 0:
        return jsonify({"ok": False, "message": "quantity must be positive"}), 400
    if position_side not in ("LONG", "SHORT"):
        return jsonify({"ok": False, "message": "position_side must be LONG or SHORT"}), 400
    result = place_hedge_opposite(symbol, position_side, quantity_float)
    if isinstance(result, dict) and result.get("ok") is False:
        msg = result.get("message", "Unknown error")
        _log(f"hedge | {symbol}: {msg}", "WARN" if "already in hedge" in msg.lower() else "ERROR")
        return jsonify({"ok": False, "message": msg}), 200 if "already in hedge" in msg.lower() else 500
    _log(f"hedge | {symbol} opposite of {position_side} qty={quantity_float}: OK")
    return jsonify({
        "ok": True,
        "symbol": symbol,
        "message": result.get("message", "Hedge order placed"),
        "order": result.get("order"),
    })


@app.route("/api/close-order", methods=["GET", "POST", "OPTIONS"])
def close_order():
    """Cancel all open orders for a symbol via main_binance.closeOrder(symbol)."""
    if request.method == "OPTIONS":
        return "", 204

    if closeOrder is None:
        return jsonify({"ok": False, "message": "closeOrder not available"}), 500

    symbol = (request.args.get("symbol") or (request.get_json(silent=True) or {}).get("symbol") or "").strip().upper()
    if not symbol:
        return jsonify({"ok": False, "message": "symbol required"}), 400

    result = closeOrder(symbol)
    if isinstance(result, dict) and result.get("ok") is False:
        error_msg = result.get("message", "Unknown error")
        _log(f"close-order | {symbol}: Error: {error_msg}", "ERROR")
        return jsonify({"ok": False, "message": error_msg}), 500
    # Binance returns {"code": 200, "msg": "The operation of cancel all open order is done."} or list
    msg = (result.get("msg") if isinstance(result, dict) and result else None) or f"Open orders for {symbol} cleared"
    _log(f"close-order | {symbol}: OK | {msg}")
    return jsonify({
        "ok": True,
        "symbol": symbol,
        "message": msg,
        "orders": result if isinstance(result, (list, dict)) else [],
    })


@app.route("/api/stop-price", methods=["POST", "OPTIONS"])
def stop_price():
    """
    Set STOP_MARKET for a hedge position via main_binance.setHedgeStopLoss(symbol, stop_price, side, posSide).
    Body: { "symbol": "BTCUSDT", "position_side": "LONG"|"SHORT"|"BOTH", "stop_price": "12345.67" }.
    """
    if request.method == "OPTIONS":
        return "", 204
    if setHedgeStopLoss is None:
        return jsonify({"ok": False, "message": "setHedgeStopLoss not available"}), 500
    data = request.get_json(silent=True) or {}
    symbol = (data.get("symbol") or "").strip().upper()
    position_side = (data.get("position_side") or "BOTH").strip().upper()
    stop_price_val = data.get("stop_price")
    if not symbol:
        return jsonify({"ok": False, "message": "symbol required"}), 400
    if stop_price_val is None or stop_price_val == "":
        return jsonify({"ok": False, "message": "stop_price required"}), 400
    try:
        stop_price_float = float(stop_price_val)
    except (TypeError, ValueError):
        return jsonify({"ok": False, "message": "stop_price must be a number"}), 400
    if position_side not in ("LONG", "SHORT", "BOTH"):
        return jsonify({"ok": False, "message": "position_side must be LONG, SHORT, or BOTH"}), 400
    if position_side == "LONG":
        result = setHedgeStopLoss(symbol, stop_price_float, "SELL", "LONG")
    elif position_side == "SHORT":
        result = setHedgeStopLoss(symbol, stop_price_float, "BUY", "SHORT")
    else:
        result = setHedgeStopLoss(symbol, stop_price_float, "SELL", "LONG")
        if isinstance(result, dict) and result.get("ok") is False:
            error_msg = result.get("message", "Unknown error")
            _log(f"stop-price | {symbol} LONG: Error: {error_msg}", "ERROR")
            return jsonify({"ok": False, "message": error_msg}), 500
        result = setHedgeStopLoss(symbol, stop_price_float, "BUY", "SHORT")
    if isinstance(result, dict) and result.get("ok") is False:
        error_msg = result.get("message", "Unknown error")
        _log(f"stop-price | {symbol}: Error: {error_msg}", "ERROR")
        return jsonify({"ok": False, "message": error_msg}), 500
    _log(f"stop-price | {symbol} {position_side} @ {stop_price_float}: OK")
    return jsonify({"ok": True, "symbol": symbol, "position_side": position_side, "message": "Stop price set"})


@app.route("/api/quantity-preview", methods=["GET", "POST", "OPTIONS"])
def quantity_preview():
    """
    Compute order quantity for a given invest amount via main_binance.getQuantity(symbol, invest).
    Query or body: symbol, invest. Returns { quantity, plquantity, lastplquantity }.
    No auth required (read-only calculation).
    """
    if request.method == "OPTIONS":
        return "", 204
    if getQuantity is None:
        return jsonify({"ok": False, "message": "getQuantity not available"}), 500
    data = request.get_json(silent=True) or {}
    symbol = (data.get("symbol") or request.args.get("symbol") or "").strip().upper()
    invest_val = data.get("invest") if "invest" in data else request.args.get("invest")
    if not symbol:
        return jsonify({"ok": False, "message": "symbol required"}), 400
    if invest_val is None or invest_val == "":
        return jsonify({"ok": False, "message": "invest required"}), 400
    try:
        invest_float = float(invest_val)
    except (TypeError, ValueError):
        return jsonify({"ok": False, "message": "invest must be a number"}), 400
    if invest_float <= 0:
        return jsonify({"ok": False, "message": "invest must be positive"}), 400
    quantity, plquantity, lastplquantity = getQuantity(symbol, invest_float)
    return jsonify({
        "ok": True,
        "symbol": symbol,
        "invest": invest_float,
        "quantity": quantity,
        "plquantity": plquantity,
        "lastplquantity": lastplquantity,
    })


@app.route("/api/add-investment", methods=["POST", "OPTIONS"])
def add_investment():
    """
    Add investment to an existing hedge position via getQuantity + HedgeModePlaceOrder.
    Body: { symbol, position_side (LONG|SHORT), amount (new investment in USDT), password }.
    Flow: getQuantity(symbol, amount) -> quantity, then HedgeModePlaceOrder(symbol, side, posSide, qty).
    """
    if request.method == "OPTIONS":
        return "", 204
    if HedgeModePlaceOrder is None or getQuantity is None:
        return jsonify({"ok": False, "message": "HedgeModePlaceOrder/getQuantity not available"}), 500
    data = request.get_json(silent=True) or {}
    symbol = (data.get("symbol") or "").strip().upper()
    position_side = (data.get("position_side") or "LONG").strip().upper()
    amount_val = data.get("amount")
    if not symbol:
        return jsonify({"ok": False, "message": "symbol required"}), 400
    if amount_val is None or amount_val == "":
        return jsonify({"ok": False, "message": "amount required"}), 400
    try:
        amount_float = float(amount_val)
    except (TypeError, ValueError):
        return jsonify({"ok": False, "message": "amount must be a number"}), 400
    if amount_float <= 0:
        return jsonify({"ok": False, "message": "amount must be positive"}), 400
    if position_side not in ("LONG", "SHORT"):
        return jsonify({"ok": False, "message": "position_side must be LONG or SHORT"}), 400
    side = "BUY" if position_side == "LONG" else "SELL"
    quantity, _, _ = getQuantity(symbol, amount_float)
    if quantity is None or quantity <= 0:
        return jsonify({"ok": False, "message": "Could not compute quantity for this amount"}), 400
    result = HedgeModePlaceOrder(symbol, side, position_side, quantity)
    if isinstance(result, dict) and result.get("ok") is False:
        error_msg = result.get("message", "Unknown error")
        _log(f"add-investment | {symbol}: Error: {error_msg}", "ERROR")
        return jsonify({"ok": False, "message": error_msg}), 500
    _log(f"add-investment | {symbol} {position_side} +{amount_float} USDT qty={quantity}: OK")
    return jsonify({
        "ok": True,
        "symbol": symbol,
        "position_side": position_side,
        "amount": amount_float,
        "quantity": quantity,
        "message": "Investment added",
        "order": result,
    })


@app.route("/api/end-trade", methods=["POST", "OPTIONS"])
def end_trade():
    """
    Close hedge position(s) via main_binance.close_hedge_position(symbol, position_side, quantity).
    Body: { "symbol": "BTCUSDT", "position_side": "LONG"|"SHORT"|"BOTH", "quantity": optional number }.
    """
    if request.method == "OPTIONS":
        return "", 204
    data = request.get_json(silent=True) or {}
    symbol = (data.get("symbol") or request.args.get("symbol") or "").strip().upper()
    position_side = (data.get("position_side") or "BOTH").strip().upper()
    quantity = data.get("quantity")

    print(f"end-trade | {symbol} {position_side} qty={quantity}")
    return jsonify({"ok": False, "message": "symbol required"}), 400
    # if quantity is not None:
    #     try:
    #         quantity = float(quantity)
    #         if quantity <= 0:
    #             quantity = None
    #     except (TypeError, ValueError):
    #         quantity = None
    # if not symbol:
    #     return jsonify({"ok": False, "message": "symbol required"}), 400
    # if position_side not in ("LONG", "SHORT", "BOTH"):
    #     return jsonify({"ok": False, "message": "position_side must be LONG, SHORT, or BOTH"}), 400
    # if close_hedge_position is None:
    #     return jsonify({"ok": False, "message": "close_hedge_position not available"}), 500
    # try:
    #     results = []
    #     if position_side == "BOTH":
    #         for side in ("LONG", "SHORT"):
    #             out = close_hedge_position(symbol, side, quantity)
    #             results.append({"positionSide": side, "result": out})
    #     else:
    #         out = close_hedge_position(symbol, position_side, quantity)
    #         results.append({"positionSide": position_side, "result": out})
    #     _log(f"end-trade | {symbol} {position_side} qty={quantity}: {results}")
    #     return jsonify({
    #         "ok": True,
    #         "symbol": symbol,
    #         "position_side": position_side,
    #         "message": f"Closed {position_side} position(s) for {symbol}",
    #         "closed": results,
    #     })
    # except Exception as e:
    #     error_msg = str(e)
    #     _log(f"end-trade | {symbol}: Error: {error_msg}", "ERROR")
    #     return jsonify({"ok": False, "message": error_msg}), 500


if __name__ == "__main__":
    port = int(os.environ.get("PYTHON_SIGNALS_PORT", "5001"))
    _exit_reason = [None]

    def _on_exit():
        reason = _exit_reason[0] or "unknown"
        msg = f"⚠️ api_signals.py EXITED\nPort: {port}\nReason: {reason}"
        _log(f"api_signals EXITING: {reason}")
        _send_telegram_sync(msg)

    atexit.register(_on_exit)

    while True:
        try:
            kill_process_on_port(port)
            _log(f"api_signals STARTED | port={port} | POST /api/calculate-signals | intervals {list(SIGNALS_INTERVALS)}")
            app.run(host="0.0.0.0", port=port, threaded=True)
        except KeyboardInterrupt:
            _exit_reason[0] = "KeyboardInterrupt (Ctrl+C)"
            sys.exit(0)
        except Exception as e:
            err_msg = str(e)
            _exit_reason[0] = err_msg
            _log(f"api_signals CRASHED: {err_msg}", "ERROR")
            _send_telegram_sync(f"⚠️ api_signals.py CRASHED\nPort: {port}\nError: {err_msg}\nRestarting in 10s...")
            time.sleep(10)
            _exit_reason[0] = None
