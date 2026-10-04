# nabla audit

How the model decides, why each rule exists, and what we know it cannot prove. Nothing below has been validated on the real data yet; every number is a starting value fixed before testing, and changes after testing are logged here.

## Portfolio limits

We set these ourselves (the organizers left limits to each team). The score is mostly total return, so the book leans aggressive, but every rule caps a specific way to lose.

| Rule | Value | Reason |
| --- | --- | --- |
| Number of stocks | 15 (12 to 18 once the optimizer ships) | Concentrated enough to stand out from diversified books; one bad pick is survivable. |
| Max per name | 10% | One blowup (a 30% to 50% drop) costs the book about 3 to 5 points, not the month. |
| Max per sector group | 30% | Stops the book from becoming a single-theme bet; about 10 groups from SIC divisions. |
| Beta band (normal) | 1.10 to 1.20 | Enough market exposure to chase total return, without becoming a pure leveraged-market bet. |
| Names reporting earnings in the window | Max 6% each; no adding the week before a report | Earnings gaps of 10% to 20% are common, and most names report during the test window. |
| Cash rule: normal | 0 to 5% cash | Cash earns nothing in a rising market, so we stay invested by default. |
| Cash rule: stress | 25% cash, beta band 0.90 to 1.00 | Stress = S&P 500 below its 200-day average AND 21-day volatility or funding stress above its 80th percentile; the trend and stress signals must agree because volatility alone says nothing about direction. |
| Panic rule | Momentum weight halved | Panic = S&P 500 down over 12 months AND volatility above its 80th percentile; momentum crashes cluster in rebounds after high-volatility declines (Daniel and Moskowitz, 2016). |
| Flag hysteresis | A flag turns off only after two calm weeks | Stops the book flipping in and out of cash on noise. |
| Entry and exit bands | Enter only in the top 15; leave only below rank 30 | Small rank moves do not trigger trades, which limits churn and cost. |
| No-trade band | Skip weight changes under 2 points | Tiny trades cost more than they add. |
| Trim rule | Trim only above 12%, back to 10% | Lets winners run while the score holds; no profit-taking on price alone. |
| Liquidity filter | 20-day dollar volume >= $50M, price > $5, drop the least liquid 10% (Amihud) | Every holding must be tradable at small cost. |
| Position vs volume | Max 1% of 20-day dollar volume | Keeps market impact negligible on a $1M book. |
| Trading costs | Half-spread 5 / 10 / 20 bps by liquidity tier, plus price impact | Costs are charged in every backtest and in the optimizer, as the organizers required; we also rerun at double costs. |

Cash is an explicit line in each portfolio, so weights always sum to 1 (for example 75% stocks and 25% cash under stress).

## Data checks on the real data (fundamentals)

Run of `explore/04_fundamentals_check.py` on the hosted data (data through 2026-09-21).

| Check | Result | What it means for the model |
| --- | --- | --- |
| Column mapping | EPS, sales, EBIT, EBITDA, net income, free cash flow, net debt and gross margin map as guessed. No gross profit, total assets or equity columns exist. | Quality uses the third definition in the code: a percentile blend of gross margin, operating margin, FCF margin and low leverage (net debt / EBITDA). Gross profit / assets and ROE are not possible on this data. |
| Quarterly vs year-to-date | Quarterly (AAPL sales about $90B to $144B per quarter). | Summing the last four quarters gives a correct trailing twelve months. |
| EPS split restatement | Restated. AAPL 2019 EPS 0.55 = reported $2.18 / 4 (2020 split); NVDA 2023 EPS 0.25 = reported about $2.48 / 10 (2024 split). | Earnings yield is consistent across splits, so the split guard is off (`SPLIT_GUARD = False`). |
| When rows become knowable | The filing calendar starts in 2014 and has no period-end or acceptance-time fields, so filings are matched to the next filing date after period end; unmatched rows use a 60-day lag. Share on the lag: 34% of 2018 rows, 13% in 2023, 2% in 2026. GOOGL is not in the calendar. | Point-in-time holds for matched rows (available the day after filing). Known small leak risk: a company that files its annual report 75 to 90 days after year end and is unmatched counts as known up to a month early. |
| Known stocks (2023-06-30) | AAPL and MSFT at the 98th quality percentile. 324 of 1,099 names lost money over the trailing year. | Signs are right. Money-losers now get an earnings yield of 0 (the bottom of the profitable range), so they rank last together; before, one penny stock's extreme loss stretched the scale and flattened the spread among profitable names. |
| Banks and energy cheap | Cannot test: `ds.universe()` has almost no financials (only BR and CHYM match), and JPM, BAC, XOM, CVX and SPY are not in it. Other energy names (DVN, CHRD, CVI) are. | The book is effectively ex-financials. No SPY hedge is possible. |
| Sector codes | `reference_tickers` has no SIC codes. | Sector groups come from return co-movement clusters over the year before the backtest start (`data.return_clusters`), used for sector z-scores and the 30% cap. |

Changes made after this check: gross margin added to the quality blend, split guard turned off, money-losers set to a 0% earnings yield.

## Backtest results

**Status: preliminary.** These numbers come from the v1 model (rung 1: equal-weight top 15 with limits and bands, no cash rule, no optimizer) on a short, favorable window. They are not expected returns, and we do not present them as such.

### v1, January 2023 to February 2026 (about 3 years, costs included)

| | v1 | Equal-weight liquid universe | S&P 500 |
| --- | --- | --- | --- |
| Total return | +169% | +58% | +80% |
| Per year | 37% | 16% | 21% |
| Volatility (per year) | 26% | 18% | 15% |
| Sharpe ratio | 1.34 | 0.93 | 1.34 |
| Max drawdown | 31% | 22% | 19% |
| Median 21-day return | +2.6% | +1.5% | +2.0% |
| Bad month (5th percentile, 21 days) | −8.0% | −6.3% | −4.8% |
| Worst 21 days | −20% | −12% | −12% |
| Turnover per year | 24x | 5x | n/a |
| Costs paid (total) | 7.2% | 2.3% | n/a |

**What it shows.** v1 passes the plan's first gate: it beats the equal-weight liquid universe after costs, on both total return and Sharpe ratio. A typical month (+2.6% median) is ahead of both benchmarks, which is what a mostly total-return score rewards.

**Why we do not trust it yet.**

1. **Return is mostly risk, not proven skill.** v1 earned 37% a year against the S&P 500's 21% at the same Sharpe ratio (1.34). Volatility of 26% against 15% implies a market beta of roughly 1.4 to 1.6 (our estimate, assuming a correlation of 0.8 to 0.9; the regression below will give the real figure). At that beta the market alone explains most of the excess return. A high-beta book in the 2023 to 2025 technology rally would look exactly like this.
2. **The window flatters it.** Three years of a strong, technology-led bull market with no crash like 2020 and no bear market like 2022.
3. **Survivorship bias.** The universe is today's surviving companies. A concentrated, high-momentum book benefits most from never holding stocks that later collapsed and were delisted.
4. **Turnover is too high.** 24x a year means about 45% of the book trades every week, costing about 2.3% a year. Most of it comes from resetting all 15 names to exactly equal weight every week. The plan's 2-point no-trade band should cut this without changing what we hold.
5. **The tail is the real risk in a one-month test.** About 1 month in 20 loses 8% or more, and the worst 21 days lost 20%.

**Verdict.** Promising, not proven. The model picks stocks that went up, and costs do not erase the gain, but we cannot claim skill until the market-exposure part is split out.

### Beta and the plan's limit

The plan targets a beta of 1.10 to 1.20 in normal markets; the preliminary run suggests v1 runs well above that. Decision pending the regression: either enforce the band (less upside in rallies, a smaller worst month) or accept the higher beta because the score is mostly total return, and record the choice here.

### Still to run

| Test | Question it answers | Result |
| --- | --- | --- |
| Full backtest from 2018 | Does it hold up through 2018 Q4, the 2020 crash and the 2022 bear market? | [pending] |
| Beta and alpha vs the S&P 500 | How much of the return is market exposure? | [pending] |
| Random-book (shuffle) test | Do 15 random liquid stocks each week do as well? If so, the scores add nothing. | [pending] |
| One-day signal delay | Does performance fall when signals are a day late? (look-ahead check) | [pending] |
| Double costs | Does it still beat equal weight? | [pending] |
| Drop one factor at a time | Which factors earn their place? | [pending] |
| Five-bucket factor test (`explore/05_factor_buckets.py`) | Does each factor point the right way, in most years? | [pending] |
| Sample holdings (`explore/06_sample_holdings.py`) | Do the names make sense, is any cluster at the 30% cap, does the stress flag fire in 2020 and 2022? | [pending] |
| No-trade band | How much turnover and cost does it remove? | [pending] |

Note: this run may predate the latest quality and value fixes (gross margin in quality, split guard off, money-losers at a 0% earnings yield); rerun before the final numbers.

## Factor direction test (five buckets)

Run of `explore/05_factor_buckets.py` on the real data: 96 month-ends from 2018-01 to 2026-01, liquid names only (about 460 per date), next 21 trading days of return starting the day after the signal. The last six months (to 2026-08) stay held back for the go/no-go.

| Factor | Bucket 1 (low) | Bucket 5 (high) | 5 minus 1 per month | t-stat | Mean IC | Years 5 > 1 | Verdict |
| --- | --- | --- | --- | --- | --- | --- | --- |
| Momentum 12-1 | 1.11% | 1.40% | +0.29% | 0.58 | +0.008 | 4 of 8 | Right sign, weak; positive 2023 to 2025 only |
| Guidance velocity | 1.23% | 1.36% | +0.13% | 0.55 | +0.009 | 4 of 8 | Right sign, weak; positive 2023 to 2025 only |
| Quality | 1.50% | 0.97% | -0.52% | -1.43 | +0.013 | 2 of 8 | Backwards on buckets (2020 and 2025 junk rallies), slightly positive IC: mixed |
| Value | 1.39% | 0.98% | -0.41% | -1.18 | -0.005 | 2 of 8 | Backwards; worked only in 2021 and 2022 |
| Volatility premium | 1.11% | 0.92% | -0.19% | -0.85 | -0.007 | 3 of 8 | Backwards, small |
| Composite (all five) | 1.23% | 1.02% | -0.21% | -0.59 | +0.005 | 3 of 8 | Backwards: the three backward factors cancel the two right ones |

What it means:
- **No factor is distinguishable from zero.** Every |t| is below 1.5; the monthly spread swings about 5 points, so a real 0.3% monthly edge would need decades of data to reach t = 2. No factor is "too good", so there is no sign of a look-ahead leak.
- **Momentum and guidance velocity point the right way** and have worked in each of the last three years. Quality, value and the volatility premium point the wrong way over this period.
- **Survivorship likely tilts quality and value backwards here.** The data holds only today's listed companies, so the weak, unprofitable firms in the history are the ones that survived and recovered; the ones that failed are missing. The test month has no such bias, so the backtest understates quality and value somewhat. It cannot explain the 2020 result, which was a real junk rally.
- **The five-factor composite as written does not beat its own bottom bucket.** Shipping it unchanged would mean shipping a score that tested backwards.

Recommendation to Ezekiel (decision is his, not made in code yet):
1. Composite = momentum + guidance velocity, equal weights (the two factors with the right sign). Keep the panic rule on momentum.
2. Drop value and the volatility premium from the score.
3. Quality: drop from the score, or keep at half weight as a tiebreak only if the backtest after costs improves; do not tune further.
4. This choice is made on the same 2018 to 2026 sample it will be backtested on, so the backtest will flatter it. The six held-back months are the honest check: rerun this script with `--include-holdback` only at the go/no-go.
