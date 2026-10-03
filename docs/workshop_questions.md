# Workshop questions (Sat 3:15 PM, Investment Society)

The starter repo (`orkid-labs/utsa-investment-hackathon`) already answers: long-only with no shorting or written options, protective puts as the only hedge, the universe (`ds.universe()`), the sealed 30-day holdout, the 2017 training start, filing-date joins, and the rubric breakdown. Only ask what is still open. Ordered by how much the answer changes the strategy.

## How the holdout is scored (biggest unknown)
1. Beyond the rubric and repo audit, is there a live portfolio score on our holdings? If so, which metric: total return, Sharpe, or drawdown-penalized?
2. How do judges apply the 30-day holdout to our endpoint? Do they call `/portfolio/holdings` once at the start and hold, or repeatedly (daily or weekly), letting us rebalance?
3. Is the holdout the trailing 30 days inside the dataset (past data we cannot touch), or future days after the dataset ends?
4. Is there a benchmark we are compared against (for example SPX), and is the score absolute or relative?

## Constraints the rules do not state
5. Are there position limits, sector caps, or a minimum number of holdings? (Our working defaults are ~5% per name and ~25% per sector.)
6. Are transaction costs or slippage applied in the scoring? Which execution price (close, next open)?
7. How are option legs priced and filled in the judges' recompute? Is a bid-ask spread assumed? (No quote-level NBBO in the data.)
8. Does the judges' `/backtest` recompute include dividends (the `adjust_dividends` option)? Should our backtest match that setting?

## Data
9. Is `ds.prices()` split- and dividend-adjusted, or raw closes?
10. Is the sentinel ticker `ORKD` handled specially in scoring?
11. Are there rate limits or latency limits on the hosted data server when our endpoint is called live?

## "AI" requirement
12. Does the strategy have to use ML, or does a signal-based model count as AI? How is it judged in the repo audit?
13. Are LLMs or external APIs allowed in the pipeline? Is external data (for example VIX or news) allowed?

## Submission and judging
14. What is the exact deadline, and how long must the endpoint stay up?
15. How are the rubric score, the repo audit, and the pitch weighted? What do the judges want in the pitch?
16. Can we add endpoints and extra response fields beyond the five judged ones without penalty?
17. Are there hosting limits for the endpoint (compute, cold start time against the 30-second timeout)?
