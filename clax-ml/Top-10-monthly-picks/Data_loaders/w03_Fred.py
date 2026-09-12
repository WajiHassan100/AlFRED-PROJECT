# clax-ml/Top-10-monthly-picks/Data_loaders/w03_Fred.py
"""Thin wrapper delegating to clax-ml/shared_data_loaders/fred_macro.py"""

import sys
import logging
from pathlib import Path

# Ensure clax-ml root is importable
_clax_ml_root = str(Path(__file__).resolve().parents[2])
if _clax_ml_root not in sys.path:
    sys.path.insert(0, _clax_ml_root)

from shared_data_loaders.fred_macro import run_pipeline as _shared_run_pipeline

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")


def run_pipeline() -> None:
    _shared_run_pipeline(output_dir="outputs", filename="03_fred_features.csv")


if __name__ == "__main__":
    run_pipeline()
