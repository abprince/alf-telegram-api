"""
Run this ONCE, on your own PC (not on Render).

It logs your Telegram user account in interactively (asks for your phone
number, then the login code Telegram sends you) and prints a session
string. Paste that string into Render as the TELEGRAM_SESSION env var.

Never commit the printed string anywhere public — it is equivalent to
being logged into your Telegram account.
"""

from telethon.sync import TelegramClient
from telethon.sessions import StringSession

# Get these from https://my.telegram.org -> API Development Tools
API_ID = int(input("API_ID: ").strip())
API_HASH = input("API_HASH: ").strip()

with TelegramClient(StringSession(), API_ID, API_HASH) as client:
    print("\nLogin successful.\n")
    print("=" * 60)
    print("Your session string (save this in Render as TELEGRAM_SESSION):")
    print("=" * 60)
    print(client.session.save())
    print("=" * 60)
