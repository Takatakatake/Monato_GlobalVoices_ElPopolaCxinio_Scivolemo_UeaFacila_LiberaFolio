#!/bin/sh
#$ -S /bin/sh
#$ -cwd
#$ -V
#$ -q all.q
#$ -pe openmpi8 8
#$ -N libera_folio_modern_8w
#$ -o logs/libera_folio_qsub_modern_20100101_20251108_8w.out
#$ -e logs/libera_folio_qsub_modern_20100101_20251108_8w.err

ulimit -s unlimited
export OMP_NUM_THREADS=8
cd "$SGE_O_WORKDIR" || exit 1
PYTHON_BIN="./.venv/bin/python"
if [ ! -x "$PYTHON_BIN" ]; then
  PYTHON_BIN="$(command -v python3)"
fi

START="2010-01-01"
END="2025-11-08"

OUT_DIR="output/libera_folio_20100101_20251108_parallel_8w"
LOG_PREFIX="logs/libera_folio_parallel_20100101_20251108_8w_modern"
mkdir -p "$OUT_DIR" "$(dirname "$LOG_PREFIX")"

"$PYTHON_BIN" "Libera Folio/parallel_scraper.py" \
  --start "$START" \
  --end "$END" \
  --workers 8 \
  --method both \
  --throttle 0.5 \
  --split-by year \
  --out "$OUT_DIR" \
  > "${LOG_PREFIX}.out" 2> "${LOG_PREFIX}.err"

