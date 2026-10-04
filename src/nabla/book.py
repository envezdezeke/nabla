"""Rung 1 of the v5 ablation: equal-weight top 15 with limits and bands."""
from __future__ import annotations

import pandas as pd

CASH = "CASHHOLDING"  # the judges' cash sleeve: 0% return, no trading fees


def select(score: pd.Series, groups: pd.Series, held: list[str], n: int = 15,
           exit_rank: int = 30, sector_cap: float = 0.30) -> list[str]:
    """Entry band: a new name enters only from the top n. Exit band: a held name
    stays while it ranks within exit_rank. Sector cap enforced as a name count.
    Unclassified names ("all"/"other") are not capped, so a failed sector lookup
    cannot shrink the book to a handful of names."""
    ranked = score.dropna().sort_values(ascending=False)
    rank = pd.Series(range(1, len(ranked) + 1), index=ranked.index)
    max_per_group = max(1, int(sector_cap * n + 1e-9))
    uncapped = {"all", "other"}
    keep = [t for t in held if rank.get(t, exit_rank + 1) <= exit_rank]
    keep = sorted(keep, key=lambda t: rank[t])
    picks, count = [], {}
    for t in keep + [t for t in ranked.index[:n] if t not in keep]:
        g = groups.get(t, "other")
        if len(picks) >= n or (g not in uncapped and count.get(g, 0) >= max_per_group):
            continue
        picks.append(t)
        count[g] = count.get(g, 0) + 1
    # top up past the entry band only if the sector cap left the book short
    for t in ranked.index:
        if len(picks) >= n:
            break
        g = groups.get(t, "other")
        if t not in picks and (g in uncapped or count.get(g, 0) < max_per_group):
            picks.append(t)
            count[g] = count.get(g, 0) + 1
    return picks


def weights(picks: list[str], days_to_report: pd.Series | None = None,
            max_name: float = 0.10, earnings_cap: float = 0.06,
            earnings_days: int = 30) -> pd.Series:
    """Equal weight, then cap names reporting inside the window and hand the
    excess to the others (still under max_name). Sums to 1."""
    if not picks:
        return pd.Series(dtype=float)
    w = pd.Series(1.0 / len(picks), index=picks)
    cap = pd.Series(max_name, index=picks)
    if days_to_report is not None:
        d = days_to_report.reindex(picks)
        cap[(d >= 0) & (d <= earnings_days)] = min(max_name, earnings_cap)
    for _ in range(20):
        over = w > cap + 1e-12
        if not over.any():
            break
        excess = float((w[over] - cap[over]).sum())
        w[over] = cap[over]
        room = (cap - w).clip(lower=0)
        room[over] = 0
        if room.sum() <= 0:
            break
        w += excess * room / room.sum()
    return w / w.sum()


def with_cash(w: pd.Series) -> pd.Series:
    """Stock weights plus the CASHHOLDING residual, so the record sums to 1."""
    w = w[w > 0]
    cash = round(1.0 - float(w.sum()), 10)
    return pd.concat([w, pd.Series({CASH: cash})]) if cash > 1e-9 else w
