"""Сборка дайджеста. Новости приоритизируются по кластерам, эксперты идут отдельным блоком."""

from ai import gemini_client
from ai.clustering import greedy_cluster, score_posts
from ai.prompts import build_digest_prompt
from config import MAX_POSTS_IN_PROMPT
from db import repository as repo
from db.connection import is_pgvector_available
from utils.logger import log


def _select_top_news(news_posts: list[dict], target: int) -> list[dict]:
    """Кластеризует и выбирает top-N по приоритету."""
    assignment = greedy_cluster(news_posts, threshold=0.72)
    scores = score_posts(news_posts, assignment, {})

    indexed = sorted(range(len(news_posts)), key=lambda i: scores[i], reverse=True)
    seen_clusters: set[int] = set()
    primary: list[int] = []
    secondary: list[int] = []
    for idx in indexed:
        cid = assignment.get(idx, -1)
        if cid < 0 or cid in seen_clusters:
            secondary.append(idx)
        else:
            primary.append(idx)
            seen_clusters.add(cid)

    chosen = primary[:target] + secondary[:max(0, target - len(primary))]
    return [news_posts[i] for i in chosen[:target]]


async def compose_digest(
    hours: int = 24,
    category: str | None = None,
    exclude_categories: list[str] | None = None,
) -> tuple[str | None, int]:
    """Возвращает (html_text, n_posts_total_in_window). None если за окно ничего нет."""
    posts = await repo.get_posts_last_hours(
        hours, limit=500, with_embeddings=is_pgvector_available(),
        category=category, exclude_categories=exclude_categories,
    )
    if not posts:
        return None, 0

    total = len(posts)
    news_posts = [p for p in posts if p["channel_type"] == "news"]
    expert_posts = [p for p in posts if p["channel_type"] == "expert"]

    top_news = _select_top_news(news_posts, target=MAX_POSTS_IN_PROMPT) if news_posts else []
    top_experts = expert_posts[:max(0, MAX_POSTS_IN_PROMPT - len(top_news))]

    log.info(f"Digest: {total} постов всего, news={len(top_news)}, experts={len(top_experts)}")

    prompt = build_digest_prompt(
        news_posts=top_news,
        expert_posts=top_experts,
        hours=hours,
        total_posts=total,
    )
    text = await gemini_client.generate(prompt, query_type="digest", use_search=False)
    return text, total
