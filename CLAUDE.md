# nabla — RowdyHacks Finance Track

## The challenge
- RowdyHacks Finance Track, run by the Investment Society.
- Build an AI that trades a $1M portfolio.
- Scored on a blind 30-day holdout (~21 trading days). Short window = mostly noise, so favor robust signals over complex models.
- Starter code provided (arrives Sat 12 PM). Bloomberg data provided.
- Investment Society workshop: Sat 3:15 PM.
- 24 hours total. Team of two: Jesse (finance: factors, risk rules, pitch) and teammate (quant: pipeline, backtester, ML).

## Open questions (fill in once known)
- Scoring metric: total return / Sharpe / drawdown-penalized? -> TBD
- Universe: -> TBD
- Trading frequency (daily rebalance vs. one allocation): -> TBD
- Shorting / leverage / position limits / transaction costs: -> TBD
- Holdout is future data or a withheld past period: -> TBD
- What counts as "AI" (ML required?): -> TBD

Scoring drives strategy: raw return -> more concentrated, higher-vol tilt (tournament logic). Sharpe -> diversify, emphasize low-vol and quality, keep risk overlay strong.

## Factors (formula / rationale / Bloomberg field — map to actual dataset names)
1. Momentum 12-1: return from t-12m to t-1m (skip last month, which tends to reverse). Persistent trends from investor underreaction (Jegadeesh & Titman 1993). `PX_LAST`
2. Short-term reversal: negative of last 1-month return. Overshoots snap back within weeks. Low weight or drop if trading costs are high / can't rebalance. `PX_LAST`
3. Estimate revisions: % change in consensus forward EPS over 1-3 months. Revisions trend and lead earnings surprises; strong short-horizon signal. `BEST_EPS`
4. Quality: ROE or gross profit / total assets; penalize high debt/equity. Profitable firms outperform and hold up in selloffs (Novy-Marx 2013). `RETURN_COM_EQY`, `TOT_DEBT_TO_TOT_EQY`
5. Low volatility: negative 60-day realized vol. Similar/better returns with less risk (Frazzini & Pedersen, betting against beta). Daily `PX_LAST` or `VOLATILITY_90D`
6. Value: earnings yield (1 / P/E), optionally book-to-market. Slow; mainly diversifies momentum (negatively correlated). `PE_RATIO`
Optional: post-earnings drift (if earnings fall in holdout), short interest (as an avoid-filter).

## Combining
1. Winsorize each factor at 1st/99th percentile.
2. Z-score within sector (avoid value = all banks/energy, low-vol = all utilities).
3. Starting weights: momentum 25%, revisions 25%, quality 20%, low-vol 15%, value 10%, reversal 5%. Adjust after scoring rules are known.
4. Rank on composite; hold top N, equal-weight or inverse-vol weight.

## Risk rules
- Max position ~5%, sector cap ~25% (finalize once constraints known).
- Volatility targeting: scale exposure down when realized vol / VIX spikes.

## Data hygiene (non-negotiable)
- Lag fundamentals to actual report date, or 45-60 days after quarter end if report dates unavailable. No look-ahead.
- Use adjusted prices (splits/dividends).
- Watch survivorship bias; include transaction costs if rebalancing often.
- Walk-forward validation only, never random train/test splits.
- Few parameters; prefer stable regions over best backtest.

## Plan
- Sat 12-2: read starter code + rules; teammate submits momentum baseline; Jesse maps factors to actual Bloomberg fields + lag rules.
- 2-3:15: finalize risk rules as concrete numbers; start pitch outline.
- 3:15: workshop — ask open questions; adjust strategy after.
- 4:30-8: backtest factors individually + combined; sanity-check holdings; drop unstable factors.
- 8-midnight: ML ranker (LightGBM on factor features, walk-forward); keep only if it beats factor model out of sample. Pitch charts: equity curve, drawdown, sector exposure.
- Midnight-3: stress test (2020, 2022), lock and submit final version.
- Sun AM: slides, rehearse twice. No model changes in the final hours.

## Repo
https://github.com/envezdezeke/nabla — always `git pull` before pushing.
