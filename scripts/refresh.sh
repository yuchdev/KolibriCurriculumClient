#!/usr/bin/env bash
set -euo pipefail

: "${CHANNEL_ID:?Set CHANNEL_ID to the Kolibri channel ID}"
DATA_DIR="${DATA_DIR:-./data}"
KOLIBRI_COMMAND="${KOLIBRI_COMMAND:-kolibri}"

kcurriculum sync \
  --channel-id "$CHANNEL_ID" \
  --data-dir "$DATA_DIR" \
  --kolibri-command "$KOLIBRI_COMMAND"
