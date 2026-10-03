"""Synthetic data for testing the pipeline before real Bloomberg data arrives."""
import numpy as np
import pandas as pd


def make_universe(n_stocks: int = 60, n_days: int = 700, n_sectors: int = 5, seed: int = 0):
    rng = np.random.default_rng(seed)
    dates = pd.bdate_range("2022-01-03", periods=n_days)
    tickers = [f"S{i:03d}" for i in range(n_stocks)]
    drift = rng.normal(0.0003, 0.0003, n_stocks)
    rets = rng.normal(drift, 0.015, (n_days, n_stocks))
    prices = pd.DataFrame(100 * np.cumprod(1 + rets, axis=0), index=dates, columns=tickers)
    sectors = pd.Series([f"SEC{i % n_sectors}" for i in range(n_stocks)], index=tickers)
    fwd_eps = pd.DataFrame(rng.normal(5, 1, (n_days, n_stocks)).cumsum(axis=0) / 50 + 5,
                           index=dates, columns=tickers)
    roe = pd.DataFrame(rng.normal(12, 5, (n_days, n_stocks)), index=dates, columns=tickers)
    d2e = pd.DataFrame(np.abs(rng.normal(80, 40, (n_days, n_stocks))), index=dates, columns=tickers)
    pe = pd.DataFrame(np.abs(rng.normal(20, 8, (n_days, n_stocks))) + 3, index=dates, columns=tickers)
    return {"prices": prices, "sectors": sectors, "fwd_eps": fwd_eps, "roe": roe, "d2e": d2e, "pe": pe}
