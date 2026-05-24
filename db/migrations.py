"""Применение schema.sql + опциональное включение pgvector с адаптацией размерности."""

import os
from pathlib import Path

from config import EMBEDDING_DIM
from db.connection import get_pool, set_pgvector_available
from utils.logger import log


SCHEMA_PATH = Path(__file__).parent / "schema.sql"


def _vector_ddl(dim: int) -> str:
    return f"""
    ALTER TABLE posts ADD COLUMN IF NOT EXISTS embedding vector({dim});
    CREATE INDEX IF NOT EXISTS idx_posts_embedding
        ON posts USING hnsw (embedding vector_cosine_ops);
    """


async def _current_embedding_dim(conn) -> int | None:
    """Возвращает текущую размерность колонки posts.embedding, или None если колонки нет."""
    row = await conn.fetchrow(
        """
        SELECT format_type(a.atttypid, a.atttypmod) AS coltype
        FROM pg_attribute a
        JOIN pg_class c ON c.oid = a.attrelid
        WHERE c.relname = 'posts' AND a.attname = 'embedding' AND a.attnum > 0
        """
    )
    if not row:
        return None
    # формат: 'vector(768)' → 768
    coltype = row["coltype"]
    if coltype.startswith("vector(") and coltype.endswith(")"):
        try:
            return int(coltype[7:-1])
        except ValueError:
            return None
    return None


async def apply_schema() -> None:
    sql = SCHEMA_PATH.read_text(encoding="utf-8")
    pool = get_pool()

    async with pool.acquire() as conn:
        await conn.execute(sql)
        log.info("Базовая схема БД применена")

        if os.environ.get("DISABLE_EMBEDDINGS", "0") in ("1", "true", "True", "yes"):
            log.info("DISABLE_EMBEDDINGS=1 — семантика отключена, работаем только на ts-поиске")
            set_pgvector_available(False)
            return

        pgvector_ok = False
        try:
            await conn.execute("CREATE EXTENSION IF NOT EXISTS vector")

            current_dim = await _current_embedding_dim(conn)
            if current_dim is not None and current_dim != EMBEDDING_DIM:
                log.warning(
                    f"Размерность embedding в БД ({current_dim}) не совпадает с конфигом ({EMBEDDING_DIM}). "
                    f"Пересоздаю колонку. Старые векторы будут потеряны."
                )
                await conn.execute("DROP INDEX IF EXISTS idx_posts_embedding")
                await conn.execute("ALTER TABLE posts DROP COLUMN IF EXISTS embedding")

            await conn.execute(_vector_ddl(EMBEDDING_DIM))
            pgvector_ok = True
            log.info(f"pgvector OK. embedding-колонка vector({EMBEDDING_DIM}), hnsw-индекс создан")
        except Exception as e:
            log.warning(
                f"pgvector недоступен ({type(e).__name__}: {e}). "
                f"Семантический поиск отключён, работаем на ts_vector."
            )

    set_pgvector_available(pgvector_ok)
