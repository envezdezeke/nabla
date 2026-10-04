# nabla audit

How the model decides, why each rule exists, and what we know it cannot prove. Every threshold below was fixed before testing; changes made after a test are logged next to that test.

**Status (current build).** Rung 1 of the plan is built and backtested: equal-weight top 15 by the factor score, with the liquidity filter, caps, entry/exit bands and the 2-point no-trade band (`config/model.json`, version `v1.1`: four factors, after the volatility premium was dropped on the drop-one-factor test). The stress/panic flags are coded and tested (`src/nabla/regime.py`) but not yet wired into the book; the optimizer is not built. Sections marked [pending] are filled in as those layers land.

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

Every week we rank about 460 liquid US stocks on four simple, published ideas (five in the original design; one was dropped after testing) about which stocks tend to do better over the next month, and hold the 15 best-ranked, roughly equal weight. A stock enters only if it ranks in the top 15 and leaves only if it falls below 30th, so small rank wiggles do not cause trades. When the market is falling and stressed, the plan moves 25% of the book to cash and lowers its market exposure.

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
| Number of stocks | 15 (12 to 18 once the optimizer ships) | Concentrated enough to stand out from diversified books; one bad pick is survivable. |
| Max per name | 10% | One blowup (a 30% to 50% drop) costs the book about 3 to 5 points, not the month. |
| Max per sector group | 30% | Stops the book from becoming a single-theme bet. The data has no SIC codes, so groups are 10 clusters of stocks that move together (see data checks). |
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

## 4. Risk rule: when and why we raise cash

The model reads two flags from the S&P 500 at each weekly decision, using only data up to that day.

| Flag | Turns on when | What it changes | Why |
| --- | --- | --- | --- |
| Stress | S&P 500 below its 200-day average AND (21-day volatility OR funding stress above its 80th percentile of all history so far) | 25% cash, beta band 0.90 to 1.00, highest-beta names swapped for lower-beta | Falling markets with high volatility are where large losses happen. Trend and stress must agree: volatility alone says nothing about direction, and a dip below the average alone is often noise. |
| Panic | S&P 500 down over 12 months AND 21-day volatility above its 80th percentile | Momentum weight halved | Momentum crashes cluster in rebounds after high-volatility declines (Daniel and Moskowitz, 2016); 2009 and 2020 are the classic cases. |

A flag turns off only after two straight weeks with its condition false, so the book does not flip in and out of cash on noise. Percentiles use expanding history only, and the whole flag history is recomputed from data at each decision, so no stored state is needed.

Cash is an explicit line in the portfolio (`CASHHOLDING`), so under stress a decision reads 75% stocks plus 25% cash, summing to 1.

**Status:** flags coded and unit-tested; wiring into the book (rungs 2 and 3 of the ablation ladder) is in progress. Results: [pending].

**Why it matters for us:** in the full backtest, v1 lost 30% in 2022 against the S&P 500's 19%, a momentum-heavy book in a falling market. The stress flag should be on for much of 2022.

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
| One-day signal delay | Performance improves or barely changes with older data | [pending] |
| Random books | Random 15-stock books do as well as ours | [pending] |
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
- **Return is mostly market exposure so far.** v1 beats equal weight on return but its Sharpe ratio is close to the S&P 500's, so much of the gain is risk, not proven skill (section 9).
- **Costs are modeled, not measured.** Hence the double-cost rerun.
- **Unclustered names.** 431 newer names lack a year of history before the cluster fit and sit in one "other" group that the 30% cap does not cover; refitting yearly would fix this.

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

**Status: preliminary.** These numbers come from the v1 model (rung 1: equal-weight top 15 with limits and bands, no cash rule, no optimizer). They are not expected returns, and we do not present them as such. Ablation ladder (each rung must beat the previous after costs): rung 1 [this run], rung 2 panic weight [pending], rung 3 cash rule [pending], rung 4 optimizer [pending].


#### Full run, January 2018 to February 2026 (v1 with the 2-point no-trade band, costs included)

Note: the audit run in the decision log below reports 13.7% a year for the same v1 configuration; the two runs differ in setup (to be reconciled before final numbers). The v1.1 audit run: 19.2% a year, Sharpe 0.82, alpha +5.7% a year (t = 1.24), turnover 7x a year, 6.6% costs in total; its drawdown and year-by-year rows are [pending].

| | v1 | Equal-weight liquid universe | S&P 500 |
| --- | --- | --- | --- |
| Per year | 15.2% | 11.5% | 12.4% |
| Sharpe ratio | 0.67 | 0.61 | 0.70 |
| Max drawdown | 36% | 39% | 34% |
| Costs paid | about 21% in total (about 2.5% a year) | | |
| 2018 Q4 | -8% | -14% to -15% (both benchmarks) | |
| 2020 | +15% | +27% | +16% |
| 2022 | -30% | | -19% |

What it shows: v1 beats equal weight after costs over the full period and lost less in 2018 Q4, but its Sharpe ratio is below the S&P 500's, it lagged the 2020 rebound, and 2022 is the worst year (a momentum-heavy book in a falling market). Costs take most of the edge over equal weight. The panic weight and cash rule target 2022 and 2020; turnover after the no-trade band: [pending].

#### v1, January 2023 to February 2026 (about 3 years, costs included)

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

#### Beta and the plan's limit

The plan targets a beta of 1.10 to 1.20 in normal markets; the preliminary run suggests v1 runs well above that. Decision pending the regression: either enforce the band (less upside in rallies, a smaller worst month) or accept the higher beta because the score is mostly total return, and record the choice here.

#### Still to run

| Test | Question it answers | Result |
| --- | --- | --- |
| Full backtest from 2018 | Does it hold up through 2018 Q4, the 2020 crash and the 2022 bear market? | Done: see the full run above |
| Beta and alpha vs the S&P 500 | How much of the return is market exposure? | [pending] |
| Random-book (shuffle) test | Do 15 random liquid stocks each week do as well? If so, the scores add nothing. | [pending] |
| One-day signal delay | Does performance fall when signals are a day late? (look-ahead check) | [pending] |
| Double costs | Does it still beat equal weight? | [pending] |
| Drop one factor at a time | Which factors earn their place? | Done: volatility premium dropped (v1.1); the other four stay (decision log below) |
| Five-bucket factor test (`explore/05_factor_buckets.py`) | Does each factor point the right way, in most years? | Done: no factor is reliable over 2018 to 2026 (see the factor test above) |
| Sample holdings (`explore/06_sample_holdings.py`) | Do the names make sense, is any cluster at the 30% cap, does the stress flag fire in 2020 and 2022? | [pending] |
| No-trade band | How much turnover and cost does it remove? | [pending] |
| Crowding check (`explore/07_crowding_check.py`) | Do we just hold last year's biggest winners? | Done: no, 2 of 15 overlap (see below) |

Note: this run may predate the latest quality and value fixes (gross margin in quality, split guard off, money-losers at a 0% earnings yield); rerun before the final numbers.


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
