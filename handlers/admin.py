"""Админ-команды: /clear_cache, /stats."""

from telegram import Update
from telegram.ext import ContextTypes

import httpx

from ai.key_rotator import get_rotator
from config import category_label, CATEGORIES
from db.connection import get_pool, is_pgvector_available
from db import repository as repo
from handlers.common import owner_only, safe_send
from formatters.utils import escape_html


@owner_only
async def test_digest(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """/test_digest — запускает push_digest как будто пришло время автодайджеста."""
    from jobs.auto_digest import push_digest
    await safe_send(update, "⏳ Запускаю тестовый дайджест...")
    await push_digest(
        bot=context.bot,
        owner_chat_id=update.effective_chat.id,
        hours=12,
        label="Тестовый дайджест",
    )
    await safe_send(update, "✅ Готово")


@owner_only
async def clear_cache(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """/clear_cache [тип] — чистит Gemini-кеш. Без аргумента — весь кеш. Тип: digest|search|why|context|map|free."""
    pool = get_pool()
    query_type = context.args[0].lower() if context.args else None

    async with pool.acquire() as conn:
        if query_type:
            result = await conn.execute(
                "DELETE FROM gemini_cache WHERE query_type = $1", query_type,
            )
        else:
            result = await conn.execute("DELETE FROM gemini_cache")
    parts = result.split()
    deleted = int(parts[1]) if len(parts) == 2 else 0
    suffix = f" для типа <code>{escape_html(query_type)}</code>" if query_type else ""
    await safe_send(update, f"🧹 Удалено записей кеша{suffix}: <b>{deleted}</b>")


@owner_only
async def stats(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    pool = get_pool()
    async with pool.acquire() as conn:
        n_channels = await conn.fetchval("SELECT COUNT(*) FROM channels")
        n_posts = await conn.fetchval("SELECT COUNT(*) FROM posts")
        n_cache = await conn.fetchval("SELECT COUNT(*) FROM gemini_cache WHERE expires_at > NOW()")
        if is_pgvector_available():
            n_with_emb = await conn.fetchval("SELECT COUNT(*) FROM posts WHERE embedding IS NOT NULL")
            n_no_emb = n_posts - n_with_emb
        else:
            n_with_emb = 0
            n_no_emb = 0
        per_channel = await conn.fetch(
            """
            SELECT c.username, c.type,
                   COUNT(p.id) AS n_total,
                   COUNT(p.embedding) AS n_with_emb
            FROM channels c LEFT JOIN posts p ON p.channel_id = c.id
            GROUP BY c.id ORDER BY n_total DESC LIMIT 30
            """
        )

    lines = [
        "<b>📊 Статистика Марка</b>",
        f"Каналов: <b>{n_channels}</b>",
        f"Постов всего: <b>{n_posts}</b>",
    ]
    if is_pgvector_available():
        pct = (100 * n_with_emb // max(1, n_posts)) if n_posts else 0
        lines.append(f"С embedding: <b>{n_with_emb}</b> / {n_posts} ({pct}%)")
        if n_no_emb:
            lines.append(f"<i>Без embedding: {n_no_emb} (фоновая задача догонит свежие; старые остаются как есть)</i>")
    else:
        lines.append("pgvector: <b>выключен</b> — семантика недоступна")
    lines.append(f"Записей в кеше Gemini: <b>{n_cache}</b>")
    # Категории за последние сутки
    try:
        cat_counts = await repo.get_category_counts_last_hours(24)
        no_cat_total = await repo.count_posts_without_category(fresh_days=2)
    except Exception:
        cat_counts, no_cat_total = {}, 0
    if cat_counts or no_cat_total:
        lines.append("")
        lines.append("<b>Категории за 24ч:</b>")
        for cid, _lbl in CATEGORIES:
            n = cat_counts.get(cid, 0)
            if n:
                lines.append(f"• {category_label(cid)} — {n}")
        unknown = cat_counts.get("unknown", 0)
        if unknown:
            lines.append(f"• <i>без категории</i> — {unknown}")
        if no_cat_total:
            lines.append(f"<i>В очереди на классификацию (свежих): {no_cat_total}</i>")

    lines.append("")
    lines.append("<b>По каналам:</b>")
    for r in per_channel:
        emb_label = f" · emb {r['n_with_emb']}/{r['n_total']}" if is_pgvector_available() and r["n_total"] else ""
        lines.append(f'• {escape_html(r["username"])} <i>({r["type"]})</i> — {r["n_total"]}{emb_label}')
    await safe_send(update, "\n".join(lines))


@owner_only
async def test_keys(update, context) -> None:
    """/test_keys — прогоняет каждый Gemini-ключ тестовым GET и показывает статус."""
    rotator = get_rotator()
    keys = rotator._keys
    await safe_send(update, f"🔑 Проверяю {len(keys)} ключ(ей)...")

    # Типичная длина ключа Gemini — 39 символов. Сильно больше → склеилось несколько.
    TYPICAL_LEN = 39

    lines = ["<b>🔑 Проверка ключей</b>", ""]
    async with httpx.AsyncClient(timeout=15.0) as client:
        for i, k in enumerate(keys, 1):
            preview = f"{k[:8]}…{k[-4:]}" if len(k) > 12 else k
            length_note = f" · длина {len(k)}"
            if len(k) > TYPICAL_LEN + 5:
                length_note += " ⚠️ <i>(возможно склеено несколько ключей — проверь разделители в Variables)</i>"

            try:
                resp = await client.get(f"https://generativelanguage.googleapis.com/v1beta/models?key={k}")
                if resp.status_code == 200:
                    n = len(resp.json().get("models", []))
                    lines.append(f"✅ #{i} <code>{preview}</code>{length_note} — рабочий, моделей: {n}")
                elif resp.status_code == 400 and ("API_KEY_INVALID" in resp.text or "API key not valid" in resp.text):
                    lines.append(f"❌ #{i} <code>{preview}</code>{length_note} — невалидный ключ")
                    rotator.mark_key_broken(k, "test_keys: API_KEY_INVALID")
                elif resp.status_code == 403:
                    lines.append(f"❌ #{i} <code>{preview}</code>{length_note} — нет прав (Generative Language API не включён в проекте?)")
                    rotator.mark_key_broken(k, "test_keys: 403")
                elif resp.status_code == 429:
                    lines.append(f"⏸ #{i} <code>{preview}</code>{length_note} — 429 (квота исчерпана прямо сейчас)")
                    rotator.mark_quota_exhausted(k)
                else:
                    lines.append(f"⚠️ #{i} <code>{preview}</code>{length_note} — HTTP {resp.status_code}: {escape_html(resp.text[:150])}")
            except Exception as e:
                lines.append(f"⚠️ #{i} <code>{preview}</code>{length_note} — сеть упала: {type(e).__name__}")

    # Статус cooldown'ов
    lines.append("")
    lines.append("<b>Cooldown'ы:</b>")
    for s in rotator.status():
        if s["cooldown_remaining"] > 0:
            mins = s["cooldown_remaining"] // 60
            lines.append(f"• #{s['idx']} <code>{s['preview']}</code> — ждать ещё {mins} мин")
        else:
            lines.append(f"• #{s['idx']} <code>{s['preview']}</code> — готов")

    await safe_send(update, "\n".join(lines))
