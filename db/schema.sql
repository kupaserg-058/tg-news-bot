-- Схема БД для бота-аналитика. Все CREATE — idempotent (IF NOT EXISTS).
-- Векторные колонки и pgvector-расширение применяются отдельно в migrations.py.

CREATE TABLE IF NOT EXISTS channels (
    id                   SERIAL PRIMARY KEY,
    username             TEXT NOT NULL UNIQUE,
    type                 TEXT NOT NULL CHECK (type IN ('news', 'expert')),
    title                TEXT,
    added_at             TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    last_parsed_msg_id   BIGINT NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS posts (
    id              BIGSERIAL PRIMARY KEY,
    channel_id      INTEGER NOT NULL REFERENCES channels(id) ON DELETE CASCADE,
    tg_message_id   BIGINT NOT NULL,
    text            TEXT NOT NULL,
    posted_at       TIMESTAMPTZ NOT NULL,
    link            TEXT NOT NULL,
    fts             tsvector,
    UNIQUE (channel_id, tg_message_id)
);

CREATE INDEX IF NOT EXISTS idx_posts_posted_at      ON posts (posted_at DESC);
CREATE INDEX IF NOT EXISTS idx_posts_channel_posted ON posts (channel_id, posted_at DESC);
CREATE INDEX IF NOT EXISTS idx_posts_fts            ON posts USING GIN (fts);

-- Триггер для автоматического обновления tsvector. russian-конфиг работает для ru+en.
CREATE OR REPLACE FUNCTION posts_fts_trigger() RETURNS trigger AS $$
BEGIN
    NEW.fts := to_tsvector('russian', COALESCE(NEW.text, ''));
    RETURN NEW;
END
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS posts_fts_update ON posts;
CREATE TRIGGER posts_fts_update
    BEFORE INSERT OR UPDATE OF text ON posts
    FOR EACH ROW EXECUTE FUNCTION posts_fts_trigger();

CREATE TABLE IF NOT EXISTS gemini_cache (
    id            BIGSERIAL PRIMARY KEY,
    prompt_hash   TEXT NOT NULL UNIQUE,
    query_type    TEXT NOT NULL,
    prompt        TEXT NOT NULL,
    response      TEXT NOT NULL,
    model         TEXT NOT NULL,
    created_at    TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    expires_at    TIMESTAMPTZ NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_cache_expires ON gemini_cache (expires_at);

CREATE TABLE IF NOT EXISTS query_log (
    id          BIGSERIAL PRIMARY KEY,
    user_id     BIGINT,
    command     TEXT NOT NULL,
    query       TEXT,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
