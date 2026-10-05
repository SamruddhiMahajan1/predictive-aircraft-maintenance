#!/usr/bin/env bash
# Fetch the NASA C-MAPSS turbofan degradation dataset into backend/data/cmapss.
#
# The four subsets are ~43 MB of plain text and are deliberately NOT committed: they are
# a third-party dataset with an unchanged upstream source, so re-fetching beats carrying
# them in every clone. `make fetch-data` is the only step a new checkout needs before
# `make up` — the API bind-mounts this directory (see docker-compose.yml) and the replay
# engine reads from it.
#
# Usage:
#   scripts/fetch-cmapss.sh                 # fetch every subset into backend/data/cmapss
#   scripts/fetch-cmapss.sh --subset FD001  # one subset only
#   scripts/fetch-cmapss.sh --dir /tmp/cmapss
#
# If you already have the dataset, just copy the *_FD*.txt files into the target
# directory and skip this script.
set -euo pipefail

DEST="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)/backend/data/cmapss"
BASE_URL="https://raw.githubusercontent.com/jasonniebeck/C-MAPSS/master"
SUBSETS=(FD001)
VERBOSE=1

while [[ $# -gt 0 ]]; do
  case "$1" in
    --subset) SUBSETS=("$2"); shift 2 ;;
    --dir)    DEST="$2"; shift 2 ;;
    --quiet)  VERBOSE=0; shift ;;
    -h|--help) sed -n '2,20p' "${BASH_SOURCE[0]}"; exit 0 ;;
    *) echo "unknown argument: $1" >&2; exit 2 ;;
  esac
done

log() { [[ "$VERBOSE" == "1" ]] && echo "[cmapss] $*" || true; }

mkdir -p "$DEST"

failed=()
for subset in "${SUBSETS[@]}"; do
  for kind in train test RUL; do
    file="${kind}_${subset}.txt"
    target="$DEST/$file"

    if [[ -s "$target" ]]; then
      log "have $file"
      continue
    fi

    url="${BASE_URL}/${file}"
    log "fetching $file"
    if command -v curl >/dev/null 2>&1; then
      curl -fsSL --retry 2 --retry-delay 1 -o "$target.part" "$url" 2>/dev/null \
        && mv "$target.part" "$target" || rm -f "$target.part"
    else
      wget -q -O "$target.part" "$url" && mv "$target.part" "$target" \
        || { rm -f "$target.part"; }
    fi

    if [[ ! -s "$target" ]]; then
      rm -f "$target"
      failed+=("$file")
      log "FAILED $file"
    else
      log "ok $file ($(wc -c <"$target" | tr -d ' ') bytes)"
    fi
  done
done

if [[ ${#failed[@]} -gt 0 ]]; then
  cat >&2 <<EOF

[cmapss] ${#failed[@]} file(s) could not be fetched:
  ${failed[*]}

The mirror may be unavailable. C-MAPSS is distributed by NASA at
  https://data.nasa.gov/dataset/cmapss-jet-engine-simulated-data

Proceeding with existing data if present.
EOF
fi

log "ready: $DEST"
log "the replay engine reads ${SUBSETS[*]} (see FDT_ML_DATASET / FDT_REPLAY_SUBSET)"