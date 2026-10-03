"""v1 strategy: the decision made on each rebalance date, shared by the backtest and the API."""
from __future__ import annotations

import json
from pathlib import Path

import pandas as pd

from . import book, combine, factors

CONFIG = Path(__file__).resolve().parents[2] / "config" / "model.json"


def load_config(path: Path | str = CONFIG) -> dict:
    return json.loads(Path(path).read_text())


def decide(ft: pd.DataFrame, groups: pd.Series, held: list[str], cfg: dict) -> tuple[pd.Series, pd.DataFrame]:
    """Liquidity filter -> composite -> banded top-n -> capped equal weights."""
    ok = factors.liquid(ft, **cfg["liquidity"])
    pool = ft[ok]
    score = combine.composite(pool, groups, cfg["factor_weights"])
    b = cfg["book"]
    picks = book.select(score, groups, held, n=b["n"], exit_rank=b["exit_rank"], sector_cap=b["sector_cap"])
    w = book.weights(picks, pool["days_to_next_report"], max_name=b["max_name"],
                     earnings_cap=b["earnings_cap"], earnings_days=b["earnings_days"])
    detail = pool.assign(score=score, group=groups.reindex(pool.index)).sort_values("score", ascending=False)
    return w, detail


def strategy(groups: pd.Series, cfg: dict):
    def fn(ft, held, _sig):
        return decide(ft, groups, held, cfg)[0]
    return fn


def equal_weight_liquid(cfg: dict):
    """Benchmark: every name passing the same liquidity filter, equal weight."""
    def fn(ft, _held, _sig):
        names = ft.index[factors.liquid(ft, **cfg["liquidity"])]
        return pd.Series(1.0 / len(names), index=names) if len(names) else pd.Series(dtype=float)
    return fn
