"""Автодайджест: периодическая отправка дайджеста владельцу.

Две схемы запуска (можно использовать обе):
1. По расписанию (cron) — в DIGEST_TIME_MORNING и DIGEST_TIME_EVENING (формат HH:MM).
2. По интервалу — каждые DIGEST_INTERVAL_HOURS часов (если переменная > 0).

Обе шлют в OWNER_CHAT_ID.
"""

import asyncio

from telegram import Bot
from telegram.constants import ParseMode

from ai.digest_service import compose_digest
from ai.gemini_client import GeminiQuotaError
from config import TELEGRAM_MESSAGE_LIMIT
from formatters.utils import split_for_telegram, sanitize_telegram_html
from utils.logger import log

# При GeminiQuotaError — повторяем с паузой, максимум столько раз
_QUOTA_RETRY_ATTEMPTS = 3
_QUOTA_RETRY_DELAY_S = 30 * 60  # 30 минут между попытками


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
    Учитывает disabled-категории владельца — они исключаются из выдачи.
    При GeminiQuotaError повторяет до _QUOTA_RETRY_ATTEMPTS раз с паузой."""
    from db import repository as repo
    disabled = list(await repo.get_disabled_categories(owner_chat_id))
    log.info(f"Автодайджест [{label}]: hours={hours}, исключены категории: {disabled or '—'}")

    text: str | None = None
    n_posts: int = 0
    for attempt in range(1, _QUOTA_RETRY_ATTEMPTS + 1):
        try:
            text, n_posts = await compose_digest(hours, exclude_categories=disabled or None)
            break
        except GeminiQuotaError as e:
            if attempt < _QUOTA_RETRY_ATTEMPTS:
                log.warning(
                    f"Автодайджест [{label}]: квота исчерпана (попытка {attempt}/{_QUOTA_RETRY_ATTEMPTS}), "
                    f"повтор через {_QUOTA_RETRY_DELAY_S // 60} мин"
                )
                await asyncio.sleep(_QUOTA_RETRY_DELAY_S)
            else:
                log.error(f"Автодайджест [{label}]: все {_QUOTA_RETRY_ATTEMPTS} попытки исчерпаны: {e}")
                try:
                    await bot.send_message(
                        chat_id=owner_chat_id,
                        text=f"⚠️ Автодайджест {label} не построился: квота Gemini исчерпана (попробовал {_QUOTA_RETRY_ATTEMPTS}×)",
                    )
                except Exception:
                    pass
                return
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
