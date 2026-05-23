"""Точка входа. Пока — только проверка окружения и базовый лог.
По мере прохождения шагов плана сюда подключатся БД, парсер, бот и scheduler.
"""

from utils.logger import log
from utils.env import load_env


def main() -> None:
    log.info("=== Bot starting ===")
    env = load_env()
    log.info(f"OWNER_CHAT_ID = {env['OWNER_CHAT_ID']}")
    log.info(f"DIGEST: утро {env['DIGEST_TIME_MORNING']}, вечер {env['DIGEST_TIME_EVENING']}")
    log.info("Шаг 1 готов. Дальше будут БД, парсер и бот.")


if __name__ == "__main__":
    main()
