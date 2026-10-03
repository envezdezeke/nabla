# Getting situated

Starter repo: https://github.com/orkid-labs/utsa-investment-hackathon (public). We build a
portfolio-management API on a point-in-time-safe equity dataset and are scored by a
deterministic rubric plus a repo audit. Read `launchpad/README.md`, `launchpad/RULES.md`,
`SUBMISSION.md`, `FEATURES.md`, `DEVIATIONS.md` there first.

## Setup

```bash
git clone https://github.com/orkid-labs/utsa-investment-hackathon
pip install -e utsa-investment-hackathon/sdk/ pandas numpy
export SV_DATA_ROOT=https://pop-os.tail01ad.ts.net   # hosted data (Tailscale host)
export SV_DATA_TOKEN=<team token>                    # from organizers; never commit
svq doctor
```

## Explore, in order

| step | script | what it answers |
|---|---|---|
| 1 | `python explore/01_setup_check.py` | Is the connection live? Panels, universe size, date range, holdout cutoff |
| 2 | `python explore/02_data_tour.py [TICKER]` | Null rates, flag frequencies, feature distributions, PIT fundamentals vs raw, options chain, sectors |
| 3 | `python explore/03_feature_ic.py` | Which of the 27 features rank-predict forward returns (IC, decile spread) |

Step 3 is the launchpad's "first afternoon" exercise. It cuts prices and signals at
`ds.holdout_cutoff()` and drops rows whose forward window would cross it. Overlapping
windows inflate the t-stat, so use it to rank features, not as a significance test.

The scripts were tested against a synthetic dataset (a planted forward signal came back
with IC ~0.19 and a random feature with ~0). They have **not** been run on the real data,
because the build session had no token and could not reach the Tailscale host.

## Rules that decide the design

- Long-only. Weights >= 0, sum ~1.0, cash is the residual. No shorts, no written options.
- Hedge only with bought puts, as OCC tickers (`O:AAPL250117P00220000`) in the holdings array.
- Sealed holdout: the trailing 30 calendar days. Never train or validate on them.
- Fundamentals by filing date (`ds.fundamentals(t, asof=...)`), never by period end.
- Stay inside `ds.universe()` (~1,258 US names). `ORKD` is an intentional sentinel; ignore it.

## Judged endpoints (keep paths and shapes)

`GET /health`, `GET /portfolio/holdings`, `POST /backtest {tickers, weights, start, end}`,
`GET /screen`, `GET /asof`. Points: 100 total, 25 for `/backtest` matching the reference
recompute within 2% (a "better" metric that disagrees scores zero), 15 for latency. Self-score:
`python launchpad/rubric/check.py --base-url http://localhost:8000`.

## Traps noticed while reading the code

- `RULES.md` mentions `POST /holdings` and `{start, end, holdings}`, but `rubric.yaml`,
  `SUBMISSION.md` and the template use `GET /portfolio/holdings` and `{tickers, weights}`.
  Follow the rubric and template.
- `ds.get()` silently caps partitioned panels (`stocks_daily`, `options_daily`, `stocks_minute`)
  at 10,000 rows when no ticker is given. Pass `limit=` or you get a truncated universe.
- `ds.holdout_cutoff()` anchors to the dataset's last trading day. The module-level
  `holdout_cutoff()` anchors to today. Use the `ds.` method.
- The template backtest accepts `rebalance` but ignores it, never prices option legs, and
  treats a missing print as a 0% return. All three are ours to implement properly.
- Estimates are a single 2026-08-28 snapshot, not point-in-time. Treat estimate-derived
  features (`fundamental_surprise` before first guidance) with suspicion.
- `skew_25d` and `rn_kurtosis` are ~52% null. Nulls mean "no liquid chain". Check the flags
  before imputing.

## Open decisions

- Signal: which features survive step 3 on a pre-holdout, walk-forward basis.
- Weighting: equal, inverse-vol, or risk parity, plus a position cap.
- Hedge: whether protective puts are worth their premium. Test it in the backtest.
- Split of work between us (folders, not files) to avoid merge conflicts.
