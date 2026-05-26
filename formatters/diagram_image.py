"""Рендер диаграмм в PNG через Kroki.io.

Поддерживаем D2 (основной движок) и Mermaid (fallback).
Kroki принимает GET с deflate+base64-encoded source, либо POST с body. Используем GET —
для наших графов из 10-25 узлов размер URL сильно меньше лимита.
"""

import base64
import zlib

import httpx

from config import D2_THEME, D2_SKETCH
from utils.logger import log


KROKI_BASE = "https://kroki.io"


def _encode(source: str) -> str:
    """Kroki требует zlib-deflate потом url-safe base64 без padding."""
    raw = source.encode("utf-8")
    compressed = zlib.compress(raw, 9)
    return base64.urlsafe_b64encode(compressed).decode("ascii").rstrip("=")


def _d2_url(source: str) -> str:
    payload = _encode(source)
    url = f"{KROKI_BASE}/d2/png/{payload}"
    params = []
    if D2_THEME:
        params.append(f"theme={D2_THEME}")
    if D2_SKETCH:
        params.append("sketch=true")
    if params:
        url += "?" + "&".join(params)
    return url


def _mermaid_url(source: str) -> str:
    payload = _encode(source)
    return f"{KROKI_BASE}/mermaid/png/{payload}"


async def _fetch_png(url: str, timeout: float = 25.0) -> bytes | None:
    try:
        async with httpx.AsyncClient(timeout=timeout, follow_redirects=True) as client:
            resp = await client.get(url)
            if resp.status_code == 200 and resp.headers.get("content-type", "").startswith("image/"):
                return resp.content
            log.warning(f"Kroki ответил {resp.status_code}: {resp.text[:200]}")
            return None
    except Exception as e:
        log.warning(f"Kroki упал: {type(e).__name__}: {e}")
        return None


async def render_d2_to_png(source: str) -> bytes | None:
    """Главный путь. Если упадёт — попробуем mermaid (если source как-то совместим)."""
    return await _fetch_png(_d2_url(source))


async def render_mermaid_to_png(source: str) -> bytes | None:
    """Fallback, остаётся для совместимости."""
    return await _fetch_png(_mermaid_url(source))
