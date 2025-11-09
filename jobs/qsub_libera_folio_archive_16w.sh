#!/bin/sh
#$ -S /bin/sh
#$ -cwd
#$ -V
#$ -q all.q
#$ -pe openmpi16 16
#$ -N libera_folio_arch_16w
#$ -o logs/libera_folio_qsub_archive_2003_2015_16w.out
#$ -e logs/libera_folio_qsub_archive_2003_2015_16w.err

set -euo pipefail

ulimit -s unlimited
export OMP_NUM_THREADS=16
cd "$SGE_O_WORKDIR" || exit 1

PYTHON_BIN="./.venv/bin/python"
if [ ! -x "$PYTHON_BIN" ]; then
  PYTHON_BIN="$(command -v python3)"
fi

START="2003-01-01"
END="2015-12-31"

OUT_DIR="output/libera_folio_20100101_20251108_parallel_16w"
LOG_PREFIX="logs/libera_folio_parallel_archive_2003_2015_16w"
mkdir -p "$OUT_DIR" "$(dirname "$LOG_PREFIX")"

exec > "${LOG_PREFIX}.out" 2> "${LOG_PREFIX}.err"

echo "[LiberaFolio-archive] Collecting ${START} -> ${END} (archive mode, 16 cores)"

"$PYTHON_BIN" "Libera Folio/parallel_scraper.py" \
  --start "$START" \
  --end "$END" \
  --workers 16 \
  --method archive \
  --throttle 0.5 \
  --split-by year \
  --out "$OUT_DIR"

echo "[LiberaFolio-archive] Completed"
