"""Утилиты форматирования: HTML-экранирование, разбиение длинных сообщений, даты."""

import re
from datetime import datetime, timezone

import pytz

from config import TIMEZONE, TELEGRAM_MESSAGE_LIMIT


_tz = pytz.timezone(TIMEZONE)


# Telegram HTML поддерживает только эти теги. Всё остальное надо конвертить или резать.
_ALLOWED_TAGS = {
    "b", "strong", "i", "em", "u", "ins", "s", "strike", "del",
    "a", "code", "pre", "tg-spoiler", "blockquote",
}

_TAG_RE = re.compile(r"</?([a-zA-Z0-9]+)(\s[^>]*)?>")


def sanitize_telegram_html(text: str) -> str:
    """Чистит HTML так, чтобы Telegram точно распарсил:
    - разрешённые теги (b/i/a/code/pre/…) оставляем
    - <h1..h6> превращаем в <b>…</b>
    - <ul>/<ol> удаляем (только контейнер), <li>… превращаем в '• …\\n'
    - <p>, <div>, <br> → перенос строки
    - всё прочее (script, span, etc.) — убираем теги, оставляя текст внутри
    """
    text = re.sub(r"<li[^>]*>", "• ", text, flags=re.IGNORECASE)
    text = re.sub(r"</li\s*>", "\n", text, flags=re.IGNORECASE)
    text = re.sub(r"</?(ul|ol)[^>]*>", "\n", text, flags=re.IGNORECASE)
    text = re.sub(r"<h[1-6][^>]*>", "<b>", text, flags=re.IGNORECASE)
    text = re.sub(r"</h[1-6]\s*>", "</b>\n", text, flags=re.IGNORECASE)
    text = re.sub(r"</?(p|div)[^>]*>", "\n", text, flags=re.IGNORECASE)
    text = re.sub(r"<br\s*/?>", "\n", text, flags=re.IGNORECASE)

    def _strip_unknown(m: re.Match) -> str:
        tag = m.group(1).lower()
        if tag in _ALLOWED_TAGS:
            return m.group(0)
        return ""  # неизвестный тег убираем целиком, содержимое останется в тексте между тегами

    text = _TAG_RE.sub(_strip_unknown, text)
    # Сжимаем лишние пустые строки
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def escape_html(text: str) -> str:
    return (
        text.replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
    )


def fmt_dt(dt: datetime, with_time: bool = True) -> str:
    """Локализованное время в TIMEZONE."""
    local = dt.astimezone(_tz)
    if with_time:
        return local.strftime("%d.%m %H:%M")
    return local.strftime("%d.%m.%Y")


def fmt_post_age(dt: datetime) -> str:
    """Дата поста вместе с явным возрастом — «сегодня 14:23», «вчера 09:10»,
    «23.08 (3 дня назад)», «10.07.2026 (47 дней назад)».

    Нужно именно для промптов: раньше модель получала только «дд.мм ЧЧ:ММ»
    без года, и не могла отличить вчерашнюю новость от прошлогодней.
    """
    local = dt.astimezone(_tz)
    now = datetime.now(timezone.utc)
    days = (now - dt).days

    if days <= 0:
        return f"сегодня {local:%H:%M}"
    if days == 1:
        return f"вчера {local:%H:%M}"
    if days < 7:
        return f"{local:%d.%m} ({days} дня назад)" if 2 <= days <= 4 else f"{local:%d.%m} ({days} дней назад)"
    if days < 365:
        return f"{local:%d.%m} ({days} дней назад)"
    return f"{local:%d.%m.%Y} ({days} дней назад)"


def truncate(text: str, max_len: int = 200) -> str:
    text = " ".join(text.split())  # схлопнуть переносы и лишние пробелы
    if len(text) <= max_len:
        return text
    return text[: max_len - 1].rstrip() + "…"


def split_for_telegram(text: str, limit: int = TELEGRAM_MESSAGE_LIMIT) -> list[str]:
    """Разбивает текст на куски не длиннее limit, стараясь рвать по переносам строк."""
    if len(text) <= limit:
        return [text]

    chunks: list[str] = []
    remaining = text
    while len(remaining) > limit:
        # ищем последний \n в пределах limit
        split_at = remaining.rfind("\n", 0, limit)
        if split_at <= 0:
            split_at = limit
        chunks.append(remaining[:split_at].rstrip())
        remaining = remaining[split_at:].lstrip()
    if remaining:
        chunks.append(remaining)
    return chunks
