"""
F1 — Fundamentals Fetcher
Fetches fundamental data for all portfolio tickers and upserts into fundamental_data table.

Sources:
  US tickers: Finnhub /stock/metric (valuation ratios + ROE/ROI)
              + yfinance .info (analyst target, sector, country, market cap + fallbacks)
  HK tickers: yfinance .info only (full field coverage confirmed)

Schedule: Weekly, Sunday 6:00 PM SGT (10:00 UTC)
"""

import time
import json
import requests
import psycopg2
import yfinance as yf
from datetime import date
from typing import Optional
import logging
logging.basicConfig(level=logging.INFO, format='%(levelname)s %(message)s')
log = logging.getLogger(__name__)


# ETFs have no PE, analyst target, or sector — suppress null warnings for these
ETF_TICKERS = {"XLV", "SPY", "QQQ", "IWM", "VTI"}


def main(
    portfolio_db: dict,
    finnhub_key: str,
):
    conn = psycopg2.connect(**portfolio_db)
    as_of = date.today()
    results = []
    failed = []
    start_time = time.time()

    # Load tickers and latest USDHKD rate
    with conn.cursor() as cur:
        cur.execute("SELECT ticker, currency FROM portfolio_positions ORDER BY ticker")
        positions = cur.fetchall()

        cur.execute("""
            SELECT rate FROM fx_rates
            WHERE from_currency = 'USD' AND to_currency = 'HKD'
            ORDER BY rate_date DESC LIMIT 1
        """)
        row = cur.fetchone()
        usdhkd = float(row[0]) if row else 7.80

    us_tickers = [t for t, c in positions if not t.endswith('.HK')]
    hk_tickers = [t for t, c in positions if t.endswith('.HK')]

    log.info(f"[F1] Starting fundamentals fetch: {len(us_tickers)} US tickers, {len(hk_tickers)} HK tickers")
    log.info(f"[F1] as_of_date: {as_of}  |  USDHKD: {usdhkd}")

    # ── US tickers ────────────────────────────────────────────────────────────

    # Step 1: Finnhub — valuation ratios + ROE/ROI for all US tickers
    finnhub_data = {}
    for ticker in us_tickers:
        try:
            resp = requests.get(
                "https://finnhub.io/api/v1/stock/metric",
                params={"symbol": ticker, "metric": "all"},
                headers={"X-Finnhub-Token": finnhub_key},
                timeout=10,
            )
            resp.raise_for_status()
            m = resp.json().get("metric", {})
            finnhub_data[ticker] = {
                "pe_ratio":           _safe_float(m.get("peBasicExclExtraTTM")),
                "pb_ratio":           _safe_float(m.get("pbAnnual")),
                "ev_ebitda":          _safe_float(m.get("evEbitdaTTM")),
                # Finnhub returns these as percentages (e.g. 70.68 = 70.68%) — normalise to decimal
                "revenue_growth_yoy": _safe_pct(m.get("revenueGrowthTTMYoy")),
                "net_margin":         _safe_pct(m.get("netProfitMarginTTM")),
                "debt_equity":        _safe_float(m.get("totalDebt/totalEquityAnnual")),
                "roe":                _safe_pct(m.get("roeTTM")),
                "roic":               _safe_pct(m.get("roiTTM")),
            }
            log.info(f"[Finnhub] {ticker}: PE={finnhub_data[ticker]['pe_ratio']} ROE={finnhub_data[ticker]['roe']}")
        except Exception as e:
            log.warning(f"[Finnhub] WARNING: {ticker} failed — {e}")
            finnhub_data[ticker] = {}
        time.sleep(0.5)

    # Step 2: yfinance — analyst target, sector, country, market cap for US tickers
    # Also serves as fallback for any Finnhub null valuation fields
    yf_us_data = {}
    for ticker in us_tickers:
        try:
            info = yf.Ticker(ticker).info
            target_usd = _safe_float(info.get("targetMeanPrice"))
            yf_us_data[ticker] = {
                "analyst_target_usd": target_usd,
                "market_cap_usd":     _safe_float(info.get("marketCap")),
                "sector":             info.get("sector"),
                "country":            info.get("country"),
                # fallbacks for Finnhub nulls
                "pe_ratio":           _safe_float(info.get("trailingPE")),
                "pb_ratio":           _safe_float(info.get("priceToBook")),
                "ev_ebitda":          _safe_float(info.get("enterpriseToEbitda")),
                "revenue_growth_yoy": _safe_float(info.get("revenueGrowth")),
                "net_margin":         _safe_float(info.get("profitMargins")),
                "debt_equity":        _safe_float(info.get("debtToEquity")),
                "roe":                _safe_float(info.get("returnOnEquity")),
            }
            log.info(f"[yfinance-US] {ticker}: target=${target_usd} sector={yf_us_data[ticker]['sector']}")
        except Exception as e:
            log.warning(f"[yfinance-US] WARNING: {ticker} failed — {e}")
            yf_us_data[ticker] = {}
        time.sleep(2)

    # Merge US ticker data — Finnhub primary, yfinance fills nulls
    for ticker in us_tickers:
        fh = finnhub_data.get(ticker, {})
        yf_ = yf_us_data.get(ticker, {})
        sources = {}

        def pick(field, primary, primary_src, fallback, fallback_src):
            val = primary.get(field)
            if val is not None:
                sources[field] = primary_src
                return val
            val = fallback.get(field)
            if val is not None:
                sources[field] = fallback_src
            return val

        row = {
            "ticker":               ticker,
            "exchange":             "US",
            "as_of_date":           as_of,
            "pe_ratio":             pick("pe_ratio",           fh, "finnhub", yf_, "yfinance"),
            "pb_ratio":             pick("pb_ratio",           fh, "finnhub", yf_, "yfinance"),
            "ev_ebitda":            pick("ev_ebitda",          fh, "finnhub", yf_, "yfinance"),
            "revenue_growth_yoy":   pick("revenue_growth_yoy", fh, "finnhub", yf_, "yfinance"),
            "net_margin":           pick("net_margin",         fh, "finnhub", yf_, "yfinance"),
            "debt_equity":          pick("debt_equity",        fh, "finnhub", yf_, "yfinance"),
            "roe":                  pick("roe",                fh, "finnhub", yf_, "yfinance"),
            "roic":                 fh.get("roic"),
            "analyst_target_usd":   yf_.get("analyst_target_usd"),
            "market_cap_usd":       yf_.get("market_cap_usd"),
            "sector":               yf_.get("sector"),
            "country":              yf_.get("country"),
        }
        if yf_.get("analyst_target_usd") is not None:
            sources["analyst_target_usd"] = "yfinance"
        if yf_.get("market_cap_usd") is not None:
            sources["market_cap_usd"] = "yfinance"
        if yf_.get("sector"):
            sources["sector"] = "yfinance"
        if row.get("roic") is not None:
            sources["roic"] = "finnhub"
        row["sources_json"] = json.dumps(sources)

        is_etf = ticker in ETF_TICKERS
        null_count = sum(1 for k, v in row.items()
                         if k not in ("ticker", "exchange", "as_of_date", "sources_json", "updated_at")
                         and v is None)
        etf_expected_nulls = 4  # PE, analyst_target, sector, revenue_growth often null for ETFs
        threshold = (null_count > 8) if not is_etf else (null_count > 8 + etf_expected_nulls)
        if threshold:
            log.warning(f"[WARN] {ticker}: {null_count} null fields — may be a data gap")
            failed.append(ticker)

        results.append(row)

    # ── HK tickers ────────────────────────────────────────────────────────────

    for ticker in hk_tickers:
        try:
            info = yf.Ticker(ticker).info
            target_hkd = _safe_float(info.get("targetMeanPrice"))
            target_usd = round(target_hkd / usdhkd, 4) if target_hkd is not None else None
            mktcap = _safe_float(info.get("marketCap"))
            mktcap_usd = round(mktcap / usdhkd, 2) if mktcap is not None else None

            row = {
                "ticker":               ticker,
                "exchange":             "HK",
                "as_of_date":           as_of,
                "pe_ratio":             _safe_float(info.get("trailingPE")),
                "pb_ratio":             _safe_float(info.get("priceToBook")),
                "ev_ebitda":            _safe_float(info.get("enterpriseToEbitda")),
                "revenue_growth_yoy":   _safe_float(info.get("revenueGrowth")),
                "net_margin":           _safe_float(info.get("profitMargins")),
                "debt_equity":          _safe_float(info.get("debtToEquity")),
                "analyst_target_usd":   target_usd,
                "market_cap_usd":       mktcap_usd,
                "sector":               info.get("sector"),
                "country":              info.get("country"),
                "roe":                  _safe_float(info.get("returnOnEquity")),
                "roic":                 None,
                "sources_json":         json.dumps({f: "yfinance" for f in [
                    "pe_ratio", "pb_ratio", "ev_ebitda", "revenue_growth_yoy",
                    "net_margin", "debt_equity", "analyst_target_usd", "market_cap_usd",
                    "sector", "country", "roe"
                ]}),
            }
            log.info(f"[yfinance-HK] {ticker}: PE={row['pe_ratio']} target_usd=${target_usd} sector={row['sector']}")
            results.append(row)
        except Exception as e:
            log.error(f"[yfinance-HK] ERROR: {ticker} failed — {e}")
            failed.append(ticker)
        time.sleep(2)

    # ── Upsert all rows ───────────────────────────────────────────────────────

    upserted = 0
    with conn.cursor() as cur:
        for row in results:
            cur.execute("""
                INSERT INTO fundamental_data (
                    ticker, exchange, as_of_date,
                    pe_ratio, pb_ratio, ev_ebitda,
                    revenue_growth_yoy, net_margin, debt_equity,
                    analyst_target_usd, market_cap_usd,
                    sector, country, roe, roic,
                    sources_json, updated_at
                ) VALUES (
                    %(ticker)s, %(exchange)s, %(as_of_date)s,
                    %(pe_ratio)s, %(pb_ratio)s, %(ev_ebitda)s,
                    %(revenue_growth_yoy)s, %(net_margin)s, %(debt_equity)s,
                    %(analyst_target_usd)s, %(market_cap_usd)s,
                    %(sector)s, %(country)s, %(roe)s, %(roic)s,
                    %(sources_json)s, NOW()
                )
                ON CONFLICT (ticker, as_of_date) DO UPDATE SET
                    pe_ratio           = EXCLUDED.pe_ratio,
                    pb_ratio           = EXCLUDED.pb_ratio,
                    ev_ebitda          = EXCLUDED.ev_ebitda,
                    revenue_growth_yoy = EXCLUDED.revenue_growth_yoy,
                    net_margin         = EXCLUDED.net_margin,
                    debt_equity        = EXCLUDED.debt_equity,
                    analyst_target_usd = EXCLUDED.analyst_target_usd,
                    market_cap_usd     = EXCLUDED.market_cap_usd,
                    sector             = EXCLUDED.sector,
                    country            = EXCLUDED.country,
                    roe                = EXCLUDED.roe,
                    roic               = EXCLUDED.roic,
                    sources_json       = EXCLUDED.sources_json,
                    updated_at         = NOW()
            """, row)
            upserted += 1
    conn.commit()
    conn.close()

    elapsed = round(time.time() - start_time, 1)

    fields = ["pe_ratio", "pb_ratio", "ev_ebitda", "revenue_growth_yoy",
              "net_margin", "debt_equity", "analyst_target_usd", "market_cap_usd",
              "sector", "country", "roe"]
    coverage = {}
    for f in fields:
        non_null = sum(1 for r in results if r.get(f) is not None)
        coverage[f] = f"{non_null}/{len(results)}"

    summary = {
        "as_of_date":      str(as_of),
        "tickers_total":   len(results),
        "tickers_us":      len(us_tickers),
        "tickers_hk":      len(hk_tickers),
        "upserted":        upserted,
        "failed_tickers":  failed,
        "field_coverage":  coverage,
        "runtime_seconds": elapsed,
        "usdhkd_rate":     usdhkd,
    }

    log.warning(f"\n[F1] Run complete — {upserted} upserted, {len(failed)} warnings, {elapsed}s")
    log.info(f"  Coverage: {coverage}")

    if len(failed) > len(results) * 0.5:
        raise RuntimeError(f"F1 fundamentals_fetcher: >50% tickers failed. Failed: {failed}")

    return summary


def _safe_float(val) -> Optional[float]:
    try:
        if val is None:
            return None
        f = float(val)
        return None if (f != f) else round(f, 6)  # reject NaN
    except (TypeError, ValueError):
        return None


def _safe_pct(val) -> Optional[float]:
    """Finnhub returns percentage fields as e.g. 70.68 (= 70.68%). Normalise to decimal 0.7068."""
    f = _safe_float(val)
    return round(f / 100, 6) if f is not None else None
