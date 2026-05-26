"""/context тема — исторические параллели через Google Search."""

from telegram import Update
from telegram.ext import ContextTypes

from ai import gemini_client
from ai.gemini_client import GeminiQuotaError
from ai.prompts import build_context_prompt, build_chronicle_prompt
from config import MAX_POSTS_IN_PROMPT
from db import repository as repo
from formatters.buttons import topic_actions
from formatters.utils import escape_html
from handlers.common import owner_only, safe_send, safe_send_with_buttons, clamp_topic, QUOTA_HINT


@owner_only
async def context_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    topic = clamp_topic(" ".join(context.args))
    if not topic:
        await safe_send(update, "Использование: <code>/context тема</code>, например <code>/context инфляция в России</code>")
        return

    await repo.log_query(update.effective_user.id, "/context", topic)
    await safe_send(update, f"🪞 Ищу исторические параллели по «{escape_html(topic)}»...")
    prompt = build_context_prompt(topic)
    try:
        text = await gemini_client.generate(prompt, query_type="context", use_search=True)
    except GeminiQuotaError:
        await safe_send(update, QUOTA_HINT)
        return
    except Exception as e:
        await safe_send(update, f"❌ Gemini не ответил: <code>{escape_html(type(e).__name__)}: {escape_html(str(e))}</code>")
        return

    await safe_send_with_buttons(update, text, reply_markup=topic_actions(context, topic, exclude="chronicle"))


@owner_only
async def chronicle_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """/chronicle тема — хроника событий по теме с мнениями экспертов."""
    topic = clamp_topic(" ".join(context.args))
    if not topic:
        await safe_send(update, "Использование: <code>/chronicle тема</code>, например <code>/chronicle выборы в США</code>")
        return

    await repo.log_query(update.effective_user.id, "/chronicle", topic)
    posts = await repo.search_posts(topic, limit=MAX_POSTS_IN_PROMPT)
    await safe_send(update, f"📜 Собираю хронику «{escape_html(topic)}» из {len(posts)} постов...")
    prompt = build_chronicle_prompt(topic, posts)
    try:
        text = await gemini_client.generate(prompt, query_type="context", use_search=True)
    except GeminiQuotaError:
        await safe_send(update, QUOTA_HINT)
        return
    except Exception as e:
        await safe_send(update, f"❌ Gemini не ответил: <code>{escape_html(type(e).__name__)}: {escape_html(str(e))}</code>")
        return

    await safe_send_with_buttons(update, text, reply_markup=topic_actions(context, topic, exclude="chronicle"))
