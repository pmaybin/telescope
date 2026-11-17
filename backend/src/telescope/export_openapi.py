"""Export the OpenAPI contract deterministically: `python -m telescope.export_openapi [path]`."""

from __future__ import annotations

import json
import sys
from pathlib import Path

from telescope.main import create_app

DEFAULT_PATH = Path(__file__).resolve().parents[3] / "openapi.json"


def render() -> str:
    return json.dumps(create_app().openapi(), indent=2, sort_keys=True) + "\n"


def main() -> None:
    path = Path(sys.argv[1]) if len(sys.argv) > 1 else DEFAULT_PATH
    path.write_text(render(), encoding="utf-8")
    print(f"wrote {path}")


if __name__ == "__main__":
    main()
