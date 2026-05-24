"""Обработчик свободного текста — собирает посты из БД и даёт развёрнутый аналитический ответ."""

from telegram import Update
from telegram.ext import ContextTypes

from ai import gemini_client
from ai.gemini_client import GeminiQuotaError
from ai.prompts import build_free_prompt
from config import MAX_POSTS_IN_PROMPT
from db import repository as repo
from formatters.buttons import topic_actions
from formatters.utils import escape_html
from handlers.common import owner_only, safe_send, safe_send_with_buttons, clamp_topic, QUOTA_HINT


@owner_only
async def free_text(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not update.message or not update.message.text:
        return
    question = clamp_topic(update.message.text)
    if not question or question.startswith("/"):
        return

    await repo.log_query(update.effective_user.id, "free_text", question)
    posts = await repo.search_posts(question, limit=MAX_POSTS_IN_PROMPT)

    await safe_send(update, f"🔎 Запрос «{escape_html(question)}»: {len(posts)} постов в базе. Думаю...")
    prompt = build_free_prompt(question, posts)
    try:
        text = await gemini_client.generate(prompt, query_type="free", use_search=True)
    except GeminiQuotaError:
        await safe_send(update, QUOTA_HINT)
        return
    except Exception as e:
        await safe_send(update, f"❌ Gemini не ответил: <code>{escape_html(type(e).__name__)}: {escape_html(str(e))}</code>")
        return

    await safe_send_with_buttons(update, text, reply_markup=topic_actions(context, question))
