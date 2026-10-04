from datetime import date

import pandas as pd

from nabla import data


def _fake(calls):
    def fetch(a, b):
        calls.append((a, b))
        d = pd.bdate_range(a, b)
        return pd.DataFrame({"date": d, "x": range(len(d))})
    return fetch


def test_stale_year_is_refetched(tmp_path, monkeypatch):
    monkeypatch.setattr(data, "CACHE", tmp_path)
    calls = []
    data._cached_years("p", date(2026, 1, 1), date(2026, 2, 20), _fake(calls))
    out = data._cached_years("p", date(2026, 1, 1), date(2026, 9, 21), _fake(calls))
    assert len(calls) == 2 and out["date"].max() == pd.Timestamp("2026-09-21")


def test_fresh_year_is_reused(tmp_path, monkeypatch):
    monkeypatch.setattr(data, "CACHE", tmp_path)
    calls = []
    data._cached_years("p", date(2025, 1, 1), date(2026, 9, 21), _fake(calls))
    data._cached_years("p", date(2025, 6, 1), date(2026, 9, 20), _fake(calls))  # Sunday end
    assert len(calls) == 2  # 2025 and 2026 once each
