#!/bin/sh
#$ -S /bin/sh
#$ -cwd
#$ -V
#$ -q all.q
#$ -pe openmpi8 8
#$ -N elpopola_8w
#$ -o logs/elpopola_qsub_20100101_20251108_8w.out
#$ -e logs/elpopola_qsub_20100101_20251108_8w.err

ulimit -s unlimited
export OMP_NUM_THREADS=8
cd "$SGE_O_WORKDIR" || exit 1
PYTHON_BIN="./.venv/bin/python"
if [ ! -x "$PYTHON_BIN" ]; then
  PYTHON_BIN="$(command -v python3)"
fi
START="2010-01-01"
END="2025-11-08"

OUT_DIR="output/elpopola_20100101_20251108_parallel_8w"
LOG_PREFIX="logs/elpopola_parallel_20100101_20251108_8w"
mkdir -p "$OUT_DIR" "$(dirname "$LOG_PREFIX")"

"$PYTHON_BIN" "El Popola Ĉinio/parallel_scraper.py" \
  --start "$START" \
  --end "$END" \
  --workers 8 \
  --throttle 1.0 \
  --max-pages 80 \
  --split-by year \
  --out "$OUT_DIR" \
  > "${LOG_PREFIX}.out" 2> "${LOG_PREFIX}.err"
