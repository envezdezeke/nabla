# Workshop questions (Sat 3:15 PM, Investment Society)

Already answered, so do not re-ask:
- Cash can be held.
- Scoring is mostly total return; Sharpe and drawdown still matter.
- Transaction costs should be baked into our own model.
- Our data stops at the holdout date; the model is tested on the 30 days after it.
- We choose our own position and sector limits.
- Plus everything in the starter repo (long-only, puts as the only hedge, the universe, filing-date joins, the rubric).

## Still open, most important first
1. The rubric still checks that holdings weights sum to 1.0 +/- 0.01 (10 points), but cash is allowed. Which governs? Is a cash-like ticker (for example a T-bill ETF) in the universe?
2. Is the book held static for the 30 test days, or can it be rebalanced? How often does the judge call `/portfolio/holdings`?
3. What is the cost model: bps per trade for stocks and for options? Is a bid-ask spread assumed for option fills?
4. How are prizes decided: top total return only, or a blend with Sharpe and drawdown? What weight does the repo audit and pitch get?
5. Our data stops at the holdout date. Does `ds.holdout_cutoff()` (last trading day minus 30 days) still apply, or does the dataset already end where the test begins?
6. Is `ds.prices()` split- and dividend-adjusted? Does the judges' `/backtest` recompute include dividends?
7. What counts as "AI" in the repo audit? Are LLMs, external APIs or external data (VIX, news) allowed?
8. How are option legs priced and marked in the judges' recompute, given missing prints?
9. Exact deadline, and how long must the endpoint stay up? Any hosting or latency limits?
10. Can we add endpoints and extra response fields beyond the five judged ones without penalty?
