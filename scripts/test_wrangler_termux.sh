#!/data/data/com.termux/files/usr/bin/bash
set -Eeuo pipefail

if [[ $# -ne 4 ]]; then
  echo "usage: $0 WRANGLER_DEB WRANGLER_VERSION WORKERD_VERSION ESBUILD_VERSION" >&2
  exit 2
fi

deb=$1
expected=$2
expected_workerd=$3
expected_esbuild=$4
[[ -f "$deb" ]] || { echo "Wrangler package not found: $deb" >&2; exit 1; }

export CI=1
export WRANGLER_SEND_METRICS=false
apt-get update
apt-get install -y --allow-downgrades --no-install-recommends curl "$deb"

[[ -x "$PREFIX/bin/node" ]] || { echo "Termux Node executable missing: $PREFIX/bin/node" >&2; exit 1; }
node_platform=$("$PREFIX/bin/node" -p 'process.platform + ":" + process.arch')
printf 'Node target: %s\n' "$node_platform"
[[ "$node_platform" == "android:arm64" ]] || { echo "Unexpected Termux Node target: $node_platform" >&2; exit 1; }

version_output=$(wrangler --version)
printf '%s\n' "$version_output"
grep -F "$expected" <<<"$version_output"

native_root="$PREFIX/lib/wrangler/native"
esbuild_version=$("$native_root/esbuild" --version)
printf 'esbuild: %s\n' "$esbuild_version"
[[ "$esbuild_version" == "$expected_esbuild" ]]
workerd_version=$("$native_root/workerd" --version 2>&1)
printf '%s\n' "$workerd_version"
grep -F workerd <<<"$workerd_version"
workerd_date=${expected_workerd#1.}
workerd_date=${workerd_date%%.*}
if [[ "$workerd_date" =~ ^([0-9]{4})([0-9]{2})([0-9]{2})$ ]]; then
  expected_workerd_date="${BASH_REMATCH[1]}-${BASH_REMATCH[2]}-${BASH_REMATCH[3]}"
else
  echo "Cannot derive workerd compatibility date from package version: $expected_workerd" >&2
  exit 1
fi
if [[ "$workerd_version" != *"$expected_workerd"* && "$workerd_version" != *"$expected_workerd_date"* ]]; then
  echo "Unexpected workerd version: $workerd_version (expected $expected_workerd or $expected_workerd_date)" >&2
  exit 1
fi


smoke="$HOME/wrangler-termux-smoke"
rm -rf "$smoke"
mkdir -p "$smoke"
cd "$smoke"
cat > index.js <<'JS'
export default {
  fetch() {
    return new Response("termux-wrangler-ok");
  },
};
JS
cat > wrangler.jsonc <<'JSON'
{
  "name": "termux-wrangler-smoke",
  "main": "index.js",
  "compatibility_date": "2026-08-01"
}
JSON

# A dry-run exercises Wrangler's bundling path and therefore the source-built
# Android esbuild binary without needing Cloudflare credentials.
wrangler deploy --dry-run --outdir "$smoke/dry-run"

dev_log="$smoke/wrangler-dev.log"
wrangler dev --ip 127.0.0.1 --port 8791 >"$dev_log" 2>&1 &
pid=$!
cleanup() {
  kill "$pid" 2>/dev/null || true
  wait "$pid" 2>/dev/null || true
}
trap cleanup EXIT

body=""
for _ in $(seq 1 180); do
  if ! kill -0 "$pid" 2>/dev/null; then
    cat "$dev_log" >&2
    exit 1
  fi
  if body=$(curl -fsS --max-time 3 http://127.0.0.1:8791/ 2>/dev/null); then
    break
  fi
  sleep 1
done

if [[ "$body" != "termux-wrangler-ok" ]]; then
  cat "$dev_log" >&2
  echo "Unexpected Wrangler dev response: $body" >&2
  exit 1
fi
printf 'Wrangler local Worker smoke test: %s\n' "$body"