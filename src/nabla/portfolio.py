"""Turn composite scores into weights, subject to risk rules."""
import numpy as np
import pandas as pd

MAX_POSITION = 0.05   # finalize once constraints known
SECTOR_CAP = 0.25


def top_n_weights(score: pd.Series, n: int = 30, vol: pd.Series | None = None) -> pd.Series:
    """Hold the top-n by score; equal-weight, or inverse-vol if `vol` given."""
    picks = score.dropna().nlargest(n).index
    if vol is None:
        w = pd.Series(1.0, index=picks)
    else:
        w = 1.0 / vol.reindex(picks).replace(0, np.nan)
        w = w.fillna(w.median())
    return w / w.sum()


def apply_caps(w: pd.Series, sectors: pd.Series, max_pos: float = MAX_POSITION,
               sector_cap: float = SECTOR_CAP, iters: int = 50) -> pd.Series:
    """Iteratively cap positions and sectors, redistributing excess to uncapped names.
    Residual stays in cash if caps make full investment infeasible."""
    w = w.copy()
    sec = sectors.reindex(w.index)
    for _ in range(iters):
        w = w.clip(upper=max_pos)
        totals = w.groupby(sec).transform("sum")
        over = totals > sector_cap
        w[over] = w[over] * sector_cap / totals[over]
        slack = 1.0 - w.sum()
        free = (w < max_pos) & ~(w.groupby(sec).transform("sum") >= sector_cap - 1e-9)
        if slack < 1e-9 or not free.any():
            break
        w[free] += slack * w[free] / w[free].sum()
    return w


def vol_target_scale(realized_vol: float, target_vol: float = 0.15) -> float:
    """Exposure multiplier in [0, 1]: scale down when realized vol exceeds target."""
    if realized_vol <= 0 or np.isnan(realized_vol):
        return 1.0
    return float(min(1.0, target_vol / realized_vol))
