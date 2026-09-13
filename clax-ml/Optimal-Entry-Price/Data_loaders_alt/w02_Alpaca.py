# Data_loaders_alt/w02_Alpaca.py
# -----------------------------
import os
import sys
import time
import logging
from pathlib import Path

import pandas as pd
from dotenv import load_dotenv
import alpaca_trade_api as tradeapi
from tqdm import tqdm

# Ensure clax-ml root is importable
_clax_ml_root = str(Path(__file__).resolve().parents[2])
if _clax_ml_root not in sys.path:
    sys.path.insert(0, _clax_ml_root)

from shared_data_loaders.liquidity import (
    get_top_liquid_stocks_alpaca,
    fetch_alpaca_bars,
    _bars_to_frames,
    _select_price_cols,
)
from shared_data_loaders.sp500_tickers import _get_alpaca_api

# ------------------ Logging Setup ------------------ #
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s"
)
logger = logging.getLogger(__name__)

# ------------------ API Setup (Alpaca) ------------------ #
# NOTE (Phase 2b): The module-level `api = tradeapi.REST(...)` call that
# previously lived here was a crash risk — it raised immediately on import
# if ALPACA_API_KEY / ALPACA_SECRET_KEY were not set in the environment.
# All functions in this file now obtain the API client lazily via
# `_get_alpaca_api()` (imported from shared_data_loaders.sp500_tickers),
# which returns None gracefully if credentials are missing rather than
# raising a RuntimeError at import time.
load_dotenv()


# ------------------ Core Functions ------------------ #
def get_top_liquid_stocks(symbols, top_n=50, liquidity_days=252, batch_size=200):
    """
    Fetches volume data via Alpaca and returns the top N most liquid stocks.
    Delegates to shared_data_loaders.liquidity.get_top_liquid_stocks_alpaca with api=None.
    """
    return get_top_liquid_stocks_alpaca(
        symbols=symbols,
        top_n=top_n,
        liquidity_days=liquidity_days,
        batch_size=batch_size,
        api=None,
    )


def fetch_bars_alpaca(symbols, start="2015-01-01", end=None, batch_size=200):
    """
    Batch-downloads daily OHLCV bars from Alpaca REST API.
    Delegates to shared_data_loaders.liquidity.fetch_alpaca_bars with api=None.
    """
    return fetch_alpaca_bars(
        symbols=symbols,
        start=start,
        end=end if end is not None else pd.Timestamp.today(tz="UTC").strftime("%Y-%m-%d"),
        batch_size=batch_size,
        api=None,
    )


def run_pipeline():
    """
    Fetches Alpaca data for top 50 liquid S&P 500 stocks.
    Note: FRED + yfinance extras are handled separately in w02b_Extras.py
    """
    logger.info("====== Starting Data Loader 02 (Alpaca): Market Data Fetching ======")
    start_time = time.time()

    # === 1. Load S&P500 tickers from CSV ===
    logger.info("Step 1/3: Loading S&P500 tickers from CSV...")
    load_tickers_start = time.time()
    sp500_df = pd.read_csv("outputs/01_SP500_Tickers_list.csv")
    initial_sp500_symbols = sp500_df["Symbol"].tolist()
    logger.info("Loaded %d S&P500 tickers in %.2f seconds.",
                len(initial_sp500_symbols), time.time() - load_tickers_start)

    # === 2. Identify Top 50 Most Liquid Stocks ===
    logger.info("Step 2/3: Identifying Top 50 Most Liquid Stocks...")
    identify_liquid_start = time.time()
    sp500_symbols = get_top_liquid_stocks(initial_sp500_symbols)
    logger.info("Identified top liquid stocks in %.2f seconds.", time.time() - identify_liquid_start)

    # === 3. Fetch Alpaca bars for equities ===
    logger.info("Step 3/3: Fetching Alpaca bars in batches...")
    fetch_data_start = time.time()
    stock_frames = fetch_bars_alpaca(sp500_symbols)
    logger.info("Fetched Alpaca data in %.2f seconds.", time.time() - fetch_data_start)

    # === 4. Save Alpaca stock data ===
    logger.info("Saving Alpaca stock data to CSV files...")
    save_csv_start = time.time()
    Path("outputs").mkdir(parents=True, exist_ok=True)

    if stock_frames:
        stocks_df = pd.concat(stock_frames, axis=0)
        if stocks_df is None or stocks_df.empty:
            logger.error("Stocks DataFrame is empty; not saving outputs/02_Yahoo_Stocks.csv.")
        else:
            stocks_df.to_csv("outputs/02_Yahoo_Stocks.csv", index=False)
            logger.info("Saved Stocks CSV with shape %s", stocks_df.shape)

        # --- Save Top 50 universe by 20-day avg dollar volume ---
        try:
            if stocks_df is None or stocks_df.empty:
                raise ValueError("Stocks DataFrame is empty; cannot compute Top 50 universe.")
            stocks_df["DollarVolume"] = stocks_df["Volume"] * stocks_df["Close"]
            latest_date = stocks_df["date"].max()
            recent_dates = sorted(stocks_df["date"].unique(), reverse=True)[:20]
            recent_data = stocks_df[stocks_df["date"].isin(recent_dates)].copy()

            if recent_data.empty:
                logger.warning("No recent data available to compute Top 50 universe.")
            else:
                avg_dollar_volumes = (
                    recent_data.groupby("Ticker")["DollarVolume"]
                    .mean()
                    .reset_index()
                    .rename(columns={"DollarVolume": "AvgDollarVolume"})
                )
                top_50 = avg_dollar_volumes.nlargest(50, "AvgDollarVolume")
                top_50["Date"] = latest_date
                top_50 = top_50[["Date", "Ticker", "AvgDollarVolume"]]
                top_50.to_csv("outputs/02_top50_universe.csv", index=False)
                logger.info("Saved Top 50 universe to outputs/02_top50_universe.csv with %d tickers.", len(top_50))
        except Exception as e:
            logger.warning("Failed to compute/save Top 50 universe: %s", e)
    else:
        logger.error("No stock data to save (all Alpaca downloads failed or returned empty).")

    if not stock_frames:
        logger.warning("No Alpaca stock data fetched or saved in this run!")

    logger.info("Saved Alpaca CSVs in %.2f seconds.", time.time() - save_csv_start)
    logger.info("====== Alpaca data fetching pipeline completed in %.2f seconds. ======", time.time() - start_time)
    logger.info("Note: Run w02b_Extras.py separately to fetch FRED + yfinance extras data.")


if __name__ == "__main__":
    run_pipeline()
