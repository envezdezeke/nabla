"""Quality and value from filed fundamentals, point-in-time.

Each quarterly row of `fundamentals_actuals` becomes knowable at its SEC
filing, matched the same way as the SDK's `asof_fundamentals`: the first
filing in (period_end + 5d, period_end + 120d]. Filing times are not always
available, so a filing counts from the day after it lands (conservative
against a 16:00 cutoff); with an acceptance timestamp it counts from that time.
Rows with no matching filing count from period_end + 60 days.

Column names in the Bloomberg drop are not documented, so each field is
looked up from a list of candidates. One definition is chosen for the whole
universe from the columns present (not per stock), and recorded in `notes`.
Run `explore/04_fundamentals_check.py` with the token to confirm the mapping.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

FLOWS = ["eps", "sales", "gross_profit", "ebit", "net_income", "fcf", "fcf_per_share", "ebitda"]
STOCKS = ["total_assets", "equity", "net_debt"]
RATIOS = ["gross_margin"]  # quarterly ratios: averaged over the four quarters, not summed

# The Bloomberg drop restates per-share history for splits (NVDA EPS shows no
# jump at the 10-for-1 split in June 2024; checked with explore/04), so the
# split guard is off by default.
SPLIT_GUARD = False

CANDIDATES = {
    "eps": ["is_eps", "eps", "basic_eps", "diluted_eps", "is_diluted_eps", "eps_basic", "eps_diluted",
            "trail_12m_eps", "is_basic_eps_cont_ops"],
    "sales": ["sales_rev_turn", "revenue", "sales", "total_revenue"],
    "gross_profit": ["gross_profit", "is_gross_profit"],
    "ebit": ["ebit", "is_oper_inc", "operating_income", "oper_inc"],
    "net_income": ["net_income", "is_net_income", "ni"],
    "fcf": ["cf_free_cash_flow", "free_cash_flow", "fcf"],
    "fcf_per_share": ["fcf_per_share", "free_cash_flow_per_sh", "cf_free_cash_flow_per_sh"],
    "ebitda": ["ebitda", "is_ebitda"],
    "total_assets": ["bs_tot_asset", "total_assets", "tot_assets"],
    "equity": ["equity", "shareholders_equity", "total_equity", "tot_common_eqy", "bs_tot_eqy", "total_shareholders_equity"],
    "net_debt": ["net_debt", "bs_net_debt"],
    "gross_margin": ["gross_margin", "gross_margin_pct"],
}

FALLBACK_LAG = pd.Timedelta(days=60)
TTM_MAX_SPAN = pd.Timedelta(days=300)  # four quarterly period ends fit inside ~9 months


def resolve_columns(cols) -> dict[str, str]:
    """field -> actual column name, for the fields present (case-insensitive)."""
    lower = {c.lower(): c for c in cols}
    out = {}
    for field, names in CANDIDATES.items():
        for n in names:
            if n in lower:
                out[field] = lower[n]
                break
    return out


def knowable_times(fund: pd.DataFrame, cal: pd.DataFrame) -> pd.Series:
    """Timestamp at which each (ticker, period_end) row was public."""
    pe = pd.to_datetime(fund["date"]).astype("datetime64[ns]")
    out = pd.Series(pe + FALLBACK_LAG, index=fund.index)
    if cal is None or cal.empty:
        return out
    c = cal.copy()
    c["filing_date"] = pd.to_datetime(c["filing_date"]).astype("datetime64[ns]")
    if "acceptance_datetime" in c and c["acceptance_datetime"].notna().any():
        acc = pd.to_datetime(c["acceptance_datetime"], errors="coerce", utc=True)
        acc = acc.dt.tz_convert("America/New_York").dt.tz_localize(None)
        c["avail"] = acc.fillna(c["filing_date"] + pd.Timedelta(days=1))
    else:
        c["avail"] = c["filing_date"] + pd.Timedelta(days=1)
    if "period_end" in c and c["period_end"].notna().any():
        # the calendar names the quarter each filing covers: match on it directly,
        # first filing for that quarter (10-K/A amendments later do not count)
        c["period_end"] = pd.to_datetime(c["period_end"], errors="coerce").astype("datetime64[ns]")
        first = (c.dropna(subset=["period_end", "filing_date"]).sort_values("filing_date")
                 .drop_duplicates(["ticker", "period_end"]))
        key = pd.DataFrame({"ticker": fund["ticker"].values, "period_end": pe.values, "row": fund.index})
        m = key.merge(first[["ticker", "period_end", "filing_date", "avail"]], on=["ticker", "period_end"], how="left")
        ok = m["filing_date"].notna() & (m["filing_date"] <= m["period_end"] + pd.Timedelta(days=120))
        out.loc[m.loc[ok, "row"].values] = m.loc[ok, "avail"].values
        unmatched = ~out.index.isin(m.loc[ok, "row"].values)
        if not unmatched.any():
            return out
        fund, pe = fund[unmatched], pe[unmatched]
    left = pd.DataFrame({"ticker": fund["ticker"].values, "key": (pe + pd.Timedelta(days=6)).values,
                         "pe": pe.values, "row": fund.index})
    left = left.sort_values("key")
    right = c[["ticker", "filing_date", "avail"]].dropna(subset=["filing_date"]).sort_values("filing_date")
    m = pd.merge_asof(left, right, left_on="key", right_on="filing_date", by="ticker", direction="forward")
    ok = m["filing_date"].notna() & (m["filing_date"] <= m["pe"] + pd.Timedelta(days=120))
    out.loc[m.loc[ok, "row"].values] = m.loc[ok, "avail"].values
    return out


def prepare(fund: pd.DataFrame, cal: pd.DataFrame | None) -> tuple[pd.DataFrame, dict]:
    """Rename to standard fields, attach knowable times. Done once per run."""
    cols = resolve_columns(fund.columns)
    keep = ["ticker", "date"] + list(cols.values())
    f = fund[keep].rename(columns={v: k for k, v in cols.items()}).copy()
    f["date"] = pd.to_datetime(f["date"]).astype("datetime64[ns]")
    f = f.drop_duplicates(["ticker", "date"], keep="last").reset_index(drop=True)
    f["knowable"] = knowable_times(f, cal)
    return f, {"fundamental_columns": cols}


def ttm(f: pd.DataFrame, cutoff: pd.Timestamp) -> pd.DataFrame:
    """Per ticker, from rows knowable by `cutoff`: trailing-four-quarter sums of
    flows and the latest balance-sheet values. Needs four quarters inside ~9 months."""
    vis = f[f["knowable"] <= cutoff].sort_values(["ticker", "date"])
    last4 = vis.groupby("ticker").tail(4)
    g = last4.groupby("ticker")
    out = pd.DataFrame({"n_q": g.size(), "span": g["date"].max() - g["date"].min(),
                        "first_pe": g["date"].min(), "last_pe": g["date"].max()})
    full = (out["n_q"] == 4) & (out["span"] <= TTM_MAX_SPAN)
    for c in [c for c in FLOWS if c in f]:
        s = g[c].sum(min_count=4)
        out[c] = s.where(full)
    for c in [c for c in RATIOS if c in f]:
        out[c] = g[c].mean().where(full & (g[c].count() >= 3))
    latest = vis.groupby("ticker").tail(1).set_index("ticker")
    for c in [c for c in STOCKS if c in f]:
        out[c] = latest[c]
    return out


def _safe_div(a: pd.Series, b: pd.Series, positive_denominator: bool = True) -> pd.Series:
    b = b.where(b > 0) if positive_denominator else b.replace(0, np.nan)
    return (a / b).replace([np.inf, -np.inf], np.nan)


def quality(t: pd.DataFrame) -> tuple[pd.Series, str]:
    """One definition for the universe, chosen by which columns exist:
    gross profit / assets (Novy-Marx) > ROE > blend of gross margin, operating
    margin, FCF margin and low leverage (needs 2 per stock). The Bloomberg drop
    has no total assets or equity, so the blend is what runs on the real data."""
    if {"gross_profit", "total_assets"} <= set(t.columns):
        return _safe_div(t["gross_profit"], t["total_assets"]), "gross_profit_to_assets"
    if {"net_income", "equity"} <= set(t.columns):
        return _safe_div(t["net_income"], t["equity"]), "roe"
    parts = {}
    if "gross_margin" in t.columns:
        parts["gross_margin"] = t["gross_margin"]
    if {"ebit", "sales"} <= set(t.columns):
        parts["oper_margin"] = _safe_div(t["ebit"], t["sales"])
    if {"fcf", "sales"} <= set(t.columns):
        parts["fcf_margin"] = _safe_div(t["fcf"], t["sales"])
    if {"net_debt", "ebitda"} <= set(t.columns):
        parts["low_leverage"] = -_safe_div(t["net_debt"], t["ebitda"])
    if len(parts) < 2:
        return pd.Series(np.nan, index=t.index), "unavailable"
    # percentile ranks, not z-scores: tiny-sales names produce margins of +/-20
    # that would otherwise dominate the blend
    z = pd.DataFrame({k: v.rank(pct=True) - 0.5 for k, v in parts.items()})
    q = z.mean(axis=1).where(z.notna().sum(axis=1) >= 2)
    return q, "margin_blend:" + "+".join(parts)


def value(t: pd.DataFrame, price: pd.Series, split_in_window: pd.Series,
          loss_to_bottom: bool = True) -> tuple[pd.Series, str]:
    """Earnings yield = TTM EPS / price. Falls back to FCF per share / price.

    Money-losing companies get an earnings yield of 0, the bottom of the range for
    profitable ones, so they rank last together instead of being sorted by the
    size of their loss (which says little about value) and an extreme loss cannot
    compress the spread among profitable names.
    `split_in_window` names are left neutral (only used when SPLIT_GUARD is on)."""
    p = price.reindex(t.index)
    if "eps" in t:
        v, name = t["eps"] / p.where(p > 0), "earnings_yield"
    elif "fcf_per_share" in t:
        v, name = t["fcf_per_share"] / p.where(p > 0), "fcf_yield"
    else:
        return pd.Series(np.nan, index=t.index), "unavailable"
    v = v.replace([np.inf, -np.inf], np.nan)
    if loss_to_bottom:
        # losses count as zero earnings: they rank last together, without one
        # extreme penny stock stretching the scale and flattening the spread
        # among profitable companies
        v = v.where(~(v < 0), 0.0)
    v = v.where(~split_in_window.reindex(t.index).fillna(False).astype(bool))
    return v, name


def splits_in_window(splits: pd.DataFrame, t: pd.DataFrame, cutoff: pd.Timestamp) -> pd.Series:
    """True where a split's ex-date falls between the oldest TTM quarter and the cutoff."""
    out = pd.Series(False, index=t.index)
    if splits is None or splits.empty or "first_pe" not in t:
        return out
    s = splits.copy()
    s["ex_date"] = pd.to_datetime(s["ex_date"])
    s = s[(s["ex_date"] <= cutoff) & (s["ticker"].isin(t.index))]
    window_start = t["first_pe"] - pd.Timedelta(days=92)  # start of the oldest TTM quarter
    for tk, ex in zip(s["ticker"], s["ex_date"]):
        ws = window_start.get(tk)
        if pd.notna(ws) and ex >= ws:
            out[tk] = True
    return out


def quality_value(f: pd.DataFrame, price: pd.Series, cutoff: pd.Timestamp,
                  splits: pd.DataFrame | None = None) -> tuple[pd.DataFrame, dict]:
    """Quality and value for every ticker in `price`, as of `cutoff` (a timestamp)."""
    t = ttm(f, cutoff).reindex(price.index)
    q, qname = quality(t)
    guard = splits_in_window(splits, t, cutoff) if SPLIT_GUARD else pd.Series(False, index=t.index)
    v, vname = value(t, price, guard)
    return pd.DataFrame({"quality": q, "value": v}), {"quality_def": qname, "value_def": vname}
