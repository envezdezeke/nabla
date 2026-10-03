"""Raw factor computations.

Conventions: `prices` is a wide DataFrame (index=date, columns=ticker) of
adjusted close (Bloomberg PX_LAST). Every function returns a wide DataFrame of
factor values where HIGHER = MORE ATTRACTIVE. Values at date t use only data
known at t (no look-ahead). Map column names to the real dataset once known.
"""
import numpy as np
import pandas as pd

TRADING_DAYS_MONTH = 21
TRADING_DAYS_YEAR = 252


def momentum_12_1(prices: pd.DataFrame) -> pd.DataFrame:
    """Return from t-12m to t-1m (skips the most recent month)."""
    return prices.shift(TRADING_DAYS_MONTH) / prices.shift(TRADING_DAYS_YEAR) - 1


def short_term_reversal(prices: pd.DataFrame) -> pd.DataFrame:
    """Negative of the last 1-month return."""
    return -(prices / prices.shift(TRADING_DAYS_MONTH) - 1)


def low_volatility(prices: pd.DataFrame, window: int = 60) -> pd.DataFrame:
    """Negative realized daily-return volatility over `window` days."""
    return -prices.pct_change().rolling(window).std()


def estimate_revisions(fwd_eps: pd.DataFrame, lookback: int = 63) -> pd.DataFrame:
    """% change in consensus forward EPS (BEST_EPS) over `lookback` days.

    Uses abs() of the base so negative-EPS names don't flip sign.
    """
    base = fwd_eps.shift(lookback).abs().replace(0, np.nan)
    return (fwd_eps - fwd_eps.shift(lookback)) / base


def quality(roe: pd.DataFrame, debt_to_equity: pd.DataFrame) -> pd.DataFrame:
    """Cross-sectional z of ROE minus z of debt/equity (RETURN_COM_EQY, TOT_DEBT_TO_TOT_EQY)."""
    return _xs_z(roe) - _xs_z(debt_to_equity)


def value(pe_ratio: pd.DataFrame) -> pd.DataFrame:
    """Earnings yield = 1 / PE (PE_RATIO). Non-positive PE -> NaN."""
    return 1.0 / pe_ratio.where(pe_ratio > 0)


def lag_fundamentals(df: pd.DataFrame, days: int = 45) -> pd.DataFrame:
    """Shift slow fundamentals when real report dates are unavailable (no look-ahead)."""
    return df.shift(days)


def _xs_z(df: pd.DataFrame) -> pd.DataFrame:
    return df.sub(df.mean(axis=1), axis=0).div(df.std(axis=1), axis=0)
