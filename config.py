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

# --- Категории постов ---
# (id, label с эмодзи). id хранится в БД, label — для UI.
CATEGORIES: list[tuple[str, str]] = [
    ("politics", "🏛 Политика"),
    ("economy",  "💸 Экономика"),
    ("it",       "💻 IT и технологии"),
    ("conflict", "⚔️ Конфликты"),
    ("society",  "👥 Общество"),
    ("culture",  "🎭 Культура"),
    ("sport",    "⚽ Спорт"),
    ("science",  "🔬 Наука"),
    ("other",    "📦 Другое"),
]
CATEGORY_IDS: set[str] = {cid for cid, _ in CATEGORIES}


def category_label(cid: str) -> str:
    for c, lbl in CATEGORIES:
        if c == cid:
            return lbl
    return cid


CLASSIFY_BATCH_SIZE = 25         # сколько постов классифицируем одним запросом к Gemini
CLASSIFY_FRESH_DAYS = 2           # классифицируем посты не старше N суток

# --- Граф связей (D2 через Kroki.io) ---
# Список тем: https://d2lang.com/tour/themes/  (0,1,100..105,200,300,301)
D2_THEME = 0                      # 0 = аккуратный neutral по умолчанию
D2_SKETCH = False                  # True = «рисованный от руки» стиль

# --- Embeddings ---
EMBEDDING_MODEL = "gemini-embedding-001"  # бесплатный tier; усекаем вывод до 768d через MRL
EMBEDDING_DIM = 768                        # HNSW в pgvector ограничен 2000 — берём 768 (стандарт)
EMBEDDING_CONCURRENCY = 6          # сколько embedContent-запросов в полёте одновременно
EMBEDDING_INPUT_CHARS = 4000       # обрезка текста перед эмбеддингом
SEMANTIC_SIMILARITY_THRESHOLD = 0.65  # минимальная похожесть для попадания в выдачу (отсекает «общие» совпадения)
EXPERT_LINK_THRESHOLD = 0.60       # для связи новость↔мнение эксперта
