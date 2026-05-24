"""Задачи для APScheduler: периодический парсинг каналов."""

from db import repository as repo
from parser.channel_parser import parse_channel
from utils.logger import log


_running = False


async def parse_all_channels_job() -> None:
    """Один проход парсинга по всем каналам из БД. Защита от наложения запусков."""
    global _running
    if _running:
        log.warning("Парсинг уже идёт, пропускаю этот тик")
        return

    _running = True
    try:
        channels = await repo.get_all_channels()
        if not channels:
            log.info("Парсинг: каналов в БД нет, пропускаю")
            return

        log.info(f"Парсинг: {len(channels)} каналов")
        total = 0
        for ch in channels:
            try:
                added = await parse_channel(ch)
                total += added
            except Exception as e:
                log.exception(f"Ошибка при парсинге {ch['username']}: {e}")
        log.info(f"Парсинг завершён. Добавлено постов за тик: {total}")
    finally:
        _running = False
