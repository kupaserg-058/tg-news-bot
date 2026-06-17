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
from config import TELEGRAM_MESSAGE_LIMIT
from formatters.utils import split_for_telegram, sanitize_telegram_html
from utils.logger import log

# При любой ошибке Gemini (429 или 503) — повторяем с паузой
_RETRY_ATTEMPTS = 4
_RETRY_DELAY_S = 5 * 60  # 5 минут — Google 503 обычно спадает за 2-5 мин


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
    # Небольшая задержка чтобы classify/embed тики, запущенные в ту же минуту, успели завершиться
    await asyncio.sleep(90)
    disabled = list(await repo.get_disabled_categories(owner_chat_id))
    log.info(f"Автодайджест [{label}]: hours={hours}, исключены категории: {disabled or '—'}")

    text: str | None = None
    n_posts: int = 0
    last_error: Exception | None = None
    for attempt in range(1, _RETRY_ATTEMPTS + 1):
        try:
            text, n_posts = await compose_digest(hours, exclude_categories=disabled or None)
            break
        except Exception as e:
            last_error = e
            if attempt < _RETRY_ATTEMPTS:
                log.warning(
                    f"Автодайджест [{label}]: ошибка Gemini ({type(e).__name__}, попытка {attempt}/{_RETRY_ATTEMPTS}), "
                    f"повтор через {_RETRY_DELAY_S // 60} мин"
                )
                await asyncio.sleep(_RETRY_DELAY_S)
            else:
                log.error(f"Автодайджест [{label}]: все {_RETRY_ATTEMPTS} попытки провалились: {e}")
                try:
                    await bot.send_message(
                        chat_id=owner_chat_id,
                        text=f"⚠️ Автодайджест {label} не построился после {_RETRY_ATTEMPTS} попыток: {type(e).__name__}",
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
