import os
from dotenv import load_dotenv

from utils.logger import log


REQUIRED = [
    "TELEGRAM_BOT_TOKEN",
    "TELEGRAM_API_ID",
    "TELEGRAM_API_HASH",
    "TELETHON_SESSION",
    "POSTGRES_URL",
    "OWNER_CHAT_ID",
]
# GEMINI_API_KEY теперь не обязательна, если задан GEMINI_API_KEYS (множественные ключи).

OPTIONAL_DEFAULTS = {
    "DIGEST_TIME_MORNING": "09:00",
    "DIGEST_TIME_EVENING": "21:00",
    "DIGEST_INTERVAL_HOURS": "0",  # 0 = выключено; >0 = присылать каждые N часов
    "DISABLE_EMBEDDINGS": "0",     # 1 = семантика отключена, работаем только на ts-поиске
}


import re

_KEY_SEP_RE = re.compile(r"[,;\s]+")  # запятая, точка с запятой, любой whitespace


def _parse_gemini_keys() -> list[str]:
    """Собирает все доступные Gemini-ключи. Разделители: запятая, ;, пробелы, переносы.
    Делает базовую санитизацию каждого ключа от невидимых символов."""
    keys: list[str] = []
    multi = os.getenv("GEMINI_API_KEYS", "")
    for k in _KEY_SEP_RE.split(multi):
        # Убираем zero-width и неразрывные пробелы которые иногда вставляются при копировании
        k = "".join(ch for ch in k if ch.isprintable() and ch not in " ​‌‍﻿")
        k = k.strip()
        if k:
            keys.append(k)
    single = "".join(
        ch for ch in os.getenv("GEMINI_API_KEY", "")
        if ch.isprintable() and ch not in " ​‌‍﻿"
    ).strip()
    if single and single not in keys:
        keys.append(single)
    return keys


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

    gemini_keys = _parse_gemini_keys()
    if not gemini_keys:
        raise RuntimeError(
            "Не задано ни одного Gemini-ключа. Заполни GEMINI_API_KEY или GEMINI_API_KEYS (через запятую)."
        )
    env["GEMINI_API_KEYS"] = gemini_keys

    env["TELEGRAM_API_ID"] = int(env["TELEGRAM_API_ID"])
    env["OWNER_CHAT_ID"] = int(env["OWNER_CHAT_ID"])
    env["DIGEST_INTERVAL_HOURS"] = int(env["DIGEST_INTERVAL_HOURS"])
    env["DISABLE_EMBEDDINGS"] = env["DISABLE_EMBEDDINGS"] in ("1", "true", "True", "yes")

    log.info(f"Переменные окружения загружены, Gemini-ключей: {len(gemini_keys)}")
    return env
