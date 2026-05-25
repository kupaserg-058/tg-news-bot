"""CRUD-функции над БД."""

from datetime import datetime, timedelta, timezone

import numpy as np

from config import SEMANTIC_SIMILARITY_THRESHOLD, EXPERT_LINK_THRESHOLD
from db.connection import get_pool, is_pgvector_available


# --- channels ---

async def upsert_channel(username: str, channel_type: str, title: str | None = None) -> int:
    """Добавить канал или обновить тип. type: 'news' | 'expert'. Возвращает id."""
    pool = get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            """
            INSERT INTO channels (username, type, title)
            VALUES ($1, $2, $3)
            ON CONFLICT (username) DO UPDATE
                SET type = EXCLUDED.type,
                    title = COALESCE(EXCLUDED.title, channels.title)
            RETURNING id
            """,
            username, channel_type, title,
        )
        return row["id"]


async def remove_channel(username: str) -> bool:
    """Удаляет канал и все его посты (CASCADE). True если канал существовал."""
    pool = get_pool()
    async with pool.acquire() as conn:
        result = await conn.execute(
            "DELETE FROM channels WHERE username = $1", username,
        )
    # asyncpg возвращает строку вида "DELETE N"
    return result.endswith(" 1") or result.endswith(" 2") or "DELETE 0" not in result


async def get_all_channels() -> list[dict]:
    pool = get_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            "SELECT id, username, type, title, last_parsed_msg_id FROM channels ORDER BY id"
        )
    return [dict(r) for r in rows]


async def update_last_parsed(channel_id: int, msg_id: int) -> None:
    pool = get_pool()
    async with pool.acquire() as conn:
        await conn.execute(
            "UPDATE channels SET last_parsed_msg_id = $1 WHERE id = $2",
            msg_id, channel_id,
        )


# --- posts ---

async def bulk_insert_posts(posts: list[dict]) -> int:
    """posts: [{channel_id, tg_message_id, text, posted_at, link, [embedding]}].
    Если embedding есть и pgvector доступен — сохраняем."""
    if not posts:
        return 0
    pool = get_pool()
    use_emb = is_pgvector_available() and any(p.get("embedding") is not None for p in posts)
    async with pool.acquire() as conn:
        if use_emb:
            await conn.executemany(
                """
                INSERT INTO posts (channel_id, tg_message_id, text, posted_at, link, embedding)
                VALUES ($1, $2, $3, $4, $5, $6::vector)
                ON CONFLICT (channel_id, tg_message_id) DO NOTHING
                """,
                [
                    (
                        p["channel_id"], p["tg_message_id"], p["text"],
                        p["posted_at"], p["link"], p.get("embedding"),
                    )
                    for p in posts
                ],
            )
        else:
            await conn.executemany(
                """
                INSERT INTO posts (channel_id, tg_message_id, text, posted_at, link)
                VALUES ($1, $2, $3, $4, $5)
                ON CONFLICT (channel_id, tg_message_id) DO NOTHING
                """,
                [
                    (p["channel_id"], p["tg_message_id"], p["text"], p["posted_at"], p["link"])
                    for p in posts
                ],
            )
    return len(posts)


async def get_posts_without_embedding(limit: int = 200) -> list[dict]:
    if not is_pgvector_available():
        return []
    pool = get_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            "SELECT id, text FROM posts WHERE embedding IS NULL ORDER BY posted_at DESC LIMIT $1",
            limit,
        )
    return [dict(r) for r in rows]


async def set_post_embeddings(items: list[tuple[int, np.ndarray | None]]) -> int:
    """items: [(post_id, vector)]. Векторы конвертируются в pgvector-строку.
    Возвращает число записей с непустыми векторами, которые реально обновили."""
    if not items or not is_pgvector_available():
        return 0
    from ai.embeddings import vector_to_pg
    payload = []
    for pid, v in items:
        if v is None:
            continue
        s = vector_to_pg(v)
        if s is None:
            continue
        payload.append((pid, s))
    if not payload:
        return 0
    pool = get_pool()
    async with pool.acquire() as conn:
        await conn.executemany(
            "UPDATE posts SET embedding = $2::vector WHERE id = $1",
            payload,
        )
    return len(payload)


async def count_posts_without_embedding() -> int:
    if not is_pgvector_available():
        return 0
    pool = get_pool()
    async with pool.acquire() as conn:
        return await conn.fetchval("SELECT COUNT(*) FROM posts WHERE embedding IS NULL")


async def count_posts() -> int:
    pool = get_pool()
    async with pool.acquire() as conn:
        return await conn.fetchval("SELECT COUNT(*) FROM posts")


async def get_latest_post(channel_id: int) -> dict | None:
    pool = get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT id, tg_message_id, text, posted_at, link FROM posts "
            "WHERE channel_id = $1 ORDER BY posted_at DESC LIMIT 1",
            channel_id,
        )
    return dict(row) if row else None


def _post_select_sql() -> str:
    return (
        "SELECT p.id, p.text, p.posted_at, p.link, "
        "c.username AS channel_username, c.type AS channel_type, c.title AS channel_title "
        "FROM posts p JOIN channels c ON c.id = p.channel_id "
    )


async def get_posts_last_hours(hours: int = 24, limit: int = 300, with_embeddings: bool = False) -> list[dict]:
    pool = get_pool()
    since = datetime.now(timezone.utc) - timedelta(hours=hours)
    want_emb = with_embeddings and is_pgvector_available()
    extra = ", p.embedding " if want_emb else ""
    sql = (
        f"SELECT p.id, p.text, p.posted_at, p.link, "
        f"c.username AS channel_username, c.type AS channel_type, c.title AS channel_title{extra} "
        f"FROM posts p JOIN channels c ON c.id = p.channel_id "
        f"WHERE p.posted_at >= $1 ORDER BY p.posted_at DESC LIMIT $2"
    )
    async with pool.acquire() as conn:
        rows = await conn.fetch(sql, since, limit)
    result = [dict(r) for r in rows]
    if want_emb:
        from ai.embeddings import pg_to_vector
        for r in result:
            r["embedding"] = pg_to_vector(r.get("embedding"))
    return result


# Алиас для обратной совместимости (используется в старом коде).
async def get_posts_last_24h(limit: int = 200) -> list[dict]:
    return await get_posts_last_hours(24, limit)


async def search_posts_ts(query: str, limit: int = 50, days: int | None = None) -> list[dict]:
    """Полнотекстовый поиск + ILIKE fallback. Используется когда embeddings недоступны."""
    if not query.strip():
        return []
    pool = get_pool()
    params: list = [query]
    where = ["p.fts @@ plainto_tsquery('russian', $1)"]
    if days is not None:
        params.append(datetime.now(timezone.utc) - timedelta(days=days))
        where.append(f"p.posted_at >= ${len(params)}")
    params.append(limit)
    sql = (
        _post_select_sql()
        + "WHERE " + " AND ".join(where)
        + " ORDER BY p.posted_at DESC LIMIT $" + str(len(params))
    )
    async with pool.acquire() as conn:
        rows = await conn.fetch(sql, *params)
    if rows:
        return [dict(r) for r in rows]

    like = f"%{query.strip()}%"
    params = [like, limit]
    where_clause = "WHERE p.text ILIKE $1"
    if days is not None:
        params = [like, datetime.now(timezone.utc) - timedelta(days=days), limit]
        where_clause = "WHERE p.text ILIKE $1 AND p.posted_at >= $2"
    sql = _post_select_sql() + where_clause + f" ORDER BY p.posted_at DESC LIMIT ${len(params)}"
    async with pool.acquire() as conn:
        rows = await conn.fetch(sql, *params)
    return [dict(r) for r in rows]


async def search_posts_semantic(
    query_vec: np.ndarray,
    limit: int = 50,
    days: int | None = None,
    threshold: float = SEMANTIC_SIMILARITY_THRESHOLD,
    channel_type: str | None = None,
) -> list[dict]:
    """Косинусная близость к query_vec. Возвращает посты со similarity >= threshold."""
    if not is_pgvector_available():
        return []
    from ai.embeddings import vector_to_pg
    pool = get_pool()
    qvec_str = vector_to_pg(query_vec)
    params: list = [qvec_str]
    where = ["p.embedding IS NOT NULL"]
    if days is not None:
        params.append(datetime.now(timezone.utc) - timedelta(days=days))
        where.append(f"p.posted_at >= ${len(params)}")
    if channel_type:
        params.append(channel_type)
        where.append(f"c.type = ${len(params)}")
    params.append(threshold)
    params.append(limit)
    # qvec приходит как text '[..]', cast в ::vector внутри SQL.
    sql = (
        "SELECT p.id, p.text, p.posted_at, p.link, "
        "c.username AS channel_username, c.type AS channel_type, c.title AS channel_title, "
        f"1 - (p.embedding <=> $1::vector) AS similarity "
        "FROM posts p JOIN channels c ON c.id = p.channel_id "
        f"WHERE {' AND '.join(where)} "
        f"AND (1 - (p.embedding <=> $1::vector)) >= ${len(params) - 1} "
        f"ORDER BY p.embedding <=> $1::vector LIMIT ${len(params)}"
    )
    async with pool.acquire() as conn:
        rows = await conn.fetch(sql, *params)
    return [dict(r) for r in rows]


async def search_posts(query: str, limit: int = 50, days: int | None = None) -> list[dict]:
    """Унифицированный вход: семантический поиск если доступен, иначе ts."""
    if is_pgvector_available():
        try:
            from ai.embeddings import embed_one
            qvec = await embed_one(query, task_type="RETRIEVAL_QUERY")
            results = await search_posts_semantic(qvec, limit=limit, days=days)
            if results:
                return results
        except Exception:
            pass
        # если эмбеддинг упал — fallback на ts
    return await search_posts_ts(query, limit=limit, days=days)


async def find_expert_links_for_post(post_id: int, limit: int = 3) -> list[dict]:
    """Для news-поста находит самые похожие expert-посты выше порога."""
    if not is_pgvector_available():
        return []
    pool = get_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            "SELECT p.id, p.text, p.posted_at, p.link, "
            "c.username AS channel_username, c.type AS channel_type, "
            "1 - (p.embedding <=> (SELECT embedding FROM posts WHERE id = $1)) AS similarity "
            "FROM posts p JOIN channels c ON c.id = p.channel_id "
            "WHERE c.type = 'expert' "
            "AND p.embedding IS NOT NULL "
            "AND p.id != $1 "
            "AND (1 - (p.embedding <=> (SELECT embedding FROM posts WHERE id = $1))) >= $2 "
            "ORDER BY p.embedding <=> (SELECT embedding FROM posts WHERE id = $1) "
            "LIMIT $3",
            post_id, EXPERT_LINK_THRESHOLD, limit,
        )
    return [dict(r) for r in rows]


# --- gemini cache ---

async def get_cached_response(prompt_hash: str) -> dict | None:
    pool = get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT response, model, created_at FROM gemini_cache "
            "WHERE prompt_hash = $1 AND expires_at > NOW()",
            prompt_hash,
        )
    return dict(row) if row else None


async def set_cached_response(
    prompt_hash: str,
    query_type: str,
    prompt: str,
    response: str,
    model: str,
    ttl_seconds: int,
) -> None:
    pool = get_pool()
    async with pool.acquire() as conn:
        await conn.execute(
            """
            INSERT INTO gemini_cache (prompt_hash, query_type, prompt, response, model, expires_at)
            VALUES ($1, $2, $3, $4, $5, NOW() + ($6 || ' seconds')::interval)
            ON CONFLICT (prompt_hash) DO UPDATE
                SET response = EXCLUDED.response,
                    model = EXCLUDED.model,
                    created_at = NOW(),
                    expires_at = EXCLUDED.expires_at
            """,
            prompt_hash, query_type, prompt, response, model, str(ttl_seconds),
        )


async def purge_expired_cache() -> int:
    pool = get_pool()
    async with pool.acquire() as conn:
        result = await conn.execute("DELETE FROM gemini_cache WHERE expires_at <= NOW()")
    # "DELETE N" -> N
    parts = result.split()
    return int(parts[1]) if len(parts) == 2 else 0


# --- query log ---

async def log_query(user_id: int | None, command: str, query: str | None) -> None:
    pool = get_pool()
    async with pool.acquire() as conn:
        await conn.execute(
            "INSERT INTO query_log (user_id, command, query) VALUES ($1, $2, $3)",
            user_id, command, query,
        )


async def purge_old_query_log(days: int = 30) -> int:
    pool = get_pool()
    async with pool.acquire() as conn:
        result = await conn.execute(
            "DELETE FROM query_log WHERE created_at < NOW() - ($1 || ' days')::interval",
            str(days),
        )
    parts = result.split()
    return int(parts[1]) if len(parts) == 2 else 0
