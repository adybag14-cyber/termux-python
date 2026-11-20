#!/usr/bin/env bash
set -euo pipefail

image=${1:?Docker image is required}
for attempt in 1 2 3; do
  if timeout -k 15s 240s docker pull "$image"; then
    exit 0
  fi
  if (( attempt < 3 )); then
    echo "Docker pull failed on attempt $attempt of 3. Retrying $image." >&2
    sleep "$((attempt * 5))"
  fi
done
exit 1
