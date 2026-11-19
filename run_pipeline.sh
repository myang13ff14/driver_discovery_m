#!/usr/bin/env bash
# Run the call-driver pipeline end to end, or a range of steps.
#
# Usage: ./run_pipeline.sh [FROM] [TO]
#   FROM, TO  step numbers 1-5 (default 1 5). The figure is drawn whenever step 5 runs.
#
# Examples:
#   ./run_pipeline.sh          # everything (reuse extraction cache if present)
#   ./run_pipeline.sh 2        # reuse step 1's extractions; recluster, rename, rebuild
#   ./run_pipeline.sh 5 5      # rebuild the hierarchy only
#
# Step 1 reuses its cache; other steps overwrite results. Step 3 reads only step 1's output,
# so it is skipped when FROM > 1 and unsupervised/step3_taxonomy/result/taxonomy.json exists.
#
# Environment overrides: WORKERS (step 1 parallel calls, default 16).

set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PY="$ROOT/.venv/bin/python"
FROM="${1:-1}"
TO="${2:-5}"
WORKERS="${WORKERS:-16}"

if ! [[ "$FROM" =~ ^[1-5]$ && "$TO" =~ ^[1-5]$ ]] || (( FROM > TO )); then
    echo "usage: $0 [FROM] [TO]   (1 <= FROM <= TO <= 5)" >&2
    exit 2
fi
[[ -x "$PY" ]] || { echo "missing $PY; see Setup in doc/README.md" >&2; exit 1; }
# Scripts that call the API load .env and validate credentials themselves.

cd "$ROOT"

run() {  # run <label> <command...>
    local label="$1"; shift
    echo
    echo "=== $label ==="
    echo "+ $*"
    local start=$SECONDS
    "$@"
    echo "--- $label done in $(( SECONDS - start ))s"
}

want() { (( FROM <= $1 && $1 <= TO )); }

if want 1; then
    run "Step 1: extraction" "$PY" unsupervised/step1_extraction/extract.py --workers "$WORKERS"
fi

if want 2; then
    run "Step 2: clustering" "$PY" unsupervised/step2_clustering/cluster.py
    run "Step 2: plots" "$PY" unsupervised/step2_clustering/plot.py
    run "Step 2: plots (all clusters)" "$PY" unsupervised/step2_clustering/plot.py --all
fi

if want 3; then
    if (( FROM > 1 )) && [[ -f unsupervised/step3_taxonomy/result/taxonomy.json ]]; then
        echo; echo "=== Step 3: skipped (step 1 unchanged, taxonomy.json exists) ==="
    else
        run "Step 3: reference taxonomy" "$PY" unsupervised/step3_taxonomy/recommend.py
    fi
fi

if want 4; then
    run "Step 4: cluster naming" "$PY" unsupervised/step4_naming/name_clusters.py
fi

if want 5; then
    run "Step 5: hierarchy" "$PY" unsupervised/step5_hierarchy/build_hierarchy.py
    run "Step 5: icicle chart" "$PY" unsupervised/step5_hierarchy/plot_hierarchy.py
    run "Step 5: L2 scatter" "$PY" unsupervised/step5_hierarchy/plot_l2_scatter.py
    # L1_COLORS and EXAMPLES in the figure script are hand-set; new L1 names break it
    run "Figure: pipeline overview" "$PY" unsupervised/figures/pipeline_overview.py ||
        echo "!!! figure failed: update L1_COLORS / EXAMPLES in unsupervised/figures/pipeline_overview.py to match step 5" >&2
fi

echo
echo "Pipeline steps $FROM-$TO finished."
