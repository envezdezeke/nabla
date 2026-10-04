"""Fit the walk-forward two-state HMM on S&P 500 returns and freeze it in config/markov.json.

    python scripts/fit_markov.py --dry-run     # print fits and timing, write nothing
    python scripts/fit_markov.py               # also write config/markov.json

Prints, per year: history length, calm and stress volatility (annualized), and
how long each regime is expected to last. Then, for each stress method, the
first weekly check that flagged each known episode, the share of weeks flagged,
and today's P(stress). The judged window has no 1 January, so the frozen
parameters cannot change during the test.
"""
from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from statevector import Dataset  # noqa: E402

from nabla import data, markov, model, regime  # noqa: E402

EPISODES = {"2018 Q4": ("2018-10-01", "2018-12-31"), "2020 Covid": ("2020-02-15", "2020-04-30"),
            "2022 bear": ("2022-01-01", "2022-06-30"), "Aug 2024": ("2024-07-24", "2024-08-31"),
            "Apr 2025": ("2025-03-25", "2025-05-15")}

if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--first-year", type=int, default=2018)
    args = ap.parse_args()
    ds = Dataset()
    spx = data.spx_close(ds).dropna()
    last = spx.index[-1]
    years = list(range(args.first_year, last.year + 1))
    params = markov.fit_yearly(spx, years)

    print(f"S&P 500 history {spx.index[0].date()} -> {last.date()}\n")
    print("year  days  calm vol  stress vol  calm stays  stress stays")
    for y, p in params.items():
        d = markov.describe(p)
        print(f"{y}  {d['n']:5d}  {d['calm_vol']:7.1%}  {d['stress_vol']:9.1%}  "
              f"{d['calm_days']:7.0f} d  {d['stress_days']:9.0f} d")

    cfg = model.load_config()["regime"]
    tables = {m: regime.weekly_table(spx, {**cfg, "method": m}, params) for m in regime.METHODS}
    print("\nfirst weekly check flagging stress (blank = never)")
    print("episode       " + "".join(f"{m:>14s}" for m in regime.METHODS))
    for name, (a, b) in EPISODES.items():
        row = []
        for m in regime.METHODS:
            s = tables[m].loc[a:b, "stress"]
            row.append(str(s.index[s.values.argmax()].date()) if s.any() else "-")
        print(f"{name:12s}  " + "".join(f"{x:>14s}" for x in row))
    print("\nshare of weeks flagged, 2018 on: " + ", ".join(
        f"{m} {tables[m].loc[str(args.first_year):, 'stress'].mean():.0%}" for m in regime.METHODS))
    p_now = tables["hmm"]["p_stress"].iloc[-1]
    below50 = bool(spx.iloc[-1] < spx.iloc[-50:].mean())
    below200 = bool(spx.iloc[-1] < spx.iloc[-200:].mean())
    print(f"\ntoday ({last.date()}): P(stress) = {p_now:.2f}; S&P {spx.iloc[-1] / spx.iloc[-200:].mean() - 1:+.1%} "
          f"vs 200-day average (below: {below200}); below 50-day: {below50}")

    if args.dry_run:
        print("\ndry run: nothing written")
    else:
        commit = subprocess.run(["git", "rev-parse", "--short", "HEAD"], capture_output=True, text=True,
                                cwd=ROOT).stdout.strip()
        markov.save(params, {"model": "2-state Gaussian HMM on daily S&P 500 returns, forward-filtered",
                             "fit": "each year on returns before 1 January", "data_through": str(last.date()),
                             "git_commit": commit})
        print(f"\nwrote {markov.CONFIG}")
