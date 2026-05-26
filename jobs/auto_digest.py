"""Автодайджест: периодическая отправка дайджеста владельцу.

Две схемы запуска (можно использовать обе):
1. По расписанию (cron) — в DIGEST_TIME_MORNING и DIGEST_TIME_EVENING (формат HH:MM).
2. По интервалу — каждые DIGEST_INTERVAL_HOURS часов (если переменная > 0).

Обе шлют в OWNER_CHAT_ID.
"""

from telegram import Bot
from telegram.constants import ParseMode

from ai.digest_service import compose_digest
from config import TELEGRAM_MESSAGE_LIMIT
from formatters.utils import split_for_telegram, sanitize_telegram_html
from utils.logger import log


async def _send_to_owner(bot: Bot, owner_chat_id: int, text: str) -> None:
    text = sanitize_telegram_html(text)
    for chunk in split_for_telegram(text, TELEGRAM_MESSAGE_LIMIT):
        await bot.send_message(
            chat_id=owner_chat_id,
            text=chunk,
            parse_mode=ParseMode.HTML,
            disable_web_page_preview=True,
        )


async def push_digest(bot: Bot, owner_chat_id: int, hours: int, label: str) -> None:
    """Один проход: построить дайджест и запушить владельцу. label идёт в заголовок.
    Учитывает disabled-категории владельца — они исключаются из выдачи."""
    from db import repository as repo
    disabled = list(await repo.get_disabled_categories(owner_chat_id))
    log.info(f"Автодайджест [{label}]: hours={hours}, исключены категории: {disabled or '—'}")
    try:
        text, n_posts = await compose_digest(hours, exclude_categories=disabled or None)
    except Exception as e:
        log.exception(f"Автодайджест [{label}] упал: {e}")
        try:
            await bot.send_message(
                chat_id=owner_chat_id,
                text=f"⚠️ Автодайджест {label} не построился: {type(e).__name__}",
            )
        except Exception:
            pass
        return

    if text is None:
        log.info(f"Автодайджест [{label}]: постов за {hours}ч нет, ничего не шлю")
        return

    header = f"⏰ <b>{label} от Марка</b> <i>({n_posts} постов за {hours} ч.)</i>\n\n"
    await _send_to_owner(bot, owner_chat_id, header + text)
    log.info(f"Автодайджест [{label}] отправлен")
