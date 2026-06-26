-- Position Sentinel — Phase 1 schema
-- position_events: per-ticker, per-headline materiality-scored events
-- position_signals: triggered alerts (price_cumulative, news_materiality, confluence)

CREATE TABLE IF NOT EXISTS position_events (
    id            SERIAL PRIMARY KEY,
    ticker        TEXT NOT NULL,
    published_at  TIMESTAMPTZ,
    fetched_at    TIMESTAMPTZ DEFAULT NOW(),
    source        TEXT,
    headline      TEXT NOT NULL,
    url           TEXT,
    url_hash      TEXT NOT NULL,
    materiality   SMALLINT,
    category      TEXT,
    direction     TEXT,
    impact        TEXT,
    UNIQUE (ticker, url_hash)
);

CREATE TABLE IF NOT EXISTS position_signals (
    id            SERIAL PRIMARY KEY,
    ticker        TEXT NOT NULL,
    signal_date   DATE NOT NULL DEFAULT CURRENT_DATE,
    signal_type   TEXT NOT NULL,
    severity      TEXT NOT NULL,
    detail        JSONB DEFAULT '{}',
    alerted       BOOLEAN DEFAULT FALSE,
    created_at    TIMESTAMPTZ DEFAULT NOW()
);
