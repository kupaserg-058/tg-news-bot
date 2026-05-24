"""Формат /digest и /search: только факты, без интерпретации."""

from formatters.utils import escape_html, fmt_dt, truncate


def _format_post_line(post: dict, with_time: bool = True) -> str:
    """Одна строка: 🔴 канал (время) — текст → ссылка"""
    username = escape_html(post["channel_username"])
    when = fmt_dt(post["posted_at"], with_time=with_time)
    text = escape_html(truncate(post["text"], 240))
    link = post["link"]
    return f'• <b>{username}</b> ({when}) — {text} <a href="{link}">→</a>'


def format_digest(posts: list[dict], title: str = "Дайджест за 24 часа") -> str:
    if not posts:
        return f"📅 <b>{escape_html(title)}</b>\n\nПока ничего нет."

    news = [p for p in posts if p["channel_type"] == "news"]
    experts = [p for p in posts if p["channel_type"] == "expert"]

    lines = [f"📅 <b>{escape_html(title)}</b>", ""]

    if news:
        lines.append(f"🔴 <b>News</b> ({len(news)})")
        for p in news:
            lines.append(_format_post_line(p))
        lines.append("")

    if experts:
        lines.append(f"💬 <b>Мнения экспертов</b> ({len(experts)})")
        for p in experts:
            lines.append(_format_post_line(p))
        lines.append("")

    return "\n".join(lines).rstrip()


def format_search_results(posts: list[dict], query: str) -> str:
    if not posts:
        return f"🔎 По запросу «{escape_html(query)}» ничего не найдено."
    title = f"Поиск: «{query}» — найдено {len(posts)}"
    return format_digest(posts, title=title)
