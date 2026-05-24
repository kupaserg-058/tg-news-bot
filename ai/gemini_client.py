"""Обёртка над google-genai SDK с кешированием и поддержкой Google Search grounding.

API: единственная функция `generate(prompt, query_type, use_search=False)`.
Внутри:
1. Проверяем кеш — если есть валидная запись, возвращаем сразу.
2. Иначе вызываем основную модель. При ошибке (429, 5xx, неподдержка search и т.п.) — fallback-модель.
3. Сохраняем в кеш и возвращаем.
"""

import os

from google import genai
from google.genai import types
from google.genai.errors import ClientError

from config import GEMINI_MODEL, GEMINI_FALLBACK_MODEL
from ai import cache
from utils.logger import log


class GeminiQuotaError(Exception):
    """Поднимается при HTTP 429 от Gemini. Хендлеры ловят и шлют понятное сообщение."""


def _is_quota_error(e: Exception) -> bool:
    if isinstance(e, ClientError):
        # google-genai 0.3.0 кладёт код в args/message
        msg = str(e)
        return "429" in msg or "RESOURCE_EXHAUSTED" in msg or "quota" in msg.lower()
    return False


_client: genai.Client | None = None


def _get_client() -> genai.Client:
    global _client
    if _client is None:
        api_key = os.environ.get("GEMINI_API_KEY")
        if not api_key:
            raise RuntimeError("GEMINI_API_KEY не задан в окружении")
        _client = genai.Client(api_key=api_key)
    return _client


def _build_config(use_search: bool) -> types.GenerateContentConfig | None:
    if not use_search:
        return None
    return types.GenerateContentConfig(
        tools=[types.Tool(google_search=types.GoogleSearch())],
    )


def _extract_sources(response) -> list[dict]:
    """Извлекает источники из grounding metadata. Возвращает [{title, uri}]."""
    try:
        candidate = response.candidates[0]
        gm = getattr(candidate, "grounding_metadata", None)
        if not gm:
            return []
        chunks = getattr(gm, "grounding_chunks", None) or []
        sources = []
        for ch in chunks:
            web = getattr(ch, "web", None)
            if web:
                sources.append({
                    "title": getattr(web, "title", "") or "",
                    "uri": getattr(web, "uri", "") or "",
                })
        return sources
    except (AttributeError, IndexError):
        return []


def _format_with_sources(text: str, sources: list[dict]) -> str:
    if not sources:
        return text
    lines = [text, "", "<b>📚 Источники из поиска:</b>"]
    seen = set()
    n = 0
    for s in sources:
        uri = s.get("uri", "")
        title = s.get("title", "") or uri
        if uri in seen or not uri:
            continue
        seen.add(uri)
        n += 1
        lines.append(f'{n}. <a href="{uri}">{title}</a>')
        if n >= 10:
            break
    return "\n".join(lines)


async def _call_model(prompt: str, model: str, use_search: bool) -> str:
    client = _get_client()
    config = _build_config(use_search)
    response = await client.aio.models.generate_content(
        model=model,
        contents=prompt,
        config=config,
    )
    text = (response.text or "").strip()
    if not text:
        raise RuntimeError("Gemini вернул пустой ответ")
    if use_search:
        sources = _extract_sources(response)
        text = _format_with_sources(text, sources)
    return text


async def generate(
    prompt: str,
    query_type: str,
    use_search: bool = False,
    use_cache: bool = True,
) -> str:
    """Главная точка входа. query_type — один из ключей CACHE_TTL: digest, search, why, context, map, free."""
    primary = GEMINI_MODEL

    if use_cache:
        cached = await cache.get(prompt, primary, use_search)
        if cached is not None:
            return cached

    try:
        text = await _call_model(prompt, primary, use_search)
        model_used = primary
    except Exception as e:
        if _is_quota_error(e):
            raise GeminiQuotaError(str(e)[:300]) from e
        log.warning(f"Gemini {primary} упал ({type(e).__name__}: {e}). Пробую fallback {GEMINI_FALLBACK_MODEL}")
        try:
            text = await _call_model(prompt, GEMINI_FALLBACK_MODEL, use_search)
        except Exception as e2:
            if _is_quota_error(e2):
                raise GeminiQuotaError(str(e2)[:300]) from e2
            raise
        model_used = GEMINI_FALLBACK_MODEL

    if use_cache:
        await cache.put(prompt, model_used, use_search, text, query_type)

    return text
