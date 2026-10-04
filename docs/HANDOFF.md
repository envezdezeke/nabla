# Handoff: where we are (for a new Claude session)

Read `CLAUDE.md` first (the full v5 plan and rules), then this file.

## Who and what
- Team nabla at the RowdyHacks finance track (UTSA Investment Society): **Jesse** (finance: factors, risk rules, audit doc, pitch; GitHub `FroyoMojo`) and **Ezekiel** (quant: pipeline, backtest, API, deploy; GitHub `envezdezeke`, repo owner).
- Deliverable: a FastAPI service + public repo. The judges replay our frozen model through the 30 days after our data ends, one decision at a time; each decision is a full target portfolio (cash is an explicit line, weights sum to 1). Scored mostly on total return.
- Timeline: Sat 6:45 PM to Sun ~11:30 AM submit (see CLAUDE.md for gates and cut rules).

## How Jesse likes to work
- Explain in plain terms; give Mac Terminal commands one at a time, numbered, with what each should print.
- Keep the pitch deck and script updated as the plan changes.
- Work directly on `main`; `git pull` before pushing. Never commit the data token.

## Plan history (so you do not re-suggest cut ideas)
- v1 static factor book -> v3 five factors + cash dial -> v4 added RL bandit, puts, HMM, optimizer -> **v5 (current)** cut the bandit, puts, partial trading and HMM after a red-team review; kept the optimizer with an equal-weight anchor and rule-based stress/panic flags.
- Replay-format fixes applied on top of v5: one deterministic `decide(information_cutoff)`, state rebuilt from data, next-open fills, research backtest = the same function.
- Fixed earlier review issues: composite is a fixed sum over five factors with missing = 0 (not an average); anchor defined on survivors.

## Done so far (all on main, 28 tests passing)
| What | Where |
| --- | --- |
| v1 pipeline (Ezekiel): data loading, split adjustment, factors, composite, bands, weekly backtest, API | `src/nabla/`, `app/main.py`, `scripts/` |
| Quality (gross profit/assets > ROE > margin blend) and value (TTM EPS / price), point-in-time from filings | `src/nabla/fundamentals.py` |
| Liquidity filter (ADV >= $50M, price > $5, drop least liquid 10%) and costs (half-spread 5/10/20 bps + Amihud impact, 1%-of-ADV cap) | `src/nabla/factors.py`, `src/nabla/costs.py` |
| Simple functions for Ezekiel: `liquid_tickers(close, volume)`, `trading_cost(current, target, close, volume)` | `src/nabla/simple.py` |
| Five-bucket factor direction test with red flags (backwards, not monotone, one year, too good) | `src/nabla/diagnostics.py`, `explore/05_factor_buckets.py` |
| Data checks for quality/value (column mapping, splits, known-stock sanity check) | `explore/04_fundamentals_check.py` |
| Limits table with reasons | `docs/AUDIT.md` |
| Organizer questions | `docs/workshop_questions.md` |

## Waiting on real data (token now works on Jesse's Mac and Ezekiel's)
1. `python explore/04_fundamentals_check.py`: confirm the fundamentals column mapping (names were guessed), quarterly vs year-to-date flows, whether EPS is restated for splits (AAPL 2020, NVDA 2024), and the known-stock check (AAPL/MSFT high quality; banks/energy cheap; loss-makers at the bottom of value).
2. `python explore/05_factor_buckets.py`: verdict per factor; flag failures to Ezekiel before the composite is final.
3. Then update `docs/AUDIT.md` (factor results), the deck and the script.

## Jesse's remaining tasks (from the plan)
- Factor signs and IC review, sample holdings review, crowding check.
- Charts (equity curve, drawdown, sector exposure vs SPX) and the ablation table once the backtest runs.
- AUDIT.md: factor rationale and results, organizer answers, survivorship, what was cut and why. README.
- Pitch: update slides with results; rehearse twice.

## Environment notes
- Mac: Python 3.12 venv in `nabla/.venv`; install the SDK with `pip install ../utsa-investment-hackathon/sdk` (editable `-e` install did not import).
- Each new Terminal: `source .venv/bin/activate`, then `export SV_DATA_ROOT=https://pop-os.tail01ad.ts.net` and `export SV_DATA_TOKEN=...`.
- `svq doctor` printing `data root : None` is normal for the hosted server; it then counts tables slowly.
- Cloud sessions need `pop-os.tail01ad.ts.net` allowed in Network access, and only work if the server is publicly reachable.

## Links
- Pitch deck (14 slides, private until shared): https://claude.ai/artifact/WXnNHkqcM5McGXFsJ2VqVQ
- Pitch script: https://claude.ai/code/artifact/31e44f1a-30cf-40d1-a234-0b3b8ed1af20
- Audit of the plans (for Ezekiel): https://claude.ai/code/artifact/6d8c695c-f533-4b06-9d40-77a848b4ad16
- Plans: `docs/nabla_plan_v3.pdf`, `docs/nabla_plan_v5.pdf`
