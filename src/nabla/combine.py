"""Winsorize, sector-neutral z-score, and weighted composite."""
import pandas as pd

DEFAULT_WEIGHTS = {
    "momentum": 0.25,
    "revisions": 0.25,
    "quality": 0.20,
    "low_vol": 0.15,
    "value": 0.10,
    "reversal": 0.05,
}


def winsorize(df: pd.DataFrame, lo: float = 0.01, hi: float = 0.99) -> pd.DataFrame:
    """Clip each date's cross-section at the lo/hi quantiles."""
    lower = df.quantile(lo, axis=1)
    upper = df.quantile(hi, axis=1)
    return df.clip(lower=lower, upper=upper, axis=0)


def sector_zscore(df: pd.DataFrame, sectors: pd.Series) -> pd.DataFrame:
    """Z-score within sector per date. `sectors` maps ticker -> sector."""
    out = df.copy()
    for sector in sectors.dropna().unique():
        cols = sectors.index[sectors == sector].intersection(df.columns)
        block = df[cols]
        std = block.std(axis=1).replace(0, float("nan"))
        out[cols] = block.sub(block.mean(axis=1), axis=0).div(std, axis=0)
    return out


def composite(factors: dict, sectors: pd.Series, weights: dict | None = None) -> pd.DataFrame:
    """Weighted sum of cleaned factor z-scores. Missing factors are skipped and
    the remaining weights renormalized per cell."""
    weights = weights or DEFAULT_WEIGHTS
    num, den = 0, 0
    for name, w in weights.items():
        if name not in factors:
            continue
        z = sector_zscore(winsorize(factors[name]), sectors)
        num = num + z.fillna(0) * w
        den = den + z.notna() * w
    return num / den.replace(0, float("nan"))
