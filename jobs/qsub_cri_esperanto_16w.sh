#!/bin/sh
#$ -S /bin/sh
#$ -cwd
#$ -V
#$ -q all.q
#$ -pe openmpi16 16
#$ -N cri_esperanto_16w
#$ -o logs/cri_esperanto_qsub_20100101_20251108_16w.out
#$ -e logs/cri_esperanto_qsub_20100101_20251108_16w.err

set -euo pipefail

ulimit -s unlimited
export OMP_NUM_THREADS=16
cd "$SGE_O_WORKDIR" || exit 1

PYTHON_BIN="./.venv/bin/python"
if [ ! -x "$PYTHON_BIN" ]; then
  PYTHON_BIN="$(command -v python3)"
fi

OUT_DIR="output/cri_esperanto_20100101_20251108_parallel_16w"
LOG_PREFIX="logs/cri_esperanto_parallel_20100101_20251108_16w"
mkdir -p "$OUT_DIR" "$(dirname "$LOG_PREFIX")"

exec > "${LOG_PREFIX}.out" 2> "${LOG_PREFIX}.err"

echo "[CRI] Starting segmented collection with 16 workers"

CRI_CMD() {
  "$PYTHON_BIN" -m cri_esperanto.parallel_scraper \
    --since "$1" \
    --until "$2" \
    --workers 16 \
    --throttle 0.2 \
    --output-dir "$3" \
    --verbose
}

MERGE_JSONL() {
  target="$1"
  source="$2"
  "$PYTHON_BIN" - <<'PY' "$target" "$source"
import json, sys
from pathlib import Path

target = Path(sys.argv[1])
source = Path(sys.argv[2])

seen = set()
records = []

def load_lines(path: Path) -> None:
    if not path.exists():
        return
    with path.open("r", encoding="utf-8") as fh:
        for line in fh:
            line = line.rstrip("\n")
            if not line:
                continue
            try:
                obj = json.loads(line)
            except Exception:
                continue
            url = obj.get("url")
            if url in seen:
                continue
            seen.add(url)
            records.append(json.dumps(obj, ensure_ascii=False))

load_lines(target)
load_lines(source)

target.parent.mkdir(parents=True, exist_ok=True)
with target.open("w", encoding="utf-8") as fh:
    for line in records:
        fh.write(line + "\n")
PY
}

TMP_ROOT="$(mktemp -d "${OUT_DIR}/tmp_run_XXXXXX")"
trap 'rm -rf "$TMP_ROOT"' EXIT

run_legacy_range() {
  start_date="$1"
  end_date="$2"
  tmp_dir="$(mktemp -d "${TMP_ROOT}/legacy_${start_date}_${end_date}_XXXXXX")"
  echo "[CRI] Legacy range ${start_date} -> ${end_date}"
  if CRI_CMD "$start_date" "$end_date" "$tmp_dir"; then
    for file in "$tmp_dir"/*.jsonl; do
      year="$(basename "$file" .jsonl)"
      mv "$file" "${OUT_DIR}/${year}.jsonl"
      echo "  - Updated ${year}.jsonl (${start_date}〜${end_date})"
    done
  else
    echo "[CRI][ERROR] Legacy range ${start_date} -> ${end_date} failed" >&2
    echo "[CRI][ERROR] Keeping existing files untouched" >&2
    exit 1
  fi
  rm -rf "$tmp_dir"
}

run_modern_range() {
  start_date="$1"
  end_date="$2"
  tmp_dir="$(mktemp -d "${TMP_ROOT}/modern_${start_date}_${end_date}_XXXXXX")"
  echo "[CRI] Modern range ${start_date} -> ${end_date}"
  if CRI_CMD "$start_date" "$end_date" "$tmp_dir"; then
    for file in "$tmp_dir"/*.jsonl; do
      year="$(basename "$file" .jsonl)"
      if [ -s "$file" ]; then
        MERGE_JSONL "${OUT_DIR}/${year}.jsonl" "$file"
        echo "  - Merged ${year}.jsonl (${start_date}〜${end_date})"
      fi
    done
  else
    echo "[CRI][ERROR] Modern range ${start_date} -> ${end_date} failed" >&2
    echo "[CRI][ERROR] Existing files preserved" >&2
    exit 1
  fi
  rm -rf "$tmp_dir"
}

LEGACY_RANGES="
2010-01-01:2010-12-31
2011-01-01:2011-12-31
2012-01-01:2012-12-31
2013-01-01:2013-12-31
2014-01-01:2014-12-31
2015-01-01:2015-12-31
"

for range in $LEGACY_RANGES; do
  start="${range%:*}"
  end="${range#*:}"
  run_legacy_range "$start" "$end"
done

MODERN_RANGES="
2021-01-01:2021-12-31
2023-01-01:2023-12-31
2024-01-01:2024-12-31
2025-01-01:2025-11-08
"

for range in $MODERN_RANGES; do
  start="${range%:*}"
  end="${range#*:}"
  run_modern_range "$start" "$end"
done

echo "[CRI] Completed segmented collection"
