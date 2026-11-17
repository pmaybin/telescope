#!/usr/bin/env python3
"""Export docs/prompts/prompt-log.csv to frontend/src/architecture/prompt-log.json.

The frontend Docker build context is frontend/ only, so the page reads a
generated JSON copy of the log. Output is deterministic.

Usage:
  scripts/export_prompt_log.py          # (re)write the JSON
  scripts/export_prompt_log.py --check  # exit 1 if the JSON is stale
"""
import argparse
import csv
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CSV_PATH = ROOT / "docs" / "prompts" / "prompt-log.csv"
JSON_PATH = ROOT / "frontend" / "src" / "architecture" / "prompt-log.json"
META_PATH = JSON_PATH.with_name("prompt-log-meta.json")
SOURCE = "docs/prompts/prompt-log.csv"


def _entries(csv_path: Path) -> list[dict[str, object]]:
    entries: list[dict[str, object]] = []
    if csv_path.exists():
        with csv_path.open(newline="", encoding="utf-8") as f:
            for n, row in enumerate(csv.DictReader(f), start=1):
                entries.append(
                    {
                        "n": n,
                        "timestamp_utc": row["timestamp_utc"],
                        "actor": row["actor"],
                        "from": row["from"],
                        "to": row["to"],
                        "model": row["model"],
                        "effort": row["effort"],
                        "bead_id": row["bead_id"],
                        "summary": row["prompt_summary"],
                        "prompt": row["prompt_full"],
                    }
                )
    return entries


def _dump(doc: object) -> str:
    return json.dumps(doc, indent=1, ensure_ascii=False) + "\n"


def render(csv_path: Path = CSV_PATH) -> str:
    return _dump({"generated_from": SOURCE, "entries": _entries(csv_path)})


def render_meta(csv_path: Path = CSV_PATH) -> str:
    """Tiny summary the page shows while the full log is still unloaded."""
    entries = _entries(csv_path)
    return _dump(
        {
            "count": len(entries),
            "human": sum(1 for e in entries if e["actor"] == "human"),
            "first": entries[0]["timestamp_utc"] if entries else "",
            "last": entries[-1]["timestamp_utc"] if entries else "",
        }
    )


def export(
    csv_path: Path = CSV_PATH,
    json_path: Path = JSON_PATH,
    meta_path: Path = META_PATH,
) -> None:
    json_path.parent.mkdir(parents=True, exist_ok=True)
    json_path.write_text(render(csv_path), encoding="utf-8", newline="\n")
    meta_path.write_text(render_meta(csv_path), encoding="utf-8", newline="\n")


def _same(path: Path, expected: str) -> bool:
    return path.exists() and path.read_text(encoding="utf-8") == expected


def is_current(
    csv_path: Path = CSV_PATH,
    json_path: Path = JSON_PATH,
    meta_path: Path = META_PATH,
) -> bool:
    return _same(json_path, render(csv_path)) and _same(meta_path, render_meta(csv_path))


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--check", action="store_true", help="exit 1 if the JSON is stale")
    a = p.parse_args()
    if a.check:
        if is_current():
            return 0
        print(
            "prompt-log.json is stale: run `python3 scripts/export_prompt_log.py`",
            file=sys.stderr,
        )
        return 1
    export()
    return 0


if __name__ == "__main__":
    sys.exit(main())
