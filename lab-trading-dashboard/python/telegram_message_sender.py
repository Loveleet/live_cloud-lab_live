from datetime import datetime, timezone

import telegram
import logging
import asyncio

# Configure logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

# Initialize Telegram Bot
telegram_bot = None
SEND_TELEGRAM_MESSAGE = True
TELEGRAM_API_KEY = "7275768507:AAHAArpfUD1PvPMXxnK2dboEcBuN5YdGLPo"
TELEGRAM_USER_IDS = "5205471359,5503047439"

if SEND_TELEGRAM_MESSAGE:
    try:
        telegram_bot = telegram.Bot(token=TELEGRAM_API_KEY)
        logging.info("Telegram bot initialized successfully.")
    except telegram.error.TelegramError as e:
        logging.error(f"Failed to initialize Telegram bot: {e}")


async def send_message_to_users(message):
    """
    Send a single message to multiple users concurrently.
    """
    if not SEND_TELEGRAM_MESSAGE or telegram_bot is None:
        logging.warning("Telegram messaging is disabled or the bot is not initialized.")
        return
    
    user_ids = [user_id.strip() for user_id in TELEGRAM_USER_IDS.split(',')]
    tasks = [_send_message_to_user(user_id, message) for user_id in user_ids]
    await asyncio.gather(*tasks)  # Run all send tasks concurrently


async def _send_message_to_user(user_id, message):
    """
    Send a message to a single user.
    """
    try:
        logging.info(f"Sending message to {user_id}: {message}")
        await telegram_bot.send_message(chat_id=user_id, text=message)
    except telegram.error.TelegramError as e:
        logging.error(f"Telegram error sending to user {user_id}: {e}")
    except Exception as e:
        logging.error(f"Unexpected error sending to user {user_id}: {e}")


async def send_multiple_messages(message_list):
    """
    Send multiple messages to multiple users concurrently.
    """
    for position in message_list:
        update_time_str = datetime.fromtimestamp(position['updateTime'] / 1000, tz=timezone.utc).strftime('%d %B %Y %H:%M')
        message = (
            "---------------------------------------------\n"
            f"updateTime: {update_time_str}\n"
            f"symbol: {position['symbol']}\n"
            f"positionAmt: {position['positionAmt']}\n"
            f"entryPrice: {position['entryPrice']}\n"
            f"positionSide: {position['positionSide']}\n"
            f"unRealizedProfit: {position['unRealizedProfit']}\n"
            "---------------------------------------------"
        )
        await send_message_to_users(message)


# if __name__ == "__main__":
#     asyncio.run(send_message_to_users("Test message from olab_M2"))