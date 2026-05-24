"""Одноразовый скрипт: создать StringSession для Telethon.

Запусти ЛОКАЛЬНО ОДИН РАЗ:
    python generate_session.py

Скрипт спросит API_ID, API_HASH, номер телефона и код из Telegram.
В конце напечатает длинную строку — это и есть твоя сессия.
Скопируй её в .env как TELETHON_SESSION=...
Эту же строку положи в Railway Variables, чтобы парсер работал на сервере.

ВАЖНО: сессия = доступ к твоему аккаунту Telegram. НЕ публикуй её, НЕ коммить в git.
"""

import asyncio
import os

from dotenv import load_dotenv
from telethon import TelegramClient
from telethon.sessions import StringSession


async def main() -> None:
    load_dotenv()
    api_id_env = os.getenv("TELEGRAM_API_ID")
    api_hash_env = os.getenv("TELEGRAM_API_HASH")

    if api_id_env and api_id_env != "stub":
        api_id = int(api_id_env)
        print(f"Использую TELEGRAM_API_ID из .env: {api_id}")
    else:
        api_id = int(input("TELEGRAM_API_ID: ").strip())

    if api_hash_env and api_hash_env != "stub":
        api_hash = api_hash_env
        print("Использую TELEGRAM_API_HASH из .env")
    else:
        api_hash = input("TELEGRAM_API_HASH: ").strip()

    async with TelegramClient(StringSession(), api_id, api_hash) as client:
        session_str = client.session.save()
        me = await client.get_me()
        print()
        print(f"Авторизован как: {me.first_name} (@{me.username}) id={me.id}")
        print()
        print("=" * 60)
        print("TELETHON_SESSION (скопируй целиком, без переносов строк):")
        print("=" * 60)
        print(session_str)
        print("=" * 60)


if __name__ == "__main__":
    asyncio.run(main())
