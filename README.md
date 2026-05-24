# News Analyst Bot

Личный Telegram-бот: парсит каналы (Telethon), хранит историю в PostgreSQL, отдаёт AI-аналитику через Gemini (с Google Search grounding).

## Команды

| Команда | Что делает |
|---|---|
| `/add_channel @name news\|expert` | Добавить канал и сделать backfill 30 дней |
| `/remove_channel @name` | Удалить канал и все его посты |
| `/list_channels` | Список подключённых каналов |
| `/digest [часы]` | AI-дайджест по темам за N часов (по умолчанию 24, можно `/digest 6`) |
| `/search ключевые слова` | Сырой полнотекстовый поиск по базе |
| `/why тема` | Глубокий анализ: что, почему, параллели, прогноз |
| `/context тема` | Только исторические параллели через Google Search |
| `/map тема` | Граф связей в формате Mermaid (вставить в mermaid.live) |
| `/stats` | Каналы / посты / кеш в цифрах |
| `/clear_cache [тип]` | Сбросить кеш Gemini (всё или по типу: digest/why/map/...) |
| Свободный текст | Полный аналитический ответ с фактами из БД и веба |

Автодайджест приходит в `DIGEST_TIME_MORNING` и `DIGEST_TIME_EVENING` (по умолчанию 09:00 и 21:00 МСК). Если выставить `DIGEST_INTERVAL_HOURS=2` — добавляется ещё дайджест каждые 2 часа.

---

## Локальный запуск (для разработки)

```bash
git clone <repo>
cd <repo>

python3.11 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt

cp .env.example .env
# заполни .env (см. ниже какие ключи где взять)

python generate_session.py   # один раз: создать Telethon-сессию
# скопировать строку TELETHON_SESSION в .env

python main.py
```

---

## Где взять ключи

### `TELEGRAM_BOT_TOKEN`
[@BotFather](https://t.me/BotFather) → `/newbot` → задать имя и username → получить токен.

### `TELEGRAM_API_ID`, `TELEGRAM_API_HASH`
https://my.telegram.org → войти по номеру → API development tools → создать приложение (Platform: Desktop, любые имя/описание) → скопировать `api_id` и `api_hash`.

### `TELETHON_SESSION`
Один раз локально:
```bash
python generate_session.py
```
Введи номер телефона, код из Telegram, 2FA если есть. Скопируй длинную строку из вывода.

⚠️ Эта строка = доступ к твоему Telegram-аккаунту. Не публикуй, не коммить.

### `GEMINI_API_KEY`
https://aistudio.google.com → Get API key → Create API key. Бесплатный tier.

### `POSTGRES_URL`
- **Локально**: `DATABASE_PUBLIC_URL` из Railway → Postgres → Variables (хост вида `kodama.proxy.rlwy.net`).
- **На Railway** в сервисе бота: `${{Postgres.DATABASE_URL}}` — внутренний быстрый URL.

### `OWNER_CHAT_ID`
Поставь временно `1`, запусти бота, напиши боту `/start` — в логах терминала появится `chat_id=...`. Скопируй число, замени и перезапусти.

---

## Деплой на Railway

### 1. Подготовка репозитория
```bash
git init
git add .
git commit -m "init"
# опционально: запушить на GitHub
git remote add origin git@github.com:USER/REPO.git
git push -u origin main
```

В репо НЕ должно быть `.env` (он в `.gitignore`).

### 2. Railway-проект
Уже создан на Шаге 1 с сервисом PostgreSQL. Добавляем второй сервис:

1. В Railway-проекте: **+ Create** → **GitHub Repo** → выбрать репо бота.
2. Railway сам определит Python через `requirements.txt`, прочитает `runtime.txt` (Python 3.11) и `Procfile` (запустит `worker: python main.py`).
3. **Variables** в сервисе бота:

| Переменная | Значение |
|---|---|
| `TELEGRAM_BOT_TOKEN` | твой токен |
| `TELEGRAM_API_ID` | число |
| `TELEGRAM_API_HASH` | строка |
| `TELETHON_SESSION` | строка из `generate_session.py` |
| `GEMINI_API_KEY` | твой ключ |
| `POSTGRES_URL` | `${{Postgres.DATABASE_URL}}` ← именно так, со ссылкой на сервис Postgres |
| `OWNER_CHAT_ID` | твой chat_id |
| `DIGEST_TIME_MORNING` | `09:00` |
| `DIGEST_TIME_EVENING` | `21:00` |
| `DIGEST_INTERVAL_HOURS` | `0` (или другое, если хочешь чаще) |

4. **Deploy**. В логах должно появиться:
   ```
   === Bot starting ===
   asyncpg pool создан
   Схема БД применена
   Telethon подключён: @твой_ник
   Scheduler запущен
   Бот запущен, polling активен
   ```

### 3. Проверка
- Напиши боту `/list_channels` — должно ответить (каналы переедут вместе с БД, если она та же).
- `/stats` — увидишь сколько постов уже в БД.
- В Railway logs смотри что парсер каждые 15 минут что-то добавляет.

### 4. Дальнейшие изменения
Любой `git push` в `main` → Railway автоматически передеплоит сервис.

---

## Архитектура

```
main.py                       — точка входа, asyncio event loop
├── parser/                   — Telethon: пользовательский клиент + парсинг
│   ├── telethon_client.py
│   ├── channel_parser.py     — backfill 30 дней + инкремент
│   └── scheduler_jobs.py     — APScheduler job каждые 15 мин
├── db/                       — asyncpg + схема
│   ├── schema.sql            — channels / posts / gemini_cache / query_log
│   ├── connection.py         — пул
│   ├── migrations.py         — apply_schema()
│   └── repository.py         — CRUD + полнотекстовый поиск
├── ai/                       — Gemini
│   ├── gemini_client.py      — обёртка с fallback-моделью
│   ├── cache.py              — sha256 → PostgreSQL
│   ├── prompts.py            — все промпты на русском
│   └── digest_service.py     — общая логика дайджеста
├── handlers/                 — команды бота
│   ├── common.py             — owner_only, safe_send, error handler
│   ├── start.py              — /start, /help
│   ├── channels.py           — /add_channel, /remove_channel, /list_channels
│   ├── digest.py             — /digest
│   ├── search.py             — /search (без AI)
│   ├── why.py                — /why
│   ├── context_cmd.py        — /context
│   ├── map_graph.py          — /map (Mermaid)
│   ├── free_text.py          — свободный текст
│   └── admin.py              — /stats, /clear_cache
├── formatters/               — экранирование HTML, разбиение длинных сообщений
├── jobs/                     — APScheduler-задачи
│   └── auto_digest.py        — утренний/вечерний/интервальный дайджест
└── utils/                    — logger, env
```

Все вызовы Gemini кешируются в `gemini_cache` (TTL по типу запроса). Повторный `/digest 24` или `/why X` в течение TTL — мгновенный ответ, 0 квоты.

Telethon-сессия — только `StringSession` из переменной окружения. Никаких файлов на FS — это важно для Railway (нет персистентного диска).
