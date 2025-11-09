#!/bin/sh
#$ -S /bin/sh
#$ -cwd
#$ -V
#$ -q all.q
#$ -pe openmpi8 8
#$ -N gv_eo_8w
#$ -o logs/global_voices_eo_qsub_20100101_20251108_8w.out
#$ -e logs/global_voices_eo_qsub_20100101_20251108_8w.err

ulimit -s unlimited
export OMP_NUM_THREADS=8
cd "$SGE_O_WORKDIR" || exit 1
PYTHON_BIN="./.venv/bin/python"
if [ ! -x "$PYTHON_BIN" ]; then
  PYTHON_BIN="$(command -v python3)"
fi
START="2013-01-01"
END="2025-11-08"
ARCHIVE_START="2010-01-01"
ARCHIVE_END="2012-12-31"

OUT_DIR="output/global_voices_eo_20100101_20251108_parallel_8w"
LOG_PREFIX="logs/global_voices_eo_parallel_20100101_20251108_8w"
mkdir -p "$OUT_DIR" "$(dirname "$LOG_PREFIX")"

# First, backfill 2010-2012 via archive crawl to capture early WordPress content.
"$PYTHON_BIN" "Global Voices en Esperanto/parallel_scraper.py" \
  --start "$ARCHIVE_START" \
  --end "$ARCHIVE_END" \
  --workers 4 \
  --method archive \
  --throttle 0.5 \
  --split-by year \
  --out "$OUT_DIR" \
  > "${LOG_PREFIX}_archive_2010_2012.out" 2> "${LOG_PREFIX}_archive_2010_2012.err"

# Then run the main job for 2013+ with both RESTとFeed/Archive fallback.
"$PYTHON_BIN" "Global Voices en Esperanto/parallel_scraper.py" \
  --start "$START" \
  --end "$END" \
  --workers 8 \
  --method both \
  --throttle 0.5 \
  --split-by year \
  --out "$OUT_DIR" \
  > "${LOG_PREFIX}.out" 2> "${LOG_PREFIX}.err"
