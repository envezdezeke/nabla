"""Does each factor point the right way? Quintile (five-bucket) test.

On each test date, liquid stocks are split into five buckets by a factor's
sector z-score (what the composite actually uses), and we record each bucket's
average forward return. A good factor has bucket 5 beating bucket 1, returns
rising fairly steadily from 1 to 5, and the spread holding up across years.

Red flags reported per factor:
  backwards     bucket 5 - bucket 1 is negative on average
  not_monotone  bucket returns do not rise steadily (rank correlation < 0.5)
  one_year      the spread is positive in under half the years, or depends on one year
  too_good      monthly spread above 2% or rank IC above 0.10: usually a data leak
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from . import combine, factors

TOO_GOOD_SPREAD = 0.02   # per month (about 27% a year)
TOO_GOOD_IC = 0.10


def forward_returns(close: pd.DataFrame, dates: list, horizon: int = 21, skip: int = 1) -> pd.DataFrame:
    """Return from the close `skip` days after each date to `horizon` days after that.
    Skipping a day mirrors trading at the next open, not at the signal's own close."""
    idx = close.index
    out = {}
    for d in dates:
        i = idx.get_loc(d)
        a, b = i + skip, i + skip + horizon
        if b < len(idx):
            out[d] = close.iloc[b] / close.iloc[a] - 1
    return pd.DataFrame(out).T


def buckets_one_date(z: pd.Series, fwd: pd.Series, n: int = 5, min_names: int = 50) -> pd.Series | None:
    d = pd.DataFrame({"z": z, "fwd": fwd}).dropna()
    if len(d) < min_names or d["z"].nunique() < n:
        return None
    q = pd.qcut(d["z"].rank(method="first"), n, labels=range(1, n + 1))
    out = d.groupby(q, observed=True)["fwd"].mean()
    out["ic"] = d["z"].rank().corr(d["fwd"].rank())
    out["names"] = len(d)
    return out


def quintile_table(z_by_date: dict, fwd: pd.DataFrame, n: int = 5) -> pd.DataFrame:
    """Rows = dates; columns = bucket 1..n mean forward return, ic, names."""
    rows = {}
    for d, z in z_by_date.items():
        if d in fwd.index:
            r = buckets_one_date(z, fwd.loc[d], n)
            if r is not None:
                rows[d] = r
    return pd.DataFrame(rows).T


def summarize(tab: pd.DataFrame, n: int = 5) -> dict:
    """One factor's verdict from its per-date bucket table."""
    if tab.empty:
        return {"dates": 0, "flags": ["no_data"]}
    b = [c for c in range(1, n + 1) if c in tab.columns]
    means = tab[b].mean()
    spread = tab[n] - tab[1]
    years = spread.groupby(pd.to_datetime(spread.index).year).mean()
    mono = float(pd.Series(range(len(b)), dtype=float).corr(pd.Series(means.values).rank()))  # Spearman, no scipy
    best_year = years.idxmax() if len(years) else None
    without_best = float(spread[pd.to_datetime(spread.index).year != best_year].mean()) if best_year else np.nan
    flags = []
    if spread.mean() < 0:
        flags.append("backwards")
    if mono < 0.5:
        flags.append("not_monotone")
    if len(years) >= 2 and ((years > 0).mean() < 0.5 or (spread.mean() > 0 and without_best <= 0)):
        flags.append("one_year")
    if spread.mean() > TOO_GOOD_SPREAD or tab["ic"].mean() > TOO_GOOD_IC:
        flags.append("too_good")
    return {
        "dates": int(len(tab)), "avg_names": float(tab["names"].mean()),
        **{f"q{c}": float(means[c]) for c in b},
        "q5_minus_q1": float(spread.mean()),
        "spread_t": float(spread.mean() / (spread.std(ddof=1) / np.sqrt(len(spread)))) if len(spread) > 2 else np.nan,
        "monotonic": mono, "mean_ic": float(tab["ic"].mean()),
        "years_positive": f"{int((years > 0).sum())}/{len(years)}",
        "spread_by_year": {int(y): round(float(v), 4) for y, v in years.items()},
        "flags": flags or ["ok"],
    }


def factor_z(ft: pd.DataFrame, groups: pd.Series, liquidity: dict, names: list[str]) -> dict[str, pd.Series]:
    """Sector z-scores of each factor among liquid names, as the composite sees them."""
    pool = ft[factors.liquid(ft, **liquidity)]
    return {f: combine.zscore(pool[f], groups) for f in names}
