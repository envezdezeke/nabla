# nabla

RowdyHacks (UTSA Investment Society) finance track. A long-only, weekly-rebalanced
15-stock factor book served as a FastAPI app on the starter repo's `statevector` dataset.
Design: `docs/nabla_plan_v5.pdf`. This is **v1 = rung 1 of the v5 ablation ladder**.

## v1 in one paragraph

Each week, on data through the prior close: filter to liquid names (20-day ADV > $50M,
price > $5, drop the most illiquid Amihud decile); score five factors (12-1 momentum,
guidance velocity, quality, FCF value, volatility premium), winsorize, z-score within
about 10 SIC sector groups, clip at ±3, and sum with fixed equal weights where a missing
factor counts as 0; hold the top 15 equal-weight. Entry band top 15, exit band rank 30,
max 4 names per sector group (30%), 10% per name, 6% for names with a projected filing
inside 30 days. Fully invested. No regime dial, no optimizer, no options yet.

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
| `src/nabla/factors.py` | the five factors and the liquidity filter |
| `src/nabla/combine.py` | winsorize, sector z-score, fixed-five composite |
| `src/nabla/book.py` | banded top-15 selection and capped equal weights |
| `src/nabla/model.py` | the weekly decision, shared by backtest and API |
| `src/nabla/sim.py` | weekly backtest with costs, judge-engine conventions |
| `src/nabla/live.py` | live book; replays recent weeks so bands need no stored state |
| `app/main.py` | API: judged endpoints plus `/model` (config, coverage, top-30 candidates) |
| `config/model.json` | every v1 parameter |

## Point-in-time and leakage guards

- As-of date is the last trading day in the data, never `date.today()`.
- Signals for a rebalance on day t use data through t-1; trades happen at t's close.
- Backtest stops at the SDK holdout cutoff and holds back a further 6 months for the go/no-go.
- Splits are back-adjusted only where the raw series shows the jump, so adjusted data is untouched.
- `tests/test_v1.py` perturbs prices and signals after a date and checks nothing before it changes.

## Known limits of v1 (honest list)

- Not yet run on the real data: every result so far is on a synthetic dataset.
- Quality is a neutral placeholder until the filing-date-gated fundamentals version lands.
- Value uses the state vector's FCF gap (`log_fv_gap`), not earnings yield.
- The earnings cap uses `days_to_next_report`, a projected SEC filing date that lags the
  actual earnings release.
- The universe is today's survivors; backtest returns flatter concentrated books.
- Price momentum is price-only; dividends are not in the signal.
