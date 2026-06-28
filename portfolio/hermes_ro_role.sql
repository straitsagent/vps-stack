-- Idempotent openclaw read-only role migration.
-- Apply: sed "s/__HERMES_RO_PW__/$(cat /root/.hermes_ro_pw)/" /root/portfolio/hermes_ro_role.sql \
--           | docker exec -i root-portfolio_postgres-1 psql -U portfolio_user -d portfolio
DO $$ BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'hermes_ro') THEN
    CREATE ROLE hermes_ro LOGIN PASSWORD '__HERMES_RO_PW__';
  END IF;
END $$;
GRANT CONNECT ON DATABASE portfolio TO hermes_ro;
GRANT USAGE ON SCHEMA public TO hermes_ro;
ALTER ROLE hermes_ro SET statement_timeout = '15s';
GRANT SELECT ON
  company_profiles, income_statements, balance_sheets, cashflow_statements,
  financial_health_metrics, valuation_snapshots, fundamental_data,
  ownership_snapshots, institutional_holders, insider_transactions, peer_comparisons,
  next_earnings, earnings_surprises, earnings_analyses,
  price_history, fx_rates, portfolio_positions, portfolio_scores, portfolio_candidate_evals,
  portfolio_thesis, watchlist_ideas, position_events, position_signals,
  research_reports
TO hermes_ro;
