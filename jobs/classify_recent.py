"""Фоновая задача: классифицирует свежие посты (category=NULL) в одну из категорий.

Раз в 10 минут берёт батч из последних 2 суток, прогоняет через AI-классификатор,
сохраняет в БД. Старые посты не трогает.
"""

from ai.classifier import classify_posts
from ai.gemini_client import GeminiQuotaError
from config import CLASSIFY_BATCH_SIZE, CLASSIFY_FRESH_DAYS
from db import repository as repo
from utils.logger import log


async def classify_recent_job() -> None:
    batch = await repo.get_posts_without_category(limit=CLASSIFY_BATCH_SIZE, fresh_days=CLASSIFY_FRESH_DAYS)
    if not batch:
        return

    log.info(f"classify_recent: классифицирую {len(batch)} свежих постов")
    try:
        cats = await classify_posts([p["text"] for p in batch])
    except GeminiQuotaError:
        log.info("classify_recent: квота 429, попробую через тик")
        return
    except Exception as e:
        log.warning(f"classify_recent упал: {type(e).__name__}: {e}")
        return

    saved = await repo.set_post_categories(list(zip([p["id"] for p in batch], cats)))
    recognized = sum(1 for c in cats if c is not None)
    log.info(f"classify_recent: сохранено {saved}, распознано {recognized}/{len(batch)}")
