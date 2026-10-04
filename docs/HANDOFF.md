# Handoff: where we are (for a new Claude session)

Read `CLAUDE.md` first (the v5 plan and rules), then this file, then `docs/AUDIT.md` (results and every decision).

## Overnight summary (Sun morning)

Overnight run (cloud session, Sun ~1-3 AM). Everything below is pushed to main.

**Results on the shipped model v1.2, 2018 to Feb 2026, costs included** (`docs/AUDIT.md` section 9 has the tables and charts):
- 17.6% a year vs 11.5% equal weight and 12.4% S&P 500; Sharpe 0.83 vs 0.61 and 0.70; max drawdown 30% vs 39% and 34%.
- 2018 Q4 -12% (benchmarks -15%/-14%), 2020 +25% (+27%/+16%), 2022 -18% (-19%/-19%).
- Beta 0.96 (1.11 without the cash dial, inside the plan's band); alpha +5.7%/yr, t = 1.27 (not significant).
- Beats 5 of 5 random books (8% to 14%/yr). Double costs: 16.6%/yr. One-day delay: 13.7%/yr (falls, no rise: no leak sign, but signals decay fast).
- Turnover 7.5x/yr, costs about 0.8%/yr.

**Fixed**
- `data._cached_years`: a saved year was never refreshed, so the live book and the crowding check used prices only to 2026-02-20. Fixed with tests.
- API: `/backtest` and `/screen` timed out against the hosted server (check.py 50/100). They now use the yearly cache, warmed at startup. Local check.py: **100/100**.
- `config/book.json` committed (v1.2, as of 2026-09-21), so a fresh deploy serves our book.

**Made**
- `docs/img/` charts (growth, drawdown, cluster concentration) via `explore/08_charts.py`.
- AUDIT.md, README, JUDGE_QA.md, the deck (factor, ladder, regime, backtest slides plus a new growth chart slide) and the pitch script updated to v1.2.

**Still to do (in priority order)**
1. **Replay record writer:** `decide(information_cutoff)` returning the judged record (schema_version, team_id, model_id, decision_id, cutoff 16:00 ET, decision 16:15, execution next open from the holiday calendar, CASHHOLDING line). Not built; this is what the judges score.
2. **Next-open fills** in the research backtest. The one-day-delay result says timing matters, so check whether next-open fills cost return.
3. **Freeze the clusters.** The live book fits clusters on the year before its own start (62 unclustered), the backtest on 2017 (431 unclustered), so live and backtest group stocks differently. Fit once at the cutoff, save to config, use everywhere; record the git commit and data hash in `config/model.json`.
4. Redeploy and rerun check.py against the deployed URL (allow a minute for the cache to warm after a cold start).
5. Go/no-go on the six held-back months (`run_backtest.py --include-holdback`), then freeze.
6. Deck: confirm with Ezekiel that the slide numbers match his runs (his rung-1 run says 19.2%/yr, ours 18.8%; small setup differences).

## Who and what
- Team nabla at the RowdyHacks finance track (UTSA Investment Society): **Jesse** (finance: factors, risk rules, audit doc, pitch; GitHub `FroyoMojo`) and **Ezekiel** (quant: pipeline, backtest, API, deploy; GitHub `envezdezeke`, repo owner).
- Deliverable: a FastAPI service + public repo. The judges replay our frozen model through the 30 days after our data ends, one decision at a time; each decision is a full target portfolio (cash is an explicit `CASHHOLDING` line, weights sum to 1). Scored mostly on total return.
- Submit Sun ~11:30 AM (timeline and cut rules in CLAUDE.md).

## How Jesse likes to work
- Plain terms; Mac Terminal commands one at a time, numbered, with what each should print.
- Keep the pitch deck and script updated as the plan changes.
- Work directly on `main`; `git pull` before pushing. Never commit the data token.

## Model as shipped: v1.2 (`config/model.json`)
- Weekly, data through the prior close. Liquidity filter (ADV >= $50M, price > $5, drop least liquid 10% by Amihud).
- Four factors with equal weight: momentum 12-1, guidance velocity, quality (margin blend from filings), value (filed TTM EPS / price). Volatility premium has weight 0 (dropped on the drop-one-factor test, v1.1).
- z-score within 10 return clusters (no SIC codes in the data), clip ±3, fixed-weight sum with missing = 0.
- Equal-weight top 15; entry top 15, exit below 30; 2-point no-trade band; 10% per name, 30% per cluster, 6% for names reporting within 30 days.
- Stress flag (SPX below 200-day average AND 21-day vol above its 80th percentile, two-week hysteresis) moves 25% to `CASHHOLDING` (v1.2). Panic momentum rule tested and rejected. Optimizer not built.

## Plan history (so you do not re-suggest cut ideas)
- v1 static factor book -> v3 five factors + cash dial -> v4 added RL bandit, puts, HMM, optimizer -> **v5** cut the bandit, puts, partial trading and HMM after a red-team review.
- Replay-format fixes on top of v5: one deterministic `decide(information_cutoff)`, state rebuilt from data, next-open fills, research backtest = the same function.

## Files to know
| What | Where |
| --- | --- |
| Pipeline, factors, book, backtest, live book, API | `src/nabla/`, `app/main.py`, `scripts/` |
| Leak/robustness tests (random books, delay, 2x costs, drop one factor, ladder) | `scripts/audit.py` |
| Charts (growth, drawdown, cluster concentration) | `explore/08_charts.py` -> `docs/img/` |
| Crowding check, sample holdings, factor buckets | `explore/07_crowding_check.py`, `explore/06_sample_holdings.py`, `explore/05_factor_buckets.py` |
| Judge-facing audit | `docs/AUDIT.md` |
| Short answers to likely judge questions | `docs/JUDGE_QA.md` |
| Frozen live book served by `/portfolio/holdings` | `config/book.json` (rebuild with `scripts/build_book.py`) |

## Environment notes
- Mac: Python 3.12 venv in `nabla/.venv`; install the SDK with `pip install ../utsa-investment-hackathon/sdk` (editable `-e` install did not import).
- Each new Terminal: `source .venv/bin/activate`, then `export SV_DATA_ROOT=https://pop-os.tail01ad.ts.net` and `export SV_DATA_TOKEN=...`.
- Price and state-vector data are cached by year in `artifacts/cache` (gitignored). Against the hosted server the first download of a year takes minutes; the API warms the screen window and 2020 at startup, so call `/health` and wait a minute after a cold deploy before running `check.py`.
- Killing a server: `ps aux | grep "[u]vicorn" | awk '{print $2}' | xargs -r kill` (plain `pkill -f` matches the calling shell and kills it).

## Links
- Pitch deck (private until shared): https://claude.ai/artifact/WXnNHkqcM5McGXFsJ2VqVQ
- Pitch script: https://claude.ai/code/artifact/31e44f1a-30cf-40d1-a234-0b3b8ed1af20
- Audit of the plans (for Ezekiel): https://claude.ai/code/artifact/6d8c695c-f533-4b06-9d40-77a848b4ad16
- Plans: `docs/nabla_plan_v3.pdf`, `docs/nabla_plan_v5.pdf`
