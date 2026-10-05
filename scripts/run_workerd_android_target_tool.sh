#!/usr/bin/env bash
set -Eeuo pipefail

fail() {
  echo "$*" >&2
  exit 2
}

if [[ $# -lt 2 ]]; then
  fail "usage: $0 ANDROID_TOOL [--kind module|function] [--v8-flag=FLAG ...] [--eager] MANIFEST"
fi

tool=$1
shift
args=("$@")
here=$PWD
manifest_index=-1
kind_seen=0
eager_seen=0
end_options=0

# workerd's gen-compile-cache accepts options before or after its one positional
# file list. In particular, modern wd_js_bundle.bzl puts --kind and repeated
# --v8-flag=... arguments before it. Keep argv intact and replace only that path.
for ((index = 0; index < ${#args[@]}; index++)); do
  arg=${args[$index]}
  if (( ! end_options )); then
    case "$arg" in
      --kind|--kind=*)
        (( ! kind_seen )) || fail "Duplicate compile-cache --kind"
        kind_seen=1
        if [[ "$arg" == --kind ]]; then
          (( index + 1 < ${#args[@]} )) || fail "Missing compile-cache --kind value"
          index=$((index + 1))
          kind=${args[$index]}
        else
          kind=${arg#--kind=}
        fi
        case "$kind" in
          module|function) ;;
          *) fail "Unsupported compile-cache kind: $kind" ;;
        esac
        continue
        ;;
      --v8-flag)
        (( index + 1 < ${#args[@]} )) || fail "Missing compile-cache --v8-flag value"
        index=$((index + 1))
        [[ -n "${args[$index]}" && "${args[$index]}" != -* ]] || \
          fail "Expected --v8-flag=FLAG for a flag beginning with '-'"
        continue
        ;;
      --v8-flag=*)
        [[ -n "${arg#--v8-flag=}" ]] || fail "Empty compile-cache --v8-flag value"
        continue
        ;;
      --eager)
        (( ! eager_seen )) || fail "Duplicate compile-cache --eager"
        eager_seen=1
        continue
        ;;
      --)
        end_options=1
        continue
        ;;
      -*) fail "Unsupported compile-cache argument: $arg" ;;
    esac
  fi
  (( manifest_index < 0 )) || fail "Expected exactly one compile-cache manifest"
  manifest_index=$index
done

(( manifest_index >= 0 )) || fail "Missing compile-cache manifest"
manifest=${args[$manifest_index]}
[[ -x "$tool" ]] || fail "Android target tool is not executable: $tool"
[[ -f "$manifest" ]] || fail "Expected compile-cache manifest file: $manifest"
command -v docker >/dev/null || fail "docker is required to execute Android target tools"

# One unique directory prevents concurrent actions from sharing staged paths and
# lets the EXIT trap clean up even when a staging command or the target fails.
staging_dir=
cleanup() {
  if [[ -n "$staging_dir" ]]; then
    rm -rf -- "$staging_dir"
  fi
}
trap cleanup EXIT
staging_dir=$(mktemp -d .android-runner.XXXXXX)
chmod a+rx "$staging_dir"
staged_tool="$staging_dir/tool"
staged_manifest="$staging_dir/manifest"
outputs=()
staged_outputs=()

cp -L -- "$tool" "$staged_tool"
chmod a+rx "$staged_tool"
: > "$staged_manifest"
args[$manifest_index]=$staged_manifest

index=0
line_number=0
manifest_line_pattern='^([^[:space:]]+) ([^[:space:]]+)$'
while IFS= read -r line || [[ -n "$line" ]]; do
  line_number=$((line_number + 1))
  [[ -n "$line" ]] || continue
  [[ "$line" =~ $manifest_line_pattern ]] || \
    fail "Malformed compile-cache manifest line $line_number: expected INPUT OUTPUT"
  input=${BASH_REMATCH[1]}
  output=${BASH_REMATCH[2]}
  staged_input="$staging_dir/input.$index"
  staged_output="$staging_dir/output.$index"
  cp -L -- "$input" "$staged_input"
  chmod a+r "$staged_input"
  : > "$staged_output"
  chmod a+rw "$staged_output"
  staged_outputs+=("$staged_output")
  outputs+=("$output")

  # Keep both sides of the Android action inside the bind-mounted sandbox.
  # Bazel output paths may be symlinks to locations outside this mount, so copy
  # each generated cache back to its declared path only after Android exits.
  # Relative staged paths also keep spaces in the sandbox path out of the file
  # list, whose upstream format is exactly two space-separated paths per line.
  printf '%s %s\n' "$staged_input" "$staged_output" >> "$staged_manifest"
  index=$((index + 1))
done < "$manifest"

((${#outputs[@]} > 0)) || fail "Android target manifest contained no outputs"
chmod a+r "$staged_manifest"

docker run --rm --platform linux/arm64 \
  -v "$here:$here" -w "$here" \
  termux/termux-docker:aarch64 \
  "$staged_tool" "${args[@]}"

# Validate every cache before publishing any output from this action.
for index in "${!outputs[@]}"; do
  [[ -s "${staged_outputs[$index]}" ]] || {
    echo "Android target tool did not produce ${outputs[$index]}" >&2
    exit 1
  }
done
for index in "${!outputs[@]}"; do
  output=${outputs[$index]}
  mkdir -p -- "$(dirname -- "$output")"
  cp -f -- "${staged_outputs[$index]}" "$output"
done
