"""
Binance USDT-M Futures (UMFutures) helpers: orders, positions, balance, market data.
All UMFutures calls are wrapped with retry (3 attempts, 5s delay), try/except,
file logging, and optional Telegram alerts on critical errors.
"""
import threading
import platform
import os
import sys
import traceback
from time import sleep
from datetime import datetime, timezone

# Optional text-to-speech dependency. We don't actually need this for
# Binance open-position / trading logic, so if it's missing we just
# disable voice features instead of breaking all imports.
try:
    import pyttsx3  # type: ignore
except ImportError:
    pyttsx3 = None  # Voice/TTS features will be disabled

# pythoncom is Windows-specific, handle it conditionally
if platform.system() == 'Windows':
    import pythoncom
else:
    # Linux/macOS fallback - create dummy pythoncom with no-op methods
    class pythoncom:
        @staticmethod
        def CoInitialize():
            pass

        @staticmethod
        def CoUninitialize():
            pass

from keys1 import api, secret
from binance.um_futures import UMFutures
import time
from binance.error import ClientError
import datetime
import logging
import numpy as np
import talib
import pandas as pd
import ta
from openpyxl import load_workbook
import functools

# colorama is only used for pretty terminal colors. If it's not installed,
# we fall back to plain strings so that Binance helpers still work.
try:
    from colorama import init, Fore, Style  # type: ignore
except ImportError:
    def init(*args, **kwargs):
        return None

    class _DummyColor:
        def __getattr__(self, name):
            return ""

    Fore = _DummyColor()
    Style = _DummyColor()

# -----------------------------------------------------------------------------
# Retry and logging constants
# -----------------------------------------------------------------------------
MAX_RETRY_COUNT = 3
RETRY_DELAY_SEC = 5
ERROR = -1

# -----------------------------------------------------------------------------
# File logger for main_binance errors (saved to log file)
# -----------------------------------------------------------------------------
_MAIN_BINANCE_LOG_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "logs")
os.makedirs(_MAIN_BINANCE_LOG_DIR, exist_ok=True)
_MAIN_BINANCE_LOG_FILE = os.path.join(_MAIN_BINANCE_LOG_DIR, "main_binance_errors.log")


def _log_error(message, critical=False, exc=None):
    """Write error to main_binance_errors.log. If critical, also send Telegram."""
    ts = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
    line = f"[{ts}] {'CRITICAL' if critical else 'ERROR'} - {message}\n"
    if exc and getattr(exc, "__traceback__", None):
        line += traceback.format_exc() + "\n"
    try:
        with open(_MAIN_BINANCE_LOG_FILE, "a", encoding="utf-8") as f:
            f.write(line)
    except Exception as e:
        print(f"Failed to write log file: {e}")
    if critical:
        _send_telegram_critical(message, exc)


def _send_telegram_critical(message, exc=None):
    """Send a critical error message via Telegram (non-blocking best effort)."""
    try:
        _python_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        if _python_dir not in sys.path:
            sys.path.insert(0, _python_dir)
        from telegram_message_sender import send_message_to_users
        import asyncio
        text = f"🚨 main_binance CRITICAL: {message}"
        if exc:
            text += f"\n{str(exc)}"
        asyncio.run(send_message_to_users(text))
    except Exception as e:
        try:
            with open(_MAIN_BINANCE_LOG_FILE, "a", encoding="utf-8") as f:
                f.write(f"[{datetime.now(timezone.utc)}] Failed to send Telegram: {e}\n")
        except Exception:
            pass


def retry_um_futures(critical_on_final_failure=True):
    """
    Decorator: retry UMFutures calls up to MAX_RETRY_COUNT times with RETRY_DELAY_SEC delay.
    On each failure, log to file; on final failure and if critical_on_final_failure, send Telegram.
    """
    def decorator(func):
        @functools.wraps(func)
        def wrapper(*args, **kwargs):
            last_exc = None
            for attempt in range(MAX_RETRY_COUNT):
                try:
                    return func(*args, **kwargs)
                except Exception as e:
                    last_exc = e
                    _log_error(
                        f"{func.__name__} attempt {attempt + 1}/{MAX_RETRY_COUNT} failed: {e}",
                        critical=False,
                        exc=e,
                    )
                    if attempt < MAX_RETRY_COUNT - 1:
                        time.sleep(RETRY_DELAY_SEC)
            if critical_on_final_failure and last_exc is not None:
                _log_error(
                    f"{func.__name__} failed after {MAX_RETRY_COUNT} attempts: {last_exc}",
                    critical=True,
                    exc=last_exc,
                )
            raise last_exc
        return wrapper
    return decorator


init(autoreset=True)

try:
    # client = UMFutures(key=api, secret=secret, base_url="https://testnet.binancefuture.com")
    client = UMFutures(key=api, secret=secret)
    volume = 50  # volume for one order (if 10 and leverage 10, then 1 USDT per position)
    sl = 0.006
    tp = 0.003

    # -------------------------------------------------------------------------
    # Market / account info
    # -------------------------------------------------------------------------

    @retry_um_futures(critical_on_final_failure=False)
    def get_tickers_usdt():
        """
        Fetch all USDT-margined futures symbols from Binance.
        Returns a list of symbol strings (e.g. ['BTCUSDT', 'ETHUSDT', ...]).
        """
        tickers = []
        try:
            resp = client.ticker_price()
            for elem in resp:
                if 'USDT' in elem['symbol']:
                    tickers.append(elem['symbol'])
            return tickers
        except Exception as e:
            _log_error(f"get_tickers_usdt: {e}", exc=e)
            return tickers

    @retry_um_futures(critical_on_final_failure=False)
    def get_avail_balance():
        """
        Get available USDT balance for the futures account.
        Returns float (0.0 if not found or on error).
        """
        availableBalance = 0.0
        try:
            balances = client.balance()
            for asset_info in balances:
                if asset_info['asset'] == 'USDT':
                    availableBalance = float(asset_info['availableBalance'])
                    print(Fore.LIGHTMAGENTA_EX + f' (Available Balance ==> {availableBalance}' + Style.RESET_ALL)
                    break
            return availableBalance
        except Exception as e:
            _log_error(f"get_avail_balance: {e}", exc=e)
            return availableBalance

    @retry_um_futures(critical_on_final_failure=False)
    def get_price_precision(symbol):
        """
        Get price precision (decimal places) for a symbol from exchange info.
        E.g. BTC has 1, XRP has 4. Returns None on error.
        """
        try:
            resp = client.exchange_info()['symbols']
            for elem in resp:
                if elem['symbol'] == symbol:
                    return elem['pricePrecision']
            return None
        except Exception as e:
            _log_error(f"get_price_precision({symbol}): {e}", exc=e)
            return None

    @retry_um_futures(critical_on_final_failure=False)
    def get_qty_precision(symbol):
        """
        Get quantity precision (decimal places) for a symbol from exchange info.
        E.g. BTC has 3, XRP has 1. Returns None on error.
        """
        try:
            resp = client.exchange_info()['symbols']
            for elem in resp:
                if elem['symbol'] == symbol:
                    return elem['quantityPrecision']
            return None
        except Exception as e:
            _log_error(f"get_qty_precision({symbol}): {e}", exc=e)
            return None

    # -------------------------------------------------------------------------
    # Position / order execution
    # -------------------------------------------------------------------------
    #
    # HEDGE MODE (dualSidePosition=True):
    #   - Enable: um_change_position_mode("true")  # API expects string "true"/"false"
    #   - Open LONG:  side='BUY',  positionSide='LONG',  quantity=qty
    #   - Open SHORT: side='SELL', positionSide='SHORT', quantity=qty
    #   - Close LONG:  side='SELL', positionSide='LONG',  quantity=abs(positionAmt) or closePosition='true'
    #   - Close SHORT: side='BUY',  positionSide='SHORT', quantity=abs(positionAmt) or closePosition='true'
    #   - You must pass positionSide on every order when in hedge mode.
    #

    def open_hedge_position(symbol, position_side, quantity):
        """
        Open a hedge-mode position: LONG or SHORT only.
        position_side: 'LONG' or 'SHORT'.
        LONG  -> side='BUY',  positionSide='LONG'
        SHORT -> side='SELL', positionSide='SHORT'
        """
        side = 'BUY' if position_side.upper() == 'LONG' else 'SELL'
        return hedgePosition(symbol, side, position_side.upper(), quantity)

    @retry_um_futures(critical_on_final_failure=True)
    def close_hedge_position(symbol, position_side, quantity=None):
        """
        Close one side of a hedge (dual-side) position: LONG or SHORT.

        - If quantity is None: closes FULL open qty for that side by reading position risk.
        - In hedge mode, closing is done by side+positionSide (reduceOnly is not allowed by Binance).
        - Returns status dict when no position or already closed; otherwise returns order response.
        """
        try:
            pos_side = position_side.upper()
            if pos_side not in ("LONG", "SHORT"):
                raise ValueError("position_side must be 'LONG' or 'SHORT'")

            close_side = "SELL" if pos_side == "LONG" else "BUY"

            # If qty not provided, read current open qty for that leg (Binance uses get_position_risk)
            if quantity is None:
                pos_list = client.get_position_risk(symbol=symbol)
                leg = next((p for p in pos_list if p.get("positionSide") == pos_side), None)
                if not leg:
                    return {"status": "no_position_info", "symbol": symbol, "positionSide": pos_side}

                amt = float(leg.get("positionAmt", 0.0))
                # LONG is >0, SHORT is <0
                quantity = abs(amt)

            if quantity is None or float(quantity) <= 0:
                return {"status": "already_closed", "symbol": symbol, "positionSide": pos_side}

            return client.new_order(
                symbol=symbol,
                side=close_side,
                positionSide=pos_side,
                type="MARKET",
                quantity=quantity,
            )
        except ValueError:
            raise
        except Exception as e:
            _log_error(f"close_hedge_position({symbol} {position_side}): {e}", critical=True, exc=e)
            return {"ok": False, "message": str(e)}

    @retry_um_futures(critical_on_final_failure=True)
    def closeAllHedgePosition(symbol):
        """
        Close both LONG and SHORT hedge positions for a symbol by placing market
        orders to flatten each side. Only runs when exactly 2 open positions (LONG + SHORT).
        """
        try:
            openHedgePosition = getOpenPosition(symbol)
            if len(openHedgePosition) != 2:
                return
            print(Fore.YELLOW + f'-----------------------------------------------------------------' + Style.RESET_ALL)
            print(Fore.CYAN + f'{openHedgePosition}' + Style.RESET_ALL)
            print(Fore.YELLOW + f'-----------------------------------------------------------------' + Style.RESET_ALL)
            for each in openHedgePosition:
                qty_order = float(each['positionAmt'])
                print(Fore.YELLOW + f'--------------------------We are inside for loop {qty_order}---------------------------------------' + Style.RESET_ALL)
                print(Fore.CYAN + f'openHedgePosition' + Style.RESET_ALL)
                print(Fore.YELLOW + f'-------------------------{each}----------------------------------------' + Style.RESET_ALL)
                if qty_order < 0:
                    order = client.new_order(symbol=symbol, side='BUY', positionSide='SHORT', type='MARKET', quantity=abs(qty_order))
                    print(Fore.YELLOW + f'Close Postion For SELL :: {order}' + Style.RESET_ALL)
                elif qty_order > 0:
                    order = client.new_order(symbol=symbol, side='SELL', positionSide='LONG', type='MARKET', quantity=abs(qty_order))
                    print(Fore.RED + f'Close Postion For Buy :: {order}' + Style.RESET_ALL)
        except Exception as e:
            _log_error(f"closeAllHedgePosition({symbol}): {e}", critical=True, exc=e)
            return {"ok": False, "message": str(e)}

    def calculateProfitBasedOnPercentage(side, symbol, profitPercentage):
        """
        Compute take-profit price from current entry and a percentage.
        BUY: entry + (entry * pct). SELL: entry - (entry * pct).
        Returns 0 if side is neither BUY nor SELL.
        """
        try:
            price_precision = get_price_precision(symbol)
            entryPrice = getEntryPrice(symbol)
            if price_precision is None:
                return 0
            if side == 'BUY':
                return round(entryPrice + (entryPrice * profitPercentage), price_precision)
            elif side == 'SELL':
                return round(entryPrice - (entryPrice * profitPercentage), price_precision)
            return 0
        except Exception as e:
            _log_error(f"calculateProfitBasedOnPercentage({symbol}): {e}", exc=e)
            return 0

    def open_order(symbol, side, invest, stop_price):
        """
        Place a market order (BUY or SELL) for symbol with invest amount, set take-profit
        orders (two levels), and optionally stop-loss. Returns 1 on success, -1 on client error.
        """
        try:
            current_price = float(client.ticker_price(symbol)['price'])
            price_precision = get_price_precision(symbol)
            qty, plquantity, lastplqty = getQuantity(symbol, invest)
            if price_precision is None:
                _log_error(f"open_order({symbol}): no price precision", exc=None)
                return -1
            if side == 'BUY':
                stop_price = round(stop_price, price_precision)
                take_profit_price = round(current_price + (current_price * tp), price_precision)
                second_take_profit_price = round(take_profit_price + (take_profit_price * (tp * 1.5)), price_precision)
                print(Fore.GREEN + f'Placing Order For {symbol}' + Style.RESET_ALL)
                print(Fore.LIGHTGREEN_EX + f'Current Price => {current_price}' + Style.RESET_ALL)
                print(Fore.LIGHTGREEN_EX + f'Quamtity => {qty}' + Style.RESET_ALL)
                print(Fore.LIGHTGREEN_EX + f'Stop Price => {stop_price}' + Style.RESET_ALL)
                print(Fore.LIGHTGREEN_EX + f'Profit Price => {take_profit_price}' + Style.RESET_ALL)
                resp1 = PlaceOrder(symbol, 'BUY', qty)
                print("\033[92mPlacing Order Response:", resp1, "\033[0m")
                setProfit(symbol, take_profit_price, 'SELL', plquantity)
                setProfit(symbol, second_take_profit_price, 'SELL', lastplqty)
                return 1
            if side == 'SELL':
                stop_price = round(stop_price, price_precision)
                take_profit_price = round(current_price - current_price * tp, price_precision)
                second_take_profit_price = round(take_profit_price - take_profit_price * (tp * 1.5), price_precision)
                print(Fore.RED + f'Placing Order For {symbol}' + Style.RESET_ALL)
                print(Fore.LIGHTRED_EX + f'Current Price => {current_price}' + Style.RESET_ALL)
                print(Fore.LIGHTRED_EX + f'Quamtity => {qty}' + Style.RESET_ALL)
                print(Fore.LIGHTRED_EX + f'Stop Price => {stop_price}' + Style.RESET_ALL)
                print(Fore.LIGHTRED_EX + f'Profit Price => {take_profit_price}' + Style.RESET_ALL)
                resp1 = PlaceOrder(symbol, 'SELL', qty)
                print("\033[92mPlacing Order Response:", resp1, "\033[0m")
                setProfit(symbol, take_profit_price, 'BUY', plquantity)
                setProfit(symbol, second_take_profit_price, 'BUY', lastplqty)
                return 1
            sleep(3)
            return -1
        except ClientError as error:
            _log_error(
                f"open_order ClientError status={error.status_code} code={error.error_code} msg={error.error_message}",
                critical=True,
                exc=error,
            )
            print("Found error. status: {}, error code: {}, error message: {}".format(
                error.status_code, error.error_code, error.error_message))
            return -1
        except Exception as e:
            _log_error(f"open_order({symbol}): {e}", critical=True, exc=e)
            return -1

    @retry_um_futures(critical_on_final_failure=True)
    def PlaceOrder(symbol, side, qty):
        """
        Place a single market order (BUY or SELL) for the given symbol and quantity.
        Returns the order response dict from Binance.
        """
        try:
            result = client.new_order(symbol=symbol, side=side, type='MARKET', quantity=qty,recvWindow=5000)
            return result
        except Exception as e:
            _log_error(f"BUYOrder({symbol} {side} {qty}): {e}", critical=True, exc=e)
            return {"ok": False, "message": str(e)}

    @retry_um_futures(critical_on_final_failure=True)
    def HedgeModePlaceOrder(symbol, side, posSide, qty):
        """
        Place a single market order (BUY or SELL) for the given symbol and quantity.
        Returns the order response dict from Binance.
        """
        try:
            return {"ok": False, "message": f'Place Order Not Implemented {symbol} {side} {posSide} {qty}'}
            # output= client.new_order(symbol=symbol, side=side,positionSide=posSide, type='MARKET', quantity=qty,recvWindow=5000)
            # return output
        except Exception as e:
            _log_error(f"HedgeModePlaceOrder({symbol} {side} {posSide} {qty}): {e}", critical=True, exc=e)
            return {"ok": False, "message": str(e)}

    @retry_um_futures(critical_on_final_failure=True)
    def setStopLoss(symbol, stop_price, side, qty):
        """
        Attach a STOP_MARKET order to close the full position at stop_price.
        Uses closePosition='true' so quantity is not required.
        """
        try:
            resp2 = client.new_order(symbol=symbol, side=side, type='STOP_MARKET', stopPrice=stop_price, closePosition='true')
            print("\033[93mStop Loss:", resp2, "\033[0m")
        except Exception as e:
            _log_error(f"setStopLoss({symbol}): {e}", critical=True, exc=e)
            return {"ok": False, "message": str(e)}

    @retry_um_futures(critical_on_final_failure=True)
    def setProfit(symbol, take_profit_price, side, qty):
        """
        Attach a TAKE_PROFIT_MARKET order to close the full position at take_profit_price.
        Uses closePosition='true'.
        """
        try:
            resp3 = client.new_order(symbol=symbol, side=side, type='TAKE_PROFIT_MARKET', stopPrice=take_profit_price, closePosition='true')
            print("\033[94mTake Profit:", resp3, "\033[0m")
            time.sleep(3)
        except Exception as e:
            _log_error(f"setProfit({symbol}): {e}", critical=True, exc=e)
            return {"ok": False, "message": str(e)}

    @retry_um_futures(critical_on_final_failure=True)
    def setHedgeProfit(symbol, take_profit_price, side, posSide):
        """
        Set take-profit for a hedge position (LONG or SHORT) by position side.
        """
        try:
            price_precision = get_price_precision(symbol)
            take_profit_price = round(take_profit_price, price_precision)
            resp3 = client.new_order(symbol=symbol, side=side, positionSide=posSide, type='TAKE_PROFIT_MARKET', stopPrice=take_profit_price, closePosition='true')
            print("\033[94mTake Profit:", resp3, "\033[0m")
            time.sleep(3)
        except Exception as e:
            _log_error(f"setHedgeProfit({symbol}): {e}", critical=True, exc=e)
            return {"ok": False, "message": str(e)}

    @retry_um_futures(critical_on_final_failure=True)
    def setHedgeStopLoss(symbol, stop_price, side, posSide):
        """
        Cancel open orders for symbol then set STOP_MARKET to close the hedge position at stop_price.
        """
        try:
            return {"ok": False, "message": f'Stop Price {stop_price} not set for {symbol}'}
            # closeOrder(symbol)
            # price_precision = get_price_precision(symbol)
            # stop_price = round(stop_price, price_precision)
            # resp3 = client.new_order(symbol=symbol, side=side, positionSide=posSide, type='STOP_MARKET', stopPrice=stop_price, closePosition='true')
            # print("\033[94mStop Loss:", resp3, "\033[0m")
            # time.sleep(3)
        except Exception as e:
            _log_error(f"setHedgeStopLoss({symbol}): {e}", critical=True, exc=e)
            return {"ok": False, "message": str(e)}

    @retry_um_futures(critical_on_final_failure=True)
    def setHedgePartialStopLoss(symbol, stop_price, side, posSide, quantity):
        """
        Cancel open orders then set a partial STOP_MARKET for the given quantity (closePosition='false').
        """
        try:
            closeOrder(symbol)
            price_precision = get_price_precision(symbol)
            stop_price = round(stop_price, price_precision)
            resp3 = client.new_order(symbol=symbol, side=side, positionSide=posSide, quantity=quantity, type='STOP_MARKET', stopPrice=stop_price, workingType='MARK_PRICE', closePosition='false')
            print("\033[94mStop Loss:", resp3, "\033[0m")
            time.sleep(3)
        except Exception as e:
            _log_error(f"setHedgePartialStopLoss({symbol}): {e}", critical=True, exc=e)
            return {"ok": False, "message": str(e)}

    @retry_um_futures(critical_on_final_failure=True)
    def hedgePosition(symbol, side, posSide, qty):
        """
        Open a hedge position: market order for the given side and position side (LONG/SHORT).
        Returns order response dict on success, or {"ok": False, "message": "..."} on error.
        """
        try:

             return {"ok": False, "message": "Hedge Position Not Implemented"}
            # resp2 = client.new_order(symbol=symbol, side=side, positionSide=posSide, type='MARKET', quantity=qty)
            # print("\033[93mHedge order:", resp2, "\033[0m")
            # return resp2
        except Exception as e:
            _log_error(f"hedgePosition({symbol}): {e}", critical=True, exc=e)
            return {"ok": False, "message": str(e)}

    def place_hedge_opposite(symbol, current_position_side, quantity):
        """
        If opposite position already exists for symbol, return {"ok": False, "message": "Pair already in hedge position"}.
        Otherwise place opposite hedge via open_hedge_position and return {"ok": True, "order": result, "message": "..."}.
        current_position_side: 'LONG' or 'SHORT' (the side we already have).
        quantity: size to open for the opposite side.
        """
        try:
            pos_list = getOpenPosition(symbol)
            if pos_list is None:
                pos_list = []
            opposite = 'SHORT' if current_position_side.upper() == 'LONG' else 'LONG'
            for p in pos_list:
                if (p.get('positionSide') or '').upper() == opposite:
                    amt = float(p.get('positionAmt', 0.0))
                    if abs(amt) > 0:
                        return {"ok": False, "message": "Pair already in hedge position"}
            qty_f = float(quantity)
            if qty_f <= 0:
                return {"ok": False, "message": "Quantity must be positive"}
            result = open_hedge_position(symbol, opposite, qty_f)
            if isinstance(result, dict) and result.get('ok') is False:
                return result
            return {"ok": True, "order": result, "message": f"Hedge order placed: {opposite} {qty_f}"}
        except Exception as e:
            _log_error(f"place_hedge_opposite({symbol}): {e}", critical=True, exc=e)
            return {"ok": False, "message": str(e)}

    def NewOrderPlace(symbol, invest, stop_price, position_side='LONG'):
        """
        Place a new hedge order: getQuantity(symbol, invest) -> quantity, then HedgeModePlaceOrder,
        then setHedgeStopLoss for the position. position_side is LONG or SHORT.
        Returns order response dict or {"ok": False, "message": "..."} on error.
        """
        return {"ok": False, "message": f'NewOrderPlace Not Implemented {symbol} {invest} {stop_price} {position_side}'}
        # quantity, _, _ = getQuantity(symbol, float(invest))
        # if quantity is None or quantity <= 0:
        #     return {"ok": False, "message": "Could not compute quantity for this investment"}
        # pos_side = (position_side or 'LONG').upper()
        # if pos_side not in ('LONG', 'SHORT'):
        #     return {"ok": False, "message": "position_side must be LONG or SHORT"}
        # side = 'BUY' if pos_side == 'LONG' else 'SELL'
        # order_out = HedgeModePlaceOrder(symbol, side, pos_side, quantity)
        # if isinstance(order_out, dict) and order_out.get('ok') is False:
        #     return order_out
        # close_side = 'SELL' if pos_side == 'LONG' else 'BUY'
        # try:
        #     stop_price_f = float(stop_price)
        # except (TypeError, ValueError):
        #     return {"ok": False, "message": "stop_price must be a number"}
        # sl_out = setHedgeStopLoss(symbol, stop_price_f, close_side, pos_side)
        # if isinstance(sl_out, dict) and sl_out.get('ok') is False:
        #     _log_error(f"NewOrderPlace setHedgeStopLoss({symbol}): {sl_out.get('message', '')}", critical=False)
        #     # Order was placed; return success but caller may see stop-loss as failed if needed
        # return order_out if isinstance(order_out, dict) else {"ok": True, "order": order_out}

    @retry_um_futures(critical_on_final_failure=True)
    def closeOrder(symbol):
        """
        Cancel all open orders for the given symbol (e.g. TP/SL orders).
        On success returns Binance response (list/dict). On exception logs and returns
        {"ok": False, "message": "<error>"} instead of raising.
        """
        try:
            # orders = client.cancel_open_orders(symbol=symbol)
            # return orders
            return {"ok": False, "message": "FFFFFFFFFFFFFFFFFFFFFFFF"}
        except ClientError as e:
            _log_error(f"closeOrder({symbol}) ClientError: {e}", critical=True, exc=e)
            return {"ok": False, "message": str(e)}
        except Exception as e:
            _log_error(f"closeOrder({symbol}): {e}", critical=True, exc=e)
            return {"ok": False, "message": str(e)}

    @retry_um_futures(critical_on_final_failure=False)
    def getOrders(symbol):
        """
        Get current open orders for the symbol from Binance.
        Returns list of order dicts; on error returns None and logs.
        """
        try:
            orders = client.get_orders(symbol=symbol)
            return orders
        except ClientError as e:
            _log_error(f"getOrders({symbol}): {e}", exc=e)
            return None
        except Exception as e:
            _log_error(f"getOrders({symbol}): {e}", exc=e)
            return None

    @retry_um_futures(critical_on_final_failure=False)
    def getOpenPosition(symbol):
        """
        Get open position(s) for the symbol (positionAmt != 0).
        Returns list of position dicts; on error returns empty list and logs.
        """
        try:
            position = client.get_position_risk(symbol=symbol)
            filtered_data = [entry for entry in position if float(entry['positionAmt']) != 0.0]
            return filtered_data
        except ClientError as e:
            _log_error(f"getOpenPosition({symbol}): {e}", exc=e)
            return []
        except Exception as e:
            _log_error(f"getOpenPosition({symbol}): {e}", exc=e)
            return []

    @retry_um_futures(critical_on_final_failure=False)
    def getAllOpenPosition():
        """
        Get all open positions across all symbols (positionAmt != 0).
        Uses a short sleep to avoid rate limit. Returns list of position dicts.
        """
        try:
            time.sleep(0.3)
            position = client.get_position_risk()
            filtered_data = [entry for entry in position if float(entry['positionAmt']) != 0.0]
            return filtered_data
        except ClientError as e:
            _log_error("getAllOpenPosition: " + str(e), exc=e)
            return []
        except Exception as e:
            _log_error("getAllOpenPosition: " + str(e), exc=e)
            return []

    @retry_um_futures(critical_on_final_failure=False)
    def getmaxNotionalValue(symbol):
        """
        Get position risk (max notional, etc.) for the symbol.
        Returns list of position info or 0 on error.
        """
        try:
            position = client.get_position_risk(symbol=symbol)
            return position
        except ClientError as e:
            _log_error(f"getmaxNotionalValue({symbol}): {e}", exc=e)
            return 0
        except Exception as e:
            _log_error(f"getmaxNotionalValue({symbol}): {e}", exc=e)
            return 0

    @retry_um_futures(critical_on_final_failure=False)
    def getEntryPrice(symbol):
        """
        Get break-even (entry) price for the current position of the symbol.
        Returns float or 0 if no position or on error.
        """
        try:
            position = client.get_position_risk(symbol=symbol)
            filtered_data = [entry for entry in position if float(entry['positionAmt']) != 0.0]
            if len(filtered_data) > 0:
                return float(filtered_data[0]['breakEvenPrice'])
            return 0.0
        except ClientError as e:
            _log_error(f"getEntryPrice({symbol}): {e}", exc=e)
            return 0.0
        except Exception as e:
            _log_error(f"getEntryPrice({symbol}): {e}", exc=e)
            return 0.0

    def FixOrder(symbol):
        """
        Adjust or close the current position: if unrealized profit > 1, close by market order;
        otherwise set force stop-loss and take-profit around break-even.
        """
        try:
            pos = getOpenPosition(symbol)
            if not pos:
                return
            qty = float(pos[0]['positionAmt'])
            unRealizedProfit = float(pos[0]['unRealizedProfit'])
            current_price = float(client.ticker_price(symbol)['price'])
            breakEvenPrice = float(pos[0]['breakEvenPrice'])
            price_precision = get_price_precision(symbol)
            if price_precision is None:
                _log_error(f"FixOrder({symbol}): no price precision", exc=None)
                return
            if qty > 0.0:
                print("This IS BUY", unRealizedProfit)
                if unRealizedProfit > 1:
                    resp = client.new_order(symbol=symbol, side='SELL', type='MARKET', quantity=qty)
                    print("\033[92mPlacing Order:", resp, "\033[0m")
                else:
                    forceStopPrice = round(current_price - current_price * 0.003, price_precision)
                    forceTakeProfit = round(breakEvenPrice + breakEvenPrice * 0.005, price_precision)
                    setStopLoss(symbol, forceStopPrice, 'SELL', qty)
                    setProfit(symbol, forceTakeProfit, 'SELL', qty)
                    print("forceTakeProfit,forceStopPrice", forceTakeProfit, forceStopPrice)
            elif qty < 0.0:
                print("\033[91mThis IS QTY:", qty, "\033[0m")
                print("\033[91mThis IS SELL:", unRealizedProfit, "\033[0m")
                qtyabs = abs(qty)
                if unRealizedProfit > 1:
                    resp = client.new_order(symbol=symbol, side='BUY', type='MARKET', quantity=qtyabs)
                    print("\033[92mPlacing Order:", resp, "\033[0m")
                else:
                    forceStopPrice = round(current_price + current_price * 0.003, price_precision)
                    forceTakeProfit = round(breakEvenPrice - breakEvenPrice * 0.005, price_precision)
                    setStopLoss(symbol, forceStopPrice, 'BUY', qtyabs)
                    setProfit(symbol, forceTakeProfit, 'BUY', qtyabs)
                    print("forceTakeProfit,forceStopPrice", forceTakeProfit, forceStopPrice)
        except Exception as e:
            _log_error(f"FixOrder({symbol}): {e}", critical=True, exc=e)

    @retry_um_futures(critical_on_final_failure=False)
    def getDateTime():
        """
        Get Binance server time as a datetime object (UTC).
        """
        try:
            res = client.time()
            ts = res['serverTime'] / 1000
            return datetime.datetime.fromtimestamp(ts)
        except Exception as e:
            _log_error("getDateTime: " + str(e), exc=e)
            return None

    def sleep_until_next_cycle():
        """
        Return seconds to sleep until the next full minute (for cycle alignment).
        """
        try:
            currentDateTime = getDateTime()
            if currentDateTime is None:
                return 0
            if currentDateTime.second <= 60:
                return 60 - currentDateTime.second
            return 0
        except Exception as e:
            _log_error("sleep_until_next_cycle: " + str(e), exc=e)
            return 0

    @retry_um_futures(critical_on_final_failure=False)
    def changeLevrage(symbol, lev):
        """
        Set leverage for the symbol to the given level (recvWindow=6000).
        """
        try:
            response = client.change_leverage(symbol=symbol, leverage=lev, recvWindow=6000)
            logging.info(response)
        except ClientError as e:
            _log_error(f"changeLevrage({symbol}): {e}", exc=e)
        except Exception as e:
            _log_error(f"changeLevrage({symbol}): {e}", exc=e)

    @retry_um_futures(critical_on_final_failure=False)
    def getData5m(SYMBOL):
        """
        Fetch last 500 5m klines for symbol and return close prices as numpy array.
        """
        try:
            klines = client.klines(SYMBOL, '5m', limit=500)
            return_data = [float(each[4]) for each in klines]
            return np.array(return_data)
        except Exception as e:
            _log_error(f"getData5m({SYMBOL}): {e}", exc=e)
            return np.array([])

    def getRSI(SYMBOL):
        """
        Compute 7-period RSI from 5m close prices; returns last value or None on error.
        """
        try:
            closing_data = getData5m(SYMBOL)
            if closing_data is None or len(closing_data) == 0:
                return None
            rsi = talib.RSI(closing_data, 7)[-1]
            return rsi
        except Exception as e:
            _log_error(f"getRSI({SYMBOL}): {e}", exc=e)
            return None

    @retry_um_futures(critical_on_final_failure=False)
    def getHistoricalData5m(symbol, min):
        """
        Fetch perpetual continuous klines for symbol and interval (e.g. '5m').
        Tries limit=500, falls back to 50 on ClientError. Returns DataFrame with OHLCV.
        """
        try:
            df = pd.DataFrame(client.continuous_klines(symbol, 'PERPETUAL', min, **{"limit": 500}))
        except ClientError as e:
            _log_error(f"getHistoricalData5m({symbol}) limit 500: {e}", exc=e)
            df = pd.DataFrame(client.continuous_klines(symbol, 'PERPETUAL', min, **{"limit": 50}))
        df = df.iloc[:, :11]
        df.columns = ["Open Time","Open Price","High","Low","Close Price","Volume","Close Time","Q.A Volume","No. Of Trades","Taker BUY Volume","Taker BUY quote asset volume"]
        df=df.set_index("Open Time")
        df.index = pd.to_datetime(df.index,unit='ms', utc=True)
        
        #appendInExcel(df)
        #df.to_excel("continuous_klines.xlsx")
        df =df.astype(float)    
        return df
    
    @retry_um_futures(critical_on_final_failure=False)
    def getHistoricalData1m(symbol):
        """
        Fetch last 5 perpetual 1m klines for symbol. Returns DataFrame. On error retries after 5s.
        """
        try:
            df = pd.DataFrame(client.continuous_klines(symbol, 'PERPETUAL', '1m', **{"limit": 5}))
        except ClientError as e:
            _log_error(f"getHistoricalData1m({symbol}): {e}", exc=e)
            sleep(5)
            df = pd.DataFrame(client.continuous_klines(symbol, 'PERPETUAL', '1m', **{"limit": 5}))
        df = df.iloc[:, :11]
        df.columns = ["Open Time", "Open Price", "High", "Low", "Close Price", "Volume", "Close Time", "Q.A Volume", "No. Of Trades", "Taker BUY Volume", "Taker BUY quote asset volume"]
        df = df.set_index("Open Time")
        df.index = pd.to_datetime(df.index, unit='ms', utc=True)
        appendInExcel(df)
        df = df.astype(float)
        return df

    def appendInExcel(df):
        """
        Append DataFrame to continuous_klines.csv (append mode, header only when file empty).
        """
        try:
            with open('continuous_klines.csv', 'a', encoding='utf-8') as f:
                df.to_csv(f, header=f.tell() == 0)
        except Exception as e:
            _log_error("appendInExcel: " + str(e), exc=e)

    @retry_um_futures(critical_on_final_failure=False)
    def getAllOrders(symbol):
        """
        Fetch all orders for symbol and return the latest FILLED order by time, or 0 if none.
        """
        try:
            orders = client.get_all_orders(symbol)
            if orders:
                filled_orders = [o for o in orders if o['status'] == 'FILLED']
                if filled_orders:
                    return max(filled_orders, key=lambda o: o['time'])
            return 0
        except ClientError as e:
            _log_error(f"getAllOrders({symbol}): {e}", exc=e)
            return 0
        except Exception as e:
            _log_error(f"getAllOrders({symbol}): {e}", exc=e)
            return 0

    def getProfitTarget(side, symbol, profitPercentage):
        """
        Compute take-profit price from current ticker price and percentage.
        BUY: price + (price * pct). SELL: price - (price * pct). Returns 0 otherwise.
        """
        try:
            price_precision = get_price_precision(symbol)
            entryPrice = float(client.ticker_price(symbol)['price'])
            if price_precision is None:
                return 0
            if side == 'BUY':
                return round(entryPrice + (entryPrice * profitPercentage), price_precision)
            elif side == 'SELL':
                return round(entryPrice - (entryPrice * profitPercentage), price_precision)
            return 0
        except Exception as e:
            _log_error(f"getProfitTarget({symbol}): {e}", exc=e)
            return 0

    # -------------------------------------------------------------------------
    # UMFutures API wrappers (all methods from binance.um_futures)
    # Each wraps client.<method> with retry, try/except, file log, Telegram on critical.
    # -------------------------------------------------------------------------

    # ----- MARKETS (read-only, non-critical) -----
    @retry_um_futures(critical_on_final_failure=False)
    def um_ping(*args, **kwargs):
        """Test connectivity to the Rest API. UMFutures.ping()."""
        try:
            return client.ping(*args, **kwargs)
        except Exception as e:
            _log_error("um_ping: " + str(e), exc=e)
            return {"ok": False, "message": str(e)}

    @retry_um_futures(critical_on_final_failure=False)
    def um_time(*args, **kwargs):
        """Check server time. UMFutures.time()."""
        try:
            return client.time(*args, **kwargs)
        except Exception as e:
            _log_error("um_time: " + str(e), exc=e)
            return {"ok": False, "message": str(e)}

    @retry_um_futures(critical_on_final_failure=False)
    def um_exchange_info(*args, **kwargs):
        """Exchange trading rules and symbol information. UMFutures.exchange_info()."""
        try:
            return client.exchange_info(*args, **kwargs)
        except Exception as e:
            _log_error("um_exchange_info: " + str(e), exc=e)
            return {"ok": False, "message": str(e)}

    @retry_um_futures(critical_on_final_failure=False)
    def um_depth(symbol, **kwargs):
        """Order book for symbol. UMFutures.depth(symbol, limit=...)."""
        try:
            return client.depth(symbol, **kwargs)
        except Exception as e:
            _log_error(f"um_depth({symbol}): " + str(e), exc=e)
            return {"ok": False, "message": str(e)}

    @retry_um_futures(critical_on_final_failure=False)
    def um_trades(symbol, **kwargs):
        """Recent market trades for symbol. UMFutures.trades(symbol, limit=...)."""
        try:
            return client.trades(symbol, **kwargs)
        except Exception as e:
            _log_error(f"um_trades({symbol}): " + str(e), exc=e)
            return {"ok": False, "message": str(e)}

    @retry_um_futures(critical_on_final_failure=False)
    def um_historical_trades(symbol, **kwargs):
        """Older market historical trades. UMFutures.historical_trades(symbol, ...)."""
        try:
            return client.historical_trades(symbol, **kwargs)
        except Exception as e:
            _log_error(f"um_historical_trades({symbol}): " + str(e), exc=e)
            return {"ok": False, "message": str(e)}

    @retry_um_futures(critical_on_final_failure=False)
    def um_agg_trades(symbol, **kwargs):
        """Compressed/aggregate trades list. UMFutures.agg_trades(symbol, ...)."""
        try:
            return client.agg_trades(symbol, **kwargs)
        except Exception as e:
            _log_error(f"um_agg_trades({symbol}): " + str(e), exc=e)
            return {"ok": False, "message": str(e)}

    @retry_um_futures(critical_on_final_failure=False)
    def um_klines(symbol, interval, **kwargs):
        """Kline/candlestick data. UMFutures.klines(symbol, interval, limit=...)."""
        try:
            return client.klines(symbol, interval, **kwargs)
        except Exception as e:
            _log_error(f"um_klines({symbol}): " + str(e), exc=e)
            return {"ok": False, "message": str(e)}

    @retry_um_futures(critical_on_final_failure=False)
    def um_continuous_klines(pair, contractType, interval, **kwargs):
        """Continuous contract klines. UMFutures.continuous_klines(pair, contractType, interval, ...)."""
        try:
            return client.continuous_klines(pair, contractType, interval, **kwargs)
        except Exception as e:
            _log_error("um_continuous_klines: " + str(e), exc=e)
            return {"ok": False, "message": str(e)}

    @retry_um_futures(critical_on_final_failure=False)
    def um_index_price_klines(pair, interval, **kwargs):
        """Index price klines for a pair. UMFutures.index_price_klines(pair, interval, ...)."""
        try:
            return client.index_price_klines(pair, interval, **kwargs)
        except Exception as e:
            _log_error("um_index_price_klines: " + str(e), exc=e)
            return {"ok": False, "message": str(e)}

    @retry_um_futures(critical_on_final_failure=False)
    def um_mark_price_klines(symbol, interval, **kwargs):
        """Mark price klines. UMFutures.mark_price_klines(symbol, interval, ...)."""
        try:
            return client.mark_price_klines(symbol, interval, **kwargs)
        except Exception as e:
            _log_error(f"um_mark_price_klines({symbol}): " + str(e), exc=e)
            return {"ok": False, "message": str(e)}

    @retry_um_futures(critical_on_final_failure=False)
    def um_mark_price(symbol=None, **kwargs):
        """Mark price and funding rate. UMFutures.mark_price(symbol=None)."""
        try:
            return client.mark_price(symbol=symbol, **kwargs)
        except Exception as e:
            _log_error("um_mark_price: " + str(e), exc=e)
            return {"ok": False, "message": str(e)}

    @retry_um_futures(critical_on_final_failure=False)
    def um_funding_rate(symbol, **kwargs):
        """Funding rate history. UMFutures.funding_rate(symbol, ...)."""
        try:
            return client.funding_rate(symbol, **kwargs)
        except Exception as e:
            _log_error(f"um_funding_rate({symbol}): " + str(e), exc=e)
            return {"ok": False, "message": str(e)}

    @retry_um_futures(critical_on_final_failure=False)
    def um_ticker_24hr_price_change(symbol=None, **kwargs):
        """24h price change statistics. UMFutures.ticker_24hr_price_change(symbol=None)."""
        try:
            return client.ticker_24hr_price_change(symbol=symbol, **kwargs)
        except Exception as e:
            _log_error("um_ticker_24hr_price_change: " + str(e), exc=e)
            return {"ok": False, "message": str(e)}

    @retry_um_futures(critical_on_final_failure=False)
    def um_ticker_price(symbol=None, **kwargs):
        """Latest price for symbol or all. UMFutures.ticker_price(symbol=None)."""
        try:
            return client.ticker_price(symbol=symbol, **kwargs)
        except Exception as e:
            _log_error("um_ticker_price: " + str(e), exc=e)
            return {"ok": False, "message": str(e)}

    @retry_um_futures(critical_on_final_failure=False)
    def um_book_ticker(symbol=None, **kwargs):
        """Best bid/ask for symbol or all. UMFutures.book_ticker(symbol=None)."""
        try:
            return client.book_ticker(symbol=symbol, **kwargs)
        except Exception as e:
            _log_error("um_book_ticker: " + str(e), exc=e)
            return {"ok": False, "message": str(e)}

    @retry_um_futures(critical_on_final_failure=False)
    def um_open_interest(symbol, **kwargs):
        """Current open interest for symbol. UMFutures.open_interest(symbol)."""
        try:
            return client.open_interest(symbol, **kwargs)
        except Exception as e:
            _log_error(f"um_open_interest({symbol}): " + str(e), exc=e)
            return {"ok": False, "message": str(e)}

    @retry_um_futures(critical_on_final_failure=False)
    def um_open_interest_hist(symbol, period, **kwargs):
        """Historical open interest. UMFutures.open_interest_hist(symbol, period, ...)."""
        try:
            return client.open_interest_hist(symbol, period, **kwargs)
        except Exception as e:
            _log_error(f"um_open_interest_hist({symbol}): " + str(e), exc=e)
            return {"ok": False, "message": str(e)}

    @retry_um_futures(critical_on_final_failure=False)
    def um_top_long_short_position_ratio(symbol, period, **kwargs):
        """Top long/short position ratio. UMFutures.top_long_short_position_ratio(symbol, period, ...)."""
        try:
            return client.top_long_short_position_ratio(symbol, period, **kwargs)
        except Exception as e:
            _log_error(f"um_top_long_short_position_ratio({symbol}): " + str(e), exc=e)
            return {"ok": False, "message": str(e)}

    @retry_um_futures(critical_on_final_failure=False)
    def um_long_short_account_ratio(symbol, period, **kwargs):
        """Global long/short account ratio. UMFutures.long_short_account_ratio(symbol, period, ...)."""
        try:
            return client.long_short_account_ratio(symbol, period, **kwargs)
        except Exception as e:
            _log_error(f"um_long_short_account_ratio({symbol}): " + str(e), exc=e)
            return {"ok": False, "message": str(e)}

    @retry_um_futures(critical_on_final_failure=False)
    def um_top_long_short_account_ratio(symbol, period, **kwargs):
        """Top long/short account ratio. UMFutures.top_long_short_account_ratio(symbol, period, ...)."""
        try:
            return client.top_long_short_account_ratio(symbol, period, **kwargs)
        except Exception as e:
            _log_error(f"um_top_long_short_account_ratio({symbol}): " + str(e), exc=e)
            return {"ok": False, "message": str(e)}

    @retry_um_futures(critical_on_final_failure=False)
    def um_taker_long_short_ratio(symbol, period, **kwargs):
        """Taker long/short ratio. UMFutures.taker_long_short_ratio(symbol, period, ...)."""
        try:
            return client.taker_long_short_ratio(symbol, period, **kwargs)
        except Exception as e:
            _log_error(f"um_taker_long_short_ratio({symbol}): " + str(e), exc=e)
            return {"ok": False, "message": str(e)}

    @retry_um_futures(critical_on_final_failure=False)
    def um_blvt_kline(symbol, interval, **kwargs):
        """Historical BLVT NAV kline. UMFutures.blvt_kline(symbol, interval, ...)."""
        try:
            return client.blvt_kline(symbol, interval, **kwargs)
        except Exception as e:
            _log_error(f"um_blvt_kline({symbol}): " + str(e), exc=e)
            return {"ok": False, "message": str(e)}

    @retry_um_futures(critical_on_final_failure=False)
    def um_index_info(symbol=None, **kwargs):
        """Composite index info. UMFutures.index_info(symbol=None)."""
        try:
            return client.index_info(symbol=symbol, **kwargs)
        except Exception as e:
            _log_error("um_index_info: " + str(e), exc=e)
            return {"ok": False, "message": str(e)}

    @retry_um_futures(critical_on_final_failure=False)
    def um_asset_index(symbol=None, **kwargs):
        """Asset index for Multi-Assets mode. UMFutures.asset_Index(symbol=None)."""
        try:
            return client.asset_Index(symbol=symbol, **kwargs)
        except Exception as e:
            _log_error("um_asset_index: " + str(e), exc=e)
            return {"ok": False, "message": str(e)}

    # ----- ACCOUNT (position/multi-asset mode: critical) -----
    @retry_um_futures(critical_on_final_failure=True)
    def um_change_position_mode(dualSidePosition, **kwargs):
        """Change position mode (hedge/one-way). UMFutures.change_position_mode(dualSidePosition, ...)."""
        try:
            return client.change_position_mode(dualSidePosition, **kwargs)
        except Exception as e:
            _log_error("um_change_position_mode: " + str(e), critical=True, exc=e)
            return {"ok": False, "message": str(e)}

    @retry_um_futures(critical_on_final_failure=False)
    def um_get_position_mode(*args, **kwargs):
        """Get current position mode. UMFutures.get_position_mode()."""
        try:
            return client.get_position_mode(*args, **kwargs)
        except Exception as e:
            _log_error("um_get_position_mode: " + str(e), exc=e)
            return {"ok": False, "message": str(e)}

    @retry_um_futures(critical_on_final_failure=True)
    def um_change_multi_asset_mode(multiAssetsMargin, **kwargs):
        """Change multi-assets mode. UMFutures.change_multi_asset_mode(multiAssetsMargin, ...)."""
        try:
            return client.change_multi_asset_mode(multiAssetsMargin, **kwargs)
        except Exception as e:
            _log_error("um_change_multi_asset_mode: " + str(e), critical=True, exc=e)
            return {"ok": False, "message": str(e)}

    @retry_um_futures(critical_on_final_failure=False)
    def um_get_multi_asset_mode(*args, **kwargs):
        """Get current multi-assets mode. UMFutures.get_multi_asset_mode()."""
        try:
            return client.get_multi_asset_mode(*args, **kwargs)
        except Exception as e:
            _log_error("um_get_multi_asset_mode: " + str(e), exc=e)
            return {"ok": False, "message": str(e)}

    @retry_um_futures(critical_on_final_failure=True)
    def um_new_order(symbol, side, type, **kwargs):
        """Place new order. UMFutures.new_order(symbol, side, type, ...)."""
        try:
            return client.new_order(symbol, side, type, **kwargs)
        except Exception as e:
            _log_error(f"um_new_order({symbol}): " + str(e), critical=True, exc=e)
            return {"ok": False, "message": str(e)}

    @retry_um_futures(critical_on_final_failure=False)
    def um_new_order_test(symbol, side, type, **kwargs):
        """Place test order. UMFutures.new_order_test(symbol, side, type, ...)."""
        try:
            return client.new_order_test(symbol, side, type, **kwargs)
        except Exception as e:
            _log_error(f"um_new_order_test({symbol}): " + str(e), exc=e)
            return {"ok": False, "message": str(e)}

    @retry_um_futures(critical_on_final_failure=True)
    def um_modify_order(symbol, side, quantity, price, orderId=None, origClientOrderId=None, **kwargs):
        """Modify order. UMFutures.modify_order(symbol, side, quantity, price, orderId=..., origClientOrderId=..., ...)."""
        try:
            return client.modify_order(symbol, side, quantity, price, orderId=orderId, origClientOrderId=origClientOrderId, **kwargs)
        except Exception as e:
            _log_error(f"um_modify_order({symbol}): " + str(e), critical=True, exc=e)
            return {"ok": False, "message": str(e)}

    @retry_um_futures(critical_on_final_failure=True)
    def um_new_batch_order(batchOrders):
        """Place multiple orders. UMFutures.new_batch_order(batchOrders)."""
        try:
            return client.new_batch_order(batchOrders)
        except Exception as e:
            _log_error("um_new_batch_order: " + str(e), critical=True, exc=e)
            return {"ok": False, "message": str(e)}

    @retry_um_futures(critical_on_final_failure=False)
    def um_query_order(symbol, orderId=None, origClientOrderId=None, **kwargs):
        """Query order status. UMFutures.query_order(symbol, orderId=..., origClientOrderId=..., ...)."""
        try:
            return client.query_order(symbol, orderId=orderId, origClientOrderId=origClientOrderId, **kwargs)
        except Exception as e:
            _log_error(f"um_query_order({symbol}): " + str(e), exc=e)
            return {"ok": False, "message": str(e)}

    @retry_um_futures(critical_on_final_failure=True)
    def um_cancel_order(symbol, orderId=None, origClientOrderId=None, **kwargs):
        """Cancel one order. UMFutures.cancel_order(symbol, orderId=..., origClientOrderId=..., ...)."""
        try:
            return client.cancel_order(symbol, orderId=orderId, origClientOrderId=origClientOrderId, **kwargs)
        except Exception as e:
            _log_error(f"um_cancel_order({symbol}): " + str(e), critical=True, exc=e)
            return {"ok": False, "message": str(e)}

    @retry_um_futures(critical_on_final_failure=True)
    def um_cancel_open_orders(symbol, **kwargs):
        """Cancel all open orders for symbol. UMFutures.cancel_open_orders(symbol, ...)."""
        try:
            return client.cancel_open_orders(symbol, **kwargs)
        except Exception as e:
            _log_error(f"um_cancel_open_orders({symbol}): " + str(e), critical=True, exc=e)
            return {"ok": False, "message": str(e)}

    @retry_um_futures(critical_on_final_failure=True)
    def um_cancel_batch_order(symbol, orderIdList=None, origClientOrderIdList=None, **kwargs):
        """Cancel multiple orders. UMFutures.cancel_batch_order(symbol, orderIdList=..., origClientOrderIdList=..., ...)."""
        try:
            return client.cancel_batch_order(symbol, orderIdList=orderIdList, origClientOrderIdList=origClientOrderIdList, **kwargs)
        except Exception as e:
            _log_error(f"um_cancel_batch_order({symbol}): " + str(e), critical=True, exc=e)
            return {"ok": False, "message": str(e)}

    @retry_um_futures(critical_on_final_failure=True)
    def um_countdown_cancel_order(symbol, countdownTime, **kwargs):
        """Auto-cancel all open orders after countdown. UMFutures.countdown_cancel_order(symbol, countdownTime, ...)."""
        try:
            return client.countdown_cancel_order(symbol, countdownTime, **kwargs)
        except Exception as e:
            _log_error(f"um_countdown_cancel_order({symbol}): " + str(e), critical=True, exc=e)
            return {"ok": False, "message": str(e)}

    @retry_um_futures(critical_on_final_failure=False)
    def um_get_open_orders(symbol=None, **kwargs):
        """Get open order(s). UMFutures.get_open_orders(symbol=None, ...)."""
        try:
            return client.get_open_orders(symbol=symbol, **kwargs)
        except Exception as e:
            _log_error("um_get_open_orders: " + str(e), exc=e)
            return {"ok": False, "message": str(e)}

    @retry_um_futures(critical_on_final_failure=False)
    def um_get_orders(*args, **kwargs):
        """Get all open orders (optionally for symbol). UMFutures.get_orders(symbol=..., ...)."""
        try:
            return client.get_orders(*args, **kwargs)
        except Exception as e:
            _log_error("um_get_orders: " + str(e), exc=e)
            return {"ok": False, "message": str(e)}

    @retry_um_futures(critical_on_final_failure=False)
    def um_get_all_orders(symbol, **kwargs):
        """Get all orders for symbol. UMFutures.get_all_orders(symbol, ...)."""
        try:
            return client.get_all_orders(symbol, **kwargs)
        except Exception as e:
            _log_error(f"um_get_all_orders({symbol}): " + str(e), exc=e)
            return {"ok": False, "message": str(e)}

    @retry_um_futures(critical_on_final_failure=False)
    def um_balance(*args, **kwargs):
        """Futures account balance. UMFutures.balance()."""
        try:
            return client.balance(*args, **kwargs)
        except Exception as e:
            _log_error("um_balance: " + str(e), exc=e)
            return {"ok": False, "message": str(e)}

    @retry_um_futures(critical_on_final_failure=False)
    def um_account(*args, **kwargs):
        """Account information. UMFutures.account()."""
        try:
            return client.account(*args, **kwargs)
        except Exception as e:
            _log_error("um_account: " + str(e), exc=e)
            return {"ok": False, "message": str(e)}

    @retry_um_futures(critical_on_final_failure=False)
    def um_change_leverage(symbol, leverage, **kwargs):
        """Change initial leverage. UMFutures.change_leverage(symbol, leverage, ...)."""
        try:
            return client.change_leverage(symbol, leverage, **kwargs)
        except Exception as e:
            _log_error(f"um_change_leverage({symbol}): " + str(e), exc=e)
            return {"ok": False, "message": str(e)}

    @retry_um_futures(critical_on_final_failure=True)
    def um_change_margin_type(symbol, marginType, **kwargs):
        """Change margin type (ISOLATED/CROSSED). UMFutures.change_margin_type(symbol, marginType, ...)."""
        try:
            return client.change_margin_type(symbol, marginType, **kwargs)
        except Exception as e:
            _log_error(f"um_change_margin_type({symbol}): " + str(e), critical=True, exc=e)
            return {"ok": False, "message": str(e)}

    @retry_um_futures(critical_on_final_failure=True)
    def um_modify_isolated_position_margin(symbol, amount, type, **kwargs):
        """Modify isolated position margin. UMFutures.modify_isolated_position_margin(symbol, amount, type, ...)."""
        try:
            return client.modify_isolated_position_margin(symbol, amount, type, **kwargs)
        except Exception as e:
            _log_error(f"um_modify_isolated_position_margin({symbol}): " + str(e), critical=True, exc=e)
            return {"ok": False, "message": str(e)}

    @retry_um_futures(critical_on_final_failure=False)
    def um_get_position_margin_history(symbol, **kwargs):
        """Position margin change history. UMFutures.get_position_margin_history(symbol, ...)."""
        try:
            return client.get_position_margin_history(symbol, **kwargs)
        except Exception as e:
            _log_error(f"um_get_position_margin_history({symbol}): " + str(e), exc=e)
            return {"ok": False, "message": str(e)}

    @retry_um_futures(critical_on_final_failure=False)
    def um_get_position_risk(symbol=None, **kwargs):
        """Position risk (all or for symbol). UMFutures.get_position_risk(symbol=None, ...)."""
        try:
            return client.get_position_risk(symbol=symbol, **kwargs)
        except Exception as e:
            _log_error("um_get_position_risk: " + str(e), exc=e)
            return {"ok": False, "message": str(e)}

    @retry_um_futures(critical_on_final_failure=False)
    def um_get_account_trades(symbol, **kwargs):
        """Account trades for symbol. UMFutures.get_account_trades(symbol, ...)."""
        try:
            return client.get_account_trades(symbol, **kwargs)
        except Exception as e:
            _log_error(f"um_get_account_trades({symbol}): " + str(e), exc=e)
            return {"ok": False, "message": str(e)}

    @retry_um_futures(critical_on_final_failure=False)
    def um_get_income_history(**kwargs):
        """Income history. UMFutures.get_income_history(...)."""
        try:
            return client.get_income_history(**kwargs)
        except Exception as e:
            _log_error("um_get_income_history: " + str(e), exc=e)
            return {"ok": False, "message": str(e)}

    @retry_um_futures(critical_on_final_failure=False)
    def um_leverage_brackets(symbol=None, **kwargs):
        """Leverage brackets. UMFutures.leverage_brackets(symbol=None, ...)."""
        try:
            return client.leverage_brackets(symbol=symbol, **kwargs)
        except Exception as e:
            _log_error("um_leverage_brackets: " + str(e), exc=e)
            return {"ok": False, "message": str(e)}

    @retry_um_futures(critical_on_final_failure=False)
    def um_adl_quantile(symbol=None, **kwargs):
        """ADL quantile. UMFutures.adl_quantile(symbol=None, ...)."""
        try:
            return client.adl_quantile(symbol=symbol, **kwargs)
        except Exception as e:
            _log_error("um_adl_quantile: " + str(e), exc=e)
            return {"ok": False, "message": str(e)}

    @retry_um_futures(critical_on_final_failure=False)
    def um_force_orders(symbol=None, **kwargs):
        """Force orders (e.g. liquidations). UMFutures.force_orders(symbol=None, ...)."""
        try:
            return client.force_orders(symbol=symbol, **kwargs)
        except Exception as e:
            _log_error("um_force_orders: " + str(e), exc=e)
            return {"ok": False, "message": str(e)}

    @retry_um_futures(critical_on_final_failure=False)
    def um_api_trading_status(*args, **kwargs):
        """API trading status. UMFutures.api_trading_status()."""
        try:
            return client.api_trading_status(*args, **kwargs)
        except Exception as e:
            _log_error("um_api_trading_status: " + str(e), exc=e)
            return {"ok": False, "message": str(e)}

    @retry_um_futures(critical_on_final_failure=False)
    def um_commission_rate(symbol=None, **kwargs):
        """Commission rate. UMFutures.commission_rate(symbol=None, ...)."""
        try:
            return client.commission_rate(symbol=symbol, **kwargs)
        except Exception as e:
            _log_error("um_commission_rate: " + str(e), exc=e)
            return {"ok": False, "message": str(e)}

    # ----- STREAMS (user data stream) -----
    @retry_um_futures(critical_on_final_failure=False)
    def um_new_listen_key(*args, **kwargs):
        """Create listen key for user data stream. UMFutures.new_listen_key()."""
        try:
            return client.new_listen_key(*args, **kwargs)
        except Exception as e:
            _log_error("um_new_listen_key: " + str(e), exc=e)
            return {"ok": False, "message": str(e)}

    @retry_um_futures(critical_on_final_failure=False)
    def um_renew_listen_key(listenKey, **kwargs):
        """Renew listen key. UMFutures.renew_listen_key(listenKey, ...)."""
        try:
            return client.renew_listen_key(listenKey, **kwargs)
        except Exception as e:
            _log_error("um_renew_listen_key: " + str(e), exc=e)
            return {"ok": False, "message": str(e)}

    @retry_um_futures(critical_on_final_failure=False)
    def um_close_listen_key(listenKey, **kwargs):
        """Close listen key. UMFutures.close_listen_key(listenKey, ...)."""
        try:
            return client.close_listen_key(listenKey, **kwargs)
        except Exception as e:
            _log_error("um_close_listen_key: " + str(e), exc=e)
            return {"ok": False, "message": str(e)}

    # ----- PORTFOLIO MARGIN -----
    @retry_um_futures(critical_on_final_failure=False)
    def um_pm_exchange_info(*args, **kwargs):
        """Portfolio margin exchange info. UMFutures.pm_exchange_info()."""
        try:
            return client.pm_exchange_info(*args, **kwargs)
        except Exception as e:
            _log_error("um_pm_exchange_info: " + str(e), exc=e)
            return {"ok": False, "message": str(e)}

except Exception as error:
    _log_error("main_binance client init: " + str(error), critical=True, exc=error)
    raise

def speak(text):
    """
    Use pyttsx3 to speak the given text (local TTS). No-op if pyttsx3 unavailable.
    """
    try:
        if pyttsx3 is None:
            return
        engine = pyttsx3.init()
        engine.setProperty('rate', 140)
        engine.setProperty('volume', 1)
        engine.say(text)
        engine.runAndWait()
    except Exception as e:
        try:
            _log_error("speak (TTS): " + str(e), exc=e)
        except Exception:
            print("An error occurred IN ENGINE:", e)

def text_to_speech(text):
    """
    Run TTS for text in a background thread (only works on local computer).
    """
    try:
        thread = threading.Thread(target=speak, args=(text,))
        thread.start()
        thread.join()
    except Exception as e:
        try:
            _log_error("text_to_speech: " + str(e), exc=e)
        except Exception:
            pass

#     try:
#         # Generate a unique filename
#         audio_file = f"output_{uuid.uuid4().hex}.mp3"
#         tts = gTTS(text=text, lang='en')
#         tts.save(audio_file)
        
#         # Initialize pygame mixer
#         pygame.mixer.pre_init(buffer=512)
#         pygame.mixer.init()
#         pygame.mixer.music.load(audio_file)
#         pygame.mixer.music.play()
        
#         # Timeout-based playback loop
#         start_time = time.time()
#         timeout=10
#         while pygame.mixer.music.get_busy():
#             if time.time() - start_time > timeout:
#                 print("Playback timed out.")
#                 break
#             time.sleep(0.1)
        
#     except pygame.error as e:
#         print(f"Pygame Error: {e}")
#     except Exception as e:
#         print(f"Speech failed: {e}")
#     finally:
#         if pygame.mixer.get_init():
#             pygame.mixer.quit()
#         if os.path.exists(audio_file):
#             os.remove(audio_file)

def simpmovavg(data, window):
    """Return simple moving average of data over the given window."""
    try:
        return data.rolling(window=window).mean()
    except Exception as e:
        try:
            _log_error("simpmovavg: " + str(e), exc=e)
        except Exception:
            pass
        return {"ok": False, "message": str(e)}

def bollinger_band(data, sma, window, nstd):
    """Compute upper and lower Bollinger Bands from data, sma, window and std multiplier."""
    try:
        std = data.rolling(window=window).std()
        upper_band = sma + std * nstd
        lower_band = sma - std * nstd
        return upper_band, lower_band
    except Exception as e:
        try:
            _log_error("bollinger_band: " + str(e), exc=e)
        except Exception:
            pass
        return {"ok": False, "message": str(e)}

def strategyBollinegerBand(symbol, min):
    """
    Bollinger Band strategy: compare current price to 20-period bands.
    Returns 2 = SELL signal, 1 = BUY signal, 0 = no signal.
    """
    try:
        df = getHistoricalData5m(symbol, min)
        if df is None or df.empty:
            return 0
        sma = simpmovavg(df['Open Price'], window=20)
        nstd = 2
        upband, lband = bollinger_band(df['Open Price'], sma, 20, nstd)
        current_price = float(client.ticker_price(symbol)['price'])
        if current_price > upband.iloc[-1]:
            print("\033[91mSELL", symbol, "\033[0m")
            print('xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx')
            print('Upper Band', upband.iloc[-1])
            print('=======lower band', lband.iloc[-1])
            print('****************************', current_price)
            return 2
        elif current_price < lband.iloc[-1]:
            print("\033[92mBUY", symbol, "\033[0m")
            print('xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx')
            print('Upper Band', upband.iloc[-1])
            print('=======lower band', lband.iloc[-1])
            print('****************************', current_price)
            return 1
        return 0
    except Exception as e:
        try:
            _log_error(f"strategyBollinegerBand({symbol}): {e}", exc=e)
        except Exception:
            pass
        return 0

def getLeverage(symbol):
    """
    Get initial leverage (bracket 1) for the symbol from Binance leverage brackets.
    Returns 0 if not found or on error.
    """
    try:
        leverage_brackets = client.leverage_brackets()
        for item in leverage_brackets:
            if item['symbol'] == symbol:
                brackets_for_symbol = item['brackets']
                for bracket in brackets_for_symbol:
                    if bracket['bracket'] == 1:
                        print(bracket['initialLeverage'])
                        return bracket['initialLeverage']
                return 0
        return 0
    except Exception as e:
        try:
            _log_error(f"getLeverage({symbol}): {e}", exc=e)
        except Exception:
            pass
        return 0

def cleanOrders():
    """
    Cancel orphaned TP/SL orders: for each open TAKE_PROFIT_MARKET or STOP_MARKET order,
    if the symbol has no position or more than one position, cancel all open orders for that symbol.
    """
    try:
        orders = client.get_orders()
        for item in orders:
            if item['type'] in ('TAKE_PROFIT_MARKET', 'STOP_MARKET'):
                symbol = item['symbol']
                pos = getOpenPosition(symbol)
                filtered_data = [entry for entry in (pos or []) if float(entry['positionAmt']) != 0.0]
                count_filtered = len(filtered_data)
                if count_filtered == 0 or count_filtered > 1:
                    closeOrder(symbol)
                    print(f'Order is Clean for symbol -- {symbol}')
    except Exception as e:
        try:
            _log_error("cleanOrders: " + str(e), critical=True, exc=e)
        except Exception:
            print("Error in cleanOrders:", e)

# def dele(symbol):
#         openHedgePosition = getOpenPosition(symbol)
#         if(len(openHedgePosition) == 2) :
#             # print(Fore.YELLOW + f'-----------------------------------------------------------------' + Style.RESET_ALL)
#             # print(Fore.CYAN + f'{openHedgePosition}' + Style.RESET_ALL)
#             # print(Fore.YELLOW + f'-----------------------------------------------------------------' + Style.RESET_ALL)


#             for each in openHedgePosition:     
#                 qty_order = float(each['positionAmt'])
#                 print(Fore.YELLOW + f'--------------------------We are inside for loop {qty_order}---------------------------------------' + Style.RESET_ALL)
#                 print(Fore.CYAN + f'openHedgePosition' + Style.RESET_ALL)
#                 print(Fore.YELLOW + f'-------------------------{each}----------------------------------------' + Style.RESET_ALL)
#                 if(qty_order <0):
#                     print('we are inside    if(qty_order <0):', qty_order)
#                     order = client.new_order(symbol=symbol, side='BUY', type='MARKET',\
#                                               quantity = abs(qty_order),positionSide = 'SHORT')
#                     print(Fore.YELLOW + f'Close Postion For SELL :: {order}' + Style.RESET_ALL)
#                 elif(qty_order > 0):
#                     print('we are inside    if(qty_order >0):',qty_order)
#                     order = client.new_order(symbol=symbol, side='SELL', positionSide = 'LONG',  type='MARKET', quantity = qty_order)
#                     print(Fore.RED + f'Close Postion For Buy :: {order}' + Style.RESET_ALL)
   
#for index, row in df.iterrows():
    # Calculate the difference between the "OPEN Price" and "Close Price" for each row
#    difference = row["Close Price"] - row["Open Price"]
    # Print the difference for each row
#    print("Difference for Row", index , ":", difference)

# print(getAllOrders('IDUSDT'))
# print(getOpenPosition('INJUSDT'))
            
#cleanOrders()
#print(getHistoricalData1m('STEEMUSDT'))
# getOrder = getOrders('DOGEUSDT  ')
# for item in getOrder :
#     if item['type'] == 'STOP_MARKET':
    #    print(getOrder)


def getQuantity(symbol, invest):
    """
    Compute order quantity from invest amount and current price, with precision.
    Returns (quantity, plquantity, lastplquantity) for main and partial TP levels; (0,0,0) on error.
    """
    try:
        current_price = float(client.ticker_price(symbol)['price'])
        quantitywithleverage = invest / current_price
        qty_precision = get_qty_precision(symbol)
        if qty_precision is None:
            _log_error(f"getQuantity({symbol}): no qty precision", exc=None)
            return 0, 0, 0
        quantity = round(quantitywithleverage, qty_precision)
        plquantity = round(quantitywithleverage / 2, qty_precision)
        lastplquantity = round(plquantity / 2, qty_precision)
        return quantity, plquantity, lastplquantity
    except Exception as e:
        _log_error(f"getQuantity({symbol}): {e}", exc=e)
        return 0, 0, 0


# getAllOpenPosition() is now called via API endpoint /api/sync-open-positions

try:
    print(client.get_position_mode())
except NameError:
    pass  # client init failed, module raised
except Exception as e:
    try:
        _log_error("get_position_mode on load: " + str(e), exc=e)
    except Exception:
        pass      





