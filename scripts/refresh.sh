#!/usr/bin/env bash
set -euo pipefail

# Preferred: set SOURCE_NAME and SOURCE_LANGUAGE.
# Example:
#   SOURCE_NAME="Khan Academy" SOURCE_LANGUAGE=en ./scripts/refresh.sh
#
# Legacy: set CHANNEL_ID to use a raw Kolibri channel ID directly.
# Example:
#   CHANNEL_ID=abc123 ./scripts/refresh.sh

DATA_DIR="${DATA_DIR:-./data}"
KOLIBRI_COMMAND="${KOLIBRI_COMMAND:-kolibri}"

if [[ -n "${SOURCE_NAME:-}" ]]; then
  SOURCE_LANGUAGE="${SOURCE_LANGUAGE:-}"
  VARIANT="${VARIANT:-}"

  ARGS=("curriculum" "sync" "$SOURCE_NAME" "--data-dir" "$DATA_DIR" "--kolibri-command" "$KOLIBRI_COMMAND")
  if [[ -n "$SOURCE_LANGUAGE" ]]; then
    ARGS+=("--language" "$SOURCE_LANGUAGE")
  fi
  if [[ -n "$VARIANT" ]]; then
    ARGS+=("--variant" "$VARIANT")
  fi

  "${ARGS[@]}"

elif [[ -n "${CHANNEL_ID:-}" ]]; then
  echo "Warning: CHANNEL_ID is a legacy option. Prefer SOURCE_NAME + SOURCE_LANGUAGE." >&2
  curriculum sync \
    --channel-id "$CHANNEL_ID" \
    --data-dir "$DATA_DIR" \
    --kolibri-command "$KOLIBRI_COMMAND"

else
  echo "Error: set SOURCE_NAME (and optionally SOURCE_LANGUAGE) or CHANNEL_ID." >&2
  echo "Example: SOURCE_NAME='Khan Academy' SOURCE_LANGUAGE=en ./scripts/refresh.sh" >&2
  exit 1
fi
