"""Inline-кнопки под ответами AI-команд.

Темы могут быть длинными — callback_data в Telegram ограничен 64 байтами.
Поэтому темы храним в bot_data (in-memory), а в callback кладём короткий id.
"""

import uuid

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, ReplyKeyboardMarkup, KeyboardButton
from telegram.ext import ContextTypes

from config import CATEGORIES


# --- Главное меню (ReplyKeyboard) ---

MENU = {
    # быстрые дайджесты (без выбора категории)
    "📅 Дайджест 24ч":   {"kind": "instant", "action": "digest", "hours": 24},
    "📅 Дайджест 6ч":    {"kind": "instant", "action": "digest", "hours": 6},

    # двухшаговый: выбираем категорию → потом период
    "🗂 По категории":   {"kind": "open_categories"},

    # настройки
    "⚙ Категории":      {"kind": "open_category_settings"},

    "📋 Каналы":          {"kind": "instant", "action": "list_channels"},
    "📊 Статистика":      {"kind": "instant", "action": "stats"},

    # требуют тему — переключают бота в "режим ожидания темы"
    "📌 Глубокий анализ":      {"kind": "ask_topic", "action": "why",       "prompt": "Какую тему разобрать глубоко? Напиши одной строкой:"},
    "📜 Хроника":              {"kind": "ask_topic", "action": "chronicle", "prompt": "По какой теме собрать хронику событий?"},
    "🕸 Граф связей":          {"kind": "ask_topic", "action": "map",       "prompt": "По какой теме построить граф?"},
    "🔎 Поиск по базе":        {"kind": "ask_topic", "action": "search",    "prompt": "Что искать в базе (ключевые слова)?"},

    "⬅️ Назад":          {"kind": "back"},
    "❌ Отмена":               {"kind": "cancel"},
}


# Метки кнопок-периодов (в режиме «выбор периода после категории»)
PERIOD_LABELS = {
    "⏱ 6ч":  6,
    "⏱ 12ч": 12,
    "⏱ 24ч": 24,
    "⏱ 3д":  72,
    "⏱ 7д":  168,
}


def make_main_menu() -> ReplyKeyboardMarkup:
    """Основная клавиатура. Висит над полем ввода всегда после /start."""
    layout = [
        ["📅 Дайджест 24ч",  "📅 Дайджест 6ч"],
        ["🗂 По категории",   "📌 Глубокий анализ"],
        ["📜 Хроника",        "🕸 Граф связей"],
        ["🔎 Поиск по базе",  "⚙ Категории"],
        ["📋 Каналы",         "📊 Статистика"],
    ]
    return ReplyKeyboardMarkup(
        [[KeyboardButton(label) for label in row] for row in layout],
        resize_keyboard=True,
        is_persistent=True,
    )


def make_cancel_menu() -> ReplyKeyboardMarkup:
    """Клавиатура в режиме ожидания темы — только Отмена."""
    return ReplyKeyboardMarkup(
        [[KeyboardButton("❌ Отмена")]],
        resize_keyboard=True,
        is_persistent=True,
    )


def make_categories_menu() -> ReplyKeyboardMarkup:
    """Клавиатура категорий для шага 1 двухшагового дайджеста."""
    # 9 категорий в 3 ряда по 3, плюс ряд с «Назад»
    labels = [lbl for _, lbl in CATEGORIES]
    rows = [labels[i:i + 3] for i in range(0, len(labels), 3)]
    rows.append(["⬅️ Назад"])
    return ReplyKeyboardMarkup(
        [[KeyboardButton(x) for x in row] for row in rows],
        resize_keyboard=True,
        is_persistent=True,
    )


def make_period_menu() -> ReplyKeyboardMarkup:
    """Клавиатура выбора периода для шага 2."""
    return ReplyKeyboardMarkup(
        [
            [KeyboardButton("⏱ 6ч"), KeyboardButton("⏱ 12ч"), KeyboardButton("⏱ 24ч")],
            [KeyboardButton("⏱ 3д"), KeyboardButton("⏱ 7д")],
            [KeyboardButton("⬅️ Назад"), KeyboardButton("❌ Отмена")],
        ],
        resize_keyboard=True,
        is_persistent=True,
    )


_TOPIC_CACHE_KEY = "topics_by_id"
_MAX_TOPICS = 500  # после переполнения — старые вытесняются


def _store_topic(context: ContextTypes.DEFAULT_TYPE, topic: str) -> str:
    """Возвращает короткий id, под которым тема лежит в bot_data."""
    store: dict = context.bot_data.setdefault(_TOPIC_CACHE_KEY, {})
    # Поищем уже существующий id для этой темы, чтобы не плодить дубли.
    for existing_id, existing_topic in store.items():
        if existing_topic == topic:
            return existing_id

    if len(store) >= _MAX_TOPICS:
        # Вытесняем самый старый ключ.
        oldest = next(iter(store))
        store.pop(oldest, None)

    tid = uuid.uuid4().hex[:10]
    store[tid] = topic
    return tid


def get_topic(context: ContextTypes.DEFAULT_TYPE, tid: str) -> str | None:
    store: dict = context.bot_data.get(_TOPIC_CACHE_KEY, {})
    return store.get(tid)


def topic_actions(context: ContextTypes.DEFAULT_TYPE, topic: str, exclude: str | None = None) -> InlineKeyboardMarkup:
    """Кнопки под ответом на конкретную тему."""
    tid = _store_topic(context, topic)
    all_buttons = [
        ("why",       "📌 Глубже"),
        ("chronicle", "📜 Хроника"),
        ("map",       "🕸 Граф"),
        ("more",      "📚 Больше деталей"),
    ]
    row = [
        InlineKeyboardButton(label, callback_data=f"{action}|{tid}")
        for action, label in all_buttons
        if action != exclude
    ]
    # Telegram разрешает до 8 кнопок в ряду, но красивее — по 2.
    rows = [row[i:i + 2] for i in range(0, len(row), 2)]
    return InlineKeyboardMarkup(rows)


def digest_actions(context: ContextTypes.DEFAULT_TYPE, topics: list[str], hours: int) -> InlineKeyboardMarkup | None:
    """Под дайджестом: кнопки по найденным темам + сменить интервал."""
    rows = []
    for topic in topics[:6]:
        tid = _store_topic(context, topic)
        rows.append([InlineKeyboardButton(f"📌 {topic}", callback_data=f"why|{tid}")])

    quick_intervals = [
        ("d6",  "6ч"),
        ("d24", "24ч"),
        ("d72", "3д"),
    ]
    quick_intervals = [(a, l) for a, l in quick_intervals if not (a == f"d{hours}")]
    if quick_intervals:
        rows.append([InlineKeyboardButton(f"⏱ {l}", callback_data=a) for a, l in quick_intervals])

    return InlineKeyboardMarkup(rows) if rows else None
