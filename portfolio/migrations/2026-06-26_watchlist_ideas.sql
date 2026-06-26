-- Migration: watchlist_ideas table (Plan A — Idea Pipeline)
-- Applied: 2026-06-26
CREATE TABLE IF NOT EXISTS watchlist_ideas (
    id            SERIAL PRIMARY KEY,
    ticker        TEXT NOT NULL,
    source        TEXT NOT NULL,
    source_ref    TEXT,
    reason        TEXT,
    added_at      TIMESTAMPTZ DEFAULT NOW(),
    status        TEXT NOT NULL DEFAULT 'pending',
    eval_date     DATE,
    prescreen_rank   INTEGER,
    prescreen_score  NUMERIC(6,4),
    UNIQUE (ticker, source)
);
