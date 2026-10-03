"""Load everything a backtest or a live decision needs, once."""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date

import pandas as pd

from . import data

WARMUP_DAYS = 260  # 12-1 momentum needs 253 trading days


@dataclass
class Inputs:
    close: pd.DataFrame
    volume: pd.DataFrame
    groups: pd.Series
    asof: date
    notes: dict = field(default_factory=dict)


def load(ds, start: date, end: date, universe: list[str] | None = None) -> Inputs:
    universe = universe or ds.universe()
    px = data.load_prices(ds, data.window_start(start, WARMUP_DAYS), end, universe)
    close, volume = data.to_wide(px, "close"), data.to_wide(px, "volume")
    close, volume, notes = data.split_adjust(close, volume, data.load_splits(ds))
    groups = data.sector_groups(ds, list(close.columns))
    notes["sector_groups"] = groups.value_counts().to_dict()
    return Inputs(close, volume, groups, end, notes)
