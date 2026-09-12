# clax-ml/Portfolio-Rebalancing/Data_loaders/w01_SP500_Tickers_and_Membership.py
"""Thin wrapper delegating to clax-ml/shared_data_loaders/sp500_tickers.py"""

import sys
import logging
from pathlib import Path
from typing import List
import pandas as pd

# Ensure clax-ml root is importable
_clax_ml_root = str(Path(__file__).resolve().parents[2])
if _clax_ml_root not in sys.path:
    sys.path.insert(0, _clax_ml_root)

from shared_data_loaders.sp500_tickers import (
    fetch_sp500_tickers as _shared_fetch_tickers,
    verify_tickers_with_alpaca as _shared_verify_tickers,
    build_membership_matrix as _shared_build_membership,
)

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)


def fetch_sp500_tickers() -> List[str]:
    return _shared_fetch_tickers()


def verify_tickers_with_alpaca(tickers: List[str]) -> List[str]:
    return _shared_verify_tickers(tickers=tickers)


def build_membership_matrix(
    tickers: List[str],
    filename: str = "outputs/01_SP500_membership_matrix.csv",
    churn_rate: float = 0.02
) -> pd.DataFrame:
    return _shared_build_membership(tickers=tickers, filename=filename, churn_rate=churn_rate)


def run_pipeline() -> None:
    logger.info("====== Starting Data Loader 01: S&P 500 Tickers & Membership ======")
    tickers = fetch_sp500_tickers()
    membership_matrix = build_membership_matrix(tickers)
    logger.info("Latest Membership Status:")
    print(membership_matrix.tail())
    logger.info("====== Finished Data Loader 01 ======")


if __name__ == "__main__":
    run_pipeline()
