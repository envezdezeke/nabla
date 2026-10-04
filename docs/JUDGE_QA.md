# Judge questions: short answers

One or two sentences each, for the Q&A after the pitch. Numbers come from `docs/AUDIT.md`; replace each [pending] with the result once it lands.

**One month is mostly luck. How is this skill?**
It isn't provable in one month, and we don't claim it: what we claim is a process, made of signals with decades of published evidence, rules fixed before testing, and an eight-year backtest where it beat the equal-weight universe after costs (15.2% vs 11.5% a year). The random-book test, where 15 random stocks each week face the same rules, is our check that the scores add something: [pending].

**How do you know there's no look-ahead?**
Every decision uses data through the prior close only, fundamentals count from the day after their filing date (60 days after period end when no filing matches), and the decision function takes the cutoff time as its input and never reads today's date. In our five-bucket factor test no factor was suspiciously good (every t-stat below 1.5), and the one-day-delay test is [pending]; the backtest calls the same function the judges replay.

**Why not machine learning or RL?**
We have about 100 independent months since 2018, and even simple factors can't be told apart from zero on that sample, so a flexible model would learn noise and look great only in the backtest. Fixed rules are transparent, give the same answer on every replay, and can't drift during the test.

**Why beta 1.15 instead of maximizing return?**
The score rewards total return, so we stay above the market's beta of 1, but past about 1.2 the extra return is just leveraged S&P exposure, and in a one-month test that mostly makes the bad month worse (our worst 21 days in the 2023-2026 run were already -20%). The band applies once the optimizer is in; v1 without it runs higher, and we record that choice in the audit [update if we decide to accept the higher beta].

**Why cash instead of puts?**
SPY and its options aren't in our universe, so there is no index put to buy, and puts on single names would cost premium every month in a test scored mostly on return. Cash costs nothing, cuts exposure by exactly the amount we choose, and is an explicit line in every portfolio.

**What happens if the market crashes in week 1?**
We would take most of that first drop: the stress rule needs the S&P below its 200-day average and high volatility, which a crash from a market high may not show yet, so it protects against drawn-out declines like 2022 rather than a one-day gap. At the next weekly decision, if the flag is on, the book moves to 25% cash and lower beta, and the 10% name cap and liquidity limits mean no single stock can sink the book.

**Which factor matters most, and how do you know?**
Momentum and guidance velocity are the only two that pointed the right way from 2018 to 2026, each working in 4 of 8 years, but neither is statistically strong on its own. The real answer comes from removing one factor at a time from the full backtest: [pending].

**What would you do with more time?**
Get data that includes delisted companies to remove survivorship bias, and test on a longer history with more market crashes. Also: refit the stock clusters each year, measure real trading costs instead of modeling them, and run the full model through the held-back months several times with different start dates.
