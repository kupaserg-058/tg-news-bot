"""Маршрутизатор текстовых сообщений.

Логика:
1. Если бот в режиме ожидания темы (user_data["awaiting"]) — текст идёт как тема для команды.
2. Если текст совпадает с кнопкой меню — выполняем действие (или включаем режим ожидания).
3. Иначе — обычный free_text-аналитический ответ.
"""

from telegram import Update
from telegram.ext import ContextTypes

from db import repository as repo
from formatters.buttons import MENU, make_main_menu, make_cancel_menu
from formatters.duration import format_hours
from formatters.utils import escape_html
from handlers.common import owner_only, safe_send

# Импорты конкретных AI-команд / прочих обработчиков
from ai.digest_service import compose_digest
from ai.gemini_client import GeminiQuotaError
from handlers.common import QUOTA_HINT, safe_send_with_buttons, clamp_topic
from formatters.buttons import digest_actions, topic_actions
from handlers.callbacks import _extract_digest_topics


AWAITING_KEY = "awaiting"  # значение в user_data — название action ("why", "context", "map", "search")


async def _do_digest(update: Update, context: ContextTypes.DEFAULT_TYPE, hours: int) -> None:
    await repo.log_query(update.effective_user.id, "menu:/digest", str(hours))
    await safe_send(update, f"🤖 Группирую посты за {format_hours(hours)} по темам...")
    try:
        text, n_posts = await compose_digest(hours)
    except GeminiQuotaError:
        await safe_send(update, QUOTA_HINT)
        return
    except Exception as e:
        await safe_send(update, f"❌ Gemini не ответил: <code>{escape_html(type(e).__name__)}: {escape_html(str(e))}</code>")
        return
    if text is None:
        await safe_send(update, f"📅 За {format_hours(hours)} в базе ничего нет.")
        return
    header = f"📅 <b>Дайджест за {format_hours(hours)}</b> <i>({n_posts} постов)</i>\n\n"
    topics = _extract_digest_topics(text)
    markup = digest_actions(context, topics, hours)
    await safe_send_with_buttons(update, header + text, reply_markup=markup)


async def _do_list_channels(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    from handlers.channels import list_channels
    await list_channels(update, context)


async def _do_stats(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    from handlers.admin import stats
    await stats(update, context)


async def _dispatch_topic_action(action: str, topic: str, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Запускает соответствующий хендлер с уже введённой темой."""
    # подменяем context.args чтобы переиспользовать существующие хендлеры
    context.args = topic.split()
    if action == "why":
        from handlers.why import why
        await why(update, context)
    elif action == "chronicle":
        from handlers.context_cmd import chronicle_cmd
        await chronicle_cmd(update, context)
    elif action == "context":
        # backward-compat для старых callback'ов
        from handlers.context_cmd import context_cmd
        await context_cmd(update, context)
    elif action == "map":
        from handlers.map_graph import map_cmd
        await map_cmd(update, context)
    elif action == "search":
        from handlers.search import search
        await search(update, context)


@owner_only
async def text_router(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not update.message or not update.message.text:
        return
    text = update.message.text.strip()
    if not text or text.startswith("/"):
        return

    awaiting = context.user_data.get(AWAITING_KEY)

    # 1) Универсальная кнопка отмены — работает в любом режиме
    menu_item = MENU.get(text)
    if menu_item and menu_item["kind"] == "cancel":
        context.user_data.pop(AWAITING_KEY, None)
        await update.effective_chat.send_message(
            "Отменено. Вернулся в главное меню.",
            reply_markup=make_main_menu(),
        )
        return

    # 2) Если ждём тему — этот текст и есть тема
    if awaiting:
        context.user_data.pop(AWAITING_KEY, None)
        # возвращаем главное меню
        await update.effective_chat.send_message("Принял.", reply_markup=make_main_menu())
        await _dispatch_topic_action(awaiting, clamp_topic(text), update, context)
        return

    # 3) Текст — это название пункта меню
    if menu_item:
        kind = menu_item["kind"]
        if kind == "instant":
            action = menu_item["action"]
            if action == "digest":
                await _do_digest(update, context, hours=menu_item["hours"])
            elif action == "list_channels":
                await _do_list_channels(update, context)
            elif action == "stats":
                await _do_stats(update, context)
            return
        if kind == "ask_topic":
            context.user_data[AWAITING_KEY] = menu_item["action"]
            await update.effective_chat.send_message(
                menu_item["prompt"],
                reply_markup=make_cancel_menu(),
            )
            return

    # 4) Просто свободный текст — обычный аналитический ответ
    from handlers.free_text import free_text
    await free_text(update, context)
