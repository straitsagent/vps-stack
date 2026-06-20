CREATE TABLE IF NOT EXISTS portfolio_positions (
    id                   SERIAL PRIMARY KEY,
    ticker               TEXT    NOT NULL UNIQUE,
    company_name         TEXT    NOT NULL,
    shares               NUMERIC NOT NULL,
    currency             TEXT    NOT NULL,
    consolidation_group  TEXT,                  -- group name for ADR+local pairs (e.g. 'Alibaba')
    last_updated         TIMESTAMP DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS fx_rates (
    id            SERIAL PRIMARY KEY,
    rate_date     DATE NOT NULL,
    from_currency TEXT NOT NULL,
    to_currency   TEXT NOT NULL,
    rate          NUMERIC NOT NULL,
    created_at    TIMESTAMP DEFAULT NOW(),
    UNIQUE (rate_date, from_currency, to_currency)
);

CREATE TABLE IF NOT EXISTS price_history (
    id           SERIAL PRIMARY KEY,
    ticker       TEXT    NOT NULL,
    price_date   DATE    NOT NULL,
    close_price  NUMERIC NOT NULL,
    currency     TEXT    NOT NULL,
    created_at   TIMESTAMP DEFAULT NOW(),
    UNIQUE (ticker, price_date)
);

CREATE TABLE IF NOT EXISTS fundamental_data (
    id                   SERIAL PRIMARY KEY,
    ticker               TEXT    NOT NULL,
    exchange             TEXT    NOT NULL,        -- 'US' or 'HK'
    as_of_date           DATE    NOT NULL,
    pe_ratio             NUMERIC,
    pb_ratio             NUMERIC,
    ev_ebitda            NUMERIC,
    revenue_growth_yoy   NUMERIC,                 -- decimal e.g. 0.702 = 70.2%
    net_margin           NUMERIC,                 -- decimal e.g. 0.630 = 63.0%
    debt_equity          NUMERIC,
    analyst_target_usd   NUMERIC,                 -- always USD (HKD converted via fx_rates)
    market_cap_usd       NUMERIC,                 -- always USD
    sector               TEXT,
    country              TEXT,
    roe                  NUMERIC,                 -- US tickers only, from FMP
    roic                 NUMERIC,                 -- US tickers only, from FMP
    sources_json         JSONB,                   -- records which API returned each field
    updated_at           TIMESTAMP DEFAULT NOW(),
    UNIQUE (ticker, as_of_date)
);

-- ── WhatsApp Agent Tables ─────────────────────────────────────────────────────

CREATE TABLE IF NOT EXISTS agent_contact_rules (
    id           BIGSERIAL PRIMARY KEY,
    wa_phone     VARCHAR(20) NOT NULL UNIQUE,
    display_name TEXT NOT NULL,
    relationship TEXT,
    auto_reply   BOOLEAN DEFAULT FALSE,
    rule_prompt  TEXT,
    notes        TEXT,
    created_at   TIMESTAMPTZ DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS agent_draft_queue (
    id           BIGSERIAL PRIMARY KEY,
    wa_phone     VARCHAR(20) NOT NULL,
    inbound_text TEXT NOT NULL,
    draft_reply  TEXT NOT NULL,
    status       VARCHAR(20) DEFAULT 'pending',
    notified_at  TIMESTAMPTZ,
    resolved_at  TIMESTAMPTZ,
    created_at   TIMESTAMPTZ DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS agent_conversation_history (
    id          BIGSERIAL PRIMARY KEY,
    wa_phone    VARCHAR(20) NOT NULL,
    role        VARCHAR(10) NOT NULL,
    content     TEXT NOT NULL,
    tool_called VARCHAR(50),
    tool_args   JSONB,
    created_at  TIMESTAMPTZ DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_conv_phone_time
    ON agent_conversation_history (wa_phone, created_at DESC);

CREATE TABLE IF NOT EXISTS agent_pending_jobs (
    id             BIGSERIAL PRIMARY KEY,
    job_id         VARCHAR(100) UNIQUE NOT NULL,
    wa_phone       VARCHAR(20) NOT NULL,
    tool_name      VARCHAR(50) NOT NULL,
    tool_args      JSONB,
    status         VARCHAR(20) DEFAULT 'running',
    dispatched_at  TIMESTAMPTZ DEFAULT NOW(),
    completed_at   TIMESTAMPTZ,
    result_preview TEXT,
    error_message  TEXT
);
CREATE INDEX IF NOT EXISTS idx_pending_jobs_running
    ON agent_pending_jobs (status) WHERE status = 'running';

CREATE TABLE IF NOT EXISTS agent_pending_confirmations (
    id         BIGSERIAL PRIMARY KEY,
    wa_phone   VARCHAR(20) NOT NULL,
    tool_name  VARCHAR(50) NOT NULL,
    tool_args  JSONB NOT NULL,
    status     VARCHAR(20) DEFAULT 'pending',
    created_at TIMESTAMPTZ DEFAULT NOW(),
    expires_at TIMESTAMPTZ DEFAULT (NOW() + INTERVAL '5 minutes')
);
CREATE INDEX IF NOT EXISTS idx_pending_conf_phone
    ON agent_pending_confirmations (wa_phone, status) WHERE status = 'pending';

CREATE TABLE IF NOT EXISTS agent_audit_log (
    id                 BIGSERIAL PRIMARY KEY,
    wa_phone           VARCHAR(20) NOT NULL,
    inbound_text       TEXT NOT NULL,
    intent_detected    VARCHAR(50),
    tool_called        VARCHAR(50),
    tool_args          JSONB,
    tool_latency_ms    INT,
    router_tokens      INT,
    synth_tokens       INT,
    estimated_cost_usd NUMERIC(10,6),
    windmill_job_id    VARCHAR(100),
    response_text      TEXT,
    status             VARCHAR(20),
    error_detail       TEXT,
    created_at         TIMESTAMPTZ DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS agent_kv (
    key   TEXT PRIMARY KEY,
    value TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS portfolio_thesis (
    id               SERIAL PRIMARY KEY,
    ticker           TEXT NOT NULL,
    thesis_date      DATE NOT NULL DEFAULT CURRENT_DATE,
    investment_thesis TEXT NOT NULL,
    key_catalysts    JSONB DEFAULT '[]',
    risks            JSONB DEFAULT '[]',
    conviction       TEXT CHECK (conviction IN ('High','Medium','Low')),
    target_price_usd NUMERIC(12,2),
    updated_at       TIMESTAMPTZ DEFAULT NOW(),
    UNIQUE (ticker)
);

CREATE TABLE IF NOT EXISTS research_reports (
    id              SERIAL PRIMARY KEY,
    question        TEXT,
    research_type   TEXT NOT NULL,
    depth           TEXT NOT NULL,
    ticker          TEXT,
    file_path       TEXT,
    word_count      INT,
    sources         TEXT[],
    search_queries  TEXT[],
    total_tokens    INT,
    est_cost_usd    NUMERIC(10,4),
    content         TEXT,
    created_at      TIMESTAMPTZ DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_research_ticker_type
    ON research_reports (ticker, research_type, created_at DESC);

CREATE TABLE IF NOT EXISTS earnings_analyses (
    id               SERIAL PRIMARY KEY,
    ticker           TEXT NOT NULL,
    analysis_type    TEXT NOT NULL CHECK (analysis_type IN ('pre', 'post')),
    earnings_date    DATE,
    eps_estimate     NUMERIC(10,4),
    eps_actual       NUMERIC(10,4),
    revenue_estimate NUMERIC(20,2),
    revenue_actual   NUMERIC(20,2),
    surprise_pct     NUMERIC(8,4),
    recommendation   TEXT CHECK (recommendation IN ('Buy','Accumulate','Hold','Reduce','Sell')),
    content          TEXT,
    file_path        TEXT,
    created_at       TIMESTAMPTZ DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_earnings_ticker_date
    ON earnings_analyses (ticker, earnings_date DESC);

-- ── Portfolio Rationalization Scores ─────────────────────────────────────────
-- Written by portfolio_rationalization.py on each monthly run.
-- One row per (score_date, ticker); UNIQUE constraint prevents duplicates.

CREATE TABLE IF NOT EXISTS portfolio_scores (
    id                       SERIAL PRIMARY KEY,
    score_date               DATE NOT NULL DEFAULT CURRENT_DATE,
    ticker                   TEXT,
    consolidated_name        TEXT,
    quality_score            NUMERIC(5,1),
    growth_score             NUMERIC(5,1),
    valuation_score          NUMERIC(5,1),
    sentiment_score          NUMERIC(5,1),
    thesis_score             NUMERIC(5,1),
    composite_score_balanced NUMERIC(5,1),
    composite_score_quality  NUMERIC(5,1),
    composite_score_growth   NUMERIC(5,1),
    composite_score_value    NUMERIC(5,1),
    data_completeness_pct    NUMERIC(5,1),
    red_flag_count           INTEGER DEFAULT 0,
    position_usd             NUMERIC(14,2),
    portfolio_pct            NUMERIC(6,3),
    recommendation           TEXT,
    rank_balanced            INTEGER,
    rank_quality             INTEGER,
    rank_growth              INTEGER,
    rank_value               INTEGER,
    delta_rank_balanced      INTEGER,
    delta_rank_quality       INTEGER,
    delta_rank_growth        INTEGER,
    delta_rank_value         INTEGER,
    UNIQUE (score_date, ticker)
);

-- ── Stock Research Structured Data Store ─────────────────────────────────────
-- Populated by research_tool.py on each deep stock research run.
-- Ticker-agnostic: covers portfolio and non-portfolio tickers alike.
-- Designed for future screener / quant analysis tools.

-- Static / slowly-changing -------------------------------------------------

CREATE TABLE IF NOT EXISTS company_profiles (
    ticker      TEXT PRIMARY KEY,
    sector      TEXT,
    industry    TEXT,
    country     TEXT,
    exchange    TEXT,
    employees   INT,
    website     TEXT,
    description TEXT,
    updated_at  TIMESTAMPTZ DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS key_management (
    id            SERIAL PRIMARY KEY,
    ticker        TEXT NOT NULL,
    name          TEXT NOT NULL,
    title         TEXT,
    age           INT,
    total_pay_usd BIGINT,
    updated_at    TIMESTAMPTZ DEFAULT NOW(),
    UNIQUE (ticker, name)
);

-- board_members table removed: broken DEF 14A parser produces garbage rows with no working writer.
-- Will be re-added when the parser is built and tested. See shared/override_log.md.

-- Annual financial statements (one row per fiscal year end, UPSERT) ---------

CREATE TABLE IF NOT EXISTS income_statements (
    id               SERIAL PRIMARY KEY,
    ticker           TEXT NOT NULL,
    fiscal_year_end  DATE NOT NULL,
    total_revenue    BIGINT,
    gross_profit     BIGINT,
    operating_income BIGINT,
    ebitda           BIGINT,
    net_income       BIGINT,
    basic_eps        NUMERIC(12,4),
    fetched_date     DATE NOT NULL DEFAULT CURRENT_DATE,
    UNIQUE (ticker, fiscal_year_end)
);

CREATE TABLE IF NOT EXISTS balance_sheets (
    id                  SERIAL PRIMARY KEY,
    ticker              TEXT NOT NULL,
    fiscal_year_end     DATE NOT NULL,
    total_assets        BIGINT,
    total_liabilities   BIGINT,
    stockholders_equity BIGINT,
    total_debt          BIGINT,
    cash                BIGINT,
    current_assets      BIGINT,
    current_liabilities BIGINT,
    fetched_date        DATE NOT NULL DEFAULT CURRENT_DATE,
    UNIQUE (ticker, fiscal_year_end)
);

CREATE TABLE IF NOT EXISTS cashflow_statements (
    id              SERIAL PRIMARY KEY,
    ticker          TEXT NOT NULL,
    fiscal_year_end DATE NOT NULL,
    operating_cf    BIGINT,
    free_cf         BIGINT,
    capex           BIGINT,
    fetched_date    DATE NOT NULL DEFAULT CURRENT_DATE,
    UNIQUE (ticker, fiscal_year_end)
);

CREATE TABLE IF NOT EXISTS financial_health_metrics (
    id                SERIAL PRIMARY KEY,
    ticker            TEXT NOT NULL,
    fiscal_year_end   DATE NOT NULL,
    net_debt          BIGINT,
    net_debt_ebitda   NUMERIC(10,4),
    gearing           NUMERIC(10,4),
    current_ratio     NUMERIC(10,4),
    net_margin        NUMERIC(10,4),
    asset_turnover    NUMERIC(10,4),
    equity_multiplier NUMERIC(10,4),
    roe_dupont        NUMERIC(10,4),
    fetched_date      DATE NOT NULL DEFAULT CURRENT_DATE,
    UNIQUE (ticker, fiscal_year_end)
);

-- Point-in-time snapshots (one row per ticker per day) ----------------------

CREATE TABLE IF NOT EXISTS valuation_snapshots (
    id                SERIAL PRIMARY KEY,
    ticker            TEXT NOT NULL,
    fetched_date      DATE NOT NULL DEFAULT CURRENT_DATE,
    trailing_pe       NUMERIC(12,4),
    forward_pe        NUMERIC(12,4),
    pb                NUMERIC(12,4),
    ps_ttm            NUMERIC(12,4),
    ev_ebitda         NUMERIC(12,4),
    ev_revenue        NUMERIC(12,4),
    p_fcf             NUMERIC(12,4),
    peg               NUMERIC(12,4),
    beta              NUMERIC(12,4),
    trailing_eps      NUMERIC(12,4),
    forward_eps       NUMERIC(12,4),
    fifty_two_wk_high NUMERIC(12,4),
    fifty_two_wk_low  NUMERIC(12,4),
    short_pct_float   NUMERIC(10,4),
    short_ratio       NUMERIC(10,4),
    analyst_target    NUMERIC(12,4),
    analyst_rec_mean  NUMERIC(6,4),
    analyst_count     INT,
    UNIQUE (ticker, fetched_date)
);

CREATE TABLE IF NOT EXISTS ownership_snapshots (
    id                SERIAL PRIMARY KEY,
    ticker            TEXT NOT NULL,
    fetched_date      DATE NOT NULL DEFAULT CURRENT_DATE,
    insider_pct       NUMERIC(10,4),
    institutional_pct NUMERIC(10,4),
    UNIQUE (ticker, fetched_date)
);

CREATE TABLE IF NOT EXISTS institutional_holders (
    id            SERIAL PRIMARY KEY,
    ticker        TEXT NOT NULL,
    fetched_date  DATE NOT NULL DEFAULT CURRENT_DATE,
    holder_name   TEXT NOT NULL,
    shares        BIGINT,
    pct_held      NUMERIC(10,4),
    reported_date DATE,
    UNIQUE (ticker, holder_name, fetched_date)
);

CREATE TABLE IF NOT EXISTS peer_comparisons (
    id             SERIAL PRIMARY KEY,
    ticker         TEXT NOT NULL,
    peer_ticker    TEXT NOT NULL,
    fetched_date   DATE NOT NULL DEFAULT CURRENT_DATE,
    peer_name      TEXT,
    market_cap_usd BIGINT,
    revenue_ttm    BIGINT,
    ebitda         BIGINT,
    trailing_pe    NUMERIC(12,4),
    pb             NUMERIC(12,4),
    UNIQUE (ticker, peer_ticker, fetched_date)
);

-- Append-only histories -----------------------------------------------------

CREATE TABLE IF NOT EXISTS insider_transactions (
    id               SERIAL PRIMARY KEY,
    ticker           TEXT NOT NULL,
    insider_name     TEXT,
    title            TEXT,
    transaction_date DATE,
    txn_type         TEXT,
    shares           BIGINT,
    value_usd        BIGINT,
    fetched_date     DATE NOT NULL DEFAULT CURRENT_DATE,
    UNIQUE (ticker, insider_name, transaction_date, txn_type, shares)
);

CREATE TABLE IF NOT EXISTS earnings_surprises (
    id           SERIAL PRIMARY KEY,
    ticker       TEXT NOT NULL,
    period_date  DATE NOT NULL,
    eps_estimate NUMERIC(12,4),
    eps_actual   NUMERIC(12,4),
    surprise_pct NUMERIC(10,4),
    UNIQUE (ticker, period_date)
);

CREATE TABLE IF NOT EXISTS next_earnings (
    ticker        TEXT PRIMARY KEY,
    earnings_date DATE,
    eps_estimate  NUMERIC(12,4),
    revenue_low   BIGINT,
    revenue_high  BIGINT,
    updated_at    TIMESTAMPTZ DEFAULT NOW()
);

-- Indexes for screener queries ----------------------------------------------

CREATE INDEX IF NOT EXISTS idx_inc_ticker
    ON income_statements (ticker, fiscal_year_end DESC);
CREATE INDEX IF NOT EXISTS idx_bal_ticker
    ON balance_sheets (ticker, fiscal_year_end DESC);
CREATE INDEX IF NOT EXISTS idx_cf_ticker
    ON cashflow_statements (ticker, fiscal_year_end DESC);
CREATE INDEX IF NOT EXISTS idx_health_ticker
    ON financial_health_metrics (ticker, fiscal_year_end DESC);
CREATE INDEX IF NOT EXISTS idx_val_ticker_date
    ON valuation_snapshots (ticker, fetched_date DESC);
CREATE INDEX IF NOT EXISTS idx_val_screen
    ON valuation_snapshots (trailing_pe, pb, fetched_date DESC);
CREATE INDEX IF NOT EXISTS idx_health_screen
    ON financial_health_metrics (net_debt_ebitda, current_ratio, fiscal_year_end DESC);

-- ── C5: Data-integrity improvements (added 2026-06-16) ───────────────────────

-- Indexes for agent_audit_log — avoids sequential scans on every agent call
CREATE INDEX IF NOT EXISTS idx_audit_created
    ON agent_audit_log (created_at DESC);
CREATE INDEX IF NOT EXISTS idx_audit_phone_created
    ON agent_audit_log (wa_phone, created_at DESC);

-- UNIQUE on earnings_analyses to prevent duplicate analysis rows from the
-- post-check race condition (dispatches could fire twice on the same ticker+date)
ALTER TABLE earnings_analyses
    ADD CONSTRAINT IF NOT EXISTS uq_earnings_analyses_ticker_type_date
    UNIQUE (ticker, analysis_type, earnings_date);

-- CHECK constraints on bounded-set text columns
ALTER TABLE agent_contact_rules
    ADD CONSTRAINT IF NOT EXISTS chk_contact_relationship
    CHECK (relationship IN ('owner','family','colleague','friend','other') OR relationship IS NULL);

ALTER TABLE agent_draft_queue
    ADD CONSTRAINT IF NOT EXISTS chk_draft_status
    CHECK (status IN ('pending','approved','rejected','sent'));

ALTER TABLE agent_pending_jobs
    ADD CONSTRAINT IF NOT EXISTS chk_job_status
    CHECK (status IN ('running','completed','failed','cancelled'));

ALTER TABLE agent_pending_confirmations
    ADD CONSTRAINT IF NOT EXISTS chk_conf_status
    CHECK (status IN ('pending','confirmed','cancelled','rejected','expired'));

-- Full set of status values used by agent/main.py write_audit calls
ALTER TABLE agent_audit_log
    ADD CONSTRAINT IF NOT EXISTS chk_audit_status
    CHECK (status IN (
        'success','failed','unregistered','dispatched','cached',
        'rejected','pending_confirmation','unknown','confirmed','error','timeout','pending'
    ) OR status IS NULL);

ALTER TABLE agent_conversation_history
    ADD CONSTRAINT IF NOT EXISTS chk_conv_role
    CHECK (role IN ('user','assistant','system'));

-- updated_at on mutable tables that lack it
ALTER TABLE portfolio_positions
    ADD COLUMN IF NOT EXISTS updated_at TIMESTAMPTZ DEFAULT NOW();

ALTER TABLE price_history
    ADD COLUMN IF NOT EXISTS updated_at TIMESTAMPTZ DEFAULT NOW();

ALTER TABLE fx_rates
    ADD COLUMN IF NOT EXISTS updated_at TIMESTAMPTZ DEFAULT NOW();

ALTER TABLE agent_audit_log
    ADD COLUMN IF NOT EXISTS updated_at TIMESTAMPTZ DEFAULT NOW();

ALTER TABLE earnings_analyses
    ADD COLUMN IF NOT EXISTS updated_at TIMESTAMPTZ DEFAULT NOW();

-- ── Portfolio Candidate Evaluations ──────────────────────────────────────────
-- Written by portfolio_candidate_eval.py on each on-demand candidate eval run.

CREATE TABLE IF NOT EXISTS portfolio_candidate_evals (
    id                      SERIAL PRIMARY KEY,
    eval_date               DATE NOT NULL DEFAULT CURRENT_DATE,
    eval_expires_date       DATE,                   -- eval_date + 30 (B11)
    ticker                  TEXT NOT NULL,
    company_name            TEXT,
    replacement_ticker      TEXT,                   -- optional exit paired with this add (B7)
    red_flag_count          INT,
    red_flags               JSONB,
    gate1_status            TEXT,                   -- 'ok' | 'breach'
    max_correlation         NUMERIC(5,3),
    closest_existing        TEXT,
    gate2_warn              TEXT,                   -- 'insufficient_history' or NULL (B1)
    max_fundamental_sim     NUMERIC(5,3),           -- cosine similarity (B2)
    closest_fundamental     TEXT,
    sector_match_count      INT,
    country_match_count     INT,
    currency_post_pct       NUMERIC(5,2),           -- post-addition currency exposure % (B8)
    currency_breach         BOOLEAN DEFAULT FALSE,
    factor_gap_fills        JSONB,
    universe_tickers        JSONB,
    universe_size           INT,
    thin_universe           BOOLEAN,
    below_min_universe      BOOLEAN DEFAULT FALSE,  -- <3 peers, ranking suppressed (B4)
    universe_heterogeneity  BOOLEAN DEFAULT FALSE,  -- user-supplied universe is heterogeneous (B9)
    quality_triplet         JSONB,                  -- {absolute, portfolio_pct, universe_pct}
    growth_triplet          JSONB,
    valuation_triplet       JSONB,
    sentiment_triplet       JSONB,
    portfolio_composite     NUMERIC(5,1),
    universe_composite      NUMERIC(5,1),
    verdict                 TEXT,                   -- 'ADD' | 'WATCH' | 'PASS'
    binding_constraint      TEXT,
    grok_json_output        JSONB,                  -- show-your-work JSON from Grok (C2)
    thesis_source           TEXT,                   -- 'user-supplied' | 'llm-derived' (B5)
    portfolio_baseline_age  INT,                    -- days since last rationalization run (B10)
    synthesiser_model       TEXT,
    input_tokens            INT,
    output_tokens           INT,
    UNIQUE (eval_date, ticker)
);

-- Telegram outbox — persistent record of every Telegram send
CREATE TABLE IF NOT EXISTS telegram_outbox (
    id          SERIAL PRIMARY KEY,
    sent_at     TIMESTAMPTZ NOT NULL DEFAULT now(),
    script_name TEXT NOT NULL,
    message_text TEXT NOT NULL,
    char_count  INTEGER,
    word_count  INTEGER,
    delivered   BOOLEAN,
    error       TEXT
);
CREATE INDEX IF NOT EXISTS idx_telegram_outbox_sent_at ON telegram_outbox (sent_at DESC);
