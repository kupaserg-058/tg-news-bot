"""Настройки категорий: какие включены в автодайджест.

Inline-клавиатура с чекбоксами. Жмёшь — переключается. Жмёшь «Готово» — сообщение
удаляется/обновляется, возвращаешься в главное меню.

Callback-data format:
    "cat:toggle:<cat_id>"   — переключить категорию
    "cat:done"              — закрыть настройки
"""

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.constants import ParseMode
from telegram.ext import ContextTypes

from config import CATEGORIES, category_label
from db import repository as repo
from handlers.common import owner_only_callback


def _build_keyboard(disabled: set[str]) -> InlineKeyboardMarkup:
    rows = []
    for cid, lbl in CATEGORIES:
        mark = "✅" if cid not in disabled else "⬜️"
        rows.append([InlineKeyboardButton(f"{mark} {lbl}", callback_data=f"cat:toggle:{cid}")])
    rows.append([InlineKeyboardButton("Готово", callback_data="cat:done")])
    return InlineKeyboardMarkup(rows)


async def render_settings(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Открывает inline-меню настроек категорий. Вызывается из text_router по кнопке «⚙ Категории»."""
    user_id = update.effective_user.id
    disabled = await repo.get_disabled_categories(user_id)
    text = (
        "<b>⚙ Категории для автодайджеста</b>\n\n"
        "Отметь какие категории нужны утром и вечером. Снятые — будут отфильтрованы.\n"
        "На «📅 Дайджест 24ч/6ч» эти настройки <b>не влияют</b>."
    )
    await update.effective_chat.send_message(
        text, parse_mode=ParseMode.HTML, reply_markup=_build_keyboard(disabled),
    )


@owner_only_callback
async def on_categories_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Обработчик inline-кнопок настроек."""
    cq = update.callback_query
    data = cq.data or ""
    user_id = update.effective_user.id

    if data == "cat:done":
        await cq.answer("Сохранено")
        try:
            await cq.message.edit_text("⚙ Настройки категорий сохранены.")
        except Exception:
            pass
        return

    if data.startswith("cat:toggle:"):
        cid = data.split(":", 2)[2]
        disabled = await repo.get_disabled_categories(user_id)
        new_enabled = cid in disabled  # если был disabled — включаем
        await repo.set_category_enabled(user_id, cid, new_enabled)
        # Перерисовываем клавиатуру с обновлённым состоянием
        disabled = await repo.get_disabled_categories(user_id)
        try:
            await cq.edit_message_reply_markup(reply_markup=_build_keyboard(disabled))
        except Exception:
            pass
        await cq.answer(f"{category_label(cid)}: {'вкл' if new_enabled else 'выкл'}")
        return

    await cq.answer()
