# clax-ml/shared_data_loaders/liquidity.py
# ----------------------------------------
"""
Shared Liquidity Ranking & Symbol Normalization Module.

Provides:
- normalize_yahoo_symbol: Converts broker/Alpaca symbol formats (e.g. BRK-B) to Yahoo format (BRK.B).
- get_top_liquid_stocks_yfinance: Identifies top liquid stocks by volume using yfinance.
- get_top_liquid_stocks_alpaca: Identifies top liquid stocks by volume using Alpaca REST API.
"""

import os
import sys
import time
import logging
from datetime import timedelta
from pathlib import Path
from typing import Any, Dict, List, Optional

import pandas as pd

# Safe optional imports
try:
    import yfinance as yf
except ImportError:
    yf = None

try:
    import alpaca_trade_api as tradeapi
except ImportError:
    tradeapi = None

try:
    from tqdm import tqdm
except ImportError:
    def tqdm(iterable, *args, **kwargs):
        return iterable

# Ensure clax-ml root is in sys.path to import shared_data_loaders
_clax_ml_root = str(Path(__file__).resolve().parents[1])
if _clax_ml_root not in sys.path:
    sys.path.insert(0, _clax_ml_root)

try:
    from shared_data_loaders.sp500_tickers import _get_alpaca_api
except ImportError:
    try:
        from .sp500_tickers import _get_alpaca_api
    except ImportError:
        from sp500_tickers import _get_alpaca_api

logger = logging.getLogger(__name__)


# ------------------ Symbol Normalization ------------------ #
def normalize_yahoo_symbol(symbol: str) -> str:
    """
    Normalize symbols for Yahoo Finance.

    Examples:
    - BRK-B -> BRK.B
    - BF-B  -> BF.B

    Leaves non-equity symbols (indices starting with '^', FX pairs with '=', futures) unchanged.
    """
    if not isinstance(symbol, str):
        return symbol
    # Leave indices, FX pairs, and futures untouched
    if symbol.startswith("^") or "=" in symbol:
        return symbol
    return symbol.replace("-", ".")


# Backwards compatibility alias
_normalize_yahoo_symbol = normalize_yahoo_symbol


# ------------------ yfinance Liquidity Ranker ------------------ #
def get_top_liquid_stocks_yfinance(
    symbols: List[str],
    top_n: int = 50,
    liquidity_days: int = 252
) -> List[str]:
    """
    Fetches volume data via yfinance and returns the top N most liquid stocks by average daily volume.
    Processes all symbols in a single bulk download, matching original behavior.

    Parameters
    ----------
    symbols : List[str]
        List of stock symbols to evaluate.
    top_n : int, default=50
        Number of top liquid stocks to return.
    liquidity_days : int, default=252
        Lookback window in days (trading year + 50 day buffer).

    Returns
    -------
    List[str]
        Top N liquid symbols sorted descending by average daily volume.
    """
    if not symbols or top_n <= 0:
        return []

    if yf is None:
        logger.warning("yfinance is not installed; returning original symbols (first %d).", top_n)
        return symbols[:top_n]

    logger.info("Identifying top %d most liquid stocks from %d tickers...", top_n, len(symbols))
    start_time = time.time()
    end_date = pd.Timestamp.today()
    start_date = end_date - timedelta(days=liquidity_days + 50)  # Fetch a bit more for buffer

    fetch_volume_start = time.time()
    logger.info("Downloading volume data for %d symbols...", len(symbols))
    all_volume_data = None
    try:
        all_volume_data = yf.download(
            symbols,
            start=start_date.strftime("%Y-%m-%d"),
            end=end_date.strftime("%Y-%m-%d"),
            group_by="ticker",
            auto_adjust=True,
            threads=True,
            progress=True
        )
    except Exception as e:
        logger.warning("yfinance liquidity download failed: %s", e)
    logger.info("Finished downloading volume data in %.2f seconds.", time.time() - fetch_volume_start)

    if all_volume_data is None or all_volume_data.empty:
        logger.warning(
            "Could not fetch volume data for liquidity check. Using original list (first %d).",
            top_n
        )
        return symbols[:top_n]

    calculate_avg_volume_start = time.time()
    logger.info("Calculating average volumes...")
    avg_volumes: Dict[str, float] = {}

    for symbol in tqdm(symbols, desc="Calculating Avg Volume"):
        try:
            # Handle both single and multi-level column structures
            if isinstance(all_volume_data.columns, pd.MultiIndex):
                symbol_data = all_volume_data[symbol]
            else:
                # If only one symbol was fetched, columns are not multi-indexed
                symbol_data = all_volume_data if len(symbols) == 1 else all_volume_data.xs(symbol, level=1, axis=1)

            if symbol_data is None or symbol_data.empty:
                logger.warning("No volume data for %s during liquidity check; treating as 0.", symbol)
                avg_volumes[symbol] = 0.0
            elif "Volume" in symbol_data.columns:
                # INTENTIONAL DEVIATION / BUGFIX:
                # In the original code, symbol_data['Volume'].mean() could return NaN if all volume values
                # were missing. In Python, sorting a dict containing NaN values with reverse=True leads to
                # arbitrary, platform-dependent ordering where delisted/missing tickers could float into top_n.
                # Coercing NaN to 0.0 ensures tickers with missing volume strictly sort to the bottom.
                mean_vol = symbol_data["Volume"].mean()
                avg_volumes[symbol] = float(mean_vol) if pd.notna(mean_vol) else 0.0
            else:
                logger.warning("Missing Volume column for %s during liquidity check; treating as 0.", symbol)
                avg_volumes[symbol] = 0.0
        except (KeyError, IndexError):
            logger.debug("Could not process volume for %s. Delisted or no data.", symbol)
            avg_volumes[symbol] = 0.0

    logger.info("Calculated average volumes in %.2f seconds.", time.time() - calculate_avg_volume_start)

    # Sort by volume descending and take top N
    sorted_symbols = sorted(avg_volumes.items(), key=lambda item: item[1], reverse=True)
    top_liquid_symbols = [symbol for symbol, _ in sorted_symbols[:top_n]]

    logger.info(
        "Identified Top %d Liquid Stocks (e.g., %s...) in %.2f seconds.",
        top_n,
        top_liquid_symbols[:5],
        time.time() - start_time
    )
    return top_liquid_symbols


# ------------------ Alpaca Liquidity Ranker ------------------ #
def get_top_liquid_stocks_alpaca(
    symbols: List[str],
    top_n: int = 50,
    liquidity_days: int = 252,
    batch_size: int = 200,
    api: Optional[Any] = None
) -> List[str]:
    """
    Fetches volume data via Alpaca and returns the top N most liquid stocks.

    Parameters
    ----------
    symbols : List[str]
        List of stock symbols to evaluate.
    top_n : int, default=50
        Number of top liquid stocks to return.
    liquidity_days : int, default=252
        Lookback window in days (trading year + 50 day buffer).
    batch_size : int, default=200
        Batch size for Alpaca bars API requests.
    api : Optional[tradeapi.REST], default=None
        Optional existing Alpaca REST client. If None, safely initializes via `_get_alpaca_api()`.

    Returns
    -------
    List[str]
        Top N liquid symbols sorted descending by average daily volume.
    """
    if not symbols or top_n <= 0:
        return []

    if api is None:
        api = _get_alpaca_api()

    if api is None:
        logger.warning(
            "Alpaca API credentials missing or client unavailable. "
            "Cannot calculate liquidity via Alpaca; returning original symbol list (first %d).",
            top_n
        )
        return symbols[:top_n]

    logger.info("Identifying top %d most liquid stocks from %d tickers...", top_n, len(symbols))
    start_time = time.time()
    end_date = pd.Timestamp.today(tz="UTC")
    start_date = end_date - timedelta(days=liquidity_days + 50)

    avg_volumes: Dict[str, float] = {s: 0.0 for s in symbols}

    timeframe = tradeapi.TimeFrame.Day if (tradeapi is not None and hasattr(tradeapi, "TimeFrame")) else "1Day"

    for i in tqdm(range(0, len(symbols), batch_size), desc="Liquidity Batches"):
        batch = symbols[i:i + batch_size]
        try:
            bars = api.get_bars(
                batch,
                timeframe,
                start=start_date.isoformat(),
                end=end_date.isoformat(),
                adjustment="all",
            ).df
        except Exception as e:
            logger.warning("Alpaca liquidity batch failed: %s", e)
            continue

        if bars is None or bars.empty:
            continue

        if isinstance(bars.index, pd.MultiIndex):
            for symbol, g in bars.groupby(level=0):
                if "volume" in g.columns:
                    vol = g["volume"].mean()
                    # INTENTIONAL DEVIATION / BUGFIX: coerce NaN to 0.0
                    avg_volumes[symbol] = float(vol) if pd.notna(vol) else 0.0
        else:
            if "symbol" in bars.columns and "volume" in bars.columns:
                grouped = bars.groupby("symbol")["volume"].mean()
                for symbol, vol in grouped.items():
                    # INTENTIONAL DEVIATION / BUGFIX: coerce NaN to 0.0
                    avg_volumes[symbol] = float(vol) if pd.notna(vol) else 0.0

        time.sleep(0.25)

    sorted_symbols = sorted(avg_volumes.items(), key=lambda item: item[1], reverse=True)
    top_liquid_symbols = [symbol for symbol, _ in sorted_symbols[:top_n]]

    logger.info(
        "Identified Top %d Liquid Stocks (e.g., %s...) in %.2f seconds.",
        top_n,
        top_liquid_symbols[:5],
        time.time() - start_time
    )
    return top_liquid_symbols
