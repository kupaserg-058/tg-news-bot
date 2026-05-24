"""Кеш ответов Gemini в PostgreSQL. Ключ = sha256(model + prompt + флаг grounding)."""

import hashlib

from config import CACHE_TTL
from db import repository as repo
from utils.logger import log


def make_key(prompt: str, model: str, use_search: bool) -> str:
    raw = f"{model}|{'g' if use_search else 'n'}|{prompt}"
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


async def get(prompt: str, model: str, use_search: bool) -> str | None:
    key = make_key(prompt, model, use_search)
    row = await repo.get_cached_response(key)
    if row:
        log.info(f"Cache HIT [{model}] key={key[:8]}…")
        return row["response"]
    return None


async def put(
    prompt: str,
    model: str,
    use_search: bool,
    response: str,
    query_type: str,
) -> None:
    key = make_key(prompt, model, use_search)
    ttl = CACHE_TTL.get(query_type, 1800)
    await repo.set_cached_response(key, query_type, prompt, response, model, ttl)
    log.info(f"Cache PUT [{model}] type={query_type} ttl={ttl}s key={key[:8]}…")
