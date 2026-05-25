"""Эмбеддинги через прямой REST к Google Generative Language API.

gemini-embedding-001 (3072d) поддерживает только одиночный :embedContent.
Поэтому в embed_batch — конкурентные одиночные запросы (asyncio.gather + semaphore).
"""

import asyncio
import os
from typing import Optional

import httpx
import numpy as np

from config import EMBEDDING_MODEL, EMBEDDING_DIM, EMBEDDING_CONCURRENCY, EMBEDDING_INPUT_CHARS
from utils.logger import log


API_BASE = "https://generativelanguage.googleapis.com/v1beta"

# Список моделей в порядке предпочтения. EMBEDDING_MODEL первый, остальные fallback.
CANDIDATE_MODELS = [
    EMBEDDING_MODEL,
    "gemini-embedding-001",
    "gemini-embedding-2",
    "gemini-embedding-2-preview",
]


_resolved_model: Optional[str] = None


class QuotaExceededError(Exception):
    """HTTP 429. Внешний код решает: остановить бэкфилл, выждать и т.п."""


def _truncate(text: str) -> str:
    text = " ".join((text or "").split())
    if len(text) > EMBEDDING_INPUT_CHARS:
        return text[:EMBEDDING_INPUT_CHARS]
    return text


def _api_key() -> str:
    key = os.environ.get("GEMINI_API_KEY")
    if not key:
        raise RuntimeError("GEMINI_API_KEY не задан")
    return key


def vector_to_pg(v: np.ndarray | list[float] | None) -> str | None:
    """Сериализация в pgvector-строку. Возвращает None если вектор битый."""
    if v is None:
        return None
    arr = np.asarray(v, dtype=np.float32)
    if arr.size != EMBEDDING_DIM:
        log.warning(f"Пропускаю вектор неверной длины: {arr.size} (ожидаю {EMBEDDING_DIM})")
        return None
    if not np.isfinite(arr).all():
        log.warning("Пропускаю вектор с NaN/Inf")
        return None
    return "[" + ",".join(f"{x:.6f}" for x in arr) + "]"


def pg_to_vector(s) -> np.ndarray | None:
    """Десериализация pgvector ('[x,y,z]' или уже ndarray) обратно в numpy. None если пусто/мусор."""
    if s is None:
        return None
    if isinstance(s, np.ndarray):
        return s.astype(np.float32, copy=False)
    if isinstance(s, (list, tuple)):
        if not s:
            return None
        return np.asarray(s, dtype=np.float32)
    if isinstance(s, str):
        body = s.strip().strip("[]").strip()
        if not body:
            return None
        try:
            return np.fromstring(body, dtype=np.float32, sep=",")
        except Exception:
            return None
    return None


async def _embed_single(
    client: httpx.AsyncClient, model: str, text: str, task_type: str
) -> Optional[np.ndarray]:
    url = f"{API_BASE}/models/{model}:embedContent?key={_api_key()}"
    payload = {
        "model": f"models/{model}",
        "content": {"parts": [{"text": text}]},
        "taskType": task_type,
        "outputDimensionality": EMBEDDING_DIM,
    }
    resp = await client.post(url, json=payload)
    if resp.status_code == 429:
        raise QuotaExceededError(f"Gemini 429: {resp.text[:300]}")
    if resp.status_code != 200:
        log.warning(f"embed [{model}] HTTP {resp.status_code}: {resp.text[:200]}")
        return None
    data = resp.json()
    values = data.get("embedding", {}).get("values", [])
    if not values:
        return None
    return np.array(values, dtype=np.float32)


async def list_available_models() -> list[str]:
    url = f"{API_BASE}/models?key={_api_key()}"
    async with httpx.AsyncClient(timeout=10.0) as client:
        resp = await client.get(url)
        resp.raise_for_status()
        data = resp.json()
    return [m["name"] for m in data.get("models", [])]


async def _resolve_model() -> Optional[str]:
    """Однократно подбирает работающую модель из списка кандидатов."""
    global _resolved_model
    if _resolved_model is not None:
        return _resolved_model

    async with httpx.AsyncClient(timeout=20.0) as client:
        for candidate in CANDIDATE_MODELS:
            try:
                vec = await _embed_single(client, candidate, "test", "RETRIEVAL_DOCUMENT")
            except QuotaExceededError:
                raise
            except Exception as e:
                log.warning(f"resolve_model: {candidate} упала ({type(e).__name__}: {e})")
                continue
            if vec is not None and vec.size == EMBEDDING_DIM:
                _resolved_model = candidate
                log.info(f"Embeddings: использую модель '{candidate}' (dim={vec.size})")
                return candidate
            if vec is not None:
                log.warning(
                    f"resolve_model: {candidate} вернула dim={vec.size}, "
                    f"а в config EMBEDDING_DIM={EMBEDDING_DIM}. Пропускаю."
                )

    log.error(f"Ни одна из {CANDIDATE_MODELS} не подошла под dim={EMBEDDING_DIM}.")
    return None


async def embed_batch(
    texts: list[str], task_type: str = "RETRIEVAL_DOCUMENT"
) -> list[Optional[np.ndarray]]:
    """Конкурентно эмбеддит список текстов. Возвращает None для упавших.
    При обнаружении HTTP 429 в любом запросе — переключает остальные задачи в no-op
    и в конце поднимает QuotaExceededError для внешнего кода."""
    if not texts:
        return []

    model = await _resolve_model()
    if model is None:
        return [None] * len(texts)

    sem = asyncio.Semaphore(EMBEDDING_CONCURRENCY)
    results: list[Optional[np.ndarray]] = [None] * len(texts)
    quota_hit = asyncio.Event()
    quota_error_msg: list[str] = []

    async with httpx.AsyncClient(timeout=30.0) as client:
        async def task(idx: int, text: str):
            if quota_hit.is_set():
                return
            async with sem:
                if quota_hit.is_set():
                    return
                try:
                    results[idx] = await _embed_single(client, model, _truncate(text), task_type)
                except QuotaExceededError as e:
                    if not quota_hit.is_set():
                        quota_error_msg.append(str(e))
                        quota_hit.set()
                    return
                except Exception as e:
                    log.warning(f"embed [{model}] упал на тексте #{idx}: {type(e).__name__}: {e}")
                    results[idx] = None

        await asyncio.gather(*[task(i, t) for i, t in enumerate(texts)], return_exceptions=True)

    if quota_hit.is_set():
        raise QuotaExceededError(quota_error_msg[0] if quota_error_msg else "Gemini 429")
    return results


async def embed_one(text: str, task_type: str = "RETRIEVAL_QUERY") -> Optional[np.ndarray]:
    res = await embed_batch([text], task_type=task_type)
    return res[0] if res else None
