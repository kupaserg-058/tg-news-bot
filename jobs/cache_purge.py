"""Периодическая очистка: истёкший Gemini-кеш + старые записи query_log (>30 дней)."""

from db import repository as repo
from utils.logger import log


async def purge_cache_job() -> None:
    n_cache = await repo.purge_expired_cache()
    n_log = await repo.purge_old_query_log(days=30)
    if n_cache or n_log:
        log.info(f"Purge: кеш={n_cache}, query_log>30д={n_log}")
