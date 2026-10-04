"""Load everything a backtest or a live decision needs, once."""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date

import pandas as pd

from . import clusters, data

WARMUP_DAYS = 260  # 12-1 momentum needs 253 trading days


@dataclass
class Inputs:
    close: pd.DataFrame
    volume: pd.DataFrame
    groups: "pd.Series | dict[int, pd.Series]"  # SIC groups, or return clusters by fit year
    asof: date
    notes: dict = field(default_factory=dict)
    fund: pd.DataFrame | None = None      # fundamentals.prepare output (quality, value)
    splits: pd.DataFrame | None = None


def load(ds, start: date, end: date, universe: list[str] | None = None) -> Inputs:
    universe = universe or ds.universe()
    years = list(range(start.year, end.year + 1))
    sched = clusters.load()
    # use the frozen fits only if they cover these years and this dataset's names
    need_fit = (sched is None or not set(years) <= set(sched)
                or sched[max(sched)].index.isin(universe).mean() < 0.5)
    # a January fit needs up to 3 years of returns before it
    first = date(start.year - 4, 1, 1) if need_fit else data.window_start(start, WARMUP_DAYS)
    px = data.load_prices(ds, min(first, data.window_start(start, WARMUP_DAYS)), end, universe)
    close, volume = data.to_wide(px, "close"), data.to_wide(px, "volume")
    close, volume, notes = data.split_adjust(close, volume, data.load_splits(ds))
    groups = data.sector_groups(ds, list(close.columns))
    if set(groups.unique()) <= {"other", "all"}:
        # no industry codes in the data: consensus return clusters refit each
        # January on prior data only (src/nabla/clusters.py)
        if need_fit:
            sched = clusters.schedule(close, years)
            notes["sector_source"] = "consensus_clusters_fitted"
        else:
            notes["sector_source"] = "consensus_clusters_config"
        groups = {y: sched[y].reindex(close.columns).fillna("other") for y in years}
        latest = groups[years[-1]]
    else:
        notes["sector_source"] = "sic"
        latest = groups
    notes["sector_groups"] = latest.value_counts().to_dict()
    splits = data.load_splits(ds)
    fund, fnotes = data.load_fundamentals(ds, list(close.columns))
    notes.update(fnotes)
    return Inputs(close, volume, groups, end, notes, fund, splits)
