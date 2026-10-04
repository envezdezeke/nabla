# Judge questions: short answers

One or two sentences each, for the Q&A after the pitch. Numbers come from `docs/AUDIT.md` (v1.3, weekly replay, costs included). Headline: Jan 2018 to the data cutoff (Aug 2026). Tests marked "development" ran on Jan 2018 to Feb 2026, before the six held-back months were opened.

**One month is mostly luck. How is this skill?**
We can't prove skill in one month and don't claim to. We claim a process: published signals, rules fixed before testing, and an eight-and-a-half-year weekly replay that beat the S&P and equal weight after costs (14.9% vs 13.0% and 12.1% a year), 16 of 20 random portfolios run under the same rules, and six held-back months we opened once (+19.7%). In any one month we beat the S&P in about half of past windows (49%). The edge is not statistically proven (alpha +2.5% a year, t = 0.6).

**Did you test it on data it never saw?**
Yes. We built everything on Jan 2018 to Feb 2026 and kept the last six months untouched. Opened once at the end: +19.7%, Sharpe 1.83, worst drop 7.8%. Six months is short, so it's encouraging, not proof.

**How do you know there's no look-ahead?**
Every decision uses data through the prior close, filings count from the day after they're filed, and the decision function takes the cutoff as input and never reads today's date. Fed data one day late, return falls (14.2% to 12.4%) rather than rising.

**Why not machine learning or RL?**
About 100 independent months since 2018, and even simple signals can't be told from luck on them, so a flexible model would learn noise. Fixed rules are transparent and give the same answer on every replay.

**What's your market exposure?**
Beta about 1.0 over the whole backtest; the cash rule lowers it in stress. The book entering the judged month is hotter, about 1.65, because momentum pulled it into chip and memory names (about a quarter of the book). We state that rather than hide it.

**Why cash instead of puts?**
SPY and its options aren't in our universe, and puts cost premium every month in a test scored mostly on return. Cash costs nothing and is an explicit line in every portfolio.

**What happens if the market crashes in week 1?**
We take most of the first drop: the stress rule protects against drawn-out declines like 2022, not a one-day gap. At the next weekly check, if the flag is on, the book moves 25% to cash, and no stock can be more than 10%.

**Which signal matters most?**
Momentum: on the development period, without it return falls from 14.2% to 10.4% a year. Value is next (11.3%). Quality and guidance didn't help on this sample, but we didn't retune after seeing that, because choosing signals on the same data would just fit the past.

**Why did your number drop from an earlier 17.6%?**
The old figure depended on one lucky way of grouping similar stocks. We switched to a stable grouping refit each January on past data only and reported the honest result, 14.2%, instead of keeping the flattering one.

**Isn't one good year doing all the work?**
2024 (+48%) carries a lot of it, and we lagged from 2020 to 2023. We beat the S&P in 6 of 9 years and stay ahead of both benchmarks from every start year, 2018 to 2022.

**Does trading at the next open hurt you?**
A little: on the development period, 13.2% a year against 14.2% with close fills, still ahead of the S&P (12.4%).

**How sensitive is it to your choices?**
We changed 24 settings one at a time (portfolio size, exit rank, cash level, group cap, liquidity floor, random signal weights): 22 of 24 still beat the S&P, 12.4% to 18.7% a year. On the development period, double costs gave 13.1%, next-open fills 13.2%, data one day late 12.4% (level with the S&P). The edge is real but thin.

**Why hold any cash if you are scored on total return?**
Only when the stress rule fires, at 25%. It cut our worst drop from about 40% to 34%; in a calm month it changes nothing.

**Why equal weight instead of an optimizer?**
Optimizers rarely beat equal weight out of sample because their return estimates are mostly noise. We planned one; it wasn't ready, so we ship the simpler, tested version.

**How do you handle transaction costs?**
Every trade pays half a spread of 5, 10 or 20 basis points by liquidity plus a size-based impact cost: about 0.9% a year. At double the costs we still beat the S&P.

**Why 15 stocks?**
Fewer and one bad pick can sink the month; more and we just track the index. At about 6.7% each, one blowup costs 2 to 3 points. We fixed 15 before testing rather than tuning it.

**Why these four signals?**
Each has decades of research and an economic reason, and they look at different things: trend, company news, business strength and price. We chose them before testing and kept them as chosen.

**Why 25% cash?**
Enough to matter in a sell-off, small enough to stay mostly invested when the signal is wrong or the market rebounds fast. Set before testing; we tested on versus off, not other levels.

**Why 10% per stock and 30% per group?**
Each caps a way to lose: no single stock can sink us (a 50% drop costs at most 5 points), and no single theme can (at most 4 of 15 stocks that move together).

**What would you do with more time?**
Get data that includes delisted companies to remove survivorship bias, test over more crashes, measure real trading costs, and test other portfolio sizes and cash levels.
