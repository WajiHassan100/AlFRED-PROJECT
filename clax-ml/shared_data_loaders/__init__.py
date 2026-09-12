"""Shared data loaders package for clax-ml agents."""

from .sp500_tickers import (
    fetch_sp500_tickers,
    verify_tickers_with_alpaca,
    build_membership_matrix,
    run_pipeline as run_sp500_pipeline,
)
from .fred_macro import (
    fetch_fred_series,
    save_fred_data,
    run_pipeline as run_fred_pipeline,
)

__all__ = [
    "fetch_sp500_tickers",
    "verify_tickers_with_alpaca",
    "build_membership_matrix",
    "run_sp500_pipeline",
    "fetch_fred_series",
    "save_fred_data",
    "run_fred_pipeline",
]
