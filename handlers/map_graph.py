"""/map тема — граф связей в Mermaid. Сначала пробуем PNG через mermaid.ink,
при ошибке шлём текстовый блок для вставки в mermaid.live."""

import re
from io import BytesIO

from telegram import Update, InputFile
from telegram.constants import ParseMode
from telegram.ext import ContextTypes

from ai import gemini_client
from ai.gemini_client import GeminiQuotaError
from ai.prompts import build_map_prompt
from config import MAX_POSTS_IN_PROMPT
from db import repository as repo
from formatters.buttons import topic_actions
from formatters.mermaid_image import render_to_png
from formatters.utils import escape_html
from handlers.common import owner_only, safe_send, clamp_topic, QUOTA_HINT


_MERMAID_BLOCK_RE = re.compile(r"```mermaid\s*\n(.*?)```", re.DOTALL | re.IGNORECASE)


def _extract_mermaid(text: str) -> str:
    m = _MERMAID_BLOCK_RE.search(text)
    if m:
        return m.group(1).strip()
    return text.strip()


_MAP_LEGEND = (
    "🟢 поддерживает · 🔴 против · ⚪ нейтрально · 🟡 противоречиво"
)


async def _send_map(update: Update, context: ContextTypes.DEFAULT_TYPE, topic: str, mermaid: str) -> None:
    chat = update.effective_chat
    markup = topic_actions(context, topic, exclude="map")

    png = await render_to_png(mermaid)
    if png:
        bio = BytesIO(png)
        bio.name = "map.png"
        await chat.send_photo(
            photo=InputFile(bio),
            caption=f"🕸 <b>Граф: {escape_html(topic)}</b>\n<i>{_MAP_LEGEND}</i>",
            parse_mode=ParseMode.HTML,
            reply_markup=markup,
        )
        return

    # fallback: текстовый блок
    header = (
        f"🕸 <b>Граф: {escape_html(topic)}</b> <i>(не удалось отрисовать PNG, картинку построишь сам)</i>\n"
        f'Скопируй блок ниже и вставь на <a href="https://mermaid.live">mermaid.live</a>\n\n'
    )
    block = f"<pre>{escape_html(mermaid)}</pre>"
    await chat.send_message(
        header + block,
        parse_mode=ParseMode.HTML,
        disable_web_page_preview=True,
        reply_markup=markup,
    )


@owner_only
async def map_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    topic = clamp_topic(" ".join(context.args))
    if not topic:
        await safe_send(update, "Использование: <code>/map тема</code>, например <code>/map иранский кризис</code>")
        return

    await repo.log_query(update.effective_user.id, "/map", topic)
    posts = await repo.search_posts(topic, limit=MAX_POSTS_IN_PROMPT)
    if not posts:
        await safe_send(update, f"⚠️ По «{escape_html(topic)}» в базе нет постов. Граф строится в основном из них.")

    await safe_send(update, f"🕸 Строю граф по «{escape_html(topic)}» из {len(posts)} постов...")
    prompt = build_map_prompt(topic, posts)
    try:
        text = await gemini_client.generate(prompt, query_type="map", use_search=False)
    except GeminiQuotaError:
        await safe_send(update, QUOTA_HINT)
        return
    except Exception as e:
        await safe_send(update, f"❌ Gemini не ответил: <code>{escape_html(type(e).__name__)}: {escape_html(str(e))}</code>")
        return

    mermaid = _extract_mermaid(text)
    await _send_map(update, context, topic, mermaid)
