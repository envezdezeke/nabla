# Judge questions: short answers

One or two sentences each, for the Q&A after the pitch. Numbers come from `docs/AUDIT.md` (v1.2, 2018 to Feb 2026, costs included).

**One month is mostly luck. How is this skill?**
It isn't provable in one month, and we don't claim it: what we claim is a process, made of published signals, fixed rules and an eight-year weekly replay that beat the equal-weight universe and the S&P 500 after costs (17.6% vs 11.5% and 12.4% a year). It also beat all 20 random books (15 random liquid stocks under the same rules: median 10% a year, best 15%), so the scores add return, though alpha (+5.7% a year, t = 1.3) is not statistically significant and one year, 2024, carries much of the edge.

**How do you know there's no look-ahead?**
Every decision uses data through the prior close only, fundamentals count from the day after their filing date (60 days after period end when no filing matches), and the decision function takes the cutoff time as its input and never reads today's date. No factor was suspiciously good in our five-bucket test (every t-stat below 1.5), and when we feed the model data one day late, return falls (17.6% to 13.7% a year) rather than rising.

**Why not machine learning or RL?**
We have about 100 independent months since 2018, and even simple factors can't be told apart from zero on that sample, so a flexible model would learn noise and look great only in the backtest. Fixed rules are transparent, give the same answer on every replay, and can't drift during the test.

**Why beta 1.15 instead of maximizing return?**
We measured it rather than forcing it: the book's beta is 1.11 in normal markets, inside the plan's 1.10 to 1.20 band, and 0.96 over the whole period because the cash dial cuts exposure in stress. Above about 1.2 the extra return is just leveraged S&P exposure, which in a one-month test mostly makes the bad month worse.

**Why cash instead of puts?**
SPY and its options aren't in our universe, so there is no index put to buy, and puts on single names would cost premium every month in a test scored mostly on return. Cash costs nothing, cuts exposure by exactly the amount we choose, and is an explicit line in every portfolio.

**What happens if the market crashes in week 1?**
We would take most of that first drop: the stress rule needs the S&P below its 200-day average and high volatility, which a crash from a market high may not show yet, so it protects against drawn-out declines like 2022 rather than a one-day gap. At the next weekly decision, if the flag is on, the book moves to 25% cash and lower beta, and the 10% name cap and liquidity limits mean no single stock can sink the book.

**Which factor matters most, and how do you know?**
Momentum: removing it from the full backtest cut return from 13.7% to 7.3% a year, the biggest drop, with quality next (8.5%). We learned which factor hurt the same way: removing the volatility premium raised return to 19.2% and cut turnover from 21x to 7x, so we dropped it, and we say plainly that this choice was made on the same data it is tested on.

**What would you do with more time?**
Get data that includes delisted companies to remove survivorship bias, and test on a longer history with more market crashes. Also: refit the stock clusters each year, measure real trading costs instead of modeling them, and run the full model through the held-back months several times with different start dates.

**Isn't one good year doing all the work?**
2024 (+50%) carries a lot of it, and we lagged badly in 2023 (+13% vs +24% for the S&P). But the model beat the S&P in 7 of 9 years and stays ahead of both benchmarks from every start year, 2018 to 2022.

**Does trading at the next open hurt you?**
No. Rerun over eight years with next-open fills, the model earns 19.0% a year against 17.6% with close fills, because the new book is in place for the whole trading day.

**How sensitive is it to your choices?**
Double trading costs: 16.6% a year. Data one day late: 13.7%. Regrouping the stocks every year: 14.2%. Each still beats the S&P's 12.4%.
