"""Общие хелперы для хендлеров: owner-only фильтр, безопасная отправка, error handler."""

from functools import wraps

from telegram import Update, InlineKeyboardMarkup, Chat
from telegram.constants import ParseMode
from telegram.ext import ContextTypes

from config import TELEGRAM_MESSAGE_LIMIT, TOPIC_MAX_LEN
from formatters.utils import split_for_telegram, sanitize_telegram_html
from utils.logger import log


def clamp_topic(topic: str) -> str:
    """Защита от мегапромптов: режем длинные темы/запросы."""
    topic = (topic or "").strip()
    if len(topic) > TOPIC_MAX_LEN:
        return topic[:TOPIC_MAX_LEN].rstrip() + "…"
    return topic


QUOTA_HINT = (
    "🚦 Квота Gemini кончилась. Минутный лимит сбрасывается сам через ~60 секунд, "
    "дневной — в ~10:00 МСК. Попробуй чуть позже."
)


_owner_chat_id: int | None = None


def set_owner_chat_id(chat_id: int) -> None:
    global _owner_chat_id
    _owner_chat_id = chat_id


def _is_owner(update: Update) -> bool:
    chat_id = update.effective_chat.id if update.effective_chat else None
    return _owner_chat_id is not None and chat_id == _owner_chat_id


def owner_only(func):
    @wraps(func)
    async def wrapper(update: Update, context: ContextTypes.DEFAULT_TYPE):
        if not _is_owner(update):
            log.warning(f"Чужой запрос от chat_id={update.effective_chat.id if update.effective_chat else '?'}, игнор")
            return
        return await func(update, context)
    return wrapper


def owner_only_callback(func):
    """Аналог owner_only для CallbackQueryHandler."""
    @wraps(func)
    async def wrapper(update: Update, context: ContextTypes.DEFAULT_TYPE):
        if not _is_owner(update):
            if update.callback_query:
                await update.callback_query.answer("Доступ закрыт", show_alert=False)
            return
        return await func(update, context)
    return wrapper


async def safe_send(update: Update, text: str, parse_mode: str | None = ParseMode.HTML) -> None:
    if not update.effective_chat:
        return
    if parse_mode == ParseMode.HTML:
        text = sanitize_telegram_html(text)
    for chunk in split_for_telegram(text, TELEGRAM_MESSAGE_LIMIT):
        await update.effective_chat.send_message(
            chunk, parse_mode=parse_mode, disable_web_page_preview=True,
        )


async def safe_send_with_buttons(
    update: Update,
    text: str,
    reply_markup: InlineKeyboardMarkup | None = None,
    parse_mode: str | None = ParseMode.HTML,
) -> None:
    """То же что safe_send, но к ПОСЛЕДНЕМУ куску прикрепляются кнопки."""
    if not update.effective_chat:
        return
    await send_long(update.effective_chat, text, reply_markup=reply_markup, parse_mode=parse_mode)


async def send_long(
    chat: Chat,
    text: str,
    reply_markup: InlineKeyboardMarkup | None = None,
    parse_mode: str | None = ParseMode.HTML,
) -> None:
    if parse_mode == ParseMode.HTML:
        text = sanitize_telegram_html(text)
    chunks = split_for_telegram(text, TELEGRAM_MESSAGE_LIMIT)
    for i, chunk in enumerate(chunks):
        is_last = i == len(chunks) - 1
        await chat.send_message(
            chunk,
            parse_mode=parse_mode,
            disable_web_page_preview=True,
            reply_markup=reply_markup if is_last else None,
        )


async def on_error(update: object, context: ContextTypes.DEFAULT_TYPE) -> None:
    log.exception("Ошибка в хендлере", exc_info=context.error)
    if isinstance(update, Update) and update.effective_chat:
        try:
            await update.effective_chat.send_message(
                f"⚠️ Ошибка: <code>{type(context.error).__name__}</code>. Подробности в логах.",
                parse_mode=ParseMode.HTML,
            )
        except Exception:
            pass
