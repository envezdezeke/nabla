"""Block commits and pushes that could carry Bloomberg data (docs/BLOOMBERG_RULES.md).

    python scripts/check_vendor_data.py              # staged files (git pre-commit hook)
    python scripts/check_vendor_data.py --outgoing   # files in commits not yet pushed
    python scripts/check_vendor_data.py --claude-hook  # Claude Code PreToolUse hook (JSON on stdin)

Exit 0 = clean. Exit 1 (git) or 2 (Claude hook) = blocked, with the reasons printed.
A person who has checked that a flagged figure or JSON file is not built from Bloomberg data
may set NABLA_REVIEWED_NOT_BLOOMBERG=1. AI tools must never set it.
"""
from __future__ import annotations

import json
import os
import re
import subprocess
import sys
from pathlib import PurePosixPath

DATA_DIRS = ("artifacts/", "data/", "bbg/", "bloomberg/")
DATA_EXT = {".csv", ".tsv", ".parquet", ".feather", ".arrow", ".pkl", ".pickle", ".xlsx", ".xls",
            ".xlsm", ".h5", ".hdf5", ".db", ".sqlite", ".npz", ".npy", ".zip", ".gz", ".ipynb"}
REVIEW_EXT = {".png", ".jpg", ".jpeg", ".svg", ".pdf", ".html", ".json", ".txt"}
ALLOWED = {"config/model.json", ".claude/settings.json"}
MAX_BYTES = 1_000_000


def git(*args: str) -> str:
    return subprocess.run(["git", *args], capture_output=True, text=True, check=False).stdout


def staged() -> list[str]:
    return [p for p in git("diff", "--cached", "--name-only", "--diff-filter=ACMR").splitlines() if p]


def outgoing() -> list[str]:
    upstream = git("rev-parse", "--abbrev-ref", "--symbolic-full-name", "@{u}").strip() or "origin/main"
    out = git("diff", "--name-only", "--diff-filter=ACMR", f"{upstream}...HEAD")
    return [p for p in out.splitlines() if p]


def size_in_index(path: str) -> int:
    obj = git("ls-files", "-s", "--", path).split()
    if len(obj) >= 2:
        n = git("cat-file", "-s", obj[1]).strip()
        if n.isdigit():
            return int(n)
    try:
        return os.path.getsize(path)
    except OSError:
        return 0


def problems(paths: list[str]) -> list[str]:
    reviewed = os.environ.get("NABLA_REVIEWED_NOT_BLOOMBERG") == "1"
    found = []
    for path in paths:
        p = path.replace("\\", "/")
        low = p.lower()
        ext = PurePosixPath(low).suffix
        if low.startswith(DATA_DIRS) or any(f"/{d}" in low for d in DATA_DIRS):
            found.append(f"{p}: in a data folder")
        elif ext in DATA_EXT:
            found.append(f"{p}: data file type ({ext})")
        elif size_in_index(p) > MAX_BYTES:
            found.append(f"{p}: larger than 1 MB")
        elif ext in REVIEW_EXT and p not in ALLOWED and not reviewed:
            found.append(f"{p}: figure/JSON/text file needs a person to confirm it is not Bloomberg data")
    return found


def report(found: list[str]) -> str:
    return ("Blocked by the Bloomberg data rules (docs/BLOOMBERG_RULES.md):\n"
            + "\n".join(f"  - {f}" for f in found)
            + "\nRemove these files from the commit (git restore --staged <file>). Bloomberg data and "
              "anything built from it stays on the terminal machine. If a flagged figure or JSON file is "
              "not from Bloomberg, a person (never an AI tool) may commit it with "
              "NABLA_REVIEWED_NOT_BLOOMBERG=1.")


def main() -> int:
    if "--claude-hook" in sys.argv:
        try:
            cmd = json.load(sys.stdin).get("tool_input", {}).get("command", "")
        except (ValueError, AttributeError):
            return 0
        # look only at the shell commands themselves, not at text inside them (heredocs, messages)
        segs = [s.strip() for s in re.split(r"&&|\|\||;|\||\n", cmd)]
        env = r"^(?:(?:export\s+)?\w+=\S*\s+)*"
        commits = [s for s in segs if re.match(env + r"git\s+(?:-C\s+\S+\s+)?commit\b", s)]
        pushes = [s for s in segs if re.match(env + r"git\s+(?:-C\s+\S+\s+)?push\b", s)]
        adds = [s for s in segs if re.match(env + r"git\s+(?:-C\s+\S+\s+)?add\b", s)]
        if any(re.search(r"\s--no-verify\b|\s-n\b", s) for s in commits) or \
                any(re.search(r"\s--no-verify\b", s) for s in pushes):
            print("Blocked: --no-verify skips the Bloomberg data check (docs/BLOOMBERG_RULES.md).", file=sys.stderr)
            return 2
        if any(re.match(r"^(?:export\s+)?NABLA_REVIEWED_NOT_BLOOMBERG=", s) for s in segs):
            print("Blocked: only a person may set NABLA_REVIEWED_NOT_BLOOMBERG (docs/BLOOMBERG_RULES.md).",
                  file=sys.stderr)
            return 2
        paths = (staged() if commits else []) + (outgoing() if pushes else [])
        if commits and (adds or any(re.search(r"\s(-a|--all|-am)\b", s) for s in commits)):
            paths += [p for p in git("diff", "--name-only", "--diff-filter=ACMR").splitlines() if p]
        if commits and adds:  # files the same command is about to stage
            paths += [p for p in git("ls-files", "--others", "--exclude-standard").splitlines() if p]
        found = problems(paths)
        if found:
            print(report(found), file=sys.stderr)
            return 2
        return 0
    found = problems(outgoing() if "--outgoing" in sys.argv else staged())
    if found:
        print(report(found), file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
