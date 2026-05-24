"""/digest [N|Nh|Nd|Nw] — AI-сгруппированный дайджест с inline-кнопками тем."""

from telegram import Update
from telegram.ext import ContextTypes

from ai.digest_service import compose_digest
from ai.gemini_client import GeminiQuotaError
from db import repository as repo
from formatters.buttons import digest_actions
from formatters.duration import parse_duration_to_hours, format_hours, DurationError
from formatters.utils import escape_html
from handlers.callbacks import _extract_digest_topics
from handlers.common import owner_only, safe_send_with_buttons, safe_send, QUOTA_HINT


@owner_only
async def digest(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    hours = 24
    if context.args:
        try:
            hours = parse_duration_to_hours(" ".join(context.args))
        except DurationError as e:
            await safe_send(update, f"⚠️ {escape_html(str(e))}")
            return

    await repo.log_query(update.effective_user.id, "/digest", str(hours))
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
