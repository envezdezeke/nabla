"""Stress and panic flags from the plan (Step 1), as pure functions of data.

    stress: S&P 500 below its 200-day average AND (21-day realized volatility
            OR funding stress above its 80th percentile of all history so far)
    panic:  S&P 500 down over 12 months AND 21-day volatility above its 80th percentile

Percentiles use expanding history only (nothing after the date). A flag
switches on when its condition is true at a weekly check and switches off only
after two straight weekly checks with the condition false (hysteresis). The
whole weekly history is recomputed from data each call, so no stored state is
needed and the same data always gives the same answer.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

MIN_HISTORY = 252  # trading days before percentiles are trusted


def _expanding_pct_rank(x: pd.Series) -> pd.Series:
    """Percentile of each value among all values up to and including that date."""
    vals = x.to_numpy()
    out = np.full(len(vals), np.nan)
    for i in range(len(vals)):
        if i + 1 >= MIN_HISTORY and np.isfinite(vals[i]):
            hist = vals[: i + 1]
            hist = hist[np.isfinite(hist)]
            out[i] = (hist <= vals[i]).mean()
    return pd.Series(out, index=x.index)


def conditions(spx: pd.Series, funding: pd.Series | None = None) -> pd.DataFrame:
    """Daily raw conditions (before hysteresis)."""
    spx = spx.dropna().sort_index()
    ret = spx.pct_change()
    vol21 = ret.rolling(21).std() * np.sqrt(252)
    vol_pct = _expanding_pct_rank(vol21)
    below_200 = spx < spx.rolling(200).mean()
    ret_12m = spx / spx.shift(252) - 1
    df = pd.DataFrame({"spx": spx, "vol21": vol21, "vol_pct": vol_pct,
                       "below_200dma": below_200, "ret_12m": ret_12m})
    if funding is not None and len(funding.dropna()):
        f = funding.dropna().sort_index().reindex(spx.index).ffill()
        df["funding_pct"] = _expanding_pct_rank(f)
    else:
        df["funding_pct"] = np.nan
    hot = (df["vol_pct"] > 0.8) | (df["funding_pct"] > 0.8)
    df["stress_raw"] = df["below_200dma"] & hot
    df["panic_raw"] = (df["ret_12m"] < 0) & (df["vol_pct"] > 0.8)
    return df


def weekly_flags(spx: pd.Series, funding: pd.Series | None = None, off_after: int = 2) -> pd.DataFrame:
    """Flags at each weekly check (last trading day of each week), with hysteresis."""
    c = conditions(spx, funding)
    wk = c.groupby(c.index.to_period("W")).tail(1)
    out = []
    state = {"stress": False, "panic": False}
    calm = {"stress": 0, "panic": 0}
    for d, row in wk.iterrows():
        for k in ("stress", "panic"):
            if bool(row[f"{k}_raw"]):
                state[k], calm[k] = True, 0
            elif state[k]:
                calm[k] += 1
                if calm[k] >= off_after:
                    state[k], calm[k] = False, 0
        out.append({"date": d, "stress": state["stress"], "panic": state["panic"],
                    "below_200dma": bool(row["below_200dma"]), "vol_pct": row["vol_pct"],
                    "funding_pct": row["funding_pct"], "ret_12m": row["ret_12m"]})
    return pd.DataFrame(out).set_index("date")


def flags_asof(spx: pd.Series, asof, funding: pd.Series | None = None) -> dict:
    """Flags at the last weekly check on or before `asof`, using data up to `asof` only."""
    asof = pd.Timestamp(asof)
    w = weekly_flags(spx[spx.index <= asof], None if funding is None else funding[funding.index <= asof])
    if w.empty:
        return {"stress": False, "panic": False}
    row = w.iloc[-1]
    return {k: (bool(v) if isinstance(v, (bool, np.bool_)) else (None if pd.isna(v) else float(v)))
            for k, v in row.items()} | {"checked": str(w.index[-1].date())}


def flags_at(weekly: pd.DataFrame | None, when) -> dict:
    """Flags from a precomputed weekly_flags table at the last check on or before
    `when`. weekly_flags is causal row by row (expanding percentiles, forward-only
    hysteresis), so computing it once over the whole history and reading row t
    equals recomputing it at t."""
    if weekly is None or weekly.empty:
        return {"stress": False, "panic": False}
    w = weekly[weekly.index <= pd.Timestamp(when)]
    if w.empty:
        return {"stress": False, "panic": False}
    out = {"stress": bool(w["stress"].iloc[-1]), "panic": bool(w["panic"].iloc[-1])}
    if "p_stress" in w and pd.notna(w["p_stress"].iloc[-1]):
        out["p_stress"] = round(float(w["p_stress"].iloc[-1]), 4)
    return out


METHODS = ("rule", "hmm", "hmm_trend", "rule_or_hmm")
HMM_DEFAULTS = {"on": 0.8, "off": 0.5, "off_after": 2, "trend_days": 50}


def _hmm_flags(weekly: pd.DataFrame, p_col: str, extra_on: pd.Series | None, h: dict) -> pd.Series:
    """Stress from P(stress): on at a weekly check when p >= on (and extra_on, if
    given); off after `off_after` straight checks with p < off."""
    state, calm, out = False, 0, []
    for d, p in weekly[p_col].items():
        on = bool(p >= h["on"]) and (extra_on is None or bool(extra_on.get(d, False)))
        if on:
            state, calm = True, 0
        elif state:
            calm = calm + 1 if p < h["off"] else 0
            if calm >= h["off_after"]:
                state, calm = False, 0
        out.append(state)
    return pd.Series(out, index=weekly.index)


def weekly_table(spx: pd.Series, regime_cfg: dict | None = None, params: dict | None = None,
                 funding: pd.Series | None = None) -> pd.DataFrame:
    """Weekly stress/panic flags for the configured method, plus p_stress.

    regime_cfg["method"]: "rule" (v1.2: below 200-day average and high vol),
    "hmm" (P(stress) only), "hmm_trend" (P(stress) and below the 50-day average),
    "rule_or_hmm" (either). Panic always comes from the rule. `params` are the
    yearly HMM fits (config/markov.json); without them the HMM is fitted
    walk-forward on the spot from `spx`.
    """
    from . import markov

    cfg = regime_cfg or {}
    method = cfg.get("method", "rule")
    if method not in METHODS:
        raise ValueError(f"regime method {method!r} not in {METHODS}")
    w = weekly_flags(spx, funding)
    spx = spx.dropna().sort_index()
    if params is None:
        params = markov.load()  # frozen fits; p_stress is reported even under "rule"
    if params is None and method != "rule":
        params = markov.fit_yearly(spx, sorted({d.year for d in spx.index}))
    if params:
        p = markov.p_stress(spx, params)
        w["p_stress"] = p.reindex(w.index, method="ffill")
    else:
        w["p_stress"] = np.nan
    w["stress_rule"] = w["stress"]
    if method == "rule":
        return w
    h = {**HMM_DEFAULTS, **cfg.get("hmm", {})}
    below_trend = (spx < spx.rolling(h["trend_days"]).mean()).reindex(w.index)
    pw = w["p_stress"].fillna(0.0)
    tmp = w.assign(_p=pw)
    hmm_only = _hmm_flags(tmp, "_p", None, h)
    hmm_trend = _hmm_flags(tmp, "_p", below_trend, h)
    w["stress"] = {"hmm": hmm_only, "hmm_trend": hmm_trend,
                   "rule_or_hmm": w["stress_rule"] | hmm_trend}[method]
    return w
