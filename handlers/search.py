"""/search [запрос] — сырой полнотекстовый поиск + кнопки для перехода в AI-режим."""

from telegram import Update
from telegram.ext import ContextTypes

from db import repository as repo
from formatters.buttons import topic_actions
from formatters.digest_format import format_search_results
from handlers.common import owner_only, safe_send, safe_send_with_buttons


@owner_only
async def search(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = " ".join(context.args).strip()
    if not query:
        await safe_send(update, "Использование: <code>/search ключевые слова</code>")
        return
    posts = await repo.search_posts(query, limit=50)
    await repo.log_query(update.effective_user.id, "/search", query)
    text = format_search_results(posts, query)
    await safe_send_with_buttons(update, text, reply_markup=topic_actions(context, query))
