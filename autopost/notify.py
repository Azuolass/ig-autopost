"""Send a message to the owner's phone (Discord webhook, optionally Telegram).

Discord:  DISCORD_WEBHOOK_URL
Telegram: TELEGRAM_BOT_TOKEN + TELEGRAM_CHAT_ID
Without either it only prints to the run log.
"""
from __future__ import annotations

import os

import requests


def _discord(url: str, text: str) -> None:
    # Discord allows 2000 characters per message.
    for i in range(0, len(text), 1900):
        requests.post(url, json={"content": text[i : i + 1900], "username": "Instagram autopilot"}, timeout=20
                      ).raise_for_status()


def _telegram(token: str, chat: str, text: str) -> None:
    requests.post(
        f"https://api.telegram.org/bot{token}/sendMessage",
        data={"chat_id": chat, "text": text, "disable_web_page_preview": "true"},
        timeout=20,
    ).raise_for_status()


def notify(text: str) -> None:
    print(text)
    try:  # a failed notification must never fail a publish
        if os.environ.get("DISCORD_WEBHOOK_URL"):
            _discord(os.environ["DISCORD_WEBHOOK_URL"], text)
        if os.environ.get("TELEGRAM_BOT_TOKEN") and os.environ.get("TELEGRAM_CHAT_ID"):
            _telegram(os.environ["TELEGRAM_BOT_TOKEN"], os.environ["TELEGRAM_CHAT_ID"], text)
    except requests.RequestException as e:
        print(f"(notification failed: {e})")
