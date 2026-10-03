# Model plan

Status: brainstorming. Nothing here has been run on the real data yet (no token in the build session). Every claim about performance is a hypothesis to test.

## What we are building

A long-only portfolio-management API on the UTSA hackathon dataset (state vector, equities, options). Judged by:

- a deterministic rubric (`launchpad/rubric/check.py`): shapes, long-only weights summing to 1, `/backtest` matching the reference recompute within 2%, `/asof` with no lookahead, latency. The reference app scores 100, so this only checks conformance.
- a repo audit: original finance logic, point-in-time discipline, sealed holdout untouched, depth of data use.

Whether the holdout also scores returns, and by what metric, is unknown. See "Questions for organizers".

## Questions for organizers (priority order)

1. Is the sealed holdout used to score returns, or only to check for cheating?
2. If scored, what metric: total return, Sharpe, drawdown-penalized?
3. One book held through the window, or can we rebalance?
4. How does the reference `/backtest` value option legs (missing prints, spreads)?
5. Are `stocks_daily` closes split- and dividend-adjusted?
6. `RULES.md` says `POST /holdings`, the rubric and template use `GET /portfolio/holdings`. Which governs?
7. Any size or latency limit on the deployed endpoint beyond the 30s rubric timeout?

Questions 1 and 2 decide how aggressive the options sleeve should be.

## Architecture

Train offline, serve cheap. The 30s latency limit means the API loads saved coefficients and runs selection and weighting, never training.

1. **Score** each stock per day from a few standardized features (ridge or simple fixed-weight combination first, small gradient-boosted ranker only if it beats it out of sample).
2. **Select** top N (20 to 40) after liquidity filters (`amihud_illiq`, `ds.adv()`).
3. **Weight** with a convex optimizer (`cvxpy`): long-only, sum 1, position cap ~5%, sector cap, score minus risk penalty. Shrink scores toward the mean. Fallback: inverse-volatility weights.
4. **Hedge** with rules: fixed-percentage OTM protective puts on the index or largest holdings (delta about -0.25 to -0.30, 30 to 45 days to expiry), premium budget 2 to 5% of the book.
5. **Regime dial**: a stress score from 2 or 3 inputs (`funding_stress`, `term_slope`, realized vol), fixed thresholds with hysteresis. It scales total equity exposure and the put budget only. It does not reweight individual names. Cash is the residual under the rules, so de-risking is free to implement.

Gradient descent fits model coefficients. It does not pick equities or contracts, which are discrete choices.

## Build order and the ablation rule

Each step must beat the previous one out of sample, or it is cut.

| step | version | adds |
|---|---|---|
| v0 | baseline | equal-weight liquid top-N; SPX as the benchmark |
| v1 | factors | 4 to 6 standardized features, ranked, top N |
| v2 | weights | inverse-vol or capped optimizer, weekly or monthly rebalance with turnover penalty |
| v3 | hedge | protective puts with a premium budget |
| v4 | regime | single exposure dial |
| v5 | options sleeve | any directional option legs. Build last, cut without regret |

Expected outcome, stated before data: v1 may show a modest edge, v4 probably will not survive ablation, and v5 will look best in the backtest and be the least trustworthy.

## Feature choice

- Pick candidates for an economic reason first: `composite_valuation_gap`, `fundamental_surprise`, `variance_risk_premium`, `amihud_illiq`, plus a momentum measure from prices.
- Then screen with `explore/03_feature_ic.py`. Choosing from all 27 by IC alone picks the winners of a noise contest.
- Z-score each feature per date, within sector where possible.
- Log how many features and parameters were tried. That count is the overfitting budget.

## Pitfalls and guards

| pitfall | guard |
|---|---|
| Lookahead | Signals dated t trade at t+1. Fundamentals via `ds.fundamentals(asof=...)`. Unit test: shift every signal one day forward and the result must get worse |
| Holdout leakage | Cut everything at `ds.holdout_cutoff()`. Drop forward windows that would cross it |
| Selection bias | Choose features and parameters on one period, evaluate on a later one, touch the final period once |
| Unadjusted prices | Check split and dividend adjustment before computing any return. A 4-for-1 split looks like a 75% crash |
| Option marks | Value only contracts that traded. Charge a spread from the high-low range proxy. Never book a missing print as 0% |
| Survivorship | The 1,275-name panel is a fixed universe. State the bias in the writeup |
| Regime overfit | Do not tune thresholds to the few visible stress events (late 2018, 2020, 2022) |
| Weight instability | No raw mean-variance on estimated returns |
| Overlapping windows | Sample every few days. Rank features with IC, do not read the t-stat as significance |
| Churn | Weekly or monthly rebalance, turnover penalty, include costs |

## Audit protocol (run once data access works)

1. Baselines: equal-weight liquid top-N and SPX.
2. Ablation: v0 through v5, one layer at a time.
3. Walk-forward splits only, never random. Sub-period report for 2018, 2020, 2022.
4. Shuffle test: permute labels, Sharpe should fall to about 0.
5. Lag test: delay signals one day and measure degradation.
6. Cost sensitivity: slippage, option spreads, turnover.
7. Concentration, drawdown and sector exposure checks.

One month of holdout cannot prove skill. A 30-stock book has about 4 to 5% monthly volatility, so a 1% monthly edge takes years to separate from luck. A good holdout result does not validate the model and a bad one does not invalidate it.

## If time is short

Do v0, the ablation harness, the lookahead tests and the split-adjustment check. Those make any result trustworthy. The regime layer and options sleeve are the most fun and the least likely to pay off.

## Deliverables for the repo audit

- `docs/AUDIT.md`: what was checked (no lookahead, holdout untouched, costs included), what was tried and dropped, known limits.
- An ablation chart (baseline, then each layer) and a drawdown chart.
- A README with a working setup path and no secrets. The token comes from `SV_DATA_TOKEN`, never committed.

## Open tasks

- [ ] Get team token, run `explore/01_setup_check.py` and `explore/03_feature_ic.py`, record results here.
- [ ] Get answers to the organizer questions.
- [ ] Update `CLAUDE.md` on `main` (it still assumes Bloomberg data, a $1M book and a different holdout).
- [ ] Build the harness (walk-forward backtester, baselines, ablation runner, audit tests).
- [ ] Split work by folder between the two of us to avoid merge conflicts.
