#!/bin/sh
#$ -S /bin/sh
#$ -cwd
#$ -V
#$ -q all.q
# request 8 cores on a compute node (velox/UGE)
#$ -pe openmpi8 8
#$ -N cri_esperanto_8w
#$ -o logs/cri_esperanto_qsub_20100101_20251108_8w.out
#$ -e logs/cri_esperanto_qsub_20100101_20251108_8w.err

set -eu

ulimit -s unlimited
export OMP_NUM_THREADS=8
cd "$SGE_O_WORKDIR" || exit 1

OUT_DIR="output/cri_esperanto_20100101_20251108_parallel_8w"
LOG_PREFIX="logs/cri_esperanto_parallel_20100101_20251108_8w"
mkdir -p "$OUT_DIR" "$(dirname "$LOG_PREFIX")"

# Chunk the crawl into ranges that we know currently yield content.
# (Legacy .htm years 2010-2015 and modern Nuxt years 2021-2025.)
RANGES="
2010-01-01:2012-12-31
2013-01-01:2015-12-31
2021-01-01:2025-11-08
"

run_range() {
  start_date="$1"
  end_date="$2"
  start_year=$(printf '%s' "$start_date" | cut -c1-4)
  end_year=$(printf '%s' "$end_date" | cut -c1-4)
  # Remove existing JSONL files for the years covered by this run
  # so we don't append duplicates when re-running.
  year="$start_year"
  while [ "$year" -le "$end_year" ]; do
    rm -f "${OUT_DIR}/${year}.jsonl"
    year=$((year + 1))
  done
  echo "[CRI] Collecting ${start_date} -> ${end_date}" >> "${LOG_PREFIX}.out"
  python3 -m cri_esperanto.parallel_scraper \
    --since "${start_date}" \
    --until "${end_date}" \
    --workers 8 \
    --throttle 0.2 \
    --output-dir "$OUT_DIR" \
    --verbose \
    >> "${LOG_PREFIX}.out" 2>> "${LOG_PREFIX}.err"
}

for entry in $RANGES; do
  START="${entry%:*}"
  END="${entry#*:}"
  run_range "$START" "$END"
done
