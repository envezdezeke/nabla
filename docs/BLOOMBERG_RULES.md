# Bloomberg data rules

These rules apply to everyone working on nabla, people and AI tools alike, whenever Bloomberg
data is involved. They come from the school's Bloomberg Terminal license. When unsure, ask the
lab administrator before doing it, not after.

## The rules

1. **Bloomberg data never leaves the terminal machine.** That includes raw data and anything built
   from it: no copies to personal computers, USB drives, email, cloud storage, chat apps, or
   GitHub.
2. **No Bloomberg data in the repo, ever.** The repo is public. Commit code only. That covers
   prices, fundamentals, estimates, index members, and anything derived from them: cleaned
   tables, factor scores, holdings files built on Bloomberg inputs, and charts or images of
   Bloomberg data.
3. **No altering or redistributing Bloomberg data.** Use it for research on the terminal only.
4. **Keep it in the local cache folder only.** Everything pulled from Bloomberg goes in
   `artifacts/bbg/` on the terminal machine. That folder is gitignored and stays there.
5. **Respect the download limits.** The Desktop API has daily and monthly caps that apply to the
   school's account. Pull in batches, cache every pull, and never re-request data you already
   have.
6. **AI tools must not read or print Bloomberg data.** Claude Code sends what it reads to
   Anthropic's servers, which would move data off the terminal. Claude may write and run code that
   uses Bloomberg data, but must not open, print, or paste the data itself (no `head` on a data file,
   no printing DataFrames, no pasting rows into chat). Scripts should print only aggregate results.
   Confirm with the lab administrator that this setup is allowed before relying on it.
7. **Only aggregate results leave the terminal**, and only after a person checks them: summary
   numbers such as annual return, Sharpe ratio, or maximum drawdown, typed into a write-up. Never
   tables of prices or per-stock values.
8. **Never bypass the safety check.** Do not use `git commit --no-verify`, and do not set
   `NABLA_REVIEWED_NOT_BLOOMBERG` unless you are a person who has checked the files yourself.

## The automatic check

`scripts/check_vendor_data.py` blocks a commit or push that includes:

- anything under `artifacts/`, `data/`, `bbg/` or `bloomberg/`
- data files (`.csv`, `.parquet`, `.xlsx`, `.pkl`, `.feather`, `.h5`, `.db` and similar)
- Jupyter notebooks (their saved outputs can contain data)
- any file over 1 MB
- new or changed images, PDFs, HTML, JSON or text files, except `config/model.json`, until a
  person confirms they were not built from Bloomberg data (see below)

It runs in two places:

- **Claude Code** runs it automatically before any `git commit` or `git push` (`.claude/settings.json`).
- **Git** runs it before every commit once you turn it on. Run this once on each machine:

  ```bash
  git config core.hooksPath .githooks
  ```

If the check blocks a figure or JSON file that is genuinely not from Bloomberg (for example a
chart from the organizers' data), a person may commit it with:

```bash
NABLA_REVIEWED_NOT_BLOOMBERG=1 git commit ...
```

AI tools must never set this variable.

## Working setup on the terminal

- Work on a branch (for example `bloomberg-data`), not `main`.
- Install the API on the terminal PC:
  `pip install --index-url=https://blpapi.bloomberg.com/repository/releases/python/simple/ blpapi`
- Keep a Bloomberg session logged in; the API connects to `localhost:8194`.
- Code that reads Bloomberg lives in `src/nabla/bloomberg.py` and writes its cache to
  `artifacts/bbg/`.
