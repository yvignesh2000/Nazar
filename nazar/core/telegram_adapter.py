"""
Telegram transport adapter for Nazar.

Uses long polling for development so the product can be tested without
another webhook setup loop.
"""

from __future__ import annotations

import json
import os
import ssl
from pathlib import Path
from typing import Optional

import aiohttp

try:
    import certifi
except Exception:
    certifi = None

DATA_DIR = Path(__file__).parent.parent / "data"
DATA_DIR.mkdir(parents=True, exist_ok=True)
STATE_PATH = DATA_DIR / "telegram_state.json"


def _ssl_context():
    if certifi is None:
        return None
    try:
        return ssl.create_default_context(cafile=certifi.where())
    except Exception:
        return None


def telegram_bot_token() -> str:
    return (os.environ.get("TELEGRAM_BOT_TOKEN") or "").strip()


def telegram_bot_username() -> str:
    return (os.environ.get("TELEGRAM_BOT_USERNAME") or "").strip()


def telegram_ready() -> bool:
    return bool(telegram_bot_token())


def telegram_contact_key(chat_id: str | int) -> str:
    return f"telegram:{str(chat_id).strip()}"


def is_telegram_contact_key(value: str) -> bool:
    return str(value or "").strip().startswith("telegram:")


def telegram_chat_id(value: str | int) -> str:
    raw = str(value or "").strip()
    if raw.startswith("telegram:"):
        return raw.split(":", 1)[1].strip()
    return raw


def load_update_offset() -> Optional[int]:
    try:
        raw = json.loads(STATE_PATH.read_text(encoding="utf-8"))
        offset = raw.get("offset")
        return int(offset) if offset is not None else None
    except Exception:
        return None


def save_update_offset(offset: int) -> None:
    STATE_PATH.write_text(json.dumps({"offset": int(offset)}, ensure_ascii=False), encoding="utf-8")


async def telegram_api(method: str, payload: Optional[dict] = None, timeout: int = 30) -> dict:
    token = telegram_bot_token()
    if not token:
        raise RuntimeError("Telegram bot is not configured")
    url = f"https://api.telegram.org/bot{token}/{method}"
    async with aiohttp.ClientSession() as session:
        async with session.post(
            url,
            json=payload or {},
            ssl=_ssl_context(),
            timeout=aiohttp.ClientTimeout(total=timeout),
        ) as resp:
            data = await resp.json(content_type=None)
            if resp.status != 200 or not data.get("ok", False):
                description = data.get("description") or f"Telegram API error {resp.status}"
                raise RuntimeError(description)
            return data


async def get_updates(offset: Optional[int] = None, timeout: int = 2) -> list[dict]:
    payload = {"timeout": max(1, int(timeout))}
    if offset is not None:
        payload["offset"] = int(offset)
    data = await telegram_api("getUpdates", payload=payload, timeout=max(10, timeout + 5))
    return data.get("result") or []


async def send_telegram_message(chat: str | int, text: str) -> dict:
    return await telegram_api(
        "sendMessage",
        {
            "chat_id": telegram_chat_id(chat),
            "text": text,
        },
    )


def normalize_text_update(update: dict) -> Optional[dict]:
    message = update.get("message") or update.get("edited_message")
    if not message:
        return None
    text = (message.get("text") or "").strip()
    if not text:
        return None
    chat = message.get("chat") or {}
    sender = message.get("from") or {}
    first_name = (sender.get("first_name") or "").strip()
    last_name = (sender.get("last_name") or "").strip()
    full_name = " ".join(part for part in [first_name, last_name] if part).strip()
    username = (sender.get("username") or "").strip()
    display_name = full_name or username or str(chat.get("id") or "")
    return {
        "update_id": update.get("update_id"),
        "message_id": message.get("message_id"),
        "chat_id": str(chat.get("id") or ""),
        "text": text,
        "name": display_name,
        "username": username,
    }
