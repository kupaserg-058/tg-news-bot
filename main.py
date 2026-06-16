"""Точка входа."""

import asyncio
import signal

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.interval import IntervalTrigger
from apscheduler.triggers.cron import CronTrigger
from telegram import Update, BotCommand
from telegram.ext import Application, CommandHandler, MessageHandler, CallbackQueryHandler, filters

from config import PARSER_INTERVAL_MIN, TIMEZONE
from utils.logger import log
from utils.env import load_env
from db.connection import init_pool, close_pool
from db.migrations import apply_schema
from parser.telethon_client import init_client, disconnect_client
from parser.scheduler_jobs import parse_all_channels_job
from jobs.auto_digest import push_digest
from jobs.cache_purge import purge_cache_job
from jobs.embed_recent import embed_recent_job
from jobs.classify_recent import classify_recent_job
from ai.key_rotator import init_rotator

from handlers.common import set_owner_chat_id, on_error
from handlers.start import start, help_cmd, menu_cmd
from handlers.channels import add_channel, remove_channel, list_channels
from handlers.digest import digest
from handlers.search import search
from handlers.why import why
from handlers.context_cmd import context_cmd, chronicle_cmd
from handlers.map_graph import map_cmd
from handlers.menu import text_router
from handlers.admin import clear_cache, stats, test_keys, test_digest
from handlers.callbacks import on_callback


BOT_COMMANDS = [
    BotCommand("menu",           "Показать главное меню"),
    BotCommand("digest",         "AI-сводка по темам (опц. период: 6 / 12h / 3d)"),
    BotCommand("why",            "Глубокий разбор темы"),
    BotCommand("chronicle",      "Хроника событий по теме"),
    BotCommand("map",            "Граф связей (Mermaid)"),
    BotCommand("search",         "Сырой поиск по базе"),
    BotCommand("add_channel",    "Добавить канал: @name news|expert"),
    BotCommand("remove_channel", "Удалить канал"),
    BotCommand("list_channels",  "Список каналов"),
    BotCommand("stats",          "Статистика"),
    BotCommand("clear_cache",    "Сброс кеша Gemini"),
    BotCommand("help",           "Справка"),
]


def build_application(token: str) -> Application:
    app = Application.builder().token(token).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("help", help_cmd))
    app.add_handler(CommandHandler("menu", menu_cmd))

    app.add_handler(CommandHandler("add_channel", add_channel))
    app.add_handler(CommandHandler("remove_channel", remove_channel))
    app.add_handler(CommandHandler("list_channels", list_channels))

    app.add_handler(CommandHandler("digest", digest))
    app.add_handler(CommandHandler("search", search))

    app.add_handler(CommandHandler("why", why))
    app.add_handler(CommandHandler("context", context_cmd))
    app.add_handler(CommandHandler("chronicle", chronicle_cmd))
    app.add_handler(CommandHandler("map", map_cmd))

    app.add_handler(CommandHandler("clear_cache", clear_cache))
    app.add_handler(CommandHandler("stats", stats))
    app.add_handler(CommandHandler("test_keys", test_keys))
    app.add_handler(CommandHandler("test_digest", test_digest))

    app.add_handler(CallbackQueryHandler(on_callback))

    # Текстовый роутер: меню → ожидание темы → свободный текст. Должен быть последним.
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, text_router))

    app.add_error_handler(on_error)
    return app


def _parse_hhmm(s: str) -> tuple[int, int]:
    h, m = s.split(":", 1)
    return int(h), int(m)


def register_digest_jobs(scheduler: AsyncIOScheduler, env: dict, bot) -> None:
    owner_id = env["OWNER_CHAT_ID"]

    morning_h, morning_m = _parse_hhmm(env["DIGEST_TIME_MORNING"])
    scheduler.add_job(
        push_digest,
        trigger=CronTrigger(hour=morning_h, minute=morning_m, timezone=TIMEZONE),
        kwargs=dict(bot=bot, owner_chat_id=owner_id, hours=12, label="Утренний дайджест"),
        id="digest_morning",
    )
    log.info(f"Утренний дайджест: каждый день в {env['DIGEST_TIME_MORNING']} (за 12ч)")

    evening_h, evening_m = _parse_hhmm(env["DIGEST_TIME_EVENING"])
    scheduler.add_job(
        push_digest,
        trigger=CronTrigger(hour=evening_h, minute=evening_m, timezone=TIMEZONE),
        kwargs=dict(bot=bot, owner_chat_id=owner_id, hours=12, label="Вечерний дайджест"),
        id="digest_evening",
    )
    log.info(f"Вечерний дайджест: каждый день в {env['DIGEST_TIME_EVENING']} (за 12ч)")

    interval = env["DIGEST_INTERVAL_HOURS"]
    if interval > 0:
        scheduler.add_job(
            push_digest,
            trigger=IntervalTrigger(hours=interval),
            kwargs=dict(bot=bot, owner_chat_id=owner_id, hours=interval, label=f"Дайджест за {interval}ч"),
            id="digest_interval",
        )
        log.info(f"Интервальный дайджест: каждые {interval} ч.")


async def amain() -> None:
    log.info("=== Bot starting ===")
    env = load_env()
    set_owner_chat_id(env["OWNER_CHAT_ID"])
    init_rotator(env["GEMINI_API_KEYS"])

    await init_pool(env["POSTGRES_URL"])
    await apply_schema()
    await init_client(env["TELEGRAM_API_ID"], env["TELEGRAM_API_HASH"], env["TELETHON_SESSION"])

    scheduler = AsyncIOScheduler(timezone=TIMEZONE)
    scheduler.add_job(
        parse_all_channels_job,
        trigger=IntervalTrigger(minutes=PARSER_INTERVAL_MIN),
        id="parse_all_channels",
    )
    scheduler.add_job(
        purge_cache_job,
        trigger=IntervalTrigger(hours=1),
        id="purge_cache",
    )
    scheduler.add_job(
        embed_recent_job,
        trigger=IntervalTrigger(minutes=10),
        id="embed_recent",
    )
    scheduler.add_job(
        classify_recent_job,
        trigger=IntervalTrigger(minutes=10),
        id="classify_recent",
    )

    application = build_application(env["TELEGRAM_BOT_TOKEN"])
    register_digest_jobs(scheduler, env, application.bot)
    scheduler.start()
    log.info(f"Scheduler запущен. Парсинг каждые {PARSER_INTERVAL_MIN} мин. Cache purge каждый час.")

    await application.initialize()
    await application.bot.set_my_commands(BOT_COMMANDS)
    await application.start()
    await application.updater.start_polling(allowed_updates=Update.ALL_TYPES)
    log.info("Бот запущен, polling активен. Жду команд.")

    asyncio.create_task(parse_all_channels_job())

    stop_event = asyncio.Event()
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(sig, stop_event.set)
    await stop_event.wait()

    log.info("Останавливаюсь...")
    await application.updater.stop()
    await application.stop()
    await application.shutdown()
    scheduler.shutdown(wait=False)
    await disconnect_client()
    await close_pool()
    log.info("Остановлен.")


def main() -> None:
    try:
        asyncio.run(amain())
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
