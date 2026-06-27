# Requirements:
# yfinance>=0.2.31
# psycopg2-binary>=2.9

import yfinance as yf
import psycopg2


def main(portfolio_db: dict):
    conn = psycopg2.connect(
        host=portfolio_db["host"],
        port=portfolio_db["port"],
        dbname=portfolio_db["dbname"],
        user=portfolio_db["user"],
        password=portfolio_db["password"],
    )
    cur = conn.cursor()

    cur.execute("SELECT ticker, currency FROM portfolio_positions ORDER BY ticker")
    positions = cur.fetchall()
    print(f"Loaded {len(positions)} positions")

    # Fetch USDHKD rate (stored as USD→HKD: 1 USD = rate HKD)
    try:
        fx_hist = yf.Ticker("USDHKD=X").history(period="5d", auto_adjust=True)
        if not fx_hist.empty:
            fx_date = fx_hist.index[-1].date()
            fx_rate = round(float(fx_hist["Close"].iloc[-1]), 6)
            cur.execute(
                """
                INSERT INTO fx_rates (rate_date, from_currency, to_currency, rate)
                VALUES (%s, 'USD', 'HKD', %s)
                ON CONFLICT (rate_date, from_currency, to_currency) DO NOTHING
                """,
                (fx_date, fx_rate),
            )
            status = "inserted" if cur.rowcount == 1 else "already in DB"
            print(f"FX    USDHKD=X    {fx_date}  {fx_rate}  ({status})")
        else:
            print("FX    USDHKD=X    empty response — skipping")
    except Exception as e:
        print(f"FX    USDHKD=X    FAILED: {e}")

    # Fetch EOD prices — insert last 2 rows per ticker for immediate P&L on first run
    inserted = 0
    skipped = 0
    failed = []

    for ticker, currency in positions:
        try:
            hist = yf.Ticker(ticker).history(period="5d", auto_adjust=True)
            if hist.empty:
                print(f"FAIL  {ticker:<10}  empty response")
                failed.append(ticker)
                continue

            for ts, row in hist.tail(2).iterrows():
                price_date = ts.date()
                close_price = round(float(row["Close"]), 4)
                cur.execute(
                    """
                    INSERT INTO price_history (ticker, price_date, close_price, currency)
                    VALUES (%s, %s, %s, %s)
                    ON CONFLICT (ticker, price_date) DO NOTHING
                    """,
                    (ticker, price_date, close_price, currency),
                )
                if cur.rowcount == 1:
                    inserted += 1
                else:
                    skipped += 1

            latest_date  = hist.index[-1].date()
            latest_price = round(float(hist["Close"].iloc[-1]), 4)
            print(f"OK    {ticker:<10}  {latest_date}  {latest_price}  {currency}")

        except Exception as e:
            print(f"FAIL  {ticker:<10}  {e}")
            failed.append(ticker)

    conn.commit()
    cur.close()
    conn.close()

    print(f"\nDone: {inserted} rows inserted, {skipped} already in DB, {len(failed)} tickers failed")
    if failed:
        print(f"Failed: {', '.join(failed)}")

    if len(failed) > len(positions) // 2:
        raise RuntimeError(f"More than half of tickers failed: {', '.join(failed)}")
