"""Send a message to the owner's phone via a Telegram bot (optional).

Needs TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID; without them it only prints.
"""
from __future__ import annotations

import os

import requests


def notify(text: str) -> None:
    print(text)
    token = os.environ.get("TELEGRAM_BOT_TOKEN")
    chat = os.environ.get("TELEGRAM_CHAT_ID")
    if not (token and chat):
        return
    try:
        requests.post(
            f"https://api.telegram.org/bot{token}/sendMessage",
            data={"chat_id": chat, "text": text, "disable_web_page_preview": "true"},
            timeout=20,
        ).raise_for_status()
    except requests.RequestException as e:  # a failed notification must never fail a publish
        print(f"(telegram notification failed: {e})")
