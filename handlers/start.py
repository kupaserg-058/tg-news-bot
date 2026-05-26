"""/start, /help, /menu. Доступны только владельцу. Чужие /start логируются (для первой настройки)."""

from telegram import Update
from telegram.constants import ParseMode
from telegram.ext import ContextTypes

from formatters.buttons import make_main_menu
from handlers.common import safe_send, owner_only, _is_owner
from utils.logger import log


HELP_TEXT = (
    "Привет. Я <b>Марк</b> — твой новостной аналитик.\n\n"
    "<b>Кнопки</b>\n"
    "📅 Дайджест 24ч / 6ч — сводка по темам\n"
    "🗂 По категории — дайджест по выбранной сфере (категория → период)\n"
    "⚙ Категории — что включать в автодайджест (утром и вечером)\n"
    "📌 Глубокий анализ — что, почему, параллели, прогноз\n"
    "📜 Хроника — таймлайн событий по теме + разные мнения экспертов\n"
    "🕸 Граф связей — Mermaid-картинка\n"
    "🔎 Поиск по базе — сырой полнотекстовый\n"
    "📋 Каналы · 📊 Статистика\n\n"
    "<b>Прочие команды</b>\n"
    "/add_channel @name news|expert — добавить канал\n"
    "/remove_channel @name — удалить канал\n"
    "/digest 3d — дайджест за нестандартный период (1..168 ч.)\n"
    "/menu — вернуть клавиатуру если скрыл\n"
    "/clear_cache — сбросить кеш Gemini"
)


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    chat_id = update.effective_chat.id if update.effective_chat else None
    user = update.effective_user
    log.info(f"/start от user_id={user.id if user else '?'} chat_id={chat_id}")
    if not _is_owner(update):
        return
    await update.effective_chat.send_message(
        HELP_TEXT,
        parse_mode=ParseMode.HTML,
        disable_web_page_preview=True,
        reply_markup=make_main_menu(),
    )


@owner_only
async def help_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.effective_chat.send_message(
        HELP_TEXT,
        parse_mode=ParseMode.HTML,
        disable_web_page_preview=True,
        reply_markup=make_main_menu(),
    )


@owner_only
async def menu_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.effective_chat.send_message(
        "Меню Марка:",
        reply_markup=make_main_menu(),
    )
