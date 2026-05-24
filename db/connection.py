"""Пул подключений asyncpg + регистрация pgvector-кодека на каждое соединение."""

import asyncpg

from utils.logger import log


_pool: asyncpg.Pool | None = None
_pgvector_available: bool = False  # выставляется в migrations.apply_schema()


async def _init_connection(conn: asyncpg.Connection) -> None:
    """Намеренно НЕ регистрируем pgvector-кодек: мы передаём векторы как text '[...]'
    и явно кастуем в ::vector в SQL. Это работает и когда расширение есть, и когда нет,
    и не требует синхронизации с register_vector в каждом соединении."""
    return


def _safe_dsn_label(dsn: str) -> str:
    """Превращает postgresql://user:pass@host:port/db в host:port/db без пароля для логов."""
    try:
        # postgresql://user:pass@host:port/db
        if "@" in dsn:
            tail = dsn.split("@", 1)[1]
            return tail.split("?", 1)[0]
    except Exception:
        pass
    return "<dsn>"


async def init_pool(dsn: str, min_size: int = 1, max_size: int = 5) -> asyncpg.Pool:
    global _pool
    if _pool is not None:
        return _pool

    label = _safe_dsn_label(dsn)
    try:
        _pool = await asyncpg.create_pool(
            dsn=dsn,
            min_size=min_size,
            max_size=max_size,
            command_timeout=30,
            init=_init_connection,
        )
    except Exception as e:
        # Не пробрасываем оригинальный exception целиком — он может содержать DSN с паролем.
        raise RuntimeError(f"Не удалось подключиться к {label} ({type(e).__name__})") from None
    log.info(f"asyncpg pool создан: {label}, min={min_size}, max={max_size}")
    return _pool


def get_pool() -> asyncpg.Pool:
    if _pool is None:
        raise RuntimeError("Pool не инициализирован. Вызови init_pool() первым.")
    return _pool


def set_pgvector_available(value: bool) -> None:
    global _pgvector_available
    _pgvector_available = value


def is_pgvector_available() -> bool:
    return _pgvector_available


async def close_pool() -> None:
    global _pool
    if _pool is not None:
        await _pool.close()
        _pool = None
        log.info("asyncpg pool закрыт")
