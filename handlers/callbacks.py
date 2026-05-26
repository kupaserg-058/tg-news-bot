"""Единый CallbackQueryHandler для кнопок под AI-ответами.

Формат callback_data:
- "why|<tid>", "context|<tid>", "map|<tid>", "more|<tid>" — действие по теме (id из bot_data)
- "d6", "d24", "d72" — быстрый интервал дайджеста (часы)
"""

from telegram import Update
from telegram.ext import ContextTypes

from ai import gemini_client
from ai.digest_service import compose_digest
from ai.gemini_client import GeminiQuotaError
from ai.prompts import build_why_prompt, build_context_prompt, build_chronicle_prompt, build_map_prompt, build_free_prompt
from config import MAX_POSTS_IN_PROMPT
from db import repository as repo
from formatters.buttons import get_topic, topic_actions, digest_actions
from formatters.duration import format_hours
from formatters.utils import escape_html
from handlers.common import safe_send_with_buttons, send_long, owner_only_callback, QUOTA_HINT
from handlers.map_graph import _extract_mermaid, _send_map
from utils.logger import log


def _extract_digest_topics(text: str) -> list[str]:
    """Берёт строки с тематическими заголовками (<b>...</b>) для построения кнопок."""
    import re
    found = re.findall(r"<b>([^<]+)</b>", text)
    # Отфильтровываем длинные служебные и пустые заголовки.
    topics: list[str] = []
    skip = {"что говорят эксперты", "источники", "хроника", "причины", "мой взгляд"}
    for t in found:
        clean = t.strip().lstrip("📌🤖🪞🔗🧭💬⏰📅").strip()
        if not clean or clean.lower() in skip:
            continue
        if len(clean) > 60:
            continue
        if clean not in topics:
            topics.append(clean)
    return topics


@owner_only_callback
async def on_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    cq = update.callback_query
    data = cq.data or ""
    log.info(f"callback: {data}")

    # Настройки категорий (свой обработчик, сам зовёт cq.answer)
    if data.startswith("cat:"):
        from handlers.categories_settings import on_categories_callback
        await on_categories_callback(update, context)
        return

    await cq.answer()

    # Быстрый интервал дайджеста.
    if data.startswith("d"):
        try:
            hours = int(data[1:])
        except ValueError:
            return
        await _do_digest(update, context, hours)
        return

    # Действия по теме.
    if "|" in data:
        action, tid = data.split("|", 1)
        topic = get_topic(context, tid)
        if topic is None:
            await safe_send_with_buttons(update, "⚠️ Кнопка устарела (бот перезапускался). Введи команду заново.")
            return
        if action == "why":
            await _do_why(update, context, topic)
        elif action == "chronicle":
            await _do_chronicle(update, context, topic)
        elif action == "context":
            # backward-compat: старые callback'ы
            await _do_chronicle(update, context, topic)
        elif action == "map":
            await _do_map(update, context, topic)
        elif action == "more":
            await _do_more(update, context, topic)


async def _do_digest(update: Update, context: ContextTypes.DEFAULT_TYPE, hours: int) -> None:
    chat = update.effective_chat
    await chat.send_message(f"🤖 Группирую посты за {format_hours(hours)}...")
    try:
        text, n_posts = await compose_digest(hours)
    except GeminiQuotaError:
        await chat.send_message(QUOTA_HINT)
        return
    except Exception as e:
        await chat.send_message(f"❌ {type(e).__name__}: {e}")
        return
    if text is None:
        await chat.send_message(f"📅 За {format_hours(hours)} в базе ничего нет.")
        return
    header = f"📅 <b>Дайджест за {format_hours(hours)}</b> <i>({n_posts} постов)</i>\n\n"
    topics = _extract_digest_topics(text)
    markup = digest_actions(context, topics, hours)
    await send_long(chat, header + text, reply_markup=markup)


async def _do_why(update: Update, context: ContextTypes.DEFAULT_TYPE, topic: str) -> None:
    chat = update.effective_chat
    posts = await repo.search_posts(topic, limit=MAX_POSTS_IN_PROMPT)
    await chat.send_message(f"🔎 «{escape_html(topic)}»: нашёл {len(posts)} постов. Думаю...")
    prompt = build_why_prompt(topic, posts)
    try:
        text = await gemini_client.generate(prompt, query_type="why", use_search=True)
    except GeminiQuotaError:
        await chat.send_message(QUOTA_HINT)
        return
    except Exception as e:
        await chat.send_message(f"❌ {type(e).__name__}: {e}")
        return
    await send_long(chat, text, reply_markup=topic_actions(context, topic, exclude="why"))


async def _do_chronicle(update: Update, context: ContextTypes.DEFAULT_TYPE, topic: str) -> None:
    chat = update.effective_chat
    posts = await repo.search_posts(topic, limit=MAX_POSTS_IN_PROMPT)
    await chat.send_message(f"📜 Собираю хронику «{escape_html(topic)}» из {len(posts)} постов...")
    prompt = build_chronicle_prompt(topic, posts)
    try:
        text = await gemini_client.generate(prompt, query_type="context", use_search=True)
    except GeminiQuotaError:
        await chat.send_message(QUOTA_HINT)
        return
    except Exception as e:
        await chat.send_message(f"❌ {type(e).__name__}: {e}")
        return
    await send_long(chat, text, reply_markup=topic_actions(context, topic, exclude="chronicle"))


async def _do_map(update: Update, context: ContextTypes.DEFAULT_TYPE, topic: str) -> None:
    chat = update.effective_chat
    posts = await repo.search_posts(topic, limit=MAX_POSTS_IN_PROMPT)
    await chat.send_message(f"🕸 Граф «{escape_html(topic)}» из {len(posts)} постов...")
    prompt = build_map_prompt(topic, posts)
    try:
        text = await gemini_client.generate(prompt, query_type="map", use_search=False)
    except GeminiQuotaError:
        await chat.send_message(QUOTA_HINT)
        return
    except Exception as e:
        await chat.send_message(f"❌ {type(e).__name__}: {e}")
        return
    mermaid = _extract_mermaid(text)
    await _send_map(update, context, topic, mermaid)


async def _do_more(update: Update, context: ContextTypes.DEFAULT_TYPE, topic: str) -> None:
    """Углубление: повторный запрос с инструкцией «развернуть, найти больше источников и деталей»."""
    chat = update.effective_chat
    posts = await repo.search_posts(topic, limit=MAX_POSTS_IN_PROMPT)
    await chat.send_message(f"📚 Углубляю «{escape_html(topic)}»: ищу детали и доп. источники...")

    deepen_question = (
        f"Развёрнутый рассказ про «{topic}». "
        "Нужны детали, контекст, предыстория, реакции сторон, последствия. "
        "Найди дополнительные источники в интернете помимо моей базы постов."
    )
    prompt = build_free_prompt(deepen_question, posts)
    try:
        text = await gemini_client.generate(prompt, query_type="free", use_search=True, use_cache=False)
    except GeminiQuotaError:
        await chat.send_message(QUOTA_HINT)
        return
    except Exception as e:
        await chat.send_message(f"❌ {type(e).__name__}: {e}")
        return
    await send_long(chat, text, reply_markup=topic_actions(context, topic, exclude="more"))
