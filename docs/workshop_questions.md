# Workshop questions (Sat 3:15 PM, Investment Society)

Already answered, so do not re-ask:
- Cash can be held, and scoring will be changed so holding cash is not punished.
- Scored mostly on total return; Sharpe and drawdown still matter.
- Transaction costs should be baked into our own model.
- Our data stops at the cutoff; the model is tested on the 30 days after it.
- Weekly rebalancing is allowed.
- We choose our own position and sector limits.
- Plus everything in the starter repo (long-only, the universe, filing-date joins, the rubric).

## Still open, most important first (numbered to match plan v3)
1. How does new data arrive during the test: does the dataset server update, or does the judge call our endpoint with a date? Will the data server stay up through the test?
2. Which weekday is the book read, and is the 30-day return compounded from the weekly holdings (constant weights rebalanced daily, or buy-and-hold)?
3. Has the starter repo's rubric been updated for cash? Does the holdings check now accept weights summing below 0.99?
4. Which metrics count besides total return (Sharpe, drawdown), and with what weight? How are prizes decided: first place only, or by rank?
5. Does the judge deduct transaction costs, or only our model?
6. Is `ds.prices()` split- and dividend-adjusted? Does the judges' `/backtest` include dividends?
7. Does `ds.holdout_cutoff()` (last trading day minus 30 days) still apply to data that already ends at the cutoff?
8. What counts as "AI" in the repo audit? Are LLMs, external APIs or external data (VIX, news) allowed?
9. Exact deadline, how long must the endpoint stay up, and any hosting or latency limits?
10. Can we add endpoints and extra response fields beyond the five judged ones without penalty?
