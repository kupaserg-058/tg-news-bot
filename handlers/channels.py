"""Команды управления каналами: /add_channel, /remove_channel, /list_channels."""

from telegram import Update
from telegram.constants import ParseMode
from telegram.ext import ContextTypes

from db import repository as repo
from handlers.common import owner_only, safe_send
from parser.channel_parser import parse_channel
from formatters.utils import escape_html


VALID_TYPES = {"news", "expert"}


def _normalize_username(raw: str) -> str:
    """Приводит к виду @username — без https://t.me/ и пр."""
    raw = raw.strip()
    if raw.startswith("https://t.me/"):
        raw = "@" + raw[len("https://t.me/"):].strip("/")
    elif raw.startswith("t.me/"):
        raw = "@" + raw[len("t.me/"):].strip("/")
    if not raw.startswith("@"):
        raw = "@" + raw
    return raw


@owner_only
async def add_channel(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    args = context.args
    if len(args) < 2:
        await safe_send(
            update,
            "Использование: <code>/add_channel @username news|expert</code>\n\n"
            "Пример:\n"
            "<code>/add_channel @meduzalive news</code>\n"
            "<code>/add_channel @stalingulag expert</code>",
        )
        return

    username = _normalize_username(args[0])
    ch_type = args[1].lower()
    if ch_type not in VALID_TYPES:
        await safe_send(update, f"Тип должен быть <code>news</code> или <code>expert</code>, не <code>{escape_html(ch_type)}</code>")
        return

    channel_id = await repo.upsert_channel(username, ch_type)
    await repo.log_query(update.effective_user.id, "/add_channel", f"{username} {ch_type}")
    await safe_send(update, f"✅ Канал {escape_html(username)} (<b>{ch_type}</b>) добавлен. Начинаю backfill последних 30 дней...")

    # Запускаем backfill сразу.
    channel = next((c for c in await repo.get_all_channels() if c["id"] == channel_id), None)
    if channel:
        try:
            added = await parse_channel(channel)
            await safe_send(update, f"📥 Backfill {escape_html(username)} завершён, добавлено постов: <b>{added}</b>")
        except Exception as e:
            await safe_send(update, f"⚠️ Backfill не удался: <code>{escape_html(type(e).__name__)}: {escape_html(str(e))}</code>")


@owner_only
async def remove_channel(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    args = context.args
    if not args:
        await safe_send(update, "Использование: <code>/remove_channel @username</code>")
        return
    username = _normalize_username(args[0])
    ok = await repo.remove_channel(username)
    await repo.log_query(update.effective_user.id, "/remove_channel", username)
    if ok:
        await safe_send(update, f"🗑 Канал {escape_html(username)} и все его посты удалены.")
    else:
        await safe_send(update, f"Канал {escape_html(username)} не найден.")


@owner_only
async def list_channels(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    channels = await repo.get_all_channels()
    if not channels:
        await safe_send(update, "Каналов пока нет. Добавь через <code>/add_channel @name news|expert</code>")
        return
    lines = ["<b>📋 Каналы:</b>"]
    for c in channels:
        title = f' — {escape_html(c["title"])}' if c.get("title") else ""
        lines.append(f'• {escape_html(c["username"])} <i>({c["type"]})</i>{title}')
    await safe_send(update, "\n".join(lines))
