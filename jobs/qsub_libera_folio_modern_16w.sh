#!/bin/sh
#$ -S /bin/sh
#$ -cwd
#$ -V
#$ -q all.q
#$ -pe openmpi16 16
#$ -N libera_folio_modern_16w
#$ -o logs/libera_folio_qsub_modern_2016_20251108_16w.out
#$ -e logs/libera_folio_qsub_modern_2016_20251108_16w.err

set -euo pipefail

ulimit -s unlimited
export OMP_NUM_THREADS=16
cd "$SGE_O_WORKDIR" || exit 1

PYTHON_BIN="./.venv/bin/python"
if [ ! -x "$PYTHON_BIN" ]; then
  PYTHON_BIN="$(command -v python3)"
fi

START="2016-01-01"
END="2025-11-08"

OUT_DIR="output/libera_folio_20100101_20251108_parallel_16w"
LOG_PREFIX="logs/libera_folio_parallel_modern_2016_20251108_16w"
mkdir -p "$OUT_DIR" "$(dirname "$LOG_PREFIX")"

exec > "${LOG_PREFIX}.out" 2> "${LOG_PREFIX}.err"

echo "[LiberaFolio-modern] Collecting ${START} -> ${END} (both modes, 16 cores)"

"$PYTHON_BIN" "Libera Folio/parallel_scraper.py" \
  --start "$START" \
  --end "$END" \
  --workers 16 \
  --method both \
  --throttle 0.5 \
  --split-by year \
  --out "$OUT_DIR"

echo "[LiberaFolio-modern] Completed"
