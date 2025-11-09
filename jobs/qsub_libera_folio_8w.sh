#!/bin/sh
#$ -S /bin/sh
#$ -cwd
#$ -V
#$ -q all.q
#$ -pe openmpi8 8
#$ -N libera_folio_8w
#$ -o logs/libera_folio_qsub_20100101_20251108_8w.out
#$ -e logs/libera_folio_qsub_20100101_20251108_8w.err

ulimit -s unlimited
export OMP_NUM_THREADS=8
cd "$SGE_O_WORKDIR" || exit 1
PYTHON_BIN="./.venv/bin/python"
if [ ! -x "$PYTHON_BIN" ]; then
  PYTHON_BIN="$(command -v python3)"
fi
START="2010-01-01"
END="2025-11-08"
ARCHIVE_START="2003-01-01"
ARCHIVE_END="2015-12-31"

OUT_DIR="output/libera_folio_20100101_20251108_parallel_8w"
LOG_PREFIX="logs/libera_folio_parallel_20100101_20251108_8w"
mkdir -p "$OUT_DIR" "$(dirname "$LOG_PREFIX")"

# Backfill legacy years (2003-2015) using archive crawl only.
"$PYTHON_BIN" "Libera Folio/parallel_scraper.py" \
  --start "$ARCHIVE_START" \
  --end "$ARCHIVE_END" \
  --workers 4 \
  --method archive \
  --throttle 0.5 \
  --split-by year \
  --out "$OUT_DIR" \
  > "${LOG_PREFIX}_archive_2003_2015.out" 2> "${LOG_PREFIX}_archive_2003_2015.err"

"$PYTHON_BIN" "Libera Folio/parallel_scraper.py" \
  --start "$START" \
  --end "$END" \
  --workers 8 \
  --method both \
  --throttle 0.5 \
  --split-by year \
  --out "$OUT_DIR" \
  > "${LOG_PREFIX}.out" 2> "${LOG_PREFIX}.err"
