# Workshop questions (Sat 3:15 PM, Investment Society)

Ordered by how much each answer changes the strategy. Fill answers into CLAUDE.md "Open questions".

## Scoring (drives everything)
1. What is the scoring metric: total return, Sharpe, or drawdown-penalized? Any tie-breakers?
2. Is there a benchmark we are scored against (e.g. S&P 500), and is it relative or absolute?
3. Is the 30-day holdout future data (live) or a withheld past period? Are the dates known?

## Rules / constraints
4. What is the investable universe (index, size, tickers list)? Is it fixed?
5. Can we short? Use leverage or hold cash? Any minimum invested fraction?
6. Position limits (max per name, sector caps, min number of holdings)?
7. Transaction costs / slippage modeled? Any turnover limits?
8. Rebalance frequency: one allocation at start, or can we trade daily during the holdout?
9. Execution price: close, next open, VWAP? Is there a fill delay?

## Data
10. Which Bloomberg fields are included, at what frequency, and from what start date?
11. Are fundamentals/estimates point-in-time (as reported date) or restated? Are report dates given?
12. Are prices split/dividend adjusted? Does the data include delisted names (survivorship)?
13. Are we allowed to use external data (VIX, macro, news, alt data)?

## "AI" requirement
14. Does the strategy have to use ML, or does a factor/rules model count? How is "AI" judged?
15. Are LLMs or other APIs allowed in the pipeline?

## Submission / judging
16. What exactly do we submit (weights file, code, API)? Format and deadline?
17. How is the pitch weighted vs. the returns score? What do judges look for?
18. Is the code run by organizers (compute/time limits, allowed libraries)?
