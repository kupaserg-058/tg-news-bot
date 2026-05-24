"""Парсинг каналов: первичный backfill (последние N дней) и инкрементальное обновление."""

import asyncio
from datetime import datetime, timedelta, timezone

from telethon.errors import FloodWaitError, ChannelPrivateError, UsernameNotOccupiedError

from config import BACKFILL_DAYS
from db import repository as repo
from parser.telethon_client import get_client
from utils.logger import log


BATCH_SIZE = 100  # сколько постов копим перед массовой записью в БД


def _build_link(username: str, msg_id: int) -> str:
    return f"https://t.me/{username.lstrip('@')}/{msg_id}"


# Эмбеддинги при парсинге НЕ считаются (квота). Это делает отдельная фоновая задача
# jobs/embed_recent.embed_recent_job тихо догоняет свежие посты раз в 10 минут.


async def _process_messages(channel: dict, messages_iter) -> tuple[int, int]:
    """Итерирует сообщения, копит батч, пишет в БД. Embeddings не считаются —
    их добавит фоновая задача embed_recent_job."""
    batch: list[dict] = []
    total = 0
    max_msg_id = channel["last_parsed_msg_id"]

    async for msg in messages_iter:
        if not msg.message:
            if msg.id > max_msg_id:
                max_msg_id = msg.id
            continue

        batch.append({
            "channel_id": channel["id"],
            "tg_message_id": msg.id,
            "text": msg.message,
            "posted_at": msg.date,
            "link": _build_link(channel["username"], msg.id),
        })
        if msg.id > max_msg_id:
            max_msg_id = msg.id

        if len(batch) >= BATCH_SIZE:
            await repo.bulk_insert_posts(batch)
            total += len(batch)
            batch.clear()

    if batch:
        await repo.bulk_insert_posts(batch)
        total += len(batch)

    return total, max_msg_id


async def _resolve_entity(username: str):
    client = get_client()
    try:
        return await client.get_entity(username)
    except (ChannelPrivateError, UsernameNotOccupiedError, ValueError) as e:
        log.warning(f"Не удалось получить канал {username}: {e}")
        return None


async def backfill_channel(channel: dict, days: int = BACKFILL_DAYS) -> int:
    """Загрузить последние `days` дней истории канала. Возвращает количество добавленных постов."""
    client = get_client()
    entity = await _resolve_entity(channel["username"])
    if entity is None:
        return 0

    offset_date = datetime.now(timezone.utc) - timedelta(days=days)
    log.info(f"Backfill {channel['username']}: загружаю с {offset_date.date()}...")

    try:
        messages_iter = client.iter_messages(
            entity,
            offset_date=offset_date,
            reverse=True,
        )
        total, max_id = await _process_messages(channel, messages_iter)
    except FloodWaitError as e:
        log.warning(f"FloodWait на {channel['username']}: ждём {e.seconds}s")
        await asyncio.sleep(e.seconds + 1)
        return 0

    if max_id > channel["last_parsed_msg_id"]:
        await repo.update_last_parsed(channel["id"], max_id)
    log.info(f"Backfill {channel['username']}: {total} новых постов, max_msg_id={max_id}")
    return total


async def update_channel(channel: dict) -> int:
    """Догрузить посты с момента last_parsed_msg_id. Embeddings добавит фоновая задача."""
    client = get_client()
    entity = await _resolve_entity(channel["username"])
    if entity is None:
        return 0

    try:
        messages_iter = client.iter_messages(
            entity,
            min_id=channel["last_parsed_msg_id"],
            reverse=True,
        )
        total, max_id = await _process_messages(channel, messages_iter)
    except FloodWaitError as e:
        log.warning(f"FloodWait на {channel['username']}: ждём {e.seconds}s")
        await asyncio.sleep(e.seconds + 1)
        return 0

    if max_id > channel["last_parsed_msg_id"]:
        await repo.update_last_parsed(channel["id"], max_id)
    if total:
        log.info(f"Update {channel['username']}: {total} новых постов")
    return total


async def parse_channel(channel: dict) -> int:
    """Единый вход: если канал ни разу не парсился — backfill, иначе update."""
    if channel["last_parsed_msg_id"] == 0:
        return await backfill_channel(channel)
    return await update_channel(channel)
