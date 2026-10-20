# Bloomberg transition: handoff for the next session

Read `docs/BLOOMBERG_RULES.md` and the top of `CLAUDE.md` first. They override everything else.
This file holds no Bloomberg data: no tickers, weights or prices, only code and aggregates.

## Where things stand (2026-10-20)
- **Archive:** tag `statevector-v1.4` (commit `1a2a1b0`, on GitHub) is the model on statevector inputs. `main` is unchanged and is still that version.
- **Branch:** `bloomberg-data` is the working branch for the Bloomberg version. Do not work on `main`.
- **Rule 6** (Claude may write and run code on Bloomberg data, never read or print it) was confirmed with the lab administrator by Ezekiel on 2026-10-20. Per-stock weights were pasted into one earlier chat by the user, so they reached Anthropic's servers; the lab administrator may need to hear about it. Do not repeat tickers or weights in files, commits or chat.
- **Model run:** v1.4 ran end to end on cached Bloomberg data through 2026-10-20: 15 names, 0% cash, stress and panic flags off, factor coverage among liquid names: momentum 100%, guidance 100%, quality 93%, value 99%.

## Two designs exist: reconcile first
`origin/bloomberg-data` (commit `14067e7`, pushed 2026-10-20 17:36 from the user's account) is a separate Bloomberg design: `src/nabla/store.py` (local parquet `Store` replacing the statevector `Dataset`), `src/nabla/ingest.py`, `scripts/bbg_ingest.py`, `scripts/bbg_check.py`, its own `src/nabla/bloomberg.py`, tests, and a `CLAUDE.md` note that nabla is now a paper-portfolio forward test, no longer a competition entry. Field mnemonics there are unverified.

This work is on branch `bloomberg-data-adapter` (same commits as the local `bloomberg-data`) so nothing on `origin/bloomberg-data` was overwritten. Both add `src/nabla/bloomberg.py` and both use `artifacts/bbg/` with different layouts, so they conflict. Next step: pick one data path, then port the other's useful parts. What this branch adds that the other lacks: a daily hit ledger, a coverage ledger that never re-requests, verified field names (see Data and limits; all returned data on the Terminal), the BEST_EPS guidance substitute, and a model run on real data. Ask the user before merging either way.

## What was built
| File | Purpose |
| --- | --- |
| `src/nabla/bloomberg.py` | blpapi session (`Terminal`), daily hit ledger (`Budget`), per-field cache with coverage ledger (`Cache`), and `BbgDataset`, which serves the cache in the shape of the statevector `Dataset` so `live.build_book` and `decide.decide` run unchanged |
| `scripts/bbg_pull.py` | `python scripts/bbg_pull.py` plans (requests nothing); `--run` pulls what the cache lacks, within the daily budget |
| `scripts/bbg_live.py` | runs the frozen model on the cache; prints aggregates only; writes `artifacts/bbg/live_book.{json,csv}` |
| `src/nabla/pipeline.py` | cluster-coverage test now measures how much of the universe the frozen clusters cover (was the reverse, which forced a refit on a 503-name universe) |

All data lives in `artifacts/bbg/` (gitignored). Never use `scripts/build_book.py` with Bloomberg data: it writes the tracked `config/book.json`.

## Data and limits
- Daily cap set to 500,000 hits (`NABLA_BBG_DAILY_HITS`, default 500000; tolerant of stray characters). The monthly unique-securities cap is not known; about 505 securities are used so far. Check `DAPI<GO>`.
- Pulled so far: PX_LAST, PX_VOLUME (split-adjusted, not dividend-adjusted) from about July 2025 (about 470 calendar days); SPX from 2018; BEST_EPS (override 1BF) for about 14 weeks; quarterly fundamentals IS_EPS, SALES_REV_TURN, GROSS_PROFIT, IS_OPER_INC, NET_INCOME, CF_FREE_CASH_FLOW, EBITDA, NET_DEBT, GROSS_MARGIN and ANNOUNCEMENT_DT from 2022; EXPECTED_REPORT_DT snapshot. About 457,000 hits were used on 2026-10-20.
- The ledger only counts hits sent by this code.
- Universe: S&P 500 members (`INDX_MEMBERS` of SPX Index), cached in `artifacts/bbg/universe.json`. The statevector model used about 1,250 names.
- Total assets and equity are deliberately not pulled, so quality keeps its v1.4 margin-blend definition.

## Differences from the statevector v1.4 (the book is not the same model)
1. `guidance_range_velocity` is replaced by 20-trading-day change in consensus EPS (BEST_EPS, 1BF) divided by price. Unvalidated.
2. `days_to_next_report` comes from ANNOUNCEMENT_DT history plus EXPECTED_REPORT_DT.
3. `atm_iv` and `log_fv_gap` are not pulled (vol premium weight is 0; value uses filed EPS).
4. Universe is the S&P 500, not the statevector universe.
5. Frozen sector clusters from `config/clusters.json` still apply; names missing from them get "other" (uncapped).

## Open items, in order
1. **PEAD coverage is 0%** (weight 0, so no effect on the book). Find out why: likely the SUE year-over-year date match (330 to 400 days) or period-end date alignment in the fundamentals. Check with aggregates only.
2. **Backtest the Bloomberg version** from 2018 and compare with the archived statevector v1.4 numbers in `docs/AUDIT.md` (14.2%/yr vs 12.4% S&P, Sharpe 0.70, max drawdown 33% in development). Needs next-open prices (PX_OPEN) and price history back to 2018: roughly 1.1M hits for 503 securities, so spread it over several days within the cap. Universe prefiltered today is survivorship-biased for a backtest; say so.
3. **Check book concentration:** clusters of correlated names (memory/storage, refiners, steel) in the live book may slip past the 30% cluster cap.
4. **Decide the endpoints:** `app/main.py`, `/backtest`, `/screen` and the judges' `check.py` read statevector. Bloomberg data cannot leave this machine, so a deployed server cannot use it.
5. **Statistical ideas using more of Bloomberg** (the user's plan): other estimate fields, implied vol and skew, short interest, analyst revisions, and statistical arbitrage tests (pairs and cluster residual reversion). Every new idea goes through the leak tests in `scripts/audit.py`.
6. `tests/` still use the statevector SDK fixture (`nabla.synthetic`), which is not installed on this machine; add Bloomberg-adapter tests that use a fake terminal.

## Working rules that bit us
- Never run a pull without confirming the budget first; `bbg_pull.py` without `--run` is the plan.
- Don't `head`, print or paste cached data; print counts and aggregates only. The user views weights in their own terminal outside Claude Code.
- Commit code and markdown only. `scripts/check_vendor_data.py` runs on every commit and push; if it blocks, unstage the files. Never set `NABLA_REVIEWED_NOT_BLOOMBERG` and never use `--no-verify`.
- Python 3.14 with pandas 3.0 on this machine (the repo says pandas >= 2). `blpapi` installs from Bloomberg's index: `pip install --index-url=https://blpapi.bloomberg.com/repository/releases/python/simple/ blpapi`.
- Other packages installed here: numpy, polars, pyarrow, pytest, scipy, scikit-learn.

## Start prompt for the new chat
"Read CLAUDE.md, docs/BLOOMBERG_RULES.md and docs/HANDOFF_BLOOMBERG.md in the nabla repo, check out the bloomberg-data branch, and continue with the open items. Rule 6 is confirmed. Do not pull from Bloomberg without telling me the planned hits first, and never print data."
