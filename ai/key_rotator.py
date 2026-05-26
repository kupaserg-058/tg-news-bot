"""Ротация Gemini API-ключей с автопереключением при 429.

Логика:
- Хранится список ключей в порядке как пришли из env.
- Каждый ключ имеет cooldown_until: timestamp, после которого можно пробовать снова.
- current_key() возвращает первый ключ с cooldown_until <= now. Если все на cooldown — возвращает тот, чей cooldown ближайший (всё равно скоро освободится).
- mark_quota_exhausted(key) ставит cooldown на 60 секунд для этого ключа.
- all_exhausted() возвращает True если все ключи сейчас в cooldown.
"""

import time
from typing import Optional

from utils.logger import log


COOLDOWN_SECONDS = 60  # сколько ждать прежде чем снова попробовать ключ после 429


class KeyRotator:
    def __init__(self, keys: list[str]) -> None:
        if not keys:
            raise ValueError("KeyRotator: пустой список ключей")
        self._keys = list(keys)
        self._cooldowns: dict[str, float] = {k: 0.0 for k in self._keys}
        self._current_idx = 0
        log.info(f"KeyRotator: загружено {len(self._keys)} ключей")

    def current_key(self) -> str:
        now = time.time()
        # Сначала пытаемся использовать текущий, если он не в cooldown
        cur = self._keys[self._current_idx]
        if self._cooldowns[cur] <= now:
            return cur

        # Иначе ищем первый свободный начиная со следующего
        n = len(self._keys)
        for offset in range(1, n + 1):
            idx = (self._current_idx + offset) % n
            k = self._keys[idx]
            if self._cooldowns[k] <= now:
                self._current_idx = idx
                log.info(f"KeyRotator: переключился на ключ #{idx + 1}/{n}")
                return k

        # Все в cooldown — возвращаем тот, чей cooldown ближе всего к концу
        soonest = min(self._keys, key=lambda k: self._cooldowns[k])
        return soonest

    def mark_quota_exhausted(self, key: str) -> None:
        """Помечает ключ как исчерпанный (минутная квота). Ставит cooldown."""
        if key not in self._cooldowns:
            return
        self._cooldowns[key] = time.time() + COOLDOWN_SECONDS
        idx = self._keys.index(key)
        log.warning(f"KeyRotator: ключ #{idx + 1} исчерпан, cooldown {COOLDOWN_SECONDS}с")

    def all_exhausted(self) -> bool:
        now = time.time()
        return all(self._cooldowns[k] > now for k in self._keys)

    def count(self) -> int:
        return len(self._keys)


_rotator: Optional[KeyRotator] = None


def init_rotator(keys: list[str]) -> None:
    global _rotator
    _rotator = KeyRotator(keys)


def get_rotator() -> KeyRotator:
    global _rotator
    if _rotator is None:
        # Lazy fallback: подцепить из env если init забыли вызвать
        import os
        from utils.env import _parse_gemini_keys
        keys = _parse_gemini_keys()
        if not keys:
            raise RuntimeError("Gemini-ключи не настроены (GEMINI_API_KEY / GEMINI_API_KEYS)")
        _rotator = KeyRotator(keys)
    return _rotator
