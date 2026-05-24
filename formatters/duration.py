"""Парсер коротких записей длительности: 30 -> 30ч, 12h -> 12ч, 3d -> 72ч, 1w -> 168ч."""

import re


_PATTERN = re.compile(r"^\s*(\d+)\s*([hdwm]?)\s*$", re.IGNORECASE)

MIN_HOURS = 1
MAX_HOURS = 24 * 7  # 7 дней


class DurationError(ValueError):
    pass


def parse_duration_to_hours(s: str) -> int:
    """30 -> 30ч, 12h -> 12ч, 3d -> 72ч, 1w -> 168ч. Возвращает часы в диапазоне [1, 168]."""
    m = _PATTERN.match(s)
    if not m:
        raise DurationError(
            "Не понял формат. Примеры: 6, 12h, 3d, 1w. "
            "Можно цифру (часы) или число с суффиксом h/d/w."
        )
    n = int(m.group(1))
    suffix = m.group(2).lower()
    if suffix in ("", "h"):
        hours = n
    elif suffix == "d":
        hours = n * 24
    elif suffix == "w":
        hours = n * 24 * 7
    elif suffix == "m":
        # Минуты округляем до часа, минимум 1 час.
        hours = max(1, n // 60)
    else:
        raise DurationError(f"Неизвестный суффикс: {suffix}")

    if hours < MIN_HOURS or hours > MAX_HOURS:
        raise DurationError(f"Допустимый диапазон: {MIN_HOURS}ч ... {MAX_HOURS}ч (7 дней)")
    return hours


def format_hours(hours: int) -> str:
    """Человекочитаемый вид: 6ч, 1 сутки, 3 дня, 1 неделя."""
    if hours < 24:
        return f"{hours} ч."
    if hours == 24:
        return "1 сутки"
    if hours % 24 == 0:
        d = hours // 24
        if d == 7:
            return "1 неделя"
        last = d % 10
        if 2 <= last <= 4 and not (12 <= d <= 14):
            return f"{d} дня"
        return f"{d} дней"
    return f"{hours} ч."
