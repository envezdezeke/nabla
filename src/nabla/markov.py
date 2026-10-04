"""Two-state Gaussian hidden Markov model on daily S&P 500 returns.

State 0 is calm, state 1 is stress (the higher-volatility state). The model
outputs P(stress) for each day using only returns up to and including that day:
the forward-filtered probability. Smoothed probabilities (forward-backward over
the whole sample) would look ahead and are never used for decisions.

Walk-forward: the parameters used in calendar year Y are fitted on returns
strictly before 1 January of Y. Fitting is deterministic (fixed start values)
and has a prior on the transition matrix that favours persistent regimes, so a
regime lasts weeks rather than days.
"""
from __future__ import annotations

import json
from datetime import date
from pathlib import Path

import numpy as np
import pandas as pd

CONFIG = Path(__file__).resolve().parents[2] / "config" / "markov.json"
SCALE = 100.0           # returns in percent: better-conditioned likelihoods
PRIOR_STAY = 200.0      # pseudo-counts on the diagonal of the transition matrix
PRIOR_MOVE = 2.0        # pseudo-counts off the diagonal (expected stay ~100 days)
MIN_HISTORY = 250       # trading days needed before a fit is trusted


def _norm_pdf(x: np.ndarray, mu: np.ndarray, sd: np.ndarray) -> np.ndarray:
    """Densities, shape (T, 2)."""
    z = (x[:, None] - mu[None, :]) / sd[None, :]
    return np.exp(-0.5 * z * z) / (sd[None, :] * np.sqrt(2 * np.pi))


def _start(x: np.ndarray) -> dict:
    """Deterministic start: calm = quiet days, stress = the volatile tail."""
    sd = x.std()
    return {"pi": np.array([0.9, 0.1]), "A": np.array([[0.98, 0.02], [0.05, 0.95]]),
            "mu": np.array([x.mean(), x.mean() - 0.5 * sd]), "sd": np.array([0.7 * sd, 2.0 * sd])}


def _forward(x: np.ndarray, p: dict) -> tuple[np.ndarray, np.ndarray]:
    """Scaled forward pass. Returns filtered P(state | data so far) and the scales."""
    b = _norm_pdf(x, p["mu"], p["sd"]) + 1e-300
    alpha = np.empty((len(x), 2))
    c = np.empty(len(x))
    a = p["pi"] * b[0]
    c[0] = a.sum()
    alpha[0] = a / c[0]
    A = p["A"]
    for t in range(1, len(x)):
        a = (alpha[t - 1] @ A) * b[t]
        c[t] = a.sum()
        alpha[t] = a / c[t]
    return alpha, c


def fit(returns: pd.Series, iters: int = 200, tol: float = 1e-6) -> dict:
    """Baum-Welch with a persistence prior. `returns` are daily simple returns."""
    x = returns.dropna().to_numpy() * SCALE
    p = _start(x)
    prev = -np.inf
    for _ in range(iters):
        b = _norm_pdf(x, p["mu"], p["sd"]) + 1e-300
        alpha, c = _forward(x, p)
        beta = np.empty_like(alpha)
        beta[-1] = 1.0
        for t in range(len(x) - 2, -1, -1):
            beta[t] = (p["A"] @ (b[t + 1] * beta[t + 1])) / c[t + 1]
        gamma = alpha * beta
        gamma /= gamma.sum(1, keepdims=True)
        xi = (alpha[:-1, :, None] * p["A"][None] * (b[1:] * beta[1:])[:, None, :]) / c[1:, None, None]
        counts = xi.sum(0) + np.array([[PRIOR_STAY, PRIOR_MOVE], [PRIOR_MOVE, PRIOR_STAY]])
        w = gamma.sum(0)
        mu = (gamma * x[:, None]).sum(0) / w
        sd = np.sqrt((gamma * (x[:, None] - mu) ** 2).sum(0) / w).clip(1e-3)
        p = {"pi": gamma[0], "A": counts / counts.sum(1, keepdims=True), "mu": mu, "sd": sd}
        ll = float(np.log(c).sum())
        if abs(ll - prev) < tol * abs(ll):
            break
        prev = ll
    if p["sd"][0] > p["sd"][1]:  # state 1 is always the volatile one
        p = {"pi": p["pi"][::-1], "A": p["A"][::-1, ::-1], "mu": p["mu"][::-1], "sd": p["sd"][::-1]}
    p["loglik"] = float(np.log(_forward(x, p)[1]).sum())
    p["n"] = int(len(x))
    return p


def filtered(returns: pd.Series, p: dict) -> pd.Series:
    """P(stress) each day from returns up to that day (forward filter only)."""
    r = returns.dropna()
    alpha, _ = _forward(r.to_numpy() * SCALE, p)
    return pd.Series(alpha[:, 1], index=r.index)


def fit_yearly(spx: pd.Series, years: list[int]) -> dict[int, dict]:
    """Parameters per calendar year, each fitted on returns before 1 January."""
    r = spx.dropna().sort_index().pct_change().dropna()
    out = {}
    for y in years:
        hist = r[r.index < pd.Timestamp(date(y, 1, 1))]
        if len(hist) >= MIN_HISTORY // 2:
            out[y] = fit(hist)
    return out


def p_stress(spx: pd.Series, params: dict[int, dict]) -> pd.Series:
    """Point-in-time P(stress): days in year Y are filtered with year Y's parameters,
    running the filter over all history up to that day."""
    r = spx.dropna().sort_index().pct_change().dropna()
    parts = []
    for y in sorted(params):
        upto = r[r.index <= pd.Timestamp(date(y, 12, 31))]
        if upto.empty:
            continue
        f = filtered(upto, params[y])
        parts.append(f[f.index.year == y])
    return pd.concat(parts).sort_index() if parts else pd.Series(dtype=float)


def describe(p: dict) -> dict:
    """Readable summary: annualized volatility per state and expected stay in days."""
    vol = p["sd"] / SCALE * np.sqrt(252)
    stay = 1.0 / (1.0 - np.diag(p["A"]))
    return {"calm_vol": float(vol[0]), "stress_vol": float(vol[1]),
            "calm_days": float(stay[0]), "stress_days": float(stay[1]), "n": p.get("n")}


def _to_json(p: dict) -> dict:
    return {k: (v.tolist() if isinstance(v, np.ndarray) else v) for k, v in p.items()}


def save(params: dict[int, dict], meta: dict, path: Path = CONFIG) -> None:
    path.write_text(json.dumps({"meta": meta, "years": {str(y): _to_json(p) for y, p in params.items()}},
                               indent=1))


def load(path: Path = CONFIG) -> dict[int, dict] | None:
    try:
        raw = json.loads(Path(path).read_text())
    except (OSError, ValueError):
        return None
    return {int(y): {k: (np.array(v) if isinstance(v, list) else v) for k, v in p.items()}
            for y, p in raw["years"].items()}
