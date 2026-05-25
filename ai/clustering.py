"""Простая кластеризация постов по близости embeddings.

Используется для приоритизации в дайджесте: большой кластер = горячая тема.
"""

from typing import Iterable

import numpy as np


def _cosine_matrix(vectors: list[np.ndarray]) -> np.ndarray:
    M = np.stack(vectors).astype(np.float32)
    norms = np.linalg.norm(M, axis=1, keepdims=True)
    norms[norms == 0] = 1.0
    Mn = M / norms
    return Mn @ Mn.T  # NxN similarity matrix


def greedy_cluster(posts: list[dict], threshold: float = 0.72) -> dict[int, int]:
    """Возвращает {post_index: cluster_id}. Жадный алгоритм: первый непомеченный пост — новый кластер,
    к нему добавляются все непомеченные посты с similarity >= threshold."""
    vectors: list = []
    for p in posts:
        v = p.get("embedding")
        if v is None:
            vectors.append(None)
        elif isinstance(v, np.ndarray) and v.size > 0:
            vectors.append(v)
        else:
            # str/list/прочее — пропускаем как невалидное
            vectors.append(None)
    valid_mask = [v is not None for v in vectors]
    if not any(valid_mask):
        return {i: i for i in range(len(posts))}

    first_valid = vectors[valid_mask.index(True)]
    sims = _cosine_matrix([v if v is not None else np.zeros_like(first_valid) for v in vectors])
    n = len(posts)
    assignment: dict[int, int] = {}
    cluster_id = 0
    for i in range(n):
        if i in assignment or not valid_mask[i]:
            assignment.setdefault(i, -1)
            continue
        assignment[i] = cluster_id
        for j in range(i + 1, n):
            if j in assignment or not valid_mask[j]:
                continue
            if sims[i, j] >= threshold:
                assignment[j] = cluster_id
        cluster_id += 1
    return assignment


def cluster_sizes(assignment: dict[int, int]) -> dict[int, int]:
    sizes: dict[int, int] = {}
    for cid in assignment.values():
        if cid < 0:
            continue
        sizes[cid] = sizes.get(cid, 0) + 1
    return sizes


def score_posts(posts: list[dict], assignment: dict[int, int], expert_link_counts: dict[int, int]) -> list[float]:
    """Score каждого поста = размер_кластера*1.0 + кол-во_экспертных_связей*2.0 + log(длина_текста).
    Чем выше — тем приоритетнее в дайджесте."""
    sizes = cluster_sizes(assignment)
    scores: list[float] = []
    for idx, p in enumerate(posts):
        cid = assignment.get(idx, -1)
        size = sizes.get(cid, 1) if cid >= 0 else 1
        links = expert_link_counts.get(p["id"], 0)
        text_factor = min(len(p.get("text", "")) / 500, 3.0)  # ограничиваем влияние длины
        scores.append(size * 1.0 + links * 2.0 + text_factor)
    return scores
