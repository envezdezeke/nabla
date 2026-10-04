"""The API starts and serves the frozen book when the data server refuses us."""
import importlib
import sys

from fastapi.testclient import TestClient


def test_api_without_data_serves_frozen_book(monkeypatch):
    monkeypatch.setenv("SV_DATA_ROOT", "http://127.0.0.1:9")  # nothing listens here
    monkeypatch.setenv("SV_DATA_TOKEN", "revoked")
    sys.modules.pop("app.main", None)
    main = importlib.import_module("app.main")
    with TestClient(main.app) as c:
        h = c.get("/health").json()
        assert h["ok"] and h["data"].startswith("unavailable")
        hold = c.get("/portfolio/holdings").json()
        assert abs(sum(x["weight"] for x in hold["holdings"]) - 1) < 1e-6
        rec = c.get("/decide", params={"information_cutoff": "2026-09-25"}).json()
        assert rec["target_holdings"] == hold["holdings"] and "fallback" in rec
        assert rec["execution_time"].startswith("2026-09-28T09:30")
        assert c.get("/screen").status_code == 503
    sys.modules.pop("app.main", None)
