"""Фоновая задача: эмбеддит свежие посты, у которых embedding ещё NULL.

Работает мягко: раз в EMBEDDING_TICK_MINUTES минут берёт до EMBEDDING_BATCH_PER_TICK
постов из последних EMBEDDING_FRESH_DAYS суток. Старые (исторические) посты не трогает.
При 429 — пропускает тик и пробует на следующем.
"""

from datetime import datetime, timedelta, timezone

from ai.embeddings import embed_batch, QuotaExceededError
from db import repository as repo
from db.connection import get_pool, is_pgvector_available
from utils.logger import log


EMBEDDING_BATCH_PER_TICK = 50    # 50/10мин = 300/час, 7200/сутки макс — хватит на 14 каналов
EMBEDDING_FRESH_DAYS = 2          # эмбеддим только посты не старше 2 суток (исторические не трогаем)


async def embed_recent_job() -> None:
    if not is_pgvector_available():
        return

    pool = get_pool()
    since = datetime.now(timezone.utc) - timedelta(days=EMBEDDING_FRESH_DAYS)

    async with pool.acquire() as conn:
        rows = await conn.fetch(
            "SELECT id, text FROM posts "
            "WHERE embedding IS NULL AND posted_at >= $1 "
            "ORDER BY posted_at DESC LIMIT $2",
            since, EMBEDDING_BATCH_PER_TICK,
        )
    if not rows:
        return

    batch = [dict(r) for r in rows]
    log.info(f"embed_recent: эмбеддю {len(batch)} свежих постов")
    try:
        vectors = await embed_batch([p["text"] for p in batch], task_type="RETRIEVAL_DOCUMENT")
    except QuotaExceededError:
        log.info("embed_recent: квота 429, попробую через тик")
        return
    except Exception as e:
        log.warning(f"embed_recent упал: {type(e).__name__}: {e}")
        return

    saved = await repo.set_post_embeddings(list(zip([p["id"] for p in batch], vectors)))
    log.info(f"embed_recent: сохранено {saved}/{len(batch)}")
