#!/bin/sh
set -eu

# Submit all Esperanto site jobs.
# Most scrapers run with 8 cores, while CRI / Libera Folio use 16 cores.

qsub jobs/qsub_elpopola_8w.sh
qsub jobs/qsub_global_voices_eo_8w.sh
qsub jobs/qsub_monato_8w.sh
qsub jobs/qsub_scivolemo_8w.sh
qsub jobs/qsub_pola_retradio_8w.sh
qsub jobs/qsub_uea_facila_8w.sh

# Libera Folio: archive (<=2015) + modern (2016+) as separate 16-core jobs.
qsub jobs/qsub_libera_folio_archive_16w.sh
qsub jobs/qsub_libera_folio_modern_16w.sh

# CRI Esperanto: segmented 16-core job.
qsub jobs/qsub_cri_esperanto_16w.sh

echo "Submitted all jobs. Use 'qstat' to monitor. Logs in logs/*qsub*."
