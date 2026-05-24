"""Диагностика: какие модели доступны под текущим GEMINI_API_KEY,
и какая из них реально работает для embedContent.

Запуск:  python check_embedding_models.py
"""

import asyncio
import os

import httpx
from dotenv import load_dotenv


load_dotenv()
KEY = os.environ.get("GEMINI_API_KEY")
if not KEY:
    raise SystemExit("GEMINI_API_KEY не найден в .env")

BASE = "https://generativelanguage.googleapis.com/v1beta"


async def main():
    async with httpx.AsyncClient(timeout=20.0) as client:
        # 1) Список всех моделей
        resp = await client.get(f"{BASE}/models?key={KEY}")
        resp.raise_for_status()
        models = resp.json().get("models", [])

        print(f"=== Всего моделей: {len(models)} ===\n")
        print("=== Embedding-related (supportedGenerationMethods содержит embedContent) ===")
        embed_models = []
        for m in models:
            name = m.get("name", "")
            methods = m.get("supportedGenerationMethods", [])
            if "embedContent" in methods or "embed" in name.lower():
                short = name.replace("models/", "")
                print(f"  • {short}  методы: {methods}")
                embed_models.append(short)

        if not embed_models:
            print("  (нет ни одной модели с поддержкой embedding)")
            return

        # 2) Пробуем каждую
        print("\n=== Тест embedContent на каждой ===")
        for model in embed_models:
            url = f"{BASE}/models/{model}:embedContent?key={KEY}"
            payload = {
                "model": f"models/{model}",
                "content": {"parts": [{"text": "hello world"}]},
            }
            r = await client.post(url, json=payload)
            if r.status_code == 200:
                vec = r.json().get("embedding", {}).get("values", [])
                print(f"  ✅ {model}: dim={len(vec)}")
            else:
                print(f"  ❌ {model}: HTTP {r.status_code} — {r.text[:150]}")


if __name__ == "__main__":
    asyncio.run(main())
