"""Маршрутизатор текстовых сообщений и стейт-машины меню.

Состояния (в user_data):
- AWAITING_KEY = "awaiting" — ждём тему для команды (action: why, chronicle, map, search)
- STATE_KEY    = "menu_state" — глобальный режим:
    None             → главное меню
    "categories"     → пользователь выбирает категорию для дайджеста
    "period:<cat>"   → пользователь выбирает период (категория уже выбрана)
"""

from telegram import Update
from telegram.ext import ContextTypes

from config import CATEGORIES, category_label
from db import repository as repo
from formatters.buttons import (
    MENU, PERIOD_LABELS,
    make_main_menu, make_cancel_menu, make_categories_menu, make_period_menu,
)
from formatters.duration import format_hours
from formatters.utils import escape_html
from handlers.common import owner_only, safe_send

from ai.digest_service import compose_digest
from ai.gemini_client import GeminiQuotaError
from handlers.common import QUOTA_HINT, safe_send_with_buttons, clamp_topic
from formatters.buttons import digest_actions, topic_actions
from handlers.callbacks import _extract_digest_topics


AWAITING_KEY = "awaiting"
STATE_KEY = "menu_state"

_LABEL_TO_CAT = {lbl: cid for cid, lbl in CATEGORIES}


async def _do_digest(
    update: Update, context: ContextTypes.DEFAULT_TYPE, hours: int, category: str | None = None
) -> None:
    label = f" · {category_label(category)}" if category else ""
    await repo.log_query(update.effective_user.id, "menu:/digest", f"{hours}h{label}")
    await safe_send(update, f"🤖 Группирую посты за {format_hours(hours)}{label}...")
    try:
        text, n_posts = await compose_digest(hours, category=category)
    except GeminiQuotaError:
        await safe_send(update, QUOTA_HINT)
        return
    except Exception as e:
        await safe_send(update, f"❌ Gemini не ответил: <code>{escape_html(type(e).__name__)}: {escape_html(str(e))}</code>")
        return
    if text is None:
        title = f"📅 За {format_hours(hours)}{label}"
        await safe_send(update, f"{title} в базе ничего нет.")
        return
    header = f"📅 <b>Дайджест за {format_hours(hours)}{label}</b> <i>({n_posts} постов)</i>\n\n"
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
    context.args = topic.split()
    if action == "why":
        from handlers.why import why
        await why(update, context)
    elif action == "chronicle":
        from handlers.context_cmd import chronicle_cmd
        await chronicle_cmd(update, context)
    elif action == "context":
        from handlers.context_cmd import context_cmd
        await context_cmd(update, context)
    elif action == "map":
        from handlers.map_graph import map_cmd
        await map_cmd(update, context)
    elif action == "search":
        from handlers.search import search
        await search(update, context)


async def _open_category_settings(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Показывает inline-чекбоксы с категориями: какие включены в автодайджест."""
    from handlers.categories_settings import render_settings
    await render_settings(update, context)


@owner_only
async def text_router(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not update.message or not update.message.text:
        return
    text = update.message.text.strip()
    if not text or text.startswith("/"):
        return

    state: str | None = context.user_data.get(STATE_KEY)
    awaiting = context.user_data.get(AWAITING_KEY)
    menu_item = MENU.get(text)

    # Универсальная отмена — всегда сбрасывает состояние
    if menu_item and menu_item["kind"] == "cancel":
        context.user_data.pop(AWAITING_KEY, None)
        context.user_data.pop(STATE_KEY, None)
        await update.effective_chat.send_message("Отменено. Главное меню.", reply_markup=make_main_menu())
        return

    # «Назад» из подменю
    if menu_item and menu_item["kind"] == "back":
        if state and state.startswith("period:"):
            # из выбора периода — назад к выбору категории
            context.user_data[STATE_KEY] = "categories"
            await update.effective_chat.send_message("Выбери категорию:", reply_markup=make_categories_menu())
            return
        # из любого другого подменю — в главное
        context.user_data.pop(STATE_KEY, None)
        context.user_data.pop(AWAITING_KEY, None)
        await update.effective_chat.send_message("Главное меню.", reply_markup=make_main_menu())
        return

    # 1) Если ждём тему для команды — следующий текст это тема
    if awaiting:
        context.user_data.pop(AWAITING_KEY, None)
        await update.effective_chat.send_message("Принял.", reply_markup=make_main_menu())
        await _dispatch_topic_action(awaiting, clamp_topic(text), update, context)
        return

    # 2) Подменю выбора категории → ждём период
    if state == "categories":
        cat_id = _LABEL_TO_CAT.get(text)
        if cat_id is not None:
            context.user_data[STATE_KEY] = f"period:{cat_id}"
            await update.effective_chat.send_message(
                f"Выбрана: <b>{escape_html(category_label(cat_id))}</b>. Теперь выбери период:",
                parse_mode="HTML",
                reply_markup=make_period_menu(),
            )
            return
        # Не категория — игнор / подсказка
        await update.effective_chat.send_message("Жми кнопку категории или ⬅️ Назад.", reply_markup=make_categories_menu())
        return

    # 3) Подменю выбора периода → запускаем дайджест по категории
    if state and state.startswith("period:"):
        cat_id = state.split(":", 1)[1]
        hours = PERIOD_LABELS.get(text)
        if hours is None:
            await update.effective_chat.send_message("Жми кнопку периода или ⬅️ Назад.", reply_markup=make_period_menu())
            return
        context.user_data.pop(STATE_KEY, None)
        await update.effective_chat.send_message("Принял.", reply_markup=make_main_menu())
        await _do_digest(update, context, hours=hours, category=cat_id)
        return

    # 4) Кнопки главного меню
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
            await update.effective_chat.send_message(menu_item["prompt"], reply_markup=make_cancel_menu())
            return
        if kind == "open_categories":
            context.user_data[STATE_KEY] = "categories"
            await update.effective_chat.send_message("Выбери категорию:", reply_markup=make_categories_menu())
            return
        if kind == "open_category_settings":
            await _open_category_settings(update, context)
            return

    # 5) Просто свободный текст — обычный аналитический ответ
    from handlers.free_text import free_text
    await free_text(update, context)
