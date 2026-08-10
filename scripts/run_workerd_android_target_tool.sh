#!/usr/bin/env bash
set -Eeuo pipefail

if [[ $# -lt 2 ]]; then
  echo "usage: $0 ANDROID_TOOL MANIFEST [extra args...]" >&2
  exit 2
fi

tool=$1
shift
manifest=$1
shift
extra_args=("$@")
here=$PWD

[[ -x "$tool" ]] || { echo "Android target tool is not executable: $tool" >&2; exit 2; }
[[ -f "$manifest" ]] || { echo "Expected compile-cache manifest as first argument: $manifest" >&2; exit 2; }
command -v docker >/dev/null || { echo "docker is required to execute Android target tools" >&2; exit 2; }

staged_tool=$(mktemp -p "$here" .android-runner-tool.XXXXXX)
staged_manifest=$(mktemp -p "$here" .android-runner-manifest.XXXXXX)
staged_inputs=()
staged_outputs=()
outputs=()

cleanup() {
  rm -f "$staged_tool" "$staged_manifest"
  if ((${#staged_inputs[@]})); then
    rm -f "${staged_inputs[@]}"
  fi
  if ((${#staged_outputs[@]})); then
    rm -f "${staged_outputs[@]}"
  fi
}
trap cleanup EXIT

cp -L "$tool" "$staged_tool"
chmod a+rx "$staged_tool"

index=0
while read -r input output; do
  [[ -n "${input:-}" && -n "${output:-}" ]] || continue
  staged_input="$here/.android-runner-input.$index"
  staged_output="$here/.android-runner-output.$index"
  cp -L "$input" "$staged_input"
  chmod a+r "$staged_input"
  : > "$staged_output"
  chmod a+rw "$staged_output"
  staged_inputs+=("$staged_input")
  staged_outputs+=("$staged_output")
  outputs+=("$output")

  # Keep both sides of the Android action inside the bind-mounted sandbox.
  # Bazel output paths may be symlinks to locations outside this mount, so copy
  # each generated cache back to its declared path only after Android exits.
  printf '%s %s\n' "$staged_input" "$staged_output" >> "$staged_manifest"
  index=$((index + 1))
done < "$manifest"

((${#outputs[@]} > 0)) || { echo "Android target manifest contained no outputs" >&2; exit 2; }
chmod a+r "$staged_manifest"

docker run --rm --platform linux/arm64 \
  -v "$here:$here" -w "$here" \
  termux/termux-docker:aarch64 \
  "$staged_tool" "$staged_manifest" "${extra_args[@]}"

for index in "${!outputs[@]}"; do
  staged_output=${staged_outputs[$index]}
  output=${outputs[$index]}
  [[ -s "$staged_output" ]] || { echo "Android target tool did not produce $output" >&2; exit 1; }
  mkdir -p "$(dirname "$output")"
  cp -f -- "$staged_output" "$output"
done
