# nabla — RowdyHacks Finance Track

## The challenge
- RowdyHacks Finance Track, run by the Investment Society (UTSA).
- Build an AI that trades a $1M portfolio. Tested on the 30 days after our data ends (~21 trading days). Short window = mostly noise, so favor robust signals over complex models.
- 24 hours total. Team of two: Jesse (finance: factors, risk rules, pitch) and Ezekiel (quant: pipeline, backtester, API, keys).
- Investment Society workshop: Sat 3:15 PM.

## Adopted plan: v3 (full text in `docs/nabla_plan_v3.pdf`)
A concentrated, slightly high-beta 15-stock book from five point-in-time factors, rebalanced weekly on new data, with one cash rule for stress. No options. Nothing has been run on the real data yet; every performance statement is a hypothesis.

### Organizer answers (workshop)
- Cash can be held, and scoring will be changed so holding cash is not punished (re-pull the starter repo and re-run `check.py`; the current rubric still checks weights sum to 1.0 +/- 0.01).
- Scored mostly on **total return**; Sharpe and drawdown still matter.
- Transaction costs must be baked into our own model.
- Our data stops at the cutoff; the model is tested on the 30 days after it.
- Weekly rebalancing is allowed.
- We choose our own position and sector limits.

## Starter repo
https://github.com/orkid-labs/utsa-investment-hackathon
- We build a **FastAPI web service**. Judged endpoints (keep paths and response shapes): `GET /health`, `GET /portfolio/holdings`, `POST /backtest`, `GET /screen`, `GET /asof`. The template in `launchpad/template/app.py` already scores 100/100.
- Hand in: a **live endpoint URL** + a **public GitHub repo** (repo audit: original finance logic, PIT discipline, honest data use).
- Rubric (100 pts, `launchpad/rubric/check.py`): health 5, holdings shape 10, holdings weights 10, backtest shape 15, backtest values match judges' recompute within 2% 25, screen 10, asof PIT 10, responsiveness 15.
- Data: `statevector` SDK; `SV_DATA_ROOT` + team token `SV_DATA_TOKEN` (**never commit it**). ~1,258 US tickers, 2014 to present. Read the starter repo's `FEATURES.md` and `DEVIATIONS.md`.
- Status: waiting on the team data token. First step once we have it: `svq doctor`.

## Rules
- Long-only stocks (options allowed by the mandate but not used in v3). Weights >= 0.
- Stay inside `ds.universe()`. Do not delete the sentinel ticker `ORKD`.
- Fundamentals join by filing date, not period end (`ds.asof()` / `ds.fundamentals(asof=...)`).
- Always set the as-of date to `max(ds.trading_days())`, never `date.today()`.
- Check whether `ds.holdout_cutoff()` (last trading day minus 30 days) still applies, since our data already ends at the cutoff.

## Factors (five, each with an economic reason fixed before testing)
| Factor | Construction | Why |
| --- | --- | --- |
| Momentum 12-1 | Return from t-12m to t-1m on split/dividend-adjusted prices | Investors underreact; trends persist |
| Guidance velocity | `guidance_range_velocity`: same-period guidance raises/cuts per day | Management revisions lead price |
| Quality | ROE or gross profit / total assets from filed fundamentals | Profitable firms outperform, hold up in selloffs |
| Value | Filed TTM EPS / price (earnings yield) | Cheap stocks outperform; offsets momentum crashes |
| Volatility premium | -log(IV30 / RV21) from `atm_iv` and 21-day realized vol | Options priced above delivered vol predict lower returns (verify the Bali and Hovakimyan 2009 citation) |

Dropped from earlier plans: `fundamental_surprise` (annual guidance vs TTM actuals measures guided growth, not beats; see DEVIATIONS item 12), `composite_valuation_gap` (no filing-date gate, duplicates 1-year reversal), `term_slope`/puts (no options), `minute_realized_diffusion` as sizing, `amihud_illiq` as alpha (now only the liquidity filter and cost model).

### Construction
1. Winsorize each raw factor at 1st/99th percentile across stocks per date.
2. Z-score within ~10 sector groups mapped from SIC division (not the raw SIC description). Clip at +/-3.
3. Missing factor = neutral (0). Composite = equal-weight sum over the **fixed five** factors (see known issue 1). Ridge only if it beats the composite out of sample.

## Portfolio rules (starting values; our own limits)
- Liquidity filter: 20-day ADV > $50M, price > $5, exclude most illiquid Amihud decile.
- Hold top 15 by composite. Max 10% per name, max 30% per sector group. Max 1% of 20-day ADV.
- Target beta 1.1 to 1.2 (shrunk beta = 0.67*beta + 0.33, 252-day vs SPX). Beta is a tie-break, not an optimization target; report realized beta.
- Earnings in window: max 6% per reporting name.
- Turnover band: trade only if a target weight moves more than 2 points.
- Crowding check: compare top 15 with a naive 12-month momentum top 20.

## Cash dial (one rule, checked weekly)
- Normal: 0 to 5% cash, beta 1.1 to 1.2.
- Stress: SPX below its 200-day average AND (21-day market realized vol OR funding stress above its 80th percentile) -> 25% cash and swap the highest-beta names for next-best lower-beta names.
- Leave Stress only after both conditions are false for two straight weeks.
- Thresholds fixed before testing; percentiles from past data only (expanding window).
- Until the sum-to-1 check is relaxed, Stress holds low-beta names instead of cash.

## Costs
Every trade pays half-spread plus impact: spread 5 bps (most liquid third), 10 (middle), 20 (rest), impact = k * Amihud * dollars traded, k = 1. Rerun at 2x costs. Watch the Amihud x10^6 scaling.

## Weekly loop
- Offline: fit weights, betas, dial thresholds on all history; save `config/model.json` with git commit and data hash; cache slow inputs.
- Live each rebalance day: as-of = last trading day in data; load newest rows; z-scores and composite; check dial; pick 15 within limits and turnover band; return from `/portfolio/holdings` inside 30 s. No refitting during the test. If no new data arrives, the book is unchanged.

## Validation
- Backtest runs the live loop exactly (weekly, same limits, costs) from 2018 to the cutoff. Walk-forward only; labels lag 21 trading days. Last 6 months held back until final go/no-go, then refit on everything.
- One return function matching `check.py`, reused by `/backtest`, unit-tested on random weights.
- Compare with SPX and an equal-weight liquid universe: total return, annualized, Sharpe, max drawdown, turnover, cost paid, rolling 21-day returns (median, 5th, 95th, worst), 2018 Q4 / 2020 / 2022.
- Tests: shuffled labels, one-day signal delay, each factor alone and composite minus each factor, 2x costs.

## Known issues to resolve (from the v3 review)
1. Composite averaging over available factors biases the top 15 toward names with fewer factors; use a fixed-five sum with zeros, or rescale to unit variance.
2. Turnover band and dial hysteresis need state; make them pure functions of the data by replaying the last N weeks on each call.
3. Judge the cash dial by the distribution of 21-day returns / rank, not max drawdown; only ~3 stress episodes exist, so treat thresholds as priors; fix thresholds before testing (not "fit on all history").
4. Report coverage per factor per date (guidance velocity and volatility premium are often null).
5. Beta target has no mechanism beyond the tie-break; add a soft constraint or just report realized beta.
6. Whipsaw: stress triggers lag and persist into rebounds.
7. Cache all inputs so a data-server hiccup does not break the live loop.
8. Equal-weight across 15 may beat score-weighting (less noise).

## Cut list
Options (puts and calls), reinforcement learning, LightGBM, Black-Litterman/CVaR, earnings overlay beyond the per-name cap.

## Open questions (see `docs/workshop_questions.md`)
How new data arrives during the test; which weekday the book is read and whether returns compound from weekly holdings; whether the sum check accepts weights below 0.99; which metrics count and with what weight; how prizes are decided; what counts as "AI".

## Build order
- Sat 6-8 PM: loader anchored to the last data date; split/dividend adjustment; deploy the starter; pass `check.py`.
- Sat 8 PM - midnight: weekly backtest harness with costs; composite and portfolio rules; check factor signs and IC.
- Sun 12-2 AM: cash dial test; held-back 6-month check; freeze `model.json`; charts.
- Sun morning: live weekly scoring in `/portfolio/holdings`; redeploy; rerun `check.py`; `docs/AUDIT.md`; pitch.
- Rule: each step must work before the next starts; if time runs out, ship the last step that passed.

## Repo notes
- `src/nabla/` holds an earlier pandas scaffold written for Bloomberg-style columns; adapt its logic to the FastAPI app and `statevector` accessors rather than reusing it directly.
- `docs/nabla_plan_v3.pdf` (plan), `docs/workshop_questions.md` (questions). Pitch deck: https://claude.ai/artifact/WXnNHkqcM5McGXFsJ2VqVQ (private until shared).
- Repo: https://github.com/envezdezeke/nabla. Work directly on `main`; always `git pull` before pushing.
