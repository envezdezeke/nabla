"""Cross-sectional cleaning and the fixed-five composite for one date."""
from __future__ import annotations

import pandas as pd


def zscore(x: pd.Series, groups: pd.Series, clip: float = 3.0, min_group: int = 5) -> pd.Series:
    """Winsorize at 1/99%, z-score within sector group, clip at +/-3.
    Groups too small to z-score fall back to the whole cross-section."""
    x = x.clip(x.quantile(0.01), x.quantile(0.99))
    g = groups.reindex(x.index).fillna("other")
    size = x.groupby(g).transform("count")
    mu = x.groupby(g).transform("mean").where(size >= min_group, x.mean())
    sd = x.groupby(g).transform("std").where(size >= min_group, x.std())
    return ((x - mu) / sd.replace(0, float("nan"))).clip(-clip, clip)


def composite(ft: pd.DataFrame, groups: pd.Series, weights: dict[str, float]) -> pd.Series:
    """Fixed-weight sum over all listed factors with missing = 0 (neutral).

    Dividing by the full weight sum, not the available one, so a name with
    fewer factors is not favored (v3 review, known issue 1).
    """
    total = sum(weights.values())
    score = sum(zscore(ft[f], groups).fillna(0.0) * w for f, w in weights.items())
    return score / total


def coverage(ft: pd.DataFrame, factors: list[str]) -> dict[str, float]:
    return {f: float(ft[f].notna().mean()) for f in factors}
