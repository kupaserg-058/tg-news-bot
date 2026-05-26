"""AI-классификатор постов в фиксированные категории.

Использует gemini-2.5-flash через единый GeminiClient. Одним запросом обрабатывает
batch_size постов (по умолчанию 25). Промпт пронумерованный, ответ парсится regex'ом.
"""

import re

from config import CATEGORIES, CATEGORY_IDS, CLASSIFY_BATCH_SIZE
from ai import gemini_client
from ai.gemini_client import GeminiQuotaError
from utils.logger import log


_CATEGORY_LIST_TXT = ", ".join(cid for cid, _ in CATEGORIES)


def _truncate(text: str, max_chars: int = 600) -> str:
    text = " ".join((text or "").split())
    if len(text) > max_chars:
        return text[:max_chars - 1] + "…"
    return text


def _build_prompt(texts: list[str]) -> str:
    lines = []
    for i, t in enumerate(texts, 1):
        lines.append(f"{i}: {_truncate(t)}")
    block = "\n".join(lines)
    return f"""Ты классификатор. Я даю тебе пронумерованные посты из новостных каналов.
Каждому присвой РОВНО ОДНУ категорию из списка:
{_CATEGORY_LIST_TXT}

Правила:
- politics — внутренняя и внешняя политика, выборы, законы, дипломатия
- economy — рынки, бизнес, валюта, инфляция, корпорации (без IT), нефть, цены
- it — программирование, ИИ, гаджеты, IT-компании, кибербезопасность, технологии
- conflict — войны, теракты, военные операции, СВО, ракетные удары
- society — происшествия, ЧС, образование, медицина, демография, преступления
- culture — кино, музыка, литература, искусство, шоу-бизнес, религия
- sport — все виды спорта
- science — научные открытия, космос, физика, биология (но не IT/гаджеты)
- other — реклама, юмор, мемы, всё что не подходит явно

Ответ строго в формате (без пояснений, без markdown):
1: politics
2: economy
3: it
...

Посты:
{block}
"""


_ANSWER_LINE = re.compile(r"^\s*(\d+)\s*[:=\-—]\s*([a-z_]+)\s*$", re.IGNORECASE | re.MULTILINE)


def _parse_response(text: str, n: int) -> list[str | None]:
    """Парсит ответ модели в список из n категорий (None если не распарсилось / не из словаря)."""
    result: list[str | None] = [None] * n
    for m in _ANSWER_LINE.finditer(text):
        idx = int(m.group(1))
        cat = m.group(2).lower()
        if 1 <= idx <= n and cat in CATEGORY_IDS:
            result[idx - 1] = cat
    return result


async def classify_posts(texts: list[str]) -> list[str | None]:
    """Возвращает категорию для каждого текста (None если не удалось определить).
    Дробит на батчи по CLASSIFY_BATCH_SIZE. При 429 пробрасывает GeminiQuotaError."""
    if not texts:
        return []

    out: list[str | None] = []
    for i in range(0, len(texts), CLASSIFY_BATCH_SIZE):
        chunk = texts[i:i + CLASSIFY_BATCH_SIZE]
        prompt = _build_prompt(chunk)
        try:
            answer = await gemini_client.generate(
                prompt,
                query_type="classify",
                use_search=False,
                use_cache=False,  # классификация одноразовая на каждый пост
            )
        except GeminiQuotaError:
            raise
        except Exception as e:
            log.warning(f"classify_posts: упал ({type(e).__name__}: {e}). Возвращаю None для {len(chunk)} постов.")
            out.extend([None] * len(chunk))
            continue
        cats = _parse_response(answer, len(chunk))
        # Если AI ничего не понял (все None) — логируем, не падаем
        recognized = sum(1 for c in cats if c is not None)
        if recognized < len(chunk):
            log.info(f"classify_posts: {recognized}/{len(chunk)} распознано из батча")
        out.extend(cats)
    return out
