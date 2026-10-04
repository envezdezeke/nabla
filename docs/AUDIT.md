# nabla audit

How the model decides, why each rule exists, and what we know it cannot prove. Every threshold below was fixed before testing; changes made after a test are logged next to that test.

**Status (current build).** The shipped model (rungs 1 and 3 of the plan's ladder) is built and backtested: equal-weight top 15 by the factor score, with the liquidity filter, caps, entry/exit bands and the 2-point no-trade band (`config/model.json`, version `v1.2`: four factors, after the volatility premium was dropped on the drop-one-factor test, plus the stress cash dial; the panic rule was tested and rejected). The optimizer is not built. Sections marked [pending] are filled in as those layers land.

## Contents
1. Strategy in plain English
2. The factors
3. Portfolio limits
4. Risk rule: when and why we raise cash
5. Point-in-time discipline
6. Organizer answers
7. Known limits
8. What we tried and cut
9. Evidence: data checks, factor test, crowding, backtests

## 1. Strategy in plain English

Every week we rank about 460 liquid US stocks on four simple, published ideas (five in the original design; one was dropped after testing) about which stocks tend to do better over the next month, and hold the 15 best-ranked, roughly equal weight. A stock enters only if it ranks in the top 15 and leaves only if it falls below 30th, so small rank wiggles do not cause trades. When the market is falling and stressed, the book moves 25% to cash. Over 2018 to February 2026 this returned 17.6% a year after costs against 12.4% for the S&P 500, with a smaller worst drawdown (30% against 34%); section 9 has the full results and their caveats.

Why this design: the judges score us on about 21 trading days after our data ends. Over one month, luck dominates any model, so we chose a few robust, well-documented signals and strict risk limits over a complex model that would fit the past and fail the month. Everything is a fixed rule: the same data always gives the same portfolio, which is exactly what the replay tests.

The output of each weekly decision is a complete target portfolio whose weights, including an explicit cash line, sum to 1.

## 2. The factors

Each factor is computed from data available at the decision time, cleaned the same way (extremes trimmed at the 1st and 99th percentile, compared within groups of similar stocks, capped at 3 standard deviations), and added with equal weight. A stock missing a factor gets a neutral 0 for it, and the total is divided by the fixed total weight, so a stock with fewer factors is not favored. Four factors carry weight in v1.1; the fifth (volatility premium) is still computed but has weight 0.

**Momentum (12-1).** Return from 12 months ago to 1 month ago, adjusted for splits. Stocks that rose over the past year tend to keep rising for a while, one of the most replicated results in finance (Jegadeesh and Titman, 1993). The most recent month is skipped because very short-term winners tend to reverse. Momentum is known to crash in sharp rebounds after market falls, which is why the panic rule halves its weight (section 4).

**Guidance velocity.** How quickly a company's outlook is being revised, from the data's `guidance_range_velocity` field. When management raises or tightens guidance, analysts and investors are slow to fully adjust, so the stock tends to keep drifting in the same direction. This is the one factor built from the hackathon's own data rather than prices or filings.

**Quality.** How profitable and financially sound the business is: a percentile blend of gross margin, operating margin, free-cash-flow margin and low leverage (net debt to EBITDA), from filed financials, needing at least two of the four. Profitable, low-debt firms have historically earned more than their risk suggests, and they hold up better in sell-offs. The data has no total assets or equity, so the textbook measures (gross profit to assets, return on equity) are not possible; the code would use them if they existed.

**Value.** Trailing twelve-month earnings per share divided by price (earnings yield), from filed results. Cheap stocks have historically outperformed expensive ones over long periods. Money-losing companies get a 0% yield, so they rank last together instead of one extreme loss distorting the scale.

**Volatility premium (dropped in v1.1, weight 0).** Minus the log of option-implied volatility over the past 21 days' realized volatility. When options price much more risk than the stock has actually shown, the stock has tended to underperform, and the reverse (Bali and Hovakimyan, 2009, on the spread between realized and implied volatility; citation to be verified).

**How they tested.** On 2018 to 2026, momentum and guidance velocity pointed the right way but weakly; quality, value and the volatility premium pointed the wrong way, and no factor was statistically distinguishable from zero (section 9). The drop-one-factor backtest then decided: removing the volatility premium raised return from 13.7% to 19.2% a year and cut turnover from 21x to 7x, because its daily-moving inputs reshuffled the book every week; removing any of the other four lowered return, so they stay (decision log at the end). This choice used the same sample the backtest reports, so v1.1's backtest is flattered; the held-back months are the honest check.

## 3. Portfolio limits

We set these ourselves (the organizers left limits to each team). The score is mostly total return, so the book leans aggressive, but every rule caps a specific way to lose.

| Rule | Value | Reason |
| --- | --- | --- |
| Number of stocks | 15 | Concentrated enough to stand out from diversified books; one bad pick is survivable. |
| Max per name | 10% | One blowup (a 30% to 50% drop) costs the book about 3 to 5 points, not the month. |
| Max per sector group | 30% | Stops the book from becoming a single-theme bet. The data has no SIC codes, so groups are 10 clusters of stocks that move together (see data checks). |
| Beta band (normal) | 1.10 to 1.20 | Enough market exposure to chase total return, without becoming a pure leveraged-market bet. |
| Names reporting earnings in the window | Max 6% each; no adding the week before a report | Earnings gaps of 10% to 20% are common, and most names report during the test window. |
| Cash rule: normal | 0 to 5% cash | Cash earns nothing in a rising market, so we stay invested by default. |
| Cash rule: stress | 25% cash | Stress = S&P 500 below its 200-day average AND 21-day volatility above its 80th percentile; the trend and stress signals must agree because volatility alone says nothing about direction. |
| Panic rule | Tested, not shipped | Halving momentum after high-volatility declines (Daniel and Moskowitz, 2016) cost about 3% a year on our data without reducing drawdown. |
| Flag hysteresis | A flag turns off only after two calm weeks | Stops the book flipping in and out of cash on noise. |
| Entry and exit bands | Enter only in the top 15; leave only below rank 30 | Small rank moves do not trigger trades, which limits churn and cost. |
| No-trade band | Skip weight changes under 2 points | Tiny trades cost more than they add. |
| Trim rule | Trim only above 12%, back to 10% | Lets winners run while the score holds; no profit-taking on price alone. |
| Liquidity filter | 20-day dollar volume >= $50M, price > $5, drop the least liquid 10% (Amihud) | Every holding must be tradable at small cost. |
| Position vs volume | Max 1% of 20-day dollar volume | Keeps market impact negligible on a $1M book. |
| Trading costs | Half-spread 5 / 10 / 20 bps by liquidity tier, plus price impact | Costs are charged in every backtest and in the optimizer, as the organizers required; we also rerun at double costs. |

Cash is an explicit line in each portfolio, so weights always sum to 1 (for example 75% stocks and 25% cash under stress).

## 4. Risk rule: when and why we raise cash

The model reads two flags from the S&P 500 at each weekly decision, using only data up to that day.

| Flag | Turns on when | What it changes | Why |
| --- | --- | --- | --- |
| Stress | S&P 500 below its 200-day average AND 21-day volatility above its 80th percentile of all history so far | 25% cash (shipped in v1.2) | Falling markets with high volatility are where large losses happen. Trend and stress must agree: volatility alone says nothing about direction, and a dip below the average alone is often noise. |
| Panic (tested, not shipped) | S&P 500 down over 12 months AND 21-day volatility above its 80th percentile | Would halve the momentum weight | Momentum crashes cluster in rebounds after high-volatility declines (Daniel and Moskowitz, 2016). On our data it cost about 3% a year and did not reduce drawdown, so it is off (decision log). |

A flag turns off only after two straight weeks with its condition false, so the book does not flip in and out of cash on noise. Percentiles use expanding history only, and the whole flag history is recomputed from data at each decision, so no stored state is needed.

Cash is an explicit line in the portfolio (`CASHHOLDING`), so under stress a decision reads 75% stocks plus 25% cash, summing to 1.

**Status:** the cash dial is live (v1.2). The stress flag was on in 18% of weeks from 2018 to 2026 (16 weeks in 2020, 44 in 2022). Against the same book without it: return 19.2% to 17.4% a year, Sharpe unchanged at 0.82, maximum drawdown 35% to 30%, beta 1.11 to 0.96 (decision log). Two deviations from the plan: funding stress is left out so the backtest and the live book use identical inputs, and the low-beta swap under stress is not built.

**Why it matters for us:** in a calm month the dial changes nothing, so the judged book is the same as without it; it is insurance against a sell-off inside the 21 days. It re-invests only after two calm weeks, so it gives up part of sharp rebounds (2020: +25% against +27% for equal weight).

## 5. Point-in-time discipline

The replay calls our model one decision at a time, so any use of future data would show up as a backtest the live model cannot repeat. Rules we follow:

- **Fundamentals by filing date.** Each quarterly row becomes usable the day after its filing date (the filing calendar has no acceptance times). Rows that cannot be matched to a filing use a conservative 60-day lag after period end. Share on the lag: 34% of 2018 rows, 13% in 2023, 2% in 2026. EPS in the data is already restated for later splits, which keeps earnings yield consistent but is not exactly what an investor saw on the day; the ratio is unaffected.
- **Prices.** Each decision uses data through the prior close only (`signal_lag = 1`). The current backtest then trades at the decision day's close, matching the judges' own `statevector.backtest` engine; the replay format trades at the next day's open, and the research backtest moves to next-open fills before the final numbers [pending].
- **No hidden clock.** The decision function takes the information cutoff as its input and never reads today's date or the last date in the data.
- **Frozen model.** All settings live in `config/model.json`; nothing is refitted during the replay. The sector clusters are fitted once on the year before the backtest starts.
- **Holdback.** The last six months of data are not used for any choice until the final go/no-go.
- **Costs.** Every backtest charges half-spread by liquidity tier plus price impact that grows with trade size; we also rerun at double costs.

**Leak tests** (`scripts/audit.py`):

| Test | What a leak would look like | Result |
| --- | --- | --- |
| Five-bucket factor test | A factor that is "too good" (very high t-stat or monotone in every year) | Passed: no factor stands out; every t-stat below 1.5 |
| One-day signal delay | Performance improves with older data | Passed: return falls from 17.6% to 13.7% a year |
| Random books | Random 15-stock books do as well as ours | Passed: beats 5 of 5 (random books 8.0% to 14.3% a year) |
| Drop one factor | One factor carries all of the return | Done: no single factor carries it; removing momentum or quality costs the most (13.7% to 7.3% and 8.5% a year) |

## 6. Organizer answers

What we were told by the organizers during the event, and how the model follows it. [Add times; questions still open are in `docs/workshop_questions.md`.]

| We asked | Answer | What we did |
| --- | --- | --- |
| What is submitted? | A chronological series of target portfolios, one complete record per decision, generated by replaying our frozen model through the holdout one step at a time (proposed format). | One deterministic decision function; the backtest calls the same function, so backtest = replay. |
| Can we hold cash? | Yes; weights always sum to 1 including cash. | Cash is its own line (`CASHHOLDING`), not the leftover. |
| How are we scored? | Mostly total return; Sharpe and drawdown still matter. | Aggressive default (0 to 5% cash), with a stress rule for drawdowns. |
| Costs and limits? | Transaction costs must be in the model; teams set their own limits. | Cost model in every backtest and decision; limits table in section 3. |
| How often can we trade? | Weekly rebalancing allowed. | Weekly decisions, with bands to limit churn. |
| What is the test period? | The 30 days after our data ends (about 21 trading days). | Favor robust signals; see known limits. |

## 7. Known limits

- **One month is mostly noise.** A concentrated 15-stock book swings roughly 6% to 8% in a typical month (our estimate). A real edge of a few tenths of a percent a month cannot be told from luck in one month: a good month would not prove the model and a bad one would not disprove it.
- **Survivorship bias.** The universe is today's listed companies. Stocks that collapsed and were delisted are missing from the history, which flatters any backtest, especially a concentrated one. It likely also makes quality and value look worse than they are, since the weak firms in the history are the ones that survived. The live test month has no such bias.
- **A narrow universe.** The universe has almost no financials and no energy majors (JPM, BAC, XOM, CVX are absent) and no SPY, so the book is effectively ex-financials and cannot hedge with an index.
- **Few stress episodes.** The cash rule rests on about three: 2018 Q4, 2020 and 2022. Its thresholds are priors fixed before testing, not fitted.
- **Skill is not proven.** Beta is about 1 and alpha is +5.7% a year, but with t = 1.27 it is not statistically significant, and the factor and rule choices were made on the same sample (section 9).
- **Costs are modeled, not measured.** Hence the double-cost rerun.
- **Unclustered names.** 431 newer names lack a year of history before the 2018 cluster fit and sit in one "other" group that the 30% cap does not cover (up to 47% of the book in 2024); refitting yearly would fix this. The live book fits its clusters on the year before its own start date, so its groups differ from the backtest's.
- **Signals decay fast.** A one-day delay cuts return from 17.6% to 13.7% a year, so the replay's next-open fills may cost some return; that test is still to run.

## 8. What we tried and cut

The plan went through five versions. Version 4 added several advanced pieces; a red-team review cut them in version 5 because each added risk of overfitting or failure without evidence it would help over 21 days.

| Idea | Why it was cut |
| --- | --- |
| Reinforcement-learning bandit choosing between strategies | Too few independent months to learn from (about 100 since 2018); it would mostly fit noise, and it adds state that is hard to replay deterministically. |
| Put option overlay (portfolio insurance) | SPY and its options are not in the universe, and an option leg might not pass the judges' checker; premiums are a steady drag in a test scored on return. |
| Hidden Markov model for market regimes | Few regime changes to fit; rule-based flags are transparent, fixed before testing, and equally good at the job on so few episodes. |
| Partial trading toward targets | Replaced by bands and a no-trade threshold, which control cost more simply. |
| Logistic calibration of flags | Kept as a chart only; not part of the decision. |

Still in the plan but not yet built: the mean-variance optimizer with an equal-weight anchor (rung 4). It ships only if it beats the simpler rung after costs.

## 9. Evidence

### Data checks on the real data (fundamentals)

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

### Factor direction test (five buckets)

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

**Decision: all five factors stay for now.** Following plan v5, we add the remaining layers first (panic momentum weight, cash rule, optimizer), then remove what does not earn its place using the drop-one-factor backtest on the full model, rather than dropping factors on this single test. When we do drop factors, the choice is made on the same 2018 to 2026 sample it is backtested on, so the backtest will flatter it; the six held-back months are the honest check (rerun this script with `--include-holdback` only at the go/no-go).

**Known limitation found here.** 431 of about 1,250 names are unclustered ("other") because they lack a full year of returns before the 2018 cluster fit; they are z-scored together and uncapped. Refitting the clusters each year on past data only would fix this.

### Crowding check

Run of `explore/07_crowding_check.py --history`: our book against a naive momentum book, the 20 liquid names with the highest plain 12-month return (what a simple momentum-chasing team would hold). Crowded means more than half of our 15 names are in that list.

| | Result |
| --- | --- |
| Latest book (2026-09-21, last date in the data; v1.1) | 2 of 15 overlap (13%): MU and WDC, ranked 1st and 5th on our score |
| Earlier book (2026-02-20; v1) | 2 of 15 overlap: STX and ARWR, both ranked 11th or worse |
| Month-end history, 2018 to 2026 (top 15 by score, no bands) | Median 3 of 15, highest 8; average by year 1.5 (2026) to 4.4 (2024) |

What it means:
- **We are not crowded.** Only once in 98 month-ends did more than half the book overlap, so a momentum reversal would not hit us harder than the market just because other teams chase the same names.
- **The opposite question matters more.** Several holdings fell over the past year (WEN -48%, PYPL -47%, GPN -23%, SPGI -23%). Momentum is one of five equal weights, so value, quality and guidance pull in beaten-down names. That is a choice, not an accident, but the bucket test found value and quality backwards on this sample, so the drop-one-factor run decides whether it stays.
- **No swap needed.** On the latest date the two overlap names are among our strongest picks, not marginal ones, so the plan's swap rule does not apply. With 2 of 15 the gain from any swap is small, so we do not add a swap rule.
- **Correction.** The first run of this check stopped at 2026-02-20 because of a cache bug: a year of prices saved by an earlier backtest was never refreshed. It is fixed in `data._cached_years` (with a test); the live book was affected the same way.

### Backtest results

These numbers are the shipped model, v1.2, replayed weekly from January 2018 to February 2026 with the plan's trading costs charged on every trade (`scripts/run_backtest.py`, `scripts/audit.py`). The six months after that stay held back for the go/no-go. They are not expected returns: the factor and rule choices were made on this same sample, and the universe is today's listed companies.

![Growth of $1](img/growth.png)

| | nabla v1.2 | Equal-weight liquid universe | S&P 500 |
| --- | --- | --- | --- |
| Return per year | 17.6% | 11.5% | 12.4% |
| Total return | +272% | +142% | +158% |
| Volatility per year | 22.6% | 21.5% | 19.5% |
| Sharpe ratio | 0.83 | 0.61 | 0.70 |
| Max drawdown | 29.9% | 38.9% | 33.9% |
| Median 21 days | +1.5% | +1.6% | +1.8% |
| Bad month (5th percentile, 21 days) | -8.1% | -8.0% | -7.2% |
| Worst 21 days | -28.8% | -38.2% | -33.0% |
| 2018 Q4 | -11.8% | -15.2% | -14.0% |
| 2020 | +25.4% | +27.1% | +16.3% |
| 2022 | -18.4% | -19.5% | -19.4% |
| Turnover per year | 7.5x | 4.5x | n/a |
| Costs paid (total, 8 years) | 6.8% | 5.7% | n/a |

![Drawdowns](img/drawdown.png)

**What it shows.** v1.2 beats the equal-weight universe and the S&P 500 on return and Sharpe ratio after costs, with a smaller maximum drawdown than either. It lost less in 2018 Q4 and 2022, the stress periods where the cash dial was on. A typical month is slightly below the benchmarks (median +1.5% against +1.6% and +1.8%); the gain comes from smaller losses in sell-offs and a stronger 2023 to 2025.

**Robustness** (`scripts/audit.py`; random-book rows from the v1.1 run, since random books ignore the cash dial):

| Test | Result | What it means |
| --- | --- | --- |
| Market beta and alpha | Beta 0.96, alpha +5.7% a year (t = 1.27) | About market-level exposure on average (the cash dial lowers it in stress); the alpha is positive but not statistically significant. |
| Random books (5 books of 15 random liquid names, same bands, caps and costs) | Our model beats all 5: random books earned 8.0% to 14.3% a year | The scores add something beyond holding 15 liquid stocks under our rules. |
| One-day signal delay | 13.7% a year (vs 17.6%) | Performance falls with older data and does not rise, which is what a model without look-ahead should show. The drop is large for a weekly model: much of the return arrives within a day of a signal (fresh filings and guidance changes), so execution timing matters and the next-open fill test is a priority. |
| Double trading costs | 16.6% a year (vs 17.6%) | Still ahead of the equal-weight universe (11.5%). |
| No-trade band and dropping the volatility premium | Turnover 21x to 7.5x a year; costs about 2.2% to 0.8% a year (v1 to v1.2, 2018 to 2026) | Most of the original cost came from resetting weights weekly and from a fast-moving factor. |

#### Market exposure and the plan's beta band

The plan targets a beta of 1.10 to 1.20 in normal markets. The shipped book is already inside that band without forcing it: rung 1 (no cash dial) measured 1.11. With the cash dial, beta over the whole period is about 0.96 because a quarter of the book is cash in stress weeks. Our earlier guess of 1.4 to 1.6, from the 2023 to 2026 run's volatility, was wrong; that window's excess return came from stock selection in a strong market, not leverage. No beta constraint is added.

![Cluster concentration](img/clusters.png)

**Concentration.** For names inside the 10 return clusters, the 30% cap holds (largest cluster: median 21% of the book, never above 30%). Names without a full year of history before the 2018 cluster fit are "unclustered" and uncapped; they reached 47% of the book in 2024. Refitting the clusters each year on past data would fix this (see known limits).

#### Earlier runs (superseded)

The first v1 runs (five factors, no no-trade band) reported 37% a year on 2023 to 2026 with 24x turnover, and 13.7% to 15.2% a year on 2018 to 2026 with about 2.5% a year in costs. The drop-one-factor and regime ladders in the decision logs below explain the changes from v1 to v1.2.

#### Status of every test

| Test | Question it answers | Result |
| --- | --- | --- |
| Full backtest from 2018 | Does it hold up through 2018 Q4, the 2020 crash and the 2022 bear market? | Done: lost less than both benchmarks in 2018 Q4 and 2022; lagged equal weight in 2020 |
| Beta and alpha vs the S&P 500 | How much of the return is market exposure? | Done: beta about 1.1 without the dial, 0.96 with it; alpha positive, not significant |
| Random-book test | Do 15 random liquid stocks each week do as well? | Done: beats 5 of 5 |
| One-day signal delay | Does performance fall when signals are a day late? (look-ahead check) | Done: falls (17.6% to 13.7%), no rise; signals decay fast |
| Double costs | Does it still beat equal weight? | Done: yes |
| Drop one factor at a time | Which factors earn their place? | Done: volatility premium dropped (v1.1); the other four stay |
| Regime ladder | Do the panic rule and the cash dial earn their place? | Done: panic rejected, cash dial shipped (v1.2) |
| Five-bucket factor test | Does each factor point the right way, in most years? | Done: no factor is reliable alone over 2018 to 2026 |
| Sample holdings (`explore/06_sample_holdings.py`) | Do the names make sense; does the stress flag fire in 2020 and 2022? | Done: recognizable, liquid names (one under $10: CZR in March 2020); stress on in March 2020 and June 2022 (16 weeks in 2020, 44 in 2022) |
| Crowding check | Do we just hold last year's biggest winners? | Done: no, 2 of 15 overlap |
| Next-open fills | Do results hold when trades fill at the next open, as in the replay? | [pending] |
| Held-back six months | The honest out-of-sample check | Untouched until the go/no-go |


## Decision log: volatility premium dropped (v1.1)

The drop-one-factor backtest on the full v1 book (2018 to the six held-back months, plan costs, 2-point no-trade band) ran `scripts/audit.py`:

| Variant | Annual return | Sharpe | Alpha vs SPX (t) | Turnover / year | Costs paid |
| --- | --- | --- | --- | --- | --- |
| v1, all five | 13.7% | 0.65 | +1.1% (0.24) | 21x | 17.8% |
| without volatility premium | 19.2% | 0.82 | +5.7% (1.24) | 7x | 6.6% |
| without momentum | 7.3% | 0.42 | -4.4% | 23x | 20.4% |
| without quality | 8.5% | 0.45 | -3.5% | 22x | 19.6% |
| without guidance velocity | 11.7% | 0.56 | -0.7% | 23x | 20.3% |
| without value | 11.8% | 0.55 | -0.6% | 24x | 19.3% |

**Decision:** the volatility premium weight is 0 (`config/model.json`, version `v1.1`). The reason is mechanical as well as statistical: it is built from 21-day realized and 30-day implied volatility, which move every day, so it reshuffled the top 15 weekly and tripled turnover; the five-bucket test also found it pointing the wrong way. The other four stay because removing each one lowered return.

**Caveat:** the factor was removed using the same 2018 to 2026 sample the backtest reports, so v1.1's backtest is flattered. The six held-back months are the honest check at the go/no-go. Alpha is still not statistically significant (t = 1.24).


## Decision log: regime ladder (v1.2)

`scripts/audit.py --only ladder`, 2018 to the six held-back months, plan costs, no-trade band, four-factor composite. Flags from SPX only: stress on in 18% of weeks, panic in 12%.

| Variant | Annual return | Sharpe | Max drawdown | Beta | Bad month (5th pct) | Alpha (t) |
| --- | --- | --- | --- | --- | --- | --- |
| Rung 1 (v1.1) | 19.2% | 0.82 | 35.1% | 1.11 | -8.8% | 5.7% (1.24) |
| Rung 2: + panic momentum weight | 16.2% | 0.72 | 35.8% | 1.10 | -9.0% | 3.1% (0.69) |
| Rung 3: + panic + 25% stress cash | 15.2% | 0.74 | 30.5% | 0.96 | -8.1% | 3.7% (0.82) |
| Cash only: + 25% stress cash | 17.4% | 0.82 | 29.9% | 0.96 | -8.2% | 5.5% (1.23) |

**Panic rule rejected.** Halving momentum in panic cost 3% a year and did not reduce drawdown; on this sample momentum recovered quickly after panic periods.

**Shipped: cash only (v1.2).** Same Sharpe and alpha as rung 1, 5 points less maximum drawdown, beta 0.96, for about 1.8% a year less return (the dial waits two calm weeks before re-investing, so it misses part of rebounds). It changes nothing unless the stress flag is on, so in a calm judged month the book is identical to rung 1; it is insurance against a sell-off inside the 21 days. This does not meet the plan's strict "beat the previous rung on return" rule; the team chose it for the drawdown and beta at equal Sharpe.

Deviation from plan v5: stress uses SPX volatility only (funding stress left out so backtest and live use identical inputs), and the stress preset's low-beta swap is not built.
