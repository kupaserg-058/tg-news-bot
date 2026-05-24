"""/why тема — глубокий анализ с кнопками."""

from telegram import Update
from telegram.ext import ContextTypes

from ai import gemini_client
from ai.gemini_client import GeminiQuotaError
from ai.prompts import build_why_prompt
from config import MAX_POSTS_IN_PROMPT
from db import repository as repo
from formatters.buttons import topic_actions
from formatters.utils import escape_html
from handlers.common import owner_only, safe_send, safe_send_with_buttons, clamp_topic, QUOTA_HINT


@owner_only
async def why(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    topic = clamp_topic(" ".join(context.args))
    if not topic:
        await safe_send(update, "Использование: <code>/why тема</code>, например <code>/why санкции против Ирана</code>")
        return

    await repo.log_query(update.effective_user.id, "/why", topic)
    posts = await repo.search_posts(topic, limit=MAX_POSTS_IN_PROMPT)

    await safe_send(update, f"🔎 «{escape_html(topic)}»: нашёл {len(posts)} постов. Гоняю Gemini + Google Search...")
    prompt = build_why_prompt(topic, posts)
    try:
        text = await gemini_client.generate(prompt, query_type="why", use_search=True)
    except GeminiQuotaError:
        await safe_send(update, QUOTA_HINT)
        return
    except Exception as e:
        await safe_send(update, f"❌ Gemini не ответил: <code>{escape_html(type(e).__name__)}: {escape_html(str(e))}</code>")
        return

    await safe_send_with_buttons(update, text, reply_markup=topic_actions(context, topic, exclude="why"))
