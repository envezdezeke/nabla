"""The API starts and keeps serving when the data server refuses us: the frozen
book for holdings/decide, the on-disk cache for backtest/screen/asof."""
import importlib
import sys

import numpy as np
import pandas as pd
from fastapi.testclient import TestClient


def _cache(tmp_path):
    rng = np.random.default_rng(0)
    for y in (2020, 2024, 2026):
        d = pd.bdate_range(f"{y}-01-01", f"{y}-12-31" if y < 2026 else "2026-09-21")
        rows = [{"ticker": t, "date": x, "close": 100 * (1 + rng.normal(0, .01)), "volume": 1e6}
                for t in ("AAPL", "MSFT") for x in d]
        pd.DataFrame(rows).to_parquet(tmp_path / f"prices_{y}.parquet")
        pd.DataFrame({"ticker": "AAPL", "date": d, "atm_iv": 0.3}).to_parquet(tmp_path / f"state_vector_{y}.parquet")


def test_api_without_data_server(monkeypatch, tmp_path):
    monkeypatch.setenv("SV_DATA_ROOT", "http://127.0.0.1:9")  # nothing listens here
    monkeypatch.setenv("SV_DATA_TOKEN", "revoked")
    _cache(tmp_path)
    sys.modules.pop("app.main", None)
    main = importlib.import_module("app.main")
    monkeypatch.setattr(main.data, "CACHE", tmp_path)
    with TestClient(main.app) as c:
        h = c.get("/health").json()
        assert h["ok"] and h["data"].startswith("unavailable")
        hold = c.get("/portfolio/holdings").json()
        assert abs(sum(x["weight"] for x in hold["holdings"]) - 1) < 1e-6
        rec = c.get("/decide", params={"information_cutoff": "2026-09-25"}).json()
        assert rec["target_holdings"] == hold["holdings"] and "fallback" in rec
        assert rec["execution_time"].startswith("2026-09-28T09:30")
        bt = c.post("/backtest", json={"tickers": ["AAPL", "MSFT"], "weights": [.5, .5],
                                       "start": "2020-01-02", "end": "2020-12-31"})
        assert bt.status_code == 200 and bt.json()["n_days"] > 200
        sc = c.get("/screen", params={"min_adv": 5e7, "limit": 10})
        assert sc.status_code == 200 and {r["ticker"] for r in sc.json()["results"]} == {"AAPL", "MSFT"}
        rows = c.get("/asof", params={"ticker": "AAPL", "on": "2024-03-31"}).json()
        assert rows and all(r["date"] <= "2024-03-31" for r in rows)
        assert c.post("/backtest", json={"tickers": ["AAPL"], "start": "2019-01-02",
                                         "end": "2019-06-30"}).status_code == 503  # year not cached
    sys.modules.pop("app.main", None)
