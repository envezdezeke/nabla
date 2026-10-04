"""Is a return edge skill or luck? Small, dependency-free significance tests.

  newey_west_t      t-stat of a mean with autocorrelation-robust (HAC) errors
  paired_bootstrap  stationary block bootstrap of the return gap between two
                    strategies run on the same days (p-value, 90% interval)
  deflated_sharpe   probability the true Sharpe is above zero after accounting
                    for how many variants were tried (Bailey and Lopez de Prado 2014)
  rank_ic           weekly Spearman IC of a score against next-period returns
"""
from __future__ import annotations

import math

import numpy as np
import pandas as pd

YEAR = 252
EULER = 0.5772156649


def newey_west_t(x: pd.Series | np.ndarray, lags: int | None = None) -> float:
    x = np.asarray(pd.Series(x).dropna(), dtype=float)
    n = len(x)
    if n < 10:
        return float("nan")
    lags = lags if lags is not None else int(4 * (n / 100) ** (2 / 9))
    e = x - x.mean()
    var = e @ e / n
    for k in range(1, lags + 1):
        var += 2 * (1 - k / (lags + 1)) * (e[k:] @ e[:-k]) / n
    return float(x.mean() / math.sqrt(var / n)) if var > 0 else float("nan")


def paired_bootstrap(a: pd.Series, b: pd.Series, n_boot: int = 2000, block: int = 21,
                     seed: int = 0) -> dict:
    """Annualized return gap a - b with a stationary block bootstrap (mean block
    `block` days keeps volatility clustering). p is one-sided: P(gap <= 0)."""
    x = pd.concat([a, b], axis=1, keys=["a", "b"], sort=True).dropna()
    d = (x["a"] - x["b"]).to_numpy()
    n = len(d)
    rng = np.random.default_rng(seed)
    p_new = 1.0 / block
    means = np.empty(n_boot)
    for k in range(n_boot):
        idx = np.empty(n, dtype=int)
        idx[0] = rng.integers(n)
        jump = rng.random(n) < p_new
        starts = rng.integers(n, size=n)
        for t in range(1, n):
            idx[t] = starts[t] if jump[t] else (idx[t - 1] + 1) % n
        means[k] = d[idx].mean()
    return {"gap_ann": float(d.mean() * YEAR), "gap_t_nw": newey_west_t(d),
            "p_gap_le_0": float((means <= 0).mean()),
            "gap_ci90": [float(np.quantile(means, 0.05) * YEAR), float(np.quantile(means, 0.95) * YEAR)]}


def _norm_cdf(z: float) -> float:
    return 0.5 * (1 + math.erf(z / math.sqrt(2)))


def _norm_ppf(p: float) -> float:
    lo, hi = -10.0, 10.0
    for _ in range(100):
        mid = (lo + hi) / 2
        lo, hi = (mid, hi) if _norm_cdf(mid) < p else (lo, mid)
    return (lo + hi) / 2


def deflated_sharpe(r: pd.Series, n_trials: int, trial_sharpes: list[float] | None = None) -> dict:
    """Probability that the true (daily) Sharpe exceeds the best Sharpe expected
    from n_trials skill-less variants. Above 0.95 is the usual bar.
    trial_sharpes: daily Sharpes of all variants tried (their spread sets the
    expected maximum); without it, the standard error of one Sharpe is used."""
    r = pd.Series(r).dropna()
    n = len(r)
    sr = r.mean() / r.std()
    skew, kurt = float(r.skew()), float(r.kurt() + 3)
    se = math.sqrt((1 - skew * sr + (kurt - 1) / 4 * sr ** 2) / (n - 1))
    if n_trials > 1:
        spread = float(np.std(trial_sharpes, ddof=1)) if trial_sharpes and len(trial_sharpes) > 1 else se
        sr0 = spread * ((1 - EULER) * _norm_ppf(1 - 1 / n_trials) + EULER * _norm_ppf(1 - 1 / (n_trials * math.e)))
    else:
        sr0 = 0.0
    return {"sharpe_ann": float(sr * math.sqrt(YEAR)), "sharpe0_ann": float(sr0 * math.sqrt(YEAR)),
            "psr_vs_0": _norm_cdf(sr / se), "dsr": _norm_cdf((sr - sr0) / se), "n_trials": n_trials}


def rank_ic(score: pd.Series, fwd: pd.Series) -> float:
    x = pd.concat([score, fwd], axis=1, sort=True).dropna()
    if len(x) < 20:
        return float("nan")
    return float(x.iloc[:, 0].rank().corr(x.iloc[:, 1].rank()))
