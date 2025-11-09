#!/bin/sh

set -eu

# このスクリプトは Scivolemo 用の 8 並列取得の例です。
# 期間・出力先は必要に応じて変更してください。

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$SCRIPT_DIR"

OUT_DIR="../output/scivolemo_parallel_8w"
LOG_PREFIX="../logs/scivolemo_parallel_8w"
mkdir -p "$OUT_DIR" "$(dirname "$LOG_PREFIX")"

python3 parallel_scraper.py \
  --start 2018-01-01 \
  --end 2025-10-19 \
  --workers 8 \
  --out "$OUT_DIR" \
  > "${LOG_PREFIX}.out" 2> "${LOG_PREFIX}.err"

