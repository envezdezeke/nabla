# nabla

RowdyHacks (UTSA Investment Society) finance track. A long-only, weekly-rebalanced
15-stock factor book served as a FastAPI app on the starter repo's `statevector` dataset.
Design: `docs/nabla_plan_v5.pdf`. Shipped model: **v1.3** (`config/model.json`, groups frozen in `config/clusters.json`).

## v1.3 in one paragraph

Each week, on data through the prior close: filter to liquid names (20-day ADV >= $50M,
price > $5, drop the least liquid 10% by Amihud); score four factors (12-1 momentum,
guidance velocity, quality from filed margins and leverage, value = filed TTM EPS / price),
winsorize, z-score within 10 groups of stocks that move together (the data has no SIC codes;
groups are consensus clusters refit each January on prior prices only), clip
at ±3, and sum with fixed equal weights where a missing factor counts as 0; hold the top 15
equal-weight. Entry band top 15, exit band rank 30, 2-point no-trade band, max 4 names per
cluster (30%), 10% per name, 6% for names with a projected filing inside 30 days. Fully
invested, except 25% `CASHHOLDING` while the stress flag is on (S&P below its 200-day
average and 21-day volatility above its 80th percentile). The volatility premium (the plan's fifth factor) has weight 0 after the
drop-one-factor test; the panic momentum rule was tested and rejected. No optimizer, no
options.

Backtest, weekly, Jan 2018 to the data cutoff (Aug 2026), costs included: **14.9% a year** vs 13.0%
for the S&P 500 and 12.1% for the equal-weight liquid universe; Sharpe 0.73 (S&P 0.73); max drawdown
34% (S&P 34%). The model was built on Jan 2018 to Feb 2026 (14.2% vs 12.4%); the six months after were
held back and used once: **+19.7%**, Sharpe 1.83, max drawdown 7.8%. 22 of 24 one-at-a-time setting
changes still beat the S&P. Survivorship-biased; every result, test and decision is in `docs/AUDIT.md`.

## Run

```bash
pip install -e <starter repo>/sdk -r requirements.txt
export SV_DATA_ROOT=https://pop-os.tail01ad.ts.net SV_DATA_TOKEN=<team token>  # never commit the token

python scripts/build_book.py          # freeze this week's book -> config/book.json
python scripts/run_backtest.py        # 2018 -> cutoff minus 6 held-back months, vs EW liquid and SPX
uvicorn app.main:app --port 8000
python <starter repo>/launchpad/rubric/check.py --base-url http://localhost:8000
pytest -q                             # runs offline on a synthetic dataset
```

## Layout

| path | what |
|---|---|
| `src/nabla/data.py` | loaders anchored to the last trading day, split adjustment, sector groups |
| `src/nabla/factors.py` | the factors and the liquidity filter |
| `src/nabla/fundamentals.py` | quality and value from filings, point-in-time by filing date |
| `src/nabla/costs.py` | spread + impact cost model and the 1%-of-ADV cap |
| `src/nabla/regime.py` | stress and panic flags (coded, not yet wired into the book) |
| `src/nabla/combine.py` | winsorize, sector z-score, fixed-five composite |
| `src/nabla/book.py` | banded top-15 selection and capped equal weights |
| `src/nabla/model.py` | the weekly decision, shared by backtest and API |
| `src/nabla/sim.py` | weekly backtest with costs, judge-engine conventions |
| `src/nabla/live.py` | live book; replays recent weeks so bands need no stored state |
| `app/main.py` | API: judged endpoints plus `/model` (config, coverage, top-30 candidates) |
| `config/model.json` | every model parameter |
| `scripts/audit.py` | leak and robustness tests (random books, delay, double costs, drop one factor) |
| `docs/AUDIT.md` | how the model decides, limits, results, what we cannot prove |

## Point-in-time and leakage guards

- As-of date is the last trading day in the data, never `date.today()`.
- Signals for a rebalance on day t use data through t-1. The research backtest trades at t's
  close (the judges' engine convention); the replay record executes at the next open, which
  backtests about a point lower (13.2% vs 14.2% a year).
- Backtest stops at the SDK holdout cutoff and holds back a further 6 months for the go/no-go.
- Splits are back-adjusted only where the raw series shows the jump, so adjusted data is untouched.
- `tests/test_v1.py` perturbs prices and signals after a date and checks nothing before it changes.

## Known limits (full list in `docs/AUDIT.md`)

- One test month is mostly noise; a small edge cannot be told from luck.
- The universe is today's survivors, with almost no financials and no SPY; backtests are flattered.
- The volatility premium was dropped using the same sample the backtest reports, so the
  backtest is in-sample; the six held-back months are the honest check.
- The earnings cap uses `days_to_next_report`, a projected SEC filing date that lags the
  actual earnings release.
- Price momentum is price-only; dividends are not in the signal.

## Replay interface (what the judges call)

`src/nabla/decide.py`: `decide(information_cutoff)` returns one decision record
(`schema_version`, `team_id`, `model_id`, `decision_id`, `information_cutoff`,
`decision_time`, `execution_time` = next open 09:30 ET, `action`,
`target_holdings` with `CASHHOLDING` for cash). Only data on or before the cutoff
is read; the book rebalances on the last trading day of each week and holds
otherwise. Served at `POST /decide {"information_cutoff": ...}` and
`GET /decide?information_cutoff=...`. `python scripts/replay.py --start ... --end ...`
writes a day-by-day record file. Set `NABLA_TEAM_ID` for the team id.
