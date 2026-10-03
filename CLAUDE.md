# nabla

RowdyHacks, Finance Track. Goal: an "AI" bot that trades equities. Team: Ezekiel + Jesse.

## Status
Early stage. Universe of tickers, data source, broker, and strategy are all TBD. Update this file as decisions get made so every Claude session starts from the same page.

## Hard rules
- Paper trading only. Never wire in live-money credentials.
- Never commit secrets. API keys live in `.env` (gitignored); keep `.env.example` with variable names only.
- Every strategy must be backtested before it touches the paper account. No lookahead bias: signals at time t use data up to t only. Include transaction costs and slippage in backtests.
- Hardcode risk limits in one place (`config`): max position size, max daily loss, max open positions. The bot must respect them even if the strategy says otherwise.
- Keep a log of every order and the reason for it.

## Assumed stack (change if we pick otherwise)
- Python 3.11+, pandas, numpy
- Data: yfinance for quick history; Alpaca or similar for paper execution
- Tests: pytest. Run `pytest` before pushing.

## Suggested layout
```
nabla/
  data/        loaders, caching
  strategies/  one file per strategy, common interface
  backtest/    engine + metrics (Sharpe, max drawdown, hit rate)
  execution/   broker wrapper (paper only)
  config.py    tickers, risk limits
  tests/
```

## Git workflow (two people, one repo)
- Do not push directly to `main`. One branch per person/feature (`ezekiel/<thing>`, `jesse/<thing>`), PR into `main`.
- Pull/rebase from `main` before starting work and before opening a PR.
- Small commits, clear messages. Split work by folder to avoid merge conflicts (e.g. one person on `data/` + `backtest/`, the other on `strategies/` + `execution/`).

## Collaborator setup (Jesse)
1. Accept the GitHub repo invite (repo: `envezdezeke/nabla`, needs write access).
2. Have a Claude account with Claude Code access (claude.ai/code or the CLI). Connect GitHub under claude.ai Settings > Connectors, and install the Claude GitHub App on the repo: https://github.com/apps/claude/installations/select_target
3. Clone the repo; Claude Code reads this `CLAUDE.md` automatically.
4. Create a personal `.env` from `.env.example` with your own paper-trading API keys. Do not share keys over chat or commit them.
5. Personal Claude settings go in `.claude/settings.local.json` (gitignored). Shared settings go in `.claude/settings.json`.
