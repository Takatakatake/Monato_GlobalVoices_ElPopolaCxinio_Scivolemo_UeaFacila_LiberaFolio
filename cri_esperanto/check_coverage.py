#!/usr/bin/env python3

"""
Utility script to summarise collected JSONL files and highlight coverage gaps.
"""

from __future__ import annotations

import argparse
import json
from datetime import datetime
from pathlib import Path
from typing import Tuple


def inspect_file(path: Path) -> Tuple[int, datetime | None, datetime | None]:
    count = 0
    earliest: datetime | None = None
    latest: datetime | None = None
    with path.open(encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            count += 1
            try:
                obj = json.loads(line)
                published = obj.get("published")
                if not published:
                    continue
                dt = datetime.fromisoformat(published)
                if earliest is None or dt < earliest:
                    earliest = dt
                if latest is None or dt > latest:
                    latest = dt
            except Exception:
                continue
    return count, earliest, latest


def format_dt(dt: datetime | None) -> str:
    return dt.isoformat() if dt else "-"


def main() -> None:
    p = argparse.ArgumentParser(description="Report per-year coverage for collected CRI JSONL files.")
    p.add_argument("directory", nargs="?", default="output/cri_esperanto", help="Directory containing <year>.jsonl files")
    args = p.parse_args()

    root = Path(args.directory)
    if not root.exists():
        raise SystemExit(f"{root} does not exist")

    files = sorted(root.glob("*.jsonl"))
    if not files:
        raise SystemExit(f"No JSONL files found under {root}")

    for path in files:
        year = path.stem
        count, earliest, latest = inspect_file(path)
        print(f"{year}: {count} articles, {format_dt(earliest)} -> {format_dt(latest)}")


if __name__ == "__main__":
    main()
