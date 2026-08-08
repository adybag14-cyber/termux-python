#!/usr/bin/env bash
set -Eeuo pipefail

if [[ $# -lt 2 ]]; then
  echo "usage: $0 ANDROID_TOOL MANIFEST [extra args...]" >&2
  exit 2
fi

tool=$1
shift
manifest=$1
here=$PWD

[[ -x "$tool" ]] || { echo "Android target tool is not executable: $tool" >&2; exit 2; }
[[ -f "$manifest" ]] || { echo "Expected compile-cache manifest as first argument: $manifest" >&2; exit 2; }
command -v docker >/dev/null || { echo "docker is required to execute Android target tools" >&2; exit 2; }

staged_tool=$(mktemp -p "$here" .android-runner-tool.XXXXXX)
staged_manifest=$(mktemp -p "$here" .android-runner-manifest.XXXXXX)
staged_inputs=()
outputs=()

cleanup() {
  rm -f "$staged_tool" "$staged_manifest"
  if ((${#staged_inputs[@]})); then
    rm -f "${staged_inputs[@]}"
  fi
}
trap cleanup EXIT

cp -L "$tool" "$staged_tool"
chmod a+rx "$staged_tool"

index=0
while read -r input output; do
  [[ -n "${input:-}" && -n "${output:-}" ]] || continue
  staged_input="$here/.android-runner-input.$index"
  cp -L "$input" "$staged_input"
  chmod a+r "$staged_input"
  staged_inputs+=("$staged_input")
  outputs+=("$output")

  # Pre-create declared Bazel outputs as the host runner. The Termux image uses
  # its own Android UID, so world-write the files rather than letting the
  # container create root/Android-owned outputs in the Bazel sandbox.
  mkdir -p "$(dirname "$output")"
  : > "$output"
  chmod a+rw "$output"

  printf '%s %s\n' "$staged_input" "$output" >> "$staged_manifest"
  index=$((index + 1))
done < "$manifest"

((${#outputs[@]} > 0)) || { echo "Android target manifest contained no outputs" >&2; exit 2; }
chmod a+r "$staged_manifest"

docker run --rm --platform linux/arm64 \
  -v "$here:$here" -w "$here" \
  termux/termux-docker:aarch64 \
  "$staged_tool" "$staged_manifest"

for output in "${outputs[@]}"; do
  [[ -s "$output" ]] || { echo "Android target tool did not produce $output" >&2; exit 1; }
done