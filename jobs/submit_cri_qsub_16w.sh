#!/bin/sh
set -eu

# Submit the 16-core CRI Esperanto job (segmented legacy + modern).
qsub jobs/qsub_cri_esperanto_16w.sh
echo "Submitted CRI job (16 cores). Use 'qstat' to monitor. Logs in logs/cri_esperanto_qsub_*_16w.out(err)."
