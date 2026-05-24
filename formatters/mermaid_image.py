"""Рендер Mermaid-диаграмм в PNG через бесплатный сервис mermaid.ink.

URL-схема: https://mermaid.ink/img/<base64-encoded-diagram>
Возвращает байты PNG, либо None если сервис недоступен.
"""

import base64

import httpx

from utils.logger import log


MERMAID_INK_URL = "https://mermaid.ink/img/{payload}?type=png&theme=default&bgColor=FFFFFF"


def _encode(diagram: str) -> str:
    raw = diagram.encode("utf-8")
    return base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")


async def render_to_png(diagram: str, timeout: float = 20.0) -> bytes | None:
    payload = _encode(diagram)
    url = MERMAID_INK_URL.format(payload=payload)
    try:
        async with httpx.AsyncClient(timeout=timeout, follow_redirects=True) as client:
            resp = await client.get(url)
            if resp.status_code == 200 and resp.headers.get("content-type", "").startswith("image/"):
                return resp.content
            log.warning(f"mermaid.ink ответил {resp.status_code}: {resp.text[:200]}")
            return None
    except Exception as e:
        log.warning(f"mermaid.ink упал: {type(e).__name__}: {e}")
        return None
