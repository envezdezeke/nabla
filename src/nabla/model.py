"""v1 strategy: the decision made on each rebalance date, shared by the backtest and the API."""
from __future__ import annotations

import json
from pathlib import Path

import pandas as pd

from . import book, combine, factors

CONFIG = Path(__file__).resolve().parents[2] / "config" / "model.json"


def load_config(path: Path | str = CONFIG) -> dict:
    return json.loads(Path(path).read_text())


def decide(ft: pd.DataFrame, groups: pd.Series, held: list[str], cfg: dict,
           flags: dict | None = None) -> tuple[pd.Series, pd.DataFrame]:
    """Liquidity filter -> composite -> banded top-n -> capped equal weights -> regime.

    flags: {"stress": bool, "panic": bool} from regime.flags_at. Rung 2 halves the
    momentum weight in panic; rung 3 holds `stress_cash` of the book in cash
    (CASHHOLDING) under stress. Both are switched in config "regime".
    book.beta_max (off when absent): cap on the book's shrunk beta, see book.beta_limit."""
    rg, flags = cfg.get("regime", {}), flags or {}
    ok = factors.liquid(ft, **cfg["liquidity"])
    pool = ft[ok]
    fw = dict(cfg["factor_weights"])
    if rg.get("panic_momentum") and flags.get("panic"):
        fw["momentum"] = fw.get("momentum", 0.0) * 0.5
    score = combine.composite(pool, groups, fw)
    b = cfg["book"]
    picks = book.select(score, groups, held, n=b["n"], exit_rank=b["exit_rank"], sector_cap=b["sector_cap"])
    def weigh(p):
        return book.weights(p, pool["days_to_next_report"], max_name=b["max_name"],
                            earnings_cap=b["earnings_cap"], earnings_days=b["earnings_days"])
    invested = 1.0 - float(rg["stress_cash"]) if rg.get("stress_cash") and flags.get("stress") else 1.0
    w = weigh(picks)
    if b.get("beta_max"):
        beta = pool["beta"] if "beta" in pool else pd.Series(float("nan"), index=pool.index)
        w = book.beta_limit(w, score, groups, beta, weigh, float(b["beta_max"]), invested,
                            pool_size=b["exit_rank"], sector_cap=b["sector_cap"], n=b["n"])
    w = w * invested  # the rest is CASHHOLDING
    detail = pool.assign(score=score, group=groups.reindex(pool.index)).sort_values("score", ascending=False)
    return w, detail


def strategy(groups, cfg: dict, weekly_flags: pd.DataFrame | None = None):
    """groups: a Series, or {fit year: Series} (the clusters in force at each signal date)."""
    from . import clusters, regime

    def fn(ft, held, sig):
        return decide(ft, clusters.at(groups, sig), held, cfg, regime.flags_at(weekly_flags, sig))[0]
    return fn


def equal_weight_liquid(cfg: dict):
    """Benchmark: every name passing the same liquidity filter, equal weight."""
    def fn(ft, _held, _sig):
        names = ft.index[factors.liquid(ft, **cfg["liquidity"])]
        return pd.Series(1.0 / len(names), index=names) if len(names) else pd.Series(dtype=float)
    return fn
