# nabla — RowdyHacks Finance Track

## The challenge
- RowdyHacks Finance Track, run by the Investment Society (UTSA).
- Build an AI that trades a $1M portfolio. Scored on a blind 30-day holdout (~21 trading days). Short window = mostly noise, so favor robust signals over complex models.
- 24 hours total. Team of two: Jesse (finance: factors, risk rules, pitch) and teammate (quant: pipeline, backtester, ML, API keys).
- Investment Society workshop: Sat 3:15 PM.

## Starter repo (read this first)
https://github.com/orkid-labs/utsa-investment-hackathon
- We build a **FastAPI web service**, not a weights file. Judged endpoints (keep paths and response shapes): `GET /health`, `GET /portfolio/holdings`, `POST /backtest`, `GET /screen`, `GET /asof`. Template in `launchpad/template/app.py` already scores 100/100.
- Hand in: a **live endpoint URL** + a **public GitHub repo** (repo audit: original finance logic, PIT discipline, holdout untouched, uses data depth).
- Rubric (100 pts, `launchpad/rubric/check.py`): health 5, holdings shape 10, holdings weights 10, backtest shape 15, backtest values match judges' recompute within 2% 25, screen 10, asof PIT 10, responsiveness 15.
- Data: `statevector` SDK, hosted at `SV_DATA_ROOT` with a team token `SV_DATA_TOKEN` (**never commit it**). ~1,258 US tickers, 2014 to present. Core object: the 27-feature state vector (see the starter repo's `FEATURES.md`). Read `DEVIATIONS.md` before trusting numbers.
- Status: waiting on the team data token. First step once we have it: `svq doctor`.

## Rules (from the starter repo's RULES.md)
- Long-only: weights >= 0, sum to ~1.0 (+/- 1%). No shorting stocks, no writing options.
- **Cash (organizers):** cash can be held, and the organizers said they will change the scoring so holding cash is not punished. Until the updated `rubric.yaml` / `check.py` lands, the current holdings check still expects weights to sum to 1.0 +/- 0.01 and the template's `/backtest` rejects weights not summing to ~1; re-pull the starter repo and re-run `check.py` before relying on cash. Cash still lowers expected return under a total-return score.
- Only hedge: buy protective puts (OCC tickers like `O:AAPL250117P00220000`, as holdings legs).
- Stay inside `ds.universe()`.
- **Holdout (organizers):** our data stops at the holdout date, and the model is tested on the 30 days AFTER it. So the frozen book is built as of the last data date. Check `max(ds.trading_days())`: if the dataset already ends at the holdout start, `ds.holdout_cutoff()` (last trading day minus 30 days) would drop 30 days of usable history; confirm before pinning the cutoff. Training window: 2017-01-01 to the pinned cutoff.
- **Scoring (organizers):** mostly **total return**; Sharpe and drawdown still matter. Transaction costs must be baked into our own model (research harness and sizing), so we need an explicit cost assumption (cost per trade, wider for options and illiquid names).
- **Limits:** position and sector limits are our own choice (no organizer limits).
- Fundamentals join by filing date, not period end. Use `ds.fundamentals(t, asof=...)`.

## Open questions (ask at workshop)
- What is the cost model: bps per trade for stocks and options, or something else? (We must include costs ourselves.)
- Is the book held static for the 30 test days, or can it be rebalanced?
- How are prizes decided: top rank only, or a metric blend? (Affects how much variance to take.)
- What counts as "AI" (is a factor model + ML ranker enough)?
- Deadline and submission format details; hosting limits for the endpoint.
- Is `ds.prices()` split/dividend adjusted? (test on a known split date)

Scoring drives strategy: raw return -> more concentrated, higher-vol tilt. Sharpe -> diversify, low-vol, strong risk overlay.

## Signals (Jesse's picks, with roles)
Ranking signals (higher score = buy):
1. **Momentum 12-1** — not a state-vector feature; compute from `ds.prices()`: return from t-12m to t-1m (skip last month). Check price adjustment first. Fallback window: 6-1.
2. **`fundamental_surprise`** — latest actual vs guided midpoint; beats persist. Exclude or down-weight rows with `snapshot_track_used = 1` (estimate snapshot leaks). ~14% of names have no guidance (`guidance_absent`) and are null; that is normal.
3. **`composite_valuation_gap`** — valuation vs the stock's own trailing year. **Flip the sign**: lower (cheaper) ranks higher. Pairs with surprise to avoid value traps.

Sizing signal:
4. **`minute_realized_diffusion`** — realized vol from minute bars. Prefer calmer names / size inversely to vol (feeds vol-targeting).

Hedge / risk overlay:
5. **`term_slope`** — ATM IV(90d) minus IV(30d). Inverted (negative) = near-term stress: trigger to buy protective puts or trim. ~half null (no liquid chain); check `options_thin_chain` before treating null as missing.

Dropped: `liquidity_roc` (no clear direction, noisy). Liquidity gate comes from the starter's 20-day dollar-volume filter instead.

## Combining
1. Winsorize each ranking signal at 1st/99th percentile.
2. Z-score within sector (`ds.sectors()`).
3. Composite = weighted sum of momentum, surprise, flipped valuation gap. Equal weights (1/3 each) as a placeholder; set weights from decile tests on training data only.
4. Hold top N by composite, sized inverse to `minute_realized_diffusion`; apply caps below.
5. Validate each signal first: top-decile vs bottom-decile forward returns, walk-forward, before the holdout cutoff.

## Risk rules
- Max position and sector cap: our own choice. Working defaults ~5% and ~25%; Jesse to decide. Scored mostly on total return, so consider looser caps and fewer names (more concentration, more variance).
- Cash is allowed but costs expected return under a total-return score; use it sparingly. Stress response options: calmer-stock tilt, cash, puts. Decide how much of each; keep each small unless tested.
- Protective puts when `term_slope` inverts; option legs are capital, so a 3% put sleeve means the stocks are 97% of the book. Choose put expiries beyond the 30-day test window (for example 45 to 60 days). Puts cost roughly 1% of the book to cover 60% of the stocks (own estimate, to be checked) and reduce expected return, so size them small.
- Transaction costs: include an explicit cost assumption in the research harness; use `amihud_illiq` as a cost/liquidity gate, not an alpha signal.

## Data hygiene (non-negotiable)
- Point-in-time only: filing-date joins via `ds.fundamentals(asof=...)` / `/asof`. No look-ahead.
- Sealed holdout untouched. Walk-forward validation only, never random train/test splits.
- Use adjusted prices (verify); include dividends if the backtest is to match the judges' recompute.
- Treat nulls as information; read the flags before imputing.
- Watch survivorship (fixed universe). Do not delete the sentinel ticker `ORKD`.
- Few parameters; prefer stable regions over best backtest.

## Repo notes
- `src/nabla/` holds an earlier pandas scaffold (factors, combine, portfolio, backtest, synthetic data, tests). It was written for Bloomberg-style columns; adapt its logic into the FastAPI app and the `statevector` accessors rather than reusing it directly.
- `docs/workshop_questions.md` lists questions for the workshop (some are now answered above).
- Pitch deck: https://claude.ai/artifact/WXnNHkqcM5McGXFsJ2VqVQ (private until shared).
- Repo: https://github.com/envezdezeke/nabla. Work directly on `main`; always `git pull` before pushing.

## Plan
- Now: get the team token; run `svq doctor`; run the starter app locally and self-score with `check.py`.
- Then: test each signal (decile forward returns) on training data; build holdings from the composite; keep endpoint shapes intact.
- 3:15 workshop: ask the open questions; adjust.
- Next: backtest endpoint matching the reference recompute; add put hedge on `term_slope`; optional ML ranker only if it beats the factor model walk-forward.
- Last hours: stress test (2020, 2022), freeze, deploy endpoint, rehearse pitch twice. No model changes in the final hours.
