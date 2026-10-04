"""Practice run against a deployed endpoint: the judges' calls, one line each.

    python scripts/practice.py --url https://gilled-dork-running.ngrok-free.dev

Runs the rubric requests (health, holdings, backtest, screen, asof) and the
decision-series request, checks the shapes the judges check, validates the
series with the starter's own validator when the SDK is installed, and prints
how long each call took (rubric timeout 30 s, decisions 60 s). Needs no data
token: it only talks to the endpoint.
"""
from __future__ import annotations

import argparse
import json
import time
import urllib.error
import urllib.request

HEADERS = {"Content-Type": "application/json", "ngrok-skip-browser-warning": "1"}


def call(base: str, method: str, path: str, body=None, timeout: int = 60):
    req = urllib.request.Request(base.rstrip("/") + path, method=method, headers=HEADERS,
                                 data=json.dumps(body).encode() if body is not None else None)
    t0 = time.time()
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.status, json.loads(r.read()), time.time() - t0
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode()[:200], time.time() - t0
    except Exception as e:  # noqa: BLE001 - network errors are a result too
        return None, f"{type(e).__name__}: {e}", time.time() - t0


def line(ok: bool, name: str, secs: float, note: str) -> bool:
    print(f"{'PASS' if ok else 'FAIL'}  {name:<22} {secs:5.1f}s  {note}")
    return ok


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--url", required=True)
    ap.add_argument("--window", default="2026-09-22:2026-10-21",
                    help="decisions window start:end (default: the month after the data)")
    args = ap.parse_args()
    u, results = args.url, []

    s, b, t = call(u, "GET", "/health")
    results.append(line(s == 200 and isinstance(b, dict) and b.get("ok") is True, "health", t,
                        f"model {b.get('model')}, data {str(b.get('data'))[:40]}" if isinstance(b, dict) else str(b)))

    s, b, t = call(u, "GET", "/portfolio/holdings")
    if s == 200 and isinstance(b, dict):
        h = b.get("holdings", [])
        tot = sum(x["weight"] for x in h)
        ok = abs(tot - 1) <= 0.01 and all(x["weight"] >= 0 for x in h)
        top = ", ".join(f"{x['ticker']} {x['weight']:.1%}" for x in sorted(h, key=lambda x: -x["weight"])[:5])
        results.append(line(ok, "holdings", t, f"{len(h)} legs, sum {tot:.4f}, as of {b.get('as_of')}: {top}"))
    else:
        results.append(line(False, "holdings", t, f"{s} {b}"))

    rubric_bt = {"tickers": ["AAPL", "MSFT"], "weights": [0.5, 0.5], "start": "2020-01-02", "end": "2020-12-31"}
    s, b, t = call(u, "POST", "/backtest", rubric_bt)
    keys = ["n_days", "total_return", "ann_return", "ann_vol", "sharpe", "max_drawdown"]
    ok = s == 200 and isinstance(b, dict) and all(k in b for k in keys)
    results.append(line(ok and t < 30, "backtest (rubric)", t,
                        f"AAPL/MSFT 2020: return {b['total_return']:+.1%}, sharpe {b['sharpe']:.2f}"
                        if ok else f"{s} {b}"))

    s, b, t = call(u, "GET", "/screen?min_adv=50000000&limit=10")
    ok = s == 200 and isinstance(b, dict) and isinstance(b.get("results"), list) and \
        all("ticker" in r for r in b["results"])
    results.append(line(ok and t < 30, "screen", t,
                        f"{len(b['results'])} names: " + ", ".join(r["ticker"] for r in b["results"][:5])
                        if ok else f"{s} {b}"))

    s, b, t = call(u, "GET", "/asof?ticker=AAPL&on=2024-03-31")
    ok = s == 200 and isinstance(b, list) and all(str(r.get("date", ""))[:10] <= "2024-03-31" for r in b)
    results.append(line(ok and t < 30, "asof (no lookahead)", t, f"{len(b)} rows, none after 2024-03-31"
                        if ok else f"{s} {b}"))

    start, end = args.window.split(":")
    s, b, t = call(u, "POST", "/decisions", {"start": start, "end": end}, timeout=60)
    if s == 200 and isinstance(b, dict):
        series = b.get("series", [])
        try:
            from statevector.backtest import validate_decision_series
            errors = validate_decision_series(series)[1]
        except ImportError:
            errors = []
        fb = sum("fallback" in r for r in series)
        note = (f"{len(series)} decisions {start}..{end}" + (f", {fb} fallback" if fb else "")
                + (f"; INVALID: {errors[:2]}" if errors else ""))
        results.append(line(not errors and t < 60, "decisions", t, note))
        for r in series:
            legs = sorted(r["target_holdings"], key=lambda x: -x["weight"])
            print(f"      #{r['decision_id']} cutoff {r['information_cutoff'][:16]} -> exec "
                  f"{r['execution_time'][:16]}  {len(legs)} legs, top "
                  + ", ".join(f"{x['ticker']} {x['weight']:.1%}" for x in legs[:3]))
    else:
        results.append(line(False, "decisions", t, f"{s} {b}"))

    print(f"\n{sum(results)} of {len(results)} checks passed")


if __name__ == "__main__":
    main()
