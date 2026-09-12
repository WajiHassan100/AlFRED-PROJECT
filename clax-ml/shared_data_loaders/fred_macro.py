# clax-ml/shared_data_loaders/fred_macro.py
# -----------------------------------------
"""
Consolidated FRED Macroeconomic Series Data Loader.
Downloads macro features (Treasury yields, unemployment, CPI) from the St. Louis Fed.
"""

import os
import logging
from typing import Dict, Optional
import pandas as pd
try:
    from pandas_datareader import data as pdr
except ImportError:
    pdr = None
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

logger = logging.getLogger(__name__)

DEFAULT_SERIES_MAPPING: Dict[str, str] = {
    "10Y_Yield": "GS10",
    "5Y_Yield": "DGS5",
    "2Y_Yield": "DGS2",
    "Unemployment": "UNRATE",
    "CPI": "CPIAUCSL"
}


def _print_data_summary(df: pd.DataFrame) -> None:
    """Log shape and date range summary for a fetched dataframe."""
    logger.info(f"Shape: {df.shape}")
    if "Date" in df.columns and not df.empty:
        logger.info(f"Date range: {df['Date'].min().date()} -> {df['Date'].max().date()}")


def fetch_fred_series(
    series_mapping: Optional[Dict[str, str]] = None,
    start: str = "2015-01-01",
    api_key: Optional[str] = None
) -> pd.DataFrame:
    """
    Fetch economic time series from St. Louis FRED via pandas_datareader.
    """
    load_dotenv()
    fred_key = api_key if api_key is not None else os.getenv("FRED_API_KEY")
    logger.info(f"FRED_API_KEY loaded: {'YES' if fred_key else 'NO'}")

    mapping = series_mapping or DEFAULT_SERIES_MAPPING
    logger.info(f"Starting to fetch FRED series from {start}...")
    merged_df = None

    for name, code in tqdm(mapping.items(), desc="Fetching FRED Series"):
        try:
            logger.info(f"   -> Fetching {name} ({code})...")
            series = pdr.DataReader(code, "fred", start=start, api_key=fred_key)
            series.index = pd.to_datetime(series.index)
            series = series.rename(columns={code: name}).reset_index()
            if merged_df is None:
                merged_df = series
            else:
                merged_df = pd.merge(merged_df, series, on="DATE", how="outer")
            logger.info(f"     OK {name}: {series.shape[0]} rows fetched.")
        except Exception as e:
            logger.error(f"     X {name} ({code}) failed: {e}")

    if merged_df is None or merged_df.empty:
        raise RuntimeError("No FRED data fetched. Check API key or series codes.")

    merged_df.rename(columns={"DATE": "Date"}, inplace=True)
    merged_df = merged_df.sort_values("Date").reset_index(drop=True)
    logger.info("FRED data fetching complete.")
    _print_data_summary(merged_df)
    return merged_df


def save_fred_data(
    df: pd.DataFrame,
    filename: str = "outputs/03_fred_features.csv"
) -> None:
    """Save FRED dataframe to CSV."""
    logger.info(f"Saving FRED features to {filename}...")
    dirname = os.path.dirname(filename)
    if dirname:
        os.makedirs(dirname, exist_ok=True)
    df.to_csv(filename, index=False)
    logger.info(f"Saved FRED features at: {os.path.abspath(filename)}")
    _print_data_summary(df)
    logger.info("FRED data saving complete.")


def run_pipeline(
    output_dir: str = "outputs",
    filename: str = "03_fred_features.csv",
    start: str = "2015-01-01",
    series_mapping: Optional[Dict[str, str]] = None,
    api_key: Optional[str] = None
) -> None:
    """Run full FRED macroeconomic series fetching pipeline."""
    logger.info("====== Starting Data Loader 03: FRED Data Fetching ======")
    target_filepath = os.path.join(output_dir, filename) if not os.path.isabs(filename) and os.path.dirname(filename) == "" else filename
    fred_df = fetch_fred_series(series_mapping=series_mapping, start=start, api_key=api_key)
    save_fred_data(fred_df, filename=target_filepath)
    logger.info("====== Finished Data Loader 03 ======")


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
    run_pipeline()
