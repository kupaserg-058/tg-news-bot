"""Singleton-обёртка над TelegramClient на StringSession.
Стейт-фул сессия в файле НЕ используется — на Railway нет персистентной FS.
"""

from telethon import TelegramClient
from telethon.sessions import StringSession

from utils.logger import log


_client: TelegramClient | None = None


async def init_client(api_id: int, api_hash: str, session_str: str) -> TelegramClient:
    global _client
    if _client is not None and _client.is_connected():
        return _client

    _client = TelegramClient(StringSession(session_str), api_id, api_hash)
    await _client.start()
    me = await _client.get_me()
    log.info(f"Telethon подключён: @{me.username or me.first_name} (id={me.id})")
    return _client


def get_client() -> TelegramClient:
    if _client is None:
        raise RuntimeError("Telethon client не инициализирован. Вызови init_client() первым.")
    return _client


async def disconnect_client() -> None:
    global _client
    if _client is not None:
        await _client.disconnect()
        _client = None
        log.info("Telethon disconnected")
