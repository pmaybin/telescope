#!/usr/bin/env python3
"""Append a properly escaped row to docs/prompts/prompt-log.csv.

Usage:
  scripts/log_prompt.py --actor human --from human --to architect \
      --model claude-opus-5-5 --effort high --bead "" \
      --summary "short summary" (--full "text" | --full-file path | stdin)
"""
import argparse
import csv
import sys
from datetime import datetime, timezone
from pathlib import Path

LOG = Path(__file__).resolve().parent.parent / "docs" / "prompts" / "prompt-log.csv"
COLUMNS = ["timestamp_utc", "actor", "from", "to", "model", "effort",
           "bead_id", "prompt_summary", "prompt_full"]
ACTORS = {"human", "architect", "subagent", "researcher"}


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--actor", required=True, choices=sorted(ACTORS))
    p.add_argument("--from", dest="src", required=True)
    p.add_argument("--to", dest="dst", required=True)
    p.add_argument("--model", default="")
    p.add_argument("--effort", default="", choices=["", "low", "medium", "high", "max"])
    p.add_argument("--bead", default="")
    p.add_argument("--summary", required=True)
    g = p.add_mutually_exclusive_group()
    g.add_argument("--full")
    g.add_argument("--full-file")
    a = p.parse_args()

    if a.full is not None:
        full = a.full
    elif a.full_file:
        full = Path(a.full_file).read_text(encoding="utf-8")
    else:
        full = sys.stdin.read()

    LOG.parent.mkdir(parents=True, exist_ok=True)
    new = not LOG.exists() or LOG.stat().st_size == 0
    with LOG.open("a", newline="", encoding="utf-8") as f:
        w = csv.writer(f, quoting=csv.QUOTE_MINIMAL)
        if new:
            w.writerow(COLUMNS)
        ts = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        w.writerow([ts, a.actor, a.src, a.dst, a.model, a.effort, a.bead, a.summary, full])


if __name__ == "__main__":
    main()
