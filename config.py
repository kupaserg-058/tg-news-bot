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
BACKFILL_DAYS = 1  # 24 часа при добавлении канала; дальше копится инкрементально каждые 15 мин

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
TOPIC_MAX_LEN = 500          # лимит на длину /why, /context, /map, free_text — защита от мегапромптов

TIMEZONE = "Europe/Moscow"

# --- Embeddings ---
EMBEDDING_MODEL = "gemini-embedding-001"  # бесплатный tier; усекаем вывод до 768d через MRL
EMBEDDING_DIM = 768                        # HNSW в pgvector ограничен 2000 — берём 768 (стандарт)
EMBEDDING_CONCURRENCY = 6          # сколько embedContent-запросов в полёте одновременно
EMBEDDING_INPUT_CHARS = 4000       # обрезка текста перед эмбеддингом
SEMANTIC_SIMILARITY_THRESHOLD = 0.65  # минимальная похожесть для попадания в выдачу (отсекает «общие» совпадения)
EXPERT_LINK_THRESHOLD = 0.60       # для связи новость↔мнение эксперта
