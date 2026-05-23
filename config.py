"""Конфигурация бота.

Каналы добавляй сюда. Формат:
    {"username": "@channelname", "type": "news"}    # факты, новости
    {"username": "@channelname", "type": "expert"}  # мнения, экспертные комментарии
"""

CHANNELS: list[dict] = [
    # {"username": "@meduzalive", "type": "news"},
    # {"username": "@kommersant", "type": "news"},
    # {"username": "@bbbreaking", "type": "news"},
    # {"username": "@stalin_gulag", "type": "expert"},
]

PARSER_INTERVAL_MIN = 15
BACKFILL_DAYS = 30

GEMINI_MODEL = "gemini-2.5-flash"
GEMINI_FALLBACK_MODEL = "gemini-2.0-flash"

CACHE_TTL = {
    "digest": 3600,
    "search": 1800,
    "why": 86400,
    "context": 86400,
    "map": 86400,
    "free": 1800,
}

MAX_POSTS_IN_PROMPT = 50
TELEGRAM_MESSAGE_LIMIT = 4096

TIMEZONE = "Europe/Moscow"
