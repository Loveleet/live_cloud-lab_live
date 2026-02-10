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
                        result = on_error(e)
                        if attempt == times - 1:
                            return result
                        time.sleep(1)
                return wrapper
        return decorator

    @retry(MAXIMUM_NUMBER_OF_API_CALL_TRIES, lambda e: logging.error(f"ERROR in setStopLoss: {e}") or (ERROR, None))        
    def closeAllHedgePosition(symbol):
        openHedgePosition = getOpenPosition(symbol)
        if(len(openHedgePosition) == 2) :
            print(Fore.YELLOW + f'-----------------------------------------------------------------' + Style.RESET_ALL)
            print(Fore.CYAN + f'{openHedgePosition}' + Style.RESET_ALL)
            print(Fore.YELLOW + f'-----------------------------------------------------------------' + Style.RESET_ALL)


            for each in openHedgePosition:     
                qty_order = float(each['positionAmt'])
                
                print(Fore.YELLOW + f'--------------------------We are inside for loop {qty_order}---------------------------------------' + Style.RESET_ALL)
                print(Fore.CYAN + f'openHedgePosition' + Style.RESET_ALL)
                print(Fore.YELLOW + f'-------------------------{each}----------------------------------------' + Style.RESET_ALL)
                if(qty_order <0):
                    print('we are inside    if(qty_order <0):')
                    order = client.new_order(symbol=symbol, side='BUY', positionSide = 'SHORT',  type='MARKET', quantity = abs(qty_order))
                    print(Fore.YELLOW + f'Close Postion For SELL :: {order}' + Style.RESET_ALL)
                elif(qty_order > 0):
                    print('we are inside    if(qty_order >0):')
                    order = client.new_order(symbol=symbol, side='SELL', positionSide = 'LONG',  type='MARKET', quantity = abs(qty_order))
                    print(Fore.RED + f'Close Postion For Buy :: {order}' + Style.RESET_ALL)




    def calculateProfitBasedOnPercentage(side,symbol, profitPercentage):
        price_precision= get_price_precision(symbol)
        entryPrice = getEntryPrice(symbol)
        if side == 'BUY':
            take_profit_price = round(entryPrice + (entryPrice * profitPercentage), price_precision) 
            return take_profit_price
        elif side == 'SELL':
            take_profit_price = round(entryPrice - (entryPrice * profitPercentage), price_precision)   
            return take_profit_price
        else :
            return 0  


    def open_order(symbol, side,invest,stop_price):

        # Get the current ticker price
        current_price = float(client.ticker_price(symbol)['price'])
        price_precision= get_price_precision(symbol)   
        # Specify the quantity you want to BUY or SELL    
      
        qty, plquantity,lastplqty = getQuantity(symbol, invest)


        # print('volume : ', volume)
        # print('current price',current_price)
        # print('quantity',qty)
        #qty= 400h
   
        if side == 'BUY':    
            try:        
            # Place a market BUY order
                stop_price = round(stop_price, price_precision)
                take_profit_price = round(current_price + (current_price * tp), price_precision)  
                second_take_profit_price = round(take_profit_price + (take_profit_price * (tp * 1.5)), price_precision) 
  
                print(Fore.GREEN + f'Placing Order For {symbol}' + Style.RESET_ALL)
                print(Fore.LIGHTGREEN_EX + f'Current Price => {current_price}' + Style.RESET_ALL)
                print(Fore.LIGHTGREEN_EX + f'Quamtity => {qty}' + Style.RESET_ALL)
                print(Fore.LIGHTGREEN_EX + f'Stop Price => {stop_price}' + Style.RESET_ALL)
                print(Fore.LIGHTGREEN_EX + f'Profit Price => {take_profit_price}' + Style.RESET_ALL)

                resp1 = BUYOrder(symbol,'BUY',qty) 
                print("\033[92mPlacing Order Response:", resp1, "\033[0m")
     
                #setStopLoss(symbol,stop_price,'SELL',qty)
                setProfit(symbol,take_profit_price,'SELL',plquantity)
                setProfit(symbol,second_take_profit_price,'SELL',lastplqty)

                return 1

            except ClientError as error:
                print(
                    "Found error. status: {}, error code: {}, error message: {}".format(
                        error.status_code, error.error_code, error.error_message
                    )                    
                )
                return -1
        if side == 'SELL' :
            try:        
                
            # Place a market BUY order
                #resp1 = client.new_order(symbol=symbol, side='SELL', type='MARKET', quantity=qty)
                #stop_price = round(current_price + current_price*sl, price_precision)
                stop_price = round(stop_price, price_precision)
                take_profit_price = round(current_price - current_price * tp, price_precision)
                second_take_profit_price = round(take_profit_price - take_profit_price * (tp * 1.5), price_precision)
                print(Fore.RED + f'Placing Order For {symbol}' + Style.RESET_ALL)
                print(Fore.LIGHTRED_EX + f'Current Price => {current_price}' + Style.RESET_ALL)
                print(Fore.LIGHTRED_EX + f'Quamtity => {qty}' + Style.RESET_ALL)
                print(Fore.LIGHTRED_EX + f'Stop Price => {stop_price}' + Style.RESET_ALL)
                print(Fore.LIGHTRED_EX + f'Profit Price => {take_profit_price}' + Style.RESET_ALL)
                resp1 = BUYOrder(symbol,'SELL',qty)
                print("\033[92mPlacing Order Response:", resp1, "\033[0m")
                #setStopLoss(symbol,stop_price,'BUY',qty)
                setProfit(symbol,take_profit_price,'BUY',plquantity)
                setProfit(symbol,second_take_profit_price,'BUY',lastplqty)

                return 1

            except ClientError as error:
                print(
                    "Found error. status: {}, error code: {}, error message: {}".format(
                        error.status_code, error.error_code, error.error_message
                    )
                    
                )   
                return -1
        sleep(3)


    def BUYOrder(symbol, side, qty):
        try:
            BUYOrder = client.new_order(symbol=symbol, side=side, type='MARKET', quantity=qty)
            return BUYOrder
        except Exception as error:
            print("An error occurred in BUYOrder:", error)
            # Handle the error as needed, e.g., logging, raising, or any other appropriate action


    @retry(MAXIMUM_NUMBER_OF_API_CALL_TRIES, lambda e: logging.error(f"ERROR in setStopLoss: {e}") or (ERROR, None))
    def setStopLoss(symbol, stop_price, side, qty):
        #resp2 = client.new_order(symbol=symbol, side=side, type='STOP_MARKET', quantity=qty, stopPrice=stop_price)
        resp2 = client.new_order(symbol=symbol, side=side, type='STOP_MARKET', stopPrice=stop_price, closePosition='true')
        print("\033[93mStop Loss:", resp2, "\033[0m")

    @retry(MAXIMUM_NUMBER_OF_API_CALL_TRIES, lambda e: logging.error(f"ERROR in setProfit: {e}") or (ERROR, None))
    def setProfit(symbol,take_profit_price,side,qty):
        #resp3 = client.new_order(symbol=symbol, side=side, type='TAKE_PROFIT_MARKET', quantity=qty, stopPrice=take_profit_price)
        resp3 = client.new_order(symbol=symbol, side=side, type='TAKE_PROFIT_MARKET', stopPrice=take_profit_price, closePosition='true')
        print("\033[94mTake Profit:", resp3, "\033[0m")
        time.sleep(3)
        
    @retry(MAXIMUM_NUMBER_OF_API_CALL_TRIES, lambda e: logging.error(f"ERROR in setHedgeProfit: {e}") or (ERROR, None))
    def setHedgeProfit(symbol,take_profit_price,side,posSide):
        price_precision = get_price_precision(symbol)
        take_profit_price =  round(take_profit_price,price_precision)  
        resp3 = client.new_order(symbol=symbol, side=side, positionSide=posSide, type='TAKE_PROFIT_MARKET', stopPrice=take_profit_price, closePosition='true')
        print("\033[94mTake Profit:", resp3, "\033[0m")
        time.sleep(3)
        
    @retry(MAXIMUM_NUMBER_OF_API_CALL_TRIES, lambda e: logging.error(f"ERROR in setHedgeProfit: {e}") or (ERROR, None))
    def setHedgeStopLoss(symbol,stop_price,side,posSide):
        closeOrder(symbol)
        price_precision = get_price_precision(symbol)
        stop_price =  round(stop_price,price_precision)  
        resp3 = client.new_order(symbol=symbol, side=side, positionSide=posSide, type='STOP_MARKET', stopPrice=stop_price, closePosition='true')
        print("\033[94mStop Loss:", resp3, "\033[0m")
        time.sleep(3)

    @retry(MAXIMUM_NUMBER_OF_API_CALL_TRIES, lambda e: logging.error(f"ERROR in setHedgeProfit: {e}") or (ERROR, None))
    def setHedgePartialStopLoss(symbol,stop_price,side,posSide,quantity):
        closeOrder(symbol)
        price_precision = get_price_precision(symbol)
        stop_price =  round(stop_price,price_precision)  
        resp3 = client.new_order(symbol=symbol, side=side, positionSide=posSide,quantity=quantity, type='STOP_MARKET', stopPrice=stop_price, workingType = 'MARK_PRICE',closePosition='false')
        print("\033[94mStop Loss:", resp3, "\033[0m")
        time.sleep(3)        

        


    @retry(MAXIMUM_NUMBER_OF_API_CALL_TRIES, lambda e: logging.error(f"ERROR in setStopLoss: {e}") or (ERROR, None))
    def hedgePosition(symbol, side, posSide, qty):
        resp2 = client.new_order(symbol=symbol, side=side,positionSide=posSide, type='MARKET', quantity=qty )
        print("\033[93mStop Loss:", resp2, "\033[0m")

    def closeOrder(symbol):
        try:
            orders = client.cancel_open_orders(symbol=symbol)
            return orders
        except ClientError as e:
            print("Error:", e)

    def getOrders(symbol):
        try:
            orders = client.get_orders(symbol=symbol)
            #print(orders)
            return orders
        except ClientError as e:
            print("Error:", e)

    def getOpenPosition(symbol):
        try:
            position = client.get_position_risk(symbol=symbol)
            filtered_data = [entry for entry in position if float(entry['positionAmt']) != 0.0]
            return filtered_data
        except ClientError as e:
            print("Error:", e)

    def getAllOpenPosition():
        try:
            time.sleep(0.3)  # brief pause to avoid rate limit; was 2s (caused sync timeout with many positions)
            position = client.get_position_risk()
            filtered_data = [entry for entry in position if float(entry['positionAmt']) != 0.0]
            return filtered_data
        except ClientError as e:
            print("Error:", e)
    
    def getmaxNotionalValue(symbol):
        try:
            position = client.get_position_risk(symbol=symbol)
            return position
        except ClientError as e:
            print("Error:", e)
            return 0

    def getEntryPrice(symbol):
        try:
            position = client.get_position_risk(symbol=symbol)
            filtered_data = [entry for entry in position if float(entry['positionAmt']) != 0.0]
            if( len(filtered_data) > 0) :
                return float(filtered_data[0]['breakEvenPrice'])
            else :
                return 0
        except ClientError as e:
            print("Error:", e)
            return 0

    def FixOrder(symbol):
        try:
            pos = getOpenPosition(symbol)
            qty = float(pos[0]['positionAmt'])
            unRealizedProfit = float(pos[0]['unRealizedProfit'])
            current_price = float(client.ticker_price(symbol)['price'])
            breakEvenPrice = float(pos[0]['breakEvenPrice'])
            price_precision = get_price_precision(symbol)

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

            elif qty < 0.0 and qty != 0:
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

        except Exception as error:
            print("An error occurred in FixOrder:", error)
            # Handle the error as needed, e.g., logging, raising, or any other appropriate action

    def getDateTime():
        try:
            res = client.time()
            ts = res['serverTime'] / 1000
            currentDateTime = datetime.datetime.fromtimestamp(ts)
            return currentDateTime
        except Exception as error:
            print("An error occurred in getDateTime:", error)

    def sleep_until_next_cycle():   
        currentDateTime = getDateTime()
        currentSecond = currentDateTime.second
        #print(currentDateTime,currentSecond)
        # Sleep until the next minute
        #print(currentDateTime)
        if currentSecond <= 60:
            sleep=60 - currentDateTime.second
            #print('wait tilllllllllllllllll::::::::::::::           ',sleep)
            return sleep
        else:
            return 0
        
    def changeLevrage(symbol,lev):
        try:
            response = client.change_leverage(symbol=symbol, leverage=lev, recvWindow=6000)
            logging.info(response)
        except ClientError as error:
            logging.error(
                "Found error. status: {}, error code: {}, error message: {}".format(
                    error.status_code, error.error_code, error.error_message
            )
        )

    def getData5m(SYMBOL):
        try:
            klines = client.klines(SYMBOL, '5m', limit=500)
            return_data = []
            for each in klines:
                return_data.append(float(each[4]))
            return np.array(return_data)
        except Exception as error:
            print("An error occurred in getData:", error)

    def getRSI(SYMBOL):
        try:
            closing_data = getData5m(SYMBOL)
            rsi = talib.RSI(closing_data, 7)[-1]
            return rsi
        except Exception as error:
            print("An error occurred in getRSI:", error)
        
    def getHistoricalData5m(symbol,min):

        try:
            df = pd.DataFrame(client.continuous_klines(symbol,'PERPETUAL',min,**{"limit": 500}))
            
        except ClientError as e:
            print(e)
            df = pd.DataFrame(client.continuous_klines(symbol,'PERPETUAL',min,**{"limit": 50}))
        df = df.iloc[:,:11]
        df.columns = ["Open Time","Open Price","High","Low","Close Price","Volume","Close Time","Q.A Volume","No. Of Trades","Taker BUY Volume","Taker BUY quote asset volume"]
        df=df.set_index("Open Time")
        df.index = pd.to_datetime(df.index,unit='ms', utc=True)
        
        #appendInExcel(df)
        #df.to_excel("continuous_klines.xlsx")
        df =df.astype(float)    
        return df
    
    def getHistoricalData1m(symbol):

        try:
            df = pd.DataFrame(client.continuous_klines(symbol,'PERPETUAL','1m',**{"limit": 5}))
            
        except ClientError as e:
            print(e)
            sleep(5)
            df = pd.DataFrame(client.continuous_klines(symbol,'PERPETUAL','1m',**{"limit": 5}))
        df = df.iloc[:,:11]
        df.columns = ["Open Time","Open Price","High","Low","Close Price","Volume","Close Time","Q.A Volume","No. Of Trades","Taker BUY Volume","Taker BUY quote asset volume"]
        df=df.set_index("Open Time")
        df.index = pd.to_datetime(df.index,unit='ms', utc=True)
        
        appendInExcel(df)
        #df.to_excel("continuous_klines.xlsx")
        df =df.astype(float)    
        return df

    def appendInExcel(df):
        try:
            with open('continuous_klines.csv', 'a') as f:
                df.to_csv(f, header=f.tell() == 0)
        except Exception as error:
            print("An error occurred in appendInExcel:", error)
            # Handle the error as needed, e.g., logging, raising, or any other appropriate action


    def getAllOrders(symbol):
        try:


            # Fetch all orders from the last month
            orders = client.get_all_orders(symbol)


            if orders:
                # Filter orders with status 'FILLED'
                filled_orders = [order for order in orders if order['status'] == 'FILLED']
                print(filled_orders)

                # Find the latest FILLED order based on time
                latest_filled_order = max(filled_orders, key=lambda order: order['time'])
                return latest_filled_order
            else:
                return 0
        except ClientError as e:
            print("Error:", e)
            return 0
        
    def getProfitTarget(side,symbol, profitPercentage):
        price_precision= get_price_precision(symbol)
        entryPrice = float(client.ticker_price(symbol)['price'])
        if side == 'BUY':
            take_profit_price = round(entryPrice + (entryPrice * profitPercentage), price_precision) 
            return take_profit_price
        elif side == 'SELL':
            take_profit_price = round(entryPrice - (entryPrice * profitPercentage), price_precision)   
            return take_profit_price
        else :
            return 0
except Exception as error:
    print("An error occurred getProfitTarget FUNCTION :", error)

def speak(text):
    try:
        # Initialize COM in the thread
        # pythoncom.CoInitialize()

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
        # Uninitialize COM to prevent resource leaks
        # pythoncom.CoUninitialize()

def text_to_speech(text):
    #### This is only work in the local computer

    # Run `speak` function in a separate thread
    thread = threading.Thread(target=speak, args=(text,))
    thread.start()
    thread.join()  # Wait for the thread to complete if needed

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
    return(data.rolling(window = window).mean())

def bollinger_band(data, sma, window, nstd):
    std = data.rolling(window = window).std()
    upper_band = sma + std * nstd
    lower_band = sma - std * nstd
    
    return upper_band, lower_band

def strategyBollinegerBand(symbol,min):

    df=getHistoricalData5m(symbol,min)
    sma = simpmovavg(df['Open Price'],window=20)  
    nstd = 2
    upband,lband =  bollinger_band(df[f'Open Price'], sma, 20, nstd)
    current_price = float(client.ticker_price(symbol)['price'])
    if(current_price > upband.iloc[-1]):
        print("\033[91mSELL", symbol ,"\033[0m")
            #print(sma,"--------")
        print('xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx')
        print ('Upper Band',upband.iloc[-1])
        print('=======lower band',lband.iloc[-1])
        print('****************************',current_price)
        return 2

    elif(current_price < lband.iloc[-1]):
        print("\033[92mBUY", symbol , "\033[0m")   

        #print(sma,"--------")
        print('xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx')
        print ('Upper Band',upband.iloc[-1])
        print('=======lower band',lband.iloc[-1])
        print('****************************',current_price)
        return 1
    else:
        
        return 0


def getLeverage(symbol):
    # Fetch leverage brackets from the client
    leverage_brackets = client.leverage_brackets()
    
    # Iterate over each item in leverage_brackets
    for item in leverage_brackets:
        # Check if the symbol matches the desired symbol
        if item['symbol'] == symbol:
            # Retrieve the brackets for the symbol
            brackets_for_symbol = item['brackets']
            
            # Iterate over the brackets for the symbol
            for bracket in brackets_for_symbol:
                # Check if the bracket number is 1
                if bracket['bracket'] == 1:
                    # Return the initial leverage of bracket 1
                    print(bracket['initialLeverage'])
                    return bracket['initialLeverage']
            else:
                # If bracket 1 is not found, return None
                return 0
                
    # If the symbol is not found in leverage brackets, return None
    return 0

def cleanOrders():
    orders = client.get_orders()
    for item in orders:
        # Check if the symbol matches the desired symbol
        if (item['type'] == 'TAKE_PROFIT_MARKET' or item['type'] == 'STOP_MARKET'):
            symbol = item['symbol']
            pos =getOpenPosition(symbol)
            filtered_data = [entry for entry in pos if float(entry['positionAmt']) != 0.0]
            # Count the filtered entries
            count_filtered = len(filtered_data)
            if(count_filtered == 0 or count_filtered > 1):
                closeOrder(symbol)
                print(f'Order is Clean for symbol -- {symbol}')

        else:
            print('There is no Order to Clean')

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


def getQuantity(symbol,invest):
    try:
        current_price = float(client.ticker_price(symbol)['price'])
        #fivepercentage = get_avail_balance() * invest # invest % of the available balance
        quantitywithleverage = (invest / current_price) 
        qty_precision = get_qty_precision(symbol)
        quantity =  round(quantitywithleverage,qty_precision)   
        plquantity = round(quantitywithleverage /2,qty_precision)
        lastplquantity = round(plquantity /2,qty_precision)
        return quantity,plquantity,lastplquantity
    except Exception as error:
        print("An error occurred in getQuantity:", error)
        # Handle the error as needed, e.g., logging, raising, or any other appropriate action


# getAllOpenPosition() is now called via API endpoint /api/sync-open-positions

# print(getOpenPosition('IDUSDT'))        





