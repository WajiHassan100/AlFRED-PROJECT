# clax-ml/shared_data_loaders/sp500_tickers.py
# -------------------------------------------
"""
Consolidated S&P 500 Ticker & Membership Matrix Loader.
Fetches S&P 500 constituents from Wikipedia, verifies tradability via Alpaca,
and constructs/extends an index membership matrix simulating churn.
"""

import os
import logging
import random
from datetime import date
from typing import List, Optional
from io import StringIO

import pandas as pd
import requests
try:
    from dotenv import load_dotenv
except ImportError:
    def load_dotenv(*args, **kwargs):
        pass

try:
    from tqdm import tqdm
except ImportError:
    def tqdm(iterable, *args, **kwargs):
        return iterable

try:
    import alpaca_trade_api as tradeapi
except ImportError:
    tradeapi = None

# ------------------ Logging Setup ------------------ #
logger = logging.getLogger(__name__)


# ------------------ Alpaca API Setup Helper ------------------ #
def _get_alpaca_api(
    api_key: Optional[str] = None,
    api_secret: Optional[str] = None,
    base_url: str = "https://paper-api.alpaca.markets"
):
    """
    Safely initializes and returns an Alpaca REST client if credentials are present.
    """
    load_dotenv()
    key = api_key if api_key is not None else os.getenv("ALPACA_API_KEY", "")
    secret = api_secret if api_secret is not None else os.getenv("ALPACA_SECRET_KEY", "")

    if not key or not secret:
        return None
    if tradeapi is None:
        logger.warning("alpaca_trade_api is not installed. Skipping Alpaca verification.")
        return None

    try:
        return tradeapi.REST(key, secret, base_url)
    except Exception as e:
        logger.warning("Failed to initialize Alpaca REST client: %s", e)
        return None


# ------------------ Data Fetching ------------------ #
def fetch_sp500_tickers(
    output_dir: str = "outputs",
    filename: str = "01_SP500_Tickers_list.csv",
    api_key: Optional[str] = None,
    api_secret: Optional[str] = None,
    base_url: str = "https://paper-api.alpaca.markets",
    fallback_to_wiki: bool = True
) -> List[str]:
    """
    Fetch the current S&P 500 tickers from Wikipedia and verify with Alpaca.
    Saves the tradable tickers to CSV in output_dir.
    """
    logger.info("--- Starting S&P 500 Ticker Fetching ---")
    url = "https://en.wikipedia.org/wiki/List_of_S%26P_500_companies"
    logger.info("Fetching S&P 500 list from Wikipedia...")
    response = requests.get(url, headers={"User-Agent": "Mozilla/5.0"})
    response.raise_for_status()

    tables = pd.read_html(StringIO(response.text))
    raw_tickers: List[str] = tables[0]["Symbol"].str.replace('.', '-', regex=False).tolist()
    logger.info("Successfully fetched %d tickers from Wikipedia.", len(raw_tickers))

    # Verify tickers using Alpaca
    logger.info("Verifying tickers with Alpaca...")
    api = _get_alpaca_api(api_key=api_key, api_secret=api_secret, base_url=base_url)
    tradable_tickers = verify_tickers_with_alpaca(raw_tickers, api=api)
    logger.info("Verified %d tradable tickers via Alpaca.", len(tradable_tickers))

    # Safety: if Alpaca returns 0 tickers (e.g. missing keys or network issue), fall back to raw Wikipedia list
    if len(tradable_tickers) == 0 and fallback_to_wiki:
        logger.warning(
            "Alpaca verification returned 0 tradable tickers. "
            "Falling back to raw Wikipedia tickers (%d symbols).",
            len(raw_tickers),
        )
        tradable_tickers = raw_tickers

    target_filepath = os.path.join(output_dir, filename) if not os.path.isabs(filename) and os.path.dirname(filename) == "" else filename
    _save_tickers_to_csv(tradable_tickers, filename=target_filepath)
    logger.info("--- S&P 500 Ticker Fetching Complete ---")
    return tradable_tickers


def verify_tickers_with_alpaca(tickers: List[str], api=None) -> List[str]:
    """
    Verify which tickers are valid and tradable using Alpaca.
    Returns an empty list if Alpaca credentials/client are missing or every call fails.
    """
    if api is None:
        api = _get_alpaca_api()

    if api is None:
        logger.warning(
            "Alpaca API credentials are missing or client uninitialized. "
            "Skipping Alpaca verification and returning empty verified list for fallback handler."
        )
        return []

    verified: List[str] = []
    first_error_logged = False

    for symbol in tqdm(tickers, desc="Verifying Tickers"):
        try:
            asset = api.get_asset(symbol)
            if getattr(asset, "tradable", False):
                verified.append(symbol)
            else:
                logger.debug("Ticker %s not tradable according to Alpaca.", symbol)
        except Exception as e:
            if not first_error_logged:
                logger.warning(
                    "Alpaca verification failed for ticker %s. "
                    "This may indicate invalid credentials, wrong base URL, or "
                    "connectivity issues. Example error: %s",
                    symbol,
                    str(e),
                )
                first_error_logged = True
            else:
                logger.debug("Ticker %s failed verification: %s", symbol, str(e))

    return verified


def _save_tickers_to_csv(tickers: List[str], filename: str = "outputs/01_SP500_Tickers_list.csv") -> None:
    """Save ticker list to CSV."""
    dirname = os.path.dirname(filename)
    if dirname:
        os.makedirs(dirname, exist_ok=True)
    pd.DataFrame(tickers, columns=["Symbol"]).to_csv(filename, index=False)
    logger.info("Saved tickers list to %s", filename)


# ------------------ Membership Matrix ------------------ #
def build_membership_matrix(
    tickers: List[str],
    filename: str = "outputs/01_SP500_membership_matrix.csv",
    churn_rate: float = 0.02,
    random_seed: Optional[int] = None
) -> pd.DataFrame:
    """
    Build or extend a membership matrix.
    Simulates churn by randomly dropping some tickers each run.
    """
    logger.info("--- Building Membership Matrix ---")
    if random_seed is not None:
        random.seed(random_seed)

    # Default: all tradable = 1
    membership_status = {t: 1 for t in tickers}

    # Simulate churn only when tickers list is non-empty
    dropped: List[str] = []
    if tickers:
        logger.info("Simulating churn with a rate of %.2f...", churn_rate)
        num_churn = max(1, int(len(tickers) * churn_rate))
        dropped = random.sample(tickers, num_churn)
        for d in dropped:
            membership_status[d] = 0
        logger.info("Simulated churn: %d tickers dropped today.", len(dropped))
    else:
        logger.warning(
            "Received an empty ticker list for membership matrix. "
            "Skipping churn simulation; resulting membership row will be empty."
        )

    today = pd.to_datetime(date.today())
    today_row = pd.DataFrame([membership_status], index=[today])

    if os.path.exists(filename):
        logger.info("Existing membership matrix found. Appending new data.")
        existing = pd.read_csv(filename, index_col=0, parse_dates=True)
        combined = pd.concat([existing, today_row], axis=0)
        combined = combined.reindex(columns=sorted(set(combined.columns)), fill_value=0)
    else:
        logger.info("No existing membership matrix found. Creating a new one.")
        combined = today_row

    _save_membership_matrix(combined, filename)
    logger.info("--- Membership Matrix Building Complete ---")
    return combined


def _save_membership_matrix(matrix: pd.DataFrame, filename: str) -> None:
    """
    Save membership matrix with proper Date column to avoid empty first column.
    """
    dirname = os.path.dirname(filename)
    if dirname:
        os.makedirs(dirname, exist_ok=True)

    matrix_reset = matrix.reset_index().rename(columns={'index': 'Date'})
    matrix_reset.to_csv(filename, index=False)
    logger.info("Saved membership matrix to %s with shape %s", filename, matrix.shape)


# ------------------ Main Pipeline ------------------ #
def run_pipeline(
    output_dir: str = "outputs",
    tickers_filename: str = "01_SP500_Tickers_list.csv",
    membership_filename: str = "01_SP500_membership_matrix.csv",
    churn_rate: float = 0.02,
    random_seed: Optional[int] = None,
    api_key: Optional[str] = None,
    api_secret: Optional[str] = None,
) -> None:
    """Run full S&P 500 tickers and membership matrix extraction pipeline."""
    logger.info("====== Starting Data Loader 01: S&P 500 Tickers & Membership ======")
    tickers_path = os.path.join(output_dir, tickers_filename) if not os.path.isabs(tickers_filename) and os.path.dirname(tickers_filename) == "" else tickers_filename
    membership_path = os.path.join(output_dir, membership_filename) if not os.path.isabs(membership_filename) and os.path.dirname(membership_filename) == "" else membership_filename

    tickers = fetch_sp500_tickers(
        output_dir=output_dir,
        filename=tickers_path,
        api_key=api_key,
        api_secret=api_secret
    )
    membership_matrix = build_membership_matrix(
        tickers=tickers,
        filename=membership_path,
        churn_rate=churn_rate,
        random_seed=random_seed
    )
    logger.info("Latest Membership Status:")
    print(membership_matrix.tail())
    logger.info("====== Finished Data Loader 01 ======")


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
    run_pipeline()
