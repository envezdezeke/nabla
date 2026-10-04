"""Stable return clusters: consensus k-means, refit each January, point-in-time.

The data has no industry codes, so stocks are grouped by how they move. A single
k-means fit is fragile (a different seed or window regroups many names), so:

  1. For each fit date (January 1 of each year) and each window (1, 2 and 3
     years of daily returns ending the day before), run k-means with 20 seeds
     on the stocks' loadings on the top principal components.
  2. Count how often each pair of stocks lands in the same cluster, divided by
     how often both were in a fit: the co-assignment (consensus) matrix.
  3. Cut 1 - consensus into k groups with average-linkage hierarchical
     clustering. Groups smaller than `min_size` are dissolved into the nearest
     big group, so outliers cannot waste a group slot.
  4. Stocks without enough history for the core fit join the group whose
     average return they correlate with most, using whatever history they have.
     Only names with fewer than `min_days` returns stay "other".

Every fit uses data strictly before its fit date, so a decision in year Y uses
the January-1-of-Y groups in the backtest and live alike.
"""
from __future__ import annotations

import json
from datetime import date
from pathlib import Path

import numpy as np
import pandas as pd

CONFIG = Path(__file__).resolve().parents[2] / "config" / "clusters.json"
DEFAULTS = {"k": 10, "seeds": 20, "windows": [252, 504, 756], "n_pc": 10,
            "min_size": 15, "min_days": 60, "coverage": 0.9}


def _kmeans(x: np.ndarray, k: int, seed: int, iters: int = 100) -> np.ndarray:
    rng = np.random.default_rng(seed)
    centers = [x[rng.integers(len(x))]]
    for _ in range(1, k):  # k-means++ start
        d = np.min([((x - c) ** 2).sum(1) for c in centers], axis=0)
        centers.append(x[rng.choice(len(x), p=d / d.sum())] if d.sum() > 0 else x[rng.integers(len(x))])
    c = np.array(centers)
    lab = np.zeros(len(x), dtype=int)
    for _ in range(iters):
        lab = ((x[:, None, :] - c[None]) ** 2).sum(2).argmin(1)
        new = np.array([x[lab == j].mean(0) if (lab == j).any() else c[j] for j in range(len(c))])
        if np.allclose(new, c):
            break
        c = new
    return lab


def _loadings(r: pd.DataFrame, n_pc: int) -> np.ndarray:
    z = ((r - r.mean()) / r.std().replace(0, np.nan)).fillna(0.0).to_numpy()
    _, _, vt = np.linalg.svd(z, full_matrices=False)
    x = vt[:n_pc].T
    return x / np.linalg.norm(x, axis=1, keepdims=True).clip(1e-12)


def consensus(rets: pd.DataFrame, k: int, seeds: int, windows: list[int], n_pc: int,
              coverage: float) -> tuple[pd.Index, np.ndarray]:
    """Co-assignment frequency over seeds x windows for names covered in at least one window."""
    names = rets.columns
    idx = {t: i for i, t in enumerate(names)}
    together = np.zeros((len(names), len(names)))
    both = np.zeros((len(names), len(names)))
    for w in windows:
        r = rets.iloc[-w:]
        if len(r) < w * coverage:
            continue
        r = r.loc[:, r.notna().mean() >= coverage].fillna(0.0)
        if r.shape[1] < k * 3:
            continue
        x = _loadings(r, n_pc)
        pos = np.array([idx[t] for t in r.columns])
        for s in range(seeds):
            lab = _kmeans(x, k, seed=1000 * w + s)
            same = (lab[:, None] == lab[None, :]).astype(float)
            together[np.ix_(pos, pos)] += same
            both[np.ix_(pos, pos)] += 1.0
    seen = both.diagonal() > 0
    s = np.divide(together, both, out=np.zeros_like(together), where=both > 0)
    return names[seen], s[np.ix_(seen, seen)]


def average_linkage(dist: np.ndarray, n_groups: int) -> np.ndarray:
    """Agglomerative clustering, average linkage (Lance-Williams), stopped at n_groups."""
    n = len(dist)
    d = dist.astype(float).copy()
    np.fill_diagonal(d, np.inf)
    size = np.ones(n)
    label = np.arange(n)
    active = np.ones(n, dtype=bool)
    for _ in range(n - n_groups):
        flat = np.where(active[:, None] & active[None, :], d, np.inf)
        a, b = divmod(int(flat.argmin()), n)
        if a > b:
            a, b = b, a
        new = (size[a] * d[a] + size[b] * d[b]) / (size[a] + size[b])
        d[a], d[:, a] = new, new
        d[a, a] = np.inf
        d[b], d[:, b] = np.inf, np.inf
        size[a] += size[b]
        active[b] = False
        label[label == b] = a
    _, out = np.unique(label, return_inverse=True)
    return out


def cut(names: pd.Index, sim: np.ndarray, k: int, min_size: int) -> pd.Series:
    """k groups of at least min_size: cut finer until k big groups exist, then fold
    small groups' members into the big group they co-cluster with most."""
    for n_cut in range(k, min(4 * k, len(names)) + 1):
        lab = average_linkage(1.0 - sim, n_cut)
        sizes = np.bincount(lab)
        big = np.where(sizes >= min_size)[0]
        if len(big) >= k:
            break
    big = big[np.argsort(-sizes[big])][:k]
    for i in np.where(~np.isin(lab, big))[0]:
        lab[i] = big[int(np.argmax([sim[i, lab == g].mean() for g in big]))]
    order = {g: j for j, g in enumerate(sorted(big, key=lambda g: names[lab == g].min()))}
    return pd.Series([f"cluster{order[g]}" for g in lab], index=names)


def assign_leftovers(groups: pd.Series, rets: pd.DataFrame, min_days: int) -> pd.Series:
    """Names outside the core fit join the group whose average return they track best."""
    out = groups.reindex(rets.columns).fillna("other")
    gret = rets[groups.index].T.groupby(groups).mean().T  # equal-weight return per group
    for t in out.index[out == "other"]:
        r = rets[t].dropna()
        if len(r) < min_days:
            continue
        corr = gret.loc[r.index].corrwith(r)
        if corr.notna().any():
            out[t] = corr.idxmax()
    return out


def fit(close: pd.DataFrame, fit_date, params: dict | None = None) -> pd.Series:
    """Groups for every ticker in `close`, using only prices before `fit_date`."""
    p = {**DEFAULTS, **(params or {})}
    hist = close.loc[close.index < pd.Timestamp(fit_date)]
    rets = hist.pct_change(fill_method=None).iloc[1:].iloc[-max(p["windows"]):]
    names, sim = consensus(rets, p["k"], p["seeds"], p["windows"], p["n_pc"], p["coverage"])
    if len(names) < p["k"] * p["min_size"]:
        return pd.Series("other", index=close.columns)
    core = cut(names, sim, p["k"], p["min_size"])
    return assign_leftovers(core, rets, p["min_days"]).reindex(close.columns).fillna("other")


def schedule(close: pd.DataFrame, years: list[int], params: dict | None = None) -> dict[int, pd.Series]:
    return {y: fit(close, date(y, 1, 1), params) for y in years}


def at(groups, when) -> pd.Series:
    """Groups in force on `when`: the fit for that calendar year (or a fixed Series)."""
    if isinstance(groups, pd.Series):
        return groups
    y = pd.Timestamp(when).year
    usable = [k for k in groups if k <= y]
    return groups[max(usable)] if usable else groups[min(groups)]


def save(sched: dict[int, pd.Series], meta: dict, path: Path = CONFIG) -> None:
    path.write_text(json.dumps({"meta": meta, "years": {str(y): g.to_dict() for y, g in sched.items()}},
                               indent=1, sort_keys=True))


def load(path: Path = CONFIG) -> dict[int, pd.Series] | None:
    try:
        raw = json.loads(Path(path).read_text())
    except (OSError, ValueError):
        return None
    return {int(y): pd.Series(g) for y, g in raw["years"].items()}


def adjusted_rand(a: pd.Series, b: pd.Series) -> float:
    """Agreement between two groupings of the same names (1 = identical, ~0 = chance)."""
    common = a.index.intersection(b.index)
    a, b = a[common], b[common]
    a, b = a[(a != "other") & (b != "other")], b[(a != "other") & (b != "other")]
    if len(a) < 2:
        return float("nan")
    t = pd.crosstab(a, b).to_numpy()

    def c2(x):
        return (x * (x - 1) / 2).sum()
    sum_ij, sa, sb, n = c2(t), c2(t.sum(1)), c2(t.sum(0)), c2(np.array([t.sum()]))
    exp = sa * sb / n
    return float((sum_ij - exp) / ((sa + sb) / 2 - exp)) if (sa + sb) / 2 != exp else 1.0
