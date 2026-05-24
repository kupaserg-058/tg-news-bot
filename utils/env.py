import os
from dotenv import load_dotenv

from utils.logger import log


REQUIRED = [
    "TELEGRAM_BOT_TOKEN",
    "TELEGRAM_API_ID",
    "TELEGRAM_API_HASH",
    "TELETHON_SESSION",
    "GEMINI_API_KEY",
    "POSTGRES_URL",
    "OWNER_CHAT_ID",
]

OPTIONAL_DEFAULTS = {
    "DIGEST_TIME_MORNING": "09:00",
    "DIGEST_TIME_EVENING": "21:00",
    "DIGEST_INTERVAL_HOURS": "0",  # 0 = выключено; >0 = присылать каждые N часов
    "DISABLE_EMBEDDINGS": "0",     # 1 = семантика отключена, работаем только на ts-поиске
}


def load_env() -> dict:
    """Загружает .env, проверяет обязательные переменные. Возвращает dict со всеми значениями."""
    load_dotenv()

    missing = [k for k in REQUIRED if not os.getenv(k)]
    if missing:
        raise RuntimeError(
            f"Отсутствуют обязательные переменные окружения: {', '.join(missing)}. "
            f"Скопируй .env.example в .env и заполни."
        )

    env = {k: os.getenv(k) for k in REQUIRED}
    for k, default in OPTIONAL_DEFAULTS.items():
        env[k] = os.getenv(k, default)

    env["TELEGRAM_API_ID"] = int(env["TELEGRAM_API_ID"])
    env["OWNER_CHAT_ID"] = int(env["OWNER_CHAT_ID"])
    env["DIGEST_INTERVAL_HOURS"] = int(env["DIGEST_INTERVAL_HOURS"])
    env["DISABLE_EMBEDDINGS"] = env["DISABLE_EMBEDDINGS"] in ("1", "true", "True", "yes")

    log.info("Переменные окружения загружены, все обязательные на месте")
    return env
