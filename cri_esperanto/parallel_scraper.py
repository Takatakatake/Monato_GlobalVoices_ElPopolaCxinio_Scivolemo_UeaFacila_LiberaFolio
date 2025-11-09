#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import argparse
import logging
from datetime import datetime, date

from cri_esperanto.cri_esperanto_lib import CRIConfig, collect_and_dump


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="CRI Esperanto 2010年以降 全記事収集（並列）")
    p.add_argument("--since", default="2010-01-01", help="開始日 (YYYY-MM-DD)")
    p.add_argument("--until", default=datetime.utcnow().date().isoformat(), help="終了日 (YYYY-MM-DD)")
    p.add_argument("--workers", type=int, default=16, help="並列ワーカー数 (default: 16)")
    p.add_argument("--throttle", type=float, default=0.5, help="1リクエストあたりのスロットル秒")
    p.add_argument("--output-dir", default="output/cri_esperanto", help="出力ディレクトリ (年別JSONL)")
    p.add_argument("--verbose", action="store_true", help="詳細ログ")
    return p.parse_args()


def main() -> None:
    args = parse_args()
    logging.basicConfig(level=logging.DEBUG if args.verbose else logging.INFO, format="%(levelname)s: %(message)s")

    try:
        sd = date.fromisoformat(args.since)
    except Exception:
        raise SystemExit("--since は YYYY-MM-DD 形式で指定してください")
    try:
        ed = date.fromisoformat(args.until)
    except Exception:
        raise SystemExit("--until は YYYY-MM-DD 形式で指定してください")

    cfg = CRIConfig(
        start_date=sd,
        end_date=ed,
        max_workers=args.workers,
        throttle_sec=args.throttle,
    )

    files = collect_and_dump(cfg, out_dir=args.output_dir)
    if not files:
        logging.warning("出力は作成されませんでした。後ほど再試行してください。")
    else:
        for y, path in sorted(files.items()):
            logging.info("%s -> %s", y, path)


if __name__ == "__main__":
    main()
