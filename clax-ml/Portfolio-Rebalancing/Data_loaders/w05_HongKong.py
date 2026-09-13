# Data_loaders/w05_HongKong.py
# --------------------
import sys
import time
import pandas as pd
import yfinance as yf
from pathlib import Path
import logging
from tqdm import tqdm

# Ensure clax-ml root is importable
_clax_ml_root = str(Path(__file__).resolve().parents[2])
if _clax_ml_root not in sys.path:
    sys.path.insert(0, _clax_ml_root)

from shared_data_loaders.liquidity import fetch_yahoo_data

# ------------------ Logging Setup ------------------ #
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s"
)
logger = logging.getLogger(__name__)

# ------------------ Constants ------------------ #
HONGKONG_SYMBOLS = [
    "0001.HK", "0002.HK", "0003.HK", "0005.HK", "0006.HK",
    "0011.HK", "0012.HK", "0016.HK", "0017.HK", "0027.HK",
    "0066.HK", "0083.HK", "0101.HK", "0175.HK", "0232.HK",
    "0267.HK", "0386.HK", "0388.HK", "0669.HK", "0688.HK",
    "0700.HK", "0857.HK", "0883.HK", "0939.HK", "0941.HK",
    "0960.HK", "0968.HK", "0981.HK", "0992.HK", "1038.HK",
    "1088.HK", "1093.HK", "1109.HK", "1113.HK", "1177.HK",
    "1288.HK", "1299.HK", "1336.HK", "1339.HK", "1359.HK",
    "1398.HK", "1810.HK", "1876.HK", "1928.HK", "1929.HK",
    "1997.HK", "2007.HK", "2018.HK", "2269.HK", "2313.HK",
    "2318.HK", "2319.HK", "2331.HK", "2382.HK", "2388.HK",
    "2628.HK", "2688.HK", "2899.HK", "3328.HK", "3690.HK",
    "3968.HK", "3988.HK", "6881.HK",
]

OUTPUT_PATH = "outputs/05_HongKong_OHLCV.csv"


# ------------------ HK-specific retry helper ------------------ #
def _retry_failed_tickers(
    failed_tickers: list,
    start: str,
    end: str,
) -> list:
    """
    Retries individual tickers that failed during batch download.
    HK-specific: wraps each single-ticker result in a MultiIndex so it
    merges cleanly with the batch DataFrames returned by fetch_yahoo_data.

    This retry logic is unique to the HK loader (HK equities have higher
    per-ticker failure rates than US equities) and is not part of the
    shared fetch_yahoo_data implementation.
    """
    extra_data = []
    logger.info("Retrying %d failed tickers individually...", len(failed_tickers))
    for ticker in failed_tickers:
        try:
            df = yf.download(
                ticker, start=start, end=end,
                auto_adjust=True, progress=False
            )
            if df is not None and not df.empty:
                # Wrap in MultiIndex so it's compatible with batch DataFrames
                df.columns = pd.MultiIndex.from_product([[ticker], df.columns])
                extra_data.append(df)
                logger.info("✅ Successfully fetched %s on retry", ticker)
            else:
                logger.warning("❌ No data found for %s on retry", ticker)
        except Exception as e:
            logger.error("❌ Failed to fetch %s on retry: %s", ticker, e)
        time.sleep(1)
    return extra_data


def fetch_data(symbols, start="2015-01-01", end=None, batch_size=50):
    """
    Fetches Hong Kong stock data via yfinance.

    Delegates the bulk batch download to shared_data_loaders.liquidity.fetch_yahoo_data,
    then retries any individually failed tickers using _retry_failed_tickers
    (HK-specific enhancement — not present in other agents' loaders).
    """
    if end is None:
        end = pd.Timestamp.today().strftime("%Y-%m-%d")

    # --- Bulk batch download via shared module ---
    # fetch_yahoo_data skips empty/failed batches with a warning.
    # We track which symbols were NOT covered to feed the retry loop.
    all_data = fetch_yahoo_data(symbols, start=start, end=end, batch_size=batch_size)

    # --- Identify symbols with no data in any batch ---
    fetched_symbols: set = set()
    for batch_df in all_data:
        if isinstance(batch_df.columns, pd.MultiIndex):
            fetched_symbols.update(batch_df.columns.get_level_values(0))
        else:
            fetched_symbols.update(batch_df.columns)

    failed_tickers = [s for s in symbols if s not in fetched_symbols]

    # --- Retry failed tickers individually (HK-specific) ---
    if failed_tickers:
        retry_data = _retry_failed_tickers(failed_tickers, start=start, end=end)
        all_data.extend(retry_data)

    return all_data


def run_pipeline():
    logger.info("====== Starting Data Loader 05: Hong Kong Stock Data Fetching ======")
    start_time = time.time()

    symbols = HONGKONG_SYMBOLS
    logger.info(f"Fetching data for {len(symbols)} Hong Kong stocks...")

    # Fetch data (bulk via shared module + HK-specific retry)
    data_batches = fetch_data(symbols)
    logger.info("Fetched data in batches (including retries).")

    # Reformat into DataFrame
    frames = []
    for sym in tqdm(symbols, desc="Reformatting Data"):
        symbol_frames = []
        for batch_df in data_batches:
            if batch_df is None or getattr(batch_df, "empty", True):
                continue
            if isinstance(batch_df.columns, pd.MultiIndex):
                if sym in batch_df.columns.get_level_values(0):
                    symbol_data = batch_df[sym].copy()
                    symbol_data.columns = symbol_data.columns.droplevel(0) if symbol_data.columns.nlevels > 1 else symbol_data.columns
                    symbol_frames.append(symbol_data)
            elif sym in batch_df.columns:
                symbol_frames.append(batch_df[[sym]])

        if symbol_frames:
            df = pd.concat(symbol_frames)
            if df is not None and not df.empty:
                df["Ticker"] = sym
                df = df.reset_index().rename(columns={"Date": "date"})
                frames.append(df)

    if frames:
        hk_df = pd.concat(frames, axis=0)
        hk_df = hk_df.sort_values(["Ticker", "date"])
        Path("outputs").mkdir(parents=True, exist_ok=True)
        hk_df.to_csv(OUTPUT_PATH, index=False)
        logger.info(f"✅ Saved Hong Kong data to {OUTPUT_PATH} with shape {hk_df.shape}")
    else:
        logger.error("❌ No data fetched for Hong Kong stocks.")

    logger.info(f"Total time: {time.time() - start_time:.2f} seconds.")


if __name__ == "__main__":
    run_pipeline()
