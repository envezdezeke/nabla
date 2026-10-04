"""Build the book served by /portfolio/holdings.

The entry/exit bands need last week's holdings. Rather than store state, the
book replays the last few weekly decisions from the data, so the same data
always gives the same book.
"""
from __future__ import annotations

import pandas as pd

from . import data, factors, model, pipeline, sim


def build_book(ds, cfg: dict, replay_weeks: int = 8) -> dict:
    asof = data.last_trading_day(ds)
    start = (pd.Timestamp(asof) - pd.Timedelta(weeks=replay_weeks + 1)).date()
    inp = pipeline.load(ds, start, asof)
    dates = inp.close.index
    rebal = [i for i in sim.rebalance_days(dates) if dates[i] >= pd.Timestamp(start)]
    sig_dates = [dates[i - 1] for i in rebal] + [dates[-1]]
    sv = data.load_state_vector(ds, data.window_start(start, 10), asof, sig_dates)
    sv_by = {d: g for d, g in sv.groupby("date")}

    held: list[str] = []
    for d in sig_dates:  # past weekly decisions, then today's
        i = dates.get_loc(d) + 1
        ft = factors.factor_table(inp.close.iloc[:i].iloc[-sim.YEAR - 2:],
                                  inp.volume.iloc[:i].iloc[-sim.YEAR - 2:],
                                  sv_by.get(d, pd.DataFrame(columns=["ticker"])),
                                  inp.fund, inp.splits)
        w, detail = model.decide(ft, inp.groups, held, cfg)
        held = list(w.index)

    w = w.round(6)
    if len(w):
        w[w.idxmax()] += round(1.0 - w.sum(), 6)
    cols = ["score", "group", *factors.FACTORS, "adv20", "days_to_next_report"]
    return {
        "as_of": str(asof),
        "model": cfg["version"],
        "method": "equal_weight_top15_fixed5_composite_bands",
        "holdings": [{"ticker": t, "weight": float(v)} for t, v in w.items()],
        "coverage": {f: float(ft.loc[detail.index, f].notna().mean()) for f in factors.FACTORS},
        "candidates": detail[cols].head(30).reset_index().rename(columns={"index": "ticker"})
                      .round(4).to_dict("records"),
        "notes": {**inp.notes, **ft.attrs.get("fund_notes", {})},
    }
