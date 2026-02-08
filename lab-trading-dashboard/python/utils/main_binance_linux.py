import threading
import pyttsx3
import platform
# pythoncom is Windows-specific, handle it conditionally
if platform.system() == 'Windows':
    import pythoncom
else:
    # Linux fallback - create dummy pythoncom
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

from time import sleep
from binance.error import ClientError
import datetime
import logging
import numpy as np
import talib 
import pandas as pd
import ta
from openpyxl import load_workbook
from utils import *
from colorama import init, Fore, Style
import functools
import time

# import uuid
# from gtts import gTTS
# import pygame
# import os
# import time


MAXIMUM_NUMBER_OF_API_CALL_TRIES = 5
ERROR = -1

init(autoreset=True)

try:
    #client = UMFutures(key = api, secret=secret,base_url="https://testnet.binancefuture.com")
    client = UMFutures(key = api, secret=secret)
    #client.ping()
    volume = 50  # volume for one order (if its 10 and leverage is 10, then you put 1 usdt to one position)
    sl = 0.006
    tp = 0.003


    def get_tickers_usdt():
        tickers = []
        try:
            resp = client.ticker_price()
            for elem in resp:
                if 'USDT' in elem['symbol']:
                    tickers.append(elem['symbol'])
        except Exception as error:
            print("An error occurred while fetching tickers:", error)
            # You can choose to log the error, raise it, or handle it in any other appropriate way
        return tickers
    
    def get_avail_balance():
        availableBalance = 0
        try:
            balances = client.balance()
            for asset_info in balances:
                # Check if the asset is 'USDT'
                if asset_info['asset'] == 'USDT':
                    # Print the USDT balance
                    availableBalance = float(asset_info['availableBalance'])
                    print(Fore.LIGHTMAGENTA_EX + f' (Available Balance ==> {availableBalance}' + Style.RESET_ALL)
                    break  # Exit the loop after finding the USDT balance
        except Exception as error:
            print("An error occurred while fetching tickers:", error)
            # You can choose to log the error, raise it, or handle it in any other appropriate way
        return availableBalance
        

    # Price precision. BTC has 1, XRP has 4
    def get_price_precision(symbol):
        try:
            resp = client.exchange_info()['symbols']
            for elem in resp:
                if elem['symbol'] == symbol:
                    return elem['pricePrecision']
        except Exception as error:
            print("An error occurred while fetching Price Precision:", error)
            
    # Amount precision. BTC has 3, XRP has 1
    def get_qty_precision(symbol):
        try:
            resp = client.exchange_info()['symbols']
            for elem in resp:
                if elem['symbol'] == symbol:
                    return elem['quantityPrecision']
        except Exception as error:
            print("An error occurred while fetching quantity precision:", error)
            # You can choose to log the error, raise it, or handle it in any other appropriate way

    def retry(times, on_error):
        def decorator(func):
            @functools.wraps(func)
            def wrapper(*args, **kwargs):
                for attempt in range(times):
                    try:
                        return func(*args, **kwargs)
                    except Exception as e:
                        if attempt == times - 1:
                            return on_error(e)
                        time.sleep(1)
                return on_error(Exception("Max retries exceeded"))
            return wrapper
        return decorator

    # Linux-compatible speak function
    def speak(text):
        try:
            # Initialize COM in the thread (only on Windows)
            if platform.system() == 'Windows':
                pythoncom.CoInitialize()

            # Initialize the pyttsx3 engine
            engine = pyttsx3.init()

            # Set properties
            engine.setProperty('rate', 140)  # Speed percent
            engine.setProperty('volume', 1)  # Volume 0-1

            # Queue the entered text
            engine.say(text)

            # Run the speech engine
            engine.runAndWait()
        except Exception as e:
            print("An error occurred IN ENGINE:", e)
            return 0
        finally:
            # Uninitialize COM to prevent resource leaks (only on Windows)
            if platform.system() == 'Windows':
                pythoncom.CoUninitialize()

    def text_to_speech(text):
        #### This is only work in the local computer

        # Run `speak` function in a separate thread
        thread = threading.Thread(target=speak, args=(text,))
        thread.start()
        thread.join()  # Wait for the thread to complete if needed

    def getQuantity(symbol,invest):
        try:
            price = float(client.ticker_price(symbol)['price'])
            qty_precision = get_qty_precision(symbol)
            qty = round(invest/price, qty_precision)
            return qty
        except Exception as error:
            print("An error occurred in getQuantity:", error)
            return 0

except Exception as error:
    print("An error occurred in main_binance setup:", error) 