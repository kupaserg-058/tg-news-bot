"""Сборка дайджеста. С embeddings — приоритизирует горячие сюжеты и связывает мнения экспертов
с конкретными новостями. Без embeddings — fallback на простой список."""

from datetime import datetime, timedelta, timezone

from ai import gemini_client
from ai.clustering import greedy_cluster, score_posts, cluster_sizes
from ai.prompts import build_digest_prompt
from config import MAX_POSTS_IN_PROMPT, EXPERT_LINK_THRESHOLD
from db import repository as repo
from db.connection import is_pgvector_available
from utils.logger import log


async def _attach_expert_links(news_posts: list[dict], since: datetime) -> dict[int, list[dict]]:
    """Для каждой news возвращает связанные expert-посты (по embedding),
    не старше окна дайджеста (since), чтобы не подтягивать старые мнения."""
    if not is_pgvector_available():
        return {}
    out: dict[int, list[dict]] = {}
    for p in news_posts:
        try:
            links = await repo.find_expert_links_for_post(p["id"], limit=3, since=since)
            if links:
                out[p["id"]] = links
        except Exception as e:
            log.warning(f"expert link для post {p['id']} упал: {e}")
    return out


def _select_top_posts(posts: list[dict], expert_links: dict[int, list[dict]], target: int) -> list[dict]:
    """Кластеризует и выбирает top-N по приоритету. Старается включить по 1 посту от каждого кластера."""
    assignment = greedy_cluster(posts, threshold=0.72)
    expert_link_counts = {pid: len(v) for pid, v in expert_links.items()}
    scores = score_posts(posts, assignment, expert_link_counts)

    # Сортируем по score убыванию, но при одинаковом cluster — берём только один пост (топ).
    indexed = sorted(range(len(posts)), key=lambda i: scores[i], reverse=True)
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

    chosen = primary[:target] + secondary[:max(0, target - len(primary[:target]))]
    chosen = chosen[:target]
    return [posts[i] for i in chosen]


async def compose_digest(
    hours: int = 24,
    category: str | None = None,
    exclude_categories: list[str] | None = None,
) -> tuple[str | None, int]:
    """Возвращает (html_text, n_posts_total_in_window). None если за окно ничего нет.
    category — фильтр по конкретной категории (приоритетнее exclude_categories).
    exclude_categories — список disabled категорий пользователя (для автодайджеста)."""
    posts = await repo.get_posts_last_hours(
        hours, limit=500, with_embeddings=True,
        category=category, exclude_categories=exclude_categories,
    )
    if not posts:
        return None, 0

    total = len(posts)
    news_posts = [p for p in posts if p["channel_type"] == "news"]
    since = datetime.now(timezone.utc) - timedelta(hours=hours)
    expert_links = await _attach_expert_links(news_posts, since)

    # Приоритизируем news по кластерам, мнения экспертов прикрепляем потом.
    if news_posts:
        top_news = _select_top_posts(news_posts, expert_links, target=MAX_POSTS_IN_PROMPT)
    else:
        top_news = []

    # Експертные посты не связанные ни с одной news — добавим отдельно как «общие мнения».
    linked_expert_ids = {ep["id"] for links in expert_links.values() for ep in links}
    unlinked_experts = [p for p in posts if p["channel_type"] == "expert" and p["id"] not in linked_expert_ids]
    unlinked_experts = unlinked_experts[: max(0, MAX_POSTS_IN_PROMPT - len(top_news))]

    prompt = build_digest_prompt(
        news_posts=top_news,
        expert_links=expert_links,
        unlinked_experts=unlinked_experts,
        hours=hours,
        total_posts=total,
    )
    log.info(
        f"Digest: {total} постов всего, top news={len(top_news)}, "
        f"expert links={sum(len(v) for v in expert_links.values())}, unlinked experts={len(unlinked_experts)}"
    )
    text = await gemini_client.generate(prompt, query_type="digest", use_search=False)
    return text, total
