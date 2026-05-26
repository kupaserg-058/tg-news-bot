"""История разговора со свободным текстом. Живёт в user_data (in-memory per chat).

Хранится deque последних HISTORY_LIMIT пар (вопрос, выжимка ответа).
Записи старше HISTORY_TTL_SECONDS игнорируются — даже если deque не успел вытеснить.

Используется только в free_text и в _do_more (углубление). Команды (/digest,
/list_channels и т.п.) и кнопки меню в историю не пишут — они не часть «разговора».
"""

import re
import time
from collections import deque

from telegram.ext import ContextTypes


HISTORY_KEY = "chat_history"
HISTORY_LIMIT = 5            # сколько последних пар храним
HISTORY_TTL_SECONDS = 30 * 60  # 30 минут — старше не подмешиваем
SUMMARY_MAX_CHARS = 600       # сжимаем ответ для контекста


_TAG_RE = re.compile(r"<[^>]+>")
_WS_RE = re.compile(r"\s+")


def _get_deque(context: ContextTypes.DEFAULT_TYPE) -> deque:
    h = context.user_data.get(HISTORY_KEY)
    if not isinstance(h, deque):
        h = deque(maxlen=HISTORY_LIMIT)
        context.user_data[HISTORY_KEY] = h
    return h


def summarize_answer(html_or_text: str, max_chars: int = SUMMARY_MAX_CHARS) -> str:
    """Чистит HTML-теги и схлопывает пробелы, обрезает до max_chars."""
    if not html_or_text:
        return ""
    plain = _TAG_RE.sub(" ", html_or_text)
    plain = _WS_RE.sub(" ", plain).strip()
    if len(plain) > max_chars:
        return plain[: max_chars - 1].rstrip() + "…"
    return plain


def add_exchange(context: ContextTypes.DEFAULT_TYPE, question: str, answer: str) -> None:
    """Сохраняет один обмен (вопрос пользователя, выжимка ответа Марка)."""
    if not question or not answer:
        return
    h = _get_deque(context)
    h.append({
        "ts": time.time(),
        "q": question.strip()[:300],
        "a": summarize_answer(answer),
    })


def get_recent_exchanges(context: ContextTypes.DEFAULT_TYPE) -> list[dict]:
    """Возвращает свежие записи (не старше TTL) в порядке от старых к новым."""
    h = _get_deque(context)
    cutoff = time.time() - HISTORY_TTL_SECONDS
    return [e for e in h if e["ts"] >= cutoff]


def clear_history(context: ContextTypes.DEFAULT_TYPE) -> None:
    if HISTORY_KEY in context.user_data:
        context.user_data[HISTORY_KEY].clear()
